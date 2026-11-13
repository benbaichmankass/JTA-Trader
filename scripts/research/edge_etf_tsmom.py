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
#: ATTEMPT-3 grid (lane orphans-legs 2026-11-13, unit RQ-20261113-62e3-03), picked by --grid 62e3. ONE factor: the return series.
#: A0 = E5 on the committed price-only closes (control; must reproduce 0.418); TR1 = E5 on TOTAL-RETURN closes = committed close x
#: the yfinance dividend factor (Adj Close / Close, both split-adjusted, so the factor carries distributions only). Signals, vol,
#: costs and the universe are unchanged; futures (MHG) carry no distributions and keep factor 1. The default grid ("d1f3") is the
#: ITER_ARMS object above with its committed prior count, so the committed d1f3-04 result reproduces on the default path.
ITER_GRIDS = {"d1f3": ITER_ARMS, "62e3": {"A0": dict(base="E5"), "TR1": dict(base="E5", series="total_return")}}
ITER_GRID_PRIOR = {"d1f3": ITER_PRIOR_TRIALS, "62e3": 9 + 5}
NO_DISTRIBUTIONS = {"MHG"}            # futures proxy: no dividend factor
PARITY_MAX_MEDIAN_ABS_BPS = 5.0       # yfinance Close vs committed close daily-return parity, per symbol (else INDETERMINATE)


def dividend_factor(close: pd.DataFrame, fetch=None):
    """Per-symbol dividend factor on the committed close index + a parity table. ``fetch(sym) -> DataFrame[Close, Adj Close]``
    (default: yfinance 1d, auto_adjust=False). Factor = Adj Close / Close, forward-filled onto the committed dates (never
    back-filled). Parity = median |daily return diff| (bps) between yfinance Close and the committed close on common dates."""
    if fetch is None:
        def fetch(sym):
            import yfinance as yf  # runner dependency (research-script-run installs it); imported only on this path
            d = yf.download(sym, start="2006-01-01", end="2024-07-01", auto_adjust=False, actions=False,
                            progress=False, threads=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            return d[["Close", "Adj Close"]]
    fac, parity = pd.DataFrame(1.0, index=close.index, columns=close.columns), {}
    for s in close.columns:
        if s in NO_DISTRIBUTIONS:
            parity[s] = {"state": "no_distributions"}
            continue
        try:
            d = fetch(s).dropna()
        except Exception as exc:  # a failed fetch is a stated read-state, never a silent factor of 1
            parity[s] = {"state": "fetch_failed", "error": str(exc)[:200]}
            continue
        if d.empty:
            parity[s] = {"state": "no_rows"}
            continue
        d.index = pd.DatetimeIndex(d.index).tz_localize("UTC") if pd.DatetimeIndex(d.index).tz is None else d.index.tz_convert("UTC")
        d.index = d.index.normalize()
        ci = close.index.normalize()
        f = (d["Adj Close"] / d["Close"]).reindex(ci, method="ffill")
        fac[s] = f.to_numpy()
        a = close[s].pct_change().set_axis(ci)
        b = d["Close"].pct_change().reindex(ci)
        diff = (a - b).abs().dropna()
        parity[s] = {"state": "ok" if len(diff) and float(diff.median()) * 1e4 <= PARITY_MAX_MEDIAN_ABS_BPS else "parity_failed",
                     "n_common": int(len(diff)), "median_abs_diff_bps": round(float(diff.median()) * 1e4, 3) if len(diff) else None,
                     "factor_first": round(float(f.dropna().iloc[0]), 5) if f.notna().any() else None,
                     "factor_coverage": round(float(f.notna().mean()), 4)}
    return fac.ffill(), parity
PRIMARY, SIDE_BPS, EVAL_A, EVAL_B = (
    "E5",
    2.0,
    pd.Timestamp("2008-01-01", tz="UTC"),
    pd.Timestamp("2020-06-01", tz="UTC"),
)


def run_iteration(a, close, ret, zero, grid="d1f3", fetch=None):
    arms = ITER_GRIDS[grid]
    n_cum = ITER_GRID_PRIOR[grid] + len(arms)
    D.EVAL_START = EVAL_A
    it = {"control": "A0", "n_arms": len(arms), "n_trials_cumulative": n_cum, "arms": {}}
    if grid != "d1f3":
        it["grid"] = grid
    tr = None
    if any(sp.get("series") == "total_return" for sp in arms.values()):
        fac, parity = dividend_factor(close, fetch)
        it["dividend_parity"] = parity
        bad = {k: v["state"] for k, v in parity.items() if v["state"] not in ("ok", "no_distributions")}
        if bad:  # the factor could not be established for a symbol: the arm would be part price-only -> INDETERMINATE, not a verdict
            vdoc = {"verdict": "indeterminate", "read_state": "insufficient", "n": None, "note": f"dividend factor not established: {bad}",
                    "population": f"etf tsmom iteration grid {grid}: dividend parity failed for {sorted(bad)}", "measurement": {"dividend_parity": parity}}
            D.write_run_outputs(a.out, {"iteration": it}, vdoc)
            print(json.dumps(vdoc["note"]))
            return 0
        tr = close * fac
    for aid, spec in arms.items():
        c = CONFIGS[spec["base"]]
        uni = spec.get("universe") or UNIVERSE
        px = tr if spec.get("series") == "total_return" else close
        ret = px.pct_change()
        W = D.tsmom_weights(px, zero.notna().astype(float), c, n_univ=len(uni), rebalance=c["reb"], max_lev=3.0,
                            vol_window=63, universe_fixed=uni)
        W = D.apply_gate(W, px, {"shorts_spy_dn": "shorts_btc_dn", "flat_spy_dn": "flat_btc_dn"}.get(spec.get("gate")), ref="SPY")
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
                         **({"grid": grid, "dividend_parity": it.get("dividend_parity")} if grid != "d1f3" else {}),
                         "arms": {k: {"spec": r["spec"], "sharpe": r["primary"].get("sharpe_net"), "h1": r["primary"].get("sharpe_h1"),
                                      "h2": r["primary"].get("sharpe_h2"), "dsr": r["primary"].get("dsr"),
                                      "stress_sharpe": r["stress"].get("sharpe_net"), "side_net_sum": r["side_net_sum"],
                                      "by_year_net_sum": r["by_year_net_sum"], "verdict": r["verdict"]["verdict"]}
                                  for k, r in it["arms"].items()}}
    what = "etf tsmom iteration" if grid == "d1f3" else f"etf tsmom iteration grid {grid}"
    D.write_run_outputs(a.out, {"iteration": it}, {**D.iteration_verdict(it, what, getattr(a, "expect_control_sharpe", None)),
                                                    "measurement": it["measurement"]})
    print(json.dumps({"passing_arms": it["passing_arms"], "delta_sharpe_vs_control": it["delta_sharpe_vs_control"]}, indent=1))
    return 0


def _self_test() -> int:
    ok = True

    def chk(label, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and bool(cond)
    chk("grids: default grid IS the committed d1f3 ITER_ARMS with its prior count",
        ITER_GRIDS["d1f3"] is ITER_ARMS and ITER_GRID_PRIOR["d1f3"] == ITER_PRIOR_TRIALS)
    chk("grids: every grid starts with control A0 on a registered config",
        all(list(g)[0] == "A0" and all(sp["base"] in CONFIGS for sp in g.values()) for g in ITER_GRIDS.values()))
    idx = pd.date_range("2020-01-01", periods=10, freq="B", tz="UTC")
    close = pd.DataFrame({"SPY": np.linspace(100, 109, 10), "MHG": np.linspace(3, 4, 10)}, index=idx)
    adj = close["SPY"].copy()
    adj.iloc[:5] = adj.iloc[:5] * 0.99                       # a 1% distribution paid between day 4 and day 5
    yf_df = pd.DataFrame({"Close": close["SPY"].to_numpy(), "Adj Close": adj.to_numpy()}, index=idx.tz_localize(None))
    fac, par = dividend_factor(close, fetch=lambda s: yf_df)
    tr = close * fac
    chk("dividend: the distribution day's total return = price return + 1% (to 1e-9)",
        abs(tr["SPY"].pct_change().iloc[5] - (close["SPY"].iloc[5] / close["SPY"].iloc[4] * (1 / 0.99) - 1)) < 1e-9)
    chk("dividend: non-distribution days are unchanged", abs(tr["SPY"].pct_change().iloc[3] - close["SPY"].pct_change().iloc[3]) < 1e-12)
    chk("dividend: futures proxy keeps factor 1", (fac["MHG"] == 1.0).all() and par["MHG"]["state"] == "no_distributions")
    chk("dividend: parity ok when yfinance Close == committed close", par["SPY"]["state"] == "ok")
    bad = yf_df.copy()
    bad["Close"] = bad["Close"] * np.linspace(1, 1.2, 10)
    chk("dividend: a mismatched Close fails parity", dividend_factor(close, fetch=lambda s: bad)[1]["SPY"]["state"] == "parity_failed")

    def boom(s):
        raise RuntimeError("no network")
    chk("dividend: a failed fetch is a stated state, never a silent factor 1", dividend_factor(close, fetch=boom)[1]["SPY"]["state"] == "fetch_failed")
    return 0 if ok else 1


def main():
    if "--self-test" in sys.argv:
        return _self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--series-dir", default=None)
    ap.add_argument("--iteration", action="store_true", help="run the pre-registered ITER_ARMS grid against E5 as control")
    ap.add_argument("--expect-control-sharpe", type=float, default=None,
                    help="--iteration: committed control net Sharpe; an A0 off by > D.CONTROL_DRIFT_TOL reads INDETERMINATE")
    ap.add_argument("--grid", choices=sorted(ITER_GRIDS), default="d1f3",
                    help="which pre-registered --iteration grid (default d1f3 = the committed attempt-2 grid; 62e3 = total-return arm)")
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
        return run_iteration(a, close, ret, zero, grid=a.grid)
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
