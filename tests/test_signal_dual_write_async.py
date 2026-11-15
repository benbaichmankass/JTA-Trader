"""DB-LOCK-HOLDERS-DESK-BUILD (2026-11-14): the signal SQL dual-write runs off the calling thread with lock retries,
and db_lock_diag names other processes holding the journal."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import db_lock_diag as dld  # noqa: E402
from src.utils import signal_audit_logger as sal  # noqa: E402


def test_lock_then_success_retries_and_writes():
    calls = []

    def insert(p):
        calls.append(p)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
    slept = []
    assert sal._write_with_retry({"x": 1}, insert=insert, sleep=slept.append) is True
    assert len(calls) == 3 and slept == [1.0, 2.0]


def test_non_lock_error_is_not_retried():
    calls = []

    def insert(p):
        calls.append(p)
        raise ValueError("bad row")
    assert sal._write_with_retry({"x": 1}, insert=insert, sleep=lambda s: None) is False
    assert len(calls) == 1


def test_persistent_lock_gives_up_after_the_registered_retries():
    calls = []

    def insert(p):
        calls.append(p)
        raise sqlite3.OperationalError("database is locked")
    assert sal._write_with_retry({"x": 1}, insert=insert, sleep=lambda s: None) is False
    assert len(calls) == len(sal._DW_RETRIES) + 1


def test_async_path_returns_without_waiting_on_the_db(monkeypatch):
    """The calling (trading) thread must not wait on the SQL write: a slow insert stays on the writer thread."""
    monkeypatch.setenv("SIGNAL_DUAL_WRITE_ASYNC_IN_TEST", "1")
    monkeypatch.delenv("SIGNAL_DUAL_WRITE_SYNC", raising=False)
    done = []

    def slow(payload, **_kw):
        time.sleep(0.5)
        done.append(payload)
        return True
    monkeypatch.setattr(sal, "_write_with_retry", slow)
    t = time.monotonic()
    sal._dual_write_to_db({"strategy": "s", "symbol": "BTC"})
    assert time.monotonic() - t < 0.2, "the caller waited on the SQL write"
    sal._dw_queue.join()
    assert done and done[0]["symbol"] == "BTC"


def test_under_pytest_the_default_stays_synchronous(monkeypatch):
    monkeypatch.delenv("SIGNAL_DUAL_WRITE_ASYNC_IN_TEST", raising=False)
    assert sal._dual_write_sync() is True


def test_other_holders_names_a_process_with_the_journal_open(tmp_path):
    db = tmp_path / "trade_journal.db"
    db.write_text("")
    proc = tmp_path / "proc"
    other = proc / "4242"
    (other / "fd").mkdir(parents=True)
    os.symlink(str(db) + "-wal", other / "fd" / "7")
    (other / "cmdline").write_bytes(b"python3\0-m\0uvicorn\0web\0")
    (other / "comm").write_text("python3\n")
    quiet = proc / "4343"
    (quiet / "fd").mkdir(parents=True)
    os.symlink(str(tmp_path / "other.db"), quiet / "fd" / "3")
    mine = proc / str(os.getpid())
    (mine / "fd").mkdir(parents=True)
    os.symlink(str(db), mine / "fd" / "5")
    got = dld.describe_other_holders(str(db), proc_root=str(proc))
    assert got.startswith("4242:python3:python3 -m uvicorn web"), got
    assert "4343" not in got and str(os.getpid()) not in got


def test_other_holders_reports_none_and_never_raises(tmp_path):
    assert dld.describe_other_holders(str(tmp_path / "j.db"), proc_root=str(tmp_path / "empty")).startswith("could_not_look")
    (tmp_path / "p").mkdir()
    assert dld.describe_other_holders(str(tmp_path / "j.db"), proc_root=str(tmp_path / "p")) == "none"
