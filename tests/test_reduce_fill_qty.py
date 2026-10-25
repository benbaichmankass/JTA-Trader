"""REDUCE-FILL-QTY: an intent reduce shrinks its parents by the FILLED qty.

Until 2026-10-12 ``_log_trade_to_journal`` shrank the parents by the REQUESTED
reduce qty. A Bybit reduce-only order is cut by the venue to the position it
holds, so when the journal held more units than the venue the reduce "closed"
units the venue never closed. MEASURED 2026-10-12: 9 of 71 fill-matched reduce
legs filled short, every one leaving the venue at exactly 0.0, e.g. bybit_1
4358 asked for 0.839 BTC and filled 0.01.

These tests pin: the fill read's three states, the shrink sized from the fill,
and the ``unknown`` fallback to the request (the pre-fix behaviour, kept on
purpose so the #5101 reduce-churn loop cannot come back).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.test_intent_reduce_partial_close import FakeDB, _signed_net


@pytest.fixture()
def db(tmp_path):
    return FakeDB(str(tmp_path / "trades.db"))


class FakeBybit:
    """Answers the two order-lookup calls by orderId from a scripted list."""

    def __init__(self, records, *, raise_exc=None):
        # ``records`` is consumed one per get_order_history call; the last one
        # repeats. ``None`` = the order is in neither endpoint.
        self._records = list(records)
        self._raise = raise_exc
        self.history_calls = 0

    def get_open_orders(self, **kw):
        if self._raise:
            raise self._raise
        return {"result": {"list": []}}

    def get_order_history(self, **kw):
        self.history_calls += 1
        rec = self._records[min(self.history_calls - 1, len(self._records) - 1)]
        if rec is None:
            return {"result": {"list": []}}
        return {"result": {"list": [dict(rec, orderId=kw["orderId"])]}}


_CFG = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear",
        "account_class": "paper"}


def _read(client, requested=0.839, **kw):
    from src.units.accounts.execute import read_reduce_fill
    return read_reduce_fill(
        client, _CFG, symbol="BTCUSDT", order_id="oid-1",
        requested_qty=requested, sleep=lambda s: None, **kw,
    )


# --------------------------------------------------------------------------
# read_reduce_fill — the three states
# --------------------------------------------------------------------------

def test_filled_in_full():
    r = _read(FakeBybit([{"orderStatus": "Filled", "cumExecQty": "0.839",
                          "avgPrice": "63542.4"}]))
    assert r["state"] == "filled"
    assert r["filled_qty"] == pytest.approx(0.839)
    assert r["avg_price"] == pytest.approx(63542.4)


def test_venue_cut_is_short_fill():
    """The measured 4358 shape: asked 0.839, the venue held 0.01."""
    r = _read(FakeBybit([{"orderStatus": "Filled", "cumExecQty": "0.01",
                          "avgPrice": "63542.4"}]))
    assert r["state"] == "short_fill"
    assert r["filled_qty"] == pytest.approx(0.01)
    assert "0.01 of 0.839" in r["reason"]


def test_terminal_zero_fill_is_short_fill_of_zero():
    r = _read(FakeBybit([{"orderStatus": "Cancelled", "cumExecQty": "0",
                          "avgPrice": ""}]))
    assert r["state"] == "short_fill"
    assert r["filled_qty"] == 0.0
    assert r["avg_price"] is None


def test_not_terminal_then_filled_retries():
    client = FakeBybit([
        {"orderStatus": "New", "cumExecQty": "0"},
        {"orderStatus": "Filled", "cumExecQty": "0.839", "avgPrice": "1"},
    ])
    r = _read(client)
    assert r["state"] == "filled"
    assert client.history_calls == 2


@pytest.mark.parametrize("client, why", [
    (FakeBybit([{"orderStatus": "PartiallyFilled", "cumExecQty": "0.2"}]),
     "not terminal"),
    (FakeBybit([None]), "not found"),
    (FakeBybit([{"orderStatus": "Filled", "cumExecQty": None}]),
     "unusable cumExecQty"),
    (FakeBybit([], raise_exc=RuntimeError("timeout")), "timeout"),
    (None, "no exchange_client"),
])
def test_could_not_read_is_unknown(client, why):
    r = _read(client)
    assert r["state"] == "unknown"
    assert r["filled_qty"] is None
    assert why in r["reason"]


def test_non_bybit_is_unknown():
    from src.units.accounts.execute import read_reduce_fill
    r = read_reduce_fill(
        FakeBybit([{"orderStatus": "Filled", "cumExecQty": "1"}]),
        {"exchange": "alpaca"}, symbol="SPY", order_id="x", requested_qty=1,
        sleep=lambda s: None,
    )
    assert r["state"] == "unknown"


# --------------------------------------------------------------------------
# _log_trade_to_journal — the shrink is sized from the fill
# --------------------------------------------------------------------------

def _pkg():
    return SimpleNamespace(
        symbol="BTCUSDT", direction="short", entry=120.0, sl=118.0, tp=125.0,
        confidence=0.7, strategy="ict_scalp_5m",
        meta={"order_package_id": "op-1",
              "execution_delta": {"action": "reduce", "target_qty": 0.2,
                                  "current_qty": 0.8}},
    )


def _seed(db):
    """id1 = 0.01 (the unit the venue really held), id2 = 3.199 (a row the
    venue had already closed — the journal had not seen it)."""
    ids = []
    for ts, size in (("t1", 0.01), ("t2", 3.199)):
        ids.append(db.insert_trade({
            "timestamp": ts, "symbol": "BTCUSDT", "direction": "long",
            "entry_price": 100.0, "position_size": size, "status": "open",
            "is_backtest": 0, "account_id": "bybit_1", "strategy_name": "s",
        }))
    return ids


def _write(db, monkeypatch, reduce_fill, qty=0.839):
    from src.units.accounts import execute as execmod
    import src.units.db.database as dbmod
    import src.utils.paths as pathsmod
    monkeypatch.setattr(pathsmod, "trade_journal_db_path", lambda: "ignored")
    monkeypatch.setattr(dbmod, "Database", lambda db_path=None: db)
    ok = execmod._log_trade_to_journal(
        _pkg(), _CFG, {"qty": qty, "symbol": "BTCUSDT"}, trade_id="oid-1",
        is_dry=False, intent_reduce=True, reduce_fill=reduce_fill,
    )
    assert ok is True
    audit = [r for r in db.rows() if r["setup_type"] == "intent_reduce"]
    assert len(audit) == 1
    return audit[0], json.loads(audit[0]["notes"])


def test_short_fill_shrinks_by_filled_qty(db, monkeypatch):
    id1, id2 = _seed(db)
    audit, notes = _write(db, monkeypatch, {
        "state": "short_fill", "filled_qty": 0.01, "avg_price": 63542.4,
        "reason": "venue filled 0.01 of 0.839 (orderStatus=Filled)",
    })
    rows = {r["id"]: r for r in db.rows()}
    assert rows[id1]["status"] == "closed"          # the 0.01 the venue closed
    assert rows[id2]["status"] == "open"
    assert rows[id2]["position_size"] == pytest.approx(3.199)  # NOT 2.37
    assert audit["position_size"] == pytest.approx(0.01)
    assert notes["intent_reduce_allocations"][0]["consumed"] == pytest.approx(0.01)
    assert notes["reduce_fill_state"] == "short_fill"
    assert notes["reduce_requested_qty"] == pytest.approx(0.839)
    assert notes["reduce_filled_qty"] == pytest.approx(0.01)
    assert notes["reduce_unfilled_qty"] == pytest.approx(0.829)
    assert notes["reduce_fill_avg_price"] == pytest.approx(63542.4)
    assert "0.01 of 0.839" in notes["reduce_fill_reason"]


def test_full_fill_matches_request(db, monkeypatch):
    id1, id2 = _seed(db)
    audit, notes = _write(db, monkeypatch, {
        "state": "filled", "filled_qty": 0.839, "avg_price": None,
    })
    assert _signed_net(db, "bybit_1", "BTCUSDT") == pytest.approx(3.209 - 0.839)
    assert audit["position_size"] == pytest.approx(0.839)
    assert notes["reduce_fill_state"] == "filled"
    assert "reduce_unfilled_qty" not in notes
    assert "reduce_fill_reason" not in notes


def test_zero_fill_shrinks_nothing(db, monkeypatch):
    _seed(db)
    audit, notes = _write(db, monkeypatch, {
        "state": "short_fill", "filled_qty": 0.0, "reason": "venue filled 0",
    })
    assert _signed_net(db, "bybit_1", "BTCUSDT") == pytest.approx(3.209)
    assert audit["position_size"] == 0.0
    assert notes["intent_reduce_allocations"] == []


@pytest.mark.parametrize("reduce_fill", [
    None,
    {"state": "unknown", "filled_qty": None, "reason": "timeout"},
    {"state": "filled"},                      # malformed: no filled_qty
    {"state": "bogus", "filled_qty": 0.01},   # not one of the states
])
def test_unread_fill_falls_back_to_request(db, monkeypatch, reduce_fill):
    """`unknown` keeps the pre-fix behaviour: the request is an upper bound on
    a reduce-only fill, and not shrinking would re-send the reduce next tick."""
    _seed(db)
    audit, notes = _write(db, monkeypatch, reduce_fill)
    assert _signed_net(db, "bybit_1", "BTCUSDT") == pytest.approx(3.209 - 0.839)
    assert audit["position_size"] == pytest.approx(0.839)
    assert notes["reduce_fill_state"] == "unknown"
    assert notes["reduce_requested_qty"] == pytest.approx(0.839)
    assert "reduce_filled_qty" not in notes


# --------------------------------------------------------------------------
# execute_pkg — the fill is read after placement and handed to the journal
# --------------------------------------------------------------------------

def test_execute_pkg_reads_fill_and_passes_it(monkeypatch):
    from src.units.accounts import execute as execmod

    captured = {}
    monkeypatch.setattr(execmod, "is_paused", lambda _a: False)
    monkeypatch.setattr(execmod, "_submit_order",
                        lambda client, order, cfg, observed=None: "oid-9")
    monkeypatch.setattr(execmod, "_log_trade_to_journal",
                        lambda *a, **k: captured.update(k) or True)
    client = FakeBybit([{"orderStatus": "Filled", "cumExecQty": "4.6",
                         "avgPrice": "76.36"}])
    pkg = SimpleNamespace(
        symbol="SOLUSDT", direction="short", entry=76.36, sl=74.0, tp=84.0,
        confidence=0.8, strategy="trend_donchian_sol_4h", meta={},
    )
    tid = execmod.execute_pkg(
        pkg, dict(_CFG, mode="live"), exchange_client=client,
        balance_usdt=10_000.0, dry_run=False, qty_override=1543.2,
        reduce_only=True,
    )
    assert tid == "oid-9"
    assert captured["intent_reduce"] is True
    assert captured["reduce_fill"]["state"] == "short_fill"
    assert captured["reduce_fill"]["filled_qty"] == pytest.approx(4.6)


def test_execute_pkg_open_order_reads_no_fill(monkeypatch):
    """A non-reduce order makes no extra venue call and passes no fill."""
    from src.units.accounts import execute as execmod

    captured = {}
    monkeypatch.setattr(execmod, "is_paused", lambda _a: False)
    monkeypatch.setattr(execmod, "_submit_order",
                        lambda client, order, cfg, observed=None: "oid-10")
    monkeypatch.setattr(execmod, "_log_trade_to_journal",
                        lambda *a, **k: captured.update(k) or True)
    monkeypatch.setattr(execmod, "_bybit_tpsl_mode", lambda: "full")
    client = FakeBybit([{"orderStatus": "Filled", "cumExecQty": "1"}])
    pkg = SimpleNamespace(
        symbol="SOLUSDT", direction="long", entry=76.36, sl=74.0, tp=84.0,
        confidence=0.8, strategy="trend_donchian_sol_4h", meta={},
    )
    execmod.execute_pkg(
        pkg, dict(_CFG, mode="live"), exchange_client=client,
        balance_usdt=10_000.0, dry_run=False, qty_override=1.0,
    )
    assert captured["reduce_fill"] is None
    assert client.history_calls == 0


# --------------------------------------------------------------------------
# XRP-REDUCE-OTHER-CLOSES — the reduce audit row carries the venue orderId
# --------------------------------------------------------------------------

def test_reduce_audit_row_stamps_broker_order_id(db, monkeypatch):
    """bybit_2 6533/6539: both reduce orders FILLED at the venue (order history
    + closed-pnl, 2026-10-09), yet both journal rows read broker_order_id NULL
    because the partial-close insert omitted the column the legacy insert
    stamps. The orderId was only in notes.trade_id."""
    _seed(db)
    audit, notes = _write(db, monkeypatch, {
        "state": "filled", "filled_qty": 0.839, "avg_price": None,
    })
    assert notes["trade_id"] == "oid-1"
    assert audit["broker_order_id"] == "oid-1"
