"""LTR-ALL-ACTIONS: every trade action x every account class, including the refusals.

Operator 2026-10-26 (mandate MD-TRADE-DESK, verbatim): "we also need to expand the desks
mandate so include all trade actions, as long as they have reasoning and confidence attached";
accounts "All accounts now". Each account decides through its OWN RiskManager.approve_action; an
action that adds risk passes the same check a fresh entry would; an account with no executor for
an action is still decided by its own RiskManager; the executor router reports "no executor wired"
(AM-PROP-VM-ACTION-MATRIX removed, operator 2026-11-12).
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


def test_no_action_may_leave_a_leg_without_both_brackets():
    """Operator 2026-10-26: "every trade always must have BOTH brackets ... nothing is supposed to remove brackets"."""
    for act, kw in (("partial_close", {"size_fraction": 0.5}), ("change_size", {"size_multiplier": 0.5}),
                    ("change_size", {"size_multiplier": 2.0}), ("add_entry", {"size_fraction": 0.5}),
                    ("widen_sl", {"new_sl": 0.23}), ("move_tp", {"new_tp": 0.18})):
        assert _d(_ti(act, **kw), _view(leg_tp=None if act != "move_tp" else 0.19, leg_sl=None if act == "move_tp" else 0.22)
                  ).reason.startswith(lri.R_BRACKETS), act
    assert _d(_ti("partial_close", size_fraction=0.5), _view(leg_sl=None)).reason == "both_brackets_required:sl"
    assert _d(_ti("close"), _view(leg_tp=None, leg_sl=None)).verdict == "approve"   # a close removes the position


def test_widen_sl_passes_the_fresh_entry_check_or_is_refused():
    ok = _d(_ti("widen_sl", new_sl=0.2300))
    assert ok.verdict == "approve" and ok.level == 0.2300
    assert _d(_ti("widen_sl", new_sl=0.2150)).reason == lri.R_NOT_WIDER
    assert _d(_ti("widen_sl", new_sl=0.1990)).reason == lri.R_WRONG_SIDE
    assert _d(_ti("widen_sl", new_sl=0.23), _view(leg_tp=None)).reason == "both_brackets_required:tp"
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


def test_no_per_bar_cap_on_trade_actions():
    """REMOVE-PER-BAR-CAP: a move_tp then a partial_close on the same bar, two review ids, both pass."""
    a = _d(_ti("move_tp", new_tp=0.185, review_id="LR-20261025T1805Z-P"))
    b = _d(_ti("partial_close", size_fraction=0.5, review_id="LR-20261025T1830Z-P"),
           _view(applied_review_ids=("LR-20261025T1805Z-P",)))
    assert a.ok and b.ok, (a, b)


def test_common_refusals():
    assert _d(_ti("close"), dry=True).reason == lri.R_DRY
    assert _d(_ti("close"), _view(strategy_execution="shadow")).reason == lri.R_SHADOW
    rid = _ti("close").review_id
    assert _d(_ti("close"), _view(applied_review_ids=(rid,))).reason == lri.R_DUPLICATE
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
    # AM-PROP-VM-ACTION-MATRIX: REMOVE (operator 2026-11-12). The prop VM account decides the close through its own
    # RiskManager and reaches the executor router (stubbed here); no matrix refusal before the decision.
    assert by["tradeify_1"]["executed"] and by["tradeify_1"]["reason"] != "no_action_path:close"
    # phone: a close reaches the phone's server-issued action channel (operator 2026-11-09; was "TP only")
    assert by["breakout_2"]["executed"] and by["breakout_2"].get("reason") != "no_action_path:close"
    assert sorted(a[1] for a in act["actions"]) == ["alpaca_live", "breakout_2", "bybit_2", "tradeify_1"]
    assert res["package_sl_moved"] is False                          # a close never moves the shared stop
    assert act["alerts"] == []                                       # nothing refused before the decision
    assert res["writeback"]["action"] == "close"
    assert res["writeback"]["disposition"]["mandate"] == lri.TRADE_MANDATE_ID


def test_move_tp_reaches_bybit_alpaca_and_phone(act):
    db = tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG)
    act["tickets"] = [{"ticket_id": "t1", "account_id": "tradeify_1", "status": "filled", "sl": 0.22, "tp": 0.19,
                       "entry": 0.21, "meta": None},
                      {"ticket_id": "t2", "account_id": "breakout_2", "status": "filled", "sl": 0.22, "tp": 0.19,
                       "entry": 0.21, "meta": None}]
    res = _run(db, act, _ti("move_tp", new_tp=0.1850))
    by = _by(res)
    assert by["bybit_2"]["executed"] and by["breakout_2"]["executed"]
    assert by["alpaca_live"]["executed"]                              # DESK-3: alpaca move_tp cell
    # tradeify_1 is a VM prop account: since PROP-BRACKET-APPLY (operator 2026-11-11) move_tp has a path for the class, so
    # the cell reaches the executor (stubbed here). The per-account refusal (browser dxtrade cannot amend a TP) is the
    # executor's, pinned in tests/test_prop_bracket_request.py::test_live_review_prop_vm_move_tp_...
    assert by["tradeify_1"]["executed"] and by["tradeify_1"]["account_class"] == "prop_vm"
    assert ("prop_vm", "tradeify_1", "move_tp", 0.185, None) in act["actions"]


def test_widen_and_add_paths(act):
    db = tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG)
    # AM-PROP-VM-ACTION-MATRIX removed 2026-11-12: every account decides; the executor router (stubbed here) is the
    # only place "no executor wired" is answered (see the routing tests below).
    by = _by(_run(db, act, _ti("widen_sl", new_sl=0.2300)))
    assert by["bybit_2"]["executed"] and by["alpaca_live"]["executed"]
    by = _by(_run(db, act, _ti("add_entry", size_fraction=0.5)))
    assert by["bybit_2"]["executed"] and by["alpaca_live"]["executed"]
    assert by["bybit_2"]["qty"] == pytest.approx(5.0)                # still capped at the fresh-entry size
    by = _by(_run(db, act, _ti("change_size", size_multiplier=0.5)))
    assert by["bybit_2"]["executed"] and by["bybit_2"]["qty"] == pytest.approx(5.0)
    assert by["alpaca_live"]["executed"]


# --------------------------------------------------------------- the executor router (AM-PROP-VM-ACTION-MATRIX)

def _route_leg(aid, kind):
    return {"account_id": aid, "kind": kind, "row": {"account_id": aid, "ticket_id": "t1", "id": 1}}


@pytest.mark.parametrize("cls,aid,kind,action,kw", [
    ("prop_vm", "tradeify_1", "ticket", "close", {}),
    ("prop_vm", "tradeify_1", "ticket", "widen_sl", {"new_sl": 0.23}),
    ("alpaca", "alpaca_live", "trade", "partial_close", {"size_fraction": 0.5}),
    ("bybit", "bybit_2", "trade", "add_entry", {"size_fraction": 0.5}),
    ("other", "ib_paper", "trade", "close", {}),
])
def test_an_approved_action_with_no_executor_wired_is_reported_not_sent(monkeypatch, cls, aid, kind, action, kw):
    called = []
    for name in ("_exec_bybit_action", "_exec_alpaca_close", "_exec_alpaca_tp", "_exec_phone_tp",
                 "_exec_prop_vm_tp", "_exec_phone_sl_widen", "_exec_phone_close"):
        monkeypatch.setattr(lra, name, lambda *a, _n=name, **k: called.append(_n) or {"result": lra.X_APPLIED})
    v = lri.AmendVerdict(aid, lri.V_APPROVE, 0.23, "within_bounds", qty=5.0)
    out = lra._exec_trade_action(None, _route_leg(aid, kind), {"order_package_id": "P"}, cls, v, _ti(action, **kw))
    assert out["result"] == lra.X_REFUSED and "no executor wired" in out["detail"]
    assert called == []   # an approved add never reaches the Bybit reduce branch


def test_an_approved_action_with_an_executor_reaches_it(monkeypatch):
    called = []
    monkeypatch.setattr(lra, "_exec_bybit_action", lambda *a, **k: called.append("bybit") or {"result": lra.X_APPLIED})
    monkeypatch.setattr(lra, "_exec_phone_close", lambda *a, **k: called.append("phone") or {"result": lra.X_APPLIED})
    v = lri.AmendVerdict("bybit_2", lri.V_APPROVE, None, "within_bounds", qty=10.0)
    assert lra._exec_trade_action(None, _route_leg("bybit_2", "trade"), {}, "bybit", v, _ti("close"))["result"] == lra.X_APPLIED
    assert lra._exec_trade_action(None, _route_leg("breakout_2", "ticket"), {}, "phone", v, _ti("close"))["result"] \
        == lra.X_APPLIED
    assert called == ["bybit", "phone"]


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
        last = dict(states[-1])
        monkeypatch.setattr(aps, "_venue_state", lambda *a, **k: states.pop(0) if states else last)
        monkeypatch.setattr(aps, "_tick_size", lambda *a: 0.0001)
        monkeypatch.setattr(aps, "_send_modify", lambda t, **kw: self.sent.append(("modify", kw)) or {"ok": True})
        monkeypatch.setattr(lra, "_venue_tp", lambda *a: {"read_state": "resolved", "venue_tp": venue_tp})
        monkeypatch.setattr(om, "_send_close_to_exchange", lambda t: self.sent.append(("close",)) or {"ok": ok})
        monkeypatch.setattr(om, "_send_partial_close_to_exchange",
                            lambda t, q: self.sent.append(("partial", q)) or {"ok": ok})
        self.resized = []
        monkeypatch.setattr(lra, "resize_legs_after_reduce",
                            lambda c, cfg, t, rem: self.resized.append(rem) or
                            {"legs": {}, "readback": {}, "ok": True, "detail": "resized and read back"})


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
    _Ex(monkeypatch, venue_tp=0.1850, after_size=10.0, venue_sl=0.22)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", 0.1850, "within_bounds")
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("move_tp", new_tp=0.1850))["result"] == lra.X_APPLIED
    assert db.trade_writes[0][1]["take_profit_1"] == 0.1850
    _Ex(monkeypatch, venue_sl=0.2290, venue_tp=0.19, after_size=10.0)  # venue did not take the level
    v = lri.AmendVerdict("bybit_2", "approve", 0.2300, "within_bounds")
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("widen_sl", new_sl=0.23))["result"] == lra.X_APPLY_FAILED


def test_bybit_reduce_that_loses_a_bracket_is_apply_failed(monkeypatch):
    _Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=None)       # size right, TP gone
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.0)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLY_FAILED and r["detail"].startswith("both_brackets_required:tp") and db.trade_writes == []
    _Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=0.19)
    assert lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.4))["result"] == lra.X_APPLIED


def test_a_tighten_may_still_name_the_superseded_alias():
    assert lri.MANDATE_ID in lri.TIGHTEN_MANDATE_IDS and lri.TRADE_MANDATE_ID == "MD-TRADE-DESK"


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


# --------------------------------------------------------------- the VM rows watcher + paper scope

def test_the_rows_watcher_dispatches_every_trade_action_and_a_paper_row(monkeypatch):
    """The watcher used to send only tighten_sl, so no trade action could ever reach the VM.
    Tests the path a class takes once it GRADUATES (every class is advice only until its own test passes,
    operator 2026-10-28; tests/test_tighten_advice_only.py), so the advice-only set is emptied here."""
    from src.runtime import live_review_rows as rows_lib
    from src.runtime import live_review_rows_watch as w
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())
    for a in lri.TRADE_ACTIONS:
        assert w.dispatchable({"recommendation": {"action": a}, "disposition": {"route": "recommended"}}) is None
    assert w.dispatchable({"recommendation": {"action": "hold"}, "disposition": {"route": "none"}}) == "action_hold"
    paper = _row("close")
    paper["account_reads"] = [{"account_id": "bybit_1", "account_class": "paper", "read": "would_apply", "evidence": "x"}]
    assert w.dispatchable(paper) is None


def test_a_paper_only_trade_action_is_dispatched_and_its_refusal_is_not_pinged():
    """Operator 2026-10-26 "All accounts now" ("Real-money, prop and paper at once"): paper is in scope."""
    paper = _row("partial_close", size_fraction=0.5)
    paper["account_reads"] = [{"account_id": "bybit_1", "account_class": "paper", "read": "would_apply", "evidence": "x"}]
    plan, refusal = lrd.check_row(paper, None)
    assert refusal is None and plan["action"] == "partial_close"
    assert lrd.is_money_row(paper) is False          # a paper refusal goes in the brief, not a ping


def test_a_venue_deferred_close_exits_deferred_and_records_the_disposition(wired, monkeypatch):  # noqa: F811
    """ALPACA-LIVE-MECHANICS 2026-11-06: an Alpaca close while us_equity is closed is DEFERRED (exit 4, route
    `deferred`), never `refused` -- so the intake re-dispatches it instead of dropping it."""
    monkeypatch.setattr(lra, "_exec_trade_action", lambda db, leg, pkg, cls, v, intent: (
        {"result": lra.X_DEFERRED, "detail": "venue deferred: us_equity market closed"}
        if cls == "alpaca" else {"result": lra.X_APPLIED}))
    monkeypatch.setattr(lra, "_fresh_entry", lambda aid, cfg, pkg, intent, stop, tp: (True, "ok", 100.0))
    wired["tickets"] = []
    res = _run(tla._ApplyDB([_tr(2, "alpaca_live")], tla.PKG), wired, _ti("close"))
    assert res["exit"] == lri.EXIT_DEFERRED
    assert _by(res)["alpaca_live"]["read"] == "deferred" and not _by(res)["alpaca_live"]["executed"]
    disp = res["writeback"]["disposition"]
    assert disp["route"] == "deferred" and "market closed" in disp["deferred_reason"] and disp["applied_at"] is None
    # an account that applied while another deferred: the applied leg is recorded, the exit still says retry
    res = _run(tla._ApplyDB([_tr(1, "bybit_2"), _tr(2, "alpaca_live")], tla.PKG), wired, _ti("close"))
    assert _by(res)["bybit_2"]["executed"] and res["exit"] == lri.EXIT_DEFERRED
    assert res["writeback"]["disposition"]["route"] == "auto_applied" or res["writeback"]["applied"]


def test_bybit_reduce_is_floored_to_the_venue_lot_step(monkeypatch):
    """2026-11-09: 0.5 x 32478.5 XRP sent "16239.25" to bybit_portfolio and Bybit refused it (Qty invalid,
    ErrCode 10001). The reduce is floored to the lot step before it is sent; a sub-minimum reduce is refused."""
    from src.units.accounts import qty_legalize as ql
    monkeypatch.setattr(ql, "_resolve_venue_lot_rule", lambda *a, **k: (0.1, 0.1, None, None, "test"))
    ex = _Ex(monkeypatch, after_size=5.7, venue_sl=0.22, venue_tp=0.19)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.25)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.425))
    assert r["result"] == lra.X_APPLIED and ex.sent == [("partial", pytest.approx(4.2))]
    ex = _Ex(monkeypatch, after_size=10.0)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=0.05)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.005))
    assert r["result"] == lra.X_REFUSED and ex.sent == []


# --------------------------------------------------------------- partial close resizes the protective legs
# TRADE-ACTION-FAST-PATH follow-up (operator 2026-11-09 "we just need to fix the partial close mechanism"): the XRP
# 50% partial left a 107.6 SL leg on bybit_2's 53.8 position; the reduce now resizes THIS row's legs and reads back.

def test_a_partial_close_resizes_the_rows_legs_to_the_remaining_size(monkeypatch):
    ex = _Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=0.19)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.0)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLIED and ex.resized == [pytest.approx(6.0)]
    audit = json.loads(db.trade_writes[0][1]["notes"])["live_review_actions"][0]
    assert audit["leg_resize"]["ok"] is True


def test_a_failed_leg_resize_keeps_the_reduce_applied_and_alerts_once(monkeypatch):
    _Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=0.19)
    monkeypatch.setattr(lra, "resize_legs_after_reduce",
                        lambda *a: {"legs": {"sl": {"state": "failed"}}, "readback": None, "ok": False,
                                    "detail": "sl:failed(Qty invalid)"})
    alerts = []
    monkeypatch.setattr(lra, "_alert", lambda pkg, aid, line: alerts.append((aid, line)))
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.0)
    r = lra._exec_bybit_action(db, _leg(), tla.PKG, v, _ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLIED            # the reduce happened: never retried as a failure
    assert db.trade_writes[0][1]["position_size"] == pytest.approx(6.0)
    assert len(alerts) == 1 and "not resized to 6" in alerts[0][1]


class _Book:
    """A Bybit open-orders book: {orderId: qty}."""
    def __init__(self, legs):
        self.legs = dict(legs)

    def get_open_orders(self, **kw):
        return {"result": {"list": [{"orderId": k, "qty": str(v)} for k, v in self.legs.items()]}}


def _seam(book, states=None):
    def f(client, cfg, *, symbol, new_qty, sl_order_id=None, tp_order_id=None, trade_id=None):
        out = {}
        for k, oid in (("sl", sl_order_id), ("tp", tp_order_id)):
            st = (states or {}).get(k, "resized")
            if oid is None:
                out[k] = {"state": "no_tracked_id", "order_id": None, "qty_sent": None, "error": None}
                continue
            if st == "resized":
                book.legs[oid] = new_qty
            out[k] = {"state": st, "order_id": oid, "qty_sent": str(new_qty) if st == "resized" else None,
                      "error": None if st == "resized" else "Qty invalid"}
        return out
    return f


def _xrp_row(**kw):
    return {"id": 7, "symbol": "XRPUSDT", "sl_order_id": "S1", "tp_order_id": "T1", **kw}


def test_resize_legs_reads_back_each_resized_leg(monkeypatch):
    from src.units.accounts import execute
    book = _Book({"S1": 107.6, "T1": 107.6})
    monkeypatch.setattr(execute, "resize_tracked_protective_legs", _seam(book))
    monkeypatch.setattr(execute, "_bybit_category", lambda cfg: "linear")
    rz = lra.resize_legs_after_reduce(book, {"exchange": "bybit"}, _xrp_row(), 53.8)
    assert rz["ok"] is True and rz["readback"] == {"S1": 53.8, "T1": 53.8}


def test_resize_legs_flags_a_venue_refusal_and_a_readback_mismatch(monkeypatch):
    from src.units.accounts import execute
    monkeypatch.setattr(execute, "_bybit_category", lambda cfg: "linear")
    book = _Book({"S1": 107.6, "T1": 107.6})
    monkeypatch.setattr(execute, "resize_tracked_protective_legs", _seam(book, {"sl": "failed"}))
    rz = lra.resize_legs_after_reduce(book, {}, _xrp_row(), 53.8)
    assert rz["ok"] is False and "sl:failed" in rz["detail"]
    # accepted, but the venue still shows the old size: a mismatch, never "resized"
    book2 = _Book({"S1": 107.6})

    def lying(client, cfg, **kw):
        return {"sl": {"state": "resized", "order_id": "S1", "qty_sent": "53.8", "error": None},
                "tp": {"state": "no_tracked_id", "order_id": None, "qty_sent": None, "error": None}}
    monkeypatch.setattr(execute, "resize_tracked_protective_legs", lying)
    rz2 = lra.resize_legs_after_reduce(book2, {}, _xrp_row(tp_order_id=None), 53.8)
    assert rz2["ok"] is False and "readback:S1 reads 107.6" in rz2["detail"]
