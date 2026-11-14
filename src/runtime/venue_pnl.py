"""The venue's net closed P&L is ``trades.pnl`` (operator decision w11, 2026-11-12).

DECISION
--------
Operator, decisions page w11 (2026-11-12, recorded on PNL-GROSS-VS-VENUE-6817): "Yes:
store the venue's net closed P&L where trusted", with the binding note "Store the
venue's always, it is the single source of truth and if we have a gap we need to
understand why".

WHAT IT REPLACES (MEASURED 2026-11-12, docs/research/pnl-gross-vs-venue-6817-2026-11-12.md)
---------------------------------------------------------------------------------------
Over 157 closed Bybit rows, ``pnl`` meant two different things. On bybit_2 (real money) it
was the venue's NET closed P&L (23 of 24 rows). On the demo books it was our GROSS local
compute, with costs held separately in the fee columns. ``net_r_label`` treated every
``pnl`` as gross and subtracted costs, so the real-money ml_entry net R was costed twice
(mean 0.2193 vs 0.2994 over 15 closes).

THE RULE
--------
* ``pnl`` = the venue's own realised-P&L record wherever the venue serves one
  (``pnl_basis='venue_net'``): Bybit's closed-pnl record, demo books included (the
  2026-06-08 "demo closed-pnl is untrusted" stance is superseded by the decision; every
  demo gap is recorded instead), and IBKR's per-execution realised P&L.
* A venue with NO per-trade P&L record (Alpaca equities) keeps the figure computed from
  its own fills, net of their fees (``pnl_basis='venue_fills_net'``), and only when the
  exit really is a venue fill. An estimated exit is left unclassified (NULL basis).
* ``pnl_computed`` = our independent figure: gross from the journal's entry and exit times
  qty, minus the row's own cost columns. ``pnl_gap_usd = pnl - pnl_computed``.
* A gap above :func:`gap_tolerance_usd` is a diagnosis item. It is recorded on the row and
  listed by ``scripts/ops/venue_pnl_gaps.py``; it is never reconciled away.
* A Bybit row whose venue record cannot be matched within the venue's retention gets
  ``pnl_basis='venue_unmatched'``, which is itself a diagnosis item. ``pnl`` stays as it
  was and nothing is invented.

Pure helpers here; the monitor sweep (``order_monitor._sweep_venue_net_pnl``) applies them.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

__all__ = [
    "BASIS_VENUE_NET",
    "BASIS_VENUE_FILLS_NET",
    "BASIS_VENUE_UNMATCHED",
    "BASIS_COMPUTED_ESTIMATE",
    "NET_BASES",
    "GAP_TOLERANCE_ABS_USD",
    "GAP_TOLERANCE_REL",
    "gap_tolerance_usd",
    "computed_net",
    "match_venue_record",
    "is_gap",
]

BASIS_VENUE_NET = "venue_net"
BASIS_VENUE_FILLS_NET = "venue_fills_net"
BASIS_VENUE_UNMATCHED = "venue_unmatched"
#: The exit is not a venue fill (a close-time candle or a projected level), so ``pnl``
#: is our gross estimate and no venue figure exists to store. Terminal, so the row is
#: not rescanned; not in NET_BASES, so net-R readers still subtract its costs.
BASIS_COMPUTED_ESTIMATE = "computed_estimate"
#: Bases under which ``pnl`` is already NET of the trade's costs.
NET_BASES = frozenset({BASIS_VENUE_NET, BASIS_VENUE_FILLS_NET})

#: Stated tolerance for a venue-vs-computed gap. Larger of 0.25 USD and 1% of the
#: venue figure: the 1% covers fee-estimate noise (journal fee columns agreed with the
#: venue-implied fees to within 1-2% per account, MEASURED 2026-11-12). Changing it is a
#: decision, so it lives here as a named constant, never inline.
GAP_TOLERANCE_ABS_USD = 0.25
GAP_TOLERANCE_REL = 0.01

#: Close-time window for a qty + time match when no order id matches (15 min, the
#: window the 2026-11-12 measurement matched 151 of 157 rows with).
_TIME_MATCH_MS = 15 * 60 * 1000


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def gap_tolerance_usd(venue_pnl: Any) -> float:
    v = abs(_f(venue_pnl) or 0.0)
    return max(GAP_TOLERANCE_ABS_USD, GAP_TOLERANCE_REL * v)


def is_gap(venue_pnl: Any, computed: Any) -> bool:
    v, c = _f(venue_pnl), _f(computed)
    if v is None or c is None:
        return False
    return abs(v - c) > gap_tolerance_usd(v)


def computed_net(row: Dict[str, Any]) -> Optional[float]:
    """Our own figure: (exit - entry) x qty x direction x contract value, minus the row's
    fee and funding columns. ``None`` when entry, exit or qty is missing."""
    from src.runtime.local_pnl import compute_realized_pnl, contract_value_usd_for

    gross = compute_realized_pnl(
        entry_price=_f(row.get("entry_price")), exit_price=_f(row.get("exit_price")),
        qty=_f(row.get("position_size")), direction=row.get("direction"),
        contract_value_usd=contract_value_usd_for(row.get("symbol")),
    )
    if gross is None:
        return None
    costs = sum((_f(row.get(k)) or 0.0) for k in ("fee_taker_usd", "fee_maker_usd", "funding_paid_usd"))
    return round(gross - costs, 8)


def match_venue_record(
    records: Iterable[Dict[str, Any]], *, own_order_ids: Sequence[Any], qty: Any,
    closed_at_ms: Optional[int], close_side: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Pick THIS row's venue closed-pnl record. Returns ``(record, how)``.

    1. A record whose ``order_id`` is one of the row's own close orders (its sl/tp leg,
       or a partial-close child's close order): ``how='order_id'``.
    2. Otherwise exactly ONE record with the same qty (1e-6 relative), the row's closing
       side, and an ``updated_time`` within 15 min of the close: ``how='qty_time'``.
    3. Two or more candidates -> ``(None, 'ambiguous')``; none -> ``(None, 'none')``.
    """
    recs = [r for r in records if isinstance(r, dict)]
    own = {str(o) for o in own_order_ids if o}
    for r in recs:
        if own and str(r.get("order_id") or "") in own:
            return r, "order_id"
    q = _f(qty)
    if not q or closed_at_ms is None:
        return None, "none"
    hits = []
    for r in recs:
        rq = _f(r.get("qty"))
        t = _f(r.get("updated_time") or r.get("created_time"))
        if rq is None or t is None or abs(rq - q) > max(1e-9, 1e-6 * q):
            continue
        if close_side and str(r.get("side") or "").lower() not in ("", close_side.lower()):
            continue
        if abs(int(t) - int(closed_at_ms)) <= _TIME_MATCH_MS:
            hits.append(r)
    if len(hits) == 1:
        return hits[0], "qty_time"
    return None, ("ambiguous" if hits else "none")
