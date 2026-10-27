"""DESK-4-INTAKE: desk decision rows on desk/decisions -> the apply path (scripts/ops/desk_intake.py)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

from scripts.ops import desk_intake as di
from src.runtime import live_review_rows_watch as w

cdr = di.cdr
T0 = datetime(2026, 10, 26, 9, 5, tzinfo=timezone.utc)
TIP = "d" * 40
GATED = {"mandates": [{"id": "MD-TRADE-DESK", "functions": {"entry_generation": {
    "blocked_until": "The DESK-13 gate, operator verbatim \"Beat random entries only\" ..."}}}]}
CLEARED = {"mandates": [{"id": "MD-TRADE-DESK", "functions": {"entry_generation": {"state": "live"}}}]}


def in_trade_row(**kw):
    r = copy.deepcopy(cdr.GOOD_DECISION)
    r["disposition"] = {"route": "recommended", "per_account": []}
    r.update(kw)
    return r


def entry_row(**kw):
    r = copy.deepcopy(cdr.GOOD_ENTRY_DECISION)
    r.update(label_source="live", intent_id="INT-E1", judged_at="2026-10-26T09:01:00Z")
    r["disposition"] = {"route": "submitted", "per_account": []}
    r["proposal"]["entry"]["type"] = "market"  # a live proposal is the short-hold kind (desk_write.live_proposal_problems)
    r["proposal"]["max_hold_min"] = 45
    r.update(kw)
    return r


class FakeGit:
    def __init__(self, rows, packets=None):
        self.rows = rows
        self.packets = packets or {p["meta"]["packet_id"]: p for p in (cdr.GOOD_PACKET, cdr.GOOD_SCAN)}

    def __call__(self, *args, timeout=30):
        assert args[0] == "show"
        path = args[1].split(":", 1)[1]
        if path == di.DECISIONS_PATH:
            return 0, "\n".join(json.dumps(r) for r in self.rows)
        pid = path.rsplit("/", 1)[-1][:-5]
        if pid in self.packets:
            return 0, json.dumps(self.packets[pid], sort_keys=True, separators=(",", ":"))
        return 128, "fatal: path does not exist"


class FakeApply:
    def __init__(self, exits=(0,)):
        self.exits, self.calls = list(exits), []

    def __call__(self, plan, evidence):
        self.calls.append((plan, evidence))
        code = self.exits.pop(0) if len(self.exits) > 1 else self.exits[0]
        return {"exit": code, "detail": None, "applied": code == 0,
                "lines": [">>> bybit_1 [bybit/apply]: approve 98.0 executed=True -- ok"]}


def run(tmp_path, rows, *, apply_fn=None, mandates=GATED, now=T0, leg=False, flags=None, accounts=None,
        symbols=("ETHUSDT",)):
    return di.run_pass(TIP, git=FakeGit(rows), apply_fn=apply_fn or FakeApply(), now_fn=lambda: now,
                       logs=tmp_path, mandates_fn=lambda: mandates, leg_fn=lambda: leg,
                       flag_fn=(flags.append if flags is not None else (lambda line: None)),
                       accounts_fn=lambda: accounts, symbols_fn=lambda: list(symbols) if symbols is not None else None)


def log(tmp_path):
    p = tmp_path / "intake.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def seeded(tmp_path):
    run(tmp_path, [])  # first pass seeds an empty branch


def test_fixtures_validate_as_desk_rows(tmp_path):
    schema = json.loads(cdr.DECISION_SCHEMA.read_text())
    for pk in (cdr.GOOD_PACKET, cdr.GOOD_SCAN):
        (tmp_path / f"{pk['meta']['packet_id']}.json").write_text(json.dumps(pk))
    assert cdr.decision_problems(in_trade_row(), schema, tmp_path) == []
    assert cdr.decision_problems(entry_row(), schema, tmp_path) == []


def test_apply_actions_are_the_guards_applicable_set():
    assert set(di.APPLY_ACTION) == set(cdr.APPLICABLE)


def test_first_pass_seeds_and_never_replays(tmp_path):
    a = FakeApply()
    st = run(tmp_path, [in_trade_row()], apply_fn=a)
    assert st["seeded"] == 1 and a.calls == [] and log(tmp_path) == []
    run(tmp_path, [in_trade_row()], apply_fn=a)
    assert a.calls == []


def test_an_in_trade_tighten_is_dispatched_once_through_the_apply(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    run(tmp_path, [in_trade_row()], apply_fn=a)
    assert len(a.calls) == 1
    plan, evidence = a.calls[0]
    assert plan["action"] == "tighten_sl" and plan["new_sl"] == 98.0 and plan["mandate"] == "MD-TRADE-DESK"
    assert plan["order_package_id"] == "pkg-1" and plan["review_id"] == cdr.GOOD_DECISION["decision_id"]
    assert plan["basis"] == "judgement" and plan["confidence"] == 0.6 and plan["mechanics"] == "match"
    assert evidence.endswith("DP-20261026T0900Z-pkg-1.json")
    (rec,) = log(tmp_path)
    assert rec["verdict"] == "dispatched" and rec["exit"] == 0 and rec["lines"]
    # dedupe: the same decision on the next pass (and a second copy on the branch) is never re-sent
    run(tmp_path, [in_trade_row(), in_trade_row()], apply_fn=a)
    assert len(a.calls) == 1 and len(log(tmp_path)) == 1


def test_a_second_decision_with_a_dispatched_intent_is_refused(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    run(tmp_path, [in_trade_row()], apply_fn=a)
    run(tmp_path, [in_trade_row(), in_trade_row(decision_id="DD-20261026T0900Z-pkg-1-b")], apply_fn=a)
    assert len(a.calls) == 1
    assert log(tmp_path)[-1]["verdict"] == "refused" and log(tmp_path)[-1]["detail"] == "duplicate_intent:INT-1"


def test_propose_entry_is_refused_while_gated_and_recorded(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    run(tmp_path, [entry_row()], apply_fn=a, leg=True)
    (rec,) = log(tmp_path)
    assert a.calls == [] and rec["verdict"] == "refused" and rec["detail"].startswith(di.R_GATED)
    assert "Beat random entries" in rec["detail"]
    assert not (tmp_path / "accepted_proposals.jsonl").exists()


def test_entry_gate_reads_the_mandate_and_fails_closed():
    assert di.entry_gate(GATED).startswith(di.R_GATED)
    assert di.entry_gate(CLEARED) is None
    assert di.entry_gate(None).endswith("mandates_unreadable")
    assert di.entry_gate({"mandates": []}).endswith("MD-TRADE-DESK_not_granted")


def test_the_real_mandate_store_admits_the_bybit_1_demo_only():
    """Field beats comment: config/mandates.yaml + config/accounts.yaml as they stand. The demo floor (operator
    popup 2026-10-27) opens the gate for the leg rostered on bybit_1 only; without the accounts it stays closed."""
    mandates, accounts = di._load_yaml("config/mandates.yaml"), di._load_yaml("config/accounts.yaml")
    assert di.carrying_accounts(accounts) == ["bybit_1"]
    assert di.entry_gate(mandates, accounts) is None
    assert di.entry_gate(mandates).startswith(di.R_GATED)


def test_cleared_gate_queues_for_the_desk_leg_or_refuses_until_rostered(tmp_path):
    seeded(tmp_path)
    run(tmp_path, [entry_row()], mandates=CLEARED, leg=False)
    assert log(tmp_path)[-1]["verdict"] == "refused" and log(tmp_path)[-1]["detail"].startswith("desk_leg_not_rostered")
    run(tmp_path, [entry_row(), entry_row(decision_id="DD-20261026T0900Z-scan-15m-2", intent_id="INT-E2")],
        mandates=CLEARED, leg=True)
    assert log(tmp_path)[-1]["verdict"] == "accepted"
    (q,) = [json.loads(x) for x in (tmp_path / "accepted_proposals.jsonl").read_text().splitlines()]
    assert q["decision_id"] == "DD-20261026T0900Z-scan-15m-2" and q["proposal"]["stop"]["level"] == 96.0


def test_a_proposal_missing_a_bracket_is_refused_by_name(tmp_path):
    seeded(tmp_path)
    r = entry_row()
    r["proposal"]["tp"] = None
    run(tmp_path, [r], mandates=CLEARED, leg=True)
    (rec,) = log(tmp_path)
    assert rec["verdict"] == "refused" and rec["detail"] == "both_brackets_required:missing_tp"


def test_a_malformed_row_is_refused_with_its_reason(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    bad = in_trade_row()
    bad["params"]["level"] = None           # tighten_sl without a level
    bad2 = in_trade_row(decision_id="DD-20261026T0900Z-pkg-1-c", intent_id="INT-2", action="widen_sl")
    run(tmp_path, [bad, bad2], apply_fn=a)
    recs = log(tmp_path)
    assert a.calls == [] and [r["verdict"] for r in recs] == ["refused", "refused"]
    assert "tighten_sl requires params.level" in recs[0]["detail"]
    assert "widen_sl" in recs[1]["detail"] and recs[1]["detail"].startswith("invalid_row")


def test_record_only_rows_are_logged_not_sent(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    shadow = in_trade_row(label_source="shadow", intent_id=None, decision_id="DD-20261026T0900Z-pkg-1-s")
    shadow["disposition"]["route"] = "none"
    hold = in_trade_row(decision_id="DD-20261026T0900Z-pkg-1-h", action="hold", intent_id=None,
                        params={"level": None, "level_atr": None, "frac": None, "bars": None})
    hold["alternatives"] = [{"action": "hold", "chosen": True, "symbol": None, "side": None, "level": None,
                             "source": "not_priced", "n": None, "mean_r": None, "sd_r": None}]
    tp = in_trade_row(decision_id="DD-20261026T0900Z-pkg-1-t", action="tp_revise", intent_id="INT-3",
                      params={"level": 118.0, "level_atr": None, "frac": None, "bars": None})
    tp["alternatives"] = [dict(a_, action=("tp_revise" if a_["chosen"] else "hold"), level=(118.0 if a_["chosen"] else None))
                          for a_ in tp["alternatives"]]
    run(tmp_path, [shadow, hold, tp], apply_fn=a)
    recs = {r["decision_id"]: r for r in log(tmp_path)}
    assert a.calls == []
    assert recs[shadow["decision_id"]]["detail"] == "label_source_shadow"
    assert recs[hold["decision_id"]]["detail"] == "action_in_trade/hold"
    assert recs[tp["decision_id"]]["detail"] == "recommendation_only_on_strategy_trade:tp_revise"
    assert all(r["verdict"] == "not_dispatchable" for r in recs.values())


def test_could_not_look_retries_then_expires_with_one_flag(tmp_path):
    seeded(tmp_path)
    a, flags = FakeApply(exits=(3,)), []
    run(tmp_path, [in_trade_row()], apply_fn=a, flags=flags)
    run(tmp_path, [in_trade_row()], apply_fn=a, now=T0 + timedelta(minutes=5), flags=flags)
    assert len(a.calls) == 2 and flags == [] and log(tmp_path)[0]["retrying"] is True
    run(tmp_path, [in_trade_row()], apply_fn=a, now=T0 + timedelta(minutes=61), flags=flags)
    assert log(tmp_path)[-1]["verdict"] == "expired" and len(flags) == 1
    run(tmp_path, [in_trade_row()], apply_fn=a, now=T0 + timedelta(minutes=62), flags=flags)
    assert len(a.calls) == 3 and len(flags) == 1


def test_a_stale_decision_is_refused(tmp_path):
    seeded(tmp_path)
    a = FakeApply()
    run(tmp_path, [in_trade_row()], apply_fn=a, now=T0 + timedelta(hours=2))
    assert a.calls == [] and log(tmp_path)[0]["detail"].startswith("stale_decision")


def test_dry_run_writes_no_state(tmp_path):
    a = FakeApply()
    st = di.run_pass(TIP, apply=False, git=FakeGit([in_trade_row()]), apply_fn=a, now_fn=lambda: T0,
                     logs=tmp_path, mandates_fn=lambda: GATED, leg_fn=lambda: False)
    assert a.calls == [] and st["new"] == 1 and not (tmp_path / "intake_state.json").exists()
    assert log(tmp_path)[0]["verdict"] == "would_dispatch"


# -- the rows watcher's desk pass ------------------------------------------------------------

class WatchGit:
    def __init__(self, tip=TIP, fetch_rc=0):
        self.tip, self.fetch_rc = tip, fetch_rc

    def __call__(self, *args, timeout=30):
        if args[0] == "fetch":
            assert args[-1] == f"+refs/heads/desk/decisions:{w.DESK_LOCAL_REF}"
            return self.fetch_rc, "fatal" if self.fetch_rc else ""
        return 0, self.tip


def test_watcher_runs_the_intake_only_when_the_tip_moves_or_a_row_is_pending(tmp_path):
    calls = []

    def intake(tip, code=[0]):
        calls.append(tip)
        return {"exit": code[0], "new": 1}

    w.run_desk_pass(git=WatchGit(), intake=intake, logs=tmp_path)
    w.run_desk_pass(git=WatchGit(), intake=intake, logs=tmp_path)
    assert calls == [TIP]
    w.run_desk_pass(git=WatchGit(tip="e" * 40), intake=lambda t: (calls.append(t), {"exit": 3})[1], logs=tmp_path)
    w.run_desk_pass(git=WatchGit(tip="e" * 40), intake=intake, logs=tmp_path)
    assert calls == [TIP, "e" * 40, "e" * 40]
    st = w.run_desk_pass(git=WatchGit(fetch_rc=1), intake=intake, logs=tmp_path)
    assert st["fetch_state"] == "could_not_fetch" and len(calls) == 3


def test_apply_builds_a_live_review_intent_and_runs_the_real_apply(monkeypatch):
    """The real seam: di._apply -> live_review_apply.build_intent + run() under MD-TRADE-DESK."""
    from scripts.ops import live_review_apply as lra

    pkg = {"order_package_id": "pkg-1", "status": "open", "direction": "long", "symbol": "ETHUSDT",
           "strategy_name": "example_leg", "sl": 95.0}
    seen = {}
    monkeypatch.setattr(lra, "_open_db", lambda: object())
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: pkg if pid == "pkg-1" else None)
    monkeypatch.setattr(lra, "_strategies", lambda: {})
    monkeypatch.setattr(lra, "_accounts", lambda: {})
    monkeypatch.setattr(lra, "market_state", lambda p, s: {"mark": 101.0, "atr": 2.0, "bar_ts": "2026-10-26T09:00:00Z"})
    monkeypatch.setattr(lra, "gather_legs", lambda db, p: (seen.setdefault("legs", p), [])[1])
    monkeypatch.setattr(lra, "APPLIED_LOG", lra.Path("/nonexistent-dir/applied.jsonl"))
    monkeypatch.setattr(lra, "_save_state", lambda st: None)
    monkeypatch.setattr(lra, "_load_state", lambda: {})
    _, _, plan = di.classify(in_trade_row(), problems=[], packet=cdr.GOOD_PACKET, gate=None, leg_rostered=False)
    res = di._apply(plan, "runtime_logs/desk/packets/DP-20261026T0900Z-pkg-1.json")
    assert res["exit"] == 0 and seen["legs"] is pkg and res["applied"] is False
    assert di._apply(dict(plan, order_package_id="pkg-gone"), "x")["exit"] == 2
