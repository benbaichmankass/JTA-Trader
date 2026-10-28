"""Cost-net labeling policy: the ONE switch + venue-correct cost terms.

Practice principle M1 (``docs/reference/trading-and-model-practice-principles.md``):
label with the cost-net outcome. Operator Tier-2 approval 2026-10-28 (popup,
verbatim): "Yes, ship it today (Recommended)" for labels net of the full cost
stack plus an enforced cost gate on model promotion; revert is one config value.

That value is ``config/ml_training.yaml::cost_net_labels`` (default ``true``).
It is read here and by ``ml.promotion.cost_gate``, so flipping it reverts both
the labels and the gate's enforcement together.

The cost terms are never re-derived here: the fee comes from
``execution_costs.resolve_fee_bps_roundtrip`` (the measured venue fee) and
slippage + funding from ``execution_costs.resolve_cost_policy`` (venue-aware:
perp funding only on crypto perps). A caller value always wins (``None`` means
"nobody chose" → venue default; an explicit ``0.0`` is a gross arm).
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .triple_barrier import BarrierConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = _REPO_ROOT / "config" / "ml_training.yaml"
SWITCH_KEY = "cost_net_labels"

# Scope of the cost a label pays.
#  - "roundtrip": an ENTRY decision (setup_candidates) pays fee + slippage +
#    funding over the hold.
#  - "hold": a HOLD-vs-exit-now decision (exit_candidates). The exit fee and
#    slippage are paid whether the position is closed now or later, so they
#    cancel out of the decision; only the extra holding cost (perp funding over
#    the forward window) is charged.
COST_SCOPES = ("roundtrip", "hold")


def cost_net_enabled(config_path: Path | str | None = None) -> bool:
    """The ONE switch. Missing/unreadable file or key → ``True`` (the shipped
    policy); only an explicit ``cost_net_labels: false`` reverts."""
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — absent/unparseable → default ON
        return True
    val = data.get(SWITCH_KEY, True) if isinstance(data, dict) else True
    return val is not False and str(val).strip().lower() not in ("false", "0", "no", "off")


_TF_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([mhdw])\s*$", re.IGNORECASE)
_TF_HOURS = {"m": 1.0 / 60.0, "h": 1.0, "d": 24.0, "w": 168.0}


def timeframe_hours(timeframe: Any) -> float:
    """``"15m"`` → 0.25, ``"1h"`` → 1.0, ``"1d"`` → 24.0. Unparseable → 0.0
    (the funding term then charges nothing rather than a guess)."""
    m = _TF_RE.match(str(timeframe or ""))
    if not m:
        return 0.0
    return float(m.group(1)) * _TF_HOURS[m.group(2).lower()]


def resolve_barrier_costs(
    symbol: Any,
    timeframe: Any,
    *,
    scope: str = "roundtrip",
    fee_bps_roundtrip: float | None = None,
    slippage_bps_roundtrip: float | None = None,
    funding_bps_per_window: float | None = None,
) -> dict[str, float]:
    """Venue-correct cost terms for one symbol/timeframe, in
    ``execution_costs`` units. Explicit values win; ``None`` → venue default."""
    if scope not in COST_SCOPES:
        raise ValueError(f"scope must be one of {COST_SCOPES}; got {scope!r}")
    from src.runtime.execution_costs import (  # noqa: PLC0415
        resolve_cost_policy,
        resolve_fee_bps_roundtrip,
    )

    fee = resolve_fee_bps_roundtrip(symbol, fee_bps_roundtrip)
    slip, fund = resolve_cost_policy(
        symbol,
        slippage_bps_roundtrip=slippage_bps_roundtrip,
        funding_bps_per_window=funding_bps_per_window,
    )
    if scope == "hold":
        # Exit cost is paid either way — only explicit values are charged.
        fee = float(fee_bps_roundtrip) if fee_bps_roundtrip is not None else 0.0
        slip = (float(slippage_bps_roundtrip)
                if slippage_bps_roundtrip is not None else 0.0)
    return {
        "fee_bps_roundtrip": float(fee),
        "slippage_bps_roundtrip": float(slip),
        "funding_bps_per_window": float(fund),
        "bar_hours": timeframe_hours(timeframe),
    }


def apply_cost_policy(
    base: BarrierConfig,
    symbol: Any,
    timeframe: Any,
    *,
    cost_net: bool | None = None,
    scope: str = "roundtrip",
    fee_bps_roundtrip: float | None = None,
    slippage_bps_roundtrip: float | None = None,
    funding_bps_per_window: float | None = None,
) -> tuple[BarrierConfig, str]:
    """Return ``(config, label_cost_basis)`` for one symbol.

    ``cost_net=None`` → the config switch decides; ``False`` → the gross arm
    (``base`` unchanged, basis ``"gross"``); ``True`` → the full cost stack
    (basis ``"net"``)."""
    enabled = cost_net_enabled() if cost_net is None else bool(cost_net)
    if not enabled:
        return base, "gross"
    terms = resolve_barrier_costs(
        symbol, timeframe, scope=scope,
        fee_bps_roundtrip=fee_bps_roundtrip,
        slippage_bps_roundtrip=slippage_bps_roundtrip,
        funding_bps_per_window=funding_bps_per_window,
    )
    return replace(base, **terms), "net"
