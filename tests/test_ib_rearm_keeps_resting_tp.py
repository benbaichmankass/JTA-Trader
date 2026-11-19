"""A stop-only IB re-arm must not silently remove a take-profit the trade has resting (BRACKETS-ALWAYS, item 1).

AM-OPS-4's inventory 2026-11-19 (row BRACKETS-ALWAYS): `execute.modify_open_order` re-arms IB at
`eff_tp = tp if tp is not None else cur_tp`. When the journal row carries no TP, that is a STOP-ONLY re-arm, and
`place_protective`'s keyed pre-cancel removes every leg of the trade's group, its resting take-profit included. The fix
reads the target the pre-cancel is about to remove and re-places it at the same price.

These tests build the resting AND the placed legs from the REAL ib_insync `LimitOrder` / `StopOrder` classes
(an unset price there is UNSET_DOUBLE = 1.797e308, not None), so a test stub cannot hide a field-name or sentinel mismatch.
"""
from __future__ import annotations

import pytest

ib_insync = pytest.importorskip("ib_insync")

from tests.test_ib_protection_quantity import _client, _Contract, _IB, _Position  # noqa: E402


class _RealTrade:
    def __init__(self, symbol, order):
        self.contract = _Contract(symbol)
        self.order = order


def _leg(kind, qty, price, *, oca="", parent=0, order_id=0):
    o = (ib_insync.LimitOrder if kind == "LMT" else ib_insync.StopOrder)("SELL", qty, price)
    o.ocaGroup, o.parentId, o.orderId = oca, parent, order_id
    return _RealTrade("TLT", o)


def _client_real(monkeypatch, ib):
    c = _client(monkeypatch, ib)
    c.readonly = False

    class _C:
        n = 900

        @classmethod
        def getReqId(cls):
            cls.n += 1
            return cls.n

    ib.client = _C()
    monkeypatch.setattr(c, "_build_contract", lambda _s: _Contract("TLT"))
    monkeypatch.setattr(c, "_sweep_stray_oca_groups", lambda *a, **k: {})
    placed = []
    ib.placeOrder = lambda _c, o: placed.append(o) or _RealTrade("TLT", o)
    ib.sleep = lambda *_a: None
    return c, placed


def _rearm(c, **over):
    order = {"symbol": "TLT", "direction": "long", "qty": 100, "sl": 80.0, "tp": None,
             "oca_key": "6879", "account_id": "ib_paper"}
    order.update(over)
    return c.place_protective(order)


def test_stop_only_rearm_carries_the_resting_take_profit_forward(monkeypatch):
    tp = _leg("LMT", 100, 88.5, oca="oca-protect-t6879", order_id=11)
    sl = _leg("STP", 100, 79.0, oca="oca-protect-t6879", order_id=12)
    ib = _IB([_Position("TLT", 100)], [tp, sl])
    c, placed = _client_real(monkeypatch, ib)
    resp = _rearm(c)
    assert resp["retCode"] == 0, resp
    assert tp.order in ib.cancelled and sl.order in ib.cancelled  # the old pair is still replaced
    kinds = {type(o).__name__: o for o in placed}
    assert set(kinds) == {"StopOrder", "LimitOrder"}, "the take-profit was dropped by a stop-only re-arm"
    assert kinds["LimitOrder"].lmtPrice == 88.5 and kinds["StopOrder"].auxPrice == 80.0
    assert {o.ocaGroup for o in placed} == {"oca-protect-t6879"}
    assert resp["result"]["tp_carried_forward"] == 88.5


def test_the_entry_bracket_child_target_is_carried_too(monkeypatch):
    tp = _leg("LMT", 100, 87.57, parent=1231, order_id=1232)
    ib = _IB([_Position("TLT", 100)], [tp])
    c, placed = _client_real(monkeypatch, ib)
    _rearm(c, entry_order_id="1231")
    assert any(type(o).__name__ == "LimitOrder" and o.lmtPrice == 87.57 for o in placed)


def test_a_sibling_trades_target_is_never_borrowed(monkeypatch):
    sib = _leg("LMT", 40, 95.0, oca="oca-protect-t900", order_id=21)
    ib = _IB([_Position("TLT", 140)], [sib])
    c, placed = _client_real(monkeypatch, ib)
    resp = _rearm(c)
    assert [type(o).__name__ for o in placed] == ["StopOrder"]
    assert sib.order not in ib.cancelled
    assert resp["result"]["tp_carried_forward"] is None


def test_an_explicit_target_wins_over_the_resting_one(monkeypatch):
    tp = _leg("LMT", 100, 88.5, oca="oca-protect-t6879", order_id=11)
    ib = _IB([_Position("TLT", 100)], [tp])
    c, placed = _client_real(monkeypatch, ib)
    resp = _rearm(c, tp=90.0)
    assert [o.lmtPrice for o in placed if type(o).__name__ == "LimitOrder"] == [90.0]
    assert resp["result"]["tp_carried_forward"] is None


def test_ambiguous_resting_targets_are_not_guessed(monkeypatch):
    a = _leg("LMT", 50, 88.5, oca="oca-protect-t6879", order_id=11)
    b = _leg("LMT", 50, 91.0, oca="oca-protect-t6879", order_id=13)
    ib = _IB([_Position("TLT", 100)], [a, b])
    c, placed = _client_real(monkeypatch, ib)
    resp = _rearm(c)
    assert [type(o).__name__ for o in placed] == ["StopOrder"]
    assert resp["result"]["tp_carried_forward"] is None


def test_the_keyless_symbol_wide_path_never_carries_a_target(monkeypatch):
    """Without a trade key the resting targets may be a sibling's: nothing is carried (unchanged behaviour)."""
    tp = _leg("LMT", 100, 88.5, oca="oca-protect-t6879", order_id=11)
    ib = _IB([_Position("TLT", 100)], [tp])
    c, placed = _client_real(monkeypatch, ib)
    resp = _rearm(c, oca_key=None)
    assert [type(o).__name__ for o in placed] == ["StopOrder"]
    assert resp["result"]["tp_carried_forward"] is None


def test_unset_double_is_never_read_as_a_price():
    from src.units.accounts.ib_client import IBClient
    o = ib_insync.LimitOrder("SELL", 1, 88.5)
    assert o.auxPrice > 1e300  # the real sentinel
    o.lmtPrice = o.auxPrice      # both unset
    assert IBClient._protective_leg_price(o, "target") is None
    assert IBClient._protective_leg_price(o, "stop") is None
    s = ib_insync.StopOrder("SELL", 1, 79.0)
    assert IBClient._protective_leg_price(s, "stop") == 79.0
