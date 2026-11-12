#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-a7e8-01 (FRONTIER-STATIC-MARKETS, lane ML standing part 3, 2026-11-12), run.command via research-script-run.yml
"""Stage-0 for INTERNAL-BAR-STRENGTH (IBS) daily mean reversion on liquid ETFs, net of the full cost stack.

WHY THIS EXISTS (row FRONTIER-STATIC-MARKETS, operator 2026-11-11: "frontier research on strategies or MLs that
are geared towards profiting from static markets"). The repo's one cost-complete mean-reversion harness is the
`fade` family (a Donchian-pierce fade), and range-gated fade has FAILED nine registered units on crypto perps
(RQ-20261022-4b82-04, RQ-20261023-1d5c-12/-13, RQ-20261026-f679-01, RQ-20261028-2a2e-05/-08, ...). IBS is a
DIFFERENT mechanism with primary outside evidence on equity ETFs (Pandey & Joshi, arXiv:2306.12434, primary;
Pagonidis 2013 "The IBS Effect", secondary citation): a close near the day's low predicts a positive next-day
close-to-close return. No harness in the repo measures it, so this is the instrument.

THE RULE (every parameter is a flag; the unit fixes them BEFORE the run)
  IBS_t = (close_t - low_t) / (high_t - low_t)   (a bar with high == low emits no signal)
  long  signal at close t iff IBS_t < --ibs-lo     (and close_t > SMA(--sma) when --trend-filter)
  short signal at close t iff IBS_t > --ibs-hi
  entry  at close_t (a market-on-close fill; the slippage term prices it)
  stop   entry -/+ --stop-atr x ATR(--atr-period)_t  (ATR = mean true range over the bars ending at t; no look-ahead)
  1R     = that stop distance
  exit   the FIRST of, on bars j = t+1 .. t+--max-hold:
           open_j through the stop  -> exit at open_j (gap; can be worse than -1R)
           low_j/high_j touches stop -> exit at the stop
           long: close_j > high_{j-1}; short: close_j < low_{j-1}   -> exit at close_j (the classic IBS exit)
           j == t + --max-hold                                        -> exit at close_j
  one position per symbol; the next signal must close AFTER the exit bar.
  net_r  = side x (exit - entry) / 1R  -  (fee + slippage round-trip bps) x entry / 1R
           fee   = execution_costs.resolve_fee_bps_roundtrip(symbol)   (venue fee; never a zero default by omission)
           slip  = execution_costs.resolve_cost_policy(symbol)          (venue default; 5 bps round trip for ETFs)
           funding = 0 for a non-perp (the same resolver); an ETF pays none.

ARMS  `--arm LABEL=key=value;key=value` over {side: long|short, ibs_lo, ibs_hi, trend_filter: 0|1, max_hold,
      stop_atr}. A CONTROL arm with ibs_lo=1.01 enters long EVERY day under the same exits: it carries the ETFs'
      drift, so a candidate that beats it by --delta-r-per-trade is not just "long equities".

GRADES  identical to harness_stage0.py (imported, not copied): per cell grade_cell, pooled calendar folds,
        breadth over powered cells, grade_arm with the baseline materiality clause, Holm p reported.

DATA  daily OHLC via scripts/ops/fetch_backtest_candles.py (yfinance, unadjusted). Dividends are NOT added back
      (unadjusted closes drop on ex-dates; this biases LONG arms DOWN slightly). A bar whose close moves > 25 %
      from the previous close is treated as a split/data fault: the symbol's series is cut there and the cut is
      RECORDED in the cell, never silently dropped.

Tier-1 research tooling: public candles, writes only under --out. No live path, no config, no roster. A PASS is a
LEAD for one confirmation unit (symbol-disjoint basket or later window), never a roster act.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

DEFAULT_ARM = {"side": "long", "ibs_lo": 0.2, "ibs_hi": 0.8, "trend_filter": 0, "max_hold": 3, "stop_atr": 2.0}
SPLIT_JUMP = 0.25


def _f(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def parse_arm(spec: str) -> tuple[str, dict[str, Any]]:
    label, _, body = spec.partition("=")
    cfg = dict(DEFAULT_ARM)
    for tok in filter(None, (t.strip() for t in body.split(";"))):
        k, _, v = tok.partition("=")
        if k not in DEFAULT_ARM:
            raise ValueError(f"arm {label}: unknown key {k!r}; known {sorted(DEFAULT_ARM)}")
        cfg[k] = _f(v)
    if cfg["side"] not in ("long", "short"):
        raise ValueError(f"arm {label}: side must be long|short")
    return label, cfg


def load_bars(csv: Path, start: str | None, end: str | None) -> tuple[list[dict[str, Any]], str | None]:
    import pandas as pd
    df = pd.read_csv(csv)
    ts = df["timestamp"]
    df["ts"] = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) else pd.to_datetime(ts, utc=True)
    df = df.sort_values("ts").dropna(subset=["open", "high", "low", "close"])
    if start:
        df = df[df["ts"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df["ts"] <= pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    bars = [{"ts": r.ts, "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close)}
            for r in df.itertuples()]
    cut = None
    for i in range(1, len(bars)):
        if abs(bars[i]["c"] / bars[i - 1]["c"] - 1.0) > SPLIT_JUMP:
            cut = f"series cut at {bars[i]['ts']} (close jump > {SPLIT_JUMP:.0%}: split or data fault)"
            bars = bars[:i]
            break
    return bars, cut


def simulate(bars: list[dict[str, Any]], arm: dict[str, Any], *, cost_bps: float, atr_period: int, sma: int) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    n = len(bars)
    tr = [None] + [max(bars[i]["h"], bars[i - 1]["c"]) - min(bars[i]["l"], bars[i - 1]["c"]) for i in range(1, n)]
    side = 1 if arm["side"] == "long" else -1
    t = max(atr_period, sma if arm["trend_filter"] else 0)
    while t < n - 1:
        b = bars[t]
        rng = b["h"] - b["l"]
        sig = False
        if rng > 0:
            ibs = (b["c"] - b["l"]) / rng
            if side == 1 and ibs < arm["ibs_lo"]:
                sig = True
                if arm["trend_filter"]:
                    sig = b["c"] > sum(x["c"] for x in bars[t - sma + 1:t + 1]) / sma
            elif side == -1 and ibs > arm["ibs_hi"]:
                sig = True
        if not sig:
            t += 1
            continue
        atr = sum(tr[t - atr_period + 1:t + 1]) / atr_period
        risk = arm["stop_atr"] * atr
        if risk <= 0:
            t += 1
            continue
        entry = b["c"]
        stop = entry - side * risk
        exit_px = None
        j = t
        why = None
        for j in range(t + 1, min(n, t + 1 + int(arm["max_hold"]))):
            x, prev = bars[j], bars[j - 1]
            if (side == 1 and x["o"] <= stop) or (side == -1 and x["o"] >= stop):
                exit_px, why = x["o"], "stop_gap"
                break
            if (side == 1 and x["l"] <= stop) or (side == -1 and x["h"] >= stop):
                exit_px, why = stop, "stop"
                break
            if (side == 1 and x["c"] > prev["h"]) or (side == -1 and x["c"] < prev["l"]):
                exit_px, why = x["c"], "ibs_exit"
                break
        if exit_px is None:
            exit_px, why = bars[j]["c"], "max_hold"
        gross = side * (exit_px - entry) / risk
        cost_r = cost_bps / 1e4 * entry / risk
        trades.append({"entry_time": str(b["ts"]), "exit_time": str(bars[j]["ts"]), "side": arm["side"],
                       "gross_r": round(gross, 5), "cost_r": round(cost_r, 5), "net_r": round(gross - cost_r, 5),
                       "bars_held": j - t, "outcome": why})
        t = j + 1
    return trades


def _edges(lo: Any, hi: Any, k: int) -> list[Any]:
    step = (hi - lo) / k
    return [lo + step * i for i in range(k)] + [hi]


def run(a: argparse.Namespace) -> dict[str, Any]:
    import exit_lever_ablation as ela
    import harness_stage0 as hs
    from short_tf_discovery_sweep import mean_test

    from src.runtime import execution_costs as ec

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(a.data_dir) if a.data_dir else out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    csv_over = dict(kv.split("=", 1) for kv in (a.data_csv or []))
    arms = dict(parse_arm(s) for s in (a.arm or ["B="]))
    ela.N_FOLDS = a.folds

    series: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        try:
            csv = Path(csv_over[sym]) if sym in csv_over else hs.fetch_csv(
                sym, "1d", days=a.days, data_dir=data_dir, non_crypto_source=a.non_crypto_source)
            bars, cut = load_bars(csv, a.start, a.end)
            fee = ec.resolve_fee_bps_roundtrip(sym, a.fee_bps_roundtrip)
            slip, fund = ec.resolve_cost_policy(sym, slippage_bps_roundtrip=a.slippage_bps_roundtrip)
            series[sym] = {"bars": bars, "cut": cut, "fee": fee, "slip": slip, "funding": fund}
        except Exception as exc:  # noqa: BLE001 - a fetch fault is RECORDED per cell, never dropped
            series[sym] = {"error": f"{type(exc).__name__}: {exc}"}

    arms_out: dict[str, Any] = {}
    for label, cfg in arms.items():
        cells: dict[str, Any] = {}
        pooled_trades: list[dict[str, Any]] = []
        spans: list[Any] = []
        for sym in symbols:
            s = series[sym]
            if "error" in s or len(s["bars"]) < max(a.atr_period, a.sma) + 10:
                cells[sym] = {"state": "producer_failed", "why": s.get("error") or f"{len(s.get('bars', []))} bars"}
                continue
            if s["funding"]:
                cells[sym] = {"state": "producer_failed", "why": "perp funding is not modelled here (ETFs only)"}
                continue
            trades = simulate(s["bars"], cfg, cost_bps=s["fee"] + s["slip"], atr_period=a.atr_period, sma=a.sma)
            edges = _edges(s["bars"][0]["ts"], s["bars"][-1]["ts"], a.folds)
            folds = ela.fold_net_r(trades, edges)
            net = round(sum(t["net_r"] for t in trades), 4)
            folds_pos = sum(1 for f in folds if f["net_r"] > 0)
            mt = mean_test([t["net_r"] for t in trades])
            cells[sym] = {"state": "measured", "n": len(trades), "net_r": net,
                          "net_r_per_trade": round(net / len(trades), 4) if trades else None,
                          "gross_r": round(sum(t["gross_r"] for t in trades), 4),
                          "cost_bps_roundtrip": {"fee": s["fee"], "slippage": s["slip"], "funding": s["funding"]},
                          "folds": folds, "folds_pos": folds_pos, "t_one_sided_p": mt.get("p"),
                          "mean_bars_held": round(sum(t["bars_held"] for t in trades) / len(trades), 3) if trades else None,
                          "by_outcome": {k: sum(1 for t in trades if t["outcome"] == k) for k in
                                         ("ibs_exit", "max_hold", "stop", "stop_gap")},
                          "series_cut": s["cut"],
                          "grade": hs.grade_cell(len(trades), net, folds_pos, n_floor=a.n_floor, fold_majority=a.fold_majority)}
            pooled_trades.extend(trades)
            spans += [edges[0], edges[-1]]
        pooled = None
        if pooled_trades:
            edges = _edges(min(spans), max(spans), a.folds)
            folds = ela.fold_net_r(pooled_trades, edges)
            net = round(sum(t["net_r"] for t in pooled_trades), 4)
            mt = mean_test([t["net_r"] for t in pooled_trades])
            pooled = {"n": len(pooled_trades), "net_r": net, "folds": folds,
                      "folds_pos": sum(1 for f in folds if f["net_r"] > 0),
                      "net_r_per_trade": round(net / len(pooled_trades), 4), "t_one_sided_p": mt.get("p"),
                      "max_drawdown_r_sequential": hs.sequential_max_drawdown(pooled_trades)}
        arms_out[label] = {"cfg": cfg, "cells": cells, "pooled": pooled,
                           "holm_survivors": hs.holm({k: c.get("t_one_sided_p") for k, c in cells.items()
                                                      if c.get("state") == "measured"}, a.holm_alpha)}

    base_pooled = arms_out[a.baseline]["pooled"] if a.baseline else None
    for label, arm in arms_out.items():
        is_cand = bool(a.baseline) and label != a.baseline
        g = hs.grade_arm(arm["cells"], arm["pooled"], declared=len(symbols), breadth_frac=a.breadth_frac,
                         pooled_n_floor=a.pooled_n_floor, fold_majority=a.fold_majority,
                         min_powered_cells=a.min_powered_cells,
                         baseline_pooled=base_pooled if (is_cand and base_pooled) else None,
                         delta_r_per_trade=a.delta_r_per_trade if is_cand else 0.0)
        if is_cand and base_pooled is None and g["verdict"] == "pass":
            g = {"verdict": "indeterminate", "why": f"baseline arm {a.baseline} has no pooled trades"}
        arm["grade"] = g
    judged = {k: v for k, v in arms_out.items() if not a.baseline or k != a.baseline}
    passing = {k: v for k, v in judged.items() if v["grade"]["verdict"] == "pass"}
    if passing:
        best = max(passing, key=lambda k: passing[k]["pooled"]["net_r"])
        verdict, why = "pass", f"arm {best} passes (pooled net_r {passing[best]['pooled']['net_r']}); {len(passing)} of {len(judged)} candidate arms pass"
    elif any(v["grade"]["verdict"] == "indeterminate" for v in judged.values()):
        verdict, why = "indeterminate", "; ".join(f"{k}: {v['grade']['why']}" for k, v in judged.items())
    else:
        verdict, why = "fail", "; ".join(f"{k}: {v['grade']['why']}" for k, v in judged.items())
    any_measured = any(c.get("state") == "measured" for v in arms_out.values() for c in v["cells"].values())
    out = {"unit": a.rule_id, "harness": "scripts/research/ibs_reversion_stage0.py",
           "verdict": verdict if any_measured else "not_applicable",
           "read_state": "measured" if any_measured else "producer_failed",
           "note": f"{verdict.upper()}: {why}",
           "population": {"symbols": symbols, "timeframe": "1d", "start": a.start, "end": a.end},
           "thresholds": {"n_floor": a.n_floor, "pooled_n_floor": a.pooled_n_floor, "folds": a.folds,
                          "fold_majority": a.fold_majority, "breadth_frac": a.breadth_frac,
                          "min_powered_cells": a.min_powered_cells, "baseline": a.baseline,
                          "delta_r_per_trade": a.delta_r_per_trade},
           "arms": arms_out}
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


def _self_test() -> int:
    """Synthetic: a mean-reverting series must give the long IBS arm positive gross R; costs must be charged."""
    import itertools
    import random
    random.seed(7)
    bars, px = [], 100.0
    import datetime as dt
    t0 = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)
    for i in range(800):
        o = px
        c = 100.0 + 0.6 * (o - 100.0) + random.gauss(0, 1.0)  # strong pull to 100
        h, l = max(o, c) + abs(random.gauss(0, 0.3)), min(o, c) - abs(random.gauss(0, 0.3))
        bars.append({"ts": t0 + dt.timedelta(days=i), "o": o, "h": h, "l": l, "c": c})
        px = c
    tr = simulate(bars, dict(DEFAULT_ARM), cost_bps=5.0, atr_period=14, sma=200)
    assert len(tr) > 50, len(tr)
    gross = sum(t["gross_r"] for t in tr)
    assert gross > 0, gross
    assert all(t["cost_r"] > 0 for t in tr)
    assert all(t["exit_time"] > t["entry_time"] for t in tr)
    # no overlap: each entry after the previous exit
    for p, q in itertools.pairwise(tr):
        assert q["entry_time"] > p["exit_time"]
    lab, cfg = parse_arm("C=ibs_lo=1.01;max_hold=3")
    assert lab == "C" and cfg["ibs_lo"] == 1.01
    print(f"self-test ok: {len(tr)} trades, gross {gross:.2f} R")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--days", type=int, default=2500)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--arm", action="append", default=None, metavar="LABEL=k=v;k=v")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--delta-r-per-trade", type=float, default=0.0)
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--sma", type=int, default=200)
    ap.add_argument("--fee-bps-roundtrip", type=float, default=None)
    ap.add_argument("--slippage-bps-roundtrip", type=float, default=None)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--fold-majority", type=int, default=4)
    ap.add_argument("--n-floor", type=int, default=39)
    ap.add_argument("--pooled-n-floor", type=int, default=39)
    ap.add_argument("--breadth-frac", type=float, default=0.5)
    ap.add_argument("--min-powered-cells", type=int, default=2)
    ap.add_argument("--holm-alpha", type=float, default=0.05)
    ap.add_argument("--non-crypto-source", choices=("yfinance", "dukascopy"), default="yfinance")
    ap.add_argument("--data-csv", action="append", default=None, metavar="SYM=PATH")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--rule-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    v = run(a)
    print(json.dumps({"verdict": v["verdict"], "read_state": v["read_state"], "note": v["note"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
