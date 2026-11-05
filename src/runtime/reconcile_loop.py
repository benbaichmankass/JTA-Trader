"""The reconciliation half of the order monitor, on its own thread.

Row TICK-STAGE2-RECONCILE-OFFTICK (Tier 2). Gates this adds or changes: none.
Nothing here decides whether anything trades.

WHAT MOVED. `run_reconciliation_tick` (reconcilers, sweeps, watchdogs, broker-
naked checks) ran inline on the main trader tick after `run_one_tick`. MEASURED
2026-11-05, /api/diag/tick_cost, one process from 06:51:30Z, 78 ticks: tick mean
47,414.7 ms, of which `order_monitor` (this half) was 23,631.5 ms mean / 27,873.3
ms max. Moving it off the tick takes that cost off every signal evaluation.

WHAT DID NOT CHANGE. The same function runs, with the same phases in the same
order, on a bounded cadence (default 60 s start-to-start; a pass that overruns
is followed immediately, never queued). It holds `journal_sync` for the whole
pass, so no entry dispatch is in flight during a pass. That is the invariant
the single-threaded loop gave for free (see src/runtime/journal_sync.py).

NO HALTING (Prime Directive rule 7). A raising pass is logged and the next pass
runs on schedule. A thread that dies is restarted by the main tick. When
passes keep failing, or no pass has completed for `stale_seconds()`, ONE latched
red flag reaches the operator while the loop keeps trying, and a recovery
message clears the latch.

ROLLBACK, ONE ENV FLIP, NO REDEPLOY: `RECONCILE_OFFTICK_DISABLED` truthy puts
the pass back on the main tick (byte-for-byte the pre-change call, now also
inside `journal_sync`, which is uncontended there). A default-off kill switch
over an on capability, the EXIT_LOOP_DECOUPLE_DISABLED shape, not a gate.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

THREAD_NAME = "reconciliation-loop"
HOOK_NAME = "reconciliation_loop"

_INTERVAL_ENV = "RECONCILE_LOOP_INTERVAL_SECONDS"
_DEFAULT_INTERVAL_S = 60.0
_STALE_ENV = "RECONCILE_LOOP_STALE_SECONDS"
# 5x the cadence against a measured ~24-28 s pass: a slow venue never cries
# wolf, and a genuine wedge is flagged within minutes.
_DEFAULT_STALE_S = 300.0
# Consecutive raising passes before the one red flag.
FAILURE_FLAG_AFTER = 5

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_state: Dict[str, Any] = {}


def _reset_state() -> None:
    _state.clear()
    _state.update(
        passes=0, failures=0, consecutive_failures=0,
        last_ok_monotonic=None, last_ok_utc=None, last_error=None,
        started_monotonic=None, thread_restarts=0,
        flag_latched=None,  # None | "failing" | "stale"
    )


_reset_state()


def _env_seconds(env: str, default: float) -> float:
    """Unparseable or non-positive -> default. A typo must never stop the sweep."""
    try:
        v = float(os.environ.get(env, "") or default)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def interval_seconds() -> float:
    return _env_seconds(_INTERVAL_ENV, _DEFAULT_INTERVAL_S)


def stale_seconds() -> float:
    return _env_seconds(_STALE_ENV, _DEFAULT_STALE_S)


def offtick_enabled() -> bool:
    """On unless RECONCILE_OFFTICK_DISABLED is explicitly truthy."""
    v = str(os.environ.get("RECONCILE_OFFTICK_DISABLED") or "").strip().lower()  # allow-silent: rollback kill switch over an ON capability (EXIT_LOOP_DECOUPLE_DISABLED shape); decides WHICH THREAD runs reconciliation, never live/dry or whether anything trades
    return v not in {"1", "true", "yes", "on"}


def _hook():
    try:
        from src.runtime.tick_cost import hook
        return hook(HOOK_NAME)
    except Exception:  # noqa: BLE001
        import contextlib
        return contextlib.nullcontext()


def run_one_pass(run_fn: Callable[[], Any]) -> bool:
    """One reconciliation pass under journal_sync. Never raises. True on success."""
    try:
        from src.runtime.journal_sync import journal_sync
        sync = journal_sync("reconciliation")
    except Exception:  # noqa: BLE001 — the pass still runs without the module
        import contextlib
        sync = contextlib.nullcontext()
    ok = False
    err: Optional[str] = None
    try:
        with sync:
            with _hook():
                run_fn()
        ok = True
    except Exception as exc:  # noqa: BLE001 — contained; retried next pass
        err = f"{type(exc).__name__}: {exc}"
        logger.exception("reconciliation_loop: pass failed (retried next pass)")
    with _lock:
        _state["passes"] += 1
        if ok:
            _state["consecutive_failures"] = 0
            _state["last_ok_monotonic"] = time.monotonic()
            _state["last_ok_utc"] = datetime.now(timezone.utc).isoformat()
        else:
            _state["failures"] += 1
            _state["consecutive_failures"] += 1
            _state["last_error"] = err
    return ok


def _loop(run_fn: Callable[[], Any], stop: Optional[threading.Event] = None) -> None:
    while stop is None or not stop.is_set():
        started = time.monotonic()
        try:
            run_one_pass(run_fn)
        except Exception:  # noqa: BLE001 — belt and braces; run_one_pass never raises
            logger.exception("reconciliation_loop: unexpected error around a pass")
        slack = interval_seconds() - (time.monotonic() - started)
        if slack > 0:
            if stop is not None:
                if stop.wait(slack):
                    return
            else:
                time.sleep(slack)


def start(run_fn: Callable[[], Any]) -> bool:
    """Start the loop thread (daemon). Never raises. True if a thread started."""
    global _thread
    try:
        with _lock:
            if _thread is not None and _thread.is_alive():
                return False
            if _state["started_monotonic"] is None:
                _state["started_monotonic"] = time.monotonic()
            elif _thread is not None:
                _state["thread_restarts"] += 1
            t = threading.Thread(target=_loop, args=(run_fn,), name=THREAD_NAME,
                                 daemon=True)
            t.start()
            _thread = t
        return True
    except Exception:  # noqa: BLE001
        logger.exception("reconciliation_loop: FAILED TO START")
        return False


def status() -> Dict[str, Any]:
    with _lock:
        snap = {k: v for k, v in _state.items() if not k.endswith("_monotonic")}
        last_ok = _state["last_ok_monotonic"]
        started = _state["started_monotonic"]
        alive = _thread is not None and _thread.is_alive()
    now = time.monotonic()
    ref = last_ok if last_ok is not None else started
    snap["age_seconds"] = None if ref is None else round(now - ref, 1)
    snap["thread_alive"] = alive
    return snap


def _send(message: str) -> None:
    try:
        from src.runtime.notify import send_telegram_direct
        send_telegram_direct(message, parse_mode=None, mirror_to_fcm=False)
    except Exception:  # noqa: BLE001
        pass


def ensure_running(run_fn: Callable[[], Any],
                   send: Callable[[str], None] = _send) -> Dict[str, Any]:
    """Called once per main tick: restart a dead thread, raise ONE latched flag
    when passes keep failing or none has completed for stale_seconds(), and
    clear the latch on recovery. Never raises; the trader keeps trading."""
    try:
        with _lock:
            dead = _thread is None or not _thread.is_alive()
        if dead:
            logger.error("reconciliation_loop: thread not alive; restarting")
            start(run_fn)
        st = status()
        age = st.get("age_seconds")
        cause = None
        if st["consecutive_failures"] >= FAILURE_FLAG_AFTER:
            cause = "failing"
        elif age is not None and age > stale_seconds():
            cause = "stale"
        latched = st.get("flag_latched")
        if cause and not latched:
            msg = ("\U0001F534 [ALERT] RECONCILIATION LOOP "
                   + ("FAILING" if cause == "failing" else "STALE")
                   + f" - consecutive_failures={st['consecutive_failures']}, "
                   f"last_ok_utc={st.get('last_ok_utc') or '-'}, "
                   f"last_error={st.get('last_error') or '-'}. Trading continues; "
                   "the loop keeps retrying. Rollback: RECONCILE_OFFTICK_DISABLED=1.")
            logger.error(msg)
            send(msg)
            with _lock:
                _state["flag_latched"] = cause
        elif not cause and latched:
            msg = ("\U0001F7E2 [RECOVERED] reconciliation loop passing again "
                   f"(last_ok_utc={st.get('last_ok_utc') or '-'}).")
            logger.warning(msg)
            send(msg)
            with _lock:
                _state["flag_latched"] = None
        return status()
    except Exception:  # noqa: BLE001
        logger.exception("reconciliation_loop: ensure_running failed")
        return {}


def _reset_for_tests() -> None:
    global _thread
    with _lock:
        _thread = None
    _reset_state()
