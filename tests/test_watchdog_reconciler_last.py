"""WATCHDOG-CLOSE-RECURRENCE — a watchdog finalise records WHY the forward
reconciler had not closed the trade first.

MEASURED 2026-10-24 (venue fills store via /api/bot/pnl/exchange/fills, journal
via /api/diag/journal):

* bybit_2 6528 / 6549: each venue stop filled on the trade's own
  ``sl_order_id`` (06:40:00 / 01:32:08) and the watchdog finalised the row
  ~2.4 min later. The forward reconciler runs earlier in the same tick with the
  same flat confirm, so it should have closed them first; the trader journal
  had rotated before anyone asked why, and the reason was unrecoverable.
* bybit_1 6634: flattened by a sibling's close (fixed by #18514).

These tests pin that the watchdog's finalise now carries ``reconciler_last``,
and that the reconciler records its per-row verdict.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.runtime import order_monitor as om
from src.units.db.database import Database


def _insert_trade(db, *, account_id="bybit_2", symbol="ADAUSDT"):
    return db.insert_trade({
        "timestamp": "2026-10-09T08:04:23+00:00",
        "created_at": "2026-10-09T08:04:23+00:00",
        "symbol": symbol,
        "direction": "short",
        "entry_price": 0.2394,
        "stop_loss": 0.24767143,
        "take_profit_1": 0.2156994,
        "position_size": 406.0,
        "status": "open",
        "account_id": account_id,
        "is_backtest": 0,
        "strategy_name": "ada_pullback_2h",
        "notes": json.dumps(
            {"trade_id": "30eb3acc-ea2e-474a-8cc9-62684c0c6c5e"}),
    })


def _insert_stuck_pkg(db, *, trade_id, symbol="ADAUSDT", age_minutes=45):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO order_packages "
            "(order_package_id, strategy_name, symbol, direction, entry, sl, tp, "
            " confidence, status, linked_trade_id, meta, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now', ? || ' minutes'), "
            " datetime('now', ? || ' minutes'))",
            ("pkg-6549", "ada_pullback_2h", symbol, "short", 0.2394, 0.2477,
             0.2157, 0.5, "open", trade_id, "{}", f"-{age_minutes}",
             f"-{age_minutes}"),
        )
        conn.commit()
    finally:
        conn.close()


def _notes(db, tid):
    conn = db.connect()
    try:
        row = conn.execute("SELECT exit_reason, notes FROM trades WHERE id=?",
                           (tid,)).fetchone()
    finally:
        conn.close()
    return row[0], json.loads(row[1])


_CFG = {"account_id": "bybit_2", "exchange": "bybit",
        "api_key_env": "BYBIT_KEY_2", "mode": "live"}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db_path))
    monkeypatch.setenv("RECONCILER_CLOSE_CONFIRM_SECONDS", "0")
    monkeypatch.setattr("src.runtime.execution_diagnostics.PENDING_PINGS_DIR",
                        tmp_path / "pings")
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile",
                        lambda: {"bybit_2": _CFG})
    monkeypatch.setattr(om, "_cancel_closed_row_protection",
                        lambda *a, **k: None)
    om._PENDING_WATCHDOG_FLAT_CONFIRM.clear()
    om._PENDING_CLOSE_CONFIRM.clear()
    om._RECONCILER_LAST_SEEN.clear()
    yield Database(db_path=str(db_path))
    om._PENDING_WATCHDOG_FLAT_CONFIRM.clear()
    om._PENDING_CLOSE_CONFIRM.clear()
    om._RECONCILER_LAST_SEEN.clear()


def _watchdog_flat_twice(db, recovered=None):
    with patch("src.units.accounts.clients.account_open_positions",
               return_value=[]), \
         patch.object(om, "_recover_close_from_broker_pnl",
                      return_value=recovered):
        om._watchdog_stuck_strategies(db)
        return om._watchdog_stuck_strategies(db)


def test_reconciler_records_an_order_read_failure(tmp_db):
    """The verdict the 6528/6549 shape would leave if the entry-order read
    failed: the reconciler skips the row and says so."""
    tid = _insert_trade(tmp_db)
    with patch("src.units.accounts.clients.account_order_status",
               return_value=None):
        om._reconcile_open_trades(tmp_db)
    assert om._reconciler_last_seen(tid) == "order_read_failed"


def test_reconciler_records_a_live_order_status(tmp_db):
    tid = _insert_trade(tmp_db)
    with patch("src.units.accounts.clients.account_order_status",
               return_value={"status": "New", "filled_qty": 0.0}):
        om._reconcile_open_trades(tmp_db)
    assert om._reconciler_last_seen(tid) == "order_live:new"


def test_reconciler_records_a_pending_flat_confirm(tmp_db):
    tid = _insert_trade(tmp_db)
    with patch("src.units.accounts.clients.account_order_status",
               return_value={"status": "Filled", "filled_qty": 406.0}), \
         patch("src.units.accounts.clients.account_open_positions",
               return_value=[]), \
         patch("src.runtime.positions.position_netting_guard_active_for",
               return_value=True):
        om._reconcile_open_trades(tmp_db)
    assert om._reconciler_last_seen(tid) == "flat_pending_confirm"


def test_watchdog_unmatched_finalise_carries_the_reconcilers_last_verdict(tmp_db):
    tid = _insert_trade(tmp_db)
    _insert_stuck_pkg(tmp_db, trade_id=tid)
    om._note_reconciler_seen(tid, "order_read_failed")

    summary = _watchdog_flat_twice(tmp_db)

    assert summary["closed_local_unmatched"] == 1
    reason, notes = _notes(tmp_db, tid)
    assert reason == "stuck_strategy_watchdog"
    assert notes["reconciler_last"] == "order_read_failed"


def test_watchdog_says_when_the_reconciler_never_saw_the_trade(tmp_db):
    tid = _insert_trade(tmp_db)
    _insert_stuck_pkg(tmp_db, trade_id=tid)

    _watchdog_flat_twice(tmp_db)

    _, notes = _notes(tmp_db, tid)
    assert notes["reconciler_last"] == "not_seen_this_process"


def test_watchdog_recovered_finalise_carries_the_reconcilers_last_verdict(tmp_db):
    tid = _insert_trade(tmp_db)
    _insert_stuck_pkg(tmp_db, trade_id=tid)
    om._note_reconciler_seen(tid, "close_write_failed:OperationalError")
    recovered = {
        "status": "closed", "exit_reason": "sl", "exit_price": 0.2477,
        "closed_at": "2026-10-10T01:32:08+00:00",
        "notes": json.dumps({"exit_reason_source": "price_vs_pkg_bracket"}),
    }

    summary = _watchdog_flat_twice(tmp_db, recovered=recovered)

    assert summary["recovered_closed"] == 1
    reason, notes = _notes(tmp_db, tid)
    assert reason == "sl"
    assert notes["exit_reason_source"] == "price_vs_pkg_bracket"
    assert notes["reconciler_last"] == "close_write_failed:OperationalError"


def test_the_record_is_bounded():
    om._RECONCILER_LAST_SEEN.clear()
    try:
        for i in range(om._RECONCILER_LAST_SEEN_CAP + 10):
            om._note_reconciler_seen(i, "position_alive")
        assert len(om._RECONCILER_LAST_SEEN) == om._RECONCILER_LAST_SEEN_CAP
        assert om._reconciler_last_seen(0) == "not_seen_this_process"
        assert om._reconciler_last_seen(
            om._RECONCILER_LAST_SEEN_CAP + 9) == "position_alive"
        om._note_reconciler_seen("not-an-id", "x")  # never raises
    finally:
        om._RECONCILER_LAST_SEEN.clear()
