"""GET /api/bot/db/overview — summary + health per database (DATA-EXPLORER).

Pins: the session gate, the allowlist/redaction exposure contract (nothing the
explorer hides appears here), null-vs-0 discipline (a failed/missing read is
never a zero), the newest-INSERTED-row semantics, mixed timestamp encodings, and
that the optional integrity check is distinguishable from 'not requested'.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_EMAIL = "operator@example.com"
_KEY = "test-signing-key-not-a-real-secret"


def _bearer() -> dict:
    from src.web.api import auth as auth_module
    return {"Authorization": f"Bearer {auth_module.issue_token(_EMAIL)}"}


def _make_journal(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, created_at TEXT)")
        conn.executemany("INSERT INTO trades (symbol, created_at) VALUES (?, ?)", [
            ("BTCUSDT", "2026-10-10 08:00:00"), ("MES", "2026-10-11T09:30:00Z"),
            ("ETHUSDT", "2026-10-12 10:15:00")])
        conn.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY, ts INTEGER)")      # allowlisted, EMPTY
        conn.execute("CREATE TABLE balance_snapshots (id INTEGER PRIMARY KEY, ts INTEGER)")
        conn.execute("INSERT INTO balance_snapshots (ts) VALUES (1760000000000)")      # epoch milliseconds
        conn.execute("CREATE TABLE insights_usage (id INTEGER PRIMARY KEY, input_tokens INTEGER)")
        conn.execute("INSERT INTO insights_usage (input_tokens) VALUES (5)")           # no timestamp column
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")         # NOT allowlisted
        conn.execute("CREATE TABLE device_tokens (id INTEGER PRIMARY KEY, token TEXT)")
        conn.execute("INSERT INTO device_tokens (token) VALUES ('SECRET-FCM-TOKEN-VALUE')")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from src.web.api import main as api_main
    from src.web.api.routers import db_explorer as dbx
    journal = tmp_path / "trade_journal.db"
    _make_journal(journal)
    monkeypatch.setattr(dbx, "_DB_PATH", journal)
    monkeypatch.setattr(dbx, "_TRAINER_STORE_DB", tmp_path / "trainer_store.db")   # absent on purpose
    monkeypatch.setattr(dbx, "build_if_stale", lambda **kw: None)
    monkeypatch.setattr(dbx, "_OVERVIEW_SWR", None)
    monkeypatch.setenv("JWT_SIGNING_KEY", _KEY)
    monkeypatch.setenv("ALLOWED_EMAIL", _EMAIL)
    return TestClient(api_main.app, raise_server_exceptions=False, headers=_bearer())


def _by_name(body: dict) -> dict:
    return {t["name"]: t for d in body["dbs"] for t in d["tables"]}


def test_requires_a_session(client: TestClient):
    anon = TestClient(client.app, raise_server_exceptions=False)
    assert anon.get("/api/bot/db/overview").status_code == 401


def test_rows_empty_flag_and_owning_db(client: TestClient):
    t = _by_name(client.get("/api/bot/db/overview").json())
    assert t["trades"]["rows"] == 3 and t["trades"]["empty"] is False and t["trades"]["db"] == "trade_journal"
    assert t["signals"]["rows"] == 0 and t["signals"]["empty"] is True
    assert t["signals"]["newestRowState"] == "empty" and t["signals"]["newestRowAt"] is None


def test_exposure_contract_is_inherited(client: TestClient):
    body = client.get("/api/bot/db/overview").json()
    assert set(_by_name(body)) == {"trades", "signals", "balance_snapshots", "insights_usage"}
    assert "SECRET-FCM-TOKEN-VALUE" not in client.get("/api/bot/db/overview").text


def test_newest_inserted_row_and_mixed_encodings(client: TestClient):
    t = _by_name(client.get("/api/bot/db/overview").json())
    assert t["trades"]["newestRowColumn"] == "created_at"
    assert t["trades"]["newestRowAt"] == "2026-10-12T10:15:00Z" and t["trades"]["newestRowState"] == "read"
    assert t["trades"]["ageSeconds"] > 0
    assert t["balance_snapshots"]["newestRowState"] == "read"            # epoch ms parsed
    assert t["balance_snapshots"]["newestRowAt"].startswith("2025-10-0")
    assert t["insights_usage"]["newestRowState"] == "no_timestamp_column"
    assert t["insights_usage"]["newestRowAt"] is None and t["insights_usage"]["ageSeconds"] is None


def test_missing_db_is_not_zero_tables(client: TestClient):
    dbs = {d["db"]: d for d in client.get("/api/bot/db/overview").json()["dbs"]}
    ts = dbs["trainer_store"]
    assert ts["present"] is False and ts["readState"] == "missing"
    assert ts["sizeBytes"] is None and ts["walBytes"] is None
    assert dbs["trade_journal"]["present"] is True and dbs["trade_journal"]["sizeBytes"] > 0
    s = client.get("/api/bot/db/overview").json()["summary"]
    assert s["dbsMissing"] == 1 and s["emptyTables"] == 1 and s["tables"] == 4


def test_integrity_is_opt_in_and_not_requested_is_not_ok(client: TestClient):
    tj = lambda b: next(d for d in b["dbs"] if d["db"] == "trade_journal")  # noqa: E731
    assert tj(client.get("/api/bot/db/overview").json())["integrity"] == {"state": "not_requested", "result": None}
    assert tj(client.get("/api/bot/db/overview?integrity=quick").json())["integrity"] == {"state": "ok", "result": "ok"}
    assert client.get("/api/bot/db/overview?integrity=full").status_code == 422


def test_unreadable_db_is_reported_not_zeroed(client: TestClient, tmp_path: Path, monkeypatch):
    from src.web.api.routers import db_explorer as dbx
    bad = tmp_path / "trainer_store.db"
    bad.write_bytes(b"this is not a sqlite database" * 50)
    monkeypatch.setattr(dbx, "_TRAINER_STORE_DB", bad)
    monkeypatch.setattr(dbx, "_OVERVIEW_SWR", None)
    ts = next(d for d in client.get("/api/bot/db/overview").json()["dbs"] if d["db"] == "trainer_store")
    assert ts["present"] is True and ts["readState"] == "unreadable" and ts["tables"] == []
    assert client.get("/api/bot/db/overview").json()["summary"]["dbsUnreadable"] == 1


def test_parse_any_ts():
    from src.web.api.routers.db_explorer import _parse_any_ts
    assert _parse_any_ts("2026-10-12 10:15:00").isoformat().startswith("2026-10-12T10:15:00")
    assert _parse_any_ts(1760000000).year == 2025 and _parse_any_ts(1760000000000).year == 2025
    for bad in (None, "", "not a date", 0, -5, True):
        assert _parse_any_ts(bad) is None
