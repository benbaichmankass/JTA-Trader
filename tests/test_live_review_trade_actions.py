"""LTR-ALL-ACTIONS: every trade action x every account class, including the refusals.

Operator 2026-10-26 (mandate MD-LIVE-TRADE-ACTIONS, verbatim): "we also need to expand the desks
mandate so include all trade actions, as long as they have reasoning and confidence attached";
accounts "All accounts now". Each account decides through its OWN RiskManager.approve_action; an
action that adds risk passes the same check a fresh entry would; an account with no executor for
an action refuses it, named (no_action_path:<action>).
"""
from __future__ import annotations

import json

import pytest

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as lrd
from src.runtime import live_review_intent as lri
from src.units.accounts.risk import RiskManager
from tests import test_live_review_apply as tla
from tests.test_live_review_apply import wired  # noqa: F401  (fixture)

JUDGE = dict(mandate=lri.TRADE_MANDATE_ID, basis=lri.BASIS_JUDGEMENT, confidence=0.65,
             reason="vol cell flipped against the leg since entry", expected_cost_r=None, worst_case_delta_r=None)


def _ti(action, **kw):
    base = dict(action=action, new_sl=None, **JUDGE)
    base.update(kw)
    return tla._intent(**base)


def _view(**kw):
    base = dict(account_id="bybit_2", account_class="bybit", leg_sl=0.2200, entry=0.2100, leg_tp=0.1900,
                position_size=10.0, fresh_ok=True, fresh_reason="ok", max_qty=30.0)
    base.update(kw)
    return lri.AmendAccountView(**base)


def _d(intent, view=None, dry=False):
    return lri.decide_action(intent, view or _view(), dry_run=dry)


# --------------------------------------------------------------- the pure decision, per action

def test_close_and_reduces_are_never_refused_for_risk():
    v = _d(_ti("close"), _view(fresh_ok=False))
    assert v.verdict == "approve" and v.qty == 10.0
    assert _d(_ti("partial_close", size_fraction=0.4)).qty == pytest.approx(4.0)
    assert _d(_ti("change_size", size_multiplier=0.25)).qty == pytest.approx(7.5)
    assert _d(_ti("partial_close", size_fraction=0.4), _view(position_size=None)).verdict == "could_not_look"


def test_move_tp_keeps_a_real_take_profit():
    assert _d(_ti("move_tp", new_tp=0.1800)).verdict == "approve"                 # short: further, either way ok
    assert _d(_ti("move_tp", new_tp=0.1950)).level == 0.1950                      # nearer, still real
    assert _d(_ti("move_tp", new_tp=0.2050)).reason == "tp_doctrine:tp_through_mark"   # above the 0.20 mark
    assert _d(_ti("move_tp", new_tp=0.1990), _view(entry=0.1980)).reason == "tp_doctrine:tp_not_beyond_entry"
    assert _d(_ti("move_tp", new_tp=0.1800), _view(leg_sl=0.2101)).reason == "tp_doctrine:sentinel"   # 300 R
    assert _d(_ti("move_tp", new_tp=0.1900)).reason == lri.R_ALREADY
    assert _d(_ti("move_tp", new_tp=0.18, mark=None)).verdict == "could_not_look"


def test_widen_sl_passes_the_fresh_entry_check_or_is_refused():
    ok = _d(_ti("widen_sl", new_sl=0.2300))
    assert ok.verdict == "approve" and ok.level == 0.2300
    assert _d(_ti("widen_sl", new_sl=0.2150)).reason == lri.R_NOT_WIDER
    assert _d(_ti("widen_sl", new_sl=0.1990)).reason == lri.R_WRONG_SIDE
    assert _d(_ti("widen_sl", new_sl=0.23), _view(leg_tp=None)).reason == "tp_doctrine:leg_has_no_real_tp"
    assert _d(_ti("widen_sl", new_sl=0.23), _view(fresh_ok=False, fresh_reason="daily_dd_switch")).reason \
        == "fresh_entry_check:daily_dd_switch"
    assert _d(_ti("widen_sl", new_sl=0.23), _view(fresh_ok=None, fresh_reason="balance_unread")).verdict \
        == "could_not_look"
    assert _d(_ti("widen_sl", new_sl=0.23), _view(max_qty=5.0)).reason.startswith(lri.R_SIZE_CAP)


def test_adds_are_capped_at_the_fresh_entry_size():
    assert _d(_ti("add_entry", size_fraction=0.5)).qty == pytest.approx(5.0)
    assert _d(_ti("change_size", size_multiplier=2.0)).qty == pytest.approx(10.0)
    assert _d(_ti("change_size", size_multiplier=4.0)).reason.startswith(lri.R_SIZE_CAP)   # 40 > 30
    assert _d(_ti("add_entry", size_fraction=0.5), _view(fresh_ok=False, fresh_reason="GROSS_EXPOSURE_CAP")).reason \
        == "fresh_entry_check:GROSS_EXPOSURE_CAP"


def test_common_refusals():
    assert _d(_ti("close"), dry=True).reason == lri.R_DRY
    assert _d(_ti("close"), _view(strategy_execution="shadow")).reason == lri.R_SHADOW
    assert _d(_ti("close"), _view(last_amend_bar="2026-10-25T18:00:00Z")).reason == lri.R_RATE
    assert _d(_ti("tighten_sl")).reason == lri.R_NOT_TRADE_ACTION
    assert _d(_ti("partial_close", size_fraction=1.0)).reason == lri.R_BAD_INPUT


def test_trade_action_precondition_needs_reason_confidence_and_target():
    assert lri.trade_action_precondition(_ti("close")) is None
    assert lri.trade_action_precondition(_ti("close", reason=" ")).endswith("reason_missing")
    assert lri.trade_action_precondition(_ti("close", confidence=None)).endswith("judgement_confidence_missing")
    assert lri.trade_action_precondition(_ti("close", mechanics_verdict="mismatch")).endswith("mechanics_mismatch")
    assert lri.trade_action_precondition(_ti("move_tp")).endswith("target_missing:new_tp")
    assert lri.trade_action_precondition(_ti("change_size", size_multiplier=1.0)).endswith("target_missing:size")
    assert lri.trade_action_precondition(_ti("close", basis="table", expected_cost_r=0.2)) is None
    assert lri.trade_action_precondition(_ti("close", basis="table")).endswith("table_ev_missing")


# --------------------------------------------------------------- the account's own risk manager

def test_fresh_entry_check_is_the_accounts_own_evaluate_and_sizer(monkeypatch):
    rm = RiskManager({}, dry_run=False, account_id="")
    order = type("O", (), {})()
    monkeypatch.setattr(rm, "evaluate", lambda o, opening=True: (False, "daily_dd_switch") if opening else (True, None))
    assert rm.fresh_entry_check(order, 1000.0) == (False, "daily_dd_switch", None)
    monkeypatch.setattr(rm, "evaluate", lambda o, opening=True: (True, None))
    assert rm.fresh_entry_check(order, None) == (None, "balance_unread", None)
    monkeypatch.setattr(rm, "position_size", lambda o, bal, **kw: 7.0)
    assert rm.fresh_entry_check(order, 1000.0) == (True, "ok", 7.0)
    assert RiskManager({}, dry_run=True, account_id="").approve_action(_ti("close"), _view()).reason == lri.R_DRY


# --------------------------------------------------------------- run(): every account class

def _tr(tid, account):
    return {**tla._trade(tid, account), "entry_price": 0.2100}


def _run(db, w, intent, granted=frozenset({lri.MANDATE_ID, lri.TRADE_MANDATE_ID}), mode="apply"):
    return lra.run(intent, apply=True, db=db, accounts=tla.ACCOUNTS, strategies=tla.STRATS,
                   review_cfg={"apply_mode": mode}, granted=set(granted), write_log=False, state={})


@pytest.fixture
def act(wired, monkeypatch):  # noqa: F811
    wired["actions"] = []
    monkeypatch.setattr(lra, "_exec_trade_action",
                        lambda db, leg, pkg, cls, v, intent: wired["actions"].append(
                            (cls, leg["account_id"], intent.action, v.level, v.qty)) or {"result": lra.X_APPLIED})
    monkeypatch.setattr(lra, "_fresh_entry", lambda aid, cfg, pkg, intent, stop, tp: (True, "ok", 100.0))
    return wired


def _by(res):
    return {a["account_id"]: a for a in res["accounts"]}


def test_close_on_every_account_class(act):
    db = tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG)
    act["tickets"] = [{"ticket_id": "t1", "account_id": "tradeify_1", "status": "filled", "sl": 0.22, "meta": None},
                      {"ticket_id": "t2", "account_id": "breakout_2", "status": "filled", "sl": 0.22, "meta": None}]
    res = _run(db, act, _ti("close"))
    by = _by(res)
    assert by["bybit_2"]["executed"] and by["alpaca_live"]["executed"]
    assert by["tradeify_1"]["reason"] == "no_action_path:close"      # prop VM: no executor
    assert by["breakout_2"]["reason"] == "no_action_path:close"      # phone: TP only
    assert sorted(a[1] for a in act["actions"]) == ["alpaca_live", "bybit_2"]
    assert res["package_sl_moved"] is False                          # a close never moves the shared stop
    assert {a for a, _ in act["alerts"]} == {"tradeify_1", "breakout_2"}   # each refusal pinged once
    assert res["writeback"]["action"] == "close"
    assert res["writeback"]["disposition"]["mandate"] == lri.TRADE_MANDATE_ID


def test_move_tp_reaches_bybit_and_phone_only(act):
    db = tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG)
    act["tickets"] = [{"ticket_id": "t2", "account_id": "breakout_2", "status": "filled", "sl": 0.22, "tp": 0.19,
                       "entry": 0.21, "meta": None}]
    res = _run(db, act, _ti("move_tp", new_tp=0.1850))
    by = _by(res)
    assert by["bybit_2"]["executed"] and by["breakout_2"]["executed"]
    assert by["alpaca_live"]["reason"] == "no_action_path:move_tp"


def test_widen_and_add_paths(act):
    db = tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG)
    by = _by(_run(db, act, _ti("widen_sl", new_sl=0.2300)))
    assert by["bybit_2"]["executed"] and by["alpaca_live"]["reason"] == "no_action_path:widen_sl"
    by = _by(_run(db, act, _ti("add_entry", size_fraction=0.5)))
    assert by["bybit_2"]["reason"] == "no_action_path:add_size"     # no add-to-position executor anywhere
    assert by["alpaca_live"]["reason"] == "no_action_path:add_size"
    by = _by(_run(db, act, _ti("change_size", size_multiplier=0.5)))
    assert by["bybit_2"]["executed"] and by["bybit_2"]["qty"] == pytest.approx(5.0)
    assert by["alpaca_live"]["reason"] == "no_action_path:reduce"


def test_widen_refused_by_the_accounts_own_fresh_entry_check(act, monkeypatch):
    monkeypatch.setattr(lra, "_fresh_entry", lambda aid, cfg, pkg, intent, stop, tp: (False, "daily_dd_switch", None))
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    by = _by(_run(db, act, _ti("widen_sl", new_sl=0.2300)))
    assert by["bybit_2"]["reason"] == "fresh_entry_check:daily_dd_switch" and not by["bybit_2"].get("executed")
    assert act["actions"] == []


def test_a_trade_action_under_the_tighten_mandate_is_refused(act):
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    res = _run(db, act, _ti("close", mandate=lri.MANDATE_ID))
    assert _by(res)["bybit_2"]["executor"]["detail"].startswith("mandate")
    assert act["actions"] == []
    res = _run(db, act, _ti("close"), granted=frozenset({lri.MANDATE_ID}))     # sibling not granted
    assert act["actions"] == [] and "not granted" in _by(res)["bybit_2"]["executor"]["detail"]


def test_no_reason_means_nothing_is_sent(act):
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    res = _run(db, act, _ti("close", reason=""))
    assert act["actions"] == [] and _by(res)["bybit_2"]["executor"]["detail"].endswith("reason_missing")


def test_recommend_mode_sends_nothing(act):
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    res = _run(db, act, _ti("close"), mode="recommend")
    assert act["actions"] == [] and _by(res)["bybit_2"]["read"] == "would_apply"


# --------------------------------------------------------------- the Bybit executor, read back

class _Ex:
    def __init__(self, monkeypatch, *, before_size=10.0, after_size=None, venue_tp=None, venue_sl=None, ok=True):
        from scripts.ops import amend_position_sl as aps
        from src.runtime import order_monitor as om
        self.sent = []
        monkeypatch.setattr(aps, "_build_client", lambda aid: (object(), {"exchange": "bybit"}))
        states = [{"read_state": "resolved", "position": {"size": before_size}, "mark": 0.2000, "venue_sl": 0.22},
                  {"read_state": "resolved", "position": ({"size": after_size} if after_size else None),
                   "mark": 0.2, "venue_sl": venue_sl}]
        monkeypatch.setattr(aps, "_venue_state", lambda *a, **k: states.pop(0) if states else states[-1])
        monkeypatch.setattr(aps, "_tick_size", lambda *a: 0.0001)
        monkeypatch.setattr(aps, "_send_modify", lambda t, **kw: self.sent.append(("modify", kw)) or {"ok": True})
        monkeypatch.setattr(lra, "_venue_tp", lambda *a: {"read_state": "resolved", "venue_tp": venue_tp})
        monkeypatch.setattr(om, "_send_close_to_exchange", lambda t: self.sent.append(("close",)) or {"ok": ok})
        monkeypatch.setattr(om, "_send_partial_close_to_exchange",
                            lambda t, q: self.sent.append(("partial", q)) or {"ok": ok})


def _leg():
    return {"kind": "trade", "account_id": "bybit_2", "row": tla._trade(1, "bybit_2")}


def test_bybit_close_is_read_back_and_journaled(monkeypatch):
    ex = _Ex(monkeypatch, after_size=None)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=10.0)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("close"))
    assert r["result"] == lra.X_APPLIED and ex.sent == [("close",)]
    tid, upd = db.trade_writes[0]
    assert upd["status"] == "closed" and upd["exit_reason"] == lra.LIVE_REVIEW_CLOSE
    assert json.loads(upd["notes"])["live_review_actions"][0]["review_id"] == "LR-20261025T2000Z-P"


def test_bybit_partial_that_the_venue_does_not_show_is_apply_failed(monkeypatch):
    _Ex(monkeypatch, after_size=10.0)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.0)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLY_FAILED and db.trade_writes == []


def test_bybit_move_tp_and_widen_read_back(monkeypatch):
    _Ex(monkeypatch, venue_tp=0.1850, after_size=10.0)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", 0.1850, "within_bounds")
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("move_tp", new_tp=0.1850))["result"] == lra.X_APPLIED
    assert db.trade_writes[0][1]["take_profit_1"] == 0.1850
    _Ex(monkeypatch, venue_sl=0.2290, after_size=10.0)                 # venue did not take the level
    v = lri.AmendVerdict("bybit_2", "approve", 0.2300, "within_bounds")
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("widen_sl", new_sl=0.23))["result"] == lra.X_APPLY_FAILED


def test_bybit_venue_refusal_is_refused_not_applied(monkeypatch):
    _Ex(monkeypatch, ok=False)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=10.0)
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("close"))["result"] == lra.X_REFUSED


def test_alpaca_close_refuses_when_the_flatten_would_hit_another_trade(monkeypatch):
    db = tla._ApplyDB([tla._trade(1, "alpaca_live"), tla._trade(2, "alpaca_live")], tla.PKG)
    leg = {"kind": "trade", "account_id": "alpaca_live", "row": tla._trade(1, "alpaca_live")}
    r = lra._exec_alpaca_close(db, leg, tla.PKG, _ti("close"))
    assert r["result"] == lra.X_REFUSED and "other open trade" in r["detail"]


# --------------------------------------------------------------- the VM dispatcher

def _row(action, **rec):
    r = {"review_id": "LR-20261026T1900Z-P", "order_package_id": "P", "mechanics": {"verdict": "match"},
         "disposition": {"route": "recommended"}, "outcome_table_source": None, "packet_sha": "ab" * 32,
         "recommendation": {"action": action, "level": None, "basis": "judgement", "evidence_source": "judgement",
                            "judgement_confidence": 0.6, "reason": "event inside the next bar", **rec}}
    return r


def test_dispatcher_hands_a_trade_action_to_the_apply_under_the_sibling_mandate():
    plan, refusal = lrd.check_row(_row("partial_close", size_fraction=0.5), None)
    assert refusal is None and plan["evidence"] == "comms/live_review/packets/LR-20261026T1900Z-P.json"
    argv = lrd.apply_argv(plan, apply=True)
    assert argv[:2] == ["--action", "partial_close"] and lri.TRADE_MANDATE_ID in argv
    assert "--size-fraction" in argv and argv[-1] == "--apply"
    plan, _ = lrd.check_row(_row("move_tp", level=0.185), None)
    assert "--new-tp" in lrd.apply_argv(plan, apply=False)


def test_dispatcher_refuses_a_trade_action_missing_a_clause():
    assert lrd.check_row(_row("close", reason=""), None)[1] == "reason_missing"
    assert lrd.check_row(_row("move_tp"), None)[1] == "level_missing"
    assert lrd.check_row(_row("close", judgement_confidence=None), None)[1] == "judgement_confidence_missing"
    bad = _row("close")
    bad["mechanics"]["verdict"] = "mismatch"
    assert lrd.check_row(bad, None)[1] == "mechanics_mismatch"
    tbl = _row("close", basis="ev_positive", evidence_source="table", ev_delta_r=0.3)
    tbl["outcome_table_source"] = "comms/live_review/tables/x.json"
    assert lrd.check_row(tbl, None)[1] == "evidence_not_committed"


def test_the_apply_cli_accepts_every_trade_action():
    import inspect
    src = inspect.getsource(lra.main)
    for flag in ("--action", "--new-tp", "--size-fraction", "--size-multiplier"):
        assert flag in src
    assert set(lri.TRADE_ACTIONS) == set(lrd.TRADE_ACTIONS)


def test_materialized_evidence_is_used_only_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(lrd, "_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(lrd, "EVIDENCE_DIR", tmp_path / "runtime_logs/live_review/evidence")
    got = lrd.materialize_evidence("comms/live_review/tables/x.json", "{}", "a" * 40)
    assert got == "runtime_logs/live_review/evidence/aaaaaaaaaaaa/comms/live_review/tables/x.json"
    assert (tmp_path / got).read_text() == "{}"
    (tmp_path / "comms/live_review/tables").mkdir(parents=True)
    (tmp_path / "comms/live_review/tables/x.json").write_text("{}")
    assert lrd.materialize_evidence("comms/live_review/tables/x.json", "{}", "a" * 40) == "comms/live_review/tables/x.json"
