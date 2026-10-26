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
import time
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
            from src.utils.paths import trade_journal_db_path
            path = db_path or str(trade_journal_db_path())
            with sqlite3.connect(path, timeout=5.0) as conn:
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
