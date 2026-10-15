"""Slice ledger — an (account, symbol) position as a sum of per-strategy slices.

Checklist row NETTED-SLICES (operator, 2026-10-15: *"as long as we know how
much of that position belongs to each strategy, and each piece of that
position has its own brackets"*).

THE LEDGER IS THE TRADE JOURNAL. A slice is one open, non-backtest
``trades`` row: ``strategy_name``, ``direction``, ``position_size`` (the slice
qty), ``entry_price``, ``stop_loss``, ``take_profit_1`` and the venue leg ids
``sl_order_id`` / ``tp_order_id`` that carry the slice's own Partial bracket
(captured at entry since 2026-07-21). No new table: a second store would be a
second truth to reconcile (new-table-wiring rule).

INVARIANT: the venue's net position on (account, symbol) equals the signed sum
of the open slices. :func:`reconcile` checks it against a venue read and
returns one of three states, never collapsed:

  ``reconciled``  both read, equal within tolerance.
  ``divergent``   both read, NOT equal — the ledger does not describe the venue.
  ``unreadable``  we could not read one side. Not "flat", not "equal".

The coordinator refuses ADDING a slice to a book that is not ``reconciled``
(per-trade refusal, logged + journalled; the next tick re-reads). Nothing here
closes, halts or latches anything — "There is no halting" (operator,
2026-10-09). Repairing a divergent book is the job of the existing netting
reconciler in ``order_monitor`` (leg-gone attribution, then FIFO residual).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

RECONCILED = "reconciled"
DIVERGENT = "divergent"
UNREADABLE = "unreadable"

#: Relative tolerance for ledger-vs-venue equality. Journal rows record the
#: legalised qty actually sent (``_submit_order`` writes it back), so the two
#: should agree exactly; the tolerance absorbs float repr only.
REL_TOL = 0.005
ABS_TOL = 1e-9


def _journal_path() -> str:
    from src.utils.paths import trade_journal_db_path
    return trade_journal_db_path()


def open_slices(
    account_id: str, symbol: str, *, db_path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Every open slice on (account, symbol), oldest first. ``None`` = could not look."""
    path = db_path or _journal_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            # SELECT * so a journal predating the sl_order_id/tp_order_id
            # migration still reads (those keys are then simply absent).
            rows = conn.execute(
                "SELECT * FROM trades "
                " WHERE account_id = ? AND symbol = ? AND status = 'open' "
                "   AND COALESCE(is_backtest, 0) = 0 "
                " ORDER BY id ASC",
                (account_id, symbol),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("slice_ledger: read failed for %s/%s: %s", account_id, symbol, exc)
        return None
    keep = ("id", "strategy_name", "direction", "position_size", "entry_price",
            "stop_loss", "take_profit_1", "sl_order_id", "tp_order_id")
    return [{k: dict(r).get(k) for k in keep} for r in rows]


def _signed(row: Mapping[str, Any]) -> float:
    try:
        q = abs(float(row.get("position_size") or 0.0))
    except (TypeError, ValueError):
        return 0.0
    d = str(row.get("direction") or "").lower()
    return q if d == "long" else -q if d == "short" else 0.0


def ledger_net(slices: Iterable[Mapping[str, Any]]) -> float:
    """Signed sum of the slices (long +, short −)."""
    return sum(_signed(r) for r in slices)


def strategy_signed_qty(slices: Iterable[Mapping[str, Any]], strategy: Optional[str]) -> float:
    """This strategy's OWN signed qty on the book — the delta basis on a slice account."""
    return sum(_signed(r) for r in slices if r.get("strategy_name") == strategy)


def venue_net(positions: Optional[Iterable[Mapping[str, Any]]], symbol: str) -> Optional[float]:
    """Signed venue net for *symbol* from an ``account_open_positions`` list.

    ``None`` in → ``None`` out (could not read). Both hedge books, if present,
    are summed — that is the economic net.
    """
    if positions is None:
        return None
    net = 0.0
    want = str(symbol).upper()
    for p in positions:
        if str(p.get("symbol") or "").upper() != want:
            continue
        try:
            size = abs(float(p.get("size") or 0.0))
        except (TypeError, ValueError):
            return None
        side = str(p.get("side") or "").lower()
        if side in ("buy", "long"):
            net += size
        elif side in ("sell", "short"):
            net -= size
        else:
            # A non-zero row whose side we cannot read makes the net unknown.
            return None
    return net


def reconcile(
    slices: Optional[Iterable[Mapping[str, Any]]],
    positions: Optional[Iterable[Mapping[str, Any]]],
    symbol: str,
) -> Dict[str, Any]:
    """``{state, ledger_net, venue_net, gap}`` — see the module docstring."""
    if slices is None:
        return {"state": UNREADABLE, "side": "journal", "ledger_net": None,
                "venue_net": None, "gap": None}
    rows = list(slices)
    led = ledger_net(rows)
    ven = venue_net(positions, symbol)
    if ven is None:
        return {"state": UNREADABLE, "side": "venue", "ledger_net": led,
                "venue_net": None, "gap": None}
    gap = led - ven
    tol = max(ABS_TOL, REL_TOL * max(abs(led), abs(ven)))
    return {
        "state": RECONCILED if abs(gap) <= tol else DIVERGENT,
        "ledger_net": led, "venue_net": ven, "gap": gap, "n_slices": len(rows),
    }


def held_stop_risk(
    slices: Iterable[Mapping[str, Any]], *, exclude_strategies: Iterable[str] = (),
) -> Optional[float]:
    """Σ qty · loss-side distance to the CURRENT stop, over slices not excluded.

    A stop already on the profit side of entry contributes 0 (trailed past
    break-even). ``None`` when any counted slice has no readable entry or stop:
    an unprotected slice's risk is unmeasured, and an unmeasured risk is never
    read as zero.
    """
    skip = {str(s) for s in exclude_strategies}
    total = 0.0
    for r in slices:
        if str(r.get("strategy_name")) in skip:
            continue
        try:
            q = abs(float(r.get("position_size") or 0.0))
            entry = float(r.get("entry_price"))
            sl = float(r.get("stop_loss"))
        except (TypeError, ValueError):
            return None
        if q <= 0:
            continue
        d = str(r.get("direction") or "").lower()
        if d == "long":
            total += q * max(0.0, entry - sl)
        elif d == "short":
            total += q * max(0.0, sl - entry)
        else:
            return None
    return total


def book_side(slices: Iterable[Mapping[str, Any]]) -> Optional[str]:
    """``long`` / ``short`` / ``None`` (flat or empty) from the ledger net."""
    net = ledger_net(slices)
    if abs(net) <= ABS_TOL:
        return None
    return "long" if net > 0 else "short"


def has_opposite_slices(slices: Iterable[Mapping[str, Any]], side: str) -> bool:
    """True when any open slice runs opposite to *side*."""
    other = "short" if side == "long" else "long"
    return any(str(r.get("direction") or "").lower() == other for r in slices)
