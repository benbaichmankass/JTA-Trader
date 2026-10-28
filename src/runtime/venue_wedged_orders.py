"""Declared venue-wedged orders, applied to the Alpaca "what rests NOW" read.

See config/venue_wedged_orders.yaml for the contract. The rule in one line: a listed order leaves the
`orders` list only when its symbol is CONFIRMED flat; it moves to a visible `excluded` list, never vanishes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "venue_wedged_orders.yaml"


def _declared(account_id: str, path: Optional[Path] = None) -> Dict[str, str]:
    """{order_id: symbol} declared for *account_id*. A missing or unreadable file declares nothing."""
    try:
        doc = yaml.safe_load((path or _CONFIG).read_text()) or {}
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged; declaring nothing leaves every order flagged (the safe side)
        logger.warning("venue_wedged_orders: config unreadable (%s); excluding nothing", exc)
        return {}
    out: Dict[str, str] = {}
    for e in (doc.get("venue_wedged_orders") or {}).get(account_id) or []:
        if isinstance(e, dict) and e.get("order_id") and e.get("symbol"):
            out[str(e["order_id"]).lower()] = str(e["symbol"]).upper()
    return out


def partition(
    account_id: str,
    orders: List[Dict[str, Any]],
    positions: Optional[List[Dict[str, Any]]],
    path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split *orders* into (kept, excluded). Excludes only declared orders on a CONFIRMED-flat symbol.

    ``positions is None`` is "could not look", never "flat": nothing is excluded.
    """
    declared = _declared(account_id, path)
    if not declared or positions is None:
        return list(orders), []
    held = {
        str(p.get("symbol") or "").upper()
        for p in positions
        if isinstance(p, dict) and (p.get("qty") is None or float(p.get("qty") or 0) != 0.0)
    }
    kept: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for o in orders:
        oid = str(o.get("order_id") or "").lower()
        sym = declared.get(oid)
        if sym is not None and sym == str(o.get("symbol") or "").upper() and sym not in held:
            excluded.append(o)
        else:
            kept.append(o)
    return kept, excluded
