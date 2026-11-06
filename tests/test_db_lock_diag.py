"""db_lock_diag: a waiter that fails on 'database is locked' reports WHERE the in-process holder is (MECH-FOLLOWUPS-1105)."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from src.utils import db_lock_diag as D


@pytest.fixture(autouse=True)
def _reset():
    D._last_report = 0.0
    yield
    D._last_report = 0.0


def _slow_broker_call(release: threading.Event) -> None:
    release.wait(10)


def _holder(path: str, started: threading.Event, release: threading.Event) -> None:
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO t VALUES (1)")        # implicit transaction: the write lock is now held
    started.set()
    _slow_broker_call(release)                      # ...held ACROSS a slow call, the suspected pattern
    conn.commit()
    conn.close()


def test_the_report_names_the_holder_thread_and_where_it_sits(tmp_path, caplog):
    path = str(tmp_path / "j.db")
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()
    started, release = threading.Event(), threading.Event()
    th = threading.Thread(target=_holder, args=(path, started, release), name="holder-under-test")
    th.start()
    assert started.wait(5)
    try:
        waiter = sqlite3.connect(path)
        waiter.execute("PRAGMA busy_timeout=150")
        with pytest.raises(sqlite3.OperationalError) as ei:
            waiter.execute("INSERT INTO t VALUES (2)")
        with caplog.at_level("WARNING", logger=D.logger.name):
            assert D.log_lock_context("test.waiter", ei.value) is True
    finally:
        release.set()
        th.join(5)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "holder-under-test" in msg and "_slow_broker_call" in msg and "test.waiter" in msg
    assert "(this thread, the waiter)" in msg


def test_rate_limited_and_ignores_other_errors():
    exc = sqlite3.OperationalError("database is locked")
    assert D.log_lock_context("a", exc, now=100.0) is True
    assert D.log_lock_context("a", exc, now=100.0 + D.MIN_INTERVAL_S - 1) is False     # same burst
    assert D.log_lock_context("a", exc, now=100.0 + D.MIN_INTERVAL_S + 1) is True      # next burst
    assert D.log_lock_context("a", ValueError("something else"), now=1000.0) is False


def test_never_raises(monkeypatch):
    monkeypatch.setattr(D, "describe_threads", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert D.log_lock_context("a", sqlite3.OperationalError("database is locked"), now=5.0) is False


def test_the_snapshot_and_history_writers_are_tagged_db_not_other():
    """MEASURED 2026-11-06: the holder candidate sat in venue_protection_snapshot.record_read and was tagged `other`."""
    for marker in ("venue_protection_snapshot", "position_path_history", "position_telemetry"):
        assert marker in D._DB_MARKERS
