#!/usr/bin/env python3
# wiring: manual-only - RESEARCH-EDGE follow-up sensitivities on units RQ-20261101-58e4-02/-03 (manager request 2026-11-01). No new configs: the DSR trial counts stay 10 (xsec) and 8 (carry).
"""Dev-window (<= 2024-06-30) sensitivities, post-hoc and labelled so. They can only REMOVE a pass, never add one.

carry : C1 with (i) short-perp liquidation at a 25% margin buffer (24.5% after 0.5% maintenance) measured on the daily HIGH vs the
        run's reference close, no top-up; (ii) the same excursion handled by margin top-ups from spot with transfer friction;
        FTX-month and venue-default scenarios; net vs the 3-month T-bill (FRED DTB3) on the same capital.
xsec  : X1 ex-2021, ex the top-3 contributing symbols (zeroed, and re-formed without them).
"""
import json, math, pickle, sys, argparse
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D, edge_data as E
from src.runtime import execution_costs as xc

LIQ_THR = 0.25 - 0.005
LIQ_FEE = 0.01          # liquidation penalty + slippage on the closed perp leg, share of notional
TOPUP_STEP = 0.125      # top up spot->perp each time the adverse excursion reaches half the buffer
TRANSFER_BPS = 5.0      # per transferred notional (operational/transfer friction, ASSUMPTION)


def met(s, n):  # metrics on a daily series, restricted from EVAL_START
    m = D.metrics(s, pd.Series(0.0, index=s.index), n)
    return {k: m.get(k) for k in ("state", "n_days", "ann_return_net", "sharpe_net", "max_drawdown", "worst_month", "sharpe_h1", "sharpe_h2", "dsr")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--data-root", required=True); ap.add_argument("--series-dir", required=True)
    ap.add_argument("--tbill", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
    root = Path(a.data_root)
    P = D.load_panels(root / "klines_all.pkl"); close, qv = P["close"], P["qv"]
    ser, _ = pickle.load(open(root / "klines_all.pkl", "rb"))
    high = pd.DataFrame({s: d["high"] for s, d in ser.items()}).reindex(close.index)
    ret = close.pct_change(); fee_rt = xc.resolve_fee_bps_roundtrip("BTCUSDT")
    ever = set()
    for t in range(0, len(close), 7):
        ever |= set(D.universe_at(qv, close, t, 20))
    F, _ = D.load_funding(sorted(ever), root); F = F.reindex(close.index)
    out = {"label": "post-hoc dev-window sensitivities; no new configs; DSR counts unchanged"}

    # ---------------- carry
    sp = E.fetch(sorted(ever), root, kinds=("k",), workers=48, market="spot"); sser, _ = E.assemble(sp, "k")
    sclose = pd.DataFrame({s: d["close"] for s, d in sser.items()}); sclose = sclose[sclose.index <= D.END_DISCOVERY].reindex(close.index)
    sret = sclose.pct_change()
    W = D.carry_weights(close, sclose, qv, F, D.CARRY_CONFIGS["C1"])
    Fz = F.reindex(columns=close.columns)
    net, to, _ = D.net_from_weights(-W, ret, Fz, 1.0, fee_rt, per_side_bps=D.CARRY_PER_SIDE_BPS)
    base = (net + (W * sret.reindex_like(W).fillna(0)).sum(axis=1)) / D.CARRY_CAP_FACTOR
    # excursion events per symbol-run
    drag_liq = pd.Series(0.0, index=W.index); drag_top = pd.Series(0.0, index=W.index)
    ev_liq = ev_top = 0; run_ref = {}
    cols = list(W.columns)
    for t in range(1, len(W)):
        for s in cols:
            w = W.iloc[t][s]
            if w <= 0: run_ref.pop(s, None); continue
            ref = run_ref.setdefault(s, close[s].iloc[t - 1])
            h = high[s].iloc[t]
            if not np.isfinite(h) or not np.isfinite(ref) or ref <= 0: continue
            exc = h / ref - 1
            if exc >= LIQ_THR:
                ev_liq += 1
                drag_liq.iloc[t] += w * (LIQ_FEE + 2 * D.CARRY_PER_SIDE_BPS / 1e4) / D.CARRY_CAP_FACTOR
                run_ref[s] = close[s].iloc[t]
            k = int(exc // TOPUP_STEP)
            if k >= 1:
                ev_top += k
                drag_top.iloc[t] += w * k * TOPUP_STEP * TRANSFER_BPS / 1e4 / D.CARRY_CAP_FACTOR
                run_ref[s] = close[s].iloc[t]
    tb = pd.read_csv(a.tbill, index_col=0, parse_dates=True)["DTB3"].replace(".", np.nan).astype(float).ffill()
    tb.index = tb.index.tz_localize("UTC"); tbd = (tb / 100 / 365).reindex(base.index).ffill()
    def win(s, a0, b0): return s[(s.index >= a0) & (s.index <= b0)]
    post = ("2022-01-01", "2024-06-30")
    variants = {"C1_base": base, "C1_liquidation_no_topup": base - drag_liq, "C1_topup_with_friction": base - drag_top}
    out["carry"] = {"events": {"liquidations_symbol_runs": ev_liq, "topup_increments": ev_top, "assumptions": {"liq_threshold": LIQ_THR, "liq_fee": LIQ_FEE, "topup_step": TOPUP_STEP, "transfer_bps": TRANSFER_BPS}}, "variants": {}}
    for k, s in variants.items():
        p = win(s, *post); c = win(tbd, *post)
        eq = (1 + p).prod() ** (365 / len(p)) - 1; cq = (1 + c).prod() ** (365 / len(c)) - 1
        ex = p - c
        out["carry"]["variants"][k] = {"full": met(s, 8), "post2021_ann_net": round(float(eq), 4), "post2021_tbill_ann": round(float(cq), 4),
            "post2021_excess_ann": round(float(eq - cq), 4), "post2021_excess_sharpe": round(float(ex.mean() / ex.std(ddof=1) * math.sqrt(365)), 3),
            "by_year_net": ((1 + s[s.index >= D.EVAL_START]).groupby(s[s.index >= D.EVAL_START].index.year).prod() - 1).round(4).to_dict()}
    nov = base[(base.index >= "2022-11-01") & (base.index <= "2022-11-30")]
    out["carry"]["ftx_nov2022"] = {"C1_month_return_measured": round(float((1 + nov).prod() - 1), 5), "worst_day": round(float(nov.min()), 5),
        "venue_default_scenario": {"loss_if_100pct_of_capital_on_defaulting_venue_recovery_0": -1.0, "recovery_50pct": -0.5,
        "note": "scenario, not measured: the archive has no venue-failure data. One such event erases roughly the cumulative post-2021 carry many times over; sizing/venue split is the only mitigation."}}

    # ---------------- xsec
    cfg = D.XSEC_CONFIGS["X1"]
    Wx = D.xsec_weights(close, qv, cfg)
    ew = None
    netx, _, _ = D.net_from_weights(Wx, ret, F, 1.0, fee_rt)
    series_x = pd.read_csv(Path(a.series_dir) / "xsec_X1.csv", index_col=0, parse_dates=True)["net"]
    assert np.allclose(series_x.reindex(netx.index).fillna(0), netx.fillna(0), atol=1e-9), "X1 reproduction mismatch"
    side = (D.CARRY_PER_SIDE_BPS * 0 + (fee_rt + D.SLIP_BPS_RT) / 2) / 1e4
    contrib = (Wx * ret.reindex_like(Wx).fillna(0) - Wx * F.reindex_like(Wx).fillna(0) - Wx.diff().abs().fillna(0) * side)
    contrib = contrib[contrib.index >= D.EVAL_START].sum().sort_values(ascending=False)
    top3 = list(contrib.index[:3])
    ex21 = netx[(netx.index.year != 2021) & (netx.index >= D.EVAL_START)]
    out["xsec"] = {"X1_full": met(netx, 10), "top3_contributors": {s: round(float(contrib[s]), 4) for s in top3},
                   "sum_contrib_all": round(float(contrib.sum()), 4)}
    out["xsec"]["ex_2021"] = met(ex21, 10)
    ex21b = ex21  # annualisation of a gapped series is the mean of daily returns, as metrics() does
    Wz = Wx.copy(); Wz[top3] = 0.0
    nz, _, _ = D.net_from_weights(Wz, ret, F, 1.0, fee_rt); out["xsec"]["ex_top3_zeroed"] = met(nz, 10)
    keep = [c for c in close.columns if c not in top3]
    Wr = D.xsec_weights(close[keep], qv[keep], cfg)
    nr, _, _ = D.net_from_weights(Wr, ret[keep], F.reindex(columns=keep), 1.0, fee_rt); out["xsec"]["ex_top3_reformed"] = met(nr, 10)
    out["xsec"]["ex_2021_and_top3_reformed"] = met(nr[nr.index.year != 2021], 10)
    Path(a.out).write_text(json.dumps(out, indent=1, default=str)); print(json.dumps(out, indent=1, default=str))

main()
