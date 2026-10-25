"""ONE full-cost-stack resolver for the portfolio/prop evaluator fleet.

WHY THIS EXISTS (PROP-EVAL-COSTS, operator 2026-10-15, pipeline item
PI-20261015-WODD53KG-0001)
-----------------------------------------------------------------------
``scripts/backtest_system.py`` keeps ``SLIPPAGE_BPS_ROUNDTRIP`` /
``FUNDING_BPS_PER_WINDOW`` as module globals defaulting to ``0.0`` that only its
CLI ``main()`` sets. Every in-process caller (the prop evaluator, the prop
Monte-Carlo, alt-prop validation, the account-compat matrix, the panel builder,
the walk-forwards) therefore ran FEE-ONLY, and a prop survival / EV number built
on a fee-only ledger is overstated -- nothing in the result said so.

``resolve_run_costs`` is the one place that turns "nobody chose" into the
venue-aware policy (``execution_costs.resolve_cost_policy``) and records where
each term came from. ``None`` means *nobody chose*, never zero; an explicit 0 is
the fee-only comparison arm and is refused unless the caller declares it
(``allow_fee_only=True``).

Prop venues: a ruleset may declare its firm's own costs in a ``costs:`` block
(``commission_bps_per_side``, ``swap_bps_per_night``); those replace the venue
fee / funding terms (slippage stays the venue-aware term -- a firm does not
declare slippage).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.runtime import execution_costs as ec

SOURCE = "execution_costs.resolve_cost_policy"
FUNDING_WINDOWS_PER_NIGHT = 24.0 / ec.FUNDING_WINDOW_HOURS


class CostPolicyError(ValueError):
    """A run was asked to proceed on a missing / fee-only cost stack."""


def prop_declared_costs(ruleset: Any) -> Dict[str, Optional[float]]:
    """The firm's declared costs from ``ruleset.raw['costs']`` (None = undeclared).

    ``commission_bps_per_side`` -> round-trip fee (x2); ``swap_bps_per_night`` ->
    bps per 8h funding window (/3). Both are the firm's published figures; the
    swap->window conversion spreads a nightly charge evenly over the windows.
    """
    raw = getattr(ruleset, "raw", None) or {}
    c = raw.get("costs") or {}
    comm = c.get("commission_bps_per_side")
    swap = c.get("swap_bps_per_night")
    return {
        "fee_bps_roundtrip": None if comm is None else 2.0 * float(comm),
        "funding_bps_per_window": None if swap is None else float(swap) / FUNDING_WINDOWS_PER_NIGHT,
    }


def resolve_run_costs(
    symbol: Any,
    *,
    fee_bps_roundtrip: Optional[float] = None,
    slippage_bps_roundtrip: Optional[float] = None,
    funding_bps_per_window: Optional[float] = None,
    funding_window_hours: Optional[float] = None,
    ruleset: Any = None,
    allow_fee_only: bool = False,
) -> Dict[str, Any]:
    """Resolve fee + slippage + funding for ``symbol`` and record provenance.

    Precedence per term: explicit argument > ruleset-declared (fee, funding only)
    > venue-aware default. Raises :class:`CostPolicyError` when the result is a
    fee-only stack (slippage 0 AND funding 0 on a symbol that is a perp or a
    prop-declared swap) unless ``allow_fee_only`` declares it the comparison arm.
    """
    declared = prop_declared_costs(ruleset) if ruleset is not None else {}
    src: Dict[str, str] = {}

    if fee_bps_roundtrip is not None:
        fee, src["fee"] = float(fee_bps_roundtrip), "explicit"
    elif declared.get("fee_bps_roundtrip") is not None:
        fee, src["fee"] = declared["fee_bps_roundtrip"], "prop_ruleset.costs"
    else:
        fee, src["fee"] = ec.DEFAULT_FEE_BPS_ROUNDTRIP, "execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP"

    if funding_bps_per_window is None and declared.get("funding_bps_per_window") is not None:
        funding_bps_per_window = declared["funding_bps_per_window"]
        src["funding"] = "prop_ruleset.costs"
    else:
        src["funding"] = "explicit" if funding_bps_per_window is not None else "venue_default"
    src["slippage"] = "explicit" if slippage_bps_roundtrip is not None else "venue_default"

    slip, fund = ec.resolve_cost_policy(
        symbol, slippage_bps_roundtrip=slippage_bps_roundtrip,
        funding_bps_per_window=funding_bps_per_window)
    window = ec.FUNDING_WINDOW_HOURS if funding_window_hours is None else float(funding_window_hours)

    fee_only = slip == 0.0 and fund == 0.0
    if fee_only and not allow_fee_only:
        raise CostPolicyError(
            f"cost stack for {symbol!r} resolved FEE-ONLY (slippage={slip}, funding={fund}); "
            "pass allow_fee_only=True to declare it the comparison arm")
    if fee < 0 or slip < 0 or fund < 0:
        raise CostPolicyError("negative cost term")
    return {
        "source": SOURCE,
        "symbol": None if symbol is None else str(symbol),
        "fee_bps_roundtrip": fee,
        "slippage_bps_roundtrip": slip,
        "funding_bps_per_window": fund,
        "funding_window_hours": window,
        "term_sources": src,
        "fee_only_arm_declared": bool(fee_only),
        "prop_declared": {k: v for k, v in declared.items() if v is not None},
    }


def add_cost_args(parser: Any) -> None:
    """The shared CLI flags. Unset = venue-aware / ruleset-declared; never zero."""
    g = parser.add_argument_group("cost stack (default: venue-aware fee+slippage+funding)")
    g.add_argument("--fee-bps-roundtrip", type=float, default=None)
    g.add_argument("--slippage-bps-roundtrip", type=float, default=None)
    g.add_argument("--funding-bps-per-window", type=float, default=None)
    g.add_argument("--fee-only-arm", action="store_true",
                   help="DECLARE a fee-only comparison run (slippage/funding 0); the result is "
                        "stamped cost-incomplete. Without it a zero stack is refused.")


def costs_from_args(args: Any, symbol: Any, ruleset: Any = None) -> Dict[str, Any]:
    arm = bool(getattr(args, "fee_only_arm", False))
    return resolve_run_costs(
        symbol,
        fee_bps_roundtrip=getattr(args, "fee_bps_roundtrip", None),
        slippage_bps_roundtrip=0.0 if arm else getattr(args, "slippage_bps_roundtrip", None),
        funding_bps_per_window=0.0 if arm else getattr(args, "funding_bps_per_window", None),
        ruleset=ruleset, allow_fee_only=arm)
