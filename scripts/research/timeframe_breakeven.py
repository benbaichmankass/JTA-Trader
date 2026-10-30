#!/usr/bin/env python3
# wiring: research/queue/RQ-20261018-ef5d-01 (long arm) + RQ-20261018-ef5d-02 (short arm), run.command via research-script-run.yml
"""Cost-aware BREAK-EVEN by horizon: at each bar size and hold, how much move does a trade need to
clear the full fee + slippage + funding stack, and how often does the market deliver it?

WHY THIS EXISTS (programme 07 TIMEFRAMES, lane FRONTIER-TIMEFRAMES-1018; operator 2026-10-18:
"test different time frames ... where the expected move per trade clears the full fee+slippage stack
(fees dominate at short horizons)"). Every strategy unit on a new horizon is a draw from a distribution
whose floor is set by cost, not by skill: at taker cost a 5m breakout pays ~10 bps round trip against a
stop of ~25 bps, so a 1R loss costs 1 R and a 1R win pays 0.6 R before any edge is asked for. The
2026-10-16 idea-family review retired "taker-cost 5m/15m trend/pullback/squeeze" as a configuration
class on exactly that wall (-783 to -878 R, docs/research/idea-family-review-2026-10-16.md § 16).
This instrument measures the wall per (venue/symbol, bar, hold) BEFORE any strategy is tried on it,
so the programme spends its runs on horizons that can pay.

WHAT IT MEASURES (per symbol x bar timeframe x hold-in-bars cell, over the fetched history)
  cost_bps          round-trip cost of a taker-in / taker-out trade held `hold` bars:
                    fee (profile_loader.roundtrip_fee_bps_for, else execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP)
                    + slippage (execution_costs.resolve_cost_policy, venue-aware)
                    + funding magnitude x EXPECTED 8h windows crossed (perps only; hold_hours / 8,
                      the fractional fallback execution_costs.funding_windows_crossed uses when no
                      timestamps are given -- the per-trade exact count needs trade times this
                      instrument does not have).
  stop_bps          the stop a strategy on this bar would carry: atr_mult x ATR(atr_period) / close,
                    per bar (distribution; the median is reported). 2.5 x ATR14 is the harness default.
  cost_r            cost_bps / stop_bps per bar -> the cost of one trade in R. THE number that
                    decides a horizon: cost_r 0.4 means a 1:1 trade needs a 70% win rate.
  wr_breakeven_rr1  (1 + cost_r) / 2       win rate needed at a 1R target with a 1R stop
  wr_breakeven_rr2  (1 + cost_r) / 3       ... at a 2R target
  mv_bps            |log(close[t+hold] / close[t])| in bps over every bar t (overlapping): what the
                    market moved over that hold, irrespective of direction or entry skill.
  p_mv_ge_cost      P(mv_bps >= cost_bps)          the move at least covers the round trip
  p_mv_ge_2cost     P(mv_bps >= 2 x cost_bps)     the move is twice the round trip
  mv_median_over_cost   median(mv_bps) / cost_bps
  Report-only arms per cell (gate nothing): maker_cost_bps (fee 0, same slippage/funding: the
  post-only bound), prop_cost_bps for ETH/SOL (Breakout/DXtrade: 8 bps commission + 3 bps slippage
  + 0.033 %/day swap x hold days, the prop_ev_sim.py CostConfig numbers).

CELL GRADE (the thresholds are the UNIT's, passed as flags; defaults here are documentation)
  viable    median cost_r <= --viable-cost-r (0.10) AND p_mv_ge_2cost >= --viable-coverage (0.50)
  marginal  not viable AND median cost_r <= --marginal-cost-r (0.25)
  dead      otherwise -- the cost wall (a strategy here needs > 25 % of its R just to pay the venue)

ARM VERDICT (verdict.json, the script_run.py contract)
  pass           >= 1 (bar, hold) cell is `viable` on at least half of the arm's MEASURED core symbols
                 (the crypto perps the books trade); the arm has somewhere to search.
  fail           no cell is viable on any measured symbol: the arm is dead at taker cost; everything
                 on it waits on a cost change (maker route, lower fee tier), not on a better entry.
  indeterminate  fewer than half of the declared (symbol, bar) frames fetched or measured, or every
                 frame is shorter than --min-bars: coverage of the grid is too thin to read.
  producer_failed (read_state) when nothing at all could be measured.

HORIZON GRIDS (registered designs; anything else is a smoke run and is labelled so)
  short   bars 1m 5m 15m 30m 1h; holds 1 2 3 6 12 24 48 bars  -> 1 minute .. 2 days
  long    bars 4h 1d 1w;          holds 1 2 3 5 10 20 30 bars  -> 4 hours .. 30 weeks

DATA. Crypto perps from Binance Vision (USD-M futures klines, keyless; the Bybit linear series is
PROXIED by Binance USD-M, prices track within a few bps -- stated in the output). Equities/ETFs and
futures proxies from Yahoo (yfinance): 1d uncapped, 1h ~730 d, 5m/15m ~60 d -- a frame whose window is
shorter than --min-bars x bar is reported `thin_window` and excluded from the verdict denominator, never
silently graded. 4h and 1w equity frames are RESAMPLED from the 1h / 1d fetch (label right, closed right,
the harness convention). Every frame reports its data_start / data_end / n_bars.

Tier-1 research tooling: fetches public candles, computes over them, writes only under --out. No live
path, no config write, no order. Nothing here proposes a leg; a `viable` cell is where the programme's
strategy units are allowed to look, nothing more.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts")]

# ---- the registered universes and grids ------------------------------------------------
#: Crypto perps the books trade (config/accounts.yaml rosters + symbols, read 2026-10-18): Bybit linear.
CRYPTO_CORE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT")
#: Alpaca equities/ETFs on a live-mode roster (alpaca_live / alpaca_paper / alpaca_portfolio / options paper).
EQUITY = ("SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "IEF", "USO", "GDX", "TQQQ", "QLD", "SPYM", "IAUM", "SCHA")
#: IBKR micro futures on ib_paper (Yahoo continuous-contract proxies ES=F / GC=F / HG=F via the fetcher's map).
FUTURES = ("MES", "MGC", "MHG")

GRIDS: dict[str, dict[str, Any]] = {
    "short": {"bars": ("1m", "5m", "15m", "30m", "1h"), "holds": (1, 2, 3, 6, 12, 24, 48)},
    "long": {"bars": ("4h", "1d", "1w"), "holds": (1, 2, 3, 5, 10, 20, 30)},
}
TF_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5, "1h": 1.0, "4h": 4.0, "1d": 24.0, "1w": 168.0}
#: Bybit-style interval codes scripts/ops/fetch_backtest_candles.py speaks, per bar.
BINANCE_CODE = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
#: Yahoo serves 5m/15m/1h/1d; 30m, 4h and 1w are RESAMPLED from the finer fetch.
YAHOO_FETCH = {"5m": ("5", None), "15m": ("15", None), "30m": ("15", "30min"), "1h": ("60", None),
               "4h": ("60", "4h"), "1d": ("D", None), "1w": ("D", "1W")}
#: Breakout / DXtrade prop cost (scripts/research/prop_ev_sim.py CostConfig; report-only).
PROP_COMMISSION_BPS_RT, PROP_SLIPPAGE_BPS_RT, PROP_SWAP_PER_DAY = 8.0, 3.0, 0.00033
PROP_SYMBOLS = ("ETHUSDT", "SOLUSDT")
GRADES = ("viable", "marginal", "dead")


# ---- cost stack ------------------------------------------------------------------------
def cost_stack(symbol: str) -> dict[str, float | bool]:
    """fee / slippage / funding-per-window for `symbol` through the ONE cost model."""
    from src.runtime import execution_costs as ec
    fee = None
    try:
        from src.core.profile_loader import roundtrip_fee_bps_for
        fee = roundtrip_fee_bps_for(symbol)
    except Exception as exc:  # allow-silent: falls back to the single-owner default fee and says so (fee_resolved false + a stderr warning)  # noqa: BLE001
        fee = None
        _warn(f"{symbol}: profile_loader fee lookup failed ({exc}); default {ec.DEFAULT_FEE_BPS_ROUNDTRIP} bps")
    slip, fund = ec.resolve_cost_policy(symbol)
    return {"fee_bps_roundtrip": ec.DEFAULT_FEE_BPS_ROUNDTRIP if fee is None else float(fee),
            "fee_resolved": fee is not None,
            "slippage_bps_roundtrip": float(slip), "funding_bps_per_window": float(fund),
            "is_perp": bool(ec.is_perp(symbol)), "funding_window_hours": float(ec.FUNDING_WINDOW_HOURS)}


def cost_bps_for_hold(stack: dict[str, Any], hold_hours: float, *, fee_override: float | None = None) -> float:
    fee = stack["fee_bps_roundtrip"] if fee_override is None else fee_override
    windows = (hold_hours / stack["funding_window_hours"]) if stack["is_perp"] else 0.0
    return float(fee + stack["slippage_bps_roundtrip"] + stack["funding_bps_per_window"] * windows)


def prop_cost_bps(hold_hours: float) -> float:
    return PROP_COMMISSION_BPS_RT + PROP_SLIPPAGE_BPS_RT + PROP_SWAP_PER_DAY * 1e4 * (hold_hours / 24.0)


# ---- the arithmetic (pure numpy over one candle frame) ---------------------------------
def wilder_atr(high, low, close, period: int):
    import numpy as np
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = np.full(len(tr), np.nan)
    if len(tr) < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    a = 1.0 / period
    for i in range(period, len(tr)):
        atr[i] = atr[i - 1] + a * (tr[i] - atr[i - 1])
    return atr


def measure_frame(df, *, symbol: str, bar: str, holds: tuple[int, ...], stack: dict[str, Any],
                  atr_mult: float, atr_period: int, viable_cost_r: float, marginal_cost_r: float,
                  viable_coverage: float, min_bars: int) -> dict[str, Any]:
    """Every hold cell for one (symbol, bar) frame. Pure: no I/O."""
    import numpy as np
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n_bars = len(close)
    window_days = (float((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds()) / 86400.0
                   if n_bars > 1 else 0.0)
    frame: dict[str, Any] = {"symbol": symbol, "bar": bar, "n_bars": int(n_bars),
                             "data_start": str(df["timestamp"].iloc[0]) if n_bars else None,
                             "data_end": str(df["timestamp"].iloc[-1]) if n_bars else None,
                             "window_days": round(window_days, 1),
                             # Yahoo clamps intraday history (~60 d at 5m/15m, ~730 d at 1h): a short frame is
                             # measured but FLAGGED, so a 60-day read is never mistaken for a 5-year one.
                             "short_window": bool(window_days < 365.0),
                             "cost_stack": dict(stack), "cells": []}
    if n_bars < min_bars:
        frame["state"] = "thin_window"
        frame["why"] = f"{n_bars} bars < --min-bars {min_bars}: not graded"
        return frame
    atr = wilder_atr(high, low, close, atr_period)
    stop_frac = atr_mult * atr / close                         # per bar, as a fraction of price
    ok = np.isfinite(stop_frac) & (stop_frac > 0)
    stop_bps_med = float(np.median(stop_frac[ok]) * 1e4) if ok.any() else float("nan")
    logc = np.log(close)
    tf_h = TF_HOURS[bar]
    for h in holds:
        if h >= n_bars:
            frame["cells"].append({"hold_bars": h, "state": "not_measured", "why": f"hold {h} >= n_bars {n_bars}"})
            continue
        hold_h = h * tf_h
        cost = cost_bps_for_hold(stack, hold_h)
        mv = np.abs(logc[h:] - logc[:-h]) * 1e4                 # bps, overlapping windows
        # cost in R per bar where a stop exists; the trade entered at t pays cost against stop_t
        cr = (cost / 1e4) / stop_frac[ok]
        cr_med = float(np.median(cr))
        p1 = float(np.mean(mv >= cost))
        p2 = float(np.mean(mv >= 2.0 * cost))
        grade = ("viable" if (cr_med <= viable_cost_r and p2 >= viable_coverage)
                 else "marginal" if cr_med <= marginal_cost_r else "dead")
        cell = {
            "hold_bars": h, "hold_hours": round(hold_h, 4), "state": "measured",
            "cost_bps": round(cost, 3),
            "maker_cost_bps": round(cost_bps_for_hold(stack, hold_h, fee_override=0.0), 3),
            "prop_cost_bps": round(prop_cost_bps(hold_h), 3) if symbol in PROP_SYMBOLS else None,
            "stop_bps_median": round(stop_bps_med, 2),
            "cost_r_median": round(cr_med, 4), "cost_r_p75": round(float(np.percentile(cr, 75)), 4),
            "wr_breakeven_rr1": round((1.0 + cr_med) / 2.0, 4), "wr_breakeven_rr2": round((1.0 + cr_med) / 3.0, 4),
            "mv_bps_median": round(float(np.median(mv)), 2), "mv_bps_p90": round(float(np.percentile(mv, 90)), 2),
            "mv_median_over_cost": round(float(np.median(mv)) / cost, 3) if cost > 0 else None,
            "p_mv_ge_cost": round(p1, 4), "p_mv_ge_2cost": round(p2, 4),
            "ret_sd_bps": round(float(np.std(logc[h:] - logc[:-h]) * 1e4), 2),
            "n_windows": len(mv), "grade": grade,
        }
        frame["cells"].append(cell)
    frame["state"] = "measured"
    return frame


def grade_arm(frames: list[dict[str, Any]], *, declared: int, core: tuple[str, ...]) -> dict[str, Any]:
    """The arm verdict from the frame table. Pure."""
    measured = [f for f in frames if f.get("state") == "measured"]
    if declared and len(measured) * 2 < declared:
        return {"verdict": "indeterminate", "read_state": "measured" if measured else "producer_failed",
                "why": f"{len(measured)} of {declared} declared (symbol, bar) frames measured (< half): grid coverage too thin"}
    core_syms = sorted({f["symbol"] for f in measured if f["symbol"] in core})
    viable_by_cell: dict[tuple[str, int], set[str]] = {}
    any_viable = False
    for f in measured:
        for c in f["cells"]:
            if c.get("grade") == "viable":
                any_viable = True
                viable_by_cell.setdefault((f["bar"], c["hold_bars"]), set()).add(f["symbol"])
    if not core_syms:
        # No core symbol measured at all: the verdict cannot rest on the periphery.
        return {"verdict": "indeterminate", "read_state": "measured",
                "why": "no core (crypto perp) symbol measured; the arm verdict is defined on the core"}
    need = math.ceil(len(core_syms) / 2)
    hits = {f"{b}x{h}": sorted(s & set(core_syms)) for (b, h), s in viable_by_cell.items()
            if len(s & set(core_syms)) >= need}
    if hits:
        return {"verdict": "pass", "read_state": "measured", "core_symbols": core_syms, "need": need,
                "viable_cells_on_core": hits,
                "why": f"{len(hits)} (bar x hold) cell(s) viable on >= {need} of {len(core_syms)} core symbols"}
    if any_viable:
        return {"verdict": "indeterminate", "read_state": "measured", "core_symbols": core_syms, "need": need,
                "why": "viable cells exist but on fewer than half the core symbols: no breadth"}
    return {"verdict": "fail", "read_state": "measured", "core_symbols": core_syms,
            "why": "no (bar x hold) cell is viable on any measured symbol: the cost wall holds across the arm"}


def frontier(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Per symbol: the shortest viable (bar, hold) by hold_hours -- the programme's search floor."""
    out: dict[str, Any] = {}
    for f in frames:
        if f.get("state") != "measured":
            continue
        for c in f["cells"]:
            if c.get("grade") != "viable":
                continue
            cur = out.get(f["symbol"])
            if cur is None or c["hold_hours"] < cur["hold_hours"]:
                out[f["symbol"]] = {"bar": f["bar"], "hold_bars": c["hold_bars"], "hold_hours": c["hold_hours"],
                                    "cost_r_median": c.get("cost_r_median"), "p_mv_ge_2cost": c.get("p_mv_ge_2cost")}
    return out


# ---- data ------------------------------------------------------------------------------
def _warn(msg: str) -> None:
    print(f"[timeframe_breakeven] {msg}", file=sys.stderr)


def _resample(df, rule: str):
    r = rule.strip().lower()
    if r.endswith("m") and not r.endswith("min"):
        rule = r[:-1] + "min"
    out = (df.set_index("timestamp").resample(rule, label="right", closed="right")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
             .dropna(subset=["open", "high", "low", "close"]).reset_index())
    return out


def fetch_frame(symbol: str, bar: str, *, days: int, data_dir: Path) -> Path:
    """Fetch one (symbol, bar) CSV through the ONE fetcher. Returns the CSV path (resampling is the caller's)."""
    fetcher = REPO / "scripts/ops/fetch_backtest_candles.py"
    if symbol.upper().endswith("USDT"):
        code, src = BINANCE_CODE[bar], "binance_vision"
    else:
        code, _ = YAHOO_FETCH[bar]
        src = "yfinance"
    out = data_dir / f"{symbol}_{code}.csv"
    if not out.exists():
        subprocess.run([sys.executable, str(fetcher), "--symbol", symbol, "--interval", code, "--days", str(days),
                        "--output", str(out), "--source", src], check=True, cwd=str(REPO))
    return out


def load_frame(csv: Path, symbol: str, bar: str):
    from candle_io import load_candles
    df = load_candles(str(csv))
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if not symbol.upper().endswith("USDT"):
        _, rule = YAHOO_FETCH[bar]
        if rule:
            df = _resample(df, rule)
    return df


# ---- main --------------------------------------------------------------------------------
def run(a: argparse.Namespace) -> dict[str, Any]:
    import pandas as pd  # noqa: F401  (candle_io needs it; fail early, loudly)
    grid = GRIDS[a.arm]
    bars = tuple(a.bars.split(",")) if a.bars else grid["bars"]
    holds = tuple(int(x) for x in a.holds.split(",")) if a.holds else grid["holds"]
    registered = (set(bars) == set(grid["bars"]) and tuple(holds) == tuple(grid["holds"]) and not a.data_csv)
    symbols = tuple(a.symbols.split(",")) if a.symbols else (CRYPTO_CORE + EQUITY + FUTURES)
    data_dir = Path(a.data_dir) if a.data_dir else Path(tempfile.mkdtemp(prefix="tf_breakeven_"))
    data_dir.mkdir(parents=True, exist_ok=True)
    given = dict(kv.split("=", 1) for kv in (a.data_csv or []))
    frames: list[dict[str, Any]] = []
    declared = 0
    inputs: list[str] = []
    for sym in symbols:
        stack = cost_stack(sym)
        for bar in bars:
            declared += 1
            key = f"{sym}:{bar}"
            try:
                if key in given:
                    csv = Path(given[key])
                elif a.no_fetch:
                    raise FileNotFoundError(f"--no-fetch and no --data-csv for {key}")
                else:
                    days = a.days_crypto if sym.upper().endswith("USDT") else a.days_equity
                    if bar in ("1m",) and sym.upper().endswith("USDT"):
                        days = min(days, a.days_1m)
                    csv = fetch_frame(sym, bar, days=days, data_dir=data_dir)
                df = load_frame(csv, sym, bar)
                try:
                    inputs.append(str(csv.resolve().relative_to(REPO.resolve())))
                except ValueError:
                    pass
                fr = measure_frame(df, symbol=sym, bar=bar, holds=holds, stack=stack, atr_mult=a.atr_mult,
                                   atr_period=a.atr_period, viable_cost_r=a.viable_cost_r,
                                   marginal_cost_r=a.marginal_cost_r, viable_coverage=a.viable_coverage,
                                   min_bars=a.min_bars)
                fr["source"] = "binance_vision (USD-M futures, PROXY for Bybit linear)" if sym.upper().endswith("USDT") else "yfinance"
            except Exception as exc:  # allow-silent: a failed frame lands as state fetch_failed with the exception text; the denominator stays whole  # noqa: BLE001
                fr = {"symbol": sym, "bar": bar, "state": "fetch_failed", "why": f"{type(exc).__name__}: {exc}",
                      "cost_stack": stack, "cells": []}
                _warn(f"{key}: {fr['why']}")
            frames.append(fr)
    g = grade_arm(frames, declared=declared, core=CRYPTO_CORE)
    measured = [f for f in frames if f.get("state") == "measured"]
    n_cells = sum(1 for f in measured for c in f["cells"] if c.get("state") == "measured")
    thresholds = {"viable_cost_r": a.viable_cost_r, "marginal_cost_r": a.marginal_cost_r,
                  "viable_coverage": a.viable_coverage, "atr_mult": a.atr_mult, "atr_period": a.atr_period,
                  "min_bars": a.min_bars}
    note = (f"{g['verdict'].upper()}: {g['why']}. "
            f"{len(measured)}/{declared} frames measured; {n_cells} (symbol, bar, hold) cells graded. "
            + ("Registered grid." if registered else "SMOKE RUN: grid, holds or data overridden; not the registered design. ")
            + " Crypto costs: Bybit linear via Binance USD-M proxy candles; equity fee 0 (Alpaca) + 5 bps slippage; "
              "funding charged as expected 8h windows x hold. maker_cost_bps / prop_cost_bps are report-only.")
    verdict = {
        "verdict": g["verdict"], "read_state": g["read_state"],
        "population": (f"arm={a.arm}; symbols={','.join(symbols)}; bars={','.join(bars)}; holds={list(holds)}; "
                       f"{len(measured)} of {declared} frames measured; overlapping |log return| windows per cell"),
        "n": n_cells if n_cells else None,
        "note": note,
        "decision_rule_id": a.rule_id,
        "data_inputs": sorted(set(inputs)),
        "measurement": {"arm": a.arm, "registered_grid": registered, "thresholds": thresholds, "grade": g,
                        "frontier": frontier(frames), "frames": frames},
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
    _write_table(out / "SUMMARY.md", verdict)
    return verdict


def _write_table(path: Path, v: dict[str, Any]) -> None:
    m = v["measurement"]
    lines = [f"# Break-even by horizon -- arm `{m['arm']}` -- {v['verdict']}", "", v["note"], "",
             "| symbol | bar | hold | hours | cost bps | stop bps (med) | cost R (med) | WR* 1:1 | P(mv>=2c) | mv med bps | grade |",
             "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
    for f in m["frames"]:
        if f.get("state") != "measured":
            lines.append(f"| {f['symbol']} | {f['bar']} | - | - | - | - | - | - | - | - | {f.get('state')}: {f.get('why', '')} |")
            continue
        for c in f["cells"]:
            if c.get("state") != "measured":
                continue
            lines.append(f"| {f['symbol']} | {f['bar']} | {c['hold_bars']} | {c['hold_hours']:.2f} | {c['cost_bps']:.1f} | "
                         f"{c['stop_bps_median']:.1f} | {c['cost_r_median']:.3f} | {c['wr_breakeven_rr1']:.3f} | "
                         f"{c['p_mv_ge_2cost']:.2f} | {c['mv_bps_median']:.1f} | {c['grade']} |")
    lines += ["", "## Frontier (shortest viable hold per symbol)", ""]
    for s, fr in sorted(m["frontier"].items()):
        lines.append(f"- {s}: {fr['bar']} x {fr['hold_bars']} bars ({fr['hold_hours']:.2f} h), cost R {fr['cost_r_median']}")
    if not m["frontier"]:
        lines.append("- none viable")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _self_test() -> int:
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(7)
    # A 1m GBM-ish series: ~0.05 % per-bar vol; stops of 2.5 ATR are ~ 25 bps, so taker cost (~10.5 bps) is a
    # LARGE share of R at short holds -- the cost wall the instrument exists to show.
    n = 20000
    r = rng.normal(0, 5e-4, n)
    close = 100.0 * np.exp(np.cumsum(r))
    high = close * (1 + np.abs(rng.normal(0, 3e-4, n)))
    low = close * (1 - np.abs(rng.normal(0, 3e-4, n)))
    ts = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "open": close, "high": high, "low": low, "close": close, "volume": 1.0})
    stack = cost_stack("BTCUSDT")
    assert stack["is_perp"] and stack["slippage_bps_roundtrip"] == 3.0, stack
    # funding: a perp pays per expected window; a non-perp never does
    assert cost_bps_for_hold(stack, 16.0) > cost_bps_for_hold(stack, 1.0)
    eq = cost_stack("SPY")
    assert eq["fee_bps_roundtrip"] == 0.0 and not eq["is_perp"]
    assert cost_bps_for_hold(eq, 240.0) == cost_bps_for_hold(eq, 1.0) == 5.0
    kw = {"holds": (1, 6, 48), "stack": stack, "atr_mult": 2.5, "atr_period": 14, "viable_cost_r": 0.10,
          "marginal_cost_r": 0.25, "viable_coverage": 0.5, "min_bars": 500}
    fr = measure_frame(df, symbol="BTCUSDT", bar="1m", **kw)
    assert fr["state"] == "measured" and len(fr["cells"]) == 3
    c1, c6, c48 = fr["cells"]
    # cost in R does not depend on the hold (same stop), except the funding term, which grows with it
    assert c48["cost_r_median"] >= c6["cost_r_median"] >= c1["cost_r_median"]
    # the market's move grows with the hold while cost barely does: coverage rises with the hold
    assert c48["p_mv_ge_2cost"] > c1["p_mv_ge_2cost"], (c1, c48)
    # on a 25 bps stop a ~10 bps round trip is the wall: cost_r well above 0.25 -> dead
    assert c1["grade"] == "dead" and c1["cost_r_median"] > 0.25, c1
    # a zero-cost planted arm: everything is viable (positive control of the grade)
    free = dict(stack, fee_bps_roundtrip=0.0, slippage_bps_roundtrip=0.0, funding_bps_per_window=0.0)
    fr0 = measure_frame(df, symbol="BTCUSDT", bar="1m", **{**kw, "stack": free})
    assert all(c["grade"] == "viable" and c["cost_r_median"] == 0.0 for c in fr0["cells"]), fr0["cells"]
    # a daily frame of the same path: 1440x the per-bar vol, so the stop is ~ 38x wider -> viable
    d = _resample(df, "1D")
    frd = measure_frame(d, symbol="BTCUSDT", bar="1d", **{**kw, "min_bars": 5, "holds": (1, 2)})
    assert frd["state"] == "measured" and frd["cells"][0]["cost_r_median"] < c1["cost_r_median"]
    # thin window is a STATE, not a grade
    thin = measure_frame(df.iloc[:100], symbol="BTCUSDT", bar="1m", **kw)
    assert thin["state"] == "thin_window" and thin["cells"] == []
    # arm grading: every branch reachable
    core = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    dead_fr = {"symbol": "BTCUSDT", "bar": "1m", "state": "measured", "cells": [{"hold_bars": 1, "hold_hours": 1 / 60, "grade": "dead"}]}
    via_fr = {"symbol": "BTCUSDT", "bar": "1d", "state": "measured", "cells": [{"hold_bars": 5, "hold_hours": 120.0, "grade": "viable"}]}
    via_eth = {**via_fr, "symbol": "ETHUSDT"}
    assert grade_arm([dead_fr], declared=1, core=core)["verdict"] == "fail"
    assert grade_arm([via_fr], declared=1, core=core)["verdict"] == "pass"          # 1 of 1 core measured
    # 1 viable of 3 measured core symbols is below the ceil(3/2)=2 breadth floor -> no breadth
    assert grade_arm([via_fr, {**dead_fr, "symbol": "ETHUSDT"}, {**dead_fr, "symbol": "SOLUSDT"}],
                     declared=3, core=core)["verdict"] == "indeterminate"
    assert grade_arm([via_fr, via_eth, {**dead_fr, "symbol": "SOLUSDT"}], declared=3, core=core)["verdict"] == "pass"  # 2 of 3
    assert grade_arm([via_fr], declared=4, core=core)["verdict"] == "indeterminate"  # 1 of 4 frames measured
    assert grade_arm([{**dead_fr, "state": "fetch_failed", "cells": []}], declared=1, core=core)["read_state"] == "producer_failed"
    assert grade_arm([{**via_fr, "symbol": "SPY"}], declared=1, core=core)["verdict"] == "indeterminate"  # no core
    fro = frontier([via_fr, {**via_fr, "bar": "4h", "cells": [{"hold_bars": 3, "hold_hours": 12.0, "grade": "viable", "cost_r_median": 0.05, "p_mv_ge_2cost": 0.6}]}])
    assert fro["BTCUSDT"]["bar"] == "4h" and fro["BTCUSDT"]["hold_bars"] == 3, fro
    # end-to-end: a smoke run writes the contract
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "BTCUSDT_1.csv"
        df.to_csv(csv, index=False)
        ns = argparse.Namespace(arm="short", bars="1m", holds="1,6", symbols="BTCUSDT", data_dir=td, data_csv=[f"BTCUSDT:1m={csv}"],
                                no_fetch=True, days_crypto=10, days_equity=10, days_1m=10, atr_mult=2.5, atr_period=14,
                                viable_cost_r=0.10, marginal_cost_r=0.25, viable_coverage=0.5, min_bars=500,
                                out=str(Path(td) / "out"), rule_id="RULE-SELFTEST")
        v = run(ns)
        assert v["verdict"] == "fail" and v["read_state"] == "measured" and v["n"] == 2, v["note"]
        assert "SMOKE RUN" in v["note"] and v["decision_rule_id"] == "RULE-SELFTEST"
        assert (Path(td) / "out" / "verdict.json").is_file() and (Path(td) / "out" / "SUMMARY.md").is_file()
    print("timeframe_breakeven self-test: ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=sorted(GRIDS), default="short")
    ap.add_argument("--bars", default=None, help="override the arm's bar grid (comma list) -- a SMOKE run")
    ap.add_argument("--holds", default=None, help="override the arm's hold grid (comma list of bars) -- a SMOKE run")
    ap.add_argument("--symbols", default=None, help="override the universe (comma list); default = the books' symbols")
    ap.add_argument("--data-dir", default=None, help="where fetched CSVs go (default: a temp dir)")
    ap.add_argument("--data-csv", action="append", default=None, metavar="SYM:BAR=PATH", help="use this CSV for a frame (tests)")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--days-crypto", type=int, default=1825)
    ap.add_argument("--days-1m", type=int, default=730, help="cap for 1m crypto frames (3M bars / 5 y is too heavy)")
    ap.add_argument("--days-equity", type=int, default=7300, help="Yahoo 1d is uncapped; intraday is clamped by the venue")
    ap.add_argument("--atr-mult", type=float, default=2.5, help="stop basis in ATRs (the harness default)")
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--viable-cost-r", type=float, default=0.10)
    ap.add_argument("--marginal-cost-r", type=float, default=0.25)
    ap.add_argument("--viable-coverage", type=float, default=0.50)
    ap.add_argument("--min-bars", type=int, default=500, help="a frame shorter than this is `thin_window`, not graded")
    ap.add_argument("--rule-id", default=None, help="the unit's decision_rule.id, stamped on the verdict")
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    v = run(a)
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
