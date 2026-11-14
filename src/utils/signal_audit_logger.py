from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from src.utils.jsonl_rotate import append_line
from src.utils.paths import runtime_logs_dir

logger = logging.getLogger(__name__)

# Writer path resolved through runtime_logs_dir() so DATA_DIR /
# RUNTIME_LOGS_DIR overrides apply consistently with the heartbeat +
# runtime_status writers. Pre-2026-05-11 this was hardcoded to
# ``Path(__file__).resolve().parents[2] / "runtime_logs"``, which
# diverged from runtime_logs_dir() the moment the OCI block-storage
# drop-in went in: liveness_watchdog + hourly_report read from the
# DATA_DIR-resolved path and found nothing while audit was being
# written at the repo path.
BASE = runtime_logs_dir()
SIGNAL_FILE = BASE / "signal_audit.jsonl"
SIGNAL_AUDIT_ROTATE_MB = 256  # env JSONL_ROTATE_MAX_MB overrides
SUMMARY_FILE = BASE / "summary_markers.json"


# ── DB-LOCK-HOLDERS-DESK-BUILD (2026-11-14): the SQL side goes through ONE background writer ───────────────────────
# MEASURED 11-13 03:22-23:00Z: 10 "SQL dual-write failed: database is locked". Every one stalled the CALLING thread
# (MainThread, inside a strategy signal builder) for the full 3 s busy_timeout and then dropped the SQL row. An
# experiment on the real schema shows Database() init takes no write lock; insert_signal waits 3 s and fails only
# while ANOTHER writer holds the lock. So the fix is not a longer wait on the trading thread: the JSONL write stays
# synchronous (the source of truth), and the SQL row is queued to a daemon writer that retries with backoff off
# the decision path. Nothing halts: a full queue drops the SQL row with one warning per burst (JSONL keeps it).
_DW_QUEUE_MAX = 5000
_DW_RETRIES = (1.0, 2.0, 4.0)          # seconds slept before each retry after a lock failure
_dw_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=_DW_QUEUE_MAX)
_dw_thread: Optional[threading.Thread] = None
_dw_start_lock = threading.Lock()
_dw_dropped = 0
_dw_stats = {"written": 0, "retried": 0, "failed": 0, "dropped": 0}


def _dual_write_sync() -> bool:
    """Synchronous dual-write: tests (a background thread must not outlive a test's monkeypatched paths) or the
    explicit opt-out ``SIGNAL_DUAL_WRITE_SYNC=true``."""
    if os.environ.get("SIGNAL_DUAL_WRITE_SYNC", "").strip().lower() in {"true", "1", "yes", "on"}:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not os.environ.get("SIGNAL_DUAL_WRITE_ASYNC_IN_TEST")


def _write_with_retry(payload: Dict[str, Any], *, insert: Optional[Callable[[Dict[str, Any]], Any]] = None,
                      sleep: Callable[[float], None] = time.sleep) -> bool:
    """One SQL row with lock retries (off the calling thread). True when written. Never raises."""
    if insert is None:
        def insert(p: Dict[str, Any]) -> Any:
            from src.units.db.database import Database
            return Database().insert_signal(p)   # canonical resolver -- never the bare-CWD fallback
    last: Optional[BaseException] = None
    for attempt in range(len(_DW_RETRIES) + 1):
        try:
            insert(payload)
            _dw_stats["written"] += 1
            return True
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "locked" not in str(exc).lower() or attempt == len(_DW_RETRIES):
                break
            _dw_stats["retried"] += 1
            sleep(_DW_RETRIES[attempt])
    _dw_stats["failed"] += 1
    logger.warning("signal_audit_logger: SQL dual-write failed: %s", last)
    try:
        from src.utils.db_lock_diag import log_lock_context

        if last is not None:
            log_lock_context("signal_audit_logger.dual_write", last)
    except Exception:  # noqa: BLE001 -- diagnostics only
        pass
    return False


def _dw_loop() -> None:
    while True:
        payload = _dw_queue.get()
        try:
            _write_with_retry(payload)
        finally:
            _dw_queue.task_done()


def _ensure_writer() -> None:
    global _dw_thread
    if _dw_thread is not None and _dw_thread.is_alive():
        return
    with _dw_start_lock:
        if _dw_thread is None or not _dw_thread.is_alive():
            _dw_thread = threading.Thread(target=_dw_loop, name="signal-dual-write", daemon=True)
            _dw_thread.start()


def _enqueue(payload: Dict[str, Any]) -> bool:
    global _dw_dropped
    try:
        _dw_queue.put_nowait(payload)
        return True
    except queue.Full:
        _dw_dropped += 1
        _dw_stats["dropped"] += 1
        if _dw_dropped == 1 or _dw_dropped % 500 == 0:
            logger.warning("signal_audit_logger: SQL dual-write queue full (%d); dropped %d SQL row(s) "
                           "(JSONL keeps them)", _DW_QUEUE_MAX, _dw_dropped)
        return False


def _dual_write_to_db(payload: Dict[str, Any]) -> None:
    """Best-effort: also write *payload* to ``trade_journal.db::signals``.

    S-034 (architecture-audit-2026-05-02 P2-9) transition: the JSONL
    file remains the source of truth during the cutover. This dual-
    write hydrates the SQL signals log so readers can flip over once
    the operator has confirmed one full day of clean writes.

    The opt-out env flag ``SIGNAL_DUAL_WRITE_DISABLED=true`` exists so
    the operator can disable the SQL side cheaply if it ever causes
    pipeline lag — the JSONL writer is unaffected.

    Never raises. DB-side failures log a warning and return; JSONL
    write happens unconditionally upstream.
    """
    if os.environ.get("SIGNAL_DUAL_WRITE_DISABLED", "").strip().lower() in {
        "true", "1", "yes", "on",
    }:
        return
    if _dual_write_sync():
        _write_with_retry(payload, sleep=lambda _s: None)   # tests: same row, no sleeping
        return
    try:
        _ensure_writer()
        _enqueue(dict(payload))
    except Exception as exc:  # noqa: BLE001 -- never raise into the audit writer
        logger.warning("signal_audit_logger: SQL dual-write enqueue failed: %s", exc)


def log_signal(event: Dict[str, Any]) -> None:
    payload = dict(event or {})
    payload.setdefault("logged_at_utc", datetime.now(timezone.utc).isoformat())
    # Size-capped (VM-DISK-GROWTH-20261102): rotates to a gzipped sibling at the cap.
    append_line(SIGNAL_FILE, json.dumps(payload, default=str) + "\n", SIGNAL_AUDIT_ROTATE_MB)
    # Dual-write to trade_journal.db::signals (S-034 transition).
    _dual_write_to_db(payload)
    # M12 S5 — mobile-push observer for buy/sell rows. Matches the
    # /api/bot/signals dashboard filter, so we only push on actual ICT
    # detections (skipping pipeline tick "candle observed" / "no signal"
    # events that would flood the operator's phone). The publish itself
    # is best-effort + feature-flagged + subscription-filtered by the
    # notifier — never propagates into the audit-writer path.
    try:
        _fire_signal_emitted_event(payload)
    except Exception:  # noqa: BLE001  # allow-silent: M12 S5 observer hook — notifier failure must never propagate into audit writer
        pass


def _fire_signal_emitted_event(payload: Dict[str, Any]) -> None:
    """Mirror a buy/sell signal to subscribed Android devices via FCM.

    Gating mirrors ``/api/bot/signals``'s server-side filter so the same
    rows the dashboard surfaces are the same rows that wake the phone —
    no surprise volume that the dashboard wouldn't have shown.

    Lazy import — mobile_push is a sibling module and a startup-ordering
    quirk (or a stripped env without google-auth) must never crash
    log_signal's main path.
    """
    side = str(payload.get("side", "")).lower()
    if side not in ("buy", "sell", "long", "short"):
        return
    from src.runtime.mobile_push import publish_event
    from src.runtime.mobile_push.event_kinds import SIGNAL_EMITTED

    # Subset of the audit row that's useful on a phone notification —
    # mirrors the Signals tab's SignalCard composition. Drop zones (too
    # big for an FCM data payload) and any field that's None.
    out = {
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "strategy": payload.get("strategy"),
        "pattern": payload.get("pattern"),
        "confidence": payload.get("confidence"),
        "price": payload.get("price"),
    }
    out = {k: v for k, v in out.items() if v is not None}
    publish_event(SIGNAL_EMITTED, out)


def _load_state() -> Dict[str, str]:
    if SUMMARY_FILE.exists():
        try:
            return json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: Dict[str, str]) -> None:
    SUMMARY_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def should_send_summary(now_utc: datetime) -> bool:
    """Return True at most once per UTC hour.

    S-022 PR2: cadence flipped from twice-a-day (07:00 / 19:00) to once
    every hour. The slot key is now ``{YYYY-MM-DD}-{HH}`` so the existing
    dedupe machinery (last_slot in summary_markers.json) still applies —
    a tick loop that calls this multiple times within the same hour gets
    True only on the first call.
    """
    now_utc = now_utc.astimezone(timezone.utc)
    slot = f"{now_utc.date()}-{now_utc.hour:02d}"
    state = _load_state()
    if state.get("last_slot") == slot:
        return False
    state["last_slot"] = slot
    _save_state(state)
    return True
