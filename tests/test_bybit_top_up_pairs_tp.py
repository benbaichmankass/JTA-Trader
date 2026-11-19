"""The Bybit qty-scoped protection top-up carries the row's own TP (TP doctrine, BRACKETS-ALWAYS item 5).

It used to add an SL-only Partial leg ("TP deliberately omitted"), leaving the topped-up qty TP-naked on real-money
bybit_2. The SL+TP pair goes in ONE Partial add-a-leg set_trading_stop; if the venue refuses it, the SL-only top-up
is sent at once so the stop is never lost for the TP's sake.
"""
from __future__ import annotations

import src.runtime.order_monitor as om

ACC = {"account_id": "bybit_2", "exchange": "bybit", "market_type": "linear"}


class FakePybit:
    """set_trading_stop in pybit's V5 response shape; refuses any call carrying a TP when tp_ok is False."""

    def __init__(self, tp_ok=True):
        self.tp_ok = tp_ok
        self.calls: list = []

    def set_trading_stop(self, **kw):
        self.calls.append(kw)
        if "takeProfit" in kw and not self.tp_ok:
            return {"retCode": 10001, "retMsg": "TakeProfit:1720000 set for Buy position should be higher than base_price"}
        return {"retCode": 0, "retMsg": "OK", "result": {}}


def _run(monkeypatch, client, row):
    monkeypatch.setenv("BYBIT_TPSL_MODE", "partial")
    monkeypatch.setattr("src.units.accounts.clients.bybit_client_for", lambda acc: client)
    return om._bybit_top_up_partial_sl(ACC, "XRPUSDT", row, 120.0, 1.49)


def test_the_top_up_carries_the_rows_take_profit_in_one_call(monkeypatch):
    c = FakePybit()
    assert _run(monkeypatch, c, {"take_profit_1": 1.72, "direction": "long"}) is True
    assert len(c.calls) == 1
    kw = c.calls[0]
    assert kw["tpslMode"] == "Partial"
    assert float(kw["stopLoss"]) == 1.49 and float(kw["takeProfit"]) == 1.72
    assert kw["slSize"] == kw["tpSize"] == "120.0"


def test_a_refused_pair_falls_back_to_the_sl_only_top_up(monkeypatch):
    c = FakePybit(tp_ok=False)
    assert _run(monkeypatch, c, {"take_profit_1": 1.72, "direction": "long"}) is True
    assert len(c.calls) == 2
    assert "takeProfit" in c.calls[0] and "takeProfit" not in c.calls[1]
    assert float(c.calls[1]["stopLoss"]) == 1.49 and c.calls[1]["slSize"] == "120.0"


def test_a_row_with_no_declared_tp_sends_the_sl_only_leg(monkeypatch):
    c = FakePybit()
    assert _run(monkeypatch, c, {"take_profit_1": None, "direction": "long"}) is True
    assert len(c.calls) == 1 and "takeProfit" not in c.calls[0]


def test_full_mode_never_adds_a_position_level_tp(monkeypatch):
    """Under Full mode the TP would cover the WHOLE netted position, overriding siblings' targets."""
    c = FakePybit()
    monkeypatch.setattr("src.units.accounts.clients.bybit_client_for", lambda acc: c)
    monkeypatch.setenv("BYBIT_TPSL_MODE", "full")
    assert om._bybit_top_up_partial_sl(ACC, "XRPUSDT", {"take_profit_1": 1.72}, 120.0, 1.49) is True
    assert all("takeProfit" not in kw for kw in c.calls)
