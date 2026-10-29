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
* LTR-JUDGEMENT-APPLY (operator 2026-10-26, popup verbatim "Claude's judgement applies
  (Recommended)"): when the LTR-0 cell is thin the reviewer's call stands as basis `judgement`.
  A `judgement` row carries `evidence_source: judgement`, a `judgement_confidence` in [0, 1] and
  a `reason`, and is exempt from the table-only 0.25R / tighten_r clauses (there is no table EV
  to bound); a `tighten_sl` row names its `evidence_source`; an `auto_applied` row needs
  `mechanics.verdict == match`. `insufficient_n` + `no_recommendation` stays valid (the
  reviewer may decline to make a call), and is still never hold.
* trigger (operator 2026-10-26, GLD re-reviewed ten times): from 2026-10-27 a row whose trigger names a due
  event carries that event's level (a string for mechanics/swing/...), and `manual` carries none.
* the `review_id` ends with the row's own `order_package_id` (a row whose id names another package is
  a corrupted write).
* LTR-ALL-ACTIONS (operator 2026-10-26, MD-TRADE-DESK, verbatim "as long as they have
  reasoning and confidence attached"): a trade action (close / partial_close / move_tp /
  widen_sl / change_size / add_entry) carries a non-empty `reason`, an `evidence_source` of
  `table` (with `ev_delta_r`) or `judgement` (with `judgement_confidence`), and its own target --
  move_tp / widen_sl a `level`, partial_close a `size_fraction` in (0, 1), change_size a
  `size_multiplier` > 0 and != 1, add_entry a `size_fraction` > 0 -- and no target it does not
  use. A trade action that names no target is refused: there is nothing to apply or to grade.

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


#: Manager 2026-10-26 ~12:37Z (finding #20322): every real-money review that day
#: ended no_recommendation + insufficient_n, so the operator's 06:30Z "Claude's
#: judgement applies" produced no graded calls. From this instant a real-money or
#: prop row must carry a call (hold / tighten_sl, judgement-backed on a thin cell);
#: earlier rows are history and are not re-graded.
MONEY_CLASSES = ("real_money", "prop")
MONEY_CALL_RULE_FROM = "2026-10-26T12:40:00Z"


def money_call_problems(row: dict) -> list[str]:
    """The no-silent-escape rule for real-money / prop rows (empty for paper or older rows)."""
    money = any(str((a or {}).get("account_class") or "").lower() in MONEY_CLASSES
                for a in row.get("account_reads") or [])
    if not money or str(row.get("reviewed_at") or "") < MONEY_CALL_RULE_FROM:
        return []
    rec = row.get("recommendation") or {}
    basis, action = rec.get("basis"), rec.get("action")
    reason = str(rec.get("reason") or "").strip()
    out = []
    if basis in ("insufficient_n", "default_hold"):
        out.append(f"real-money/prop row: basis {basis} is refused; make a call (hold / tighten_sl with "
                   "basis judgement + judgement_confidence + reason) or record could_not_look")
    if action == "no_recommendation" and not (basis == "could_not_look" and reason):
        out.append("real-money/prop row: no_recommendation requires basis could_not_look and a reason")
    if action == "hold" and basis not in ("ev_positive", "judgement"):
        out.append("real-money/prop row: hold requires basis ev_positive (measured cell) or judgement")
    return out


#: LTR-ALL-ACTIONS (MD-TRADE-DESK, operator 2026-10-26): the trade actions beyond a tighten.
#: ``tp_revise`` stays the legacy (operator-ask) spelling and is not graded here as a trade action.
TRADE_ACTIONS = ("close", "partial_close", "move_tp", "widen_sl", "change_size", "add_entry")
_TARGETS = {"close": (), "partial_close": ("size_fraction",), "move_tp": ("level",), "widen_sl": ("level",),
            "change_size": ("size_multiplier",), "add_entry": ("size_fraction",)}


def trade_action_problems(rec: dict) -> list[str]:
    """Reason + confidence (or table basis) + the action's own target, for every trade action."""
    act = rec.get("action")
    if act not in TRADE_ACTIONS:
        return [f"{k} is set but {act} takes no {k}" for k in ("size_fraction", "size_multiplier")
                if rec.get(k) is not None]
    out = []
    if not str(rec.get("reason") or "").strip():
        out.append(f"{act} requires a reason (operator: reasoning and confidence attached)")
    src = rec.get("evidence_source")
    if src == "judgement":
        if not _is_num(rec.get("judgement_confidence")):
            out.append(f"{act} on judgement requires a judgement_confidence in [0, 1]")
    elif src == "table":
        if not _is_num(rec.get("ev_delta_r")):
            out.append(f"{act} on a table basis requires ev_delta_r")
    else:
        out.append(f"{act} requires evidence_source table or judgement (got {src!r})")
    want = _TARGETS[act]
    for k in ("level", "size_fraction", "size_multiplier"):
        v = rec.get(k)
        if k in want:
            if not _is_num(v) or v <= 0:
                out.append(f"{act} requires {k} > 0")
        elif v is not None and k != "level":
            out.append(f"{k} is set but {act} takes no {k}")
    sf, sm = rec.get("size_fraction"), rec.get("size_multiplier")
    if act == "partial_close" and _is_num(sf) and not 0 < sf < 1:
        out.append("partial_close size_fraction must be in (0, 1) (a full exit is close)")
    if act == "change_size" and _is_num(sm) and sm == 1:
        out.append("change_size size_multiplier 1 changes nothing")
    if act == "close" and rec.get("level") is not None:
        out.append("close takes no level (it exits at market)")
    return out


#: Operator 2026-10-26 (a wedged GLD package was re-reviewed ten times): the due dedupe keys on
#: the trigger's (event, level), so a row that answers a due event must carry the level the due
#: packet gave. Earlier rows are history (they carry a null level and the due side infers it).
DUE_EVENTS = ("r_milestone", "new_peak", "giveback", "near_target", "daily_floor",
              "swing", "vol_regime", "funding", "calendar", "mechanics",
              "adverse_r", "stall", "momentum_flip", "structure_break", "mandate_cadence")
TRIGGER_LEVEL_RULE_FROM = "2026-10-27T00:00:00Z"


def trigger_problems(row: dict) -> list[str]:
    if str(row.get("reviewed_at") or "") < TRIGGER_LEVEL_RULE_FROM:
        return []
    trig = row.get("trigger") or {}
    event, level = trig.get("event"), trig.get("level")
    if event in DUE_EVENTS and level is None:
        return [f"trigger.event {event} names a due event but no level (copy event AND level from the wake entry)"]
    if event == "mechanics" and not isinstance(level, str):
        return ["trigger.event mechanics needs its string level (venue_sl_diverges / journal_trade_absent)"]
    if event == "manual" and level is not None:
        return ["trigger.event manual takes no level (a level means this answers a due event: name that event)"]
    return []


def row_problems(row: dict, kind: str, schema: dict) -> list[str]:
    out: list[str] = []
    _check(row, schema[kind], schema["enums"], kind, out)
    if out or kind != "reviews":
        return out
    # 2026-10-26: LR-...-pkg-6a8e... was written carrying pkg-465a...'s body; the id must name its own package.
    if not str(row["review_id"]).endswith("-" + str(row["order_package_id"])):
        out.append(f"review_id {row['review_id']} does not end with its order_package_id {row['order_package_id']}")
    st, ap, sh, rec, disp = row["state"], row["apply_policy"], row["shadow_policy"], row["recommendation"], row["disposition"]
    if st["peak_provenance"] in ("unverified", "fabricated") and st["peak_r"] == 0:
        out.append("state.peak_r: 0 with unverified/fabricated provenance (unmeasured must be null)")
    for i, o in enumerate(row["options"]):
        if o["n"] == 0 and any(o[k] is not None for k in ("mean_r", "sd_r", "worst_r")):
            out.append(f"options[{i}]: n == 0 but numbers present (must be null)")
    if (disp["route"] == "auto_applied") != row["applied"]:
        out.append("applied disagrees with disposition.route (auto_applied <=> applied)")
    judged = rec["basis"] == "judgement"
    if disp["route"] == "auto_applied" and ap["within_bound"] is not True and not judged:
        out.append("auto_applied outside the 0.25R apply bound")
    if disp["route"] == "auto_applied" and row["mechanics"].get("verdict") != "match":
        out.append("auto_applied requires mechanics.verdict == match")
    if (ap["tighten_r"] is not None and ap["within_bound"] is not None
            and ap["within_bound"] != (ap["tighten_r"] <= ap["bound_r"])):
        out.append("apply_policy.within_bound contradicts tighten_r vs 0.25R")
    if (sh["tighten_r"] is not None and sh["within_bound"] is not None
            and sh["within_bound"] != (sh["tighten_r"] <= sh["bound_r"])):
        out.append("shadow_policy.within_bound contradicts tighten_r vs 0.5R")
    if rec["action"] == "tighten_sl" and not judged and (ap["tighten_r"] is None or sh["tighten_r"] is None):
        out.append("tighten_sl recommendation must record tighten_r on both the apply and shadow arms")
    if rec["basis"] == "insufficient_n" and rec["action"] != "no_recommendation":
        out.append("basis insufficient_n requires action no_recommendation (insufficient_n is never hold)")
    if rec["action"] == "no_recommendation" and (row["applied"] or disp["route"] == "auto_applied"):
        out.append("no_recommendation cannot be applied")
    src = rec.get("evidence_source")
    if rec["action"] == "tighten_sl" and src is None:
        out.append("tighten_sl must name recommendation.evidence_source (table | judgement)")
    if judged:
        if src != "judgement":
            out.append("basis judgement requires evidence_source judgement")
        if not _is_num(rec.get("judgement_confidence")):
            out.append("basis judgement requires a judgement_confidence in [0, 1]")
        if not str(rec.get("reason") or "").strip():
            out.append("basis judgement requires a reason")
    elif src == "judgement":
        out.append("evidence_source judgement requires basis judgement")
    if src == "table" and rec["basis"] == "insufficient_n":
        out.append("evidence_source table contradicts basis insufficient_n")
    if rec["basis"] == "could_not_look" and not str(rec.get("reason") or "").strip():
        out.append("basis could_not_look requires a reason")
    out += trade_action_problems(rec)
    out += money_call_problems(row)
    out += trigger_problems(row)
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
    return packet_blob_problems(row, f.read_bytes())


def packet_blob_problems(row: dict, blob: bytes) -> list[str]:
    """packet_sha against the packet's bytes (the mirror reads them from the rows branch)."""
    sha = row.get("packet_sha")
    if not sha:
        return []
    try:
        got = hashlib.sha256(json.dumps(json.loads(blob), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except ValueError:
        return [f"packet for {row.get('review_id')} is not JSON"]
    return [] if got == sha else [f"packet_sha does not match {row.get('review_id')}.json"]


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
                       "worst_case_delta_r": 2.0, "basis": "preference_within_bound", "confidence": "measured",
                       "evidence_source": "table"},
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
           mut(GOOD_REVIEW, lambda r: (r["recommendation"].update(action="no_recommendation", basis="insufficient_n",
                                                                  evidence_source="none"),
                                       r["apply_policy"].update(within_bound=None, tighten_r=None),
                                       r["shadow_policy"].update(within_bound=None, would_apply=None, tighten_r=None))), "reviews", False)
    def judged(r):
        r["recommendation"].update(basis="judgement", evidence_source="judgement", confidence="anecdote",
                                   judgement_confidence=0.6, reason="stalled at swing high",
                                   ev_delta_r=None, worst_case_delta_r=None)
        r["apply_policy"].update(within_bound=None, tighten_r=None)
        r["shadow_policy"].update(within_bound=None, would_apply=None, tighten_r=None)
        r["disposition"].update(route="auto_applied", mandate="MD-LIVE-TIGHTEN-SL")
        r.update(applied=True)
    expect("a judgement-basis applied tighten passes", mut(GOOD_REVIEW, judged), "reviews", False)
    expect("judgement without a confidence is refused",
           mut(GOOD_REVIEW, lambda r: (judged(r), r["recommendation"].pop("judgement_confidence"))), "reviews", True)
    expect("judgement confidence above 1 is refused",
           mut(GOOD_REVIEW, lambda r: (judged(r), r["recommendation"].update(judgement_confidence=1.4))), "reviews", True)
    expect("judgement without a reason is refused",
           mut(GOOD_REVIEW, lambda r: (judged(r), r["recommendation"].update(reason=""))), "reviews", True)
    expect("judgement applied on a mechanics mismatch is refused",
           mut(GOOD_REVIEW, lambda r: (judged(r), r["mechanics"].update(verdict="mismatch"))), "reviews", True)
    expect("tighten_sl without evidence_source is refused",
           mut(GOOD_REVIEW, lambda r: r["recommendation"].pop("evidence_source")), "reviews", True)
    expect("table basis applied outside 0.25R is still refused (table path unchanged)",
           mut(GOOD_REVIEW, lambda r: (r["disposition"].update(route="auto_applied"), r.update(applied=True))), "reviews", True)
    def action(act, **kw):
        def f(r):
            judged(r)
            r["recommendation"].update({"action": act, "level": None, **kw})
        return f
    expect("close with reason + confidence passes", mut(GOOD_REVIEW, action("close")), "reviews", False)
    expect("close without a reason is refused",
           mut(GOOD_REVIEW, lambda r: (action("close")(r), r["recommendation"].update(reason=" "))), "reviews", True)
    expect("close without a confidence is refused",
           mut(GOOD_REVIEW, lambda r: (action("close")(r), r["recommendation"].pop("judgement_confidence"))), "reviews", True)
    expect("close with no evidence_source is refused",
           mut(GOOD_REVIEW, lambda r: (action("close")(r), r["recommendation"].update(evidence_source="none"))), "reviews", True)
    expect("partial_close 0.5 passes", mut(GOOD_REVIEW, action("partial_close", size_fraction=0.5)), "reviews", False)
    expect("partial_close of 1.0 is refused (that is close)",
           mut(GOOD_REVIEW, action("partial_close", size_fraction=1.0)), "reviews", True)
    expect("partial_close without a size is refused", mut(GOOD_REVIEW, action("partial_close")), "reviews", True)
    expect("move_tp with a level passes", mut(GOOD_REVIEW, action("move_tp", level=2.5)), "reviews", False)
    expect("move_tp without a level is refused", mut(GOOD_REVIEW, action("move_tp")), "reviews", True)
    expect("widen_sl with a level passes", mut(GOOD_REVIEW, action("widen_sl", level=0.9)), "reviews", False)
    expect("change_size 0.5 passes", mut(GOOD_REVIEW, action("change_size", size_multiplier=0.5)), "reviews", False)
    expect("change_size 1.0 is refused", mut(GOOD_REVIEW, action("change_size", size_multiplier=1.0)), "reviews", True)
    expect("add_entry 0.5 passes", mut(GOOD_REVIEW, action("add_entry", size_fraction=0.5)), "reviews", False)
    expect("add_entry with a size_multiplier is refused",
           mut(GOOD_REVIEW, action("add_entry", size_fraction=0.5, size_multiplier=1.5)), "reviews", True)
    expect("a size_fraction on a tighten is refused",
           mut(GOOD_REVIEW, lambda r: r["recommendation"].update(size_fraction=0.5)), "reviews", True)
    expect("a table-basis close needs ev_delta_r",
           mut(GOOD_REVIEW, lambda r: r["recommendation"].update(action="close", level=None, reason="x",
                                                                 evidence_source="table", ev_delta_r=None)), "reviews", True)
    expect("a table-basis close with ev_delta_r passes",
           mut(GOOD_REVIEW, lambda r: r["recommendation"].update(action="close", level=None, reason="x",
                                                                 evidence_source="table", ev_delta_r=0.3)), "reviews", False)
    def trig(event, level, at="2026-10-27T01:00:00Z"):
        return lambda r: (r["trigger"].update(event=event, level=level), r.update(reviewed_at=at))
    expect("a due event with no level is refused", mut(GOOD_REVIEW, trig("mechanics", None)), "reviews", True)
    expect("a mechanics event with its string level passes",
           mut(GOOD_REVIEW, trig("mechanics", "venue_sl_diverges")), "reviews", False)
    expect("a swing event with no level is refused", mut(GOOD_REVIEW, trig("swing", None)), "reviews", True)
    expect("a manual row naming a level is refused", mut(GOOD_REVIEW, trig("manual", 1)), "reviews", True)
    expect("a manual row with no level passes", mut(GOOD_REVIEW, trig("manual", None)), "reviews", False)
    expect("a pre-rule due event with a null level is history, not refused",
           mut(GOOD_REVIEW, trig("mechanics", None, "2026-10-26T22:16:00Z")), "reviews", False)
    expect("a review_id naming another package than the row's is refused",
           mut(GOOD_REVIEW, lambda r: r.update(order_package_id="pkg-2")), "reviews", True)
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
