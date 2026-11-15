"""Per-account ml_entry profile: ONE ml_entry implementation, every account by config (row ML-ENTRY-ALL-ACCOUNTS; Tier 3).

Operator 2026-11-01, verbatim: "the supra-symbol mls are for all symbols on all accounts". The #22079 audit found six
crypto/Bybit assumptions hard-coded in the ml_entry path. This module turns the five that are CODE into declared
config on the leg (``config/strategies.yaml::ml_entry.account_profiles.<account_id>``); the sixth (features assume 24
bars/day: ``ret_168``, ``vol168``, ``hour``/``dow`` on an equity RTH series) is an EVIDENCE question for the Stage-0
unit, not code.

Keys of one profile (every key optional; an absent key is today's behaviour, so a leg with no ``account_profiles`` --
bybit_2, bybit_portfolio, alpaca_paper as of 2026-11-04 -- is byte-identical):

``reference: {venue: <venue>, universe: artifact | [symbols]}``
    Where the cross-sectional reference frames come from, INDEPENDENT of the trading venue. Default ``bybit`` +
    the artifact's ``meta.xs_reference`` (the 60 linear perps the model was trained against).
``anchor: <symbol>``
    The symbol behind the ``btc_ret24`` / ``btc_vol24`` features. Default the artifact's ``meta.xs_anchor`` when it
    declares one, else ``BTCUSDT``. The FEATURE NAMES never change (they are the artifact's columns).
``side_filter: long | short | both``
    Which sides the model may choose on this account, resolved by the existing
    ``strategy_signal_builders._resolve_side_filter`` (``long_only: true`` also works). The decision is the argmax over
    the ALLOWED sides (a long-only account takes ``long`` when ``p_long > tau`` even if ``p_short`` is larger).
``session: <asset class> | auto``
    Market-hours-aware decision bars: a decision bar is taken only when that market is open at the bar's close (a
    market order fills) AND still open when the time stop comes due (``max_hold``) -- the same refusal pair the desk
    leg uses (``market_closed`` / ``market_closes_before_max_hold``). ``auto`` = ``market_hours.asset_class_for_symbol``.
    Default none = 24/7.
``cost_basis: {fee_bps_rt, slippage_bps_rt, funding_bps_per_8h, artifact_bps_rt?}``
    The account's cost stack, bps of notional. It (a) re-derives a gated artifact's ``cost_gate.k_cost_x_atr``,
    (b) prices the moving-TP grid, (c) is recorded on the package, and (d) ONLY when ``artifact_bps_rt`` (the stack
    the artifact's tau / pred net R were fit under) is declared, re-bases ``pred_net_r`` from that stack to this one.
    Default none = the artifact's own (crypto) stack, unchanged.

Resolution is per SYMBOL, because ml_entry builds ONE signal per symbol and the coordinator dispatches it to every
account whose ``account_symbols`` holds that symbol. Accounts sharing a symbol must agree on reference / anchor /
session / cost basis (a disagreement refuses the decision ``profile_conflict:<key>`` -- never a silent pick); sides
take the UNION (the per-account ``accounts.yaml::side_filter`` at dispatch still narrows each account).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

PROFILES_KEY = "account_profiles"
DEFAULT_REFERENCE_VENUE = "bybit"
DEFAULT_ANCHOR = "BTCUSDT"
_SHARED_KEYS = ("reference_venue", "reference_universe", "anchor", "session", "cost_basis")
_COST_KEYS = ("fee_bps_rt", "slippage_bps_rt", "funding_bps_per_8h", "artifact_bps_rt")


def _accounts_for(leg_cfg: Mapping[str, Any], symbol: str, leg: Optional[str] = None) -> List[str]:
    from src.config.symbol_sets import (
        ACCOUNT_SYMBOLS_KEY,
        leg_symbols,
        scoped_leg_accounts,
    )
    scope = leg_cfg.get(ACCOUNT_SYMBOLS_KEY)
    if not isinstance(scope, Mapping):
        return []
    return [a for a in scoped_leg_accounts(leg, scope) if symbol in leg_symbols(leg_cfg, a, leg=leg)]


def _norm_cost(raw: Any) -> Optional[Dict[str, float]]:
    if not isinstance(raw, Mapping):
        return None
    out = {k: float(raw[k]) for k in _COST_KEYS if raw.get(k) is not None}
    return out or None


def _one(profile: Mapping[str, Any], leg_side: str) -> Dict[str, Any]:
    """One account's profile with every key resolved (``None`` = the artifact / today's default)."""
    from src.runtime.strategy_signal_builders import _resolve_side_filter
    ref = profile.get("reference") if isinstance(profile.get("reference"), Mapping) else {}
    uni = ref.get("universe")
    universe = tuple(str(s) for s in uni) if isinstance(uni, (list, tuple)) else None
    sess = profile.get("session")
    has_side = "side_filter" in profile or "long_only" in profile
    return {
        "reference_venue": str(ref.get("venue") or DEFAULT_REFERENCE_VENUE).lower(),
        "reference_universe": universe,
        "anchor": str(profile["anchor"]) if profile.get("anchor") else None,
        "session": str(sess).strip().lower() if sess else None,
        "cost_basis": _norm_cost(profile.get("cost_basis")),
        "side_filter": _resolve_side_filter(dict(profile)) if has_side else leg_side,
    }


def resolve(leg_cfg: Mapping[str, Any], symbol: str, leg: Optional[str] = None) -> Dict[str, Any]:
    """The resolved profile for ``symbol`` on this leg. Always returns a dict; ``conflict`` is a key name or None.

    A leg without ``account_profiles`` returns the defaults with ``declared=False`` -- the caller then takes the
    pre-2026-11-04 path verbatim (bybit parity)."""
    from src.runtime.strategy_signal_builders import _resolve_side_filter
    leg_cfg = leg_cfg if isinstance(leg_cfg, Mapping) else {}
    leg_side = _resolve_side_filter(dict(leg_cfg))
    profiles = leg_cfg.get(PROFILES_KEY) if isinstance(leg_cfg.get(PROFILES_KEY), Mapping) else {}
    accounts = _accounts_for(leg_cfg, symbol, leg)
    resolved = [_one(profiles.get(a) if isinstance(profiles.get(a), Mapping) else {}, leg_side) for a in accounts]
    if not resolved:
        resolved = [_one({}, leg_side)]
    out: Dict[str, Any] = {"accounts": accounts, "conflict": None,
                           "declared": any(isinstance(profiles.get(a), Mapping) for a in accounts)}
    for k in _SHARED_KEYS:
        vals = [r[k] for r in resolved]
        if any(v != vals[0] for v in vals[1:]):
            out["conflict"] = out["conflict"] or k
        out[k] = vals[0]
    sides = {r["side_filter"] for r in resolved}
    out["side_filter"] = sides.pop() if len(sides) == 1 else "both"
    return out


def reference_universe(profile: Mapping[str, Any], meta: Mapping[str, Any]) -> List[str]:
    u = profile.get("reference_universe")
    return list(u) if u else list(meta.get("xs_reference") or [])


def anchor(profile: Optional[Mapping[str, Any]], meta: Mapping[str, Any]) -> str:
    return str((profile or {}).get("anchor") or meta.get("xs_anchor") or DEFAULT_ANCHOR)


def allowed_sides(side_filter: str) -> tuple:
    return {"long": ("long",), "short": ("short",)}.get(str(side_filter or "both"), ("long", "short"))


def total_bps_rt(cost: Mapping[str, float], horizon_h: float) -> float:
    """Round-trip bps over a hold of ``horizon_h`` hours: fee + slippage + funding x (horizon / 8h)."""
    return (float(cost.get("fee_bps_rt", 0.0)) + float(cost.get("slippage_bps_rt", 0.0))
            + float(cost.get("funding_bps_per_8h", 0.0)) * float(horizon_h) / 8.0)


def cost_r(bps_rt: float, atr_pct: float, sl_atr: float) -> float:
    """Cost per R for a stop of ``sl_atr`` x ATR: bps / 1e4 / (sl_atr x ATR / price)."""
    return float(bps_rt) / 1e4 / (float(sl_atr) * float(atr_pct)) if atr_pct > 0 else float("inf")


def session_refusal(session: Optional[str], symbol: str, close_ts: Any, max_hold_min: int) -> Optional[str]:
    """``None`` when the decision may be taken; else the refusal reason. No session declared -> always ``None``."""
    if not session:
        return None
    from datetime import timedelta

    import pandas as pd

    from src.runtime.market_hours import asset_class_for_symbol, is_market_open
    cls = asset_class_for_symbol(symbol) if session == "auto" else session
    t = pd.Timestamp(close_ts).to_pydatetime()
    if not is_market_open(cls, t):
        return f"market_closed:{cls}"
    if max_hold_min > 0 and not is_market_open(cls, t + timedelta(minutes=int(max_hold_min))):
        return f"market_closes_before_max_hold:{cls}:{int(max_hold_min)}m"
    return None
