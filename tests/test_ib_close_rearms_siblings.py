"""An IB close re-arms each same-direction sibling's own bracket (BRACKETS-ALWAYS item 3, option B).

IBClient.close cancels EVERY resting leg on the symbol before flattening this trade's lots; on a contract a sibling
trade also holds, the sibling sat unprotected until the ~5-min naked sweep. close_open_position now re-places each
sibling's bracket at once, at the sibling row's own journal levels, keyed by its own trade id.
"""
from __future__ import annotations

import pytest

from src.units.accounts.execute import close_open_position
from src.units.accounts.ib_client import IBClient
from src.units.db.database import Database

CFG = {"account_id": "ib_paper", "exchange": "interactive_brokers"}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    p = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(p))
    monkeypatch.setattr("src.utils.paths.trade_journal_db_path", lambda: str(p))
    return Database(db_path=str(p))


def _seed(db, tag, size, sl, tp, direction="short", broker_order_id=None):
    db.insert_trade({"timestamp": "2026-11-16T06:13:48+00:00", "symbol": "MGC", "direction": direction,
                     "entry_price": 3843.3, "stop_loss": sl, "take_profit_1": tp, "position_size": size,
                     "status": "open", "is_backtest": 0, "strategy_name": tag, "setup_type": tag,
                     "account_id": "ib_paper", "broker_order_id": broker_order_id})
    return db.get_trades(filters={"strategy_name": tag, "status": "open"})[0]["id"]


class FakeIB(IBClient):
    def __init__(self, *, close_ok=True, rearm_ok=True):  # noqa: D107 -- no gateway
        self.close_ok, self.rearm_ok = close_ok, rearm_ok
        self.closes, self.rearms = [], []

    def close(self, symbol, direction, qty, sibling_qty=0.0):  # type: ignore[override]
        self.closes.append((symbol, direction, qty, sibling_qty))
        return {"retCode": 0, "result": {"orderId": "900"}} if self.close_ok else {"retCode": 1, "retMsg": "x"}

    def place_protective(self, order):  # type: ignore[override]
        self.rearms.append(order)
        return {"retCode": 0, "retMsg": "OK"} if self.rearm_ok else {"retCode": 1, "retMsg": "gateway down"}


def test_a_close_with_a_sibling_rearms_the_siblings_own_bracket(journal):
    me = _seed(journal, "mgc_trend_1h", 5, 3891.71, 3462.81)
    sib = _seed(journal, "mgc_pullback_1d", 11, 4116.03, 3766.99, broker_order_id="7000")
    ib = FakeIB()
    res = close_open_position(ib, CFG, symbol="MGC", side="short", qty=5, trade_id=me)
    assert res["ok"] and ib.closes[0][3] == pytest.approx(11.0)        # sibling reserved
    assert len(ib.rearms) == 1
    o = ib.rearms[0]
    assert o["oca_key"] == str(sib) and o["qty"] == pytest.approx(11.0)
    assert o["sl"] == pytest.approx(4116.03) and o["tp"] == pytest.approx(3766.99)
    assert o["entry_order_id"] == "7000" and o["direction"] == "short"
    assert res["siblings_rearmed"] == [{"trade_id": sib, "rearmed": True, "ret_msg": "OK"}]


def test_no_sibling_means_no_rearm(journal):
    me = _seed(journal, "mgc_trend_1h", 5, 3891.71, 3462.81)
    ib = FakeIB()
    res = close_open_position(ib, CFG, symbol="MGC", side="short", qty=5, trade_id=me)
    assert res["ok"] and ib.rearms == [] and res["siblings_rearmed"] == []


def test_an_opposite_direction_row_is_not_a_sibling(journal):
    me = _seed(journal, "mgc_trend_1h", 5, 3891.71, 3462.81)
    _seed(journal, "mgc_long", 2, 3700.0, 4000.0, direction="long")
    ib = FakeIB()
    close_open_position(ib, CFG, symbol="MGC", side="short", qty=5, trade_id=me)
    assert ib.rearms == []


def test_a_failed_close_rearms_nothing(journal):
    me = _seed(journal, "mgc_trend_1h", 5, 3891.71, 3462.81)
    _seed(journal, "mgc_pullback_1d", 11, 4116.03, 3766.99)
    ib = FakeIB(close_ok=False)
    res = close_open_position(ib, CFG, symbol="MGC", side="short", qty=5, trade_id=me)
    assert not res["ok"] and ib.rearms == []


def test_a_refused_rearm_is_reported_and_never_fails_the_close(journal):
    me = _seed(journal, "mgc_trend_1h", 5, 3891.71, 3462.81)
    sib = _seed(journal, "mgc_pullback_1d", 11, 4116.03, 3766.99)
    ib = FakeIB(rearm_ok=False)
    res = close_open_position(ib, CFG, symbol="MGC", side="short", qty=5, trade_id=me)
    assert res["ok"]
    assert res["siblings_rearmed"] == [{"trade_id": sib, "rearmed": False, "ret_msg": "gateway down"}]
