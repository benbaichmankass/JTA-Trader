#!/usr/bin/env python3
# wiring: manual-only - run by a RESEARCH-EDGE session for units RQ-TSMOM-PORTFOLIO-DISCOVERY, RQ-XSEC-MOM-DISCOVERY and the funding-carry discovery unit.
"""Portfolio-level discovery for the three families with a documented payer (lane RESEARCH-EDGE, 2026-11-01).

Families (mechanism and rule are registered in the three research/queue units BEFORE the first run; this file's
``REGISTERED`` dict is the same text and a test in the unit's ``decision_rule`` points at it):

  tsmom  : vol-targeted time-series momentum across the point-in-time top-20 USD-M perps (+ liquid ETFs if data).
  xsec   : weekly cross-sectional crypto momentum, long-short and long-only, point-in-time top-20 perps.
  carry  : delta-neutral spot-long / perp-short funding carry, point-in-time top-N perps that also have spot.

Data   : Binance Vision monthly archive (USD-M perp 1d klines, settled fundingRate, spot 1d klines). Bybit is the
         venue the book trades; Binance is the only public archive reachable here (same USDT-margined perp design,
         the proxy `fetch_binance_vision.py` already documents). Discovery window ends 2024-06-30 (HOLDOUT-LOCK):
         ``edge_data.MAX_MONTH`` makes loading anything later impossible.
Costs  : fee round trip = ``execution_costs.resolve_fee_bps_roundtrip`` (measured 11.0 bps perp), charged PER SIDE
         (RT/2 per unit of |delta weight|, exact for open+close); slippage 3 bps RT (above the measured 0.87 for
         the large caps, deliberately generous for alts); funding = the SIGNED settled series. STRESS arm = 2x
         fee+slippage (this equals the older harness convention of charging a full round trip on every |delta w|).
Returns: daily fractional portfolio return on capital. NOT stop-distance R.
Trials : every config run is counted (n_trials = len(configs)); DSR is ``trial_ledger.dsr`` with that N.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
for p in (str(_REPO), str(_REPO / "scripts" / "research")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.runtime import execution_costs  # noqa: E402
import trial_ledger  # noqa: E402

END_DISCOVERY = pd.Timestamp("2024-06-30", tz="UTC")
EVAL_START = pd.Timestamp("2020-06-01", tz="UTC")   # first day any lookback (<=224d) can exist for BTC/ETH (archive starts 2019-09)
DAYS = 365
SLIP_BPS_RT = 3.0
STABLE_BASES = ("USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "USDT", "EUR", "UST", "USDS")

REGISTERED = {
    "tsmom": {"primary": "T4", "n_universe": 20,
              "rule": "PASS iff PRIMARY net Sharpe>=0.5 AND stress(2x cost) net Sharpe>0 AND net Sharpe>0 in BOTH halves AND "
                      "bootstrap 5th-pct of annualised mean net return>0 AND DSR(primary; N=configs run)>0.95. "
                      "Else FAIL. Data coverage short => indeterminate."},
    "xsec": {"primary": "X1", "n_universe": 20,
             "rule": "Same thresholds as tsmom. Long-short graded on its own net return; long-only graded on net return "
                     "MINUS the equal-weight universe benchmark (same rebalance, same cost). PRIMARY is X1 (L=28, q=0.3, long-short)."},
    "carry": {"primary": "C1", "n_universe": 10,
              "rule": "PASS iff PRIMARY net annualised return>0 AND net Sharpe>=1.0 AND stress(2x cost) annualised return>0 AND "
                      "worst calendar month>-5% AND both halves net return>0 AND DSR(primary; N=configs run)>0.95. Else FAIL."},
}


# ----------------------------------------------------------------------------- data
def load_panels(klines_pkl: Path) -> Dict[str, pd.DataFrame]:
    ser, manifest = pickle.load(open(klines_pkl, "rb"))
    close = pd.DataFrame({s: d["close"] for s, d in ser.items()})
    qv = pd.DataFrame({s: d["quote_volume"] for s, d in ser.items()})
    close = close[close.index <= END_DISCOVERY]
    qv = qv[qv.index <= END_DISCOVERY]
    assert close.index.max() <= END_DISCOVERY, "HOLDOUT-LOCK: data past 2024-06-30 loaded"
    return {"close": close, "qv": qv, "manifest": manifest}


def is_stable(sym: str) -> bool:
    base = sym[:-4] if sym.endswith("USDT") else sym
    return any(base == b or base.startswith(b) and len(base) <= len(b) + 1 for b in STABLE_BASES)


def universe_at(qv: pd.DataFrame, close: pd.DataFrame, t: int, n: int, window: int = 90,
                require: Optional[set] = None) -> List[str]:
    """Top-n by trailing mean quote volume over the ``window`` days ending t-1 (point-in-time).
    Needs a full ``window`` of volume history and a close at t-1."""
    if t - window < 0:
        return []
    seg = qv.iloc[t - window:t]
    ok = seg.notna().sum() >= window
    ok &= close.iloc[t - 1].notna()
    cols = [c for c in seg.columns[ok.values] if not is_stable(c) and (require is None or c in require)]
    if not cols:
        return []
    r = seg[cols].mean().sort_values(ascending=False)
    return list(r.index[:n])


# ----------------------------------------------------------------------------- metrics
def stationary_bootstrap_mean(x: np.ndarray, reps: int = 2000, block: int = 10, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    out = np.empty(reps)
    for k in range(reps):
        idx = np.empty(n, dtype=int)
        i = 0
        while i < n:
            s = rng.integers(0, n)
            L = min(rng.geometric(1.0 / block), n - i)
            idx[i:i + L] = (s + np.arange(L)) % n
            i += L
        out[k] = x[idx].mean()
    return out


def metrics(r: pd.Series, turnover: pd.Series, n_trials: int) -> Dict[str, Any]:
    r = r.dropna()
    r = r[r.index >= EVAL_START]
    n = len(r)
    if n < 200 or r.std() == 0:
        return {"state": "insufficient", "n_days": n}
    mu, sd = r.mean(), r.std(ddof=1)
    eq = (1 + r).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    mon = (1 + r).groupby([r.index.year, r.index.month]).prod() - 1
    half = n // 2
    h1, h2 = r.iloc[:half], r.iloc[half:]
    bs = stationary_bootstrap_mean(r.to_numpy())
    d = trial_ledger.dsr([float(v) for v in r.to_numpy()], n_trials)
    to = turnover[turnover.index >= EVAL_START]
    return {
        "state": "computed", "n_days": n, "first": str(r.index[0].date()), "last": str(r.index[-1].date()),
        "ann_return_net": round(float(mu * DAYS), 4), "ann_vol": round(float(sd * math.sqrt(DAYS)), 4),
        "sharpe_net": round(float(mu / sd * math.sqrt(DAYS)), 3),
        "max_drawdown": round(dd, 4), "worst_month": round(float(mon.min()), 4),
        "sharpe_h1": round(float(h1.mean() / h1.std(ddof=1) * math.sqrt(DAYS)), 3),
        "sharpe_h2": round(float(h2.mean() / h2.std(ddof=1) * math.sqrt(DAYS)), 3),
        "ann_return_h1": round(float(h1.mean() * DAYS), 4), "ann_return_h2": round(float(h2.mean() * DAYS), 4),
        "boot_ann_mean_p05": round(float(np.percentile(bs, 5) * DAYS), 4),
        "turnover_per_year": round(float(to.sum() / (n / DAYS)), 2),
        "dsr": d.get("dsr"), "psr_n1": d.get("psr_n1"), "dsr_state": d.get("state"), "n_trials": n_trials,
    }


# ----------------------------------------------------------------------------- engine (weights -> net returns)
def net_from_weights(W: pd.DataFrame, R: pd.DataFrame, F: pd.DataFrame, cost_mult: float, fee_rt: float,
                     basis: Optional[pd.DataFrame] = None, cap_factor: float = 1.0,
                     per_side_bps: Optional[float] = None):
    """W: target weight per symbol-day (weight applied to that day's return). R: perp close-to-close return.
    F: summed settled funding rate per day (long pays). basis: extra per-unit-weight daily pnl (carry spot leg)."""
    W = W.fillna(0.0)
    Rv = R.reindex_like(W).fillna(0.0)
    Fv = F.reindex_like(W).fillna(0.0)
    gross = (W * Rv).sum(axis=1)
    fund = (W * Fv).sum(axis=1)          # long pays, short receives
    dW = W.diff().abs().fillna(0.0)
    side_bps = per_side_bps if per_side_bps is not None else (fee_rt + SLIP_BPS_RT) / 2.0
    cost = dW.sum(axis=1) * side_bps * cost_mult / 1e4
    extra = (W * basis.reindex_like(W).fillna(0.0)).sum(axis=1) if basis is not None else 0.0
    net = (gross + extra - fund - cost) / cap_factor
    return net, dW.sum(axis=1), {"gross": float(gross.sum()), "funding": float(fund.sum()), "cost": float(cost.sum())}


def realised_vol(ret: pd.DataFrame, window: int) -> pd.DataFrame:
    return ret.rolling(window).std(ddof=0).shift(1) * math.sqrt(DAYS)   # data through t-1 only


# ----------------------------------------------------------------------------- TSMOM
TSMOM_CONFIGS = {
    # id: lookbacks, sleeve target vol, long_only, universe-kind
    "T1": dict(lb=[28], tv=0.40, lo=False), "T2": dict(lb=[56], tv=0.40, lo=False),
    "T3": dict(lb=[112], tv=0.40, lo=False), "T4": dict(lb=[28, 56, 112], tv=0.40, lo=False),
    "T5": dict(lb=[14, 28, 56], tv=0.40, lo=False), "T6": dict(lb=[28, 56, 112, 224], tv=0.40, lo=False),
    "T7": dict(lb=[56], tv=0.40, lo=True), "T8": dict(lb=[28, 56, 112], tv=0.40, lo=True),
    "T9": dict(lb=[28, 56, 112], tv=0.20, lo=False),
    # T10 = primary signal on the liquid-ETF universe; only run when ETF daily data is supplied
    "T10": dict(lb=[28, 56, 112], tv=0.40, lo=False, etf=True),
}


def tsmom_weights(close, qv, cfg, n_univ=20, rebalance=7, max_lev=2.0, vol_window=30, universe_fixed=None):
    ret = close.pct_change()
    vol = realised_vol(ret, vol_window)
    days = close.index
    W = pd.DataFrame(0.0, index=days, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    for t in range(len(days)):
        if t % rebalance == 0:
            cur = pd.Series(0.0, index=close.columns)
            uni = universe_fixed if universe_fixed is not None else universe_at(qv, close, t, n_univ)
            for s in uni:
                sc = []
                for L in cfg["lb"]:
                    if t - 1 - L < 0:
                        sc = None
                        break
                    a, b = close[s].iloc[t - 1], close[s].iloc[t - 1 - L]
                    if not (a > 0 and b > 0):
                        sc = None
                        break
                    sc.append(np.sign(a / b - 1))
                v = vol[s].iloc[t]
                if sc is None or not np.isfinite(v) or v <= 0:
                    continue
                score = float(np.mean(sc))
                if cfg["lo"]:
                    score = max(score, 0.0)
                cur[s] = score * min(max_lev, cfg["tv"] / v) / max(len(uni), 1)
        W.iloc[t] = cur.values
    return W


# ----------------------------------------------------------------------------- XSEC
XSEC_CONFIGS = {
    "X1": dict(L=28, skip=0, q=0.3, mode="ls", wt="eq"), "X2": dict(L=14, skip=0, q=0.3, mode="ls", wt="eq"),
    "X3": dict(L=56, skip=0, q=0.3, mode="ls", wt="eq"), "X4": dict(L=84, skip=0, q=0.3, mode="ls", wt="eq"),
    "X5": dict(L=28, skip=7, q=0.3, mode="ls", wt="eq"), "X6": dict(L=28, skip=0, q=0.3, mode="lo", wt="eq"),
    "X7": dict(L=14, skip=0, q=0.3, mode="lo", wt="eq"), "X8": dict(L=56, skip=0, q=0.3, mode="lo", wt="eq"),
    "X9": dict(L=28, skip=0, q=0.3, mode="ls", wt="ivol"), "X10": dict(L=28, skip=0, q=0.2, mode="ls", wt="eq"),
}


def xsec_weights(close, qv, cfg, n_univ=20, rebalance=7, vol_window=30, ew_benchmark=False):
    ret = close.pct_change()
    vol = realised_vol(ret, vol_window)
    days = close.index
    W = pd.DataFrame(0.0, index=days, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    for t in range(len(days)):
        if t % rebalance == 0:
            cur = pd.Series(0.0, index=close.columns)
            uni = universe_at(qv, close, t, n_univ)
            if ew_benchmark:
                for s in uni:
                    cur[s] = 1.0 / len(uni)
            elif len(uni) >= 8:
                e, b = t - 1 - cfg["skip"], t - 1 - cfg["skip"] - cfg["L"]
                if b >= 0:
                    sc = {}
                    for s in uni:
                        a, c0 = close[s].iloc[e], close[s].iloc[b]
                        if a > 0 and c0 > 0:
                            sc[s] = a / c0 - 1
                    if len(sc) >= 8:
                        rk = pd.Series(sc).sort_values(ascending=False)
                        k = max(1, int(round(cfg["q"] * len(rk))))
                        longs, shorts = list(rk.index[:k]), list(rk.index[-k:])

                        def side(names):
                            if cfg["wt"] == "ivol":
                                iv = pd.Series({s: 1.0 / vol[s].iloc[t] for s in names if np.isfinite(vol[s].iloc[t]) and vol[s].iloc[t] > 0})
                                return iv / iv.sum() if len(iv) else iv
                            return pd.Series(1.0 / len(names), index=names)
                        if cfg["mode"] == "ls":
                            for s, w in side(longs).items():
                                cur[s] += 0.5 * w
                            for s, w in side(shorts).items():
                                cur[s] -= 0.5 * w
                        else:
                            for s, w in side(longs).items():
                                cur[s] += w
        W.iloc[t] = cur.values
    return W


# ----------------------------------------------------------------------------- CARRY
CARRY_CONFIGS = {
    # N names, trailing funding window (days), threshold per 8h settlement, rebalance days
    "C1": dict(n=10, win=7, th=0.0001, reb=1), "C2": dict(n=10, win=7, th=0.0, reb=1),
    "C3": dict(n=10, win=7, th=0.0002, reb=1), "C4": dict(n=10, win=30, th=0.0001, reb=1),
    "C5": dict(n=5, win=7, th=0.0001, reb=1), "C6": dict(n=20, win=7, th=0.0001, reb=1),
    "C7": dict(n=10, win=7, th=0.0001, reb=7), "C8": dict(n=10, win=7, th=-1.0, reb=1),   # C8 = always-on benchmark
}
CARRY_PER_SIDE_BPS = 10.0 + 5.5 + 2.0   # spot taker 10 + perp taker 5.5 (=11 RT/2) + 2 slippage, per unit of pair notional
CARRY_CAP_FACTOR = 1.25                  # spot fully funded + 25% of notional as perp margin


def carry_weights(close_perp, close_spot, qv, fund_daily, cfg):
    days = close_perp.index
    have_spot = set(close_spot.columns)
    W = pd.DataFrame(0.0, index=days, columns=close_perp.columns)
    trail = fund_daily.rolling(cfg["win"], min_periods=cfg["win"]).mean().shift(1)   # settled funding through t-1 only
    cur = pd.Series(0.0, index=close_perp.columns)
    for t in range(len(days)):
        if t % cfg["reb"] == 0:
            cur = pd.Series(0.0, index=close_perp.columns)
            uni = universe_at(qv, close_perp, t, cfg["n"], require=have_spot)
            for s in uni:
                if s not in trail.columns:
                    continue
                f = trail[s].iloc[t]
                sp = close_spot[s].iloc[t - 1] if t >= 1 else np.nan
                if np.isfinite(f) and f >= 3 * cfg["th"] and np.isfinite(sp):
                    cur[s] = 1.0 / cfg["n"]
        W.iloc[t] = cur.values
    return W


# ----------------------------------------------------------------------------- verdicts
def verdict(family: str, primary: Dict[str, Any], stress: Dict[str, Any]) -> Dict[str, Any]:
    if primary.get("state") != "computed":
        return {"verdict": "indeterminate", "why": "primary series insufficient"}
    chk = {}
    if family in ("tsmom", "xsec"):
        chk["sharpe>=0.5"] = primary["sharpe_net"] >= 0.5
        chk["stress_sharpe>0"] = stress.get("sharpe_net", -9) > 0
        chk["both_halves>0"] = primary["sharpe_h1"] > 0 and primary["sharpe_h2"] > 0
        chk["boot_p05>0"] = primary["boot_ann_mean_p05"] > 0
        chk["dsr>0.95"] = (primary["dsr"] or 0) > 0.95
    else:
        chk["ann_return>0"] = primary["ann_return_net"] > 0
        chk["sharpe>=1.0"] = primary["sharpe_net"] >= 1.0
        chk["stress_ann_return>0"] = stress.get("ann_return_net", -9) > 0
        chk["worst_month>-5%"] = primary["worst_month"] > -0.05
        chk["both_halves>0"] = primary["ann_return_h1"] > 0 and primary["ann_return_h2"] > 0
        chk["dsr>0.95"] = (primary["dsr"] or 0) > 0.95
    return {"verdict": "pass" if all(chk.values()) else "fail", "checks": chk}


def load_funding(symbols, root: Path):
    import edge_data as E
    fr = E.fetch(symbols, root, kinds=("f",), workers=48)
    ser, man = E.assemble(fr, "f")
    daily = pd.DataFrame({s: d["last_funding_rate"].resample("1D").sum(min_count=1) for s, d in ser.items()})
    daily.index = daily.index.normalize()
    return daily, man


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=["tsmom", "xsec", "carry"], required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--etf-csv", default=None, help="optional daily close panel csv for T10 (date index, ticker columns)")
    a = ap.parse_args()
    root = Path(a.data_root)
    P = load_panels(root / "klines_all.pkl")
    close, qv = P["close"], P["qv"]
    ret = close.pct_change()
    fee_rt = execution_costs.resolve_fee_bps_roundtrip("BTCUSDT")
    out: Dict[str, Any] = {"family": a.family, "registered": REGISTERED[a.family], "fee_bps_roundtrip": fee_rt,
                           "slippage_bps_roundtrip": SLIP_BPS_RT, "discovery_end": str(END_DISCOVERY.date()),
                           "eval_start": str(EVAL_START.date()), "configs": {}}
    # union of symbols that are ever in a top-N universe -> funding fetch
    ever = set()
    nu = REGISTERED[a.family]["n_universe"] if a.family != "carry" else 20
    for t in range(0, len(close), 7):
        ever |= set(universe_at(qv, close, t, nu))
    F, fman = load_funding(sorted(ever), root)
    F = F.reindex(close.index)
    out["funding_symbols"] = len(ever)
    out["funding_missing_symbols"] = sorted(ever - set(F.columns))

    if a.family == "carry":
        import edge_data as E
        sp = E.fetch(sorted(ever), root, kinds=("k",), workers=48, market="spot")
        sser, _ = E.assemble(sp, "k")
        sclose = pd.DataFrame({s: d["close"] for s, d in sser.items()})
        sclose = sclose[sclose.index <= END_DISCOVERY].reindex(close.index)
        out["spot_symbols"] = len(sclose.columns)
        sret = sclose.pct_change()
        basis = (sret - ret).reindex(close.index)   # spot minus perp per unit weight
        Fz = F.reindex(columns=close.columns)
        # carry earns funding as SHORT perp: net() subtracts W*F for longs, so pass -F-equivalent via sign flip
        runs = {}
        for cid, cfg in CARRY_CONFIGS.items():
            W = carry_weights(close, sclose, qv, F, cfg)
            res = {}
            for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                # short perp leg: W<0 on perp, long spot leg via basis term -> use perp weights = -W, basis term W*(r_spot - r_perp)
                net, to, parts = net_from_weights(-W, ret, Fz, mult, fee_rt, basis=None,
                                                  per_side_bps=CARRY_PER_SIDE_BPS, cap_factor=1.0)
                spot_pnl = (W * sret.reindex_like(W).fillna(0.0)).sum(axis=1)
                net = (net + spot_pnl) / CARRY_CAP_FACTOR
                res[tag] = metrics(net, to, len(CARRY_CONFIGS))
                res[tag + "_parts"] = parts
            runs[cid] = res
            out["configs"][cid] = {"params": cfg, **res}
        out["verdict"] = verdict("carry", out["configs"][REGISTERED["carry"]["primary"]]["primary"],
                                 out["configs"][REGISTERED["carry"]["primary"]]["stress"])
    else:
        ew_net = ew_to = None
        configs = TSMOM_CONFIGS if a.family == "tsmom" else XSEC_CONFIGS
        if a.family == "xsec":
            Wb = xsec_weights(close, qv, {}, ew_benchmark=True)
            ew_net = {m: net_from_weights(Wb, ret, F, m, fee_rt)[0] for m in (1.0, 2.0)}
        n_run = len([c for c in configs if not configs[c].get("etf")]) if not a.etf_csv else len(configs)
        for cid, cfg in configs.items():
            if cfg.get("etf") and not a.etf_csv:
                out["configs"][cid] = {"state": "not_run_no_etf_data"}
                continue
            if cfg.get("etf"):
                eclose = pd.read_csv(a.etf_csv, index_col=0, parse_dates=True)
                eclose.index = eclose.index.tz_localize("UTC") if eclose.index.tz is None else eclose.index
                eclose = eclose[eclose.index <= END_DISCOVERY]
                eret = eclose.pct_change()
                W = tsmom_weights(eclose, eclose.notna().astype(float), cfg, n_univ=len(eclose.columns),
                                  universe_fixed=list(eclose.columns))
                res = {}
                for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                    net, to, parts = net_from_weights(W, eret, pd.DataFrame(0.0, index=W.index, columns=W.columns), mult, 0.0,
                                                      per_side_bps=1.0)   # ETFs: commission-free, 1bp/side slippage; no funding
                    res[tag] = metrics(net, to, n_run)
                out["configs"][cid] = {"params": cfg, **res}
                continue
            W = (tsmom_weights(close, qv, cfg) if a.family == "tsmom" else xsec_weights(close, qv, cfg))
            res = {}
            for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                net, to, parts = net_from_weights(W, ret, F, mult, fee_rt)
                if a.family == "xsec" and cfg["mode"] == "lo":
                    net = net - ew_net[mult]
                res[tag] = metrics(net, to, n_run)
                res[tag + "_parts"] = parts
                if tag == "primary" and cid == REGISTERED[a.family]["primary"] and a.family == "tsmom":
                    b = ret["BTCUSDT"].reindex(net.index)
                    res["corr_to_btc"] = round(float(net.corr(b)), 3)
            out["configs"][cid] = {"params": cfg, **res}
        pid = REGISTERED[a.family]["primary"]
        out["verdict"] = verdict(a.family, out["configs"][pid]["primary"], out["configs"][pid]["stress"])
        out["n_trials_run"] = n_run
    btc = ret["BTCUSDT"]
    btc = btc[btc.index >= EVAL_START]
    out["btc_buyhold_sharpe_same_window"] = round(float(btc.mean() / btc.std() * math.sqrt(DAYS)), 3)
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("family", "verdict")}, indent=1))
    for cid, c in out["configs"].items():
        p = c.get("primary")
        if p and p.get("state") == "computed":
            print(cid, "sharpe", p["sharpe_net"], "ann", p["ann_return_net"], "dd", p["max_drawdown"], "dsr", p["dsr"],
                  "stress_sh", c["stress"].get("sharpe_net"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
