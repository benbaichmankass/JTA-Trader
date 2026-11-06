"""Venue protection SNAPSHOT — what the venue was resting for each open package.

WHY THIS EXISTS (checklist row LTR-MECHANICS-VENUE-SNAPSHOT, roadmap L-ATM)
---------------------------------------------------------------------------
The live review's mechanics check ("does the venue SL/TP equal the package's?")
could only be answered by a reviewer pulling the venue by hand. Two paper
mismatches on 2026-10-26 slipped past every automatic surface for that reason:
the ``alpaca_paper`` GLD wedge (journal stop 414.54, venue stop 416.09) and an
``ib_paper`` MGC pullback whose bracket was replaced at the venue by the
``ict_scalp_mgc_15m`` leg's (PI-20261026-UNSVQMPZ-0001). The exit loop's three
broker sweeps ALREADY read the venue's resting stops and targets per symbol to
decide whether a position is naked; they discarded the prices after grading
quantity. This module keeps what they read.

SHAPE
-----
One row per (``order_package_id``, ``account_id``): the LATEST read wins. A
package carried on several accounts has several venue reads, so keying on the
package alone would let one account's read overwrite another's.

``read_state`` is never collapsed (CLAUDE-RULES-CANONICAL § "Collapsed states"):

* ``measured``        — the venue answered and at least one resting stop price
                        was read; ``venue_sl`` is the resting stop NEAREST the
                        package's own stop (so a netted position carrying other
                        packages' stops is graded on the one that belongs here).
* ``none_resting``    — the venue answered and nothing usable rests: flat, or no
                        stop leg. A real finding, owned by the naked sweeps; it
                        is NOT "we could not look" and is never written as one.
* ``could_not_look``  — the read failed, was refused, or returned prices we
                        could not attribute. ``venue_sl`` is NULL and
                        ``read_reason`` says why. Never read as "all clear".

``venue_sl`` / ``venue_tp`` are NULL, never ``0.0``, when no price was read.

CONSTRAINTS (the same ones ``position_telemetry`` / ``position_path_history`` carry)
------------------------------------------------------------------------------
1. **Observe-only; no new order path.** The sweeps pass in prices they ALREADY
   read; this module makes no venue call. Nothing reads the table back to change
   an order, an exit or a stop. The only consumer is
   ``live_review_due.venue_events`` (a read).
2. **Never raises into the exit loop.** A write failure is contained to that one
   write, logged at WARNING once per process (then DEBUG); the next sweep tries
   again. :func:`record_read` returns ``None``/``False`` and nothing else.
3. **Timed.** Every write rides ``tick_cost.hook("monitor.venue_snapshot")`` so
   its cost is MEASURED on the live loop, like ``monitor.position_telemetry``.
4. **Bounded.** ``RETENTION_DAYS`` of rows, pruned at most once an hour per
   process on the write path. The table holds one row per (package, account),
   so it is also bounded by the number of packages.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "venue_protection_snapshot"
HOOK_NAME = "monitor.venue_snapshot"

#: Rows whose ``read_at`` is older than this are deleted on the write path.
RETENTION_DAYS = 30
_PRUNE_EVERY_S = 3600.0

READ_STATES = ("measured", "none_resting", "could_not_look")

_last_prune: Dict[str, float] = {}
_warned: set = set()


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def _warn_once(key: str, msg: str) -> None:
    if key in _warned:
        logger.debug(msg, exc_info=True)
        return
    _warned.add(key)
    logger.warning(msg, exc_info=True)


def _prices(raw: Optional[Iterable[Any]]) -> List[float]:
    out: List[float] = []
    for p in raw or []:
        x = _f(p)
        if x is not None:
            out.append(x)
    return out


def nearest(prices: List[float], reference: Optional[float]) -> Tuple[Optional[float], Optional[str]]:
    """``(price, why_not)``: the resting price nearest *reference*.

    With no reference a single resting price is unambiguous; several are not,
    and guessing which belongs to this package would manufacture either a false
    match or a false divergence, so the answer is ``(None, "no_reference_level")``.
    """
    if not prices:
        return None, "no_price"
    if reference is None:
        if len(prices) == 1:
            return prices[0], None
        return None, "no_reference_level"
    return min(prices, key=lambda p: (abs(p - reference), p)), None


def build_snapshot_row(*, order_package_id: Any, account_id: Any, symbol: Any = None,
                       direction: Any = None, trade_id: Any = None, venue: Any = None,
                       stop_prices: Optional[Iterable[Any]] = None,
                       target_prices: Optional[Iterable[Any]] = None,
                       position_size: Any = None,
                       ref_sl: Any = None, ref_tp: Any = None,
                       unreadable: Optional[str] = None,
                       now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The snapshot row for one venue read. Pure; never raises.

    ``unreadable`` is the reason the sweep could not read the venue (breaker
    open, refusal, read error): it produces a ``could_not_look`` row with no
    prices. Otherwise the sweep's resting ``stop_prices`` / ``target_prices``
    decide ``measured`` vs ``none_resting``. ``ref_sl`` / ``ref_tp`` are the
    package's own levels, used only to pick which resting price belongs here.
    Returns ``None`` when the read cannot be attributed to a package + account.
    """
    try:
        if not order_package_id or not account_id:
            return None
        ts = (now or datetime.now(timezone.utc)).isoformat()
        stops, targets = _prices(stop_prices), _prices(target_prices)
        sl_ref, tp_ref = _f(ref_sl), _f(ref_tp)
        state, reason = "could_not_look", None
        v_sl = v_tp = None
        if unreadable:
            reason = str(unreadable)
        else:
            size = None
            try:
                size = abs(float(position_size)) if position_size is not None else None
            except (TypeError, ValueError):
                size = None
            if size is not None and size <= 0:
                state, reason = "none_resting", "venue_flat"
            elif not stops:
                state, reason = "none_resting", "no_stop_leg"
            else:
                v_sl, why = nearest(stops, sl_ref)
                if v_sl is None:
                    reason = why
                else:
                    state = "measured"
                    # The target is advisory data: a missing/ambiguous one never
                    # downgrades a measured stop (the SL half is what is graded).
                    v_tp, _ = nearest(targets, tp_ref)
        return {
            "order_package_id": str(order_package_id),
            "account_id": str(account_id),
            "trade_id": None if trade_id in (None, "") else str(trade_id),
            "symbol": symbol, "direction": direction, "venue": venue,
            "venue_sl": v_sl, "venue_tp": v_tp,
            "n_stop_legs": len(stops), "n_target_legs": len(targets),
            "ref_sl": sl_ref, "ref_tp": tp_ref,
            "read_state": state, "read_reason": reason,
            "read_at": ts, "first_read_at": ts,
        }
    except Exception:  # noqa: BLE001 — never raise into the exit loop
        _warn_once("build", "venue_protection_snapshot: row build failed")
        return None


_COLS = ("order_package_id", "account_id", "trade_id", "symbol", "direction",
         "venue", "venue_sl", "venue_tp", "n_stop_legs", "n_target_legs",
         "ref_sl", "ref_tp", "read_state", "read_reason", "read_at", "first_read_at")

_UPSERT = (
    f"INSERT INTO {TABLE} ({', '.join(_COLS)}, reads) "
    f"VALUES ({', '.join(':' + c for c in _COLS)}, 1) "
    "ON CONFLICT(order_package_id, account_id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _COLS
                if c not in ("order_package_id", "account_id", "first_read_at"))
    + f", reads={TABLE}.reads + 1"
)


def prune(conn: sqlite3.Connection, *, now: Optional[datetime] = None,
          retention_days: int = RETENTION_DAYS) -> int:
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=retention_days)).isoformat()
    return conn.execute(f"DELETE FROM {TABLE} WHERE read_at < ?", (cutoff,)).rowcount or 0


def _package_for_trade(conn: sqlite3.Connection, trade_id: Any) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """``(order_package_id, sl, tp)`` for a trade, best-effort, else all None."""
    try:
        r = conn.execute(
            "SELECT t.order_package_id, p.sl, p.tp FROM trades t "
            "LEFT JOIN order_packages p ON p.order_package_id = t.order_package_id "
            "WHERE t.id = ?", (int(trade_id),)).fetchone()
    except (sqlite3.Error, TypeError, ValueError):
        return None, None, None  # allow-silent: enrichment only; the caller says why no row
    if not r or not r[0]:
        return None, None, None
    return str(r[0]), _f(r[1]), _f(r[2])


# --- one write transaction per reconciliation sweep (MECH-FOLLOWUPS-1105, manager 2026-11-06) -------------------
#
# MEASURED 2026-11-06 (db_lock_diag, two 'database is locked' bursts, 05:24:23Z and 06:11:12Z): the only in-process
# thread inside a trade_journal.db write at the instant the waiter failed was `reconciliation-loop` in
# `venue_protection_snapshot.record_read` (once at the UPSERT, once at the connect/commit). `record_read` used to open a
# connection, take the write lock and commit PER venue read, i.e. once per (package, account) per sweep, so one sweep took
# the journal's single write lock many times. Inside `batch()` a read is only BUILT (a read-only package lookup, no write
# lock) and queued; the outermost exit writes every queued row in ONE connection / ONE transaction. The lock is therefore
# held for one short executemany, never across a broker call between two reads. Outside `batch()` nothing changes.

_batch_state = threading.local()


class _Batch:
    __slots__ = ("rows", "ro", "path")

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.ro: Optional[sqlite3.Connection] = None
        self.path: Optional[str] = None


def _flush(rows: List[Dict[str, Any]], path: str) -> Tuple[int, float]:
    """Write *rows* in ONE connection and ONE transaction. Returns ``(rows_written, ms_connect_to_commit)``.
    Never raises (a failure is contained, logged once, and the next sweep re-reads and retries)."""
    if not rows:
        return 0, 0.0
    t0 = time.monotonic()
    try:
        with sqlite3.connect(path, timeout=_write_busy_timeout(5.0)) as conn:
            conn.executemany(_UPSERT, rows)
            mono = time.monotonic()
            if mono - _last_prune.get(path, -_PRUNE_EVERY_S - 1) >= _PRUNE_EVERY_S:
                _last_prune[path] = mono
                prune(conn)
        return len(rows), (time.monotonic() - t0) * 1000.0
    except Exception:  # noqa: BLE001 — never raise into the sweep; next sweep retries
        _warn_once("write", "venue_protection_snapshot: write failed "
                            "(contained; trading unaffected; retried next sweep)")
        return 0, (time.monotonic() - t0) * 1000.0


@contextmanager
def batch(db_path: Optional[str] = None):
    """Collect every :func:`record_read` of this thread inside the block and write them in one transaction at exit.

    Nests (only the outermost writes). Never raises into the caller. Logs ONE line per batch with the number of reads
    queued, rows written and the connect+commit time, so the lock time of this writer is MEASURED, not inferred.
    """
    if getattr(_batch_state, "b", None) is not None:
        yield
        return
    b = _Batch()
    _batch_state.b = b
    try:
        yield
    finally:
        _batch_state.b = None
        try:
            if b.ro is not None:
                b.ro.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if b.rows:
                from src.utils.paths import trade_journal_db_path
                path = db_path or b.path or str(trade_journal_db_path())
                # Last read of a (package, account) wins, as it did when each read upserted in turn.
                latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
                for r in b.rows:
                    latest[(r["order_package_id"], r["account_id"])] = r
                n, ms = _flush(list(latest.values()), path)
                logger.info("venue_protection_snapshot: sweep batch queued=%d written=%d connect+commit=%.1f ms "
                            "(thread=%s)", len(b.rows), n, ms, threading.current_thread().name)
        except Exception:  # noqa: BLE001
            _warn_once("batch", "venue_protection_snapshot: batch flush failed")


def _record_read_batched(b: _Batch, *, account_id: Any, trade_id: Any, symbol: Any, direction: Any, venue: Any,
                         stop_prices: Any, target_prices: Any, position_size: Any, unreadable: Optional[str],
                         order_package_id: Any, db_path: Optional[str], now: Optional[datetime]) -> bool:
    from src.utils.paths import trade_journal_db_path
    path = db_path or str(trade_journal_db_path())
    if b.path is None:
        b.path = path
    if b.ro is None:
        b.ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    pkg, sl, tp = _package_for_trade(b.ro, trade_id)
    row = build_snapshot_row(
        order_package_id=order_package_id or pkg, account_id=account_id,
        symbol=symbol, direction=direction, trade_id=trade_id, venue=venue,
        stop_prices=stop_prices, target_prices=target_prices,
        position_size=position_size, ref_sl=sl, ref_tp=tp,
        unreadable=unreadable, now=now)
    if row is None:
        return False
    b.rows.append(row)
    return True


def record_read(*, account_id: Any, trade_id: Any, symbol: Any = None, direction: Any = None,
                venue: Any = None, stop_prices: Optional[Iterable[Any]] = None,
                target_prices: Optional[Iterable[Any]] = None, position_size: Any = None,
                unreadable: Optional[str] = None, order_package_id: Any = None,
                db_path: Optional[str] = None, now: Optional[datetime] = None) -> bool:
    """Persist one venue read for the package behind *trade_id*. Never raises.

    Timed into the tick's hook split. Returns whether a row landed; ``False`` is
    also the answer when the trade has no package (nothing to key the row on).
    """
    try:
        from src.runtime import tick_cost
        ctx = tick_cost.hook(HOOK_NAME)
    except Exception:  # noqa: BLE001 — measurement must never gate the write
        from contextlib import nullcontext
        ctx = nullcontext()
    try:
        with ctx:
            b = getattr(_batch_state, "b", None)
            if b is not None:
                return _record_read_batched(
                    b, account_id=account_id, trade_id=trade_id, symbol=symbol, direction=direction, venue=venue,
                    stop_prices=stop_prices, target_prices=target_prices, position_size=position_size,
                    unreadable=unreadable, order_package_id=order_package_id, db_path=db_path, now=now)
            from src.utils.paths import trade_journal_db_path
            path = db_path or str(trade_journal_db_path())
            with sqlite3.connect(path, timeout=_write_busy_timeout(5.0)) as conn:
                pkg, sl, tp = _package_for_trade(conn, trade_id)
                row = build_snapshot_row(
                    order_package_id=order_package_id or pkg, account_id=account_id,
                    symbol=symbol, direction=direction, trade_id=trade_id, venue=venue,
                    stop_prices=stop_prices, target_prices=target_prices,
                    position_size=position_size, ref_sl=sl, ref_tp=tp,
                    unreadable=unreadable, now=now)
                if row is None:
                    return False
                conn.execute(_UPSERT, row)
                mono = time.monotonic()
                if mono - _last_prune.get(path, -_PRUNE_EVERY_S - 1) >= _PRUNE_EVERY_S:
                    _last_prune[path] = mono
                    prune(conn)
            return True
    except Exception:  # noqa: BLE001 — never raise into the exit loop; next sweep retries
        _warn_once("write", "venue_protection_snapshot: write failed "
                            "(contained; trading unaffected; retried next sweep)")
        return False


def read_snapshots(db_path: Optional[str] = None, *, order_package_id: Optional[str] = None,
                   account_id: Optional[str] = None, limit: int = 2000) -> Dict[str, Any]:
    """Snapshot rows as an envelope. ``present: false`` = table absent, not "no rows"."""
    env: Dict[str, Any] = {"present": False, "count": 0, "rows": [], "error": None,
                           "read_states": list(READ_STATES), "retention_days": RETENTION_DAYS}
    try:
        from src.utils.paths import trade_journal_db_path
        path = db_path or str(trade_journal_db_path())
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                  (TABLE,)).fetchone()
            if not exists:
                return env
            where, params = [], []
            for col, val in (("order_package_id", order_package_id), ("account_id", account_id)):
                if val:
                    where.append(f"{col} = ?")
                    params.append(str(val))
            sql = f"SELECT * FROM {TABLE}" + (" WHERE " + " AND ".join(where) if where else "")
            sql += " ORDER BY read_at DESC LIMIT ?"
            params.append(max(1, min(int(limit), 10000)))
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        env["error"] = str(exc)
        return env
    env.update({"present": True, "count": len(rows), "rows": rows})
    return env


def _write_busy_timeout(default: float) -> float:
    """5 s everywhere, but the short bound on the exit-evaluation thread
    (src/runtime/journal_sync.py; TICK-STAGE2-RECONCILE-OFFTICK): a best-effort
    telemetry write must not hold an exit pass past the 60 s requirement."""
    try:
        from src.runtime.journal_sync import write_busy_timeout
        return write_busy_timeout(default)
    except Exception:  # noqa: BLE001
        return default
