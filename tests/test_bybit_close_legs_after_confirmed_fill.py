"""A Bybit close cancels the trade's SL/TP legs only once the close is CONFIRMED FILLED (BRACKETS-ALWAYS item 5).

Before: the legs were cancelled as soon as the reduce-only Market order was ACCEPTED. An accepted-but-unfilled close
(halt, partial, unreadable status) left the still-open position with no SL/TP. The responses below follow pybit's V5
shapes (``result.list`` of order records with ``orderId`` / ``orderStatus`` / ``cumExecQty`` / ``avgPrice``).
"""
from __future__ import annotations

from src.units.accounts.execute import close_open_position

CFG = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear"}


class FakePybit:
    def __init__(self, *, status="Filled", cum="12.2", history_ok=True):
        self.status, self.cum, self.history_ok = status, cum, history_ok
        self.cancelled: list = []

    def get_positions(self, **_):
        return {"retCode": 0, "result": {"list": [{"side": "Buy", "size": "12.2", "positionIdx": 0}]}}

    def place_order(self, **kw):
        return {"retCode": 0, "result": {"orderId": "close-1"}}

    def get_open_orders(self, **kw):
        if kw.get("orderId") == "close-1" and self.status in ("New", "PartiallyFilled"):
            return {"retCode": 0, "result": {"list": [
                {"orderId": "close-1", "orderStatus": self.status, "cumExecQty": self.cum, "avgPrice": "0"}]}}
        return {"retCode": 0, "result": {"list": []}}

    def get_order_history(self, **kw):
        if not self.history_ok:
            raise TimeoutError("read timed out")
        if kw.get("orderId") == "close-1" and self.status not in ("New", "PartiallyFilled"):
            return {"retCode": 0, "result": {"list": [
                {"orderId": "close-1", "orderStatus": self.status, "cumExecQty": self.cum, "avgPrice": "180.1"}]}}
        return {"retCode": 0, "result": {"list": []}}

    def cancel_order(self, **kw):
        self.cancelled.append(kw.get("orderId"))
        return {"retCode": 0}


def _close(c):
    return close_open_position(c, CFG, symbol="SOLUSDT", side="long", qty=12.2,
                               sl_order_id="sl-1", tp_order_id="tp-1")


def test_a_confirmed_fill_cancels_both_legs():
    c = FakePybit()
    res = _close(c)
    assert res["ok"] and res["legs_cancel"] == "confirmed_filled"
    assert sorted(c.cancelled) == ["sl-1", "tp-1"]


def test_an_accepted_but_unfilled_close_keeps_the_legs(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = FakePybit(status="New", cum="0")
    res = _close(c)
    assert res["ok"] and res["legs_cancel"].startswith("skipped_")
    assert c.cancelled == [], "SL/TP were cancelled while the close had not filled"


def test_a_partial_fill_keeps_the_legs(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = FakePybit(status="PartiallyFilledCanceled", cum="5.0")
    res = _close(c)
    assert res["legs_cancel"] == "skipped_short_fill" and c.cancelled == []


def test_an_unreadable_status_keeps_the_legs(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = FakePybit(history_ok=False)
    res = _close(c)
    assert res["ok"] and res["legs_cancel"] == "skipped_unknown" and c.cancelled == []


def test_no_tracked_legs_skips_the_fill_read():
    c = FakePybit()
    res = close_open_position(c, CFG, symbol="SOLUSDT", side="long", qty=12.2)
    assert res["ok"] and res["legs_cancel"] == "not_needed" and c.cancelled == []
