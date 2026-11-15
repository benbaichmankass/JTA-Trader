"""Lock-holder diagnostics for ``database is locked`` (MECH-FOLLOWUPS-1105, manager 2026-11-06).

THE QUESTION. Three EXIT-EVAL INTERVAL breaches on 2026-11-05 (16:58 74.3 s, 21:47 59.0 s, 02:35 61.4 s) line up with
bursts of ``database is locked`` on ``trade_journal.db``, and the HOLDER of the write lock is unknown: the relay cannot
see sqlite lock owners, the waiter's 3 s ``busy_timeout`` only proves the lock was held that long, and the log carries
no thread name. (PI-20261105-F2QX97PI-0001.)

THE METHOD. A waiter fails WHILE the holder still holds. So at the failure site, log every thread of THIS process with
its current stack. An in-process holder is then visible by name and by where it sits (e.g. inside a broker HTTP call
between a DML statement and its commit). If no thread's stack is in a DB write or commit, the holder is another
process (web-api, a timer unit, the trainer copy) and the log says so.

Pure diagnostics: never raises, logs only, rate-limited, touches no database and no lock.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Optional

logger = logging.getLogger(__name__)

#: At most one report per this many seconds per process (a burst is dozens of failures within ~30 s).
MIN_INTERVAL_S = 20.0
#: Frames kept per thread (innermost last) and threads reported: bounds the log line.
MAX_FRAMES = 7
MAX_THREADS = 24

_lock = threading.Lock()
_last_report = 0.0

#: A frame in any of these suggests the thread is writing, committing or waiting on the journal.
_DB_MARKERS = ("sqlite3", "database.py", "prop_journal", "journal", "signal_audit_logger",
               # MEASURED 2026-11-06: the holder candidate sat in these writers and was tagged `other` because none of
               # the markers above matched their file names (they open their own sqlite3 connection per write).
               "venue_protection_snapshot", "position_path_history", "position_telemetry")
#: A frame in any of these suggests the thread is blocked on the network (a write held across a broker call).
_NET_MARKERS = ("socket.py", "ssl.py", "http/client.py", "urllib3", "requests", "ib_insync", "ibapi", "httpx", "ccxt", "alpaca")


def _is_lock_error(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower() or "database table is locked" in str(exc).lower()


def _compact(frames: traceback.StackSummary) -> str:
    tail = frames[-MAX_FRAMES:]
    return " > ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.name}:{f.lineno}" for f in tail)


def describe_threads() -> str:
    """One line per thread: name, class (db / net / other) and its compact stack. Pure; for tests and the log."""
    me = threading.get_ident()
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in list(sys._current_frames().items())[:MAX_THREADS]:
        stack = traceback.extract_stack(frame)
        text = " ".join(f"{f.filename}:{f.name}" for f in stack)
        kinds = [k for k, marks in (("db", _DB_MARKERS), ("net", _NET_MARKERS)) if any(m in text for m in marks)]
        out.append(f"[{names.get(ident, ident)}{' (this thread, the waiter)' if ident == me else ''}"
                   f" {'+'.join(kinds) or 'other'}] {_compact(stack)}")
    return " || ".join(out)


def describe_other_holders(db_path: Optional[str] = None, *, proc_root: str = "/proc") -> str:
    """Other processes that have the journal (or its -wal/-shm) open NOW, as "pid:comm:cmdline" (Linux /proc scan).

    DB-LOCK-HOLDERS-DESK-BUILD (2026-11-14): 2 of 7 lock dumps on 11-13 showed NO in-process holder and no desk
    build, so the holder was another process and the log could not name it. A process with the file open is a
    candidate, not proof of the holder; the list is the denominator to correlate with. Never raises."""
    import os

    try:
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        real = os.path.realpath(db_path)
        targets = {real, real + "-wal", real + "-shm"}
        me = os.getpid()
        out = []
        for pid in os.listdir(proc_root):
            if not pid.isdigit() or int(pid) == me:
                continue
            fd_dir = os.path.join(proc_root, pid, "fd")
            try:
                hit = any(os.path.realpath(os.path.join(fd_dir, fd)) in targets for fd in os.listdir(fd_dir))
            except OSError:
                continue
            if not hit:
                continue
            try:
                with open(os.path.join(proc_root, pid, "cmdline"), "rb") as fh:
                    cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()[:120]
                with open(os.path.join(proc_root, pid, "comm"), "r", encoding="utf-8") as fh:
                    comm = fh.read().strip()
            except OSError:
                cmd, comm = "?", "?"
            out.append(f"{pid}:{comm}:{cmd}")
        return " || ".join(out) if out else "none"
    except Exception as exc:  # noqa: BLE001 -- diagnostics must never add a failure
        return f"could_not_look ({type(exc).__name__})"


def log_lock_context(where: str, exc: BaseException, *, now: Optional[float] = None) -> bool:
    """If *exc* is a lock error and the rate limit allows, log every thread's stack. Returns True when it logged.

    Call it from the ``except`` of a site that already logs the lock error. Never raises."""
    global _last_report
    try:
        if not _is_lock_error(exc):
            return False
        t = time.monotonic() if now is None else now
        with _lock:
            if t - _last_report < MIN_INTERVAL_S:
                return False
            _last_report = t
        logger.warning("db_lock_diag: %s hit 'database is locked' at %s; in-process thread stacks NOW (a holder is "
                       "still inside its transaction, so look for a [db]/[net] thread that is not the waiter): %s "
                       "#### other processes with the journal open: %s",
                       where, threading.current_thread().name, describe_threads(), describe_other_holders())
        return True
    except Exception:  # noqa: BLE001 -- diagnostics must never add a failure
        return False
