"""Shared entry-gate rules for the per-leg Stage-0 harnesses (PI-20261123-SME5WDGR-0008, lever-flag parity).

ONE definition of the ATR-percentile vol-at-entry gate, copied from the semantics of ``scripts/backtest_trend.py`` (M21 E-2) so every harness
that grows ``--vol-skip-above-pctl`` / ``--vol-skip-below-pctl`` agrees with it:

  * the percentile is the rank of the SIGNAL bar's ATR within the trailing ``window`` bars (causal: the window includes the bar itself),
    ``min_periods == window`` so it is NaN until the window fills;
  * ``above > 0`` skips the hot tail (percentile > above), ``below > 0`` skips the dead tail (percentile < below);
  * an undefined (NaN) percentile NEVER skips (fail-permissive), and 0 means off, so a default run allocates nothing and stays byte-identical.

Tier 1 research tooling. Lives under scripts/ (not src/): it is backtest-only and a src/ edit would bar a self-land PR.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

DEFAULT_WINDOW = 200


def gate_armed(above: float, below: float) -> bool:
    return above > 0.0 or below > 0.0


def flag_errors(above: float, below: float, window: int) -> list:
    """Reasons a flag set is refused (empty = fine). A percentile is a fraction in (0, 1]; the window must be a positive bar count."""
    errs = []
    for name, v in (("--vol-skip-above-pctl", above), ("--vol-skip-below-pctl", below)):
        if v < 0.0 or v > 1.0:
            errs.append(f"{name} must be a fraction in [0, 1] (0 = off), got {v!r}")
    if window < 2:
        errs.append(f"--vol-pctl-window must be >= 2 bars, got {window!r}")
    if above > 0.0 and below > 0.0 and below >= above:
        errs.append("--vol-skip-below-pctl must be below --vol-skip-above-pctl when both are set (the kept band would be empty)")
    return errs


def pctl_series(atr: pd.Series, window: int = DEFAULT_WINDOW) -> pd.Series:
    """Trailing ATR percentile rank (the same expression backtest_trend.py uses)."""
    return atr.rolling(window, min_periods=window).rank(pct=True)


def skips(pctl: Optional[pd.Series], i: int, above: float, below: float) -> bool:
    """True when the signal bar at position ``i`` is in a skipped tail. ``pctl`` None (gate off) or an undefined value never skips."""
    if pctl is None:
        return False
    vp = pctl.iloc[i]
    if pd.isna(vp):
        return False
    if above > 0.0 and float(vp) > above:
        return True
    if below > 0.0 and float(vp) < below:
        return True
    return False


# ---- ADX ceiling (--adx-max), the convention of the chop-family harnesses (backtest_fade.py / backtest_fvg_range.py) -----------------------

def adx_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's ADX, the SAME definition as backtest_fade._adx / backtest_fvg_range._adx (a test asserts equality; backtest_trend's differs).
    Callers shift it by one bar so the signal bar reads the ADX of the last CLOSED bar (no lookahead)."""
    h, low, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)) * down.clip(lower=0)
    pc = c.shift(1)
    tr = pd.concat([(h - low), (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    return dx.ewm(alpha=alpha, adjust=False).mean()


def adx_blocks(adx_prev: Optional[pd.Series], i: int, adx_max: Optional[float]) -> bool:
    """True when the signal bar at ``i`` is blocked by the ceiling: ADX (last closed bar) >= adx_max, or undefined (fail-closed, as fade/fvg).
    ``adx_max`` None = gate off = never blocks."""
    if adx_max is None or adx_prev is None:
        return False
    a = adx_prev.iloc[i]
    return bool(pd.isna(a) or float(a) >= float(adx_max))
