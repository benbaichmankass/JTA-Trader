"""Store for the closed-trade chart snapshot (UI-REDESIGN-2026-11 addendum 3): table ``trade_chart_snapshots``.

One row per closed ``trades.id``. The payload is the framed DATA (``src.web.api.trade_chart_snapshot.build_snapshot``),
not an image. The table lives in ``trade_journal.db`` next to the trade it describes; it is derived data (it can
always be rebuilt from the journal + candles), so a lost row is a rebuild, never lost truth.

``state``: ``built`` (payload present) · ``retrying`` (a build failed; ``attempts``/``last_error``/``next_attempt_at``
say when it runs again) · ``gave_up`` is never used -- a failing trade keeps retrying at the max backoff (Prime
Directive rule 7: no halting; the builder flags a trade that keeps failing).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

TABLE = "trade_chart_snapshots"
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    trade_id INTEGER PRIMARY KEY,
    order_package_id TEXT,
    account_id TEXT,
    schema TEXT,
    state TEXT NOT NULL,
    read_state TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TEXT,
    built_at TEXT,
    payload TEXT
)
"""


def read(conn: sqlite3.Connection, trade_id: int) -> Dict[str, Any]:
    """``{"state": "absent"|"built"|"retrying"|"no_table", "payload": dict|None, ...}``. Never raises on a missing table."""
    try:
        row = conn.execute(f"SELECT state, read_state, attempts, last_error, built_at, payload FROM {TABLE} "
                           "WHERE trade_id = ?", (int(trade_id),)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {"state": "no_table", "payload": None}
        raise
    if row is None:
        return {"state": "absent", "payload": None}
    payload: Optional[Dict[str, Any]] = None
    if row[5]:
        try:
            p = json.loads(row[5])
            payload = p if isinstance(p, dict) else None
        except ValueError:
            payload = None
    return {"state": row[0], "read_state": row[1], "attempts": row[2], "last_error": row[3], "built_at": row[4],
            "payload": payload}
