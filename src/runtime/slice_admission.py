"""May this strategy add a slice to this (account, symbol) — and how big?

Checklist row NETTED-SLICES. Called by ``Coordinator.multi_account_execute``
for an intent-mode package on an account declaring ``position_model: slices``,
AFTER the RiskManager has sized the trade and BEFORE the execution delta is
computed. Every refusal is per trade: it is journalled with its reason, the
account stays live, and the next tick asks again ("There is no halting",
operator 2026-10-09). Nothing here closes, cancels or latches anything.

Order of checks, each with the reason token it journals:

1. ``slice_ledger_unreadable`` — the journal could not be read.
2. The strategy's OWN signed qty becomes the delta basis. If it already holds a
   slice, admission returns ``ok`` unchanged: the existing same-strategy guard
   (``reentry_suppressed_netting_guard``) and the coordinator's
   ``slice_hold_to_bracket`` rule handle it. A strategy never double-enters.
3. ``opposite_slice_one_way_book`` — the book holds a slice on the OTHER side
   and the symbol is a ONE-WAY book. Bybit sizes position TP/SL to the open
   position ("adjust the qty according to the size of the open position",
   v5 /position/trading-stop), so an opposite slice would shrink the net below
   the same-side slices' legs and a firing leg would close LESS than its slice:
   the ledger would stop describing the venue. The same mechanism stranded
   8 of 8 SOL/ETH pairs legs (``src/runtime/bybit_position_mode.py``, T.2).
   On a HEDGE book (``bybit_position_mode.hedge_mode_enabled``) the opposite
   slice opens in its own book with its own Partial legs and is admitted.
4. ``slice_requires_partial_tpsl`` — the book is not flat and the venue is
   Bybit but ``BYBIT_TPSL_MODE`` is not ``partial``: under Full mode a second
   slice's bracket would REPLACE the first's.
5. ``slice_ledger_divergent`` / ``slice_ledger_venue_unreadable`` — the signed
   sum of open slices does not match the venue's net (or the venue could not be
   read). Skipped on a dry account (no venue to read; the journal is the book).
6. ``slice_risk_unmeasurable`` — a non-contending slice has no readable stop.
7. ``slice_budget_exhausted`` — the symbol's risk budget is used up by other
   strategies' open slices at their current stops.

Otherwise ``qty = slice_allocation.slice_qty(...)`` — never above the
RiskManager's size.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from src.runtime import slice_allocation as _sa
from src.runtime import slice_ledger as _sl

logger = logging.getLogger(__name__)


def _default_positions_reader(account_cfg: Mapping[str, Any]):
    from src.units.accounts.clients import account_open_positions
    return account_open_positions(dict(account_cfg))


def _default_tpsl_mode() -> str:
    from src.units.accounts.execute import _bybit_tpsl_mode
    return _bybit_tpsl_mode()


def _default_hedge(account_id: str, symbol: str) -> bool:
    from src.runtime.bybit_position_mode import hedge_mode_enabled
    return hedge_mode_enabled(account_id, symbol)


def admit_slice(
    *,
    account_id: str,
    account_cfg: Mapping[str, Any],
    strategy: str,
    symbol: str,
    direction: str,
    entry: Any,
    sl: Any,
    meta: Optional[Mapping[str, Any]],
    sized_qty: float,
    dry: bool,
    slices_reader: Optional[Callable[[str, str], Optional[list]]] = None,
    positions_reader: Optional[Callable[[Mapping[str, Any]], Optional[Iterable]]] = None,
    tpsl_mode_fn: Optional[Callable[[], str]] = None,
    hedge_fn: Optional[Callable[[str, str], bool]] = None,
    budget_trades: Optional[float] = None,
) -> Dict[str, Any]:
    """``{ok, reason, qty, own_signed, detail}`` — see the module docstring."""
    detail: Dict[str, Any] = {"position_model": "slices"}
    slices = (slices_reader or (lambda a, s: _sl.open_slices(a, s)))(account_id, symbol)
    if slices is None:
        return {"ok": False, "reason": "slice_ledger_unreadable", "qty": 0.0,
                "own_signed": None, "detail": detail}
    own = _sl.strategy_signed_qty(slices, strategy)
    detail.update({"n_slices": len(slices), "ledger_net": _sl.ledger_net(slices),
                   "own_signed": own})
    if abs(own) > _sl.ABS_TOL:
        detail["admission"] = "own_slice_open"
        return {"ok": True, "reason": None, "qty": float(sized_qty),
                "own_signed": own, "detail": detail}

    exchange = str(account_cfg.get("exchange") or "").lower()
    if slices:
        if _sl.has_opposite_slices(slices, direction):
            hedge = bool((hedge_fn or _default_hedge)(account_id, symbol))
            detail["hedge_book"] = hedge
            if not hedge:
                return {"ok": False, "reason": "opposite_slice_one_way_book",
                        "qty": 0.0, "own_signed": own, "detail": detail}
        if exchange == "bybit":
            mode = str((tpsl_mode_fn or _default_tpsl_mode)() or "")
            detail["tpsl_mode"] = mode
            if mode != "partial":
                return {"ok": False, "reason": "slice_requires_partial_tpsl",
                        "qty": 0.0, "own_signed": own, "detail": detail}

    if dry:
        detail["reconcile"] = "skipped_dry"
    else:
        try:
            positions = (positions_reader or _default_positions_reader)(account_cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("slice_admission: venue read failed for %s: %s", account_id, exc)
            positions = None
        rec = _sl.reconcile(slices, positions, symbol)
        detail["reconcile"] = rec
        if rec["state"] == _sl.UNREADABLE:
            return {"ok": False, "reason": "slice_ledger_venue_unreadable", "qty": 0.0,
                    "own_signed": own, "detail": detail}
        if rec["state"] != _sl.RECONCILED:
            return {"ok": False, "reason": "slice_ledger_divergent", "qty": 0.0,
                    "own_signed": own, "detail": detail}

    alloc = ((meta or {}).get(_sa.SLICE_ALLOCATION_META_KEY) or {}).get(account_id) or {}
    weight = float(alloc.get("weight", 1.0) if isinstance(alloc, Mapping) else 1.0)
    contenders = list(alloc.get("contenders") or [strategy]) if isinstance(alloc, Mapping) else [strategy]
    if strategy not in contenders:
        contenders.append(strategy)
    held = _sl.held_stop_risk(slices, exclude_strategies=contenders)
    detail.update({"weight": weight, "contenders": sorted(contenders), "held_risk": held,
                   "allocation_basis": (alloc.get("basis") if isinstance(alloc, Mapping) else None)})
    if held is None:
        return {"ok": False, "reason": "slice_risk_unmeasurable", "qty": 0.0,
                "own_signed": own, "detail": detail}
    if budget_trades is None:
        budget_trades = float(_sa.load_config().get("symbol_budget_trades", 1.0))
    try:
        sizing = _sa.slice_qty(sized_qty=sized_qty, entry=float(entry), sl=float(sl),
                               weight=weight, budget_trades=budget_trades, held_risk=held)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "slice_risk_unmeasurable", "qty": 0.0,
                "own_signed": own, "detail": detail}
    detail["sizing"] = {k: (round(v, 10) if isinstance(v, float) else v)
                        for k, v in sizing.items()}
    detail["budget_trades"] = budget_trades
    if sizing["qty"] <= 0:
        return {"ok": False, "reason": "slice_budget_exhausted", "qty": 0.0,
                "own_signed": own, "detail": detail}
    return {"ok": True, "reason": None, "qty": float(sizing["qty"]),
            "own_signed": own, "detail": detail}
