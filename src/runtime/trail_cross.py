"""Trail-crossed close -- the chandelier candidate is THROUGH the price (TRAIL-RATCHET-AUDIT, Tier 3).

When a strategy's own trail candidate sits at or beyond the current price (long: ``candidate >= price``; short:
``candidate <= price``) the Stage-0 harness has already exited: ``trail = max(trail, ext - mult*atr)`` is updated on the
bar's close and the NEXT bar's ``_stop_or_target`` fills at ``min(trail, open)`` (long) / ``max(trail, open)`` (short).
Live used to IGNORE that candidate (``candidate < current_price`` was a guard on the amend) and keep the looser stop.
Operator, 2026-10-29: moving the stop past price "means that we should close it".

This returns the monitor close verdict; the order monitor sends it through the ordinary close path. Pure, never raises.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

CLOSE_REASON = "strategy_close"


def trail_cross_verdict(direction: str, candidate: float, sl: float, price: float) -> Optional[Dict[str, Any]]:
    """The close verdict when ``candidate`` TIGHTENS ``sl`` and is through ``price``; else None."""
    try:
        if direction == "long" and candidate > sl and candidate >= price:
            return {"action": "close", "reason": CLOSE_REASON, "exit_price": price}
        if direction == "short" and candidate < sl and candidate <= price:
            return {"action": "close", "reason": CLOSE_REASON, "exit_price": price}
    except TypeError:
        return None
    return None
