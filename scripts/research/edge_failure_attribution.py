#!/usr/bin/env python3
# wiring: manual-only - RESEARCH-EDGE failure attribution for units -01,-02,-05,-06,-07 (operator doctrine 2026-11-01: attribute before anything else).
"""Where was the return lost or made: gross vs funding vs cost, by side, year, month, symbol (and outcome mix for brackets)."""

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
from src.runtime import execution_costs as xc


def pieces(W, ret, F, side_bps):
    r, f = ret.reindex_like(W).fillna(0), F.reindex_like(W).fillna(0)
    gross, fund = W * r, W * f
    cost = W.diff().abs().fillna(0) * side_bps / 1e4
    return gross, fund, cost


def summarise(W, ret, F, side_bps, start):
    gross, fund, cost = pieces(W, ret, F, side_bps)
    net = gross - fund - cost
    m = net.index >= start
    g, fu, co, n = gross[m], fund[m], cost[m], net[m]
    sym = n.sum().sort_values()
    longm, shortm = (W[m] > 0), (W[m] < 0)
    mon = n.sum(axis=1).groupby([n.index.year, n.index.month]).sum()
    yr = n.sum(axis=1).groupby(n.index.year).sum()
    return {
        "total": {
            "gross": round(float(g.sum().sum()), 4),
            "funding_paid": round(float(fu.sum().sum()), 4),
            "cost": round(float(co.sum().sum()), 4),
            "net": round(float(n.sum().sum()), 4),
        },
        "by_side_net": {
            "long": round(float(n.where(longm, 0).sum().sum()), 4),
            "short": round(float(n.where(shortm, 0).sum().sum()), 4),
        },
        "by_year_net": {int(k): round(float(v), 4) for k, v in yr.items()},
        "worst_months": {
            f"{a}-{b:02d}": round(float(v), 4) for (a, b), v in mon.nsmallest(4).items()
        },
        "best_months": {
            f"{a}-{b:02d}": round(float(v), 4) for (a, b), v in mon.nlargest(4).items()
        },
        "worst_symbols": {k: round(float(v), 4) for k, v in sym.head(4).items()},
        "best_symbols": {k: round(float(v), 4) for k, v in sym.tail(4).items()},
        "gross_by_side_by_year": {
            int(y): {
                "long": round(
                    float(g.where(longm, 0).sum(axis=1)[g.index.year == y].sum()), 4
                ),
                "short": round(
                    float(g.where(shortm, 0).sum(axis=1)[g.index.year == y].sum()), 4
                ),
            }
            for y in sorted(set(g.index.year))
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--fred-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.data_root)
    out = {}
    P = D.load_panels(root / "klines_all.pkl")
    close, qv = P["close"], P["qv"]
    ret = close.pct_change()
    fee = xc.resolve_fee_bps_roundtrip("BTCUSDT")
    side = (fee + D.SLIP_BPS_RT) / 2
    ever = set()
    for t in range(0, len(close), 7):
        ever |= set(D.universe_at(qv, close, t, 20))
    F, _ = D.load_funding(sorted(ever), root)
    F = F.reindex(close.index)
    out["tsmom_T4"] = summarise(
        D.tsmom_weights(close, qv, D.TSMOM_CONFIGS["T4"]), ret, F, side, D.EVAL_START
    )
    out["xsec_X1"] = summarise(
        D.xsec_weights(close, qv, D.XSEC_CONFIGS["X1"]), ret, F, side, D.EVAL_START
    )
    # ETF E5
    U = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SLV", "GDX", "USO", "XLE", "MHG"]
    cols = {}
    for s in U:
        c = min(
            Path("comms/research").glob(f"**/data/{s}_D.csv"),
            key=lambda q: -q.stat().st_size,
        )
        d = pd.read_csv(c, parse_dates=["timestamp"], index_col="timestamp")
        d.index = (
            d.index.tz_convert("UTC")
            if d.index.tz is not None
            else d.index.tz_localize("UTC")
        )
        cols[s] = d["close"][~d.index.duplicated()]
    ec = pd.DataFrame(cols).sort_index()
    ec = ec[(ec.index <= D.END_DISCOVERY) & ec["SPY"].notna()]
    D.DAYS = 252
    zero = pd.DataFrame(0.0, index=ec.index, columns=ec.columns)
    We = D.tsmom_weights(
        ec,
        zero.notna().astype(float),
        dict(lb=[63, 126, 252], tv=0.10, lo=False),
        n_univ=len(U),
        rebalance=5,
        max_lev=3.0,
        vol_window=63,
        universe_fixed=U,
    )
    out["etf_E5"] = summarise(
        We, ec.pct_change(), zero, 2.0, pd.Timestamp("2008-01-01", tz="UTC")
    )
    # movement + vol-premium: exec the module bodies (their main() is guarded by being after the split)
    ns = {"__file__": str(Path("scripts/research/edge_movement_capture.py").resolve())}
    exec(
        open("scripts/research/edge_movement_capture.py").read().split("\ndef main")[0],
        ns,
    )
    ser, _ = pickle.load(open(root / "klines_1h.pkl", "rb"))
    rows = []
    for cid in ("BO1", "FD1g"):
        cfg = ns["CFG"][cid]
        for s in ns["UNIVERSE"]:
            df = ser[s]
            df = df[
                df.index
                <= D.END_DISCOVERY + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
            ]
            g = df.groupby(df.index.normalize())
            dd = pd.DataFrame(
                {
                    "o": g["open"].first(),
                    "h": g["high"].max(),
                    "lo": g["low"].min(),
                    "n": g["open"].size(),
                }
            )
            dd = dd[dd.n == 24]
            r = (dd.h - dd.lo) / dd.o
            v = None
            ew = []
            for i, x in enumerate(r.values):
                ew.append(np.nan if v is None or i < 30 else v)
                v = x if v is None else 0.94 * v + 0.06 * x
            dd["rh"] = ew
            med = dd.rh.rolling(60).median().shift(1)
            bars = {t: gb for t, gb in df.groupby(df.index.normalize())}
            for t, row in dd.iterrows():
                if t < D.EVAL_START or not np.isfinite(row.rh):
                    continue
                if cfg.get("gate") and not (np.isfinite(med[t]) and row.rh >= med[t]):
                    continue
                gb = bars[t]
                sim = ns["sim_day"](
                    gb.open.to_numpy(),
                    gb.high.to_numpy(),
                    gb.low.to_numpy(),
                    gb.close.to_numpy(),
                    row.rh,
                    cfg,
                )
                if sim is None:
                    continue
                ret_, d, why = sim
                rows.append((cid, s, t, d, why, ret_, ret_ - 14 / 1e4, row.rh))
    tr = pd.DataFrame(
        rows, columns=["cfg", "sym", "t", "d", "why", "gross", "net", "rh"]
    )
    mv = {}
    for cid, g in tr.groupby("cfg"):
        mv[cid] = {
            "n_trades": int(len(g)),
            "mean_gross_pct": round(float(g.gross.mean() * 100), 3),
            "mean_net_pct": round(float(g.net.mean() * 100), 3),
            "cost_pct_per_trade": 0.14,
            "outcome_mix": g.why.value_counts().to_dict(),
            "mean_net_pct_by_outcome": {
                k: round(float(v * 100), 3)
                for k, v in g.groupby("why").net.mean().items()
            },
            "by_side_mean_net_pct": {
                str(int(k)): round(float(v * 100), 3)
                for k, v in g.groupby("d").net.mean().items()
            },
            "by_year_mean_net_pct": {
                int(k): round(float(v * 100), 3)
                for k, v in g.groupby(g.t.dt.year).net.mean().items()
            },
            "by_symbol_mean_net_pct": {
                k: round(float(v * 100), 3)
                for k, v in g.groupby("sym").net.mean().items()
            },
            "by_rh_tercile_mean_net_pct": {
                str(k): round(float(v * 100), 3)
                for k, v in g.groupby(
                    pd.qcut(g.rh, 3, labels=["low", "mid", "high"]), observed=True
                )
                .net.mean()
                .items()
            },
        }
    out["movement"] = mv
    vp = {}
    ns2 = {"__file__": str(Path("scripts/research/edge_vol_premium.py").resolve())}
    exec(
        open("scripts/research/edge_vol_premium.py").read().split("\ndef main")[0], ns2
    )
    px, iv = ns2["load"]("comms/research", a.fred_dir)
    df2 = ns2["run_cfg"](px, iv, ns2["CFG"]["V2"], 1.0)
    vp["V2"] = {
        "n_obs": int(len(df2)),
        "by_underlying_net_sum": {
            k: round(float(v), 3) for k, v in df2.groupby("s").net.sum().items()
        },
        "by_pos_net_sum": {
            str(int(k)): round(float(v), 3)
            for k, v in df2.groupby("pos").net.sum().items()
        },
        "by_year_net_sum": {
            int(k): round(float(v), 3)
            for k, v in df2.groupby(pd.to_datetime(df2.t).dt.year).net.sum().items()
        },
        "mean_gap_when_long_var": round(float(df2[df2.pos > 0].gap.mean()), 4),
        "mean_y_when_long_var": round(float(df2[df2.pos > 0].y.mean()), 4),
        "mean_y_when_short_var": round(float(df2[df2.pos < 0].y.mean()), 4),
    }
    out["vol_premium"] = vp
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print("done", list(out))


main()
