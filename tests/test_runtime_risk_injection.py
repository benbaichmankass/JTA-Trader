"""
Tests for _inject_runtime_counters in src.runtime.pipeline.

Verifies that CURRENT_DAILY_LOSS_USD is correctly injected into the
settings dict before safe_place_order is called (CURRENT_OPEN_POSITIONS was
retired 2026-10-21).

All tests are network-free and DB-free (in-memory SQLite where needed).

Tests:
  1. No exchange, no DB   — counters absent, original settings unchanged.
  2-4. (retired) positions counter is never injected.
  5. Daily loss below cap — CURRENT_DAILY_LOSS_USD = "50.0" (negative pnl).
  6. Daily loss positive  — CURRENT_DAILY_LOSS_USD = "0.0" (profit day → 0 loss).
  7. Backtest exclusion   — is_backtest=1 row ignored; is_backtest=0 row counted.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date


from src.runtime.risk_counters import inject_runtime_counters as _inject_runtime_counters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_with_trades(rows: list[dict]) -> str:
    """Create a temp SQLite DB with a trades table and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            pnl REAL,
            status TEXT DEFAULT 'open',
            is_backtest BOOLEAN DEFAULT 1
        )"""
    )
    today = date.today().isoformat()
    for r in rows:
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, entry_price, pnl, status, is_backtest) "
            "VALUES (?, 'BTCUSDT', 'long', 50000, ?, ?, ?)",
            (r.get("timestamp", today + "T12:00:00"), r["pnl"], r["status"], r["is_backtest"]),
        )
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Test 1: no exchange, no DB → counters absent
# ---------------------------------------------------------------------------

def test_no_db_leaves_settings_unchanged():
    settings = {"SYMBOL": "BTCUSDT"}
    result = _inject_runtime_counters(settings)
    assert "CURRENT_OPEN_POSITIONS" not in result
    assert "CURRENT_DAILY_LOSS_USD" not in result
    assert result["SYMBOL"] == "BTCUSDT"


def test_original_settings_dict_not_mutated():
    settings = {"SYMBOL": "BTCUSDT"}
    _inject_runtime_counters(settings)
    assert "CURRENT_OPEN_POSITIONS" not in settings


# ---------------------------------------------------------------------------
# Retired 2026-10-21 (RETIRE-GLOBAL-POSCAP): no positions fetch, no exchange arg
# ---------------------------------------------------------------------------

def test_open_position_counter_never_injected():
    path = _db_with_trades([{"pnl": -1.0, "status": "closed", "is_backtest": 0}])
    try:
        result = _inject_runtime_counters({"TRADE_JOURNAL_DB": path})
        assert "CURRENT_OPEN_POSITIONS" not in result
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Test 5: daily loss — negative pnl → abs value injected
# ---------------------------------------------------------------------------

def test_daily_loss_negative_pnl():
    path = _db_with_trades([{"pnl": -50.0, "status": "closed", "is_backtest": 0}])
    try:
        result = _inject_runtime_counters({"TRADE_JOURNAL_DB": path})
        assert result["CURRENT_DAILY_LOSS_USD"] == "50.0"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Test 6: positive pnl day → CURRENT_DAILY_LOSS_USD = "0.0"
# ---------------------------------------------------------------------------

def test_daily_loss_positive_pnl_is_zero():
    path = _db_with_trades([{"pnl": 200.0, "status": "closed", "is_backtest": 0}])
    try:
        result = _inject_runtime_counters({"TRADE_JOURNAL_DB": path})
        assert result["CURRENT_DAILY_LOSS_USD"] == "0.0"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Test 7: backtest exclusion (the critical correctness test)
# ---------------------------------------------------------------------------

def test_backtest_rows_excluded_from_daily_loss():
    """is_backtest=1 pnl=-9999 must be ignored; is_backtest=0 pnl=-50 is counted."""
    today = date.today().isoformat() + "T10:00:00"
    rows = [
        {"pnl": -9999.0, "status": "closed", "is_backtest": 1, "timestamp": today},
        {"pnl": -50.0,   "status": "closed", "is_backtest": 0, "timestamp": today},
    ]
    path = _db_with_trades(rows)
    try:
        result = _inject_runtime_counters({"TRADE_JOURNAL_DB": path})
        assert result["CURRENT_DAILY_LOSS_USD"] == "50.0"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Additional: DB error → counter absent, no exception
# ---------------------------------------------------------------------------

def test_db_error_no_counter_no_raise():
    result = _inject_runtime_counters(
        {"TRADE_JOURNAL_DB": "/nonexistent/path/that/cannot/exist.db"},
    )
    assert "CURRENT_DAILY_LOSS_USD" not in result


def test_open_trades_excluded_from_daily_loss():
    """status='open' rows must not contribute to the daily loss figure."""
    path = _db_with_trades([{"pnl": -300.0, "status": "open", "is_backtest": 0}])
    try:
        result = _inject_runtime_counters({"TRADE_JOURNAL_DB": path})
        # No closed trades → SUM is NULL → loss = 0.0
        assert result["CURRENT_DAILY_LOSS_USD"] == "0.0"
    finally:
        os.unlink(path)
