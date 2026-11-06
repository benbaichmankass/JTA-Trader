"""Mover attribution for ``order_packages.sl`` (LTR-MECH-PROP-MIRROR-BRACKET, 2026-11-06).

MEASURED 2026-11-06 (bybit_1, ADAUSDT pkg-78342b614f6040f6 and SOLUSDT pkg-81365629b21a4fc1):
both package stops moved at the 08:00Z bar close (0.18747 -> 0.186646, 92.72 -> 90.87) through
the ``structure_exit`` verdict (``reason: swing_ratchet``) in ``order_monitor._apply_update``.
The mover was in the trader log, but the package row recorded nothing, so a reviewer reading the
journal saw "a stop that moved by an unnamed path". Every package SL write now stamps its source
here, on ``order_packages.meta`` (no new table: the package row is the canonical store).

Pure functions; the caller owns the DB write (``Database.update_order_package``).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

#: Cap on ``meta.sl_moves`` so a trailing package cannot grow its meta without bound.
MAX_SL_MOVES = 20

SRC_STRUCTURE = "structure_exit"
SRC_STRATEGY = "strategy_monitor"
SRC_LIVE_REVIEW = "live_review_apply"


def mover_from_verdict(verdict: Any, strategy: Optional[str] = None) -> Dict[str, Any]:
    """``{"source", "detail"}`` naming what proposed a monitor verdict's stop.

    A verdict carrying ``structure_move`` came from the structure exit (its ``reason`` and level are
    the detail); any other stop verdict came from the strategy's own monitor (trail / stale / giveback
    -- its ``reason`` when it gives one, else the strategy name). Never empty.
    """
    v = verdict if isinstance(verdict, dict) else {}
    sm = v.get("structure_move")
    if isinstance(sm, dict):
        bits = [str(sm.get("reason") or "structure_move")]
        if sm.get("level_type"):
            bits.append(str(sm["level_type"]))
        if sm.get("level_price") is not None:
            bits.append(str(sm["level_price"]))
        return {"source": SRC_STRUCTURE, "detail": ":".join(bits)}
    return {"source": SRC_STRATEGY, "detail": str(v.get("reason") or v.get("sl_reason") or strategy or "unspecified")}


def _meta_dict(meta: Any) -> Dict[str, Any]:
    if isinstance(meta, dict):
        return dict(meta)
    if isinstance(meta, str) and meta.strip():
        try:
            m = json.loads(meta)
            return dict(m) if isinstance(m, dict) else {}
        except (ValueError, TypeError):
            return {}  # allow-silent: an unreadable meta is rebuilt with only the move record
    return {}


def stamp_sl_move(meta: Any, old_sl: Any, new_sl: Any, source: str, detail: str = "",
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """The package ``meta`` with this stop move recorded (``last_sl_move`` + capped ``sl_moves``).

    ``last_sl_move.ts`` is also what the venue-divergence detector uses to know the package stop moved
    after a venue read, so it is written at the same moment as the ``sl`` it describes.
    """
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    out = _meta_dict(meta)
    rec = {"ts": ts, "from": old_sl, "to": new_sl, "source": source, "detail": detail}
    moves = [m for m in (out.get("sl_moves") or []) if isinstance(m, dict)]
    moves.append(rec)
    out["sl_moves"] = moves[-MAX_SL_MOVES:]
    out["last_sl_move"] = rec
    return out


def last_sl_move_ts(meta: Any) -> Optional[datetime]:
    """UTC time of the newest recorded stop move, or ``None`` (no record: not "never moved")."""
    rec = _meta_dict(meta).get("last_sl_move")
    if not isinstance(rec, dict):
        return None
    try:
        t = datetime.fromisoformat(str(rec.get("ts")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
