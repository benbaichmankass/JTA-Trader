#!/usr/bin/env python3
# wiring: manual-only - run by scripts/research/frontier_momentum_runner.py (research-script-run.yml unit RQ-20261011-9da8-05); otherwise a session runs it by hand.
"""Time-series momentum (TSMOM) with volatility targeting, per symbol, full cost stack.

The entry-signal instrument RQ-20261011-9da8-05 asks for. ``scripts/backtest_vol_target.py`` is a
BOOK-LEVEL overlay on a return series and has no entry signal, so the question had no instrument.

Spec, exact (every parameter is a flag; the QUEUE UNIT fixes the values before the run):
  - Signal   : per symbol and per lookback L in ``--lookbacks``: ``sign(close[t-1] / close[t-1-L] - 1)``,
               data through t-1 ONLY. The score is the MEAN sign over the lookback set (in [-1, +1]).
  - Sizing   : ``w = score * min(--max-leverage, --target-vol / realised_vol)``, realised vol = annualised
               population stdev of the trailing ``--vol-window`` daily returns ending t-1. Each symbol is its
               own sleeve (weight is a fraction of that sleeve's notional); symbols are NOT netted or ranked.
  - Rebalance: every ``--rebalance-days`` panel days (default 7): the weight is reset from the signal and held
               in between (bounds turnover; the same cadence as the xsec harness).
  - Returns  : daily fractional return per sleeve ``w * (close[t]/close[t-1] - 1)``. UNIT: fractional return of
               the sleeve, NOT stop-distance R -- there is no stop here. ``net_total_r`` in the verdict is the sum.
  - Costs    : the FULL stack from ``src.runtime.execution_costs`` (no cost dict here): fee
               ``resolve_fee_bps_roundtrip(sym)`` x ``--fee-multiplier`` plus ``resolve_cost_policy(sym)`` slippage,
               both charged on turnover ``|delta w|`` (the xsec convention, i.e. a round-trip rate per unit of
               weight change: CONSERVATIVE, it charges both legs of every round trip at the full round-trip rate);
               FUNDING per held day: the SIGNED settled series when ``funding_series[sym]`` is given
               (``w * summed_daily_rate``: long pays, short receives), else the flat directionless
               ``|w| * funding_bps_per_window * 3`` drag, with the symbol listed in ``funding_flat_symbols``.
  - n_trades : a leg OPENED or FLIPPED (flat -> held, or sign change) per symbol.

Research only (Tier-1). No config, no order path. ``--self-test`` plants a trending and a mean-reverting
series and checks the sign of the net result and the cost arithmetic.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.runtime import execution_costs  # noqa: E402

FUNDING_WINDOWS_PER_DAY = 24.0 / execution_costs.FUNDING_WINDOW_HOURS
TRADING_DAYS_PER_YEAR = 365  # crypto trades every day; the vol annualiser uses calendar days


def _score(closes: np.ndarray, t: int, lookbacks: Sequence[int]) -> Optional[float]:
    """Mean sign of the trailing returns, data through t-1 only. None if any lookback is unavailable."""
    end = t - 1
    signs: List[float] = []
    for L in lookbacks:
        start = end - L
        if start < 0 or not (closes[end] > 0 and closes[start] > 0):
            return None
        r = closes[end] / closes[start] - 1.0
        signs.append(float(np.sign(r)))
    return float(np.mean(signs))


def _realised_vol(closes: np.ndarray, t: int, window: int) -> Optional[float]:
    end = t - 1
    if end - window < 0:
        return None
    seg = closes[end - window:end + 1]
    if not np.all(seg > 0):
        return None
    rets = seg[1:] / seg[:-1] - 1.0
    sd = float(np.std(rets))
    return sd * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None


def run_tsmom(panel: pd.DataFrame, *, lookbacks: Sequence[int], vol_window: int, target_vol: float,
              max_leverage: float, rebalance: int, fee_multiplier: float = 1.0,
              fee_bps_roundtrip: Optional[float] = None, slippage_bps: Optional[float] = None,
              funding_bps_per_window: Optional[float] = None, venue: str = "auto",
              funding_series: Optional[Dict[str, pd.Series]] = None) -> Dict[str, Any]:
    cols = list(panel.columns)
    days = list(panel.index)
    closes_all = panel.to_numpy(dtype=float)
    fseries = {s: v for s, v in (funding_series or {}).items() if s in cols}
    per_symbol: Dict[str, Dict[str, Any]] = {}
    daily_net = np.zeros(len(days))
    for ci, sym in enumerate(cols):
        key = f"{sym}USDT" if venue == "perp" and not str(sym).upper().endswith("USDT") else sym
        fee_bps = execution_costs.resolve_fee_bps_roundtrip(key, fee_bps_roundtrip)
        slip_bps, fund_bps = execution_costs.resolve_cost_policy(
            key, slippage_bps_roundtrip=slippage_bps, funding_bps_per_window=funding_bps_per_window)
        unit_cost = (fee_bps * fee_multiplier + slip_bps) / 10_000.0
        closes = closes_all[:, ci]
        w = 0.0
        gross = fund_tot = turn_tot = 0.0
        n_trades = held_days = real_days = missing_days = 0
        net_daily = np.zeros(len(days))
        for t in range(len(days)):
            turn = 0.0
            if t % rebalance == 0:
                sc = _score(closes, t, lookbacks)
                vol = _realised_vol(closes, t, vol_window)
                new_w = 0.0 if (sc is None or vol is None) else sc * min(max_leverage, target_vol / vol)
                if new_w != 0.0 and (w == 0.0 or (w > 0) != (new_w > 0)):
                    n_trades += 1
                turn = abs(new_w - w) * unit_cost
                turn_tot += turn
                w = new_w
            g = f = 0.0
            if t > 0 and w != 0.0 and closes[t] > 0 and closes[t - 1] > 0:
                g = w * (closes[t] / closes[t - 1] - 1.0)
                held_days += 1
                if sym in fseries:
                    fr = fseries[sym].get(days[t])
                    if fr is None or pd.isna(fr):
                        missing_days += 1
                    else:
                        f = w * float(fr)
                        real_days += 1
                else:
                    f = abs(w) * fund_bps / 10_000.0 * FUNDING_WINDOWS_PER_DAY
            gross += g
            fund_tot += f
            net_daily[t] = g - f - turn
        daily_net += net_daily
        per_symbol[sym] = {
            "net_total_r": round(float(net_daily.sum()), 8), "gross_return": round(gross, 8),
            "funding_cost": round(fund_tot, 8), "turnover_cost": round(turn_tot, 8),
            "n_trades": n_trades, "held_days": held_days,
            "funding_real_days": real_days, "funding_missing_days": missing_days,
            "funding_basis": "real_series" if sym in fseries else "flat_directionless",
            "cost_policy": {"fee_bps_roundtrip": fee_bps, "fee_multiplier": fee_multiplier,
                            "slippage_bps_roundtrip": slip_bps, "funding_bps_per_window": fund_bps,
                            "source": "execution_costs.resolve_fee_bps_roundtrip + resolve_cost_policy"},
        }
    return {"per_symbol": per_symbol, "n_days": len(days),
            "data_start": str(days[0].date()) if days else None,
            "data_end": str(days[-1].date()) if days else None,
            "params": {"lookbacks": list(lookbacks), "vol_window": vol_window, "target_vol": target_vol,
                       "max_leverage": max_leverage, "rebalance_days": rebalance,
                       "fee_multiplier": fee_multiplier, "venue": venue},
            "unit": "fractional return of each symbol's vol-targeted sleeve (not stop-distance R)"}


def _self_test() -> int:
    rng = np.random.default_rng(7)
    n = 900
    idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    trend = 100 * np.exp(np.cumsum(0.004 + rng.normal(0, 0.01, n)))
    # mean-reverting series around 100: signal is wrong-footed
    mr = 100 * np.exp(0.15 * np.sin(np.arange(n) / 6.0) + rng.normal(0, 0.003, n))
    panel = pd.DataFrame({"BTCUSDT": trend, "ETHUSDT": mr}, index=idx)
    kw = dict(lookbacks=[28], vol_window=30, target_vol=0.2, max_leverage=2.0, rebalance=7,
              fee_bps_roundtrip=0.0, slippage_bps=0.0, funding_bps_per_window=0.0)
    r0 = run_tsmom(panel, **kw)["per_symbol"]
    assert r0["BTCUSDT"]["net_total_r"] > 0.2, r0["BTCUSDT"]
    assert r0["BTCUSDT"]["net_total_r"] > r0["ETHUSDT"]["net_total_r"], r0
    # costs strictly reduce the net, and funding is signed (short receives)
    kw2 = {**kw, "fee_bps_roundtrip": 11.0, "slippage_bps": 3.0}
    r1 = run_tsmom(panel, **kw2)["per_symbol"]["BTCUSDT"]
    assert r1["net_total_r"] < r0["BTCUSDT"]["net_total_r"] and r1["turnover_cost"] > 0, r1
    fs = pd.Series(0.001, index=panel.index)
    rf = run_tsmom(panel, **kw, funding_series={"BTCUSDT": fs})["per_symbol"]["BTCUSDT"]
    assert rf["funding_basis"] == "real_series" and rf["funding_cost"] > 0, rf  # long-only trend pays
    assert abs(rf["net_total_r"] - (rf["gross_return"] - rf["funding_cost"] - rf["turnover_cost"])) < 1e-6, rf
    print(f"backtest_tsmom SELF-TEST PASS (trend net={r0['BTCUSDT']['net_total_r']:.3f}, "
          f"mr net={r0['ETHUSDT']['net_total_r']:.3f}, n_trades={r0['BTCUSDT']['n_trades']})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    sys.exit(_self_test() if a.self_test else (ap.print_help() or 0))
