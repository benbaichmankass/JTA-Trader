"""Send an hourly report immediately, bypassing the dedup marker.

Usage:
    PYTHONPATH=. python scripts/send_hourly_now.py

Prints the rendered report to stdout and dispatches it through
``src.runtime.outcomes.send_scheduled`` (the same path the in-process
scheduler in `src/main.py` uses). Useful as:

* a post-merge demo for BUG-032 (the operator confirms the pipe is
  hot end-to-end);
* a recovery hook when `summary_markers.json` is corrupt and the
  scheduled path is silently a no-op;
* the ExecStart for ``ict-hourly-snapshot.service`` (M1 P1-C —
  fires once an hour with a 60 s randomized delay).

Concurrency
-----------

The script grabs an ``fcntl.flock`` exclusive lock on
``/tmp/ict-hourly-snapshot.lock`` (override via
``ICT_HOURLY_LOCK_PATH``) before calling ``send_scheduled``. A second
caller running while the first still holds the lock exits non-zero
with code 75 (EX_TEMPFAIL) and a log line — preventing two timer
firings (or a timer + manual ``/hourly``) from racing.
"""
from __future__ import annotations

import fcntl
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOCK_PATH = "/tmp/ict-hourly-snapshot.lock"
LOCK_BUSY_EXIT_CODE = 75  # POSIX EX_TEMPFAIL — caller may retry later

logger = logging.getLogger(__name__)


def _resolve_lock_path() -> Path:
    return Path(os.environ.get("ICT_HOURLY_LOCK_PATH", DEFAULT_LOCK_PATH))


def _acquire_lock(lock_path: Path):
    """Open ``lock_path`` and grab an exclusive non-blocking flock.

    Returns the file handle so the caller can hold the lock for the
    duration of the dispatch. Closing the handle (or process exit)
    releases the lock automatically.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise
    return fh


def _due(update: str, now) -> tuple[bool, str]:
    try:
        from src.runtime import telegram_settings
        return telegram_settings.is_due(update, now)
    except Exception as exc:  # noqa: BLE001 — a broken gate SENDS, never silences
        return True, f"gate unreadable ({type(exc).__name__}) — sending"


def _window(update: str, now):
    try:
        from src.runtime import telegram_settings
        return telegram_settings.window_start(update, now)
    except Exception:  # noqa: BLE001
        from datetime import timedelta
        return now - timedelta(hours=1)


def _stamp(update: str, now) -> None:
    try:
        from src.runtime import telegram_settings
        telegram_settings.mark_sent(update, now)
    except Exception:  # noqa: BLE001
        logger.warning("send_hourly_now: could not stamp %s", update)


def send_periodic_updates(now) -> dict:
    """Send whichever of SYSTEM health / TRADES snapshot is due. Returns
    ``{update: outcome}``. One data sweep serves both."""
    from src.runtime import telegram_channels
    from src.runtime.hourly_report import (
        assemble_hourly_data, deploy_and_alerts, render_system_health)

    due = {u: _due(u, now) for u in ("system_health", "trades_snapshot")}
    for u, (d, why) in due.items():
        print(f"{u}: {'DUE' if d else 'not due'} ({why})")
    if not any(d for d, _ in due.values()):
        return {u: "not_due" for u in due}
    since_h = _window("system_health", now)
    report = assemble_hourly_data(now_utc=now, tick_interval_s=900, since=since_h)
    out = {}
    if due["system_health"][0]:
        text = render_system_health(report, deploy_and_alerts(since_h, now))
        print(f"--- SYSTEM health check ({len(text)} chars) ---\n{text}")
        try:
            ok = telegram_channels.send("system_health", text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            # The SYSTEM route itself raised: keep the legacy scheduled path as
            # the last rung so the health check is never silently lost.
            logger.warning("system health HTML send failed (%s); scheduled fallback", exc)
            from src.runtime.outcomes import send_scheduled
            send_scheduled(text)
            ok = True
        out["system_health"] = "sent" if ok else "not_sent"
        if ok:
            _stamp("system_health", now)
    if due["trades_snapshot"][0]:
        from src.runtime import trades_snapshot
        since_t = _window("trades_snapshot", now)
        text = trades_snapshot.render(trades_snapshot.gather(since_t, now), since=since_t,
                                      now=now, accounts=report.get("accounts"))
        print(f"--- TRADES snapshot ({len(text)} chars) ---\n{text}")
        try:
            ok = telegram_channels.send("trades_snapshot", text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.warning("trades snapshot send failed: %s", exc)
            ok = False
        out["trades_snapshot"] = "sent" if ok else "not_sent"
        if ok:
            _stamp("trades_snapshot", now)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    lock_path = _resolve_lock_path()

    try:
        lock_fh = _acquire_lock(lock_path)
    except BlockingIOError:
        logger.warning(
            "send_hourly_now: another instance holds %s; skipping.",
            lock_path,
        )
        return LOCK_BUSY_EXIT_CODE

    try:
        # Lazy imports so the lock acquisition (and its failure mode)
        # surfaces a useful error before we touch the runtime modules.
        now = datetime.now(timezone.utc)
        # TELEGRAM-CHANNELS (2026-10-11, operator): the periodic update is
        # SPLIT BY CONTENT — the SYSTEM channel gets the HEALTH CHECK, the
        # TRADES channel the PERFORMANCE SNAPSHOT — each at the operator's own
        # cadence, decided by the ONE shared gate (telegram_settings.is_due).
        # This timer still fires hourly; the gate decides what is due.
        try:
            send_periodic_updates(now)
        except Exception:  # noqa: BLE001 — the watchdog below must still run
            logger.exception("send_hourly_now: periodic updates failed")

        # Liveness watchdog piggybacks on the hourly cycle (moved here from
        # the trader loop): pings when actionable signals fired but no
        # trades landed (the BUG-034 gap). Best-effort; never raises.
        try:
            from src.runtime.liveness_watchdog import run_liveness_watchdog
            run_liveness_watchdog(now_utc=now)
        except Exception:  # noqa: BLE001
            logger.exception("liveness_watchdog dispatch failed")
        return 0
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fh.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
