"""The venue Positions read, in the shape every ``account_status`` consumer reads.

AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE (2026-11-04). The phone executor
(``src/prop/phone_executor.py``) posts ``positions_state`` + ``positions`` in its
``account_status``; the two DXtrade writers (``prop_executor`` every cycle, and
the ``ict-prop-feed`` tick via ``scripts/prop/breakout_login_check.py``) read the
terminal's Positions every time but never posted them in that shape, so
``GET /api/bot/prop/status`` carried no positions for tradeify_1 / velotrade_1
and ``INV-PROP-POSITIONS`` / the live-review packet could only say
"could not look".

This module turns ``Position`` rows (venue symbol, quantity in LOTS) into the
consumer shape (bot symbol, ``direction``, ``qty`` in UNITS, the journal's
unit). Read-only: it formats what was already read and touches no order path.

States (``positions_state``), never collapsed into "flat":
  * ``read``         -- a clean read; ``positions`` is the list ([] = flat).
  * ``not_read``     -- the terminal read raised / was not attempted.
  * ``side_unread``  -- a row came back without a long/short side.
  * ``qty_unread``   -- a row's quantity, or its venue's ``lot_units`` (an unmapped
                        instrument has none), is unknown, so its size in units cannot be stated.
Only ``read`` carries a ``positions`` key, so no reader ever reconciles a
half-read list.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Sequence

SOURCE = "venue_terminal"


def _get(p: Any, name: str) -> Any:
    return p.get(name) if isinstance(p, Mapping) else getattr(p, name, None)


def _num(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _norm(s: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def lot_units_by_venue(symbols: Optional[Mapping[str, Mapping[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """``ExecutorConfig.symbols`` (bot -> {venue, lot_units, ...}) -> venue -> {bot, lot_units}."""
    out: Dict[str, Dict[str, Any]] = {}
    for bot, blk in (symbols or {}).items():
        venue = _norm((blk or {}).get("venue"))
        if venue:
            out[venue] = {"bot": str(bot).upper(), "lot_units": _num((blk or {}).get("lot_units"))}
    return out


def positions_fields(positions: Optional[Sequence[Any]],
                     symbols: Optional[Mapping[str, Mapping[str, Any]]]) -> Dict[str, Any]:
    """-> the keys to merge into an ``account_status`` body.

    ``positions`` is three-state: ``None`` (did not look), ``[]`` (clean flat
    read), or the rows. ``symbols`` is ``ExecutorConfig.symbols``; ``None``
    means the routing could not be loaded, so a non-empty read cannot be sized
    (``qty_unread``)."""
    if positions is None:
        return {"positions_state": "not_read"}
    by_venue = lot_units_by_venue(symbols)
    rows = []
    state = "read"
    for p in positions:
        venue = str(_get(p, "symbol") or "").upper()
        side = str(_get(p, "side") or "").lower()
        side = {"buy": "long", "sell": "short"}.get(side, side)
        if side not in ("long", "short"):
            state = state if state != "read" else "side_unread"
            continue
        m = by_venue.get(_norm(venue))
        lots, lu = _num(_get(p, "quantity")), (m or {}).get("lot_units")
        if lots is None or lots <= 0 or not lu:
            state = state if state != "read" else "qty_unread"
            continue
        # (an instrument the routing does not map has no lot_units, so it lands in qty_unread above: visible, never sized by a guess)
        rows.append({"symbol": m["bot"], "venue_symbol": venue, "direction": side,
                     "qty": round(lots * float(lu), 10), "lots": lots,
                     "entry": _num(_get(p, "entry_price")), "sl": _num(_get(p, "stop_loss")),
                     "tp": _num(_get(p, "take_profit")), "upnl": _num(_get(p, "unrealized_pnl"))})
    if state != "read":
        return {"positions_state": state, "positions_source": SOURCE}
    return {"positions_state": "read", "positions": rows, "positions_count": len(rows),
            "positions_source": SOURCE, "positions_provenance": "MEASURED"}


def account_symbols(account_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """``load_config(account_id).symbols`` or None when the routing cannot be loaded."""
    try:
        from src.prop.prop_executor import load_config
        return load_config(account_id).symbols
    except Exception:
        return None
