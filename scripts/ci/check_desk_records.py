#!/usr/bin/env python3
"""desk-records-guard -- validates the trading-desk records against comms/schema/desk_*.schema.json.

DESK-0-SCHEMA (design docs/plans/claude-trading-desk-DESIGN.md sections 2.2, 2.3, 3.4, 3.6).
A sibling of live-review-records-guard, not a replacement: it reuses that guard's schema walker and
leaves comms/live_review/ (and its v2 packets) to it. It checks

* comms/desk/packets/*.json  -- packet v3 (desk_packet.schema.json): which blocks a kind carries,
  `outcome` only on kind exit (T1), could-not-look is null AND named in meta.missing_inputs;
* comms/desk/decisions.jsonl -- desk_decision.schema.json `decisions`: action closed per role, role
  matched to packet kind, params agree with the action, nothing but a tighten is ever applied,
  external_context consistent (used => sources + trigger, reproducible=false), packet_sha equals
  the committed packet and the row agrees with it;
* comms/desk/touches.jsonl   -- desk_decision.schema.json `touches`: only applied intents, tighten-only,
  `sandbox` iff the account is the sandbox account, each touch joins to a decision that applied it.

Files are append-only and start empty; a leading {"_meta": ...} line is skipped.
Exit: 0 clean / 1 refused.   Usage: check_desk_records.py [--self-test]
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_live_review_records as lr  # noqa: E402  (the shared schema walker)

REPO = Path(__file__).resolve().parents[2]
PACKET_SCHEMA = REPO / "comms/schema/desk_packet.schema.json"
DECISION_SCHEMA = REPO / "comms/schema/desk_decision.schema.json"
DESK = REPO / "comms/desk"
DECISIONS = DESK / "decisions.jsonl"
TOUCHES = DESK / "touches.jsonl"
PACKETS = DESK / "packets"

# design 2.2 table: which blocks each kind carries. "-" cells are FORBIDDEN, not optional.
COMMON = {"meta", "package", "market", "features_at_review"}
BLOCKS_BY_KIND = {
    "entry": COMMON | {"history", "book", "per_account", "ml"},
    "in_trade": COMMON | {"state", "history", "book", "per_account", "mechanics", "ml", "prior_decisions"},
    "exit": COMMON | {"state", "mechanics", "prior_decisions", "outcome"},
}
ALL_BLOCKS = {"state", "history", "book", "per_account", "mechanics", "ml", "prior_decisions", "outcome"}
# Roles whose actions are never applied today (design 2.3 'applied today?' column).
NEVER_APPLIED = {"market_watch", "entry_review", "exit", "post_trade"}
LEVEL_ACTIONS = {"tighten_sl", "tp_revise"}
BARS_ACTIONS = {"delay", "delay_candidate"}
# Fields projected into features_at_review (flat numeric view of the same packet; design 2.2).
FEATURE_SOURCES = {
    "open_r": ("state", "open_r"), "peak_r": ("state", "peak_r"), "giveback_r": ("state", "giveback_r"),
    "bars_held": ("state", "bars_held"), "bars_since_peak": ("state", "bars_since_peak"),
    "r_to_stop": ("state", "r_to_stop"), "r_to_target": ("state", "r_to_target"),
    "atr_now": ("market", "atr_now"), "atr_entry": ("market", "atr_entry"),
}


def packet_sha(packet: dict) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def project_features(packet: dict) -> dict:
    """The ML feature view as a projection of the packet: flat, numeric-or-null. A block the kind does
    not carry, or a field the packet could not read, projects to null -- never 0."""
    out = {}
    for name, (blk, key) in FEATURE_SOURCES.items():
        v = (packet.get(blk) or {}).get(key)
        out[name] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    a, b = out["atr_now"], out["atr_entry"]
    out["atr_now_over_entry"] = (a / b) if a is not None and b else None
    return out


def packet_problems(p: dict, schema: dict) -> list[str]:
    out: list[str] = []
    lr._check(p, schema["packet"], schema["enums"], "packet", out)
    if out:
        return out
    kind = p["meta"]["packet_kind"]
    have = set(p) & ALL_BLOCKS
    for b in sorted(BLOCKS_BY_KIND[kind] & ALL_BLOCKS - have):
        out.append(f"packet kind {kind} requires block `{b}`")
    for b in sorted(have - BLOCKS_BY_KIND[kind]):
        out.append(f"packet kind {kind} must not carry block `{b}`")
    if kind != "exit" and "outcome" in p:
        out.append("outcome (T1) is only allowed on kind exit")
    missing = set(p["meta"]["missing_inputs"])
    # collapsed-state rule: a null feature must be named in missing_inputs or have a null source
    feats = p["features_at_review"]
    for k, v in project_features(p).items():
        if k in feats and feats[k] != v:
            out.append(f"features_at_review.{k} is not the projection of the packet (got {feats[k]!r}, packet says {v!r})")
    if "state" in p:
        st = p["state"]
        if st["peak_provenance"] in ("unverified", "fabricated") and st["peak_r"] == 0:
            out.append("state.peak_r: 0 with unverified/fabricated provenance (unmeasured must be null)")
        for k in ("open_r", "peak_r", "giveback_r"):
            if st[k] is None and not any(m == f"state.{k}" or m.startswith(f"state.{k}:") for m in missing):
                out.append(f"state.{k} is null but not named in meta.missing_inputs (could-not-look != zero)")
    for blk in ("funding", "calendar"):
        if p["market"][blk]["read_state"] == "could_not_look" and not any(m.startswith(f"market.{blk}") for m in missing):
            out.append(f"market.{blk} could_not_look but not named in meta.missing_inputs")
    for i, o in enumerate((p.get("history") or {}).get("options", [])):
        if o["n"] == 0 and any(o[k] is not None for k in ("mean_r", "sd_r", "worst_r")):
            out.append(f"history.options[{i}]: n == 0 but numbers present (must be null)")
    for i, m in enumerate(p.get("ml", [])):
        if (m["state"] == "absent") != (m["prediction"] is None):
            out.append(f"ml[{i}]: state absent <=> prediction null (absent is never imputed)")
    ids = [a["account_id"] for a in p["package"]["accounts"]]
    if len(ids) != len(set(ids)):
        out.append("package.accounts names an account more than once")
    if "per_account" in p and {a["account_id"] for a in p["per_account"]} != set(ids):
        out.append("per_account must cover exactly package.accounts")
    return out


def decision_problems(r: dict, schema: dict, packets: Path) -> list[str]:
    out: list[str] = []
    lr._check(r, schema["decisions"], schema["enums"], "decision", out)
    if out:
        return out
    role, action = r["role"], r["action"]
    if action not in schema["role_actions"][role]:
        out.append(f"action {action!r} is not in the closed enum for role {role}: {schema['role_actions'][role]}")
    if r["packet_kind"] not in schema["role_packet_kinds"][role]:
        out.append(f"role {role} cannot judge a {r['packet_kind']} packet (allowed: {schema['role_packet_kinds'][role]})")
    pr = r["params"]
    if action in LEVEL_ACTIONS and pr["level"] is None:
        out.append(f"{action} requires params.level")
    if action not in LEVEL_ACTIONS and (pr["level"] is not None or pr["level_atr"] is not None):
        out.append(f"params.level/level_atr only with {sorted(LEVEL_ACTIONS)}")
    if action == "partial_close" and (pr["frac"] is None or not 0 < pr["frac"] < 1):
        out.append("partial_close requires 0 < params.frac < 1")
    if action != "partial_close" and pr["frac"] is not None:
        out.append("params.frac only with partial_close")
    if action in BARS_ACTIONS and pr["bars"] is None:
        out.append(f"{action} requires params.bars")
    if action not in BARS_ACTIONS and pr["bars"] is not None:
        out.append(f"params.bars only with {sorted(BARS_ACTIONS)}")
    if r["basis"] == "insufficient_n" and action in ("hold", "take"):
        out.append("basis insufficient_n is never hold/take (insufficient_n is no recommendation)")
    if r["label_provenance"] != "judgment" and role != "post_trade":
        out.append("label_provenance computed/measured only on post_trade rows")
    d = r["disposition"]
    applied = [a for a in d["per_account"] if a["applied"]]
    if len({a["account_id"] for a in d["per_account"]}) != len(d["per_account"]):
        out.append("disposition.per_account names an account more than once")
    if d["route"] == "auto_applied":
        if role != "in_trade" or action != "tighten_sl":
            out.append("only an in_trade tighten_sl may be auto_applied (size, entries, exits and widening are never applied)")
        if r["intent_id"] is None:
            out.append("auto_applied requires intent_id")
        if not applied:
            out.append("auto_applied requires at least one applied per_account entry")
    elif applied:
        out.append("a per_account entry is applied but route is not auto_applied")
    if role in NEVER_APPLIED and (applied or r["intent_id"] is not None):
        out.append(f"role {role} is never applied: intent_id must be null and nothing applied")
    for a in d["per_account"]:
        if a["applied"] and not (a["verdict"] in ("approve", "clip") and a["readback"] == "match"):
            out.append(f"{a['account_id']}: applied requires verdict approve|clip and readback match (a mismatch is apply_failed)")
        if a["applied"] and (a["level_before"] is None or a["level_after"] is None):
            out.append(f"{a['account_id']}: applied requires level_before and level_after")
        if a["desk_touched"] != a["applied"]:
            out.append(f"{a['account_id']}: desk_touched must equal applied (a pair is touched from its first applied intent)")
    ec = r["external_context"]
    if ec["used"]:
        if not ec["sources"]:
            out.append("external_context.used with empty sources")
        if ec["trigger"] is None:
            out.append("external_context.used requires a trigger (calendar|swing|escalation)")
        if ec["trigger"] in ("calendar", "swing") and r["trigger_event"] != ec["trigger"]:
            out.append("external_context.trigger calendar/swing must equal trigger_event (big-event exception only)")
        if not ec["summary"]:
            out.append("external_context.used requires a summary")
        if ec["reproducible"] is not False:
            out.append("external_context.used requires reproducible=false (replays and training exclude these rows)")
    else:
        if ec["sources"] or ec["trigger"] is not None or ec["summary"] is not None:
            out.append("external_context.used=false must have no sources, trigger or summary")
        if ec["reproducible"] is not True:
            out.append("external_context.used=false requires reproducible=true")
    f = packets / f"{r['packet_id']}.json"
    if not f.exists():
        out.append(f"packet {f.name} is missing from comms/desk/packets/")
    else:
        try:
            pk = json.loads(f.read_text())
        except ValueError:
            return out + [f"packet {f.name} is not valid JSON"]
        if packet_sha(pk) != r["packet_sha"]:
            out.append(f"packet_sha does not match {f.name}")
        meta = pk.get("meta", {})
        if meta.get("packet_kind") != r["packet_kind"]:
            out.append("packet_kind disagrees with the committed packet")
        if meta.get("info_cutoff_at") != r["info_cutoff_at"]:
            out.append("info_cutoff_at disagrees with the committed packet")
        if pk.get("package", {}).get("order_package_id") != r["order_package_id"]:
            out.append("order_package_id disagrees with the committed packet")
        known = {a["account_id"] for a in pk.get("package", {}).get("accounts", [])}
        for a in d["per_account"]:
            if a["account_id"] not in known:
                out.append(f"disposition names account {a['account_id']} that does not carry the package")
    return out


def touch_problems(t: dict, schema: dict, decisions: dict[str, dict]) -> list[str]:
    out: list[str] = []
    lr._check(t, schema["touches"], schema["enums"], "touch", out)
    if out:
        return out
    if t["sandbox"] != (t["account"] == schema["sandbox_account"]):
        out.append(f"sandbox must be true exactly when account == {schema['sandbox_account']}")
    long_ = t["side"] == "long"
    if not (t["level_after"] > t["level_before"] if long_ else t["level_after"] < t["level_before"]):
        out.append("a desk touch is tighten-only: long stops rise, short stops fall")
    d = decisions.get(t["decision_id"])
    if d is None:
        return out + [f"decision {t['decision_id']} has no row in decisions.jsonl"]
    if d["intent_id"] != t["intent_id"] or d["order_package_id"] != t["order_package_id"]:
        out.append("touch intent_id/order_package_id disagree with its decision")
    if not any(a["account_id"] == t["account"] and a["applied"] and a["level_after"] == t["level_after"]
               and a["level_before"] == t["level_before"] for a in d["disposition"]["per_account"]):
        out.append("no applied per_account entry on the decision matches this touch")
    return out


def _rows(path: Path):
    yield from lr._rows(path)


def findings(decisions: Path = DECISIONS, touches: Path = TOUCHES, packets: Path = PACKETS,
             pschema: Path = PACKET_SCHEMA, dschema: Path = DECISION_SCHEMA) -> list[str]:
    ps, ds = json.loads(pschema.read_text()), json.loads(dschema.read_text())
    out: list[str] = []
    if packets.exists():
        for f in sorted(packets.glob("*.json")):
            try:
                pk = json.loads(f.read_text())
            except ValueError as e:
                out.append(f"{f.name}: invalid JSON ({e})")
                continue
            out += [f"{f.name}: {m}" for m in packet_problems(pk, ps)]
            if pk.get("meta", {}).get("packet_id") != f.stem:
                out.append(f"{f.name}: meta.packet_id must equal the file name")
    byid: dict[str, dict] = {}
    for kind, p in (("decisions", decisions), ("touches", touches)):
        if not p.exists():
            out.append(f"{p.name}: file missing")
            continue
        for n, r, err in _rows(p):
            tag = f"{p.name}:{n}"
            if err or not isinstance(r, dict):
                out.append(f"{tag}: {err or 'not an object'}")
                continue
            if kind == "decisions":
                out += [f"{tag}: {m}" for m in decision_problems(r, ds, packets)]
                if r.get("decision_id") in byid:
                    out.append(f"{tag}: duplicate decision_id {r.get('decision_id')}")
                byid[r.get("decision_id")] = r
    if touches.exists():
        seen: set[str] = set()
        for n, r, err in _rows(touches):
            if isinstance(r, dict):
                out += [f"{touches.name}:{n}: {m}" for m in touch_problems(r, ds, byid)]
                if r.get("touch_id") in seen:
                    out.append(f"{touches.name}:{n}: duplicate touch_id {r.get('touch_id')}")
                seen.add(r.get("touch_id"))
    return out


# ----------------------------------------------------------------------------- fixtures / self-test

GOOD_PACKET = {
    "schema_version": 1,
    "meta": {"packet_id": "DP-20261026T0900Z-pkg-1", "packet_kind": "in_trade", "packet_version": 3,
             "built_at": "2026-10-26T09:00:00Z", "info_cutoff_at": "2026-10-26T08:59:30Z",
             "generator": "example", "missing_inputs": ["market.funding: no route"]},
    "package": {"order_package_id": "pkg-1", "leg": "example_leg", "symbol": "ETHUSDT", "side": "long",
                "timeframe": "4h", "signal_logic": "example", "entry": 100.0, "sl": 95.0, "tp": 120.0,
                "risk_per_unit": 5.0,
                "accounts": [{"account_id": "acct_a", "account_class": "real_money"},
                             {"account_id": "bybit_1", "account_class": "soak"}]},
    "state": {"open_r": 1.2, "peak_r": 1.5, "peak_provenance": "estimated", "giveback_r": 0.3, "bars_held": 6,
              "bars_since_peak": 2, "r_to_stop": 2.2, "r_to_target": 2.8, "sl_live": 95.0, "tp_live": 120.0},
    "market": {"atr_now": 2.0, "atr_entry": 2.0, "htf_trend": "up", "regime_cell_now": None, "regime_cell_entry": "trend_calm",
               "funding": {"read_state": "could_not_look", "rate": None, "vs_assumption": None},
               "calendar": {"read_state": "read", "events_next_bar": []},
               "news": {"state": "none_found", "decision": None}},
    "history": {"source": "live_review_outcomes.py", "read_state": "read", "population": "comparable", "n_floor": 20,
                "net_of_full_cost_stack": True,
                "options": [{"action": "hold", "level": None, "n": 32, "mean_r": 3.1, "sd_r": 1.3, "worst_r": 0.2}]},
    "book": {"read_state": "read", "correlated_open": []},
    "per_account": [
        {"account_id": "acct_a", "account_class": "real_money", "mode": "live", "venue_read_state": "read", "venue_sl": 95.0,
         "venue_tp": 120.0, "venue_size": 1.0, "gate_preview": {"verdict": "not_available", "reason": "gate not built"}},
        {"account_id": "bybit_1", "account_class": "soak", "mode": "live", "venue_read_state": "read", "venue_sl": 95.0,
         "venue_tp": 120.0, "venue_size": 1.0, "gate_preview": {"verdict": "not_available", "reason": "gate not built"}}],
    "mechanics": {"verdict": "match", "evidence": "example"},
    "ml": [{"head": "example_head", "stage": "shadow", "state": "absent", "prediction": None}],
    "prior_decisions": [],
    "features_at_review": {"open_r": 1.2, "peak_r": 1.5, "giveback_r": 0.3, "bars_held": 6, "bars_since_peak": 2,
                           "r_to_stop": 2.2, "r_to_target": 2.8, "atr_now": 2.0, "atr_entry": 2.0, "atr_now_over_entry": 1.0},
}
GOOD_EXIT_PACKET = {k: v for k, v in GOOD_PACKET.items() if k not in ("history", "book", "per_account", "ml")}
GOOD_EXIT_PACKET["meta"] = dict(GOOD_PACKET["meta"], packet_id="DP-20261026T1200Z-pkg-1", packet_kind="exit")
GOOD_EXIT_PACKET["prior_decisions"] = [{"decision_id": "DD-20261026T0900Z-pkg-1", "judged_at": "2026-10-26T09:00:30Z",
                                        "action": "tighten_sl", "applied": True}]
GOOD_EXIT_PACKET["outcome"] = {"t1": True, "closed_at": "2026-10-26T12:00:00Z", "net_r": 1.4,
                               "provenance": "measured", "exit_reason": "sl_hit"}

GOOD_DECISION = {
    "schema_version": 1, "decision_id": "DD-20261026T0900Z-pkg-1", "packet_id": "DP-20261026T0900Z-pkg-1",
    "packet_sha": packet_sha(GOOD_PACKET), "packet_kind": "in_trade", "role": "in_trade", "order_package_id": "pkg-1",
    "judged_at": "2026-10-26T09:00:30Z", "info_cutoff_at": "2026-10-26T08:59:30Z", "trigger_event": "r_milestone",
    "model": "sonnet-tier", "session": "session_x", "prompt_sha": None, "skill_sha": None, "label_version": 1,
    "label_provenance": "judgment", "action": "tighten_sl",
    "params": {"level": 98.0, "level_atr": 1.0, "frac": None, "bars": None},
    "judge_prior": 0.6, "confidence": "measured", "basis": "preference_within_bound", "rationale": "example",
    "escalated_to": None, "intent_id": "INT-1",
    "disposition": {"route": "auto_applied", "per_account": [
        {"account_id": "bybit_1", "account_class": "soak", "verdict": "approve", "reason": None, "applied": True,
         "level_before": 95.0, "level_after": 98.0, "readback": "match", "desk_touched": True},
        {"account_id": "acct_a", "account_class": "real_money", "verdict": "refuse", "reason": "example", "applied": False,
         "level_before": 95.0, "level_after": None, "readback": "not_applicable", "desk_touched": False}]},
    "external_context": {"used": False, "trigger": None, "sources": [], "summary": None, "reproducible": True},
}
GOOD_TOUCH = {
    "schema_version": 1, "touch_id": "DT-20261026T0900Z-pkg-1-bybit_1", "order_package_id": "pkg-1", "account": "bybit_1",
    "account_class": "soak", "side": "long", "intent_id": "INT-1", "decision_id": "DD-20261026T0900Z-pkg-1",
    "applied_at": "2026-10-26T09:01:00Z", "level_before": 95.0, "level_after": 98.0, "verdict": "approve", "sandbox": True,
}


def _mut(base, fn):
    r = copy.deepcopy(base)
    fn(r)
    return r


def _self_test() -> int:
    ps, ds = json.loads(PACKET_SCHEMA.read_text()), json.loads(DECISION_SCHEMA.read_text())
    ok = True

    def expect(label, problems, bad):
        nonlocal ok
        good = bool(problems) == bad
        print(f"  {'PASS' if good else 'FAIL'}  {label}")
        ok &= good

    with tempfile.TemporaryDirectory() as d:
        pk = Path(d) / "packets"
        pk.mkdir()
        (pk / "DP-20261026T0900Z-pkg-1.json").write_text(json.dumps(GOOD_PACKET))
        dp = lambda r: decision_problems(r, ds, pk)  # noqa: E731
        P = lambda r: packet_problems(r, ps)  # noqa: E731
        T = lambda r: touch_problems(r, ds, {GOOD_DECISION["decision_id"]: GOOD_DECISION})  # noqa: E731

        expect("a well-formed in_trade packet passes", P(GOOD_PACKET), False)
        expect("a well-formed exit packet passes", P(GOOD_EXIT_PACKET), False)
        expect("a well-formed decision passes", dp(GOOD_DECISION), False)
        expect("a well-formed touch passes", T(GOOD_TOUCH), False)
        # packets
        expect("entry packet carrying `state` is refused", P(_mut(GOOD_PACKET, lambda r: (r["meta"].update(packet_kind="entry"), r.pop("mechanics"), r.pop("prior_decisions")))), True)
        expect("in_trade packet missing `mechanics` is refused", P(_mut(GOOD_PACKET, lambda r: r.pop("mechanics"))), True)
        expect("outcome on a non-exit packet is refused", P(_mut(GOOD_PACKET, lambda r: r.update(outcome=GOOD_EXIT_PACKET["outcome"]))), True)
        expect("exit packet without outcome is refused", P(_mut(GOOD_EXIT_PACKET, lambda r: r.pop("outcome"))), True)
        expect("packet_version 2 is refused", P(_mut(GOOD_PACKET, lambda r: r["meta"].update(packet_version=2))), True)
        expect("null state.open_r not named in missing_inputs is refused",
               P(_mut(GOOD_PACKET, lambda r: (r["state"].update(open_r=None), r["features_at_review"].update(open_r=None)))), True)
        expect("could_not_look funding not named in missing_inputs is refused",
               P(_mut(GOOD_PACKET, lambda r: r["meta"].update(missing_inputs=[]))), True)
        expect("zero peak with unverified provenance is refused",
               P(_mut(GOOD_PACKET, lambda r: (r["state"].update(peak_r=0, peak_provenance="unverified"), r["features_at_review"].update(peak_r=0)))), True)
        expect("features_at_review that is not the projection is refused",
               P(_mut(GOOD_PACKET, lambda r: r["features_at_review"].update(open_r=9.9))), True)
        expect("ml head absent with a prediction (imputed) is refused",
               P(_mut(GOOD_PACKET, lambda r: r["ml"][0].update(prediction=0.0))), True)
        expect("a history option with n == 0 and numbers is refused",
               P(_mut(GOOD_PACKET, lambda r: r["history"]["options"][0].update(n=0))), True)
        expect("per_account not covering package.accounts is refused",
               P(_mut(GOOD_PACKET, lambda r: r["per_account"].pop())), True)
        # decisions
        expect("prose action is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(action="move it up a bit"))), True)
        expect("size change is not in any enum", dp(_mut(GOOD_DECISION, lambda r: r.update(action="size_up"))), True)
        expect("widen_sl is not in any enum", dp(_mut(GOOD_DECISION, lambda r: r.update(action="widen_sl"))), True)
        expect("an entry-role action on an in_trade role is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(action="skip"))), True)
        expect("role entry_review on an in_trade packet is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(role="entry_review", action="take"))), True)
        expect("tighten_sl without a level is refused", dp(_mut(GOOD_DECISION, lambda r: r["params"].update(level=None))), True)
        expect("partial_close frac out of (0,1) is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="exit", action="partial_close"), r["params"].update(level=None, level_atr=None, frac=1.0)))), True)
        expect("insufficient_n written as hold is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(action="hold", basis="insufficient_n"), r["params"].update(level=None, level_atr=None)))), True)
        expect("auto_applied on an exit-role close is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="exit", action="close"), r["params"].update(level=None, level_atr=None)))), True)
        expect("a shadow entry_review row carrying an intent is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="entry_review", packet_kind="entry", action="skip"), r["params"].update(level=None, level_atr=None)))), True)
        expect("an applied account with a readback mismatch is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][0].update(readback="mismatch"))), True)
        expect("desk_touched that disagrees with applied is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][0].update(desk_touched=False))), True)
        expect("an account that does not carry the package is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][1].update(account_id="acct_zzz"))), True)
        expect("packet_sha not matching the committed packet is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(packet_sha="0" * 64))), True)
        expect("a missing packet file is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(packet_id="DP-20261026T0900Z-nope"))), True)
        expect("a model identifier instead of a tier is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(model="some-model-5"))), True)
        # external_context
        EXT = {"used": True, "trigger": "calendar", "reproducible": False, "summary": "CPI due",
               "sources": [{"url_or_id": "example:cpi", "title": None, "fetched_at": "2026-10-26T08:59:00Z"}]}
        expect("external_context used with a calendar trigger event passes",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=EXT)))), False)
        expect("external_context used with empty sources is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=dict(EXT, sources=[]))))), True)
        expect("external_context used but reproducible=true is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=dict(EXT, reproducible=True))))), True)
        expect("external_context calendar trigger on an r_milestone event is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(external_context=EXT))), True)
        expect("external_context unused but carrying sources is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["external_context"].update(sources=EXT["sources"]))), True)
        expect("external_context trigger outside the exception list is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(external_context=dict(EXT, trigger="curiosity")))), True)
        # touches
        expect("a touch on a non-sandbox account flagged sandbox is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(account="acct_a"))), True)
        expect("a loosening long touch is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(level_after=94.0))), True)
        expect("a touch with verdict refuse is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(verdict="refuse"))), True)
        expect("a touch whose decision did not apply it is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(level_after=97.0))), True)
        expect("an orphan touch is refused", touch_problems(GOOD_TOUCH, ds, {}), True)
        # file level
        dec, tch = Path(d) / "decisions.jsonl", Path(d) / "touches.jsonl"
        dec.write_text(json.dumps(GOOD_DECISION) + "\n")
        tch.write_text(json.dumps(GOOD_TOUCH) + "\n")
        c = findings(dec, tch, pk)
        expect("a consistent decision + touch + packet set passes", c, False)
        tch.write_text(json.dumps(GOOD_TOUCH) + "\n" + json.dumps(GOOD_TOUCH) + "\n")
        expect("a duplicate touch_id is refused", findings(dec, tch, pk), True)
        tch.write_text("")
        dec.write_text("not json\n")
        expect("a bad line is refused", findings(dec, tch, pk), True)
        dec.write_text("")
        expect("empty files pass (append-only, start empty)", findings(dec, tch, pk), False)
        (pk / "DP-20261026T0900Z-pkg-1.json").write_text(json.dumps(_mut(GOOD_PACKET, lambda r: r.pop("mechanics"))))
        expect("a committed packet that breaks the kind matrix is refused", findings(dec, tch, pk), True)
    print("desk-records-guard self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    f = findings()
    if f:
        print("::error::comms/desk records fail comms/schema/desk_*.schema.json:")
        for x in f:
            print(f"  ✗ {x}")
        return 1
    print("desk-records-guard: comms/desk packets, decisions and touches are schema-valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
