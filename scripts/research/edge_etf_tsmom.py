#!/usr/bin/env python3
# wiring: manual-only - RESEARCH-EDGE unit RQ-20261101-58e4-05 (multi-asset ETF/futures-proxy TSMOM). Reuses edge_portfolio_discovery's engine.
"""Vol-targeted time-series momentum across liquid ETFs + a copper futures proxy, daily bars, discovery window ends 2024-06-30.

Data  : committed runner closes comms/research/*/data/<SYM>_D.csv (largest file per symbol; XLE only exists under RQ-20261025-bda2-01) (unadjusted closes, price return only:
        dividends/distributions are NOT included -- understates long carry on bonds/equity ETFs, flatters shorts; stated limitation).
Costs : commission-free ETFs; 2 bps per side slippage per unit |delta w| (stress 2x = 4 bps); no financing/borrow on shorts (stated, favours the strategy).
Rule  : research/queue/RQ-20261101-58e4-05.yaml (registered before the run).
"""

import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D

UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SLV", "GDX", "USO", "XLE", "MHG"]
CONFIGS = {
    "E1": dict(lb=[21], tv=0.10, lo=False, reb=5),
    "E2": dict(lb=[63], tv=0.10, lo=False, reb=5),
    "E3": dict(lb=[126], tv=0.10, lo=False, reb=5),
    "E4": dict(lb=[252], tv=0.10, lo=False, reb=5),
    "E5": dict(lb=[63, 126, 252], tv=0.10, lo=False, reb=5),  # PRIMARY
    "E6": dict(lb=[21, 63, 126], tv=0.10, lo=False, reb=5),
    "E7": dict(lb=[63, 126, 252], tv=0.10, lo=True, reb=5),
    "E8": dict(lb=[126, 252], tv=0.10, lo=False, reb=5),
    "E9": dict(lb=[63, 126, 252], tv=0.10, lo=False, reb=21),
}
EQUITY, NON_EQUITY = ["SPY", "QQQ", "IWM"], ["TLT", "IEF", "GLD", "SLV", "GDX", "USO", "XLE", "MHG"]
#: ITERATION arms (lane RESEARCH-OPS 2026-11-01): one factor from the primary E5, every arm counted; DSR N = 9 discovery configs + arms.
ITER_ARMS = {
    "A0": dict(base="E5"),                                   # control == discovery primary
    "C1": dict(base="E5", universe=EQUITY),                  # asset-class gating: equity ETFs only
    "C2": dict(base="E5", universe=NON_EQUITY),              # asset-class gating: rates / metals / energy / copper only
    "R1": dict(base="E5", gate="shorts_spy_dn"),             # regime: shorts only while SPY < its 200d mean
    "R2": dict(base="E5", gate="flat_spy_dn"),               # regime: whole book flat while SPY < its 200d mean
}
ITER_PRIOR_TRIALS = 9
PRIMARY, SIDE_BPS, EVAL_A, EVAL_B = (
    "E5",
    2.0,
    pd.Timestamp("2008-01-01", tz="UTC"),
    pd.Timestamp("2020-06-01", tz="UTC"),
)


def run_iteration(a, close, ret, zero):
    n_cum = ITER_PRIOR_TRIALS + len(ITER_ARMS)
    D.EVAL_START = EVAL_A
    it = {"control": "A0", "n_arms": len(ITER_ARMS), "n_trials_cumulative": n_cum, "arms": {}}
    for aid, spec in ITER_ARMS.items():
        c = CONFIGS[spec["base"]]
        uni = spec.get("universe") or UNIVERSE
        W = D.tsmom_weights(close, zero.notna().astype(float), c, n_univ=len(uni), rebalance=c["reb"], max_lev=3.0,
                            vol_window=63, universe_fixed=uni)
        W = D.apply_gate(W, close, {"shorts_spy_dn": "shorts_btc_dn", "flat_spy_dn": "flat_btc_dn"}.get(spec.get("gate")), ref="SPY")
        res = {"spec": {k: v for k, v in spec.items()}}
        for tag, m in (("primary", 1.0), ("stress", 2.0)):
            net, to, _ = D.net_from_weights(W, ret, zero, m, 0.0, per_side_bps=SIDE_BPS)
            res[tag] = D.metrics(net, to, n_cum)
            if tag == "primary":
                lo_n = D.net_from_weights(W.clip(lower=0.0), ret, zero, 1.0, 0.0, per_side_bps=SIDE_BPS)[0]
                sh_n = D.net_from_weights(W.clip(upper=0.0), ret, zero, 1.0, 0.0, per_side_bps=SIDE_BPS)[0]
                res["side_net_sum"] = {"long": round(float(lo_n[lo_n.index >= EVAL_A].sum()), 4),
                                       "short": round(float(sh_n[sh_n.index >= EVAL_A].sum()), 4)}
                yr = net[net.index >= EVAL_A]
                res["by_year_net_sum"] = {str(k): round(float(v), 4) for k, v in yr.groupby(yr.index.year).sum().items()}
        res["verdict"] = D.verdict("tsmom", res["primary"], res["stress"])
        it["arms"][aid] = res
    ctl = it["arms"]["A0"]["primary"]
    it["delta_sharpe_vs_control"] = {k: (round(r["primary"]["sharpe_net"] - ctl["sharpe_net"], 3)
                                         if r["primary"].get("state") == "computed" and ctl.get("state") == "computed" else None)
                                     for k, r in it["arms"].items() if k != "A0"}
    it["passing_arms"] = [k for k, r in it["arms"].items() if k != "A0" and r["verdict"]["verdict"] == "pass"]
    it["measurement"] = {"control": "A0", "delta_sharpe_vs_control": it["delta_sharpe_vs_control"], "passing_arms": it["passing_arms"],
                         "arms": {k: {"spec": r["spec"], "sharpe": r["primary"].get("sharpe_net"), "h1": r["primary"].get("sharpe_h1"),
                                      "h2": r["primary"].get("sharpe_h2"), "dsr": r["primary"].get("dsr"),
                                      "stress_sharpe": r["stress"].get("sharpe_net"), "side_net_sum": r["side_net_sum"],
                                      "by_year_net_sum": r["by_year_net_sum"], "verdict": r["verdict"]["verdict"]}
                                  for k, r in it["arms"].items()}}
    D.write_run_outputs(a.out, {"iteration": it}, {**D.iteration_verdict(it, "etf tsmom iteration"), "measurement": it["measurement"]})
    print(json.dumps({"passing_arms": it["passing_arms"], "delta_sharpe_vs_control": it["delta_sharpe_vs_control"]}, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--series-dir", default=None)
    ap.add_argument("--iteration", action="store_true", help="run the pre-registered ITER_ARMS grid against E5 as control")
    a = ap.parse_args()
    cols = {}
    for s in UNIVERSE:
        cands = sorted(
            Path(a.data_dir).glob(f"**/data/{s}_D.csv"), key=lambda q: -q.stat().st_size
        )  # longest committed history wins
        print(f"{s}: using {cands[0]}")  # the chosen input is printed, never silent
        d = pd.read_csv(cands[0], parse_dates=["timestamp"], index_col="timestamp")
        d.index = (
            d.index.tz_convert("UTC")
            if d.index.tz is not None
            else d.index.tz_localize("UTC")
        )
        cols[s] = d["close"][~d.index.duplicated()]
    close = pd.DataFrame(cols).sort_index()
    close = close[(close.index <= D.END_DISCOVERY) & close["SPY"].notna()]
    D.DAYS = 252
    ret = close.pct_change()
    zero = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    out = {
        "universe": UNIVERSE,
        "data_first": str(close.index[0].date()),
        "data_last": str(close.index[-1].date()),
        "rows": int(len(close)),
        "missing_by_symbol": close.isna().sum().to_dict(),
        "configs": {},
        "n_trials": len(CONFIGS),
        "primary": PRIMARY,
    }
    spy = ret["SPY"]
    if a.iteration:
        return run_iteration(a, close, ret, zero)
    for cid, c in CONFIGS.items():
        W = D.tsmom_weights(
            close,
            zero.notna().astype(float),
            c,
            n_univ=len(UNIVERSE),
            rebalance=c["reb"],
            max_lev=3.0,
            vol_window=63,
            universe_fixed=UNIVERSE,
        )
        res = {}
        for tag, m in (("primary", 1.0), ("stress", 2.0)):
            net, to, _ = D.net_from_weights(W, ret, zero, m, 0.0, per_side_bps=SIDE_BPS)
            D.EVAL_START = EVAL_A
            res[tag] = D.metrics(net, to, len(CONFIGS))
            if tag == "primary":
                D.EVAL_START = EVAL_B
                sub = D.metrics(net, to, len(CONFIGS))
                res["window_2020_06_to_2024_06"] = {
                    k: sub.get(k)
                    for k in ("n_days", "ann_return_net", "sharpe_net", "max_drawdown")
                }
                yr = net[net.index >= EVAL_A]
                res["by_year"] = (
                    ((1 + yr).groupby(yr.index.year).prod() - 1).round(4).to_dict()
                )
                if cid == PRIMARY:
                    res["corr_to_spy"] = round(
                        float(net[net.index >= EVAL_A].corr(spy.reindex(net.index))), 3
                    )
                    if a.series_dir:
                        Path(a.series_dir).mkdir(parents=True, exist_ok=True)
                        net.to_csv(
                            Path(a.series_dir) / "etf_tsmom_E5.csv", header=["net"]
                        )
        out["configs"][cid] = {"params": c, **res}
    D.EVAL_START = EVAL_A
    s = spy[spy.index >= EVAL_A]
    out["spy_buyhold_sharpe_primary_window_price_only"] = round(
        float(s.mean() / s.std() * np.sqrt(252)), 3
    )
    out["verdict"] = D.verdict(
        "tsmom", out["configs"][PRIMARY]["primary"], out["configs"][PRIMARY]["stress"]
    )
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["verdict"]))
    for cid, c in out["configs"].items():
        p = c["primary"]
        print(
            cid,
            "sharpe",
            p.get("sharpe_net"),
            "ann",
            p.get("ann_return_net"),
            "dd",
            p.get("max_drawdown"),
            "dsr",
            p.get("dsr"),
            "stress",
            c["stress"].get("sharpe_net"),
            "2020-24",
            c["window_2020_06_to_2024_06"].get("sharpe_net"),
        )


if __name__ == "__main__":
    sys.exit(main() or 0)
