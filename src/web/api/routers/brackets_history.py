"""Tier-1 read endpoint: bracket (SL/TP) history for the chart overlay (UI-CHART-BRACKET-HISTORY).

``GET /api/bot/brackets/history?order_package_id=<id>`` (exchange accounts) or ``?prop_fill_id=<id>`` (prop; the
opening or closing fill row) ``&interval=1h`` -> levels (main + earlier) and one marker per update.
Builders and the honesty rules (no TP history for exchange packages, null is not []) live in
``src.web.api.brackets_history``. GET only (CORS allows GET/POST); unknown interval / bad selector -> HTTP 400.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from src.utils.paths import trade_journal_db_path
from src.web.api import brackets_history as bh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

_DB_PATH = Path(trade_journal_db_path())


def _package_row(order_package_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM order_packages WHERE order_package_id = ?", (order_package_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


@router.get("/brackets/history")
def get_brackets_history(order_package_id: Optional[str] = None, prop_fill_id: Optional[int] = None,
                         interval: str = "1h") -> Dict[str, Any]:
    if interval not in bh._INTERVAL_S:
        raise HTTPException(status_code=400, detail=f"unknown interval {interval!r}; one of {sorted(bh._INTERVAL_S)}")
    if bool(order_package_id) == (prop_fill_id is not None):
        raise HTTPException(status_code=400, detail="give exactly one of order_package_id, prop_fill_id")
    as_of = datetime.now(timezone.utc).isoformat()
    try:
        if order_package_id:
            pkg = _package_row(order_package_id)
            if pkg is None:
                raise HTTPException(status_code=404, detail="no such order package")
            out = bh.build_package_history(pkg, interval)
        else:
            from src.prop import prop_journal
            row = prop_journal.get_fill(prop_fill_id)
            if row is None:
                raise HTTPException(status_code=404, detail="no such prop fill")
            if str(row.get("status", "")).lower() == "closed":   # a closing row: the levels live on its opener
                row = prop_journal.get_opening_fill(row.get("account_id"), row.get("ticket_id"),
                                                    row.get("external_order_id")) or row
            out = bh.build_prop_history(row, interval)
    except HTTPException:
        raise
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state no_record + journal_unreadable, never an empty line that reads as 'no moves'
        logger.warning("brackets history: read failed", exc_info=True)
        return {"as_of": as_of, "read_state": "no_record", "partial_reasons": ["journal_unreadable"],
                "levels": [], "updates": []}
    return {"as_of": as_of, "interval": interval, **out}
