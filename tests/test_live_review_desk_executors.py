"""DESK-3-EXECUTORS: the cells this row adds to ``live_review_apply.ACTION_PATHS``.

* the desk's own leg (``claude_desk``, trading-desk design § 3.8): a close / partial_close is the
  leg's own exit, journaled ``strategy_close`` on every account's existing close path (Bybit close,
  Bybit reduce, Alpaca close), never ``live_review_close``;
* a ``widen_sl`` or a size add on a desk-leg trade is refused before any read (design § 2.4);
* Alpaca ``move_tp`` (a desk ``tp_revise``): this trade's own target leg, read back, and never left
  without its stop leg (operator 2026-10-26: "nothing is supposed to remove brackets").

Every new executor reads the venue back; a failed read-back is ``apply_failed`` / ``could_not_look``,
never ``applied``, and the journal is untouched.
"""
from __future__ import annotations

import json

import pytest

from scripts.ops import live_review_apply as lra
from src.runtime import live_review_intent as lri
from src.units.accounts import alpaca_amend
from tests import test_live_review_apply as tla
from tests import test_live_review_trade_actions as tta
from tests.test_live_review_apply import wired  # noqa: F401  (fixture)

DESK_PKG = {**tla.PKG, "strategy_name": lra.DESK_LEG}
STRATS = {**tla.STRATS, lra.DESK_LEG: {"execution": "live", "timeframe": "1h"}}


def _leg(aid="bybit_2", tid=1):
    return {"kind": "trade", "account_id": aid, "row": tla._trade(tid, aid)}


def _run(db, w, intent):
    return lra.run(intent, apply=True, db=db, accounts=tla.ACCOUNTS, strategies=STRATS,
                   review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID}, write_log=False, state={})


# --------------------------------------------------------------- the cell table itself

def test_the_cell_table():
    assert lra.ACTION_PATHS["alpaca"] == frozenset({"close", "move_tp"})
    assert lra.ACTION_PATHS["bybit"] == frozenset({"close", "reduce", "move_tp", "widen_sl"})
    assert lra.ACTION_PATHS["phone"] == frozenset({"move_tp"})
    assert lra.ACTION_PATHS["prop_vm"] == frozenset() and lra.ACTION_PATHS["other"] == frozenset()
    assert lra.close_reason_for(DESK_PKG) == "strategy_close"
    assert lra.close_reason_for(tla.PKG) == lra.LIVE_REVIEW_CLOSE


# --------------------------------------------------------------- strategy_close on the desk leg

def test_bybit_close_of_a_desk_leg_is_strategy_close(monkeypatch):
    ex = tta._Ex(monkeypatch, after_size=None)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], DESK_PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=10.0)
    r = lra._exec_bybit_action(db, _leg(), DESK_PKG, v, tta._ti("close"))
    assert r["result"] == lra.X_APPLIED and ex.sent == [("close",)]
    _, upd = db.trade_writes[0]
    assert upd["status"] == "closed" and upd["exit_reason"] == "strategy_close"
    assert json.loads(upd["notes"])["live_review_actions"][0]["close_reason"] == "strategy_close"


def test_bybit_partial_of_a_desk_leg_records_strategy_close_and_keeps_both_brackets(monkeypatch):
    tta._Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=0.19)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], DESK_PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=4.0)
    r = lra._exec_bybit_action(db, _leg(), DESK_PKG, v, tta._ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLIED
    _, upd = db.trade_writes[0]
    assert upd["position_size"] == pytest.approx(6.0) and "exit_reason" not in upd
    assert json.loads(upd["notes"])["live_review_actions"][0]["close_reason"] == "strategy_close"
    # the same partial that loses the TP at the venue: apply_failed, nothing journaled
    tta._Ex(monkeypatch, after_size=6.0, venue_sl=0.22, venue_tp=None)
    db2 = tla._ApplyDB([tla._trade(1, "bybit_2")], DESK_PKG)
    r = lra._exec_bybit_action(db2, _leg(), DESK_PKG, v, tta._ti("partial_close", size_fraction=0.4))
    assert r["result"] == lra.X_APPLY_FAILED and r["detail"].startswith("both_brackets_required:tp")
    assert db2.trade_writes == []


def test_bybit_close_read_back_failure_is_apply_failed_not_closed(monkeypatch):
    tta._Ex(monkeypatch, after_size=None)
    from scripts.ops import amend_position_sl as aps
    states = [{"read_state": "resolved", "position": {"size": 10.0}, "mark": 0.2, "venue_sl": 0.22},
              {"read_state": "read_failed", "position": None, "venue_sl": None}]
    monkeypatch.setattr(aps, "_venue_state", lambda *a, **k: states.pop(0))
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], DESK_PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=10.0)
    r = lra._exec_bybit_action(db, _leg(), DESK_PKG, v, tta._ti("close"))
    assert r["result"] == lra.X_APPLY_FAILED and db.trade_writes == []


def test_strategy_trades_keep_live_review_close(monkeypatch):
    tta._Ex(monkeypatch, after_size=None)
    db = tla._ApplyDB([tla._trade(1, "bybit_2")], tla.PKG)
    v = lri.AmendVerdict("bybit_2", "approve", None, "within_bounds", qty=10.0)
    lra._exec_bybit_action(db, _leg(), tla.PKG, v, tta._ti("close"))
    assert db.trade_writes[0][1]["exit_reason"] == lra.LIVE_REVIEW_CLOSE


def test_alpaca_close_of_a_desk_leg_is_strategy_close(monkeypatch):
    from src.runtime import order_monitor as om
    from src.units.accounts import clients
    monkeypatch.setattr(om, "_send_close_to_exchange", lambda t: {"ok": True})
    monkeypatch.setattr(clients, "account_open_positions", lambda cfg: [])
    monkeypatch.setattr(lra, "_accounts", lambda: tla.ACCOUNTS)
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_close(db, _leg("alpaca_live"), DESK_PKG, tta._ti("close"))
    assert r["result"] == lra.X_APPLIED
    assert db.trade_writes[0][1]["exit_reason"] == "strategy_close"
    # read-back failure (positions unreadable) -> apply_failed, never closed in the journal
    monkeypatch.setattr(clients, "account_open_positions", lambda cfg: None)
    db2 = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_close(db2, _leg("alpaca_live"), DESK_PKG, tta._ti("close"))
    assert r["result"] == lra.X_APPLY_FAILED and db2.trade_writes == []


# --------------------------------------------------------------- never on a desk leg

@pytest.fixture
def act(wired, monkeypatch):  # noqa: F811
    wired["actions"] = []
    monkeypatch.setattr(lra, "_exec_trade_action",
                        lambda db, leg, pkg, cls, v, intent: wired["actions"].append(
                            (cls, leg["account_id"], intent.action)) or {"result": lra.X_APPLIED})
    wired["fresh_calls"] = []
    monkeypatch.setattr(lra, "_fresh_entry", lambda aid, cfg, pkg, intent, stop, tp: wired["fresh_calls"].append(
        aid) or (True, "ok", 100.0))
    return wired


def test_widen_and_add_are_refused_on_a_desk_leg_before_any_read(act):
    db = tla._ApplyDB([tta._tr(1, "bybit_2"), tta._tr(2, "alpaca_live")], DESK_PKG)
    res = _run(db, act, tta._ti("widen_sl", new_sl=0.2300))
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["bybit_2"]["reason"] == "desk_leg_never:widen_sl"
    assert by["alpaca_live"]["reason"] == "desk_leg_never:widen_sl"
    res = _run(db, act, tta._ti("add_entry", size_multiplier=1.5))
    assert {a["reason"] for a in res["accounts"]} == {"desk_leg_never:add_size"}
    assert act["actions"] == [] and act["fresh_calls"] == []      # nothing sent, nothing read
    # the same widen on a STRATEGY trade still reaches bybit's executor
    db = tla._ApplyDB([tta._tr(1, "bybit_2")], tla.PKG)
    res = _run(db, act, tta._ti("widen_sl", new_sl=0.2300))
    assert res["accounts"][0]["executed"]


def test_desk_close_and_partial_reach_bybit_and_alpaca(act):
    db = tla._ApplyDB([tta._tr(1, "bybit_1"), tta._tr(2, "alpaca_live")], DESK_PKG)
    accounts = {**tla.ACCOUNTS, "bybit_1": {"exchange": "bybit", "mode": "live", "risk": {}}}
    res = lra.run(tta._ti("close"), apply=True, db=db, accounts=accounts, strategies=STRATS,
                  review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID}, write_log=False, state={})
    assert sorted(a[1] for a in act["actions"]) == ["alpaca_live", "bybit_1"]
    act["actions"].clear()
    res = lra.run(tta._ti("partial_close", size_fraction=0.5), apply=True, db=db, accounts=accounts,
                  strategies=STRATS, review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID},
                  write_log=False, state={})
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["bybit_1"]["executed"]
    assert by["alpaca_live"]["reason"] == "no_action_path:reduce"   # not built: the brackets hold every share


# --------------------------------------------------------------- the Alpaca move_tp cell

class _Alp:
    """Fake ``alpaca_amend.tighten``: a plan read, then an apply."""

    def __init__(self, monkeypatch, *, plan=None, applied=None, client=object()):
        self.calls = []
        stop = {"id": "s1", "price": 0.22}
        self.plan = plan or {"result": alpaca_amend.X_PLANNED, "before": {"stop_leg": stop}}
        self.applied = applied or {"result": alpaca_amend.X_APPLIED, "after": {"stop_leg": stop},
                                   "venue_tp_after": 0.185, "oco_leg_ids_after": {"stop": "s1", "target": "t9"}}

        def tighten(client, *, apply=False, **kw):
            self.calls.append(("apply" if apply else "plan", kw.get("new_tp")))
            return dict(self.applied if apply else self.plan)
        monkeypatch.setattr(alpaca_amend, "tighten", tighten)
        monkeypatch.setattr(lra, "_alpaca_client", lambda aid: client)


def _tp_verdict():
    return lri.AmendVerdict("alpaca_live", "approve", 0.185, "within_bounds")


def test_alpaca_move_tp_applies_and_journals_after_read_back(monkeypatch):
    a = _Alp(monkeypatch)
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_APPLIED and a.calls == [("plan", 0.185), ("apply", 0.185)]
    _, upd = db.trade_writes[0]
    assert upd["take_profit_1"] == 0.185
    assert json.loads(upd["notes"])["live_review_actions"][0]["action"] == "move_tp"


def test_alpaca_move_tp_refused_when_the_stop_leg_is_not_resting(monkeypatch):
    a = _Alp(monkeypatch, plan={"result": alpaca_amend.X_PLANNED, "before": {"stop_leg": None}})
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_REFUSED and r["detail"].startswith("both_brackets_required:sl")
    assert a.calls == [("plan", 0.185)] and db.trade_writes == []      # no PATCH sent


def test_alpaca_move_tp_that_loses_the_stop_is_apply_failed(monkeypatch):
    _Alp(monkeypatch, applied={"result": alpaca_amend.X_APPLIED, "after": {"stop_leg": None},
                               "venue_tp_after": 0.185})
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_APPLY_FAILED and r["detail"].startswith("both_brackets_required:sl")
    assert db.trade_writes == []


def test_alpaca_move_tp_read_back_mismatch_is_apply_failed(monkeypatch):
    _Alp(monkeypatch, applied={"result": alpaca_amend.X_APPLY_FAILED,
                               "detail": "venue reads target 0.19 after the amend, not 0.185"})
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_APPLY_FAILED and db.trade_writes == []


def test_alpaca_move_tp_unread_venue_is_could_not_look(monkeypatch):
    _Alp(monkeypatch, plan={"result": alpaca_amend.X_COULD_NOT_LOOK, "detail": "open orders read failed"})
    db = tla._ApplyDB([tla._trade(1, "alpaca_live")], DESK_PKG)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_COULD_NOT_LOOK and db.trade_writes == []
    _Alp(monkeypatch, client=None)
    r = lra._exec_alpaca_tp(db, _leg("alpaca_live"), DESK_PKG, _tp_verdict(), tta._ti("move_tp", new_tp=0.185))
    assert r["result"] == lra.X_COULD_NOT_LOOK


def test_alpaca_move_tp_failure_surfaces_through_run_never_silent(wired, monkeypatch):  # noqa: F811
    _Alp(monkeypatch, applied={"result": alpaca_amend.X_APPLIED, "after": {"stop_leg": None},
                               "venue_tp_after": 0.185})
    accounts = {**tla.ACCOUNTS, "alpaca_live": {**tla.ACCOUNTS["alpaca_live"], "account_class": "real_money"}}
    db = tla._ApplyDB([tta._tr(1, "alpaca_live")], DESK_PKG)
    res = lra.run(tta._ti("move_tp", new_tp=0.185), apply=True, db=db, accounts=accounts, strategies=STRATS,
                  review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID}, write_log=False, state={})
    rec = res["accounts"][0]
    assert rec["executor"]["result"] == lra.X_APPLY_FAILED and not rec["executed"]
    assert res["exit"] == lra.EXIT_FAILED
    assert [a for a, _ in wired["alerts"]] == ["alpaca_live"]      # ONE flag on a real-money account
    assert res["writeback"]["applied"] is False
