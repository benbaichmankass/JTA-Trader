"""CLOSED-TRADE-SNAPSHOT-WRITER: the web-api background builder (new closes + backfill), contained per trade."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import trade_snapshot_builder as b
from src.runtime import trade_snapshot_store as store
from tests.fixtures.real_schema_db import insert_order_package, insert_trade, make_canonical_db
from tests.test_trade_chart_snapshot import PKG, RECEIPTS, REVIEWS, _candles, insert_prop_trade

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
EMPTY = {"state": "read", "rows": []}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "trade_journal.db"
    make_canonical_db(p)
    insert_order_package(p, order_package_id=PKG, created_at="2026-11-12T01:00:00+00:00", status="closed", meta="{}")
    return p


def _trade(db, opened="2026-11-12T01:00:00+00:00", closed="2026-11-12T07:00:00+00:00", **kw):
    f = dict(timestamp=opened, closed_at=closed, symbol="BTCUSDT", direction="long", entry_price=100.0,
             exit_price=101.0, position_size=1.0, status="closed", is_backtest=0, account_id="bybit_1",
             order_package_id=PKG)
    f.update(kw)
    return insert_trade(db, **f)


def _fetch_ok(calls=None):
    def fetch(symbol, interval, since_ms, limit):
        if calls is not None:
            calls.append((symbol, interval, since_ms, limit))
        start = int(datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        return _candles(start, 120), "test"
    return fetch


def _row(db, tid):
    return store.read_key(str(db.parent / "trade_chart_snapshots.db"),
                          tid if isinstance(tid, str) else store.trade_key(tid))


def test_builds_closed_trade_once_and_is_idempotent(db):
    tid = _trade(db)
    calls = []
    assert b.run_batch(db, _fetch_ok(calls), NOW, reviews=REVIEWS, receipts=RECEIPTS)["built_partial"] == 1
    got = _row(db, tid)
    assert got["state"] == "built" and got["payload"]["trade"]["trade_id"] == tid
    assert "indicators" not in got["payload"]            # stored slim; the route recomputes them
    assert calls[0][1] == "5m" and calls[0][2] is not None   # historical read from the window start
    assert b.run_batch(db, _fetch_ok(calls), NOW, reviews=REVIEWS, receipts=RECEIPTS) == \
        {"built": 0, "built_partial": 0, "retrying": 0}
    assert len(calls) == 1


def test_waits_until_post_close_window_has_passed(db):
    _trade(db, opened="2026-11-12T10:00:00+00:00", closed="2026-11-12T11:50:00+00:00")   # window ends 12:06:30
    assert sum(b.run_batch(db, _fetch_ok(), NOW, reviews=EMPTY, receipts=EMPTY).values()) == 0
    assert sum(b.run_batch(db, _fetch_ok(), NOW + timedelta(minutes=10), reviews=EMPTY, receipts=EMPTY).values()) == 1


def test_open_and_backtest_trades_are_skipped(db):
    _trade(db, status="open", closed=None)
    _trade(db, is_backtest=1)
    assert sum(b.run_batch(db, _fetch_ok(), NOW, reviews=EMPTY, receipts=EMPTY).values()) == 0


def test_candle_failure_retries_then_stores_partial_without_candles(db):
    tid = _trade(db)
    none = lambda *a: (None, "test")  # noqa: E731
    t = NOW
    assert b.run_batch(db, none, t, reviews=EMPTY, receipts=EMPTY)["retrying"] == 1
    got = _row(db, tid)
    assert got["state"] == "retrying" and got["attempts"] == 1 and "candles_unavailable" in got["last_error"]
    # not due again until the backoff passes
    assert sum(b.run_batch(db, none, t + timedelta(seconds=60), reviews=EMPTY, receipts=EMPTY).values()) == 0
    t += timedelta(seconds=b.BACKOFF_S[0] + 1)
    assert b.run_batch(db, none, t, reviews=EMPTY, receipts=EMPTY)["retrying"] == 1
    t += timedelta(seconds=b.BACKOFF_S[1] + 1)
    assert b.run_batch(db, none, t, reviews=EMPTY, receipts=EMPTY)["built_partial"] == 1
    got = _row(db, tid)
    assert got["state"] == "built" and got["payload"]["candles"]["state"] == "unavailable"


def test_one_bad_trade_does_not_stop_the_batch(db):
    bad = _trade(db, closed="not-a-time")
    good = _trade(db)
    out = b.run_batch(db, _fetch_ok(), NOW, reviews=EMPTY, receipts=EMPTY)
    assert out["retrying"] == 1 and out["built_partial"] == 1
    assert _row(db, bad)["state"] == "retrying" and _row(db, good)["state"] == "built"


def test_newest_first_and_batch_limit(db):
    ids = [_trade(db) for _ in range(5)]
    b.run_batch(db, _fetch_ok(), NOW, limit=2, reviews=EMPTY, receipts=EMPTY)
    built = [i for i in ids if _row(db, i)["state"] == "built"]
    assert built == ids[-2:]


def test_recent_fallback_when_connector_has_no_since(db):
    _trade(db)

    def fetch(symbol, interval, since_ms, limit):
        if since_ms is not None:
            return None, "test"           # e.g. IB / Alpaca: no historical since read
        start = int(datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc).timestamp())
        return _candles(start, limit), "test"

    assert b.run_batch(db, fetch, NOW, reviews=EMPTY, receipts=EMPTY)["built_partial"] == 1


def test_route_reads_what_the_builder_wrote(db, monkeypatch):
    from fastapi.testclient import TestClient
    from src.web.api import main as api_main
    from src.web.api.routers import trade_snapshot as router
    tid = _trade(db)
    b.run_batch(db, _fetch_ok(), NOW, reviews=REVIEWS, receipts=RECEIPTS)
    monkeypatch.setattr(router, "_DB_PATH", db)
    monkeypatch.setattr(router, "_SNAP_PATH", db.parent / "trade_chart_snapshots.db")
    d = TestClient(api_main.app).get(f"/api/bot/trades/{tid}/snapshot").json()
    assert d["snapshot"]["indicators"]["state"] == "measured"
    assert json.dumps(d)  # serialisable


def test_startup_hook_does_not_spawn_under_pytest():
    from src.web.api import main as api_main
    api_main._start_trade_snapshot_builder()
    assert b._thread is None


def test_prop_closed_trade_is_built_keyed_by_closing_row(db):
    opener, closer = insert_prop_trade(db)
    out = b.run_batch(db, _fetch_ok(), NOW, reviews=REVIEWS, receipts=RECEIPTS)
    assert sum(out.values()) == 1 and out["retrying"] == 0
    got = _row(db, store.prop_key(closer))
    assert got["state"] == "built"
    assert got["payload"]["trade"]["prop_fill_id"] == opener and got["payload"]["trade"]["account_class"] == "prop"
    assert got["payload"]["brackets"]["tp_history"] == "recorded"
    assert sum(b.run_batch(db, _fetch_ok(), NOW, reviews=REVIEWS, receipts=RECEIPTS).values()) == 0


def test_open_prop_trade_not_built(db):
    insert_prop_trade(db, closed=False)
    assert sum(b.run_batch(db, _fetch_ok(), NOW, reviews=EMPTY, receipts=EMPTY).values()) == 0


def test_no_prop_tables_is_not_an_error(tmp_path):
    p = tmp_path / "j.db"
    make_canonical_db(p)
    conn = sqlite3.connect(str(p))
    conn.execute("DROP TABLE IF EXISTS prop_fills")
    conn.commit()
    conn.close()
    assert sum(b.run_batch(p, _fetch_ok(), NOW, reviews=EMPTY, receipts=EMPTY).values()) == 0


def test_writer_never_writes_the_journal(db):
    """Manager condition 2026-11-12: no write transaction on trade_journal.db. The journal file is made
    read-only on disk; a single write (DDL, insert, even a WAL switch) would raise 'readonly database'."""
    import os
    import stat
    tid = _trade(db)
    insert_prop_trade(db)
    wal = db.parent / (db.name + "-wal")
    before = (db.read_bytes(), wal.read_bytes() if wal.exists() else None)
    os.chmod(db, stat.S_IRUSR | stat.S_IRGRP)   # (root ignores this; the byte checks below are the proof)
    try:
        out = b.run_batch(db, _fetch_ok(), NOW, reviews=REVIEWS, receipts=RECEIPTS)
    finally:
        os.chmod(db, stat.S_IRUSR | stat.S_IWUSR)
    assert out["retrying"] == 0 and out["built"] + out["built_partial"] == 2
    after = (db.read_bytes(), wal.read_bytes() if wal.exists() else None)
    assert after == before                                             # journal + its WAL byte-identical
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (store.TABLE,)).fetchone() is None
    conn.close()
    assert _row(db, tid)["state"] == "built"                           # the snapshot is in its own file


def test_attached_journal_rejects_writes(db, tmp_path):
    conn = store.snapshots_rw(str(tmp_path / "s.db"), journal_path=str(db))
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO j.trades (timestamp, symbol, direction, entry_price, position_size) "
                     "VALUES ('t', 'X', 'long', 1, 1)")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        store.journal_ro(str(db)).execute("CREATE TABLE x (a)")
    conn.close()
