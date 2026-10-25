"""GET /api/diag/open_packages (LTR-11): open packages and open trades, filtered in SQL."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main
from src.web.api.routers import diag

_TOKEN = "t" * 64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIAG_READ_TOKEN", _TOKEN)
    monkeypatch.setenv("JWT_SIGNING_KEY", "x" * 64)
    monkeypatch.setenv("ALLOWED_EMAIL", "test@example.com")
    monkeypatch.setenv("WEBAPP_PASSWORD_SHA256", "deadbeef")
    return TestClient(api_main.app, raise_server_exceptions=False)


def _db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, strategy_name TEXT, symbol TEXT, direction TEXT,"
              " entry REAL, sl REAL, tp REAL, status TEXT, close_reason TEXT, created_at TEXT, updated_at TEXT,"
              " linked_trade_id TEXT, meta TEXT)")
    c.execute("CREATE TABLE trades (id INTEGER, order_package_id TEXT, account_id TEXT, account_class TEXT,"
              " strategy_name TEXT, symbol TEXT, direction TEXT, entry_price REAL, stop_loss REAL,"
              " take_profit_1 REAL, timestamp TEXT, status TEXT)")
    c.executemany("INSERT INTO order_packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("pkg-a", "leg_a", "ADAUSDT", "short", 1, 2, 0, "open", None, "t", "t", "1", "{}"),
        ("pkg-b", "leg_b", "XRPUSDT", "long", 1, 0, 2, "closed", "tp", "t", "t", "2", "{}")])
    c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "pkg-a", "bybit_2", "real_money", "leg_a", "ADAUSDT", "short", 1, 2, 0, "t", "open"),
        (2, "pkg-b", "bybit_2", "real_money", "leg_b", "XRPUSDT", "long", 1, 0, 2, "t", "closed")])
    c.commit()
    c.close()


def test_returns_only_open_rows(client, monkeypatch, tmp_path):
    p = tmp_path / "j.db"
    _db(p)
    monkeypatch.setattr(diag, "_DB_PATH", p)
    r = client.get("/api/diag/open_packages", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    d = r.json()
    assert [x["order_package_id"] for x in d["packages"]] == ["pkg-a"]
    assert [x["id"] for x in d["open_trades"]] == [1]
    assert d["counts"] == {"packages": 1, "open_trades": 1} and d["db_state"] == "read"


def test_absent_db_is_could_not_look_not_empty(client, monkeypatch, tmp_path):
    monkeypatch.setattr(diag, "_DB_PATH", tmp_path / "missing.db")
    d = client.get("/api/diag/open_packages", headers={"Authorization": f"Bearer {_TOKEN}"}).json()
    assert d["db_state"] == "db_absent" and d["counts"] is None


def test_requires_the_diag_token(client):
    assert client.get("/api/diag/open_packages").status_code in (401, 403)
