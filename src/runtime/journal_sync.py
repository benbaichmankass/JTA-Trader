"""journal_sync — the one lock that orders ENTRY DISPATCH against RECONCILIATION.

Row TICK-STAGE2-RECONCILE-OFFTICK (Tier 2, operator decision relayed by the
manager 2026-11-05). Gates this adds or changes: none. Nothing here decides
whether anything trades; it only orders two things that already run.

WHY A LOCK AT ALL. Until this row, `run_reconciliation_tick` ran on the main
loop AFTER `run_one_tick`, so it could never observe an order that had been
placed at the venue but not yet journaled. That ordering was load-bearing,
not incidental: the reverse reconciler's default `ORPHAN_POSITION_POLICY=adopt`
acts on FIRST sight, and the package -> trade row takes up to 7.6 s (audit F8,
n=40). A reconciliation pass running concurrently with a dispatch could adopt
a duplicate of a fill the dispatching thread is about to journal.

`journal_sync()` restores exactly that invariant across threads: entry dispatch
(`Coordinator.multi_account_execute`, place + journal; the M22 pairs tick) and
each reconciliation pass hold the same lock, so neither sees the other
half-done. An entry waits at most one pass, and only when a pass is in flight.

RE-ENTRANT on purpose: `multi_account_execute_typed` calls
`multi_account_execute`, and a plain Lock would deadlock that thread on itself.

SQLITE CONTENTION, BOUNDED. The lock also means the trader process never has
more than one of {entry dispatch, reconciliation} writing the journal at once,
so moving reconciliation off the main thread does not add a concurrent journal
writer. The exit-evaluation thread was already concurrent with both. Its
best-effort telemetry writes take a SHORT busy timeout (`write_busy_timeout`),
so a journal write lock held elsewhere (MEASURED 2026-11-05T08:00:30-08:01:12Z:
a pass of ~15 packages at 2-7 s each, 41,989.8 ms in total, against a ~1 s norm,
alongside main-thread "database is locked" lines) cannot push an exit pass past the
60 s exit-evaluation requirement. Verdict writes (SL/TP moves, closes) keep
`Database`'s 3 s busy timeout: they are rare and must land.

Never raises out of instrumentation. The wrapped body's own exceptions
propagate unchanged.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Iterator

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# The exit-evaluation thread's name, set in src/main.py::_start_exit_loop.
EXIT_LOOP_THREAD_NAME = "exit-evaluation-loop"

_EXIT_WRITE_TIMEOUT_ENV = "EXIT_LOOP_DB_WRITE_TIMEOUT_SECONDS"
_DEFAULT_EXIT_WRITE_TIMEOUT_S = 0.25


@contextlib.contextmanager
def journal_sync(holder: str) -> Iterator[None]:
    """Hold the journal_sync lock for one dispatch or one reconciliation pass.

    Records the wait and the hold under `journal_sync.wait` / `journal_sync.hold`
    (tick_cost files them on-loop or off-loop by thread), so the cost this adds
    to an entry is MEASURED and visible instead of claimed. ``holder`` is used
    for the slow-wait log line only; hook names stay bounded.
    """
    t0 = time.monotonic()
    _LOCK.acquire()
    t1 = time.monotonic()
    try:
        _record("journal_sync.wait", (t1 - t0) * 1000.0)
        if t1 - t0 > 5.0:
            logger.info("journal_sync: %s waited %.1f s for the lock", holder, t1 - t0)
        yield
    finally:
        try:
            _record("journal_sync.hold", (time.monotonic() - t1) * 1000.0)
        finally:
            _LOCK.release()


def is_held_by_current_thread() -> bool:
    """For tests: whether this thread holds the lock (RLock ownership)."""
    try:
        return _LOCK._is_owned()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def exit_write_timeout_seconds() -> float:
    """The exit thread's busy timeout for BEST-EFFORT telemetry writes.

    Unparseable or non-positive -> the default (fail toward the bounded value,
    the same discipline as `exit_loop_interval_seconds`).
    """
    try:
        v = float(os.environ.get(_EXIT_WRITE_TIMEOUT_ENV, "")
                  or _DEFAULT_EXIT_WRITE_TIMEOUT_S)
    except (TypeError, ValueError):
        return _DEFAULT_EXIT_WRITE_TIMEOUT_S
    return v if v > 0 else _DEFAULT_EXIT_WRITE_TIMEOUT_S


def write_busy_timeout(default: float) -> float:
    """sqlite ``timeout=`` for a best-effort observability write.

    On the exit-evaluation thread: the short bound, so a held journal lock
    costs at most that per write and the pass stays inside 60 s. Elsewhere:
    the caller's own default, unchanged.
    """
    try:
        if threading.current_thread().name == EXIT_LOOP_THREAD_NAME:
            return min(float(default), exit_write_timeout_seconds())
    except Exception:  # noqa: BLE001
        pass
    return default


def _record(name: str, elapsed_ms: float) -> None:
    try:
        from src.runtime.tick_cost import record_hook
        record_hook(name, elapsed_ms)
    except Exception:  # noqa: BLE001 — measurement never breaks the caller
        pass
