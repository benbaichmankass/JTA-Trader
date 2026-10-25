"""SOAK-MECH-FAULTS class C — a Bybit reduce-only close must not take a
same-direction SIBLING trade's share of a netted position.

Measured incident (bybit_1 XRPUSDT, 2026-09-26): trade 6193
(ict_scalp_xrp_5m, 87674.6) and trade 6171 (xrp_pullback_2h, 1221.9) shared
one one-way long. 6193's own PartialStopLoss leg filled at the venue at
09:11:18; at 09:11:56 the monitor sent its own ``sl_cross`` reduce-only close
for 87674.6, Bybit clamped it to the 1221.9 that remained, and 6171 was
flattened with no journal close (journaled later as ``reconciler_filled`` at a
candle price). xrp_pullback_2h shares XRPUSDT with trend_donchian_xrp_4h on
bybit_2 (real money), so the same race is reachable there.
"""
from __future__ import annotations

import pytest

from src.units.accounts.execute import close_open_position
from src.units.db.database import Database
from src.runtime.order_monitor import _venue_reports_position_already_flat


@pytest.fixture
def tmp_journal(tmp_path, monkeypatch):
    db_path = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db_path))
    return Database(db_path=str(db_path))


def _seed(db, tag, size, direction="long", account_id="bybit_1"):
    db.insert_trade({
        "timestamp": "2026-09-26T08:37:38+00:00", "symbol": "XRPUSDT",
        "direction": direction, "entry_price": 1.55, "stop_loss": 1.49,
        "take_profit_1": 1.72, "position_size": size, "status": "open",
        "is_backtest": 0, "strategy_name": tag, "setup_type": tag,
        "account_id": account_id,
    })
    for row in db.get_trades(filters={"strategy_name": tag, "status": "open"}):
        return row["id"]
    raise AssertionError("seed not found")


class FakeBybit:
    def __init__(self, *, live_long=0.0, resting_ids=(), pos_ok=True):
        self.live_long = live_long
        self.resting_ids = list(resting_ids)
        self.pos_ok = pos_ok
        self.placed = []
        self.cancelled = []

    def get_positions(self, **_):
        if not self.pos_ok:
            return {"retCode": 10002, "retMsg": "timeout", "result": {}}
        rows = []
        if self.live_long:
            rows.append({"side": "Buy", "size": str(self.live_long)})
        return {"retCode": 0, "result": {"list": rows}}

    def get_open_orders(self, **_):
        return {"retCode": 0, "result": {"list": [
            {"orderId": i, "stopOrderType": "PartialStopLoss"}
            for i in self.resting_ids]}}

    def place_order(self, **kw):
        self.placed.append(kw)
        return {"retCode": 0, "result": {"orderId": "close-1"}}

    def cancel_order(self, **kw):
        self.cancelled.append(kw)
        return {"retCode": 0}


ACCT = {"exchange": "bybit", "account_id": "bybit_1", "market_type": "linear"}


def _close(client, trade_id, qty, sl="own-sl", tp="own-tp"):
    return close_open_position(
        client, ACCT, symbol="XRPUSDT", side="long", qty=qty,
        sl_order_id=sl, tp_order_id=tp, trade_id=trade_id,
    )


def test_incident_shape_own_leg_filled_does_not_take_sibling_share(tmp_journal):
    a = _seed(tmp_journal, "ict_scalp_xrp_5m", 87674.6)
    _seed(tmp_journal, "xrp_pullback_2h", 1221.9)
    # A's own SL leg already filled: only B's 1221.9 remains, A's legs gone.
    client = FakeBybit(live_long=1221.9, resting_ids=["sibling-sl"])
    out = _close(client, a, 87674.6)
    assert client.placed == [], "must not send a close that eats B's share"
    assert out["ok"] is False
    assert _venue_reports_position_already_flat(
        out["error"], out["exchange_response"]), (
        "the monitor must route this to its already-closed DB update")


def test_partial_shortfall_clamps_to_own_headroom(tmp_journal):
    a = _seed(tmp_journal, "a", 100.0)
    _seed(tmp_journal, "b", 30.0)
    client = FakeBybit(live_long=90.0)  # A's share shrank to 60
    out = _close(client, a, 100.0)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(60.0)


def test_own_legs_still_resting_sends_unclamped_qty(tmp_journal):
    """A stale-open sibling row must not make a real close under-close."""
    a = _seed(tmp_journal, "a", 100.0)
    _seed(tmp_journal, "b", 30.0)
    client = FakeBybit(live_long=100.0, resting_ids=["own-sl"])
    out = _close(client, a, 100.0)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)


def test_untracked_legs_send_unclamped_qty(tmp_journal):
    a = _seed(tmp_journal, "a", 100.0)
    _seed(tmp_journal, "b", 30.0)
    client = FakeBybit(live_long=30.0)
    out = _close(client, a, 100.0, sl=None, tp=None)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)


def test_no_sibling_full_headroom_is_unchanged(tmp_journal):
    a = _seed(tmp_journal, "a", 100.0)
    client = FakeBybit(live_long=100.0)
    out = _close(client, a, 100.0)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)


def test_opposite_direction_row_is_not_a_sibling(tmp_journal):
    a = _seed(tmp_journal, "a", 100.0)
    _seed(tmp_journal, "b", 30.0, direction="short")
    client = FakeBybit(live_long=100.0)
    _close(client, a, 100.0)
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)


def test_position_read_failure_sends_pre_fix_qty(tmp_journal):
    a = _seed(tmp_journal, "a", 100.0)
    _seed(tmp_journal, "b", 30.0)
    client = FakeBybit(live_long=30.0, pos_ok=False)
    out = _close(client, a, 100.0)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)


def test_no_trade_id_is_byte_for_byte_pre_fix(tmp_journal):
    _seed(tmp_journal, "b", 30.0)
    client = FakeBybit(live_long=30.0)
    out = close_open_position(client, ACCT, symbol="XRPUSDT", side="long",
                              qty=100.0)
    assert out["ok"] is True
    assert float(client.placed[0]["qty"]) == pytest.approx(100.0)
