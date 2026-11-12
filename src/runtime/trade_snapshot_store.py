"""Store for the closed-trade chart snapshot (UI-REDESIGN-2026-11 addendum 3): table ``trade_chart_snapshots``.

One row per closed trade, keyed by ``snapshot_key``:
  * ``trade:<trades.id>``            -- exchange / paper accounts (the ``trades`` table);
  * ``prop:<closing prop_fills.id>`` -- prop accounts (``prop_fills``; only a CLOSED trade has a snapshot, and its
    closing row is what the backfill scans for, so it is the key; the payload still reports ``prop_fill_id`` = the
    opening row, which is what the routes take).
The payload is the framed DATA (``src.web.api.trade_chart_snapshot.build_snapshot``), not an image, stored
zlib-compressed (``payload`` BLOB) and WITHOUT the indicator series, which the read route recomputes from the
stored candles (deterministic), so ~2,600 backfilled trades stay small. The table lives in its OWN SQLite file,
``trade_chart_snapshots.db`` (``src.utils.paths.trade_snapshots_db_path``), beside the journal and never inside it:
a snapshot write can never take ``trade_journal.db``'s write lock (manager condition 2026-11-12,
JOURNAL-LOCK-RESIDUAL). Every reader and the builder open the journal READ-ONLY (:func:`journal_ro`). It is
derived data (always rebuildable from the journal + candles).

``state``: ``built`` (payload present) · ``retrying`` (a build failed; ``attempts``/``last_error``/``next_attempt_at``
say when it runs again). There is no give-up state: a failing trade keeps retrying at the longest backoff (Prime
Directive rule 7: no halting); the builder flags one that keeps failing.
"""
from __future__ import annotations

import json
import sqlite3
import zlib
from typing import Any, Dict, Optional, Tuple

TABLE = "trade_chart_snapshots"
# data-wiring: derived enrichment sidecar, NOT a source of truth. The truth stays in trade_journal.db (trades,
# order_packages, prop_fills/prop_tickets) + the review/receipt logs + venue candles; this table only caches a framed
# projection of them per closed trade, in its own file (trade_chart_snapshots.db). History is backfilled by the same
# builder loop (src/runtime/trade_snapshot_builder.py: every closed trade with no row, newest first), and any row can
# be deleted and rebuilt.
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    snapshot_key TEXT PRIMARY KEY,
    trade_id INTEGER,
    prop_fill_id INTEGER,
    order_package_id TEXT,
    account_id TEXT,
    schema TEXT,
    state TEXT NOT NULL,
    read_state TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TEXT,
    built_at TEXT,
    payload BLOB
)
"""


def journal_ro(path: str, timeout: float = 5.0) -> sqlite3.Connection:
    """``trade_journal.db`` opened READ-ONLY (``mode=ro`` URI): no statement on it can ever write."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn


def snapshots_rw(path: str, journal_path: Optional[str] = None, timeout: float = 10.0) -> sqlite3.Connection:
    """The snapshot DB, read-write, table ensured; with ``journal_path`` the journal is ATTACHed READ-ONLY as ``j``,
    so unqualified ``trades`` / ``order_packages`` / ``prop_fills`` resolve to it for joins and every write lands
    in the snapshot file only."""
    conn = sqlite3.connect(f"file:{path}", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(DDL)
    conn.commit()
    if journal_path:
        conn.execute("ATTACH DATABASE ? AS j", (f"file:{journal_path}?mode=ro",))
    return conn


def snapshots_ro(path: str) -> Optional[sqlite3.Connection]:
    """The snapshot DB for a read route, read-only; None while the builder has not created it yet."""
    import os
    if not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)


def read_key(path: str, key: str) -> Dict[str, Any]:
    conn = snapshots_ro(path)
    if conn is None:
        return {"state": "no_table", "payload": None}
    try:
        return read(conn, key)
    finally:
        conn.close()


def trade_key(trade_id: int) -> str:
    return f"trade:{int(trade_id)}"


def prop_key(fill_id: int) -> str:
    return f"prop:{int(fill_id)}"


def read(conn: sqlite3.Connection, key: str) -> Dict[str, Any]:
    """``{"state": "absent"|"built"|"retrying"|"no_table", "payload": dict|None, ...}``. Never raises on a missing table."""
    try:
        row = conn.execute(f"SELECT state, read_state, attempts, last_error, built_at, payload FROM {TABLE} "
                           "WHERE snapshot_key = ?", (key,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {"state": "no_table", "payload": None}
        raise
    if row is None:
        return {"state": "absent", "payload": None}
    row = tuple(row)
    payload: Optional[Dict[str, Any]] = None
    if row[5]:
        try:
            raw = row[5]
            p = json.loads(zlib.decompress(raw).decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
            payload = p if isinstance(p, dict) else None
        except (ValueError, zlib.error):
            payload = None
    return {"state": row[0], "read_state": row[1], "attempts": row[2], "last_error": row[3], "built_at": row[4],
            "payload": payload}


def encode(payload: Dict[str, Any]) -> bytes:
    """The stored form: the payload minus ``indicators`` (recomputed on read), compact JSON, zlib level 6."""
    slim = {k: v for k, v in payload.items() if k != "indicators"}
    return zlib.compress(json.dumps(slim, separators=(",", ":")).encode("utf-8"), 6)


# ───────────────────────────── prop trades: one trade = an opening prop_fills row + (once closed) a closing row

def _one(conn: sqlite3.Connection, sql: str, args: tuple) -> Optional[Dict[str, Any]]:
    cur = conn.execute(sql, args)
    r = cur.fetchone()
    if r is None:
        return None
    return dict(zip([d[0] for d in cur.description], tuple(r)))


def _sibling(conn: sqlite3.Connection, row: Dict[str, Any], want_open: bool) -> Optional[Dict[str, Any]]:
    """The other half of ``row``'s trade: same account and external order id (else ticket id)."""
    # an opener is an open/filled row; a 'placed' row (order sent, fill not journaled) is the fallback
    # (MEASURED 2026-11-12, /api/bot/prop/fills, all 257 rows: of 72 closed rows, 66 have an open/filled
    # sibling, 2 only a placed one, 4 none)
    tiers = ("lower(status) IN ('open','filled')", "lower(status) = 'placed'") if want_open else ("lower(status) = 'closed'",)
    order = "ASC" if want_open else "DESC"
    for status_sql in tiers:
        for col in ("external_order_id", "ticket_id"):
            val = row.get(col)
            if not val:
                continue
            got = _one(conn, f"SELECT * FROM prop_fills WHERE account_id = ? AND {col} = ? AND {status_sql} "
                             f"AND id != ? ORDER BY id {order} LIMIT 1", (row.get("account_id"), str(val), row.get("id")))
            if got is not None:
                return got
    return None


def resolve_prop(conn: sqlite3.Connection, fill_id: int) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]],
                                                                          Optional[Dict[str, Any]]]]:
    """``(opener, closer|None, ticket|None)`` for the prop trade ``fill_id`` (an opening OR closing row) belongs to.

    ``opener`` is the opening row, or the closing row itself when no opening row was journaled. None = no such
    row (or no prop tables)."""
    try:
        row = _one(conn, "SELECT * FROM prop_fills WHERE id = ?", (int(fill_id),))
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    if row is None:
        return None
    if str(row.get("status") or "").lower() in ("open", "filled", "placed"):
        opener, closer = row, _sibling(conn, row, want_open=False)
    else:
        closer = row
        opener = _sibling(conn, row, want_open=True) or row
    ticket = None
    if opener.get("ticket_id"):
        try:
            ticket = _one(conn, "SELECT * FROM prop_tickets WHERE ticket_id = ?", (str(opener["ticket_id"]),))
        except sqlite3.OperationalError:
            ticket = None
    return opener, closer, ticket


FLAG_AFTER_ATTEMPTS = 5  # == trade_snapshot_builder.FLAG_AFTER (asserted in tests)


def status_counts(path: str) -> Dict[str, Any]:
    """Backfill progress from the snapshot DB, read-only: built / built_partial / retrying (+ attempts), the newest
    build time and the latest error. ``state`` = read | no_table (the builder has not created the file yet) |
    could_not_look (the read failed). Counts are None (never 0) unless state is read."""
    out: Dict[str, Any] = {"state": "no_table", "built": None, "built_partial": None, "built_trade": None,
                           "built_prop": None, "retrying": None, "failing_flagged": None, "max_attempts": None,
                           "last_built_at": None, "last_error": None, "last_error_key": None}
    conn = snapshots_ro(path)
    if conn is None:
        return out
    try:
        r = conn.execute(
            f"SELECT SUM(state='built'), SUM(state='built' AND read_state='partial'), "
            f"SUM(state='built' AND snapshot_key LIKE 'trade:%'), SUM(state='built' AND snapshot_key LIKE 'prop:%'), "
            f"SUM(state='retrying'), SUM(state='retrying' AND attempts>=?), MAX(CASE WHEN state='retrying' "
            f"THEN attempts END), MAX(built_at) FROM {TABLE}", (FLAG_AFTER_ATTEMPTS,)).fetchone()
        e = conn.execute(f"SELECT snapshot_key, last_error FROM {TABLE} WHERE state='retrying' AND last_error IS NOT NULL "
                         "ORDER BY next_attempt_at DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return out
        return dict(out, state="could_not_look", error=str(exc)[:200])
    except sqlite3.Error as exc:
        return dict(out, state="could_not_look", error=str(exc)[:200])
    finally:
        conn.close()
    n = [int(x or 0) for x in r[:6]]
    out.update(state="read", built=n[0], built_partial=n[1], built_trade=n[2], built_prop=n[3], retrying=n[4],
               failing_flagged=n[5], max_attempts=r[6], last_built_at=r[7],
               last_error=(e[1] if e else None), last_error_key=(e[0] if e else None))
    return out
