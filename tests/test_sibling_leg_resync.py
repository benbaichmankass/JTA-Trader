"""PI-20261124-RORTRAIL-0001 (Tier 2): package-level actions must reach EVERY leg of the package.

Case 1 (pkg-b7456c45491e44c2, ml_entry ADAUSDT long): the trail amended bybit_2 and wrote the package stop
0.5 s BEFORE the bybit_portfolio mirror's trade row existed, so the fan-out never saw the mirror; the package
stop then read as already moved and the mirror kept its entry-time stop (0.14299 vs 0.14421) for 13 h.
Case 2 (LR-20261124T0307Z): the live-review CLOSE skipped that mirror because its mechanics read "mismatch"
(the very SL divergence of case 1), although a close does not depend on a bracket level.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from scripts.ops import live_review_dispatch as d
from src.runtime import order_monitor as om

PKG = "pkg-b7456c45491e44c2"


class FakeDB:
    def __init__(self, trades):
        self.trades = trades
        self.trade_writes: List[tuple] = []

    def get_trades(self, filters=None, limit=None):
        rows = self.trades
        for k, v in (filters or {}).items():
            rows = [r for r in rows if str(r.get(k)) == str(v)]
        return [dict(r) for r in rows]

    def update_trade(self, tid, upd):
        self.trade_writes.append((tid, upd))


def _leg(tid, acct, sl, tp=0.1568, notes=None):
    return {"id": tid, "account_id": acct, "order_package_id": PKG, "status": "open", "stop_loss": sl,
            "take_profit_1": tp, "position_size": 1.0, "symbol": "ADAUSDT", "direction": "long",
            "strategy_name": "ml_entry", "is_backtest": 0, "notes": json.dumps(notes) if notes else None}


def _pkg(sl=0.14421071, tp=0.1568, meta=None):
    return {"order_package_id": PKG, "linked_trade_id": 8459, "status": "open", "sl": sl, "tp": tp,
            "strategy_name": "ml_entry", "symbol": "ADAUSDT", "direction": "long", "meta": meta or {}}


@pytest.fixture(autouse=True)
def _clear():
    om._RESYNC_NEXT_TRY.clear()


def _capture(monkeypatch, ok=True):
    sent: List[Dict[str, Any]] = []

    def fake(leg, **kw):
        sent.append({"account": leg["account_id"], **kw})
        return {"ok": ok, "error": None if ok else "boom"}
    monkeypatch.setattr(om, "_send_modify_to_exchange", fake)
    return sent


def test_case1_mirror_that_missed_the_trail_is_brought_to_the_package_stop(monkeypatch):
    sent = _capture(monkeypatch)
    db = FakeDB([_leg(8459, "bybit_2", 0.14421071), _leg(8460, "bybit_portfolio", 0.14299)])
    out = om._resync_package_legs(db, _pkg())
    assert [s["account"] for s in sent] == ["bybit_portfolio"]          # only the lagging sibling
    assert sent[0]["sl"] == pytest.approx(0.14421071)
    assert out[0]["outcome"] == "applied"
    assert db.trade_writes == [(8460, {"stop_loss": pytest.approx(0.14421071)})]


def test_parity_every_open_leg_ends_on_the_package_stop(monkeypatch):
    _capture(monkeypatch)
    legs = [_leg(1, "bybit_2", 0.14299), _leg(2, "bybit_portfolio", 0.14299), _leg(3, "bybit_1", 0.14421071)]
    db = FakeDB(legs)
    om._resync_package_legs(db, _pkg())
    synced = {tid: u["stop_loss"] for tid, u in db.trade_writes}
    assert set(synced) == {1, 2}
    assert all(v == pytest.approx(0.14421071) for v in synced.values())


def test_in_sync_and_tighter_legs_are_never_touched(monkeypatch):
    sent = _capture(monkeypatch)
    db = FakeDB([_leg(1, "bybit_2", 0.14421071), _leg(2, "bybit_portfolio", 0.1450)])   # equal, tighter
    assert om._resync_package_legs(db, _pkg()) == []
    assert sent == []


def test_a_reviewed_widen_is_not_undone(monkeypatch):
    sent = _capture(monkeypatch)
    widened = {"sl_floor": {"level": 0.1420, "action": "widen_sl", "source": "x"}}
    db = FakeDB([_leg(1, "bybit_2", 0.1420, notes=widened)])
    assert om._resync_package_legs(db, _pkg()) == [] and sent == []


def test_short_direction_is_mirrored(monkeypatch):
    sent = _capture(monkeypatch)
    leg = _leg(1, "bybit_portfolio", 0.1600)
    leg["direction"] = "short"
    p = _pkg(sl=0.1580)
    om._resync_package_legs(FakeDB([leg]), p)
    assert sent and sent[0]["sl"] == pytest.approx(0.1580)


def test_tp_moved_by_the_monitor_reaches_a_lagging_leg_but_not_a_reviewed_one(monkeypatch):
    sent = _capture(monkeypatch)
    meta = {"last_tp_move": {"ts": "2026-11-24T00:03:58+00:00", "from": 0.1568, "to": 0.16}}
    reviewed = {"live_review_actions": [{"action": "move_tp", "review_id": "LR-1"}]}
    db = FakeDB([_leg(1, "bybit_portfolio", 0.14421071, tp=0.1568),
                 _leg(2, "bybit_2", 0.14421071, tp=0.1700, notes=reviewed)])
    om._resync_package_legs(db, _pkg(tp=0.16, meta=meta))
    assert [s["account"] for s in sent] == ["bybit_portfolio"] and sent[0]["tp"] == pytest.approx(0.16)
    # no recorded monitor TP move -> a differing leg TP is left alone
    sent.clear()
    om._resync_package_legs(FakeDB([_leg(1, "bybit_portfolio", 0.14421071, tp=0.1568)]), _pkg(tp=0.16))
    assert sent == []


def test_failure_leaves_db_unchanged_and_backs_off(monkeypatch):
    sent = _capture(monkeypatch, ok=False)
    db = FakeDB([_leg(8460, "bybit_portfolio", 0.14299)])
    out = om._resync_package_legs(db, _pkg(), now=1000.0)
    assert out[0]["outcome"] == "failed" and db.trade_writes == []
    om._resync_package_legs(db, _pkg(), now=1100.0)          # inside the back-off: no second venue call
    assert len(sent) == 1
    om._resync_package_legs(db, _pkg(), now=1400.0)          # after it: retried
    assert len(sent) == 2


def test_unreadable_leg_read_does_nothing(monkeypatch):
    sent = _capture(monkeypatch)

    class Bad(FakeDB):
        def get_trades(self, *a, **k):
            raise RuntimeError("locked")
    assert om._resync_package_legs(Bad([]), _pkg()) == [] and sent == []


# ---- case 2: the close must reach the mirror whose only mismatch is a bracket level -----------------

ROW = {
    "mechanics": {"verdict": "mismatch", "evidence": "bybit_portfolio: venue SL 0.143 != package SL 0.14421071",
                  "per_account": {
                      "bybit_2": {"verdict": "match", "evidence": None, "by_design": None},
                      "bybit_portfolio": {"verdict": "mismatch", "level_only": True,
                                          "evidence": "bybit_portfolio: venue SL 0.143 != package SL 0.14421071",
                                          "by_design": None}}}}


def test_case2_close_and_partial_close_include_the_level_only_mismatch():
    for act in ("close", "partial_close"):
        scope, skipped, refusal = d.mechanics_scope(ROW, act)
        assert refusal is None and scope == ["bybit_2", "bybit_portfolio"] and skipped == {}


def test_case2_tighten_and_other_actions_still_skip_it():
    for act in (None, "tighten_sl", "move_tp", "widen_sl"):
        scope, skipped, _ = d.mechanics_scope(ROW, act)
        assert scope == ["bybit_2"] and "bybit_portfolio" in skipped


def test_case2_a_missing_position_mismatch_still_skips_even_a_close():
    row = copy.deepcopy(ROW)
    row["mechanics"]["per_account"]["bybit_portfolio"] = {
        "verdict": "mismatch", "level_only": False, "evidence": "journal open but no ADAUSDT position at the venue"}
    scope, skipped, _ = d.mechanics_scope(row, "close")
    assert scope == ["bybit_2"] and "bybit_portfolio" in skipped
    row["mechanics"]["per_account"]["bybit_portfolio"].pop("level_only")   # legacy row: unchanged behaviour
    assert d.mechanics_scope(row, "close")[0] == ["bybit_2"]
