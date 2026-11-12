#!/usr/bin/env python3
"""IBS take/skip meta-labeler (row ML-QUEUE-DIVERSIFY x FRONTIER-STATIC-MARKETS; unit RQ-20261112-3c8f-03).

Question: does a small LightGBM, trained only on PAST IBS-long candidate trades, pick which ones to take well enough
to beat taking every candidate, net of cost, out of sample?  This is trade SELECTION on a fixed entry rule, not a
direction or regime model.

Population: IBS arm L candidates (long when IBS < 0.2, classic exit or 3 days, 2 x ATR14 stop -- the arm of
RQ-20261112-a7e8-01, frozen) on daily bars of the --symbols basket, simulated by
``ibs_reversion_stage0.simulate`` (net of fee + slippage from execution_costs).

Features (all known at the signal bar's close): ibs, atr_pct, range_atr (bar range / ATR), ret_1, ret_5, ret_20,
dist_sma200, market (first symbol of --market, default SPY) ret_5 and dist_sma200, day of week, asset group.

Walk-forward: expanding by calendar year. For test year Y the model trains on every candidate whose EXIT is at least
--purge-days before Jan 1 of Y; test years are --test-years (default 2016..2026). Take rule (fixed): take iff the
predicted net R > 0.

Statistic: per-CANDIDATE net R (a skipped candidate scores 0) of the meta rule minus take-all, pooled over the test
years; 95 % CI by bootstrap over signal DATES (candidates on one date move together). The decision rule lives in the
unit YAML; this script reports the numbers and a verdict computed against the thresholds passed on the command line.

Writes only under --out (verdict.json, candidates.csv). Public candles; no config, src/ or order path.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for p in (str(_REPO), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

ARM_L = {"side": "long", "ibs_lo": 0.2, "ibs_hi": 0.8, "trend_filter": 0, "max_hold": 3, "stop_atr": 2.0}
FEATURES = ["ibs", "atr_pct", "range_atr", "ret_1", "ret_5", "ret_20", "dist_sma200", "mkt_ret_5", "mkt_dist_sma200",
            "dow", "grp"]
GROUPS = {"equity_index": {"SPY", "QQQ", "IWM", "DIA"}, "bond": {"TLT", "IEF"}, "metal": {"GLD", "SLV", "GDX"}}


def group_of(sym: str) -> int:
    for i, (_, s) in enumerate(GROUPS.items()):
        if sym in s:
            return i
    return len(GROUPS)  # sector / other


def bar_features(bars: list[dict[str, Any]], atr_period: int = 14) -> dict[str, dict[str, float]]:
    """Per-bar features keyed by str(ts); bars before 200 history are omitted."""
    out: dict[str, dict[str, float]] = {}
    n = len(bars)
    tr = [None] + [max(bars[i]["h"], bars[i - 1]["c"]) - min(bars[i]["l"], bars[i - 1]["c"]) for i in range(1, n)]
    for t in range(200, n):
        b = bars[t]
        c = b["c"]
        atr = sum(tr[t - atr_period + 1:t + 1]) / atr_period
        rng = b["h"] - b["l"]
        sma = sum(x["c"] for x in bars[t - 199:t + 1]) / 200
        out[str(b["ts"])] = {
            "ibs": (c - b["l"]) / rng if rng > 0 else 0.5,
            "atr_pct": atr / c if c else 0.0,
            "range_atr": rng / atr if atr else 0.0,
            "ret_1": c / bars[t - 1]["c"] - 1,
            "ret_5": c / bars[t - 5]["c"] - 1,
            "ret_20": c / bars[t - 20]["c"] - 1,
            "dist_sma200": c / sma - 1,
            "dow": float(b["ts"].dayofweek) if hasattr(b["ts"], "dayofweek") else 0.0,
        }
    return out


def build_candidates(series: dict[str, list[dict[str, Any]]], costs: dict[str, float], market: str) -> list[dict[str, Any]]:
    from ibs_reversion_stage0 import simulate
    feats = {s: bar_features(b) for s, b in series.items()}
    mkt = feats.get(market, {})
    rows = []
    for sym, bars in series.items():
        for tr in simulate(bars, ARM_L, cost_bps=costs[sym], atr_period=14, sma=200):
            f = feats[sym].get(tr["entry_time"])
            m = mkt.get(tr["entry_time"])
            if f is None or m is None:
                continue  # inside the 200-bar warm-up, or the market had no bar that day
            rows.append({"symbol": sym, "entry_time": tr["entry_time"], "exit_time": tr["exit_time"],
                         "net_r": tr["net_r"], "gross_r": tr["gross_r"], **f,
                         "mkt_ret_5": m["ret_5"], "mkt_dist_sma200": m["dist_sma200"], "grp": float(group_of(sym))})
    rows.sort(key=lambda r: r["entry_time"])
    return rows


def walk_forward(rows: list[dict[str, Any]], test_years: list[int], purge_days: int, seed: int) -> list[dict[str, Any]]:
    import lightgbm as lgb
    import numpy as np
    import pandas as pd
    df = pd.DataFrame(rows)
    df["entry_ts"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_ts"] = pd.to_datetime(df["exit_time"], utc=True)
    out = []
    for y in test_years:
        start = pd.Timestamp(f"{y}-01-01", tz="UTC")
        end = pd.Timestamp(f"{y + 1}-01-01", tz="UTC")
        train = df[df.exit_ts < start - pd.Timedelta(days=purge_days)]
        test = df[(df.entry_ts >= start) & (df.entry_ts < end)]
        if len(test) == 0:
            continue
        if len(train) < 200:
            pred = np.full(len(test), np.nan)  # too little history: recorded, the year is not scored
        else:
            params = {"objective": "regression", "max_depth": 3, "num_leaves": 7, "learning_rate": 0.05,
                      "min_data_in_leaf": 50, "bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8,
                      "seed": seed, "deterministic": True, "num_threads": 1, "verbose": -1}
            ds = lgb.Dataset(train[FEATURES].to_numpy(dtype=float), label=train["net_r"].clip(-3, 3).to_numpy())
            m = lgb.train(params, ds, num_boost_round=100)
            pred = m.predict(test[FEATURES].to_numpy(dtype=float))
        for (_, r), p in zip(test.iterrows(), pred):
            out.append({"year": y, "symbol": r.symbol, "entry_time": r.entry_time, "net_r": float(r.net_r),
                        "pred": None if (p is None or (isinstance(p, float) and math.isnan(p))) else float(p),
                        "n_train": int(len(train))})
    return out


def grade(scored: list[dict[str, Any]], *, delta_bar: float, n_floor: int, year_majority: float, boot: int,
          seed: int) -> dict[str, Any]:
    s = [r for r in scored if r["pred"] is not None]
    n = len(s)
    if n == 0:
        return {"verdict": "indeterminate", "read_state": "no_data", "n": 0, "why": "no scored candidates"}
    meta = [r["net_r"] if r["pred"] > 0 else 0.0 for r in s]
    base = [r["net_r"] for r in s]
    d = [a - b for a, b in zip(meta, base)]
    delta = sum(d) / n
    taken = [r["net_r"] for r in s if r["pred"] > 0]
    by_date: dict[str, list[float]] = {}
    for r, x in zip(s, d):
        by_date.setdefault(r["entry_time"][:10], []).append(x)
    dates = list(by_date)
    rng = random.Random(seed)
    bs = []
    for _ in range(boot):
        tot, cnt = 0.0, 0
        for _ in range(len(dates)):
            v = by_date[dates[rng.randrange(len(dates))]]
            tot += sum(v)
            cnt += len(v)
        bs.append(tot / cnt)
    bs.sort()
    lo, hi = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
    years: dict[int, list[float]] = {}
    for r, x in zip(s, d):
        years.setdefault(r["year"], []).append(x)
    yr = {y: {"n": len(v), "delta_per_cand": round(sum(v) / len(v), 4)} for y, v in sorted(years.items())}
    yrs_ok = sum(1 for v in yr.values() if v["delta_per_cand"] >= 0)
    need_years = math.ceil(year_majority * len(yr))
    taken_mean = sum(taken) / len(taken) if taken else None
    res = {"n": n, "n_taken": len(taken), "take_share": round(len(taken) / n, 4),
           "base_net_r_per_cand": round(sum(base) / n, 5), "meta_net_r_per_cand": round(sum(meta) / n, 5),
           "delta_per_cand": round(delta, 5), "ci95": [round(lo, 5), round(hi, 5)], "n_dates": len(dates),
           "taken_mean_net_r": None if taken_mean is None else round(taken_mean, 5),
           "years": yr, "years_delta_nonneg": yrs_ok, "years_needed": need_years,
           "skipped_mean_net_r": (round(sum(r["net_r"] for r in s if r["pred"] <= 0) / (n - len(taken)), 5)
                                  if n > len(taken) else None)}
    if n < n_floor:
        res.update(verdict="indeterminate", why=f"n {n} < floor {n_floor}")
    elif delta >= delta_bar and lo > 0 and taken_mean is not None and taken_mean > 0 and yrs_ok >= need_years:
        res.update(verdict="pass", why=f"delta {delta:+.4f} >= {delta_bar}, CI lo {lo:+.4f} > 0, {yrs_ok}/{len(yr)} years")
    else:
        res.update(verdict="fail", why=(f"delta {delta:+.4f} (bar {delta_bar}), CI [{lo:+.4f}, {hi:+.4f}], taken mean "
                                        f"{taken_mean}, years {yrs_ok}/{len(yr)} (need {need_years})"))
    res["read_state"] = "measured"
    return res


def run(a: argparse.Namespace) -> dict[str, Any]:
    import harness_stage0 as hs
    from ibs_reversion_stage0 import load_bars

    from src.runtime import execution_costs as ec
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data_dir = Path(a.data_dir) if a.data_dir else out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    series, costs, failed = {}, {}, {}
    for s in syms:
        try:
            csv = hs.fetch_csv(s, "1d", days=a.days, data_dir=data_dir, non_crypto_source="yfinance")
            bars, cut = load_bars(csv, a.start, a.end)
            fee = ec.resolve_fee_bps_roundtrip(s, None)
            slip, fund = ec.resolve_cost_policy(s, slippage_bps_roundtrip=None)
            series[s], costs[s] = bars, fee + slip + fund
            if cut:
                failed[s] = f"series cut: {cut}"
        except Exception as exc:  # noqa: BLE001  # allow-silent: a fetch fault is RECORDED in symbols_failed and the population line, never dropped
            failed[s] = f"{type(exc).__name__}: {exc}"
    rows = build_candidates(series, costs, a.market)
    scored = walk_forward(rows, a.test_years, a.purge_days, a.seed)
    res = grade(scored, delta_bar=a.delta_bar, n_floor=a.n_floor, year_majority=a.year_majority, boot=a.boot, seed=a.seed)
    v = {"unit": a.rule_id and a.rule_id.replace("RULE-", "") or None, "rule_id": a.rule_id, "verdict": res["verdict"],
         "read_state": res["read_state"], "note": res["why"],
         "population": {"symbols": syms, "symbols_built": sorted(series), "symbols_failed": failed, "start": a.start,
                        "end": a.end, "test_years": a.test_years, "n_candidates_all_years": len(rows), "arm": ARM_L,
                        "features": FEATURES, "cost_bps_roundtrip": costs},
         "measurement": res}
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=str))
    import csv as _csv
    with (out / "candidates.csv").open("w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["year", "symbol", "entry_time", "net_r", "pred", "n_train"])
        w.writeheader()
        w.writerows(scored)
    return v


def _self_test() -> bool:
    import pandas as pd
    ok = True
    # 1. grade: a predictor that skips exactly the losers must pass; the take-all predictor has delta 0 -> fail.
    rng = random.Random(1)
    sc = []
    for y in range(2016, 2027):
        for i in range(120):
            x = rng.gauss(0.0, 1.0)
            sc.append({"year": y, "entry_time": f"{y}-03-{(i % 28) + 1:02d}", "net_r": x, "pred": x})
    g = grade(sc, delta_bar=0.02, n_floor=620, year_majority=0.5, boot=200, seed=1)
    ok &= g["verdict"] == "pass"
    print(("  PASS" if g["verdict"] == "pass" else "  FAIL") + "  an oracle skip rule passes")
    sc2 = [dict(r, pred=1.0) for r in sc]
    g2 = grade(sc2, delta_bar=0.02, n_floor=620, year_majority=0.5, boot=200, seed=1)
    ok &= g2["verdict"] == "fail" and g2["delta_per_cand"] == 0.0
    print(("  PASS" if g2["verdict"] == "fail" else "  FAIL") + "  take-all has delta 0 and fails")
    g3 = grade(sc[:100], delta_bar=0.02, n_floor=620, year_majority=0.5, boot=50, seed=1)
    ok &= g3["verdict"] == "indeterminate"
    print(("  PASS" if g3["verdict"] == "indeterminate" else "  FAIL") + "  below the floor is indeterminate, never fail")
    # 2. purge: no training row's exit falls within purge_days of the test year.
    t0 = pd.Timestamp("2014-01-02", tz="UTC")
    rows = []
    for i in range(1500):
        e = t0 + pd.Timedelta(days=2 * i)
        rows.append({"symbol": "SPY", "entry_time": str(e), "exit_time": str(e + pd.Timedelta(days=3)),
                     "net_r": rng.gauss(0, 1), **{f: rng.random() for f in FEATURES}})
    wf = walk_forward(rows, [2016, 2017], purge_days=5, seed=1)
    ok &= all(r["year"] in (2016, 2017) for r in wf) and len(wf) > 0
    tr16 = [r for r in rows if pd.Timestamp(r["exit_time"]) < pd.Timestamp("2016-01-01", tz="UTC") - pd.Timedelta(days=5)]
    ok &= wf[0]["n_train"] == len(tr16)
    print(("  PASS" if wf[0]["n_train"] == len(tr16) else "  FAIL") + "  walk-forward trains only on exits before the purge")
    print("ibs_meta_label self-test:", "OK" if ok else "FAILED")
    return bool(ok)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA,TLT,IEF,GLD,SLV,GDX")
    ap.add_argument("--market", default="SPY")
    ap.add_argument("--days", type=int, default=6300)
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--test-years", type=lambda s: [int(x) for x in s.split(",")],
                    default=list(range(2016, 2027)))
    ap.add_argument("--purge-days", type=int, default=5)
    ap.add_argument("--delta-bar", type=float, default=0.02)
    ap.add_argument("--n-floor", type=int, default=620)
    ap.add_argument("--year-majority", type=float, default=0.5)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261112)
    ap.add_argument("--rule-id", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return 0 if _self_test() else 1
    if not a.out:
        ap.error("--out is required")
    v = run(a)
    print(json.dumps({"verdict": v["verdict"], "read_state": v["read_state"], "note": v["note"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
