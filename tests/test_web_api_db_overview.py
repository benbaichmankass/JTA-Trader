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
    """The REAL production schema (Database.create_tables), then a few rows with REAL columns
    -- a fictional-column fixture is exactly how `signals` was first mis-modelled as having `ts`."""
    from tests.fixtures.real_schema_db import make_canonical_db
    make_canonical_db(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.executemany(
            "INSERT INTO trades (timestamp, created_at, symbol, direction, entry_price, position_size) VALUES (?,?,?,?,?,?)",
            [("2026-10-10 08:00:00", "2026-10-10 08:00:00", "BTCUSDT", "long", 1.0, 1.0),
             ("2026-10-11T09:30:00Z", "2026-10-11T09:30:00Z", "MES", "short", 1.0, 1.0),   # mixed encodings
             ("2026-10-12 10:15:00", "2026-10-12 10:15:00", "ETHUSDT", "long", 1.0, 1.0)])
        # real `signals` timestamp column is logged_at_utc; the table is left EMPTY on purpose
        conn.execute("INSERT INTO balance_snapshots (account_id, ts, api_ok) VALUES ('a', '1760000000000', 1)")  # epoch ms as text
        conn.execute("INSERT INTO device_tokens (token, platform) VALUES ('SECRET-FCM-TOKEN-VALUE', 'android')")
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
    from src.web.api.routers import db_explorer as dbx
    names = set(_by_name(body))
    assert names <= dbx._TABLE_ALLOWLIST and "device_tokens" not in names
    assert {"trades", "signals", "balance_snapshots"} <= names
    assert "SECRET-FCM-TOKEN-VALUE" not in client.get("/api/bot/db/overview").text


def test_newest_inserted_row_and_mixed_encodings(client: TestClient):
    t = _by_name(client.get("/api/bot/db/overview").json())
    assert t["trades"]["newestRowColumn"] == "created_at"       # preferred: when the row was written
    assert t["trades"]["newestRowAt"] == "2026-10-12T10:15:00Z" and t["trades"]["newestRowState"] == "read"
    assert t["trades"]["ageSeconds"] > 0
    assert t["balance_snapshots"]["newestRowState"] == "read"            # epoch ms parsed
    assert t["balance_snapshots"]["newestRowAt"].startswith("2025-10-0")
    assert t["signals"]["newestRowColumn"] == "logged_at_utc"          # the real column, not a guess


def test_table_without_a_timestamp_column_says_so():
    import datetime
    from src.web.api.routers.db_explorer import _table_overview
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY, n INTEGER)")
    conn.execute("INSERT INTO x (n) VALUES (1)")
    o = _table_overview(conn, "x", "trade_journal", datetime.datetime.now(datetime.timezone.utc))
    assert o["rows"] == 1 and o["newestRowState"] == "no_timestamp_column"
    assert o["newestRowAt"] is None and o["ageSeconds"] is None


def test_missing_db_is_not_zero_tables(client: TestClient):
    dbs = {d["db"]: d for d in client.get("/api/bot/db/overview").json()["dbs"]}
    ts = dbs["trainer_store"]
    assert ts["present"] is False and ts["readState"] == "missing"
    assert ts["sizeBytes"] is None and ts["walBytes"] is None
    assert dbs["trade_journal"]["present"] is True and dbs["trade_journal"]["sizeBytes"] > 0
    s = client.get("/api/bot/db/overview").json()["summary"]
    assert s["dbsMissing"] == 1 and s["emptyTables"] >= 1 and s["tables"] == len(_by_name(client.get("/api/bot/db/overview").json()))


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


# ── budgeted counts: the Overview must never hang on a big table (2026-10-14) ───────────────────
def _big_db(path: Path, rows: int = 1_500_000) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, v INTEGER)")
    conn.execute(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < {rows}) "
                 "INSERT INTO big (v) SELECT i FROM n")
    conn.commit()
    return conn


def test_a_real_slow_count_is_interrupted_and_reported_not_zeroed(tmp_path: Path):
    """The mechanism itself: COUNT(*) runs inside ONE opcode, so a progress handler could not stop it;
    Connection.interrupt() from the timer thread must. Budget 1 ms vs a 1.5M-row table."""
    from src.web.api.routers.db_explorer import _count_rows
    conn = _big_db(tmp_path / "big.db")
    try:
        count, state, estimate, ms = _count_rows(conn, "big", budget_s=0.001)
        assert (count, state) == (None, "count_timed_out")
        assert estimate == 1_500_000                        # MAX(rowid): labelled upper bound, not a count
        assert conn.execute("SELECT COUNT(*) FROM big").fetchone()[0] == 1_500_000   # connection still usable
        count, state, estimate, ms = _count_rows(conn, "big", budget_s=60.0)         # the same table, ample budget
        assert (count, state, estimate) == (1_500_000, "read", None)
    finally:
        conn.close()


def test_timed_out_table_row_keeps_null_vs_zero_honesty(tmp_path: Path, monkeypatch):
    import datetime
    from src.web.api.routers import db_explorer as dbx
    conn = _big_db(tmp_path / "big.db", rows=300_000)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(dbx, "_COUNT_BUDGET_S", 0.0005)
    try:
        t = dbx._table_overview(conn, "big", "trade_journal", datetime.datetime.now(datetime.timezone.utc))
    finally:
        conn.close()
    assert t["rows"] is None and t["rowsState"] == "count_timed_out"
    assert t["empty"] is None                                # unknown is not 'not empty'
    assert t["rowsEstimate"] == 300_000 and t["rowsEstimateBasis"] == "max_rowid_upper_bound"
    assert isinstance(t["countMs"], int)


def test_fast_counts_stay_exact_and_carry_timing(client: TestClient):
    body = client.get("/api/bot/db/overview").json()
    t = _by_name(body)["trades"]
    assert t["rows"] == 3 and t["rowsState"] == "read" and t["rowsEstimate"] is None and t["rowsEstimateBasis"] is None
    assert isinstance(t["countMs"], int) and isinstance(body["elapsedMs"], int)
    assert body["summary"]["countTimedOut"] == 0


def test_a_non_interrupt_count_error_is_count_failed_not_a_timeout():
    from src.web.api.routers.db_explorer import _count_rows

    class Boom:
        def interrupt(self): pass
        def execute(self, *_a): raise sqlite3.OperationalError("no such table: x")
    assert _count_rows(Boom(), "x")[:2] == (None, "count_failed")


def test_overview_cache_is_long_and_serves_stale():
    from src.web.api.routers import db_explorer as dbx
    assert dbx._OVERVIEW_FRESH_S >= 120 and dbx._OVERVIEW_STALE_S >= 3600 and dbx._COUNT_BUDGET_S <= 5
