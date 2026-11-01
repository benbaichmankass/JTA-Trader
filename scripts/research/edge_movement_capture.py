#!/usr/bin/env python3
# wiring: manual-only - RESEARCH-EDGE unit RQ-20261101-58e4-06 (direction-agnostic movement capture). Reuses edge_portfolio_discovery metrics and regime_robustness.
"""Predict the SIZE of the next day's move, trade it BOTH ways (two-sided stop brackets around the predicted range). No direction view.

Forecast : R_hat(D) = EWMA(lambda 0.94) of the realised daily range r=(H-L)/O over days < D (causal). It is the baseline any ML vol head must beat.
           Predictability is REPORTED per calendar year (Spearman of R_hat vs realised range, pooled over symbol-days).
Levels   : at 00:00 UTC of day D, U = O(1+a*R_hat), L = O(1-a*R_hat). First touch opens the trade, the other side is cancelled. One trade per symbol-day.
  breakout: trade WITH the touch (long at U, short at L). fade: trade AGAINST it (short at U, long at L).
  TP = entry +/- b*R_hat*O (a real predicted-range target), SL = entry -/+ c*R_hat*O, otherwise exit at the day's last close.
Fills   : 1h bars. Entry bar: stop checked first, TP not credited (pessimistic). Both levels touched in one bar: counted as a stop loss (-c*R_hat), split evenly across sides.
Costs   : round trip 11 bps fee + 3 bps slippage = 14 bps per trade, all taker (stress 2x). Fixed notional 1/N per symbol (NO sizing work); returns are fractions of capital.
Selection: the config with the highest net Sharpe among the 8 is the only one graded, deflated at N=8.
"""

import argparse
import json
import pickle
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D
import regime_robustness as RR


def spearmanr(x, y):
    return (pd.Series(np.asarray(x)).rank().corr(pd.Series(np.asarray(y)).rank()),)


UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "BCHUSDT",
    "SOLUSDT",
]
CFG = {
    "BO1": dict(mode="bo", a=0.4, b=0.6, c=0.4),
    "BO2": dict(mode="bo", a=0.6, b=0.8, c=0.5),
    "BO3": dict(mode="bo", a=0.4, b=1.0, c=0.5),
    "FD1": dict(mode="fd", a=0.5, b=0.5, c=0.5),
    "FD2": dict(mode="fd", a=0.7, b=0.7, c=0.5),
    "FD3": dict(mode="fd", a=0.35, b=0.35, c=0.35),
    "BO1g": dict(mode="bo", a=0.4, b=0.6, c=0.4, gate=True),
    "FD1g": dict(mode="fd", a=0.5, b=0.5, c=0.5, gate=True),
}
LAM, RT_BPS = 0.94, 14.0


def sim_day(o, h, lo, c, rh, cfg):
    px0 = o[0]
    U, Lv = px0 * (1 + cfg["a"] * rh), px0 * (1 - cfg["a"] * rh)
    for i in range(len(o)):
        up, dn = h[i] >= U, lo[i] <= Lv
        if not up and not dn:
            continue
        if up and dn:
            return -cfg["c"] * rh, 0, "amb"
        touch = 1 if up else -1
        d = touch if cfg["mode"] == "bo" else -touch
        E = U if up else Lv
        tp, sl = E * (1 + d * cfg["b"] * rh), E * (1 - d * cfg["c"] * rh)

        def hit_sl(j):
            return (lo[j] <= sl) if d > 0 else (h[j] >= sl)

        def hit_tp(j):
            return (h[j] >= tp) if d > 0 else (lo[j] <= tp)

        if hit_sl(i):
            return d * (sl / E - 1), d, "sl"
        for j in range(i + 1, len(o)):
            if hit_sl(j):
                return d * (sl / E - 1), d, "sl"
            if hit_tp(j):
                return d * (tp / E - 1), d, "tp"
        return d * (c[-1] / E - 1), d, "time"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rt-bps", type=float, default=RT_BPS,
                    help="round-trip cost in bps (default 14 = 11 taker fee + 3 slippage). 4 = the MAKER-FILL CEILING arm: 100%% fill, "
                         "no adverse selection, 2 bps/side -- an upper bound on what a limit-entry cost lever can recover.")
    ap.add_argument("--dsr-trials", type=int, default=len(CFG),
                    help="N for the deflated Sharpe (default = this grid). The cost-ceiling iteration passes the CUMULATIVE count.")
    a = ap.parse_args()
    ser, _ = pickle.load(open(Path(a.data_root) / "klines_1h.pkl", "rb"))
    out = {"universe": UNIVERSE, "configs": {}, "n_trials": a.dsr_trials}
    recs = {}
    pred_rows = []
    for s in UNIVERSE:
        df = ser[s]
        df = df[
            df.index <= D.END_DISCOVERY + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
        ]
        g = df.groupby(df.index.normalize())
        dd = pd.DataFrame(
            {
                "o": g["open"].first(),
                "h": g["high"].max(),
                "l": g["low"].min(),
                "n": g["open"].size(),
            }
        )
        dd = dd[dd.n == 24]
        r = (dd.h - dd.l) / dd.o
        ew = pd.Series(np.nan, index=r.index)
        v = None
        for i, (t, x) in enumerate(r.items()):
            ew.iloc[i] = np.nan if v is None or i < 30 else v
            v = x if v is None else LAM * v + (1 - LAM) * x
        dd["rh"] = ew
        dd["r"] = r
        recs[s] = (df, dd)
        for t, row in dd.dropna().iterrows():
            pred_rows.append((s, t, row.rh, row.r))
    pr = pd.DataFrame(pred_rows, columns=["s", "t", "rh", "r"])
    pr = pr[pr.t >= D.EVAL_START]
    out["vol_predictability_spearman_by_year"] = {
        int(y): round(float(spearmanr(g.rh, g.r)[0]), 3)
        for y, g in pr.groupby(pr.t.dt.year)
    }
    naive = pr.assign(
        n=pr.groupby("s").r.transform(lambda x: x.rolling(22).mean().shift(1))
    ).dropna()
    out["corr_ewma_vs_trailing22_mean"] = round(
        float(spearmanr(naive.rh, naive.n)[0]), 3
    )
    idx = pd.date_range(D.EVAL_START, D.END_DISCOVERY, freq="D", tz="UTC")
    for cid, cfg in CFG.items():
        res = {}
        for tag, mult in (("primary", 1.0), ("stress", 2.0)):
            net = pd.Series(0.0, index=idx)
            ln = net.copy()
            sn = net.copy()
            cnt = net.copy()
            outc = {"tp": 0, "sl": 0, "time": 0, "amb": 0}
            for s in UNIVERSE:
                df, dd = recs[s]
                med = dd.rh.rolling(60).median().shift(1)
                bars = {t: g for t, g in df.groupby(df.index.normalize())}
                for t, row in dd.iterrows():
                    if t < D.EVAL_START or not np.isfinite(row.rh):
                        continue
                    if cfg.get("gate") and not (
                        np.isfinite(med[t]) and row.rh >= med[t]
                    ):
                        continue
                    gb = bars[t]
                    sim = sim_day(
                        gb.open.to_numpy(),
                        gb.high.to_numpy(),
                        gb.low.to_numpy(),
                        gb.close.to_numpy(),
                        row.rh,
                        cfg,
                    )
                    if sim is None:
                        continue
                    ret, d, why = sim
                    ret = (ret - a.rt_bps * mult / 1e4) / len(UNIVERSE)
                    net[t] += ret
                    cnt[t] += 1 / len(UNIVERSE)
                    outc[why] += 1
                    if d > 0:
                        ln[t] += ret
                    elif d < 0:
                        sn[t] += ret
                    else:
                        ln[t] += ret / 2
                        sn[t] += ret / 2
            m = D.metrics(net, cnt, a.dsr_trials)
            res[tag] = m
            if tag == "primary":
                res["outcomes"] = outc
                res["series"] = (net, ln, sn)
        out["configs"][cid] = res
    best = max(
        out["configs"], key=lambda k: out["configs"][k]["primary"].get("sharpe_net", -9)
    )
    net, ln, sn = out["configs"][best]["series"]
    cl = RR.clause(net, ln, sn, two_sided=True)
    p, st = out["configs"][best]["primary"], out["configs"][best]["stress"]
    chk = {
        "sharpe>=0.5": p["sharpe_net"] >= 0.5,
        "stress_sharpe>0": st.get("sharpe_net", -9) > 0,
        "both_halves>0": p["sharpe_h1"] > 0 and p["sharpe_h2"] > 0,
        "boot_p05>0": p["boot_ann_mean_p05"] > 0,
        "dsr>0.95": (p["dsr"] or 0) > 0.95,
        "clause:years": cl["years_ok"],
        "clause:concentration": cl["concentration_ok"],
        "clause:sides": bool(cl["sides_ok"]),
        "clause:subperiods": cl["subperiods_ok"],
    }
    out["selected"] = best
    out["clause"] = cl
    out["verdict"] = {"verdict": "pass" if all(chk.values()) else "fail", "checks": chk}
    for c in out["configs"].values():
        c.pop("series", None)
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(
        json.dumps(out["verdict"]),
        "selected",
        best,
        "\npredictability",
        out["vol_predictability_spearman_by_year"],
    )
    for cid, c in out["configs"].items():
        q = c["primary"]
        print(
            cid,
            "sharpe",
            q.get("sharpe_net"),
            "ann",
            q.get("ann_return_net"),
            "stress",
            c["stress"].get("sharpe_net"),
            c["outcomes"],
        )
    print(
        {
            k: cl[k]
            for k in (
                "years_positive",
                "top_year_share_of_total",
                "long_net_sum",
                "short_net_sum",
                "subperiod_sums",
            )
        },
        cl["per_year"],
    )


main()
