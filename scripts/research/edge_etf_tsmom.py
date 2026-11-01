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
PRIMARY, SIDE_BPS, EVAL_A, EVAL_B = (
    "E5",
    2.0,
    pd.Timestamp("2008-01-01", tz="UTC"),
    pd.Timestamp("2020-06-01", tz="UTC"),
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--series-dir", default=None)
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


main()
