"""Sliding-window backtest helpers shared by training-run hypothesis modules."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def simple_backtest(
    candles: pd.DataFrame,
    build_signal: Callable,
    exit_policy: Callable,
    lookback_bars: int,
    max_hold_bars: int = 96,
) -> dict:
    """Walk forward through candles, call build_signal at each step, exit per policy.

    build_signal(window_df) -> dict {direction, entry, sl, tp} OR None.
    exit_policy(sig, future_bars) -> (exit_price, reason).
    """
    trades: list = []
    # AUD-20260927-CA-B02: a build_signal() that RAISES is not "no setup found".
    # Count and keep the first error so the result can tell them apart.
    signal_errors = 0
    first_error: str | None = None
    i = lookback_bars
    while i < len(candles) - max_hold_bars - 1:
        window = candles.iloc[i - lookback_bars : i]
        try:
            sig = build_signal(window)
        except Exception as exc:  # noqa: BLE001 — recorded, surfaced in the result
            signal_errors += 1
            if first_error is None:
                first_error = f"{type(exc).__name__}: {exc}"
            sig = None
        if not sig:
            i += 1
            continue
        future = candles.iloc[i : i + max_hold_bars]
        exit_price, reason = exit_policy(sig, future)
        risk = abs(sig["entry"] - sig["sl"])
        if risk == 0:
            i += 1
            continue
        if sig["direction"] == "long":
            r_mult = (exit_price - sig["entry"]) / risk
        else:
            r_mult = (sig["entry"] - exit_price) / risk
        trades.append({
            **sig, "exit_price": exit_price, "exit_reason": reason,
            "r_mult": r_mult, "ts": candles["timestamp"].iloc[i],
        })
        i += max(1, max_hold_bars // 8)
    err = {"build_signal_errors": signal_errors, "build_signal_first_error": first_error}
    if not trades:
        return {"trades": 0, "expectancy_r": 0.0, "win_rate": 0.0, "sharpe": 0.0,
                "max_dd_r": 0.0, **err}
    rs = pd.Series([t["r_mult"] for t in trades])
    equity = rs.cumsum()
    dd = (equity - equity.cummax()).min()
    return {
        "trades": len(trades),
        "expectancy_r": float(rs.mean()),
        "win_rate": float((rs > 0).mean()),
        "sharpe": float(rs.mean() / rs.std() * np.sqrt(len(rs))) if rs.std() > 0 else 0.0,
        "max_dd_r": float(dd),
        **err,
    }


def sl_tp_exit(sig: dict, future: pd.DataFrame) -> tuple[float, str]:
    """First-touch exit: stop-loss or take-profit, whichever the bar high/low hits first."""
    for _, bar in future.iterrows():
        if sig["direction"] == "long":
            if bar["low"] <= sig["sl"]:
                return float(sig["sl"]), "sl"
            if bar["high"] >= sig["tp"]:
                return float(sig["tp"]), "tp"
        else:
            if bar["high"] >= sig["sl"]:
                return float(sig["sl"]), "sl"
            if bar["low"] <= sig["tp"]:
                return float(sig["tp"]), "tp"
    return float(future["close"].iloc[-1]), "timeout"
