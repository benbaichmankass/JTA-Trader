#!/usr/bin/env python3
# wiring: research/queue/RQ-20261123-1e04-01..03.yaml (once, research-script-run.yml); direction switch: scripts/research/index_direction_switch.py
"""Index-signal -> ETF-execution backtest harness (row IELE-INDEX-DRIVEN-HARNESS).

WHY (operator ask 2026-11-23, via manager Session 2026-11-22a): the six inverse-ETF trend twins (RQ-20261123-1e01-01..06) all FAILED,
because long-side trend rules copied onto a decaying inverse ETF's OWN chart do not work. The remaining units drive the SIGNAL from the
INDEX (SPY/QQQ/DIA/IWM daily) and execute the long-only BUY on the matching bull or inverse ETF.

WHAT IT MODELS (every choice stated; none is tuned after a result)
  * SIGNAL: computed on the INDEX proxy's daily bars only (functions below take index arrays and nothing else; the parity test proves
    the ETF columns cannot change a signal; the lookahead test proves bar i's signal is identical on data truncated at i).
  * ENTRY: next session's OPEN of the execution ETF (signal bar i -> entry bar i+1). Long-only: every order is a BUY of the ETF.
  * BRACKET: the stop is an INDEX level (index structure) mapped through the ETF with its signed leverage beta
        etf_stop = etf_entry * (1 + beta * (idx_stop / idx_entry_open - 1)),   risk = etf_entry - etf_stop  (= 1 R, in ETF price).
    The TP is K* x R above entry (an index-structure target in the same mapping, K* calibrated on the in-sample span, see below).
    Stop/TP are tested against the ETF's OWN daily high/low (what a resting bracket would see); a gap through a level fills at the
    open; stop and TP in one bar -> stop first (conservative). Hold cap = sessions, exit at that bar's close.
  * DECAY: not modelled -- the ETF's actual price series is used, so the daily-reset decay, expense ratio and any reverse-split
    adjustment (yfinance split-adjusted Close, auto_adjust=False, the same feed the twins read) are embedded. Per trade the harness
    also reports `decay_drag` = ETF return - beta x index return over the hold (entry open -> exit-bar close), informational.
    Distributions are NOT added back (price return); state that when reading a small net.
  * COST: slippage `slip_bps` per SIDE on entry and exit (unit rule: fee 0 + 5 bps per side; the 2x re-read is 10 bps per side),
    converted to R by cost_r = 2 * slip/1e4 * entry / risk. No funding.
  * SIZING NOTE (whole shares): reports median entry price, median risk per share and the equity at which ONE whole share's stop risk
    equals 1% of equity (`min_equity_for_1_share_at_1pct_risk`); a derived figure, no account balance is read or written.
  * ONE POSITION at a time per (index, ETF) pair; a signal while in a position is ignored; entry needs bar index > the prior exit bar.
  * TP CALIBRATION (TP doctrine; mirrors scripts/research/tp_prediction_derive.py constants GRID/REACH_FLOOR/IS_FRAC): replay with NO
    TP recording mfe_r, choose K* on the chronologically first IS_FRAC of trades (best counterfactual IS net among K with IS reach >=
    REACH_FLOOR), then RE-SIMULATE with the TP at K* for the graded numbers. Folds 1-2 therefore contain in-sample trades; the
    `oos` block reports the post-boundary trades alone. Never tp_r 50.

Tier-1 research tooling: reads public daily candles (yfinance), writes only under --out, changes no config.
Usage: python3 scripts/research/index_signal_etf_harness.py --family breakdown|failed_rally|capitulation --unit RQ-... --out DIR
       python3 scripts/research/index_signal_etf_harness.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent.parent

# --- constants copied from scripts/research/tp_prediction_derive.py (editing one here is a different experiment) -------------
GRID = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
REACH_FLOOR = 0.10
IS_FRAC = 0.60
# --- registered parameters (units RQ-20261123-1e04-01..03, rules registered 2026-11-23 before any run) ---------------------
DONCHIAN = 20
PIVOT_K = 5
PIVOT_LOOKBACK = 60
SMA_LEN = 50
ATR_LEN = 14
FLUSH_ATR = 2.0
FLUSH_MEAN = 5
FLUSH_UP_WINDOW = 5      # fixed here (the unit text says "then the first up-close" without a bound): expire a flush after 5 sessions
HOLD_CAP = {"capitulation_bull": 10, "breakdown": 20, "failed_rally": 15, "capitulation": 10, "breakdown_bear": 20, "breakdown_bounce": 10, "capitulation_wide": 10}
SMA_LONG = 200
SMA_SLOPE_LOOKBACK = 20
FLUSH_ATR_WIDE = 1.5
BOUNCE_STOP_BARS = 5
SLIP_BPS_SIDE = 5.0
MIN_RISK_FRAC = 0.0025   # a mapped stop closer than 0.25% of the ETF price is skipped (R explodes); skip counts are reported
N_FLOOR = 25
FOLDS = 4
FOLD_MAJORITY = 3
WINDOW_START = "2010-06-01"
WINDOW_END = "2026-10-22"

#: (index proxy, execution ETF, signed leverage beta)
PAIRS = {
    "breakdown": [("SPY", "SPXU", -3.0), ("SPY", "SH", -1.0), ("QQQ", "SQQQ", -3.0), ("QQQ", "PSQ", -1.0),
                  ("DIA", "SDOW", -3.0), ("IWM", "TZA", -3.0)],
    "capitulation": [("SPY", "UPRO", 3.0), ("QQQ", "TQQQ", 3.0), ("DIA", "UDOW", 3.0), ("IWM", "TNA", 3.0)],
    "capitulation_1x": [("SPY", "SPY", 1.0), ("QQQ", "QQQ", 1.0), ("DIA", "DIA", 1.0), ("IWM", "IWM", 1.0)],
}
PAIRS["failed_rally"] = PAIRS["breakdown"]
PAIRS["breakdown_bear"] = PAIRS["breakdown"]
PAIRS["breakdown_bounce"] = PAIRS["capitulation"]
PAIRS["capitulation_wide"] = PAIRS["capitulation"]
#: 1e06-04 confirmation population: 3x ETFs on sector/mid-cap/REIT indexes NOT used in the 1e06-03 discovery read (no fossil-fuel instruments)
PAIRS["capitulation_holdout"] = [("XLK", "TECL", 3.0), ("SOXX", "SOXL", 3.0), ("XLF", "FAS", 3.0), ("MDY", "MIDU", 3.0),
                                 ("IYR", "DRN", 3.0), ("XLV", "CURE", 3.0)]
PAIRS["capitulation_holdout_1x"] = [(i, i, 1.0) for i, _, _ in PAIRS["capitulation_holdout"]]
#: 1e06-05 FRESH population (lane ML-PRIMARY 2026-11-24): 3x ETFs on indexes used in NO earlier read (discovery 1e06-03 or confirmation 1e06-04),
#: no fossil-fuel instruments (same exclusion as 1e06-04)
PAIRS["capitulation_fresh"] = [("XBI", "LABU", 3.0), ("KRE", "DPST", 3.0), ("EEM", "EDC", 3.0), ("XLI", "DUSL", 3.0),
                               ("XLU", "UTSL", 3.0), ("XLY", "WANT", 3.0)]
PAIRS["capitulation_fresh_1x"] = [(i, i, 1.0) for i, _, _ in PAIRS["capitulation_fresh"]]
#: units whose rule GATES on the timing control (1e06-04 reported it: actual at the 86th percentile of re-timed draws)
TIMING_GATED = {"RQ-20261124-1e06-05": 0.05, "RQ-20261124-1e06-06": 0.05, "RQ-20261124-1e06-07": 0.05}
#: 1e06-06 (lane ML-PRIMARY 2026-11-24): the capitulation trigger executed in 1x index ETFs on 8 indexes used in NO earlier read (1e06-05 showed the
#: timing at the 94.5th percentile but 3x losing to 1x: leverage, not timing, broke it). No fossil-fuel instruments.
PAIRS["capitulation_1x_fresh"] = [(t, t, 1.0) for t in ("XLB", "XLP", "ITB", "XME", "EFA", "EWJ", "IYT", "IWN")]
#: pooled units graded against FLAT (no 1x arm: the execution IS 1x) and their pairs-positive floor where it is not POOLED_MIN_POSITIVE_PAIRS
POOLED_MIN_POSITIVE = {"RQ-20261124-1e06-06": 4, "RQ-20261124-1e06-07": 4}
#: 1e06-07 population: 8 more 1x index ETFs used in NO earlier read (no fossil-fuel instruments)
PAIRS["capitulation_bull"] = [(t, t, 1.0) for t in ("KBE", "SMH", "EWZ", "FXI", "EWG", "EWU", "VGK", "IJR")]
POOLED_MIN_POSITIVE_PAIRS = 3
#: 1e06-08 CONFIRMATION of the 1e06-06 pass (lane ML-PRIMARY 2026-11-24): the same 1x timing-gated trigger on 10 country index ETFs used in NO
#: earlier read (no fossil-fuel instruments). A fresh POPULATION, not a fresh time window: the daily window ends 2026-10-22 in every unit.
PAIRS["capitulation_1x_confirm"] = [(t, t, 1.0) for t in ("EWC", "EWA", "EWT", "EWY", "EWW", "EWH", "EWS", "EWL", "EWQ", "EWP")]
TIMING_GATED["RQ-20261124-1e06-08"] = 0.05
POOLED_MIN_POSITIVE["RQ-20261124-1e06-08"] = 5
#: the own-chart trend twin per execution ETF (rule baseline of 1e04-01): unit id
TWIN_UNIT = {"SQQQ": "RQ-20261123-1e01-01", "SPXU": "RQ-20261123-1e01-02", "SDOW": "RQ-20261123-1e01-03",
             "TZA": "RQ-20261123-1e01-04", "SH": "RQ-20261123-1e01-05", "PSQ": "RQ-20261123-1e01-06"}


# ----------------------------------------------------------------------------- data -------------------------------------------
def fetch_daily(ticker: str, start: str, end: str, cache_dir: Path | None = None) -> pd.DataFrame:
    """Daily OHLC from yfinance (auto_adjust=False: split-adjusted, price return -- the twins' feed). tz-naive date index."""
    cp = (cache_dir / f"{ticker}_{start}_{end}.csv") if cache_dir else None
    if cp is not None and cp.exists():
        df = pd.read_csv(cp, index_col=0, parse_dates=True)
        return df
    import yfinance as yf
    df = yf.download(ticker, start=start, end=(pd.Timestamp(end) + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                     interval="1d", auto_adjust=False, progress=False, threads=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance returned no daily bars for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="first")].sort_index().dropna()
    df = df[df.index <= pd.Timestamp(end)]
    if cp is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cp)
    return df


def build_frame(idx: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    """Inner-join by session date: i_* = index proxy, e_* = execution ETF."""
    a = idx[["open", "high", "low", "close"]].add_prefix("i_")
    b = etf[["open", "high", "low", "close"]].add_prefix("e_")
    f = a.join(b, how="inner").sort_index()
    f = f.rename(columns={"i_open": "i_o", "i_high": "i_h", "i_low": "i_l", "i_close": "i_c",
                          "e_open": "e_o", "e_high": "e_h", "e_low": "e_l", "e_close": "e_c"})
    return f.dropna()


# --------------------------------------------------------------------------- signals (INDEX columns only) ---------------------
def _atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()  # simple mean of TR (deterministic, no recursion on the future)


def confirmed_pivot_highs(h: np.ndarray, k: int = PIVOT_K) -> list[tuple[int, int, float]]:
    """(pivot bar p, confirmation bar p+k, value): high[p] strictly above the k bars either side. Known only at p+k."""
    out = []
    for p in range(k, len(h) - k):
        w = h[p - k:p + k + 1]
        if h[p] == w.max() and (w == h[p]).sum() == 1:
            out.append((p, p + k, float(h[p])))
    return out


def signals_breakdown(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:  # inert: i_o — uniform (open, high, low, close) signature across signal families; this trigger reads no index open
    """Donchian-20 close-below-prior-20-low on the index; stop = most recent confirmed pivot-5 high above the close."""
    n = len(i_c)
    piv = confirmed_pivot_highs(i_h)
    out = []
    for i in range(max(DONCHIAN, PIVOT_LOOKBACK), n - 1):
        if not i_c[i] < np.min(i_l[i - DONCHIAN:i]):
            continue
        cands = [v for (p, cf, v) in piv if cf <= i and i - p <= PIVOT_LOOKBACK and v > i_c[i]]
        cand_p = [(p, v) for (p, cf, v) in piv if cf <= i and i - p <= PIVOT_LOOKBACK and v > i_c[i]]
        if not cands:
            out.append({"i": i, "stop_idx": None, "skip": "no_pivot_high"})
            continue
        out.append({"i": i, "stop_idx": cand_p[-1][1]})
    return out


def signals_failed_rally(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:  # inert: i_o — uniform (open, high, low, close) signature across signal families; this trigger reads no index open
    """On the bar a pivot-5 high is CONFIRMED: it is lower than the prior confirmed pivot-5 high, the close is below its 50-day mean
    and below the 20-day mid (prior-20 channel). Stop = that lower high."""
    n = len(i_c)
    piv = confirmed_pivot_highs(i_h)
    sma = pd.Series(i_c).rolling(SMA_LEN).mean().to_numpy()
    hh = pd.Series(i_h).shift(1).rolling(DONCHIAN).max().to_numpy()
    ll = pd.Series(i_l).shift(1).rolling(DONCHIAN).min().to_numpy()
    mid = (hh + ll) / 2.0
    out = []
    for m, (p, cf, v) in enumerate(piv):
        i = cf
        if i >= n - 1 or m == 0:
            continue
        pp, _pcf, pv = piv[m - 1]
        if p - pp > PIVOT_LOOKBACK or not v < pv:
            continue
        if np.isnan(sma[i]) or np.isnan(mid[i]):
            continue
        if i_c[i] < sma[i] and i_c[i] < mid[i]:
            out.append({"i": i, "stop_idx": v})
    return out


def signals_capitulation(i_o, i_h, i_l, i_c, flush_atr: float = FLUSH_ATR) -> list[dict[str, Any]]:  # inert: i_o — uniform (open, high, low, close) signature across signal families; this trigger reads no index open
    """Flush: close >= 2.0 ATR14 below its 5-bar mean AND low below the prior 20 lows. Signal = the first up-close after the flush
    (within FLUSH_UP_WINDOW sessions). Stop = lowest low from the flush bar to the signal bar."""
    n = len(i_c)
    atr = _atr(i_h, i_l, i_c, ATR_LEN)
    m5 = pd.Series(i_c).rolling(FLUSH_MEAN).mean().to_numpy()
    out = []
    start = None
    for i in range(max(DONCHIAN, ATR_LEN) + 1, n - 1):
        flush = (not np.isnan(atr[i])) and i_c[i] <= m5[i] - flush_atr * atr[i] and i_l[i] < np.min(i_l[i - DONCHIAN:i])
        if start is not None and i - start > FLUSH_UP_WINDOW:
            start = None
        if start is None:
            if flush:
                start = i
            continue
        if i_c[i] > i_c[i - 1]:
            out.append({"i": i, "stop_idx": float(np.min(i_l[start:i + 1]))})
            start = None
    return out


def signals_capitulation_wide(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:
    """1e06-03: the capitulation trigger with the flush loosened from 2.0 to 1.5 ATR14 (everything else identical) to reach n >= 25."""
    return signals_capitulation(i_o, i_h, i_l, i_c, FLUSH_ATR_WIDE)


def signals_capitulation_bull(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:  # inert: i_o — uniform (open, high, low, close) signature across signal families; this trigger reads no index open
    """1e06-07 (REGIME arm): the 1.5-ATR capitulation trigger kept only in a bull regime, index close > its SMA200 at the signal bar (point-in-time)."""
    sma = pd.Series(i_c).rolling(SMA_LONG).mean().to_numpy()
    return [s for s in signals_capitulation_wide(i_o, i_h, i_l, i_c) if not np.isnan(sma[s["i"]]) and i_c[s["i"]] > sma[s["i"]]]


def signals_breakdown_bear(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:
    """1e06-01: the 1e04-01 breakdown, kept only in a genuine bear regime: close < SMA200 AND SMA200 below its value 20 bars ago."""
    sma = pd.Series(i_c).rolling(SMA_LONG).mean().to_numpy()
    out = []
    for s in signals_breakdown(i_o, i_h, i_l, i_c):
        i = s["i"]
        if i - SMA_SLOPE_LOOKBACK < 0 or np.isnan(sma[i]) or np.isnan(sma[i - SMA_SLOPE_LOOKBACK]):
            continue
        if i_c[i] < sma[i] and sma[i] < sma[i - SMA_SLOPE_LOOKBACK]:
            out.append(s)
    return out


def signals_breakdown_bounce(i_o, i_h, i_l, i_c) -> list[dict[str, Any]]:
    """1e06-02: the 1e04-01 breakdown trigger executed as a BOUNCE BUY of the bull ETF; stop = lowest low of the last 5 index bars."""
    out = []
    for s in signals_breakdown(i_o, i_h, i_l, i_c):
        i = s["i"]
        out.append({"i": i, "stop_idx": float(np.min(i_l[i - BOUNCE_STOP_BARS + 1:i + 1]))})
    return out


SIGNALS = {"capitulation_bull": signals_capitulation_bull, "breakdown": signals_breakdown, "breakdown_bear": signals_breakdown_bear, "breakdown_bounce": signals_breakdown_bounce,
           "capitulation_wide": signals_capitulation_wide, "failed_rally": signals_failed_rally, "capitulation": signals_capitulation}


def index_signals(frame: pd.DataFrame, family: str) -> list[dict[str, Any]]:
    """The ONLY entry point that turns a frame into signals: it hands the family function the INDEX columns and nothing else."""
    a = [frame[c].to_numpy(float) for c in ("i_o", "i_h", "i_l", "i_c")]
    return SIGNALS[family](*a)


# --------------------------------------------------------------------------------------- execution (ETF columns) -------------
def simulate(frame: pd.DataFrame, sigs: list[dict[str, Any]], beta: float, hold_cap: int, slip_bps: float = SLIP_BPS_SIDE,
             tp_k: float | None = None) -> dict[str, Any]:
    ix = frame.index
    io, ic = frame["i_o"].to_numpy(float), frame["i_c"].to_numpy(float)
    eo, eh, el, ec = (frame[c].to_numpy(float) for c in ("e_o", "e_h", "e_l", "e_c"))
    n = len(frame)
    trades: list[dict[str, Any]] = []
    skips: dict[str, int] = {}
    last_exit = -1
    for s in sigs:
        i = s["i"]
        j = i + 1
        if j >= n:
            continue
        if s.get("stop_idx") is None:
            skips[s.get("skip", "no_stop")] = skips.get(s.get("skip", "no_stop"), 0) + 1
            continue
        if j <= last_exit:
            skips["in_position"] = skips.get("in_position", 0) + 1
            continue
        entry, idx_e, stop_idx = eo[j], io[j], s["stop_idx"]
        if (beta < 0 and not stop_idx > idx_e) or (beta > 0 and not stop_idx < idx_e):
            skips["stop_wrong_side_at_entry"] = skips.get("stop_wrong_side_at_entry", 0) + 1
            continue
        stop = entry * (1.0 + beta * (stop_idx / idx_e - 1.0))
        risk = entry - stop
        if not (risk > 0 and risk / entry >= MIN_RISK_FRAC and stop > 0):
            skips["risk_degenerate"] = skips.get("risk_degenerate", 0) + 1
            continue
        tp = entry + tp_k * risk if tp_k else None
        exit_px, why, k_exit, mfe = ec[min(j + hold_cap - 1, n - 1)], "timeout", min(j + hold_cap - 1, n - 1), 0.0
        for k in range(j, min(j + hold_cap, n)):
            o = eo[k]
            if k > j and o <= stop:
                exit_px, why, k_exit = o, "stop", k
                break
            if k > j and tp is not None and o >= tp:
                exit_px, why, k_exit = o, "take_profit", k
                break
            if el[k] <= stop:
                exit_px, why, k_exit = stop, "stop", k
                break
            mfe = max(mfe, (eh[k] - entry) / risk)
            if tp is not None and eh[k] >= tp:
                exit_px, why, k_exit = tp, "take_profit", k
                break
        gross = (exit_px - entry) / risk
        cost_r = 2.0 * slip_bps / 1e4 * entry / risk
        etf_ret = ec[k_exit] / entry - 1.0
        idx_ret = ic[k_exit] / idx_e - 1.0
        trades.append({"entry_date": str(ix[j].date()), "exit_date": str(ix[k_exit].date()), "signal_date": str(ix[i].date()),
                       "entry": round(entry, 4), "risk": round(risk, 4), "exit": round(float(exit_px), 4), "why": why,
                       "bars": k_exit - j + 1, "gross_r": round(gross, 4), "cost_r": round(cost_r, 4),
                       "net_r": round(gross - cost_r, 4), "mfe_r": round(mfe, 4),
                       "decay_drag": round(etf_ret - beta * idx_ret, 5)})
        last_exit = k_exit
    return {"trades": trades, "skips": skips}


def timing_control(frame: pd.DataFrame, family: str, beta: float, hold_cap: int, k_star: float | None, ndraw: int = 200, seed: int = 11) -> list[float]:
    """Null for TIMING: each real signal keeps its stop geometry (stop/close ratio) but moves to a random bar 40-400 sessions away
    (either direction); returns the net_r total of each of `ndraw` re-timed replays (same TP K*, same cost). Diagnostic, not a gate."""
    sigs = index_signals(frame, family)
    ic = frame["i_c"].to_numpy(float)
    n = len(frame)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(ndraw):
        ss = []
        for s in sigs:
            if s.get("stop_idx") is None:
                continue
            off = int(rng.integers(40, 400)) * (1 if rng.random() < 0.5 else -1)
            ni = s["i"] + off
            if not (60 <= ni < n - 1):
                continue
            ss.append({"i": ni, "stop_idx": ic[ni] * s["stop_idx"] / ic[s["i"]]})
        ss.sort(key=lambda x: x["i"])
        out.append(float(sum(t["net_r"] for t in simulate(frame, ss, beta, hold_cap, SLIP_BPS_SIDE, k_star)["trades"])))
    return out


def calibrate_tp(trades_no_tp: list[dict[str, Any]]) -> dict[str, Any]:
    """K* from the first IS_FRAC of the no-TP trades (chronological): best counterfactual IS net among K with reach >= REACH_FLOOR."""
    n = len(trades_no_tp)
    n_is = math.ceil(IS_FRAC * n)
    isb = trades_no_tp[:n_is]
    if n_is < 10:
        return {"k_star": None, "state": "uncalibrated_too_few_is", "n_is": n_is}
    best = None
    curve = []
    for k in GRID:
        reach = float(np.mean([t["mfe_r"] >= k for t in isb]))
        cf = sum((k - t["cost_r"]) if t["mfe_r"] >= k else t["net_r"] for t in isb)
        curve.append({"k": k, "is_reach": round(reach, 3), "is_cf_net_r": round(cf, 3)})
        if reach >= REACH_FLOOR and (best is None or cf > best[1]):
            best = (k, cf)
    if best is None:
        return {"k_star": None, "state": "uncalibrated_no_k_reaches_floor", "n_is": n_is, "curve": curve}
    return {"k_star": best[0], "state": "calibrated", "n_is": n_is, "is_boundary": isb[-1]["entry_date"], "curve": curve}


def stats(trades: list[dict[str, Any]], edges: list[pd.Timestamp] | None = None) -> dict[str, Any]:
    r = [t["net_r"] for t in trades]
    cum = np.cumsum(r) if r else np.array([0.0])
    dd = float(np.max(np.maximum.accumulate(np.r_[0.0, cum]) - np.r_[0.0, cum])) if r else 0.0
    out = {"n": len(r), "net_r": round(float(sum(r)), 4), "mean_net_r": round(float(np.mean(r)), 4) if r else None,
           "max_drawdown_r": round(dd, 4), "win_rate": round(float(np.mean([x > 0 for x in r])), 3) if r else None,
           "by_outcome": {w: sum(1 for t in trades if t["why"] == w) for w in ("stop", "take_profit", "timeout")}}
    if edges:
        folds = []
        for a, b in itertools.pairwise(edges):
            sel = [t["net_r"] for t in trades if a <= pd.Timestamp(t["entry_date"]) < b or (b == edges[-1] and pd.Timestamp(t["entry_date"]) == b)]
            folds.append({"n": len(sel), "net_r": round(float(sum(sel)), 4)})
        out["folds"] = folds
    return out


def fold_edges(frame: pd.DataFrame, k: int = FOLDS) -> list[pd.Timestamp]:
    a, b = frame.index[0], frame.index[-1]
    return [a + (b - a) * q / k for q in range(k + 1)]


def run_pair(frame: pd.DataFrame, family: str, beta: float, hold_cap: int, tp_k: float | str = "calibrate") -> dict[str, Any]:
    """Full read of one (index, ETF) pair: signals -> no-TP replay -> K* -> graded replay (1x and 2x slippage)."""
    sigs = index_signals(frame, family)
    base = simulate(frame, sigs, beta, hold_cap, SLIP_BPS_SIDE, None)
    cal = calibrate_tp(base["trades"]) if tp_k == "calibrate" else {"k_star": tp_k, "state": "fixed"}
    k = cal["k_star"]
    g1 = simulate(frame, sigs, beta, hold_cap, SLIP_BPS_SIDE, k)
    g2 = simulate(frame, sigs, beta, hold_cap, 2 * SLIP_BPS_SIDE, k)
    edges = fold_edges(frame)
    st = stats(g1["trades"], edges)
    bound = cal.get("is_boundary")
    oos = [t for t in g1["trades"] if bound and t["entry_date"] > bound]
    px = [t["entry"] for t in g1["trades"]]
    rk = [t["risk"] for t in g1["trades"]]
    return {"n_signals": len(sigs), "skips": g1["skips"], "tp_calibration": cal, **st,
            "net_r_2x_slip": stats(g2["trades"])["net_r"],
            "oos": stats(oos) if oos else None,
            "mean_decay_drag": round(float(np.mean([t["decay_drag"] for t in g1["trades"]])), 5) if g1["trades"] else None,
            "mean_bars_held": round(float(np.mean([t["bars"] for t in g1["trades"]])), 2) if g1["trades"] else None,
            "sizing_note": {"median_entry_price": round(float(np.median(px)), 3) if px else None,
                            "median_risk_per_share": round(float(np.median(rk)), 3) if rk else None,
                            "min_equity_for_1_share_at_1pct_risk": round(float(np.median(rk)) / 0.01, 0) if rk else None},
            "data_start": str(frame.index[0].date()), "data_end": str(frame.index[-1].date()), "trades": g1["trades"]}


# ------------------------------------------------------------------------------------------------ grading -------------------
def folds_positive(res: dict[str, Any]) -> int:
    return sum(1 for f in res.get("folds", []) if f["net_r"] > 0)


def grade_pair(res: dict[str, Any], baseline_net: float | None, baseline_kind: str, *, baseline_indeterminate: bool = False) -> dict[str, Any]:
    """PASS iff n>=25 AND net_r>0 AND net_r>baseline AND >=3/4 folds>0 AND net_r>0 under 2x slippage. INDETERMINATE if n<25 or the
    baseline is unavailable. A baseline that is itself INDETERMINATE (1e04-02's alternative branch) is waived."""
    n = res["n"]
    c = {"n_ge_floor": n >= N_FLOOR, "net_gt_0": res["net_r"] > 0, "folds_ge_3": folds_positive(res) >= FOLD_MAJORITY,
         "net_gt_0_at_2x_slip": res["net_r_2x_slip"] > 0}
    if baseline_indeterminate:
        c["beats_baseline"] = True
    elif baseline_net is None:
        c["beats_baseline"] = None
    else:
        c["beats_baseline"] = res["net_r"] > baseline_net
    if n < N_FLOOR or c["beats_baseline"] is None:
        v = "indeterminate"
    else:
        v = "pass" if all(bool(x) for x in c.values()) else "fail"
    return {"verdict": v, "checks": c, "baseline_kind": baseline_kind, "baseline_net_r": baseline_net}


def twin_net(etf: str, results_root: Path = REPO / "comms" / "research") -> float | None:
    """net_r of the own-chart twin on `etf` (1e01-*), read from its landed verdict.json (MEASURED), else None."""
    unit = TWIN_UNIT.get(etf)
    if not unit:
        return None
    for f in sorted(glob.glob(str(results_root / unit / "*" / "verdict.json"))):
        try:
            v = json.loads(Path(f).read_text())
            return float(v["measurement"]["arms"]["A"]["net_r"])
        except (KeyError, ValueError, TypeError, OSError):
            continue
    return None


def unit_verdict(per_pair: dict[str, dict[str, Any]]) -> str:
    vs = [p["grade"]["verdict"] for p in per_pair.values()]
    if "pass" in vs:
        return "pass"
    if vs and all(v == "indeterminate" for v in vs):
        return "indeterminate"
    return "fail"


def artifact_safe(name: str) -> str:
    """A file-name fragment actions/upload-artifact accepts: it refuses " : < > | * ? \\r \\n". "SPY->UPRO" -> "SPY__UPRO"."""
    out = name.replace("->", "__")
    for ch in '":<>|*?\r\n':
        out = out.replace(ch, "_")
    return out


def write_record(out: Path, unit: str, rule_id: str, rule: str, family: str, per_pair: dict[str, dict[str, Any]], extra: dict[str, Any],
                 population: str, verdict_override: str | None = None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    slim = {k: {kk: vv for kk, vv in v["res"].items() if kk != "trades"} | {"grade": v["grade"]} for k, v in per_pair.items()}
    for k, v in per_pair.items():
        # artifact-safe name: actions/upload-artifact refuses '>' (and ':' etc.), so "SPY->UPRO" lands as "SPY__UPRO" (1e06 runs 45496877325.. lost
        # every output to an upload failure on "trades_EEM->EDC.jsonl")
        (out / f"trades_{artifact_safe(k)}.jsonl").write_text("\n".join(json.dumps(t) for t in v["res"]["trades"]) + "\n")
    verdict = verdict_override or unit_verdict(per_pair)
    passed = [k for k, v in per_pair.items() if v["grade"]["verdict"] == "pass"]
    total_n = sum(v["res"]["n"] for v in per_pair.values())
    rec = {"schema_version": 1, "research_unit": unit, "read_state": "measured", "verdict": verdict, "n": total_n,
           "note": (f"{family}: {verdict.upper()}; pairs passed {passed or 'none'} of {len(per_pair)}; "
                    "6-pair family read -> any pass needs the fresh-window confirmation before a proposal"),
           "decision_rule": {"id": rule_id, "rule": rule}, "population": population,
           "measurement": {"family": family, "pairs": slim, **extra}, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    (out / "measurement.json").write_text(json.dumps(rec["measurement"], indent=1, default=str) + "\n")
    return rec


RULES = {
    "RQ-20261123-1e04-01": ("RULE-RQ-20261123-1e04-01", "breakdown",
                            "PASS IFF n>=25 AND net_r>0 AND net_r>own-chart twin net_r on the same ETF AND >=3 of 4 folds>0 AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise (a pass is per pair)"),
    "RQ-20261123-1e04-02": ("RULE-RQ-20261123-1e04-02", "failed_rally",
                            "PASS IFF n>=25 AND net_r>0 AND net_r>1e04-01 net_r on the same pair (or 1e04-01 INDETERMINATE and >=3 of 4 folds>0) AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise"),
    "RQ-20261123-1e04-03": ("RULE-RQ-20261123-1e04-03", "capitulation",
                            "PASS IFF n>=25 AND net_r(3x)>0 AND net_r(3x)>net_r(1x same trigger) AND >=3 of 4 folds>0 AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise"),
}


BASELINE = {"RQ-20261123-1e04-01": "twin", "RQ-20261123-1e04-02": "family:breakdown", "RQ-20261123-1e04-03": "1x",
            "RQ-20261124-1e06-01": "family:breakdown", "RQ-20261124-1e06-02": "1x", "RQ-20261124-1e06-03": "1x", "RQ-20261124-1e06-04": "1x",
            "RQ-20261124-1e06-05": "1x", "RQ-20261124-1e06-06": "flat", "RQ-20261124-1e06-07": "flat"}
#: unit -> (pairs key, 1x-arm pairs key) where it is not the family default; units graded on the POOLED population
PAIRS_KEY = {"RQ-20261124-1e06-04": ("capitulation_holdout", "capitulation_holdout_1x"),
             "RQ-20261124-1e06-05": ("capitulation_fresh", "capitulation_fresh_1x"),
             "RQ-20261124-1e06-06": ("capitulation_1x_fresh", "capitulation_1x_fresh"),
             "RQ-20261124-1e06-07": ("capitulation_bull", "capitulation_bull")}
POOLED = {"RQ-20261124-1e06-04", "RQ-20261124-1e06-05", "RQ-20261124-1e06-06", "RQ-20261124-1e06-07", "RQ-20261124-1e06-08"}
PAIRS_KEY["RQ-20261124-1e06-08"] = ("capitulation_1x_confirm", "capitulation_1x_confirm")
BASELINE["RQ-20261124-1e06-08"] = "flat"
RULES["RQ-20261124-1e06-01"] = ("RULE-RQ-20261124-1e06-01", "breakdown_bear",
                                "PASS IFF n>=25 AND net_r>0 AND net_r>1e04-01 net_r on the same pair (or 1e04-01 INDETERMINATE) AND >=3 of 4 folds>0 AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise (a pass is per pair)")
RULES["RQ-20261124-1e06-02"] = ("RULE-RQ-20261124-1e06-02", "breakdown_bounce",
                                "PASS IFF n>=25 AND net_r(3x)>0 AND net_r(3x)>net_r(1x same trigger) AND >=3 of 4 folds>0 AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-04"] = ("RULE-RQ-20261124-1e06-04", "capitulation_wide",
                                "CONFIRMATION of 1e06-03 on 6 untested 3x sector/mid-cap/REIT ETFs, graded POOLED: PASS IFF pooled n>=25 AND pooled net_r(3x)>0 AND pooled net_r(3x)>pooled net_r(1x same trigger) AND >=3 of 6 pairs net_r>0 AND pooled net_r>0 under 2x slippage; INDETERMINATE if pooled n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-07"] = ("RULE-RQ-20261124-1e06-07", "capitulation_bull",
                                "REGIME ARM, TIMING-GATED: the 1.5-ATR capitulation trigger kept only when the index closes above its SMA200, executed in 1x index ETFs on 8 FRESH indexes (KBE, SMH, EWZ, FXI, EWG, EWU, VGK, IJR), graded POOLED: PASS IFF pooled n>=25 AND pooled net_r>0 AND >=4 of 8 pairs net_r>0 AND pooled net_r>0 under 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws; INDETERMINATE if pooled n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-06"] = ("RULE-RQ-20261124-1e06-06", "capitulation_wide",
                                "TIMING-GATED capitulation trigger executed in 1x index ETFs on 8 FRESH indexes (XLB, XLP, ITB, XME, EFA, EWJ, IYT, IWN), graded POOLED: PASS IFF pooled n>=25 AND pooled net_r>0 AND >=4 of 8 pairs net_r>0 AND pooled net_r>0 under 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws (share_of_draws_ge_actual <= 0.05); INDETERMINATE if pooled n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-08"] = ("RULE-RQ-20261124-1e06-08", "capitulation_wide",
                                "CONFIRMATION of the 1e06-06 pass: the TIMING-GATED capitulation trigger executed in 1x index ETFs on 10 FRESH country indexes (EWC, EWA, EWT, EWY, EWW, EWH, EWS, EWL, EWQ, EWP), graded POOLED: PASS IFF pooled n>=25 AND pooled net_r>0 AND >=5 of 10 pairs net_r>0 AND pooled net_r>0 under 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws (share_of_draws_ge_actual <= 0.05); INDETERMINATE if pooled n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-05"] = ("RULE-RQ-20261124-1e06-05", "capitulation_wide",
                                "TIMING-GATED test of the 1e06-03/-04 capitulation 3x buy on 6 FRESH 3x ETFs (XBI/LABU, KRE/DPST, EEM/EDC, XLI/DUSL, XLU/UTSL, XLY/WANT), graded POOLED: PASS IFF pooled n>=25 AND pooled net_r(3x)>0 AND pooled net_r(3x)>pooled net_r(1x same trigger) AND >=3 of 6 pairs net_r>0 AND pooled net_r>0 under 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws (share_of_draws_ge_actual <= 0.05); INDETERMINATE if pooled n<25; FAIL otherwise")
RULES["RQ-20261124-1e06-03"] = ("RULE-RQ-20261124-1e06-03", "capitulation_wide",
                                "PASS IFF n>=25 AND net_r(3x)>0 AND net_r(3x)>net_r(1x same trigger) AND >=3 of 4 folds>0 AND net_r>0 under 2x slippage; INDETERMINATE if n<25; FAIL otherwise")


def load_frames(pairs, start, end, cache_dir):
    cache: dict[str, pd.DataFrame] = {}
    frames = {}
    for idx_t, etf_t, beta in pairs:
        for t in (idx_t, etf_t):
            if t not in cache:
                cache[t] = fetch_daily(t, start, end, cache_dir)
        f = build_frame(cache[idx_t], cache[etf_t])
        f = f[(f.index >= pd.Timestamp(start)) & (f.index <= pd.Timestamp(end))]
        frames[f"{idx_t}->{etf_t}"] = (f, beta)
    return frames


def run_unit(unit: str, out: Path, start: str, end: str, cache_dir: Path | None) -> dict[str, Any]:
    rule_id, family, rule = RULES[unit]
    cap = HOLD_CAP[family]
    pk, pk1 = PAIRS_KEY.get(unit, (family, "capitulation_1x"))
    frames = load_frames(PAIRS[pk], start, end, cache_dir)
    per: dict[str, dict[str, Any]] = {}
    extra: dict[str, Any] = {"hold_cap_sessions": cap, "slip_bps_per_side": SLIP_BPS_SIDE, "window": [start, end]}
    kind = BASELINE[unit]
    base_by_pair: dict[str, dict[str, Any]] = {}
    if kind.startswith("family:"):  # baseline = another family on the same pair, same harness (1e04-01 for 1e04-02 and 1e06-01)
        bf = kind.split(":", 1)[1]
        for k, (f, beta) in load_frames(PAIRS[bf], start, end, cache_dir).items():
            base_by_pair[k] = run_pair(f, bf, beta, HOLD_CAP[bf])
    arm_b: dict[str, dict[str, Any]] = {}
    if kind == "1x":  # arm B: the same trigger executed in the 1x index ETF
        for k, (f, beta) in load_frames(PAIRS[pk1], start, end, cache_dir).items():
            arm_b[k.split("->")[0]] = run_pair(f, family, beta, cap)
    for k, (f, beta) in frames.items():
        res = run_pair(f, family, beta, cap)
        idx_t, etf_t = k.split("->")
        if kind == "twin":
            g = grade_pair(res, twin_net(etf_t), "own-chart trend twin (1e01-*), landed verdict net_r")
        elif kind == "flat":
            g = grade_pair(res, 0.0, "flat (no trade): the execution is already the 1x index ETF")
        elif kind.startswith("family:"):
            b = base_by_pair[k]
            g = grade_pair(res, b["net_r"], f"{kind[7:]} on the same pair", baseline_indeterminate=b["n"] < N_FLOOR)
            g["baseline_n"] = b["n"]
        else:
            b = arm_b[idx_t]
            g = grade_pair(res, b["net_r"], "same trigger in the 1x index ETF")
            g["baseline_n"] = b["n"]
        per[k] = {"res": res, "grade": g}
    pop = (f"{family}: {len(per)} (index, ETF) pairs, daily bars {start}..{end} (yfinance auto_adjust=False), trades net of "
           f"{SLIP_BPS_SIDE} bps/side slippage on the ETF's own price series; n per pair in measurement.pairs")
    ov = None
    if unit in POOLED:
        net3 = sum(v["res"]["net_r"] for v in per.values())
        net1 = 0.0 if kind == "flat" else sum(arm_b[k.split("->")[0]]["net_r"] for k in per)
        net2x = sum(v["res"]["net_r_2x_slip"] for v in per.values())
        npool = sum(v["res"]["n"] for v in per.values())
        npos = sum(1 for v in per.values() if v["res"]["net_r"] > 0)
        min_pos = POOLED_MIN_POSITIVE.get(unit, POOLED_MIN_POSITIVE_PAIRS)
        chk = {"pooled_n_ge_floor": npool >= N_FLOOR, "pooled_net_gt_0": net3 > 0, "pooled_net_gt_1x": net3 > net1,
               f"pairs_positive_ge_{min_pos}": npos >= min_pos, "pooled_net_gt_0_at_2x_slip": net2x > 0}
        if kind == "flat":                # no separate 1x arm to beat: the execution is the 1x ETF
            chk.pop("pooled_net_gt_1x")
        ov = "indeterminate" if npool < N_FLOOR else ("pass" if all(chk.values()) else "fail")
        draws = np.zeros(200)
        for k_, (f_, beta_) in frames.items():
            draws += np.array(timing_control(f_, family, beta_, cap, per[k_]["res"]["tp_calibration"].get("k_star")))
        extra["timing_control"] = {"draws": 200, "shift_sessions": "40..400 either direction", "mean_net_r": round(float(draws.mean()), 3),
                                   "p95_net_r": round(float(np.percentile(draws, 95)), 3), "actual_net_r": round(net3, 3),
                                   "share_of_draws_ge_actual": round(float((draws >= net3).mean()), 3)}
        if unit in TIMING_GATED:          # the timing control is a RULE clause here, not a diagnostic
            chk["beats_timing_control_95"] = float((draws >= net3).mean()) <= TIMING_GATED[unit]
            ov = "indeterminate" if npool < N_FLOOR else ("pass" if all(chk.values()) else "fail")
            extra["timing_control"]["gating"] = True
        extra["pooled"] = {"n": npool, "net_r_3x": round(net3, 4), "net_r_1x": round(net1, 4), "net_r_2x_slip": round(net2x, 4),
                           "pairs_positive": npos, "checks": chk, "verdict": ov}
    return write_record(out, unit, rule_id, rule, family, per, extra, pop, ov)


# ---------------------------------------------------------------------------------------------------- self-test -------------
def _synthetic(n: int = 900, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0003, 0.012, n)
    r[300:330] -= 0.012  # a drawdown leg
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    ix = pd.bdate_range("2015-01-01", periods=n)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=ix)


def _synthetic_etf(idx: pd.DataFrame, beta: float) -> pd.DataFrame:
    """A daily-reset leveraged ETF built from index close-to-close returns, plus its own intraday noise."""
    ret = idx["close"].pct_change().fillna(0.0).to_numpy()
    c = 50 * np.cumprod(1 + beta * ret)
    o = np.r_[c[0], c[:-1]] * (1 + beta * (idx["open"].to_numpy() / np.r_[idx["close"].iloc[0], idx["close"].to_numpy()[:-1]] - 1))
    h = np.maximum(o, c) * 1.003
    lo = np.minimum(o, c) * 0.997
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=idx.index)


def self_test() -> int:
    ok = True

    def ck(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    idx = _synthetic()
    etf = _synthetic_etf(idx, -3.0)
    f = build_frame(idx, etf)
    for fam in list(SIGNALS):
        base = index_signals(f, fam)
        ck(f"{fam}: produces signals on the synthetic path", len(base) > 0)
        # PARITY: scrambling every ETF column must not move any signal; the signal used by simulate() is the one computed on the index
        g = f.copy()
        for c in ("e_o", "e_h", "e_l", "e_c"):
            g[c] = np.random.default_rng(1).uniform(1, 9, len(g))
        ck(f"{fam}: parity -- signals identical with the ETF columns scrambled", index_signals(g, fam) == base)
        idx_only = f[["i_o", "i_h", "i_l", "i_c"]]
        a = [idx_only[c].to_numpy(float) for c in ("i_o", "i_h", "i_l", "i_c")]
        ck(f"{fam}: parity -- signals identical computed on an index-only frame", SIGNALS[fam](*a) == base)
        # NO LOOKAHEAD: every signal at bar i is reproduced on data truncated at i+1 (entry bar is the only future bar allowed)
        bad = 0
        for s in base[:25]:
            t = f.iloc[: s["i"] + 2]
            bad += s not in [x for x in index_signals(t, fam)]
        ck(f"{fam}: no lookahead -- signals reproduced on data truncated at the signal bar", bad == 0)
    # cost stack on the ETF: slippage cost_r matches 2*slip/1e4*entry/risk and 2x slippage lowers net by exactly that cost
    sigs = index_signals(f, "breakdown")
    s1 = simulate(f, sigs, -3.0, 20, 5.0, 1.5)["trades"]
    s2 = simulate(f, sigs, -3.0, 20, 10.0, 1.5)["trades"]
    ck("cost: trades exist for the cost check", len(s1) > 3 and len(s1) == len(s2))
    ck("cost: cost_r = 2*slip/1e4*entry/risk", all(abs(t["cost_r"] - 2 * 5.0 / 1e4 * t["entry"] / t["risk"]) < 2e-4 for t in s1))
    ck("cost: 2x slippage exactly doubles cost_r and leaves gross_r", all(abs(b["cost_r"] - 2 * a_["cost_r"]) < 3e-4 and a_["gross_r"] == b["gross_r"] for a_, b in zip(s1, s2)))
    ck("cost: net_r = gross_r - cost_r", all(abs(t["net_r"] - (t["gross_r"] - t["cost_r"])) < 2e-4 for t in s1))
    # execution happens in the ETF: entry = ETF open of the bar after the signal
    by_date = {str(d.date()): row for d, row in f.iterrows()}
    ck("exec: entry price is the ETF open of the next session", all(abs(by_date[t["entry_date"]]["e_o"] - t["entry"]) < 1e-3 for t in s1))
    ck("exec: entry date is after the signal date", all(t["entry_date"] > t["signal_date"] for t in s1))
    ck("exec: stop maps THROUGH the ETF (inverse -> stop below entry, risk>0)", all(t["risk"] > 0 for t in s1))
    ck("exec: one position at a time (no overlapping holds)", all(a_["exit_date"] < b["entry_date"] or a_["exit_date"] == b["entry_date"] and False or a_["exit_date"] < b["entry_date"] for a_, b in itertools.pairwise(s1)))
    # a worked mapping: beta -3, idx_entry 100, idx_stop 102 -> ETF stop = entry*(1-0.06)
    mini = pd.DataFrame({"i_o": [100.0] * 4, "i_h": [101.0] * 4, "i_l": [99.0] * 4, "i_c": [100.0] * 4,
                         "e_o": [50.0] * 4, "e_h": [50.4] * 4, "e_l": [49.6] * 4, "e_c": [50.0] * 4},
                        index=pd.bdate_range("2020-01-01", periods=4))
    tr = simulate(mini, [{"i": 0, "stop_idx": 102.0}], -3.0, 3, 5.0, None)["trades"][0]
    ck("mapping: risk = entry*3*(102/100-1) = 3.0", abs(tr["risk"] - 3.0) < 1e-6 and tr["why"] == "timeout")
    # stop touched intraday fills at the stop; gap fills at the open
    gap = mini.copy()
    gap.loc[gap.index[2], ["e_o", "e_l", "e_h", "e_c"]] = [40.0, 39.0, 41.0, 40.0]
    tg = simulate(gap, [{"i": 0, "stop_idx": 102.0}], -3.0, 3, 5.0, None)["trades"][0]
    ck("gap: fills at the gap open, not the stop", tg["why"] == "stop" and tg["exit"] == 40.0)
    # calibration: K* only from the IS slice; fixed-K path bypasses it
    cal = calibrate_tp(s1) if len(s1) >= 10 else {"state": "n/a"}
    ck("tp: calibration never returns 50R", cal.get("k_star") in (None, *GRID))
    # grading
    r = {"n": 30, "net_r": 2.0, "net_r_2x_slip": 1.0, "folds": [{"net_r": 1}, {"net_r": 1}, {"net_r": 1}, {"net_r": -1}]}
    ck("grade: pass when all conditions hold", grade_pair(r, 1.0, "x")["verdict"] == "pass")
    ck("grade: fail when it does not beat the baseline", grade_pair(r, 3.0, "x")["verdict"] == "fail")
    ck("grade: indeterminate when n<25", grade_pair({**r, "n": 10}, 1.0, "x")["verdict"] == "indeterminate")
    ck("grade: indeterminate when the baseline is missing", grade_pair(r, None, "x")["verdict"] == "indeterminate")
    ck("grade: indeterminate-baseline branch waives the baseline", grade_pair(r, 9.0, "x", baseline_indeterminate=True)["verdict"] == "pass")
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", choices=sorted(RULES))
    ap.add_argument("--out")
    ap.add_argument("--start", default=WINDOW_START)
    ap.add_argument("--end", default=WINDOW_END)
    ap.add_argument("--cache-dir")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.unit and a.out):
        ap.error("--unit and --out are required")
    rec = run_unit(a.unit, Path(a.out), a.start, a.end, Path(a.cache_dir) if a.cache_dir else None)
    print(json.dumps({"unit": a.unit, "verdict": rec["verdict"], "n": rec["n"], "note": rec["note"]}))
    for k, v in rec["measurement"]["pairs"].items():
        print(f"  {k:12s} n={v['n']:3d} net_r={v['net_r']:8.3f} 2x={v['net_r_2x_slip']:8.3f} folds={[f['net_r'] for f in v.get('folds', [])]} "
              f"K*={v['tp_calibration'].get('k_star')} -> {v['grade']['verdict']} (base {v['grade']['baseline_net_r']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
