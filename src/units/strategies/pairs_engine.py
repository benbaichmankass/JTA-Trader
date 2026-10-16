"""Live spread/z-score signal engine for the market-neutral pairs sleeve (M22 D2).

Pure signal math, mirroring ``scripts/backtest_pairs.py`` EXACTLY so that the live
sleeve's entry/exit decisions reproduce the validated backtest (SOL/BTC, BNB/BTC,
ETH/BTC, SOL/ETH at lookback=15, entry_z=2.0, exit_z=0.5, stop_z=2.0, rolling
hedge-β). No I/O, no exchange, no accounts, no state — the executor owns state and
placement; this module only computes, given two aligned close series:

  * the log-spread ``s = log(A) − β·log(B)`` (β = rolling OLS cov/var, shift-1
    leakage-safe, or 1.0),
  * the rolling z-score ``z = (s − mean_{lb}) / std_{lb}`` (mean/std shift-1),
  * an ENTRY verdict for the latest closed bar when flat (|z| ≥ entry_z),
  * an EXIT verdict for the latest closed bar when in a position (reversion
    |z| ≤ exit_z, adverse spread-level stop, or max-hold timeout).

The R-unit (the divergence stop) is ``risk = stop_z · std`` in log-spread units,
matching the harness. ⚠️ With ``hedge_beta: rolling`` that std is taken over a
series whose β changes bar to bar, so β drift × the log-price LEVEL inflates it
(~775x measured on SOL/ETH 1h, checklist PAIRS-R-SCALE) and every leg sized off
it is undersized by the same factor. ``fixed_beta_risk`` is the honest R unit —
the same window with β frozen at the entry bar — and ``entry_signal`` reports
both plus their ratio, so a caller can refuse to size on an inflated R unit.
With ``hedge_beta: one`` the two are the same number by construction. The executor translates a spread-direction verdict into the
two per-leg orders (long_spread ⇒ long A / short B; short_spread ⇒ short A / long B)
and prices each leg's SL/TP from the spread stop/target.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class PairParams:
    symbol_a: str
    symbol_b: str
    lookback: int = 15
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 2.0
    max_hold_bars: int = 20
    hedge_beta: str = "rolling"  # "rolling" | "one"


@dataclass(frozen=True)
class OpenPair:
    """The executor's view of an open pairs position, passed back to exit_signal."""
    direction: str        # "long_spread" | "short_spread"
    entry_spread: float
    stop_spread: float
    bars_held: int


def _rolling_beta(la: np.ndarray, lb: np.ndarray, window: int) -> np.ndarray:
    """Rolling OLS slope of la on lb (cov/var), shifted 1 bar (leakage-safe).
    Mirrors scripts/backtest_pairs.py::_rolling_beta."""
    import pandas as pd
    sa, sb = pd.Series(la), pd.Series(lb)
    cov = sa.rolling(window).cov(sb)
    var = sb.rolling(window).var()
    beta = (cov / var).replace([np.inf, -np.inf], np.nan).shift(1).fillna(1.0)
    return beta.to_numpy()


def compute_spread_z(close_a: Sequence[float], close_b: Sequence[float],
                     lookback: int, hedge_beta: str = "rolling"
                     ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (spread, z, std, beta) arrays aligned to the inputs. Mirrors the
    harness: mean/std are rolling(lookback) SHIFTED 1 bar (std ddof=0)."""
    import pandas as pd
    a = np.asarray(close_a, dtype=float)
    b = np.asarray(close_b, dtype=float)
    la, lb = np.log(a), np.log(b)
    beta = _rolling_beta(la, lb, lookback) if hedge_beta == "rolling" else np.ones_like(la)
    spread = la - beta * lb
    sp = pd.Series(spread)
    mean = sp.rolling(lookback).mean().shift(1)
    std = sp.rolling(lookback).std(ddof=0).shift(1)
    z = ((sp - mean) / std).replace([np.inf, -np.inf], np.nan)
    return spread, z.to_numpy(), std.to_numpy(), beta


def _latest_valid(spread: np.ndarray, z: np.ndarray, std: np.ndarray
                  ) -> Optional[Tuple[int, float, float, float]]:
    """Latest bar index with finite z + positive std. Returns (i, spread_i, z_i, std_i)."""
    n = len(spread)
    i = n - 1
    if i < 1:
        return None
    zi, si, spi = z[i], std[i], spread[i]
    if zi is None or not np.isfinite(zi) or si is None or not np.isfinite(si) or si <= 0:
        return None
    if not np.isfinite(spi):
        return None
    return i, float(spi), float(zi), float(si)


#: |risk / risk_fixed_beta − 1| at or under this is "the same R unit"
#: (pandas' rolling std and numpy's std differ only in floating-point noise).
RISK_SCALE_TOLERANCE = 0.01


def fixed_beta_risk(close_a: Sequence[float], close_b: Sequence[float],
                    params: PairParams, beta_entry: float) -> Optional[float]:
    """The honest R unit for an entry on the LATEST bar: ``stop_z × std`` (ddof 0)
    of ``logA − beta_entry·logB`` over the SAME shift-1 lookback window
    ``entry_signal``'s std covers (the ``lookback`` bars before the latest),
    with β FROZEN at the entry bar's value.

    A position entered at β_entry makes money on ``N_A·(dlogA − β_entry·dlogB)``,
    so the spread its stop and size must be measured on is the fixed-β one; the
    rolling-β series also moves whenever β itself moves (PAIRS-R-SCALE).
    None when not computable (short input, non-positive price, zero std)."""
    a = np.asarray(close_a, dtype=float)
    b = np.asarray(close_b, dtype=float)
    n = len(a)
    lb_n = int(params.lookback)
    if n != len(b) or n <= lb_n + 1 or lb_n < 2:
        return None
    if not (np.all(a > 0) and np.all(b > 0)) or not np.isfinite(beta_entry):
        return None
    la, lb = np.log(a[n - 1 - lb_n:n - 1]), np.log(b[n - 1 - lb_n:n - 1])
    sd = float(np.std(la - float(beta_entry) * lb, ddof=0))
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float(params.stop_z * sd)


def entry_signal(close_a: Sequence[float], close_b: Sequence[float],
                 params: PairParams) -> Optional[Dict[str, Any]]:
    """ENTRY verdict for the latest closed bar when FLAT, or None. Mirrors the
    harness entry block: |z| >= entry_z → short_spread if z>0 else long_spread;
    risk = stop_z*std; stop_spread = entry ∓ risk."""
    if len(close_a) != len(close_b) or len(close_a) <= params.lookback + 1:
        return None
    spread, z, std, beta = compute_spread_z(close_a, close_b, params.lookback, params.hedge_beta)
    latest = _latest_valid(spread, z, std)
    if latest is None:
        return None
    i, entry_spread, zi, si = latest
    if abs(zi) < params.entry_z:
        return None
    direction = "short_spread" if zi > 0 else "long_spread"
    risk = float(params.stop_z * si)
    if risk <= 0:
        return None
    stop_spread = entry_spread - risk if direction == "long_spread" else entry_spread + risk
    risk_fixed = fixed_beta_risk(close_a, close_b, params, float(beta[i]))
    ratio = (risk / risk_fixed) if risk_fixed else None
    return {
        "direction": direction, "z": round(zi, 4), "entry_spread": round(entry_spread, 6),
        "std": round(si, 6), "risk": round(risk, 6), "stop_spread": round(stop_spread, 6),
        "beta": round(float(beta[i]), 6), "symbol_a": params.symbol_a, "symbol_b": params.symbol_b,
        "risk_fixed_beta": round(risk_fixed, 6) if risk_fixed else None,
        "risk_scale_ratio": round(ratio, 4) if ratio is not None else None,
    }


def exit_signal(close_a: Sequence[float], close_b: Sequence[float],
                params: PairParams, position: OpenPair) -> Optional[Dict[str, Any]]:
    """EXIT verdict for the latest closed bar when IN a position, or None (hold).
    Mirrors the harness exit checks (spread-level divergence stop, reversion,
    timeout). Order: divergence stop first, then reversion, then timeout."""
    if len(close_a) != len(close_b) or len(close_a) <= params.lookback + 1:
        return None
    spread, z, std, _ = compute_spread_z(close_a, close_b, params.lookback, params.hedge_beta)
    latest = _latest_valid(spread, z, std)
    if latest is None:
        # can't evaluate; only the executor's own timeout can fire (handled below)
        if position.bars_held >= params.max_hold_bars:
            return {"outcome": "timeout"}
        return None
    _, sj, zj, _ = latest
    # divergence stop (spread-level breach), matching the harness
    if position.direction == "long_spread" and sj <= position.stop_spread:
        return {"outcome": "stop", "exit_spread": round(position.stop_spread, 6)}
    if position.direction == "short_spread" and sj >= position.stop_spread:
        return {"outcome": "stop", "exit_spread": round(position.stop_spread, 6)}
    # reversion exit
    if abs(zj) <= params.exit_z:
        return {"outcome": "revert", "exit_spread": round(sj, 6), "z": round(zj, 4)}
    # timeout
    if position.bars_held >= params.max_hold_bars:
        return {"outcome": "timeout", "exit_spread": round(sj, 6)}
    return None


def reversion_target_spread(close_a: Sequence[float], close_b: Sequence[float],
                            params: PairParams, direction: str) -> Optional[Dict[str, float]]:
    """The spread level the REVERSION exit predicts, measured against the window
    the NEXT bar's z will use, plus the current spread and beta.

    The harness's revert exit fires at ``|z| <= exit_z``; for a long_spread
    (entered at z <= -entry_z) the nearest such level is ``mean - exit_z*std``,
    for a short_spread ``mean + exit_z*std``. ``mean``/``std`` here are the
    rolling(lookback) stats INCLUDING the latest bar — exactly the shift-1
    window the next bar's z is computed against — so the level is a prediction
    of where the exit will fire, re-estimable every bar (TP doctrine clause 2).
    Returns ``{target_spread, spread_now, beta}`` or None when not computable.
    """
    import pandas as pd
    if len(close_a) != len(close_b) or len(close_a) <= params.lookback + 1:
        return None
    spread, _, _, beta = compute_spread_z(close_a, close_b, params.lookback, params.hedge_beta)
    sp = pd.Series(spread)
    mean = float(sp.rolling(params.lookback).mean().iloc[-1])
    std = float(sp.rolling(params.lookback).std(ddof=0).iloc[-1])
    s_now = float(spread[-1])
    if not (np.isfinite(mean) and np.isfinite(std) and std > 0 and np.isfinite(s_now)):
        return None
    band = float(params.exit_z) * std
    target = mean - band if direction == "long_spread" else mean + band
    return {"target_spread": target, "spread_now": s_now, "beta": float(beta[-1])}


def leg_target_prices(direction: str, price_a: float, price_b: float,
                      spread_now: float, target_spread: float,
                      beta: float) -> Optional[Dict[str, float]]:
    """Per-leg take-profit prices implied by the spread reaching ``target_spread``.

    Each leg's TP is the price at which THAT leg alone closes the predicted
    spread gap (the other leg unchanged): leg A moves the spread one-for-one,
    leg B by ``-beta`` per unit of log-price. A TP that fires on one leg
    therefore means the predicted reversion happened — the thesis, not a
    sentinel. Returns None when the gap is not in the trade's favour (the
    spread is already at/through the target: nothing left to predict) or any
    input is degenerate.
    """
    if not (price_a > 0 and price_b > 0):
        return None
    gap = float(target_spread) - float(spread_now)       # log-spread still to travel
    if direction == "long_spread" and gap <= 0:
        return None
    if direction == "short_spread" and gap >= 0:
        return None
    b = abs(float(beta)) if np.isfinite(beta) and abs(float(beta)) > 0 else 1.0
    tp_a = float(price_a) * float(np.exp(gap))           # A carries the gap directly
    tp_b = float(price_b) * float(np.exp(-gap / b))      # B carries it inverted, / beta
    return {"tp_a": tp_a, "tp_b": tp_b, "gap": gap}


def leg_directions(spread_direction: str) -> Dict[str, str]:
    """Map a spread verdict to per-leg order directions.
    long_spread  = long A / short B (spread = logA - beta*logB expected to rise).
    short_spread = short A / long B."""
    if spread_direction == "long_spread":
        return {"a": "long", "b": "short"}
    return {"a": "short", "b": "long"}
