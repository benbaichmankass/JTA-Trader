#!/usr/bin/env python3
# wiring: manual-only - RESEARCH-EDGE unit RQ-20261101-58e4-07 (implied-vs-forecast volatility, variance-swap proxy on liquid ETFs).
"""Does (EWMA realised-vol forecast - CBOE 30d implied vol) predict the sign of the variance-swap P&L, and is trading it net of cost robust?

IMPLIED vol : CBOE vol indices from FRED fredgraph.csv (keyless): VIXCLS->SPY, VXNCLS->QQQ, RVXCLS->IWM, GVZCLS->GLD, OVXCLS->USO, VXSLVCLS->SLV.
              TLT has NO keyless IV history (TYVIX/VXTLT are 404 on FRED): not tested, filed as a data gap.
FORECAST    : sqrt(EWMA(lambda) of daily squared returns, through t-1) x sqrt(252), from the committed runner ETF closes.
PAYOFF PROXY: a long variance-swap at strike IV_t: y = (RV^2 - IV^2) / IV^2 over the next h trading days (RV = realised from closes).
              NOT a straddle price: actual option bid/ask, skew and vega/gamma path are NOT modelled. Cost haircut per trade (registered):
              round trip 1 vol point on IV => (2*IV*0.01 + 0.0001)/IV^2 of variance. Position s = +1 (long variance) if F - IV > thr, -1 if < -thr, else 0.
Portfolio   : equal-weight across underlyings; samples every h days (non-overlapping). Return unit = variance-premium units (Sharpe is scale-free).
"""

import argparse
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D
import regime_robustness as RR

MAP = {
    "SPY": "VIXCLS",
    "QQQ": "VXNCLS",
    "IWM": "RVXCLS",
    "GLD": "GVZCLS",
    "USO": "OVXCLS",
    "SLV": "VXSLVCLS",
}
CFG = {
    f"V{i + 1}": dict(lam=lam, thr=t, h=h)
    for i, (lam, t, h) in enumerate(
        [
            (0.94, 0.0, 21),
            (0.94, 0.02, 21),
            (0.97, 0.0, 21),
            (0.97, 0.02, 21),
            (0.94, 0.0, 63),
            (0.94, 0.02, 63),
            (0.97, 0.0, 63),
            (0.97, 0.02, 63),
        ]
    )
}
#: ITERATION arms (lane RESEARCH-OPS 2026-11-01), chosen from research/levers/vol-premium-proxy.yaml: the signal LOSES on its long-variance
#: side and an always-short-variance baseline earns more than the signal, so the premium is the base rate. One factor from the control
#: (V2 = the discovery best): replace the signal with always-short (S0), then add a TAIL GATE (flat when the underlying's IV is above its
#: own trailing-252d q-quantile; decision-time, history strictly before t). Every arm counted; DSR N = 8 discovery configs + these.
ITER_CFG = {
    "A0": dict(lam=0.94, thr=0.02, h=21),
    "S0": dict(lam=0.94, thr=0.02, h=21, mode="short_always"),
    "S1": dict(lam=0.94, thr=0.02, h=21, mode="short_always", tail_q=0.8),
    "S2": dict(lam=0.94, thr=0.02, h=21, mode="short_always", tail_q=0.9),
}
START, END = pd.Timestamp("2008-07-01", tz="UTC"), pd.Timestamp("2024-06-30", tz="UTC")


def load(data_dir, fred_dir):
    px, iv = {}, {}
    for s, f in MAP.items():
        c = sorted(
            Path(data_dir).glob(f"**/data/{s}_D.csv"), key=lambda q: -q.stat().st_size
        )[0]
        print(f"{s}: prices {c}; IV {f}")
        d = pd.read_csv(c, parse_dates=["timestamp"], index_col="timestamp")
        d.index = (
            d.index.tz_convert("UTC")
            if d.index.tz is not None
            else d.index.tz_localize("UTC")
        )
        px[s] = d["close"][~d.index.duplicated()]
        fp = Path(fred_dir) / f"{f}.csv"
        if not fp.is_file():                       # public FRED series, no key: fetch when the dir was not pre-filled
            import urllib.request
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={f}", timeout=60).read())
        v = pd.read_csv(fp)
        v = v.set_index(pd.to_datetime(v.iloc[:, 0], utc=True)).iloc[:, 1]
        iv[s] = pd.to_numeric(v, errors="coerce") / 100.0
    return px, iv


def run_cfg(px, iv, cfg, mult):
    rows = []
    for s in MAP:
        c = px[s][px[s].index <= END]
        r = c.pct_change().dropna()
        var = (r**2).ewm(alpha=1 - cfg["lam"], adjust=False).mean().shift(
            1
        ) * 252  # through t-1 only
        idx = [t for t in c.index if t >= START][:: cfg["h"]]
        for t in idx:
            i = c.index.get_loc(t)
            if (
                i + cfg["h"] >= len(c)
                or t not in iv[s].index
                or not np.isfinite(iv[s].get(t, np.nan))
                or t not in var.index
            ):
                continue
            K = float(iv[s][t])
            F = math.sqrt(var[t])
            rr = (
                r.iloc[i - 0 : i + cfg["h"] - 0]
                if False
                else c.iloc[i : i + cfg["h"] + 1].pct_change().dropna()
            )
            RV = math.sqrt((rr**2).mean() * 252)
            y = (RV**2 - K**2) / K**2
            gap = F - K
            pos = 1 if gap > cfg["thr"] else (-1 if gap < -cfg["thr"] else 0)
            if cfg.get("mode") == "short_always":
                pos = -1
            if cfg.get("tail_q") is not None and pos != 0:
                hist = iv[s][iv[s].index < t].dropna().tail(252)
                if len(hist) >= 100 and K > float(hist.quantile(cfg["tail_q"])):
                    pos = 0
            cost = (2 * K * 0.01 + 1e-4) / K**2 * mult if pos != 0 else 0.0
            rows.append((t, s, pos, y, pos * y - abs(pos) * cost, gap))
    df = pd.DataFrame(rows, columns=["t", "s", "pos", "y", "net", "gap"])
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--fred-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--iteration", action="store_true", help="run ITER_CFG (control + always-short + tail-gated) instead of CFG")
    a = ap.parse_args()
    CFGS = ITER_CFG if a.iteration else CFG
    NT = (len(CFG) + len(ITER_CFG)) if a.iteration else len(CFG)      # cumulative trials: discovery configs + these arms
    px, iv = load(a.data_dir, a.fred_dir)
    out = {
        "underlyings": list(MAP),
        "tlt": "no keyless IV history (FRED TYVIX/VXTLT 404) - not tested",
        "configs": {},
        "n_trials": NT,
    }
    D.EVAL_START = START
    for cid, cfg in CFGS.items():
        res = {}
        for tag, mult in (("primary", 1.0), ("stress", 2.0)):
            df = run_cfg(px, iv, cfg, mult)
            per = df.groupby(
                "t"
            ).net.mean()  # equal weight across underlyings available that date
            full = pd.Series(0.0, index=pd.DatetimeIndex(sorted(df.t.unique())))
            full[per.index] = per
            # re-index to daily so metrics' annualisation (DAYS) is right: spread each h-day P&L on its start day, zero elsewhere is NOT used; use period Sharpe
            n = len(full)
            mu, sd = full.mean(), full.std(ddof=1)
            ppy = 252 / cfg["h"]
            sr = mu / sd * math.sqrt(ppy)
            half = n // 2
            h1, h2 = full.iloc[:half], full.iloc[half:]

            rng = np.random.default_rng(5)
            bs = np.array([rng.choice(full.to_numpy(), n).mean() for _ in range(2000)])
            import trial_ledger

            d = trial_ledger.dsr([float(x) for x in full.to_numpy()], NT)
            res[tag] = {
                "n_periods": n,
                "sharpe_net": round(float(sr), 3),
                "mean_net": round(float(mu), 5),
                "sharpe_h1": round(
                    float(h1.mean() / h1.std(ddof=1) * math.sqrt(ppy)), 3
                ),
                "sharpe_h2": round(
                    float(h2.mean() / h2.std(ddof=1) * math.sqrt(ppy)), 3
                ),
                "boot_p05_mean": round(float(np.percentile(bs, 5)), 5),
                "dsr": d.get("dsr"),
                "hit_rate_sign_vs_realised": round(
                    float(((df.pos * df.y) > 0)[df.pos != 0].mean()), 3
                ),
                "frac_long_var": round(float((df.pos > 0).mean()), 3),
                "frac_short_var": round(float((df.pos < 0).mean()), 3),
            }
            if tag == "primary":
                lg = (
                    df.assign(v=np.where(df.pos > 0, df.net, 0.0)).groupby("t").v.mean()
                )
                sh = (
                    df.assign(v=np.where(df.pos < 0, df.net, 0.0)).groupby("t").v.mean()
                )
                res["_series"] = (
                    full,
                    lg.reindex(full.index).fillna(0.0),
                    sh.reindex(full.index).fillna(0.0),
                )
                res["_df"] = df
        out["configs"][cid] = res
    best = max(out["configs"], key=lambda k: out["configs"][k]["primary"]["sharpe_net"])
    full, lg, sh = out["configs"][best]["_series"]
    df = out["configs"][best]["_df"]
    cl = RR.clause(full, lg, sh, two_sided=True)
    # always-short-variance baseline (the known variance risk premium) for context
    base = df.assign(b=-df.y).groupby("t").b.mean()
    out["context_always_short_var_mean_gross"] = round(float(base.mean()), 5)
    p, st = out["configs"][best]["primary"], out["configs"][best]["stress"]
    chk = {
        "sharpe>=0.5": p["sharpe_net"] >= 0.5,
        "stress_sharpe>0": st["sharpe_net"] > 0,
        "both_halves>0": p["sharpe_h1"] > 0 and p["sharpe_h2"] > 0,
        "boot_p05>0": p["boot_p05_mean"] > 0,
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
        c.pop("_series", None)
        c.pop("_df", None)
    if a.iteration:
        ctl_sh = out["configs"]["A0"]["primary"]["sharpe_net"]
        non_ctl_pass = out["verdict"]["verdict"] == "pass" and best != "A0"
        meas = {"control": "A0", "selected": best, "arms": {k: {"spec": CFGS[k], "sharpe": c["primary"]["sharpe_net"],
                "delta_sharpe_vs_control": round(c["primary"]["sharpe_net"] - ctl_sh, 3), "h1": c["primary"]["sharpe_h1"],
                "h2": c["primary"]["sharpe_h2"], "stress_sharpe": c["stress"]["sharpe_net"], "dsr": c["primary"]["dsr"],
                "frac_short_var": c["primary"]["frac_short_var"], "frac_long_var": c["primary"]["frac_long_var"]}
                for k, c in out["configs"].items()}, "checks_of_selected": out["verdict"]["checks"]}
        vdoc = {"verdict": "pass" if non_ctl_pass else "fail", "read_state": "measured", "n": out["configs"][best]["primary"]["n_periods"],
                "population": f"vol-premium iteration: {len(CFGS)} arms incl. control A0, {len(MAP)} underlyings, 21d periods, {START.date()}..{END.date()}, DSR N_cum={NT}",
                "note": f"selected {best}; passes the unchanged registered rule: {non_ctl_pass}", "measurement": meas}
        D.write_run_outputs(a.out, out, vdoc)
    else:
        Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["verdict"]), "selected", best)
    for cid, c in out["configs"].items():
        q = c["primary"]
        print(
            cid,
            "sharpe",
            q["sharpe_net"],
            "mean",
            q["mean_net"],
            "hit",
            q["hit_rate_sign_vs_realised"],
            "stress",
            c["stress"]["sharpe_net"],
            "dsr",
            q["dsr"],
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
        }
    )
    print(cl["per_year"])


if __name__ == "__main__":
    main()
