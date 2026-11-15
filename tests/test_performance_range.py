"""``GET /api/bot/performance?since=&until=`` -- explicit calendar range.

Root cause pinned (2026-11-12): the SPA's 30d tile read 35 / -22.87 against
the bot's 34 / -19.89 because the SPA cut at the START of the UTC day 30 days
ago while the bot cuts at now-30d; one close in between (ETHUSDT, 03:33Z,
-2.981) is in one window and not the other. ``since=`` makes the cutoff the
caller's, so the SPA can ask for exactly what it displays.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main
from src.web.api.routers import performance as perf

_SCHEMA = """
CREATE TABLE trades (
    id INTEGER PRIMARY KEY, account_id TEXT, strategy_name TEXT, symbol TEXT,
    direction TEXT, entry_price REAL, stop_loss REAL, position_size REAL,
    pnl REAL, status TEXT, is_backtest INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0, account_class TEXT, setup_type TEXT,
    reconcile_status TEXT, exit_reason TEXT, closed_at TEXT, timestamp TEXT,
    notes TEXT);
CREATE TABLE order_packages (
    order_package_id TEXT PRIMARY KEY, linked_trade_id INTEGER, updated_at TEXT);
"""

# (closed_at, pnl)
_ROWS = [
    ("2026-10-13T03:33:20+00:00", -2.981),   # the boundary trade
    ("2026-10-13T10:00:00+00:00", 5.0),
    ("2026-10-20T10:00:00+00:00", -1.0),
    ("2026-11-12T23:30:00+00:00", 2.0),      # last second of the end day
    ("2026-11-13T00:00:00+00:00", 9.0),      # next day: out of until=2026-11-12
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "trade_journal.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_SCHEMA)
    for i, (closed, pnl) in enumerate(_ROWS, start=1):
        conn.execute(
            "INSERT INTO trades (id, account_id, strategy_name, symbol, direction,"
            " entry_price, stop_loss, position_size, pnl, status, is_backtest,"
            " is_demo, account_class, closed_at, timestamp) VALUES"
            " (?, 'bybit_2','s','ETHUSDT','long',100,99,1,?,'closed',0,0,"
            "'real_money',?,?)", (i, pnl, closed, closed))
    conn.commit()
    conn.close()
    monkeypatch.setattr(perf, "_DB_PATH", db)
    return TestClient(api_main.app, raise_server_exceptions=False)


def test_day_aligned_since_includes_the_boundary_trade(client):
    a = client.get("/api/bot/performance?since=2026-10-13T09:20:29Z"
                   "&until=2026-11-12").json()
    b = client.get("/api/bot/performance?since=2026-10-13&until=2026-11-12").json()
    assert a["totalTrades"] == 3 and b["totalTrades"] == 4
    assert round(b["totalPnl"] - a["totalPnl"], 3) == -2.981


def test_until_date_is_inclusive_of_the_whole_day(client):
    body = client.get("/api/bot/performance?since=2026-10-13&until=2026-11-12").json()
    assert body["totalTrades"] == 4          # 11-13T00:00 excluded, 11-12T23:30 in


def test_echoes_range_and_marks_window(client):
    body = client.get("/api/bot/performance?since=2026-10-13&until=2026-11-12").json()
    assert body["window"] == "range"
    assert body["since"] == "2026-10-13T00:00:00Z"
    assert body["until"] == "2026-11-12T00:00:00Z"
    assert body["filterState"] == "parsed"
    assert "paper" in body and "paperPortfolio" in body and "demo" in body


def test_only_until_or_only_since(client):
    assert client.get("/api/bot/performance?until=2026-10-13").json()["totalTrades"] == 2
    body = client.get("/api/bot/performance?since=2026-10-20").json()
    assert body["totalTrades"] == 3 and body["until"] is None


@pytest.mark.parametrize("qs", [
    "since=garbage", "until=nope", "since=2026-11-12&until=2026-11-01",
    "since=2026-11-12T10:00:00Z&until=2026-11-12T09:00:00Z"])
def test_bad_or_inverted_range_is_400(client, qs):
    r = client.get(f"/api/bot/performance?{qs}")
    assert r.status_code == 400
    assert r.json()["detail"]["filter_state"] in ("unparsed", "inverted")


def test_empty_range_is_200_with_null_stats_not_error(client):
    body = client.get("/api/bot/performance?since=2027-01-01&until=2027-01-02").json()
    assert body["totalTrades"] == 0 and body["error"] is False
    assert body["profitFactor"] is None


def test_window_behaviour_unchanged_without_range(client):
    assert client.get("/api/bot/performance?window=all").json()["totalTrades"] == 5
    assert client.get("/api/bot/performance?window=bogus").status_code == 400
    assert "until" not in client.get("/api/bot/performance?window=all").json()
