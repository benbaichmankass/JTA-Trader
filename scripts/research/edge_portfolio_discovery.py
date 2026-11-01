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
EVAL_START = pd.Timestamp(
    "2020-06-01", tz="UTC"
)  # first day any lookback (<=224d) can exist for BTC/ETH (archive starts 2019-09)
DAYS = 365
SLIP_BPS_RT = 3.0
STABLE_BASES = (
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "DAI",
    "USDP",
    "USDT",
    "EUR",
    "UST",
    "USDS",
)

REGISTERED = {
    "tsmom": {
        "primary": "T4",
        "n_universe": 20,
        "rule": "PASS iff PRIMARY net Sharpe>=0.5 AND stress(2x cost) net Sharpe>0 AND net Sharpe>0 in BOTH halves AND "
        "bootstrap 5th-pct of annualised mean net return>0 AND DSR(primary; N=configs run)>0.95. "
        "Else FAIL. Data coverage short => indeterminate.",
    },
    "xsec": {
        "primary": "X1",
        "n_universe": 20,
        "rule": "Same thresholds as tsmom. Long-short graded on its own net return; long-only graded on net return "
        "MINUS the equal-weight universe benchmark (same rebalance, same cost). PRIMARY is X1 (L=28, q=0.3, long-short).",
    },
    "carry": {
        "primary": "C1",
        "n_universe": 10,
        "rule": "PASS iff PRIMARY net annualised return>0 AND net Sharpe>=1.0 AND stress(2x cost) annualised return>0 AND "
        "worst calendar month>-5% AND both halves net return>0 AND DSR(primary; N=configs run)>0.95. Else FAIL.",
    },
}


# ----------------------------------------------------------------------------- data
def build_klines(root: Path, symbols: Optional[List[str]] = None, ms: Optional[List[str]] = None) -> Path:
    """Build ``<root>/klines_all.pkl`` = (series, manifest) from the public Binance Vision archive (no key). Same artefact the
    discovery sessions built by hand; ``edge_data`` caps the months at MAX_MONTH (HOLDOUT-LOCK), so nothing past 2024-06 loads."""
    import edge_data as E

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    syms = symbols or [x for x in E.list_symbols() if x.endswith("USDT")]
    ser, man = E.assemble(E.fetch(syms, root, kinds=("k",), ms=ms), "k")
    out = root / "klines_all.pkl"
    pickle.dump((ser, man), open(out, "wb"))
    return out


def load_panels(klines_pkl: Path) -> Dict[str, pd.DataFrame]:
    ser, manifest = pickle.load(open(klines_pkl, "rb"))
    close = pd.DataFrame({s: d["close"] for s, d in ser.items()})
    qv = pd.DataFrame({s: d["quote_volume"] for s, d in ser.items()})
    close = close[close.index <= END_DISCOVERY]
    qv = qv[qv.index <= END_DISCOVERY]
    assert close.index.max() <= END_DISCOVERY, (
        "HOLDOUT-LOCK: data past 2024-06-30 loaded"
    )
    return {"close": close, "qv": qv, "manifest": manifest}


def is_stable(sym: str) -> bool:
    base = sym[:-4] if sym.endswith("USDT") else sym
    return any(
        base == b or base.startswith(b) and len(base) <= len(b) + 1
        for b in STABLE_BASES
    )


def universe_at(
    qv: pd.DataFrame,
    close: pd.DataFrame,
    t: int,
    n: int,
    window: int = 90,
    require: Optional[set] = None,
) -> List[str]:
    """Top-n by trailing mean quote volume over the ``window`` days ending t-1 (point-in-time).
    Needs a full ``window`` of volume history and a close at t-1."""
    if t - window < 0:
        return []
    seg = qv.iloc[t - window : t]
    ok = seg.notna().sum() >= window
    ok &= close.iloc[t - 1].notna()
    cols = [
        c
        for c in seg.columns[ok.values]
        if not is_stable(c) and (require is None or c in require)
    ]
    if not cols:
        return []
    r = seg[cols].mean().sort_values(ascending=False)
    return list(r.index[:n])


# ----------------------------------------------------------------------------- metrics
def stationary_bootstrap_mean(
    x: np.ndarray, reps: int = 2000, block: int = 10, seed: int = 11
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    out = np.empty(reps)
    for k in range(reps):
        idx = np.empty(n, dtype=int)
        i = 0
        while i < n:
            s = rng.integers(0, n)
            L = min(rng.geometric(1.0 / block), n - i)
            idx[i : i + L] = (s + np.arange(L)) % n
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
        "state": "computed",
        "n_days": n,
        "first": str(r.index[0].date()),
        "last": str(r.index[-1].date()),
        "ann_return_net": round(float(mu * DAYS), 4),
        "ann_vol": round(float(sd * math.sqrt(DAYS)), 4),
        "sharpe_net": round(float(mu / sd * math.sqrt(DAYS)), 3),
        "max_drawdown": round(dd, 4),
        "worst_month": round(float(mon.min()), 4),
        "sharpe_h1": round(float(h1.mean() / h1.std(ddof=1) * math.sqrt(DAYS)), 3),
        "sharpe_h2": round(float(h2.mean() / h2.std(ddof=1) * math.sqrt(DAYS)), 3),
        "ann_return_h1": round(float(h1.mean() * DAYS), 4),
        "ann_return_h2": round(float(h2.mean() * DAYS), 4),
        "boot_ann_mean_p05": round(float(np.percentile(bs, 5) * DAYS), 4),
        "turnover_per_year": round(float(to.sum() / (n / DAYS)), 2),
        "dsr": d.get("dsr"),
        "psr_n1": d.get("psr_n1"),
        "dsr_state": d.get("state"),
        "n_trials": n_trials,
    }


# ----------------------------------------------------------------------------- engine (weights -> net returns)
def net_from_weights(
    W: pd.DataFrame,
    R: pd.DataFrame,
    F: pd.DataFrame,
    cost_mult: float,
    fee_rt: float,
    basis: Optional[pd.DataFrame] = None,
    cap_factor: float = 1.0,
    per_side_bps: Optional[float] = None,
):
    """W: target weight per symbol-day (weight applied to that day's return). R: perp close-to-close return.
    F: summed settled funding rate per day (long pays). basis: extra per-unit-weight daily pnl (carry spot leg)."""
    W = W.fillna(0.0)
    Rv = R.reindex_like(W).fillna(0.0)
    Fv = F.reindex_like(W).fillna(0.0)
    gross = (W * Rv).sum(axis=1)
    fund = (W * Fv).sum(axis=1)  # long pays, short receives
    dW = W.diff().abs().fillna(0.0)
    side_bps = (
        per_side_bps if per_side_bps is not None else (fee_rt + SLIP_BPS_RT) / 2.0
    )
    cost = dW.sum(axis=1) * side_bps * cost_mult / 1e4
    extra = (
        (W * basis.reindex_like(W).fillna(0.0)).sum(axis=1)
        if basis is not None
        else 0.0
    )
    net = (gross + extra - fund - cost) / cap_factor
    return (
        net,
        dW.sum(axis=1),
        {
            "gross": float(gross.sum()),
            "funding": float(fund.sum()),
            "cost": float(cost.sum()),
        },
    )


def realised_vol(ret: pd.DataFrame, window: int) -> pd.DataFrame:
    return ret.rolling(window).std(ddof=0).shift(1) * math.sqrt(
        DAYS
    )  # data through t-1 only


# ----------------------------------------------------------------------------- TSMOM
TSMOM_CONFIGS = {
    # id: lookbacks, sleeve target vol, long_only, universe-kind
    "T1": dict(lb=[28], tv=0.40, lo=False),
    "T2": dict(lb=[56], tv=0.40, lo=False),
    "T3": dict(lb=[112], tv=0.40, lo=False),
    "T4": dict(lb=[28, 56, 112], tv=0.40, lo=False),
    "T5": dict(lb=[14, 28, 56], tv=0.40, lo=False),
    "T6": dict(lb=[28, 56, 112, 224], tv=0.40, lo=False),
    "T7": dict(lb=[56], tv=0.40, lo=True),
    "T8": dict(lb=[28, 56, 112], tv=0.40, lo=True),
    "T9": dict(lb=[28, 56, 112], tv=0.20, lo=False),
    # T10 = primary signal on the liquid-ETF universe; only run when ETF daily data is supplied
    "T10": dict(lb=[28, 56, 112], tv=0.40, lo=False, etf=True),
}


def tsmom_weights(
    close,
    qv,
    cfg,
    n_univ=20,
    rebalance=7,
    max_lev=2.0,
    vol_window=30,
    universe_fixed=None,
):
    ret = close.pct_change()
    vol = realised_vol(ret, vol_window)
    days = close.index
    W = pd.DataFrame(0.0, index=days, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    for t in range(len(days)):
        if t % rebalance == 0:
            cur = pd.Series(0.0, index=close.columns)
            uni = (
                universe_fixed
                if universe_fixed is not None
                else universe_at(qv, close, t, n_univ)
            )
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
    "X1": dict(L=28, skip=0, q=0.3, mode="ls", wt="eq"),
    "X2": dict(L=14, skip=0, q=0.3, mode="ls", wt="eq"),
    "X3": dict(L=56, skip=0, q=0.3, mode="ls", wt="eq"),
    "X4": dict(L=84, skip=0, q=0.3, mode="ls", wt="eq"),
    "X5": dict(L=28, skip=7, q=0.3, mode="ls", wt="eq"),
    "X6": dict(L=28, skip=0, q=0.3, mode="lo", wt="eq"),
    "X7": dict(L=14, skip=0, q=0.3, mode="lo", wt="eq"),
    "X8": dict(L=56, skip=0, q=0.3, mode="lo", wt="eq"),
    "X9": dict(L=28, skip=0, q=0.3, mode="ls", wt="ivol"),
    "X10": dict(L=28, skip=0, q=0.2, mode="ls", wt="eq"),
}


def xsec_weights(
    close, qv, cfg, n_univ=20, rebalance=7, vol_window=30, ew_benchmark=False
):
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
                                iv = pd.Series(
                                    {
                                        s: 1.0 / vol[s].iloc[t]
                                        for s in names
                                        if np.isfinite(vol[s].iloc[t])
                                        and vol[s].iloc[t] > 0
                                    }
                                )
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
    "C1": dict(n=10, win=7, th=0.0001, reb=1),
    "C2": dict(n=10, win=7, th=0.0, reb=1),
    "C3": dict(n=10, win=7, th=0.0002, reb=1),
    "C4": dict(n=10, win=30, th=0.0001, reb=1),
    "C5": dict(n=5, win=7, th=0.0001, reb=1),
    "C6": dict(n=20, win=7, th=0.0001, reb=1),
    "C7": dict(n=10, win=7, th=0.0001, reb=7),
    "C8": dict(n=10, win=7, th=-1.0, reb=1),  # C8 = always-on benchmark
}
CARRY_PER_SIDE_BPS = (
    10.0 + 5.5 + 2.0
)  # spot taker 10 + perp taker 5.5 (=11 RT/2) + 2 slippage, per unit of pair notional
CARRY_CAP_FACTOR = 1.25  # spot fully funded + 25% of notional as perp margin


def carry_weights(close_perp, close_spot, qv, fund_daily, cfg):
    days = close_perp.index
    have_spot = set(close_spot.columns)
    W = pd.DataFrame(0.0, index=days, columns=close_perp.columns)
    trail = (
        fund_daily.rolling(cfg["win"], min_periods=cfg["win"]).mean().shift(1)
    )  # settled funding through t-1 only
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
def verdict(
    family: str, primary: Dict[str, Any], stress: Dict[str, Any]
) -> Dict[str, Any]:
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
        chk["both_halves>0"] = (
            primary["ann_return_h1"] > 0 and primary["ann_return_h2"] > 0
        )
        chk["dsr>0.95"] = (primary["dsr"] or 0) > 0.95
    return {"verdict": "pass" if all(chk.values()) else "fail", "checks": chk}


def load_funding(symbols, root: Path):
    import edge_data as E

    fr = E.fetch(symbols, root, kinds=("f",), workers=48)
    ser, man = E.assemble(fr, "f")
    daily = pd.DataFrame(
        {
            s: d["last_funding_rate"].resample("1D").sum(min_count=1)
            for s, d in ser.items()
        }
    )
    daily.index = daily.index.normalize()
    return daily, man


# ----------------------------------------------------------------------------- ITERATION (lane RESEARCH-OPS, 2026-11-01)
# One-factor / ablation arms against the family's registered PRIMARY as control, chosen from research/levers/<subject>.yaml
# (OPERATING-PLAN § 2 "What does not pass goes back into research"). Every arm run is counted; DSR uses the CUMULATIVE trial
# count (the discovery configs already run + every arm here), so a pass here is not flattered by a fresh N.
ITER_PRIOR_TRIALS = {"tsmom": 9, "xsec": 10}
ITER_ARMS = {
    "tsmom": {
        "A0": dict(base="T4"),                                   # control == discovery primary, reproduced in the same run
        "R1": dict(base="T4", gate="shorts_btc_dn"),             # regime: shorts only while BTC < its 200d mean
        "R2": dict(base="T4", gate="flat_btc_dn"),               # regime: whole book flat while BTC < its 200d mean
        "F1": dict(base="T4", rb=3),                             # rebalance frequency (discovery used 7d)
        "F2": dict(base="T4", rb=14),
        "U1": dict(base="T4", n=10),                             # universe size (discovery used 20)
        "U2": dict(base="T4", n=40),
    },
    "xsec": {
        "A0": dict(base="X1"),
        "R1": dict(base="X1", gate="shorts_btc_dn"),
        "R2": dict(base="X1", gate="flat_btc_dn"),
        "F1": dict(base="X1", rb=3),
        "F2": dict(base="X1", rb=14),
        "U1": dict(base="X1", n=10),
        "U2": dict(base="X1", n=40),
    },
}


def iteration_verdict(it: Dict[str, Any], what: str) -> Dict[str, Any]:
    """The unit's registered reading of an arm grid: PASS iff >=1 non-control arm clears the UNCHANGED registered rule at the cumulative
    trial count (then ONE holdout read is the next step, never a book); FAIL iff the control computed and no arm cleared it (the lever
    families tried are recorded in the map, no family is closed by this); INDETERMINATE iff the control series was insufficient."""
    ctl = it["arms"]["A0"]["primary"]
    if ctl.get("state") != "computed":
        v, note = "indeterminate", "control series insufficient"
    elif it["passing_arms"]:
        v, note = "pass", f"arm(s) {it['passing_arms']} clear the registered rule at N_cum={it['n_trials_cumulative']}"
    else:
        v, note = "fail", f"no arm clears the registered rule at N_cum={it['n_trials_cumulative']}; delta Sharpe vs control {it['delta_sharpe_vs_control']}"
    return {"verdict": v, "read_state": "measured", "n": ctl.get("n_days"), "note": note,
            "population": f"{what}: {it['n_arms']} arms incl. control A0, daily net returns, {ctl.get('first')}..{ctl.get('last')} "
                          f"(n_days={ctl.get('n_days')}), DSR N_cum={it['n_trials_cumulative']}"}


def write_run_outputs(out_arg: str, result: Dict[str, Any], verdict_doc: Optional[Dict[str, Any]] = None) -> Path:
    """`--out X.json` keeps the old behaviour (one file). `--out <dir>` (the research-script-run `{out_dir}`) writes result.json and,
    when a verdict is given, verdict.json {verdict, read_state, population, n, note, measurement} so the runner can grade it."""
    o = Path(out_arg)
    if o.suffix == ".json":
        o.write_text(json.dumps(result, indent=1, default=str))
        return o
    o.mkdir(parents=True, exist_ok=True)
    (o / "result.json").write_text(json.dumps(result, indent=1, default=str))
    if verdict_doc is not None:
        (o / "verdict.json").write_text(json.dumps(verdict_doc, indent=1, default=str))
    return o


def apply_gate(W: pd.DataFrame, close: pd.DataFrame, mode: Optional[str], ma: int = 200, ref: str = "BTCUSDT") -> pd.DataFrame:
    """BTC trend gate on a weight panel. Decision-time: the BTC state at day t uses closes through t-1 (shift(1)); the first
    ``ma`` days have no state and read as 'BTC up' (so a gate never opens a position it could not see)."""
    if not mode:
        return W
    btc = close[ref]
    sma = btc.rolling(ma).mean()
    up = (btc > sma).where(sma.notna()).shift(1)      # NaN (not False) until the mean exists: a NaN comparison is False
    up = up.where(up.notna(), True).astype(bool).to_numpy()
    if mode == "shorts_btc_dn":          # keep a short only in a BTC downtrend
        return W.mask((W < 0) & up[:, None], 0.0)
    if mode == "flat_btc_dn":            # hold nothing in a BTC downtrend
        return W.mul(up.astype(float), axis=0)
    raise ValueError(f"unknown gate {mode!r}")


def run_iteration(family: str, close, qv, ret, F, fee_rt: float) -> Dict[str, Any]:
    arms = ITER_ARMS[family]
    n_cum = ITER_PRIOR_TRIALS[family] + len(arms)
    base_cfgs = TSMOM_CONFIGS if family == "tsmom" else XSEC_CONFIGS
    out: Dict[str, Any] = {"control": "A0", "n_arms": len(arms), "n_trials_cumulative": n_cum, "arms": {}}
    for aid, spec in arms.items():
        cfg = base_cfgs[spec["base"]]
        kw = {"rebalance": spec.get("rb", 7), "n_univ": spec.get("n", 20)}
        W = tsmom_weights(close, qv, cfg, **kw) if family == "tsmom" else xsec_weights(close, qv, cfg, **kw)
        W = apply_gate(W, close, spec.get("gate"))
        res: Dict[str, Any] = {"spec": spec}
        for tag, mult in (("primary", 1.0), ("stress", 2.0)):
            net, to, parts = net_from_weights(W, ret, F, mult, fee_rt)
            res[tag] = metrics(net, to, n_cum)
            res[tag + "_parts"] = parts
            if tag == "primary":
                lo, sh = W.clip(lower=0.0), W.clip(upper=0.0)      # side split of the same weights (same cost/funding frame)
                res["side_net_sum"] = {
                    "long": round(float(net_from_weights(lo, ret, F, 1.0, fee_rt)[0].loc[lambda x: x.index >= EVAL_START].sum()), 4),
                    "short": round(float(net_from_weights(sh, ret, F, 1.0, fee_rt)[0].loc[lambda x: x.index >= EVAL_START].sum()), 4)}
                yr = net.loc[net.index >= EVAL_START]
                res["by_year_net_sum"] = {str(k): round(float(v), 4) for k, v in yr.groupby(yr.index.year).sum().items()}
        res["verdict"] = verdict(family, res["primary"], res["stress"])
        out["arms"][aid] = res
    ctl = out["arms"]["A0"]["primary"]
    out["delta_sharpe_vs_control"] = {
        a: (round(r["primary"]["sharpe_net"] - ctl["sharpe_net"], 3)
            if r["primary"].get("state") == "computed" and ctl.get("state") == "computed" else None)
        for a, r in out["arms"].items() if a != "A0"}
    out["passing_arms"] = [a for a, r in out["arms"].items() if a != "A0" and r["verdict"]["verdict"] == "pass"]
    return out


def _self_test() -> int:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2019-09-01", periods=900, freq="D", tz="UTC")
    cols = [f"S{i}USDT" for i in range(45)] + ["BTCUSDT"]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (900, len(cols))), axis=0)), index=idx, columns=cols)
    ok = True

    def chk(label, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and bool(cond)
    W = pd.DataFrame(rng.normal(0, 1, close.shape), index=idx, columns=cols)
    btc = close["BTCUSDT"]
    sma = btc.rolling(200).mean()
    up = (btc > sma).where(sma.notna()).shift(1)
    g = apply_gate(W, close, "shorts_btc_dn")
    dn_day = [i for i in range(210, 900) if up.iloc[i] is False or up.iloc[i] == False][0]  # noqa: E712
    up_day = [i for i in range(210, 900) if up.iloc[i] == True][0]                           # noqa: E712
    chk("gate: a BTC-up day keeps no short", (g.iloc[up_day] >= 0).all())
    chk("gate: a BTC-down day keeps its shorts", (g.iloc[dn_day] == W.iloc[dn_day]).all())
    chk("gate: longs are never touched by shorts_btc_dn", (g.clip(lower=0) == W.clip(lower=0)).all().all())
    chk("gate: flat_btc_dn zeroes a BTC-down day", (apply_gate(W, close, "flat_btc_dn").iloc[dn_day] == 0).all())
    chk("gate: flat_btc_dn keeps a BTC-up day", (apply_gate(W, close, "flat_btc_dn").iloc[up_day] == W.iloc[up_day]).all())
    chk("gate: first 200 days read BTC-up (no look-ahead, nothing opened it could not see)",
        (apply_gate(W, close, "flat_btc_dn").iloc[:200] == W.iloc[:200]).all().all())
    chk("gate: None is the identity", apply_gate(W, close, None) is W)
    chk("arms: control is first and both families register A0", all(list(v)[0] == "A0" for v in ITER_ARMS.values()))
    chk("arms: every arm names a registered base config", all(a["base"] in (TSMOM_CONFIGS if f == "tsmom" else XSEC_CONFIGS)
                                                              for f, d in ITER_ARMS.items() for a in d.values()))
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=["tsmom", "xsec", "carry"], required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--series-dir",
        default=None,
        help="diagnostic only: write each config's primary daily net series as csv (does not affect any verdict)",
    )
    ap.add_argument(
        "--etf-csv",
        default=None,
        help="optional daily close panel csv for T10 (date index, ticker columns)",
    )
    ap.add_argument("--build-data", action="store_true",
                    help="if <data-root>/klines_all.pkl is absent, build it from the public Binance Vision archive first")
    ap.add_argument("--iteration", action="store_true",
                    help="run the pre-registered one-factor ITER_ARMS grid (tsmom/xsec) against the primary as control")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    root = Path(a.data_root)
    if a.build_data and not (root / "klines_all.pkl").is_file():
        print(f"building {root / 'klines_all.pkl'} from the public archive", file=sys.stderr)
        build_klines(root)
    P = load_panels(root / "klines_all.pkl")
    close, qv = P["close"], P["qv"]
    ret = close.pct_change()
    fee_rt = execution_costs.resolve_fee_bps_roundtrip("BTCUSDT")
    out: Dict[str, Any] = {
        "family": a.family,
        "registered": REGISTERED[a.family],
        "fee_bps_roundtrip": fee_rt,
        "slippage_bps_roundtrip": SLIP_BPS_RT,
        "discovery_end": str(END_DISCOVERY.date()),
        "eval_start": str(EVAL_START.date()),
        "configs": {},
    }
    # union of symbols that are ever in a top-N universe -> funding fetch
    ever = set()
    nu = REGISTERED[a.family]["n_universe"] if a.family != "carry" else 20
    for t in range(0, len(close), 7):
        ever |= set(universe_at(qv, close, t, nu))
    F, fman = load_funding(sorted(ever), root)
    F = F.reindex(close.index)
    out["funding_symbols"] = len(ever)
    out["funding_missing_symbols"] = sorted(ever - set(F.columns))

    if a.iteration:
        if a.family not in ITER_ARMS:
            print(f"--iteration has no arm grid for family {a.family!r}", file=sys.stderr)
            return 2
        out["iteration"] = run_iteration(a.family, close, qv, ret, F, fee_rt)
        it = out["iteration"]
        it["measurement"] = {"control": "A0", "delta_sharpe_vs_control": it["delta_sharpe_vs_control"], "passing_arms": it["passing_arms"],
                             "arms": {k: {"spec": r["spec"], "sharpe": r["primary"].get("sharpe_net"), "h1": r["primary"].get("sharpe_h1"),
                                          "h2": r["primary"].get("sharpe_h2"), "dsr": r["primary"].get("dsr"),
                                          "stress_sharpe": r["stress"].get("sharpe_net"), "side_net_sum": r.get("side_net_sum"),
                                          "by_year_net_sum": r.get("by_year_net_sum"), "verdict": r["verdict"]["verdict"]}
                                      for k, r in it["arms"].items()}}
        write_run_outputs(a.out, out, {**iteration_verdict(it, f"{a.family} iteration"), "measurement": it["measurement"]})
        print(json.dumps({"family": a.family, "passing_arms": it["passing_arms"], "n_arms": it["n_arms"],
                          "delta_sharpe_vs_control": it["delta_sharpe_vs_control"]}, indent=1))
        for aid, r in it["arms"].items():
            p = r["primary"]
            if p.get("state") == "computed":
                print(aid, r["spec"], "sharpe", p["sharpe_net"], "h1/h2", p["sharpe_h1"], p["sharpe_h2"], "dsr", p["dsr"],
                      "stress", r["stress"].get("sharpe_net"), "sides", r["side_net_sum"], r["verdict"]["verdict"])
        return 0

    if a.family == "carry":
        import edge_data as E

        sp = E.fetch(sorted(ever), root, kinds=("k",), workers=48, market="spot")
        sser, _ = E.assemble(sp, "k")
        sclose = pd.DataFrame({s: d["close"] for s, d in sser.items()})
        sclose = sclose[sclose.index <= END_DISCOVERY].reindex(close.index)
        out["spot_symbols"] = len(sclose.columns)
        sret = sclose.pct_change()
        Fz = F.reindex(columns=close.columns)
        # carry earns funding as SHORT perp: net() subtracts W*F for longs, so pass -F-equivalent via sign flip
        runs = {}
        for cid, cfg in CARRY_CONFIGS.items():
            W = carry_weights(close, sclose, qv, F, cfg)
            res = {}
            for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                # short perp leg: W<0 on perp, long spot leg via basis term -> use perp weights = -W, basis term W*(r_spot - r_perp)
                net, to, parts = net_from_weights(
                    -W,
                    ret,
                    Fz,
                    mult,
                    fee_rt,
                    basis=None,
                    per_side_bps=CARRY_PER_SIDE_BPS,
                    cap_factor=1.0,
                )
                spot_pnl = (W * sret.reindex_like(W).fillna(0.0)).sum(axis=1)
                net = (net + spot_pnl) / CARRY_CAP_FACTOR
                res[tag] = metrics(net, to, len(CARRY_CONFIGS))
                res[tag + "_parts"] = parts
                if a.series_dir and tag == "primary":
                    Path(a.series_dir).mkdir(parents=True, exist_ok=True)
                    net.to_csv(
                        Path(a.series_dir) / f"{a.family}_{cid}.csv", header=["net"]
                    )
            runs[cid] = res
            out["configs"][cid] = {"params": cfg, **res}
        out["verdict"] = verdict(
            "carry",
            out["configs"][REGISTERED["carry"]["primary"]]["primary"],
            out["configs"][REGISTERED["carry"]["primary"]]["stress"],
        )
    else:
        ew_net = None
        configs = TSMOM_CONFIGS if a.family == "tsmom" else XSEC_CONFIGS
        if a.family == "xsec":
            Wb = xsec_weights(close, qv, {}, ew_benchmark=True)
            ew_net = {m: net_from_weights(Wb, ret, F, m, fee_rt)[0] for m in (1.0, 2.0)}
        n_run = (
            len([c for c in configs if not configs[c].get("etf")])
            if not a.etf_csv
            else len(configs)
        )
        for cid, cfg in configs.items():
            if cfg.get("etf") and not a.etf_csv:
                out["configs"][cid] = {"state": "not_run_no_etf_data"}
                continue
            if cfg.get("etf"):
                eclose = pd.read_csv(a.etf_csv, index_col=0, parse_dates=True)
                eclose.index = (
                    eclose.index.tz_localize("UTC")
                    if eclose.index.tz is None
                    else eclose.index
                )
                eclose = eclose[eclose.index <= END_DISCOVERY]
                eret = eclose.pct_change()
                W = tsmom_weights(
                    eclose,
                    eclose.notna().astype(float),
                    cfg,
                    n_univ=len(eclose.columns),
                    universe_fixed=list(eclose.columns),
                )
                res = {}
                for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                    net, to, parts = net_from_weights(
                        W,
                        eret,
                        pd.DataFrame(0.0, index=W.index, columns=W.columns),
                        mult,
                        0.0,
                        per_side_bps=1.0,
                    )  # ETFs: commission-free, 1bp/side slippage; no funding
                    res[tag] = metrics(net, to, n_run)
                out["configs"][cid] = {"params": cfg, **res}
                continue
            W = (
                tsmom_weights(close, qv, cfg)
                if a.family == "tsmom"
                else xsec_weights(close, qv, cfg)
            )
            res = {}
            for tag, mult in (("primary", 1.0), ("stress", 2.0)):
                net, to, parts = net_from_weights(W, ret, F, mult, fee_rt)
                if a.family == "xsec" and cfg["mode"] == "lo":
                    net = net - ew_net[mult]
                res[tag] = metrics(net, to, n_run)
                res[tag + "_parts"] = parts
                if a.series_dir and tag == "primary":
                    Path(a.series_dir).mkdir(parents=True, exist_ok=True)
                    net.to_csv(
                        Path(a.series_dir) / f"{a.family}_{cid}.csv", header=["net"]
                    )
                if (
                    tag == "primary"
                    and cid == REGISTERED[a.family]["primary"]
                    and a.family == "tsmom"
                ):
                    b = ret["BTCUSDT"].reindex(net.index)
                    res["corr_to_btc"] = round(float(net.corr(b)), 3)
            out["configs"][cid] = {"params": cfg, **res}
        pid = REGISTERED[a.family]["primary"]
        out["verdict"] = verdict(
            a.family, out["configs"][pid]["primary"], out["configs"][pid]["stress"]
        )
        out["n_trials_run"] = n_run
    btc = ret["BTCUSDT"]
    btc = btc[btc.index >= EVAL_START]
    out["btc_buyhold_sharpe_same_window"] = round(
        float(btc.mean() / btc.std() * math.sqrt(DAYS)), 3
    )
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("family", "verdict")}, indent=1))
    for cid, c in out["configs"].items():
        p = c.get("primary")
        if p and p.get("state") == "computed":
            print(
                cid,
                "sharpe",
                p["sharpe_net"],
                "ann",
                p["ann_return_net"],
                "dd",
                p["max_drawdown"],
                "dsr",
                p["dsr"],
                "stress_sh",
                c["stress"].get("sharpe_net"),
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
