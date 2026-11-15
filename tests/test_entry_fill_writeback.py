"""ENTRY-FILL-WRITEBACK (manager decision 2026-11-15, option a): entry_price becomes the entry order's own fill.

The four conditions the manager set, each pinned here:
  1. the ENTRY ORDER's own avgPrice matched by orderId, never a position average; a fill that cannot be isolated is
     NOT written (entry_price_source stays "plan" with the reason);
  2. a DB field update only: no order placed / amended / cancelled, SL/TP and slices untouched;
  3. entry_price_source on every row (fill | plan + reason), as Alpaca does;
  4. no history backfill: closed rows and rows without the insert's pending marker are never touched.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.core.coordinator import OrderPackage
from src.runtime import order_monitor as om
from src.units.accounts.execute import _log_trade_to_journal, execute_pkg
from src.units.db.database import Database


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    p = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(p))
    return p


class _StubBybit:
    def place_order(self, **kwargs):
        return {"retCode": 0, "result": {"orderId": "ENTRY-OID-1"}}

    def get_wallet_balance(self, **kwargs):
        return {"result": {"list": [{"coin": [{"usdValue": "10000"}]}]}}


def _pkg(**kw):
    base = dict(strategy="vwap", symbol="BTCUSDT", direction="short", entry=50_000.0, sl=50_500.0, tp=49_000.0,
                confidence=0.7, meta={"strategy_name": "vwap", "entry_reason": "t"})
    base.update(kw)
    return OrderPackage(**base)


def _cfg(name="bybit_2", exchange="bybit"):
    return {"account_id": name, "exchange": exchange, "api_key_env": "BYBIT_KEY_2", "risk_pct": 0.01,
            "min_balance_usd": 50.0, "min_qty": 0.001, "qty_precision": 3}


def _rows(path):
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute("SELECT * FROM trades ORDER BY id")]
    c.close()
    return out


def _notes(row):
    return json.loads(row["notes"] or "{}")


# ---------------------------------------------------------------- condition 3: every row is labelled at insert
def test_a_live_bybit_entry_is_labelled_plan_pending_writeback(journal):
    execute_pkg(_pkg(), _cfg(), exchange_client=_StubBybit(), balance_usdt=10_000.0, dry_run=False)
    r = _rows(journal)[0]
    n = _notes(r)
    assert r["entry_price"] == 50_000.0                       # the plan, until the sweep reads the fill
    assert n["entry_price_source"] == "plan" and n["entry_price_source_reason"] == om.ENTRY_FILL_PENDING


def test_dry_and_rejected_rows_are_labelled_with_their_reason(journal):
    assert _log_trade_to_journal(_pkg(), _cfg(), {"qty": 0.1}, is_dry=True, status="rejected",
                                 reason="account_mode_dry_run")
    assert _log_trade_to_journal(_pkg(), _cfg(), {"qty": 0.1}, status="exchange_rejected", reason="x")
    a, b = (_notes(r) for r in _rows(journal))
    assert a["entry_price_source"] == "plan" and a["entry_price_source_reason"] == "dry_run"
    assert b["entry_price_source"] == "plan" and b["entry_price_source_reason"] == "status_exchange_rejected"


def test_an_alpaca_venue_fill_keeps_its_own_label(journal):
    order = {"qty": 1.0, "venue_fill": {"avg_price": 49_990.0, "source": "alpaca_order_status"}}
    assert _log_trade_to_journal(_pkg(), _cfg("alpaca_live", "alpaca"), order, trade_id="A1", status="open")
    r = _rows(journal)[0]
    n = _notes(r)
    assert r["entry_price"] == 49_990.0 and n["entry_price_source"] == "alpaca_order_status"
    assert n["package_entry"] == 50_000.0 and "entry_price_source_reason" not in n


# ---------------------------------------------------------------- condition 1: the decision (pure)
@pytest.mark.parametrize("order,action,reason", [
    (None, "wait", "order_status_read_failed"),
    ({"status": "New"}, "wait", "entry_order_New"),
    ({"status": "PartiallyFilled", "avg_price": 1.0, "filled_qty": 0.05}, "wait", "entry_order_PartiallyFilled"),
    ({"status": "not_found", "avg_price": 0.0, "filled_qty": 0.0}, "plan", "entry_order_not_found"),
    ({"status": "Filled", "avg_price": 0.0, "filled_qty": 0.1}, "plan", "no_avg_price_status_Filled"),
    ({"status": "Filled", "avg_price": 49_980.0, "filled_qty": 0.3}, "plan", "entry_order_qty_mismatch"),
    ({"status": "Filled", "avg_price": 49_980.0, "filled_qty": 0.1}, "write", om.ENTRY_FILL_SOURCE_BYBIT),
])
def test_entry_fill_decision(order, action, reason):
    d = om.entry_fill_decision({"position_size": 0.1}, order)
    assert (d["action"], d["reason"]) == (action, reason)
    assert d["entry"] == (49_980.0 if action == "write" else None)


# ---------------------------------------------------------------- the sweep: conditions 1, 2, 4 end to end
def _seed(journal, monkeypatch):
    execute_pkg(_pkg(), _cfg(), exchange_client=_StubBybit(), balance_usdt=10_000.0, dry_run=False)   # id 1: pending
    execute_pkg(_pkg(symbol="ETHUSDT", entry=2000.0, sl=2050.0, tp=1900.0), _cfg(),
                exchange_client=_StubBybit(), balance_usdt=10_000.0, dry_run=False)                   # id 2: pending
    c = sqlite3.connect(str(journal))
    # id 3: a CLOSED pending row (history) and id 4: an old open row with no marker -- neither may be touched
    c.execute("INSERT INTO trades (timestamp, symbol, direction, entry_price, stop_loss, take_profit_1, position_size,"
              " status, is_backtest, account_id, notes, broker_order_id) VALUES"
              " ('2026-11-01', 'SOLUSDT', 'long', 70, 65, 80, 1, 'closed', 0, 'bybit_2', ?, 'OLD-1')",
              (json.dumps({"entry_price_source": "plan", "entry_price_source_reason": om.ENTRY_FILL_PENDING}),))
    c.execute("INSERT INTO trades (timestamp, symbol, direction, entry_price, stop_loss, take_profit_1, position_size,"
              " status, is_backtest, account_id, notes, broker_order_id) VALUES"
              " ('2026-11-01', 'XRPUSDT', 'long', 1, 0.9, 1.2, 10, 'open', 0, 'bybit_2', '{}', 'OLD-2')")
    c.commit()
    c.close()
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {"bybit_2": _cfg()})


def test_sweep_writes_the_entry_orders_fill_and_nothing_else(journal, monkeypatch):
    _seed(journal, monkeypatch)
    before = _rows(journal)
    qty = {r["id"]: r["position_size"] for r in before}
    asked = []

    def _status(cfg, oid):
        asked.append(oid)
        rid = 2 if len(asked) == 1 else 1       # newest first: id 2, then id 1
        if rid == 2:   # ETH: the order's fills are not the row's size -> cannot isolate -> keep the plan
            return {"status": "Filled", "avg_price": 1999.0, "filled_qty": qty[2] * 3}
        return {"status": "Filled", "avg_price": 49_975.0, "filled_qty": qty[1]}

    # condition 2: any order / bracket call is a test failure
    import src.units.accounts.execute as ex
    for name in ("modify_open_order", "_submit_order", "execute_pkg"):
        if hasattr(ex, name):
            monkeypatch.setattr(ex, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("order path touched")))
    # the canonical writer's observer hooks (trade-updated / trade-closed notifications, cost stamp) must not fire
    for hook in ("_fire_trade_updated_event", "_fire_trade_closed_event", "_record_trade_cost_estimate"):
        monkeypatch.setattr(Database, hook, lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"{hook} fired")))
    summary = om._sweep_entry_fill_writeback(Database(str(journal)), order_status=_status)
    after = {r["id"]: r for r in _rows(journal)}
    b = {r["id"]: r for r in before}

    assert summary["written"] == 1 and summary["kept_plan"] == 1 and summary["errors"] == 0
    assert asked == ["ENTRY-OID-1", "ENTRY-OID-1"]                      # only the two pending OPEN rows were read
    # id 1: entry_price is now the entry order's own fill; the plan is kept in notes
    n1 = _notes(after[1])
    assert after[1]["entry_price"] == 49_975.0
    assert n1["entry_price_source"] == om.ENTRY_FILL_SOURCE_BYBIT and n1["package_entry"] == 50_000.0
    assert "entry_price_source_reason" not in n1
    # id 2: fill not isolable -> plan kept, labelled with the reason, entry unchanged
    n2 = _notes(after[2])
    assert after[2]["entry_price"] == b[2]["entry_price"] == 2000.0
    assert n2["entry_price_source"] == "plan" and n2["entry_price_source_reason"] == "entry_order_qty_mismatch"
    # condition 2: SL / TP / size / status untouched on every row
    for i in after:
        for k in ("stop_loss", "take_profit_1", "position_size", "status", "sl_order_id", "tp_order_id"):
            assert after[i][k] == b[i][k], (i, k)
    # condition 4: the closed pending row and the unmarked open row are byte-identical
    assert after[3] == b[3] and after[4] == b[4]


def test_sweep_waits_on_a_read_failure_and_retries_next_tick(journal, monkeypatch):
    _seed(journal, monkeypatch)
    s = om._sweep_entry_fill_writeback(Database(str(journal)), order_status=lambda cfg, oid: None)
    assert s["waiting"] == 2 and s["written"] == 0
    assert all(_notes(r).get("entry_price_source_reason") == om.ENTRY_FILL_PENDING for r in _rows(journal)[:2])


def test_the_sweep_source_never_calls_an_order_or_bracket_function():
    import inspect
    src = inspect.getsource(om._sweep_entry_fill_writeback) + inspect.getsource(om.entry_fill_decision)
    for forbidden in ("place_order", "amend_order", "cancel_order", "modify_open_order", "set_trading_stop",
                      "_submit_order", "update_trade_sl", "apply_intent_reduce", "_resize_slice"):
        assert forbidden not in src, forbidden
