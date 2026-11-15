#!/usr/bin/env python3
# wiring: manual-only - run by lane SMALL-TF-ML-RESEARCH for unit RQ-20261112-743a-01 (row SMALL-TF-ML-RESEARCH, roadmap M27); no schedule consumes it.
"""Small-timeframe COST-BREAKEVEN CENSUS per (symbol, tf, hold) at 1m / 5m / 15m, token-free.

Rule and constants: research/queue/RQ-20261112-743a-01.yaml (registered before this file was run).

Question: what gross edge must a small-TF entry earn to clear fee + slippage + funding, and is that inside what a fitted
learner has ALREADY been measured to earn on the same symbols and window? Two halves, joined in bps of notional:

 REQUIRED  (computed here, from Binance Vision USD-M 1m klines): per (symbol, tf, hold cap, stop multiple k, TP multiple m) a
           random-entry bracket simulation (both sides, every tf bar, entry at the NEXT bar's open, stop 1.0*k*ATR14(tf),
           TP m*k*ATR14(tf), time cap at the hold, same-bar stop+TP resolves to STOP, gaps fill at the open). Gives the
           observed TP / stop / time-exit hit rates, stop distance in bps, and the round-trip cost under each scenario in bps and
           in R (src/runtime/execution_costs.roundtrip_cost_r formula, checked against the function on a sample).
 ACHIEVED  (NOT recomputed; read from the committed record comms/research/desk_edge/ceiling-1m/verdict.json, rule
           RULE-RQ20261027-FE57-02-SHORT-HOLD-CEILING, same six symbols, same DEV window 2025-11-01..2026-09-15): the best learner's
           S3 (selected gross lift over random geometry) per hold, point and family-corrected lower CI bound, converted to bps with
           that record's own stop width (taker cost bps / mean_cost_r_taker) and rescaled to each symbol by its own hold-move sd.

Scenarios (round trip, bps of notional; the unmeasured ones are UPPER BOUNDS and are labelled so):
  taker_measured   12.3  MEASURED fee 11.0 (5.5/side, comms/research/desk_edge/levers/bybit-fee-measured-2026-10-27.json) + 1.3 slippage
  repo_stack       10.5  7.5 fee + 3.0 slippage (execution_costs default stack)
  makerF_measured  taker_measured - 2.03   MEASURED saving of a post-only entry with taker fallback, adverse selection INCLUDED
                   (RQ-20261027-a3f1-01 PASS: mean delta_F 2.03 bps, strict fill 88.7%; the 2.0 bps maker fee is PUBLISHED, UNVERIFIED)
  makerF_tpmaker_ub  makerF entry + TP exit as a resting maker order at 2.0 bps with no slippage, fills on touch (UPPER BOUND: no
                   queue, no adverse selection), stop and time exits taker; the maker share is the cell's own observed TP rate
  maker_entry_ub    9.0  desk_edge_levers scenario, entry fills at the same price (UPPER BOUND)
  both_maker_ub     4.0  every leg maker, stops included (UPPER BOUND, not achievable: stops cannot rest)
Funding: 1.0 bps per 8 h held (desk_edge_levers.FUNDING_BPS_PER_8H), charged on the cell's mean hold.

  run --cache DIR --out DIR [--symbols ...]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.runtime.execution_costs import roundtrip_cost_r

SYMBOLS = ["ADAUSDT", "AVAXUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
MONTHS = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
WINDOW = ("2025-11-01", "2026-09-15")
URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1m/{s}-1m-{m}.zip"
# (tf minutes, hold-cap bars): cap minutes = tf * bars must be a hold of the committed ceiling-1m record
GRID_TF_BARS = {1: [5, 15, 30, 60], 5: [3, 6, 12, 24], 15: [2, 4, 8, 16]}
K_STOP = [1.0, 2.0]
M_TP = [1.0, 1.5, 3.0]
ATR_N = 14
FUND_BPS_8H = 1.0
TAKER_MEASURED = 12.3
MAKER_F_SAVING = 2.03
SIDE_TAKER = 11.0 / 2 + 1.3 / 2          # 6.15 bps per side
SIDE_MAKER = 2.0                          # published maker fee, no slippage on a filled limit
SCEN_MEASURED = ["taker_measured", "repo_stack", "makerF_measured"]
SCEN_UB = ["makerF_tpmaker_ub", "maker_entry_ub", "both_maker_ub"]
ROOM = 1.25                               # "clears with room": achieved lower bound >= 1.25 x required
BREADTH_MIN = 4                           # of 6 symbols
CEIL = "comms/research/desk_edge/ceiling-1m/verdict.json"


def load_1m(sym: str, cache: Path) -> pd.DataFrame:
    parts = []
    for m in MONTHS:
        f = cache / f"{sym}-1m-{m}.zip"
        if not f.exists():
            req = urllib.request.Request(URL.format(s=sym, m=m))
            f.write_bytes(urllib.request.urlopen(req, timeout=120).read())
        z = zipfile.ZipFile(f)
        (name,) = z.namelist()
        df = pd.read_csv(io.BytesIO(z.read(name)), usecols=range(6))
        df.columns = ["t", "open", "high", "low", "close", "volume"]
        df = df[pd.to_numeric(df["t"], errors="coerce").notna()].astype({"t": "int64"})
        parts.append(df)
    d = pd.concat(parts).drop_duplicates("t").sort_values("t")
    t = d["t"].to_numpy()
    d["t"] = pd.to_datetime(np.where(t > 1e14, t // 1000, t), unit="ms", utc=True)
    d = d[(d["t"] >= WINDOW[0]) & (d["t"] < WINDOW[1])].set_index("t")
    return d[["open", "high", "low", "close"]].astype(float)


def resample(d1: pd.DataFrame, tf: int) -> pd.DataFrame:
    if tf == 1:
        return d1
    r = d1.resample(f"{tf}min", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return r.dropna()


def atr(d: pd.DataFrame) -> np.ndarray:
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_N).mean().to_numpy()


def simulate(d: pd.DataFrame, a: np.ndarray, nbars: int, k: float, m: float, chunk: int = 60000):
    """Random-entry bracket outcomes for BOTH sides. Returns dict of arrays over (entry, side) rows."""
    o, h, lo, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    n = len(d)
    idx = np.arange(ATR_N, n - nbars - 1)
    idx = idx[np.isfinite(a[idx])]
    out = {x: [] for x in ("entry", "risk", "exit", "kind", "bars", "gross_r")}
    def sw(arr):
        return np.lib.stride_tricks.sliding_window_view(arr, nbars)

    H, L, OP = sw(h), sw(lo), sw(o)
    for s0 in range(0, len(idx), chunk):
        ii = idx[s0 : s0 + chunk]
        e = o[ii + 1]
        risk = k * a[ii]
        hh, ll, oo = H[ii + 1], L[ii + 1], OP[ii + 1]
        lastc = c[ii + nbars]
        for side in (1, -1):
            stop = e - side * risk
            tp = e + side * m * risk
            if side == 1:
                hs, ht = ll <= stop[:, None], hh >= tp[:, None]
            else:
                hs, ht = hh >= stop[:, None], ll <= tp[:, None]
            anys, anyt = hs.any(1), ht.any(1)
            fs = np.where(anys, hs.argmax(1), nbars)
            ft = np.where(anyt, ht.argmax(1), nbars)
            stop_first = anys & (~anyt | (fs <= ft))                 # same bar -> stop
            tp_first = anyt & ~stop_first
            rows = np.arange(len(ii))
            sx = np.where(side == 1, np.minimum(stop, oo[rows, np.minimum(fs, nbars - 1)]), np.maximum(stop, oo[rows, np.minimum(fs, nbars - 1)]))
            tx = np.where(side == 1, np.maximum(tp, oo[rows, np.minimum(ft, nbars - 1)]), np.minimum(tp, oo[rows, np.minimum(ft, nbars - 1)]))
            ex = np.where(stop_first, sx, np.where(tp_first, tx, lastc))
            kind = np.where(stop_first, 0, np.where(tp_first, 1, 2))
            bars = np.where(stop_first, fs + 1, np.where(tp_first, ft + 1, nbars))
            out["entry"].append(e)
            out["risk"].append(risk)
            out["exit"].append(ex)
            out["kind"].append(kind)
            out["bars"].append(bars)
            out["gross_r"].append(side * (ex - e) / risk)
    return {x: np.concatenate(v) for x, v in out.items()}


def scenario_bps(p_tp: float, hold_h: float) -> dict:
    fund = FUND_BPS_8H * hold_h / 8.0
    mk_exit = p_tp * SIDE_MAKER + (1 - p_tp) * SIDE_TAKER
    return {
        "taker_measured": TAKER_MEASURED + fund,
        "repo_stack": 10.5 + fund,
        "makerF_measured": TAKER_MEASURED - MAKER_F_SAVING + fund,
        "makerF_tpmaker_ub": (SIDE_TAKER - MAKER_F_SAVING) + mk_exit + fund,
        "maker_entry_ub": 9.0 + fund,
        "both_maker_ub": 4.0 + fund,
    }


def check_cost_formula(sim: dict, n: int = 2000) -> float:
    """Vectorised cost_R must equal execution_costs.roundtrip_cost_r on a sample (same formula, same inputs)."""
    rng = np.random.default_rng(7)
    ix = rng.choice(len(sim["entry"]), min(n, len(sim["entry"])), replace=False)
    worst = 0.0
    for i in ix:
        f = roundtrip_cost_r(entry=sim["entry"][i], exit_price=sim["exit"][i], risk=sim["risk"][i], hold_hours=1.0,
                             fee_bps_roundtrip=11.0, slippage_bps_roundtrip=1.3, funding_bps_per_window=1.0)
        avg = (abs(sim["entry"][i]) + abs(sim["exit"][i])) / 2
        mine = (11.0 + 1.3 + FUND_BPS_8H * 1.0 / 8.0) * 1e-4 * avg / sim["risk"][i]
        worst = max(worst, abs(f["total_cost_r"] - mine))
    return worst


def achieved_table(root: Path) -> dict:
    v = json.loads((root / CEIL).read_text())["measurement"]
    out = {}
    for h, row in v["per_hold"].items():
        g = row["gbdt/taker"]
        stop_bps = (TAKER_MEASURED + FUND_BPS_8H * int(h) / 480.0) / row["mean_cost_r_taker"]
        out[int(h)] = {"S3_point": g["S3"], "S3_lo_corrected": g["S3_ci_corrected"][0], "stop_bps_ceiling": stop_bps,
                       "ceiling_cost_r_taker": row["mean_cost_r_taker"], "ceiling_S1_taker": g["S1"],
                       "point_bps": g["S3"] * stop_bps, "lo_bps": g["S3_ci_corrected"][0] * stop_bps}
    return out


def hold_sd_bps(d1: pd.DataFrame, minutes: int) -> float:
    r = np.diff(np.log(d1["close"].to_numpy()[::minutes])) * 1e4
    return float(r.std())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", nargs="*", default=SYMBOLS)
    a = ap.parse_args()
    cache, out = Path(a.cache), Path(a.out)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    ach = achieved_table(root)
    cells, sd_tab, formula_dev = [], {}, 0.0
    for sym in a.symbols:
        d1 = load_1m(sym, cache)
        print(f"{sym}: {len(d1)} 1m bars {d1.index[0]} .. {d1.index[-1]}", file=sys.stderr)
        sd_tab[sym] = {h: hold_sd_bps(d1, h) for h in sorted(ach)}
        for tf, bars_list in GRID_TF_BARS.items():
            d = resample(d1, tf)
            at = atr(d)
            for nb in bars_list:
                hold_min = tf * nb
                for k in K_STOP:
                    for m in M_TP:
                        s = simulate(d, at, nb, k, m)
                        if (tf, nb, k, m) == (5, 6, 1.0, 1.5):
                            formula_dev = max(formula_dev, check_cost_formula(s))
                        kind, bars = s["kind"], s["bars"]
                        p_tp, p_st, p_tm = float((kind == 1).mean()), float((kind == 0).mean()), float((kind == 2).mean())
                        hold_h = float(bars.mean()) * tf / 60.0
                        stop_bps = float((s["risk"] / s["entry"]).mean() * 1e4)
                        sc = scenario_bps(p_tp, hold_h)
                        cost_r = {n_: float(b * 1e-4 * ((s["entry"] + s["exit"]) / 2 / s["risk"]).mean()) for n_, b in sc.items()}
                        cells.append({
                            "symbol": sym, "tf": tf, "hold_min": hold_min, "k": k, "m": m, "n_rows": len(kind),
                            "p_tp": p_tp, "p_stop": p_st, "p_time": p_tm, "mean_hold_min": float(bars.mean()) * tf,
                            "stop_bps": stop_bps, "random_gross_r": float(s["gross_r"].mean()),
                            "random_gross_bps": float(s["gross_r"].mean() * stop_bps),
                            "required_bps": sc, "cost_r": cost_r,
                            "req_hit_lift_pp": {n_: float(100 * cost_r[n_] / (m + 1)) for n_ in sc},
                        })
    # join to the achieved side, per symbol rescaled by its own hold-move sd relative to the pooled median
    for c in cells:
        H = c["hold_min"]
        med = float(np.median([sd_tab[s][H] for s in sd_tab]))
        scale = sd_tab[c["symbol"]][H] / med
        c["achieved_point_bps"] = ach[H]["point_bps"] * scale
        c["achieved_lo_bps"] = ach[H]["lo_bps"] * scale
        c["clears_lo_with_room"] = {n_: bool(c["achieved_lo_bps"] >= ROOM * r) for n_, r in c["required_bps"].items()}
        c["clears_point"] = {n_: bool(c["achieved_point_bps"] >= r) for n_, r in c["required_bps"].items()}
        c["breakeven_cost_bps_point"] = c["achieved_point_bps"]
    # registered grading: breadth across symbols for the same (tf, hold, k, m, scenario)
    keyed = {}
    for c in cells:
        keyed.setdefault((c["tf"], c["hold_min"], c["k"], c["m"]), []).append(c)
    def breadth(field, scen):
        best = []
        for key, cs in keyed.items():
            best.append((sum(1 for c in cs if c[field][scen]), key))
        return max(best)
    summary = {}
    for scen in SCEN_MEASURED + SCEN_UB:
        summary[scen] = {"max_symbols_clearing_lo_with_room": breadth("clears_lo_with_room", scen)[0],
                         "at": breadth("clears_lo_with_room", scen)[1],
                         "max_symbols_clearing_point": breadth("clears_point", scen)[0],
                         "at_point": breadth("clears_point", scen)[1]}
    pass_ = any(summary[s]["max_symbols_clearing_lo_with_room"] >= BREADTH_MIN for s in SCEN_MEASURED)
    fail = not any(summary[s]["max_symbols_clearing_point"] >= BREADTH_MIN for s in SCEN_MEASURED)
    verdict = "pass" if pass_ else ("fail" if fail else "indeterminate")
    n_cells = len(cells)
    per_hold = {}
    for H in sorted(ach):
        cs = [c for c in cells if c["hold_min"] == H]
        if not cs:
            continue
        per_hold[H] = {
            "ceiling": ach[H],
            "median_stop_bps_cells": float(np.median([c["stop_bps"] for c in cs])),
            "breakeven_cost_bps_point_by_symbol": {s: round(next(c for c in cs if c["symbol"] == s)["achieved_point_bps"], 2) for s in a.symbols},
            "required_bps_taker_measured": round(cs[0]["required_bps"]["taker_measured"], 2),
            "required_bps_makerF_measured": round(cs[0]["required_bps"]["makerF_measured"], 2),
        }
    res = {"verdict": verdict, "read_state": "measured", "n_cells": n_cells,
           "population": f"{len(a.symbols)} Binance USD-M perps, 1m klines {WINDOW[0]}..{WINDOW[1]}, random entries both sides per tf bar; "
                         f"{n_cells} (symbol, tf, hold, k, m) cells; achieved side = committed ceiling-1m record (gbdt/taker S3)",
           "rows_per_cell_median": int(np.median([c["n_rows"] for c in cells])),
           "summary_by_scenario": summary, "per_hold": per_hold, "cost_formula_max_abs_dev_r": formula_dev,
           "constants": {"room": ROOM, "breadth_min": BREADTH_MIN, "measured_scenarios": SCEN_MEASURED, "upper_bound_scenarios": SCEN_UB,
                         "maker_f_saving_bps": MAKER_F_SAVING, "funding_bps_per_8h": FUND_BPS_8H}}
    (out / "census_cells.json").write_text(json.dumps(cells))
    (out / "census_summary.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({"verdict": verdict, "summary": summary}, indent=1, default=str))


if __name__ == "__main__":
    main()
