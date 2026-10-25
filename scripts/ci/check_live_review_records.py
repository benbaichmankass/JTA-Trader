#!/usr/bin/env python3
"""live-review-records-guard -- validates comms/live_review/{reviews,outcomes}.jsonl.

LTR-2-RECORDS (design docs/plans/live-trade-review-DESIGN.md sections 3, 5, 8). Every row
must satisfy comms/schema/live_review.schema.json. The rules the schema cannot say on its own:

* an unmeasured value is null, never 0 (collapsed-state rule): `peak_provenance` of
  "unverified" or "fabricated" with a numeric `peak_r` of exactly 0 is refused, and an option
  with n == 0 must carry null mean/sd/worst;
* operator Q1: the applied bound is 0.25R and the shadow arm is 0.5R, on EVERY review; an
  `auto_applied` route requires `applied` true and an apply tighten within the 0.25R bound;
* `applied` must agree with `disposition.route` (auto_applied <=> applied);
* review_id unique; an outcome must name a review_id present in reviews.jsonl;
* LTR-3 (settled 2026-10-25): `insufficient_n` means NO recommendation, never hold -- basis
  `insufficient_n` requires action `no_recommendation`; `no_recommendation` never routes to an
  apply; and `account_reads` (one read per account carrying the package -- the review is
  package-level, each account applies through its own risk layer) names each account once.

Canonical source: trade_journal.db order_packages / trades, joined on `order_package_id`.
Files are append-only and start empty; a leading {"_meta": ...} line is skipped.

Exit: 0 clean / 1 refused.   Usage: check_live_review_records.py [--self-test]
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "comms/schema/live_review.schema.json"
REVIEWS = REPO / "comms/live_review/reviews.jsonl"
OUTCOMES = REPO / "comms/live_review/outcomes.jsonl"
PACKETS = REPO / "comms/live_review/packets"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _type_ok(v, t: str) -> bool:
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "integer": isinstance(v, int) and not isinstance(v, bool), "number": _is_num(v),
            "boolean": isinstance(v, bool), "null": v is None}[t]


def _check(v, spec: dict, enums: dict, path: str, out: list) -> None:
    t = spec.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_type_ok(v, x) for x in ts):
            out.append(f"{path}: expected {'|'.join(ts)}, got {type(v).__name__}")
            return
    if v is None:
        return
    allowed = spec.get("enum") or (enums[spec["enum_ref"]] if "enum_ref" in spec else None)
    if allowed is not None and v not in allowed:
        out.append(f"{path}: {v!r} not in {allowed}")
    if isinstance(v, str):
        if "minLength" in spec and len(v) < spec["minLength"]:
            out.append(f"{path}: empty string")
        if "pattern" in spec and not re.search(spec["pattern"], v):
            out.append(f"{path}: {v!r} does not match {spec['pattern']}")
    if _is_num(v):
        if "minimum" in spec and v < spec["minimum"]:
            out.append(f"{path}: {v} < {spec['minimum']}")
        if "maximum" in spec and v > spec["maximum"]:
            out.append(f"{path}: {v} > {spec['maximum']}")
    if isinstance(v, dict):
        props = spec.get("properties", {})
        for k in spec.get("required", []):
            if k not in v:
                out.append(f"{path}.{k}: missing")
        for k, x in v.items():
            if k in props:
                _check(x, props[k], enums, f"{path}.{k}", out)
            elif "values" in spec:
                _check(x, spec["values"], enums, f"{path}.{k}", out)
            elif spec.get("additionalProperties") is False:
                out.append(f"{path}.{k}: unexpected field")
    if isinstance(v, list) and "items" in spec:
        for i, x in enumerate(v):
            _check(x, spec["items"], enums, f"{path}[{i}]", out)


def row_problems(row: dict, kind: str, schema: dict) -> list[str]:
    out: list[str] = []
    _check(row, schema[kind], schema["enums"], kind, out)
    if out or kind != "reviews":
        return out
    st, ap, sh, rec, disp = row["state"], row["apply_policy"], row["shadow_policy"], row["recommendation"], row["disposition"]
    if st["peak_provenance"] in ("unverified", "fabricated") and st["peak_r"] == 0:
        out.append("state.peak_r: 0 with unverified/fabricated provenance (unmeasured must be null)")
    for i, o in enumerate(row["options"]):
        if o["n"] == 0 and any(o[k] is not None for k in ("mean_r", "sd_r", "worst_r")):
            out.append(f"options[{i}]: n == 0 but numbers present (must be null)")
    if (disp["route"] == "auto_applied") != row["applied"]:
        out.append("applied disagrees with disposition.route (auto_applied <=> applied)")
    if disp["route"] == "auto_applied" and ap["within_bound"] is not True:
        out.append("auto_applied outside the 0.25R apply bound")
    if (ap["tighten_r"] is not None and ap["within_bound"] is not None
            and ap["within_bound"] != (ap["tighten_r"] <= ap["bound_r"])):
        out.append("apply_policy.within_bound contradicts tighten_r vs 0.25R")
    if (sh["tighten_r"] is not None and sh["within_bound"] is not None
            and sh["within_bound"] != (sh["tighten_r"] <= sh["bound_r"])):
        out.append("shadow_policy.within_bound contradicts tighten_r vs 0.5R")
    if rec["action"] == "tighten_sl" and (ap["tighten_r"] is None or sh["tighten_r"] is None):
        out.append("tighten_sl recommendation must record tighten_r on both the apply and shadow arms")
    if rec["basis"] == "insufficient_n" and rec["action"] != "no_recommendation":
        out.append("basis insufficient_n requires action no_recommendation (insufficient_n is never hold)")
    if rec["action"] == "no_recommendation" and (row["applied"] or disp["route"] == "auto_applied"):
        out.append("no_recommendation cannot be applied")
    accts = [a["account_id"] for a in row["account_reads"]]
    if len(accts) != len(set(accts)):
        out.append("account_reads names an account more than once")
    if set(accts) != set(row["accounts"]):
        out.append("account_reads must cover exactly the accounts in `accounts`")
    return out


def packet_problems(row: dict, packets: Path) -> list[str]:
    """A recorded packet_sha must be the sha256 of the committed decision packet
    (canonical JSON: sort_keys, compact) -- the join from a decision to exactly what was seen."""
    sha = row.get("packet_sha")
    if not sha:
        return []
    f = packets / f"{row.get('review_id')}.json"
    if not f.exists():
        return [f"packet_sha set but {f.name} is missing from comms/live_review/packets/"]
    got = hashlib.sha256(json.dumps(json.loads(f.read_text()), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return [] if got == sha else [f"packet_sha does not match {f.name}"]


def _rows(path: Path):
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError as e:
            yield n, None, f"invalid JSON ({e})"
            continue
        if isinstance(r, dict) and "_meta" in r and len(r) == 1:
            continue
        yield n, r, None


def findings(reviews: Path = REVIEWS, outcomes: Path = OUTCOMES, schema_path: Path = SCHEMA) -> list[str]:
    schema = json.loads(schema_path.read_text())
    out: list[str] = []
    ids: set[str] = set()
    for kind, p in (("reviews", reviews), ("outcomes", outcomes)):
        if not p.exists():
            out.append(f"{p.name}: file missing")
            continue
        for n, r, err in _rows(p):
            tag = f"{p.name}:{n}"
            if err or not isinstance(r, dict):
                out.append(f"{tag}: {err or 'not an object'}")
                continue
            out += [f"{tag}: {m}" for m in row_problems(r, kind, schema)]
            if kind == "reviews":
                out += [f"{tag}: {m}" for m in packet_problems(r, PACKETS)]
                if r.get("review_id") in ids:
                    out.append(f"{tag}: duplicate review_id {r.get('review_id')}")
                ids.add(r.get("review_id"))
    if outcomes.exists():
        for n, r, err in _rows(outcomes):
            if isinstance(r, dict) and r.get("review_id") not in ids:
                out.append(f"{outcomes.name}:{n}: review_id {r.get('review_id')} has no row in reviews")
    return out


GOOD_REVIEW = {
    "schema_version": 1, "review_id": "LR-20261025T1404Z-pkg-1", "reviewed_at": "2026-10-25T14:04:00Z",
    "order_package_id": "pkg-1", "trade_id": 1, "leg": "example_leg", "accounts": ["acct_a"],
    "trigger": {"event": "r_milestone", "level": 3, "l0_snapshot_at": None},
    "info_cutoff_at": "2026-10-25T14:00:00Z",
    "state": {"open_r": 3.4, "peak_r": 3.5, "peak_provenance": "estimated", "giveback_r": 0.1, "bars_held": 17,
              "sl": 1.0, "tp": 2.0, "atr_now_over_entry": 1.0, "regime_cell_now": None, "regime_cell_entry": None},
    "features_at_review": {"open_r": 3.4, "peak_r": 3.5, "correlated_open": None},
    "mechanics": {"verdict": "match", "evidence": "example"},
    "options": [{"action": "hold", "level": None, "n": 32, "mean_r": 3.1, "sd_r": 1.3, "worst_r": 0.2, "net": True}],
    "outcome_table_source": None,
    "recommendation": {"action": "tighten_sl", "level": 1.1, "level_atr": 1.5, "ev_delta_r": -0.2,
                       "worst_case_delta_r": 2.0, "basis": "preference_within_bound", "confidence": "measured"},
    "judge_prior": 0.6, "applied": False,
    "apply_policy": {"bound_r": 0.25, "within_bound": False, "tighten_r": 0.4},
    "shadow_policy": {"bound_r": 0.5, "within_bound": True, "would_apply": True, "tighten_r": 0.4},
    "context_flags": [],
    "account_reads": [{"account_id": "acct_a", "account_class": "real_money", "read": "would_apply", "evidence": "example"}],
    "disposition": {"route": "recommended", "mandate": None, "action_issue": None,
                                         "applied_at": None, "verified_readback": None},
    "model": "m", "session": "session_x", "prompt_sha": None, "skill_sha": None,
}
GOOD_OUTCOME = {
    "schema_version": 1, "review_id": "LR-20261025T1404Z-pkg-1", "order_package_id": "pkg-1", "trade_id": 1,
    "closed_at": "2026-10-25T20:00:00Z", "computed_at": "2026-10-26T00:00:00Z", "net_r": 3.0,
    "pnl_provenance": "measured", "cf_r": 3.2, "cf_r_shadow_0_5": None, "cf_method": "monitor_replay_v1",
    "cf_provenance": "computed", "exit_reason": "sl_hit",
}


def _self_test() -> int:
    import tempfile
    schema = json.loads(SCHEMA.read_text())
    ok = True

    def mut(base, fn):
        r = copy.deepcopy(base)
        fn(r)
        return r

    def expect(label, row, kind, bad):
        nonlocal ok
        got = bool(row_problems(row, kind, schema))
        good = got == bad
        print(f"  {'PASS' if good else 'FAIL'}  {label}")
        ok &= good

    expect("a well-formed review passes", GOOD_REVIEW, "reviews", False)
    expect("a well-formed outcome passes", GOOD_OUTCOME, "outcomes", False)
    expect("missing shadow_policy is refused", mut(GOOD_REVIEW, lambda r: r.pop("shadow_policy")), "reviews", True)
    expect("apply bound other than 0.25 is refused", mut(GOOD_REVIEW, lambda r: r["apply_policy"].update(bound_r=0.5)), "reviews", True)
    expect("prose action is refused", mut(GOOD_REVIEW, lambda r: r["recommendation"].update(action="move it up a bit")), "reviews", True)
    expect("zero peak with unverified provenance is refused",
           mut(GOOD_REVIEW, lambda r: r["state"].update(peak_r=0, peak_provenance="unverified")), "reviews", True)
    expect("n == 0 option with numbers is refused",
           mut(GOOD_REVIEW, lambda r: r["options"][0].update(n=0)), "reviews", True)
    expect("auto_applied beyond 0.25R is refused",
           mut(GOOD_REVIEW, lambda r: (r["disposition"].update(route="auto_applied"), r.update(applied=True))), "reviews", True)
    expect("insufficient_n written as hold is refused",
           mut(GOOD_REVIEW, lambda r: r["recommendation"].update(action="hold", basis="insufficient_n")), "reviews", True)
    expect("insufficient_n as no_recommendation passes",
           mut(GOOD_REVIEW, lambda r: (r["recommendation"].update(action="no_recommendation", basis="insufficient_n"),
                                       r["apply_policy"].update(within_bound=None, tighten_r=None),
                                       r["shadow_policy"].update(within_bound=None, would_apply=None, tighten_r=None))), "reviews", False)
    expect("missing account_reads is refused", mut(GOOD_REVIEW, lambda r: r.pop("account_reads")), "reviews", True)
    expect("an account read outside the enum is refused",
           mut(GOOD_REVIEW, lambda r: r["account_reads"][0].update(read="approved")), "reviews", True)
    expect("account_reads not covering `accounts` is refused",
           mut(GOOD_REVIEW, lambda r: r["accounts"].append("acct_b")), "reviews", True)
    expect("outcome with a non-computed cf is refused", mut(GOOD_OUTCOME, lambda r: r.update(cf_provenance="declared")), "outcomes", True)
    with tempfile.TemporaryDirectory() as d:
        rv, oc = Path(d) / "reviews.jsonl", Path(d) / "outcomes.jsonl"
        rv.write_text(json.dumps(GOOD_REVIEW) + "\n")
        oc.write_text(json.dumps(mut(GOOD_OUTCOME, lambda r: r.update(review_id="LR-20261025T1404Z-nope"))) + "\n")
        c = bool(findings(rv, oc))
        print(f"  {'PASS' if c else 'FAIL'}  an orphan outcome is refused")
        ok &= c
        oc.write_text(json.dumps(GOOD_OUTCOME) + "\n")
        c = not findings(rv, oc)
        print(f"  {'PASS' if c else 'FAIL'}  a consistent pair passes")
        ok &= c
        pk = Path(d) / "packets"
        pk.mkdir()
        (pk / f"{GOOD_REVIEW['review_id']}.json").write_text(json.dumps({"a": 1}))
        good_sha = hashlib.sha256(b'{"a":1}').hexdigest()
        c = not packet_problems(mut(GOOD_REVIEW, lambda r: r.update(packet_sha=good_sha)), pk)
        print(f"  {'PASS' if c else 'FAIL'}  a packet_sha matching its packet passes")
        ok &= c
        c = bool(packet_problems(mut(GOOD_REVIEW, lambda r: r.update(packet_sha="0" * 64)), pk))
        print(f"  {'PASS' if c else 'FAIL'}  a packet_sha not matching its packet is refused")
        ok &= c
        rv.write_text("not json\n")
        c = bool(findings(rv, oc))
        print(f"  {'PASS' if c else 'FAIL'}  a bad line is refused")
        ok &= c
    print("live-review-records-guard self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    f = findings()
    if f:
        print("::error::comms/live_review records fail comms/schema/live_review.schema.json:")
        for x in f:
            print(f"  ✗ {x}")
        return 1
    print("live-review-records-guard: reviews.jsonl and outcomes.jsonl are schema-valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
