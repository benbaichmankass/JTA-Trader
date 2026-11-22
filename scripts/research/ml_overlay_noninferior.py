#!/usr/bin/env python3
"""ML-REAL-MONEY-OVERLAY: a reduce-only meta-label overlay graded NON-INFERIOR vs take-all (RULE-ML-OVERLAY-NONINFERIOR-V1).

The leg's own strategy is the primary model. The overlay only decides TAKE (1.0) or REDUCE (one fixed
multiplier) per entry. It never upsizes, never opens a trade, never moves a bracket.

Pipeline (each step is the rule registered in research/queue/RQ-20261029-5785-01.yaml BEFORE any run):
  1. CORPUS: config-exact Stage-0 harness runs with --emit-paths for every leg of each family (the same argv
     builder the RQ-20261024-09a6-01 corpus used: path_metric_giveback.run_leg_paths), over a pinned window.
     Labels are `net_r` per trade: cost-net (fee + slippage + funding), the exit actually traded, in R of the
     initial risk (practice M1). Real-money legs are cross-checked trade-for-trade against the committed
     reference corpus (fidelity); a parity share < 0.98 makes the family INDETERMINATE.
  2. FEATURES: src/runtime/overlay_features.decision_features on the leg's OWN candles up to and including the
     decision bar (the bar whose close is the entry price) -- the same function the live scorer calls.
  3. VALIDATION: combinatorial purged CV, N=6 calendar groups, k=2 test groups (15 splits, 5 paths), purge by
     trade interval overlap + an embargo after each test block (practice M2). Model: L2 logistic on
     standardised features predicting P(net_r > 0). Threshold tau = the q-quantile of the TRAINING scores.
  4. GATE per family, on the family's REAL-MONEY legs' out-of-sample trades, net of the full cost stack:
     (a) one-sided 95% lower bound of mean delta net R/trade vs take-all > -0.02 (month-block bootstrap);
     (b) max drawdown (R, exit-ordered) and CVaR5 (per-trade R) not worse than take-all;
     (c) delta beats a same-rate RANDOM reduce: above the 90th percentile of the permutation distribution;
     (d) not vacuous: reduce rate >= 5% and the mean R of reduced trades <= the take-all mean;
     (e) per calendar group: delta > -0.02, (b) holds, delta > the random mean -- in >= 4 of 6 groups.
  5. SELECTION ACCOUNTING (M4/M5): the PRIMARY configuration is fixed in advance and alone decides the verdict.
     Every configuration in the trial grid is still run and counted; PBO (CSCV over the 6 groups) and a
     Bonferroni-deflated lower bound are reported.

Usage:
  python3 scripts/research/ml_overlay_noninferior.py --family 'PB2H:ada_pullback_2h+,xrp_pullback_2h+,...' \
      --family 'TD:trend_donchian_eth_4h+,...' --start 2020-07-01 --end '2026-10-15 23:59' --days 2330 \
      --reference-corpus comms/research/RQ-20261024-09a6-01/40143286436/first_passage_paths_4b_c03_b \
      --out <dir> [--export-dir <dir>]
  python3 scripts/research/ml_overlay_noninferior.py --self-test
  (`+` marks a real-money leg: the gate population. The others are training-only siblings.)
"""
from __future__ import annotations

import argparse
import itertools
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

from src.runtime.overlay_features import FEATURES, MIN_BARS, decision_features  # noqa: E402

RULE_ID = "RULE-ML-OVERLAY-NONINFERIOR-V1"
N_GROUPS, K_TEST = 6, 2
EMBARGO_DAYS = 7.0
MULTIPLIER = 0.5
PRIMARY = {"C": 0.1, "q": 0.20}
GRID = [{"C": c, "q": q} for c in (0.1, 1.0) for q in (0.10, 0.20, 0.30)]
NI_MARGIN = -0.02
ALPHA = 0.05
RANDOM_PCTL = 0.90
MIN_ACT = 0.05
FOLDS_NEEDED = 4
N_BOOT = 5000
N_RAND = 2000
PARITY_MIN = 0.98
N_GATE_MIN = 200
SEED = 20261029
# ml-week-plan D4 task 4 (RQ-20261119-e8a1-03): a MONOTONE LightGBM learner on Beagle-1's features, target win, same CPCV
# splits, config q and multiplier. Each feature's monotone direction is FIXED BEFORE ANY RUN from the sign of the committed
# Beagle-1 coefficient (ml/overlay/overlay_td.json); a coefficient with |coef| < MONO_MIN_ABS_COEF is left unconstrained (0).
LEARNER_ARMS = ("mlgbm",)
MONO_MIN_ABS_COEF = 0.02
MLGBM_PARAMS = {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 7, "min_child_samples": 50, "subsample": 0.8,
                "subsample_freq": 1, "colsample_bytree": 0.9, "reg_lambda": 1.0, "verbose": -1}


def monotone_signs(artifact: Path | None = None) -> list[int]:
    """+1 / -1 / 0 per FEATURES entry from the committed Beagle-1 coefficients (features matched by name)."""
    art = json.loads((artifact or REPO / "ml/overlay/overlay_td.json").read_text())
    coef = dict(zip(art["features"], art["coef"]))
    return [0 if abs(coef.get(f, 0.0)) < MONO_MIN_ABS_COEF else (1 if coef[f] > 0 else -1) for f in FEATURES]


def fit_predict_mlgbm(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, signs: list[int], seed: int = SEED):
    """(p_train, p_test) = P(win) from a monotone-constrained LGBMClassifier."""
    import lightgbm as lgb
    m = lgb.LGBMClassifier(**MLGBM_PARAMS, monotone_constraints=list(signs), random_state=seed)
    m.fit(Xtr, ytr.astype(int))
    # provenance: predict_proba[:, 1] = P(net_r > 0), the same quantity Beagle-1's logistic score is
    return m.predict_proba(Xtr)[:, 1], m.predict_proba(Xte)[:, 1]


# ----------------------------------------------------------------------------------------------- model
def fit_logistic(X: np.ndarray, y: np.ndarray, C: float, iters: int = 50,
                 sw: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """L2-penalised logistic regression by Newton/IRLS (penalty 1/(2C)||w||^2, intercept unpenalised).
    Deterministic; numpy only (the research runner installs no sklearn). ``sw`` = optional per-row sample weights
    (normalised to mean 1 so the penalty keeps its scale); None reproduces the unweighted fit exactly."""
    n, p = X.shape
    sw = np.ones(n) if sw is None else np.asarray(sw, float) / float(np.mean(sw))
    Xa = np.hstack([np.ones((n, 1)), X])
    w = np.zeros(p + 1)
    lam = np.full(p + 1, 1.0 / C)
    lam[0] = 0.0
    for _ in range(iters):
        z = np.clip(Xa @ w, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-z))
        g = Xa.T @ (sw * (mu - y)) + lam * w
        H = (Xa * (sw * mu * (1 - mu))[:, None]).T @ Xa + np.diag(lam) + 1e-9 * np.eye(p + 1)
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w[1:], float(w[0])


def predict(X: np.ndarray, coef: np.ndarray, b: float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(X @ coef + b, -30, 30)))


def standardise(Xtr: np.ndarray, *others: np.ndarray):
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd[sd == 0] = 1.0
    return mu, sd, [(o - mu) / sd for o in (Xtr, *others)]


# ----------------------------------------------------------------------------------------------- corpus
SPOT_WARMUP_DAYS = 120  # candles fetched before `start` so indicators are warm when the window opens


def fetch_spot_proxy_csv(leg: str, base: dict, *, start: str, end: str, csv: Path) -> dict:
    """Binance SPOT candles for a USDT crypto leg (PI-20261029-XME2GXW7-0003). Spot is a PROXY for the perp the leg
    trades (same exchange + symbol, no funding in the price); the harness still charges the full cost stack."""
    import subprocess
    import regime_debt_matrix as rdm
    sym, tf = (base.get("symbols") or [None])[0], base.get("timeframe")
    if not sym or not tf:
        raise ValueError(f"{leg}: no symbols[0]/timeframe in config")
    feed = rdm.resolve_feed(sym, tf)
    if feed["source"] != "binance":
        raise ValueError(f"{leg}: spot proxy needs a USDT crypto leg, got feed source {feed['source']!r}")
    t0 = (pd.Timestamp(start) - pd.Timedelta(days=SPOT_WARMUP_DAYS)).strftime("%Y-%m-%d")
    t1 = pd.Timestamp(end).strftime("%Y-%m-%d")
    subprocess.run([sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", feed["ticker"],
                    "--interval", feed["interval"], "--start-date", t0, "--end-date", t1, "--output", str(csv),
                    "--source", "binance_vision", "--vision-market", "spot"], check=True, cwd=str(REPO))
    return {**feed, "source": "binance_spot_proxy", "window": [t0, t1]}


def build_corpus(legs: list[str], *, start: str, end: str, days: int, wd: Path,
                 market: str = "perp") -> tuple[dict, dict]:
    """Run each leg's config-exact harness with --emit-paths (one argv builder, path_metric_giveback).
    market="spot" pre-fetches Binance SPOT candles (a labelled perp proxy) and feeds them as the harness CSV."""
    import yaml
    from path_metric_giveback import run_leg_paths
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    cfgs = cfgs.get("strategies", cfgs)
    out, runs = {}, {}
    for leg in legs:
        base = cfgs.get(leg)
        if not isinstance(base, dict):
            runs[leg] = {"state": "not_in_config"}
            continue
        try:
            spot_feed, data_csv = None, None
            if market == "spot":
                data_csv = wd / f"{leg}__data.csv"
                spot_feed = fetch_spot_proxy_csv(leg, base, start=start, end=end, csv=data_csv)
            _paths, meta = run_leg_paths(leg, base, days=days, start=start, end=end, wd=wd,
                                         data_csv=str(data_csv) if data_csv else None, non_crypto_source="auto")
            if spot_feed is not None:
                meta["feed"] = spot_feed
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded per leg; the family verdict goes INDETERMINATE when a gate leg fails
            runs[leg] = {"state": "harness_failed", "error": str(exc)[:400]}
            continue
        bt = meta.get("bt") or {}
        out[leg] = wd
        runs[leg] = {"state": "ok", "argv": meta["argv"], "feed": meta["feed"],
                     "timeframe_declared": base.get("timeframe"), "timeframe_bt": bt.get("timeframe"),
                     "cost_policy": {f: bt.get(f) for f in ("fee_bps_roundtrip", "slippage_bps_roundtrip",
                                                            "funding_bps_per_window")},
                     "bt_total_trades": bt.get("total_trades"), "bt_net_expectancy_r": bt.get("net_expectancy_r")}
    return out, runs


def load_leg(leg: str, d: Path) -> pd.DataFrame:
    """Trades + point-in-time features for one leg from <d>/<leg>__trades.jsonl and <d>/<leg>__data.csv."""
    trades = [json.loads(ln) for ln in open(d / f"{leg}__trades.jsonl", encoding="utf-8") if ln.strip()]
    bars = pd.read_csv(d / f"{leg}__data.csv")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars = bars.sort_values("timestamp").reset_index(drop=True)
    idx = {ts: i for i, ts in enumerate(bars["timestamp"])}
    hi, lo, cl = bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float)
    rows = []
    for t in trades:
        ts = pd.Timestamp(t["entry_time"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        i = idx.get(ts)
        aligned = i is not None and abs(cl[i] - float(t["entry"])) <= 1e-6 * abs(float(t["entry"]))
        feats = None
        if i is not None and i + 1 >= MIN_BARS:
            feats = decision_features({"high": hi[:i + 1], "low": lo[:i + 1], "close": cl[:i + 1]},
                                      t["direction"])
        rows.append({"leg": leg, "entry_time": ts,
                     "exit_time": pd.Timestamp(t["exit_time"]).tz_convert("UTC")
                     if pd.Timestamp(t["exit_time"]).tzinfo else pd.Timestamp(t["exit_time"]).tz_localize("UTC"),
                     "direction": t["direction"], "net_r": float(t["net_r"]), "aligned": aligned,
                     "scored": feats is not None, **(feats or {f: np.nan for f in FEATURES})})
    return pd.DataFrame(rows)


def parity(leg: str, df: pd.DataFrame, ref_dir: Path | None, basis: str = "net_r", ours_dir: Path | None = None) -> dict:
    """Trade-for-trade parity with the reference corpus. basis "net_r" (V1): same entry/direction AND net_r within
    1e-3 -- which also fails on a deliberate cost-stack update. basis "trade" (V2): same entry_time, direction,
    exit_time and gross_r (the trade itself), with the net_r shift reported separately as a cost-stack delta."""
    if basis == "trade":
        return _trade_parity(leg, ref_dir, ours_dir)
    if ref_dir is None or not (ref_dir / f"{leg}__trades.jsonl").exists():
        return {"state": "no_reference"}
    ref = [json.loads(ln) for ln in open(ref_dir / f"{leg}__trades.jsonl", encoding="utf-8") if ln.strip()]
    rk = {(str(pd.Timestamp(r["entry_time"])), r["direction"]): float(r["net_r"]) for r in ref}
    ours = {(str(t), d): r for t, d, r in zip(df["entry_time"], df["direction"], df["net_r"])}
    common = [k for k in ours if k in rk]
    same_r = sum(1 for k in common if abs(ours[k] - rk[k]) <= 1e-3)
    # The reference window may end earlier than ours; compare over the reference's span only.
    ref_end = max(pd.Timestamp(r["entry_time"]) for r in ref) if ref else None
    ours_in = [k for k in ours if ref_end is None or pd.Timestamp(k[0]) <= ref_end]
    denom = max(len(rk), len(ours_in), 1)
    return {"state": "checked", "n_ref": len(rk), "n_ours_in_ref_span": len(ours_in), "n_common": len(common),
            "n_same_net_r": same_r, "parity_share": round(same_r / denom, 4)}


def _trade_parity(leg: str, ref_dir: Path | None, ours_dir: Path | None) -> dict:
    if ref_dir is None or ours_dir is None or not (ref_dir / f"{leg}__trades.jsonl").exists():
        return {"state": "no_reference"}
    load = lambda d: [json.loads(ln) for ln in open(d / f"{leg}__trades.jsonl", encoding="utf-8") if ln.strip()]  # noqa: E731
    key = lambda r: (str(pd.Timestamp(r["entry_time"])), r["direction"])  # noqa: E731
    ref, ours = {key(r): r for r in load(ref_dir)}, {key(r): r for r in load(ours_dir)}
    ref_end = max(pd.Timestamp(k[0]) for k in ref) if ref else None
    ours_in = [k for k in ours if ref_end is None or pd.Timestamp(k[0]) <= ref_end]
    same = [k for k in ours_in if k in ref and str(pd.Timestamp(ours[k]["exit_time"])) == str(pd.Timestamp(ref[k]["exit_time"]))
            and abs(float(ours[k]["gross_r"]) - float(ref[k]["gross_r"])) <= 1e-3]
    shift = [float(ours[k]["net_r"]) - float(ref[k]["net_r"]) for k in same]
    denom = max(len(ref), len(ours_in), 1)
    return {"state": "checked", "basis": "trade", "n_ref": len(ref), "n_ours_in_ref_span": len(ours_in),
            "n_same_trade": len(same), "parity_share": round(len(same) / denom, 4),
            "cost_stack_net_r_shift_mean": round(float(np.mean(shift)), 5) if shift else None}


# ----------------------------------------------------------------------------------------------- CPCV
def cpcv_splits(times: pd.Series, exits: pd.Series):
    """Yield (split_id, test_groups, train_mask, test_mask) for N_GROUPS calendar groups, K_TEST test groups,
    purging train trades whose [entry, exit] overlaps a test block and embargoing EMBARGO_DAYS after it."""
    t0, t1 = times.min(), times.max()
    edges = [t0 + (t1 - t0) * i / N_GROUPS for i in range(N_GROUPS + 1)]
    g = np.minimum(((times - t0) / (t1 - t0) * N_GROUPS).astype(float).to_numpy().astype(int), N_GROUPS - 1)
    emb = pd.Timedelta(days=EMBARGO_DAYS)
    for sid, tg in enumerate(itertools.combinations(range(N_GROUPS), K_TEST)):
        test = np.isin(g, tg)
        train = ~test
        for k in tg:
            a, b = edges[k], edges[k + 1]
            overlap = (exits >= a).to_numpy() & (times <= b + emb).to_numpy()
            train &= ~overlap
        yield sid, tg, train, test, g


# Label targets for the overlay's logistic (RQ-20261117-aadc-03, the D4 challengers that change the TARGET, not the
# threshold). "win" is Beagle-1's own label and the default everywhere. Every target exports the same artifact form
# (standardised logistic over FEATURES), so src/runtime/overlay_features.score_overlay scores it with no runtime change.
TAIL_R = 1.0
EVW_CLIP = (0.05, 5.0)


def target_labels(net_r: np.ndarray, target: str = "win") -> tuple[np.ndarray, np.ndarray | None]:
    """(y, sample_weight). win: P(net_r > 0). tail1r: P(net_r >= TAIL_R) -- the trend payoff is carried by tail winners,
    and 5785-05 found the reduce halves trades that still average +0.21 R. evweight: P(net_r > 0) with each row weighted
    by |net_r| (clipped), so a model is paid for ranking by money, not by win count."""
    r = np.asarray(net_r, float)
    if target == "win":
        return (r > 0).astype(float), None
    if target == "tail1r":
        return (r >= TAIL_R).astype(float), None
    if target == "evweight":
        return (r > 0).astype(float), np.clip(np.abs(r), *EVW_CLIP)
    raise ValueError(f"unknown target {target!r}")


def run_cpcv(df: pd.DataFrame, cfg: dict, target: str = "win", learner: str = "logistic") -> dict:
    """Out-of-sample reduce decisions per trade per CPCV path. Returns m (n x paths multiplier), p (scores)."""
    X = df[list(FEATURES)].to_numpy(float)
    y, sw = target_labels(df["net_r"].to_numpy(), target)
    n = len(df)
    n_paths = math.comb(N_GROUPS - 1, K_TEST - 1)
    mult = np.full((n, n_paths), np.nan)
    score = np.full((n, n_paths), np.nan)
    seen = np.zeros(N_GROUPS, dtype=int)
    groups = None
    signs = monotone_signs() if learner == "mlgbm" else None
    for _sid, tg, train, test, g in cpcv_splits(df["entry_time"], df["exit_time"]):
        groups = g
        _mu, _sd, (Xtr, Xte) = standardise(X[train], X[test])
        if learner == "mlgbm":
            ptr, pte = fit_predict_mlgbm(Xtr, y[train], Xte, signs)
            tau = float(np.quantile(ptr, cfg["q"]))
        else:
            coef, b = fit_logistic(Xtr, y[train], cfg["C"], sw=None if sw is None else sw[train])
            tau = float(np.quantile(predict(Xtr, coef, b), cfg["q"]))
            pte = predict(Xte, coef, b)
        te_idx = np.where(test)[0]
        for k in tg:
            col = seen[k]
            sel = te_idx[g[te_idx] == k]
            loc = np.isin(te_idx, sel)
            mult[sel, col] = np.where(pte[loc] < tau, MULTIPLIER, 1.0)
            score[sel, col] = pte[loc]
            seen[k] += 1
    return {"mult": mult, "score": score, "groups": groups, "y": y}


# ----------------------------------------------------------------------------------------------- metrics
def max_dd(r_sorted: np.ndarray) -> float:
    eq = np.cumsum(r_sorted)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return float(np.max(peak - eq)) if len(eq) else 0.0


def cvar5(r: np.ndarray) -> float:
    k = max(1, int(math.ceil(0.05 * len(r))))
    return float(np.mean(np.sort(r)[:k]))


def month_block_lb(delta: np.ndarray, months: np.ndarray, rng: np.random.Generator, alpha: float) -> float:
    """One-sided (1-alpha) lower bound of mean(delta) by a calendar-month block bootstrap (resample months)."""
    um = np.unique(months)
    by = {m: delta[months == m] for m in um}
    sums = np.array([by[m].sum() for m in um])
    cnts = np.array([len(by[m]) for m in um])
    boots = np.empty(N_BOOT)
    for i in range(N_BOOT):
        pick = rng.integers(0, len(um), len(um))
        boots[i] = sums[pick].sum() / max(cnts[pick].sum(), 1)
    return float(np.quantile(boots, alpha))


def random_deltas(R: np.ndarray, mbar: np.ndarray, groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Same-rate random reduce: permute the overlay's (path-averaged) multipliers WITHIN each calendar group,
    so the random arm reduces the same share of trades in the same periods."""
    out = np.empty(N_RAND)
    for i in range(N_RAND):
        m = mbar.copy()
        for gk in np.unique(groups):
            ix = np.where(groups == gk)[0]
            m[ix] = m[rng.permutation(ix)]
        out[i] = float(np.mean((m - 1.0) * R))
    return out


def evaluate(df: pd.DataFrame, res: dict, gate_mask: np.ndarray, rng: np.random.Generator,
             n_groups: int = N_GROUPS) -> dict:
    R = df["net_r"].to_numpy()
    mbar = np.nanmean(res["mult"], axis=1)
    g = res["groups"]
    Rg, mg, gg = R[gate_mask], mbar[gate_mask], g[gate_mask]
    exits = df["exit_time"].to_numpy()[gate_mask]
    order = np.argsort(exits, kind="stable")
    months = pd.DatetimeIndex(df["entry_time"][gate_mask]).strftime("%Y-%m").to_numpy()
    delta = (mg - 1.0) * Rg
    d_mean = float(delta.mean())
    lb = month_block_lb(delta, months, rng, ALPHA)
    dd_take, dd_ovl = max_dd(Rg[order]), max_dd((Rg * mg)[order])
    cv_take, cv_ovl = cvar5(Rg), cvar5(Rg * mg)
    rnd = random_deltas(Rg, mg, gg, rng)
    rnd_thr = float(np.quantile(rnd, RANDOM_PCTL))
    act = float(np.mean(1.0 - mg) / (1.0 - MULTIPLIER))
    w = (1.0 - mg)
    red_mean = float(np.sum(w * Rg) / np.sum(w)) if np.sum(w) > 0 else float("nan")
    take_mean = float(Rg.mean())
    folds = []
    for gk in range(n_groups):
        ix = gg == gk
        if not ix.any():
            folds.append({"group": gk, "n": 0, "pass": False})
            continue
        o = np.argsort(exits[ix], kind="stable")
        dg = float(np.mean((mg[ix] - 1.0) * Rg[ix]))
        rg = random_deltas(Rg[ix], mg[ix], np.zeros(ix.sum(), dtype=int), rng)
        bdd = max_dd((Rg[ix] * mg[ix])[o]) <= max_dd(Rg[ix][o]) + 1e-9
        bcv = cvar5(Rg[ix] * mg[ix]) >= cvar5(Rg[ix]) - 1e-9
        fa, fc = dg > NI_MARGIN, dg > float(np.mean(rg))
        folds.append({"group": gk, "n": int(ix.sum()), "delta": round(dg, 4), "random_mean": round(float(np.mean(rg)), 4),
                      "a": fa, "b": bool(bdd and bcv), "c": fc, "pass": bool(fa and bdd and bcv and fc)})
    paths = [float(np.mean((res["mult"][gate_mask, j] - 1.0) * Rg)) for j in range(res["mult"].shape[1])]
    # provenance: predict — `score` is P(net_r > 0) from the binary L2-logistic sigmoid, not a multiclass max(proba)
    p_gate, y_gate = np.nanmean(res["score"], axis=1)[gate_mask], res["y"][gate_mask]
    checks = {
        "a_noninferior": lb > NI_MARGIN,
        "b_risk": dd_ovl <= dd_take + 1e-9 and cv_ovl >= cv_take - 1e-9,
        "c_beats_random": d_mean > rnd_thr,
        "d_not_vacuous": act >= MIN_ACT and red_mean <= take_mean,
        "e_folds": sum(f["pass"] for f in folds) >= FOLDS_NEEDED,
    }
    return {
        "n_gate": int(gate_mask.sum()), "take_all_mean_r": round(take_mean, 4),
        "delta_mean_r": round(d_mean, 4), "delta_lb95_r": round(lb, 4),
        "delta_lb_bonferroni_r": round(month_block_lb(delta, months, rng, ALPHA / len(GRID)), 4),
        "maxdd_take_r": round(dd_take, 3), "maxdd_overlay_r": round(dd_ovl, 3),
        "cvar5_take_r": round(cv_take, 4), "cvar5_overlay_r": round(cv_ovl, 4),
        "random_delta_mean_r": round(float(rnd.mean()), 4), "random_delta_p90_r": round(rnd_thr, 4),
        "random_p_value": round(float(np.mean(rnd >= d_mean)), 4),
        "reduce_rate": round(act, 4), "reduced_mean_r": round(red_mean, 4),
        "net_total_r_take": round(float(Rg.sum()), 2), "net_total_r_overlay": round(float((Rg * mg).sum()), 2),
        "paths_delta_mean_r": [round(x, 4) for x in paths],
        "calibration": calib(p_gate, y_gate), "folds": folds,
        "folds_passing": int(sum(f["pass"] for f in folds)), "checks": checks, "pass": all(checks.values()),
    }


def calib(p: np.ndarray, y: np.ndarray) -> dict:
    ok = ~np.isnan(p)
    p, y = p[ok], y[ok]
    if not len(p):
        return {}
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = sum(abs(p[bins == b].mean() - y[bins == b].mean()) * (bins == b).sum() for b in range(10) if (bins == b).any())
    return {"brier": round(float(np.mean((p - y) ** 2)), 4), "brier_const": round(float(np.mean((y.mean() - y) ** 2)), 4),
            "ece": round(float(ece / len(p)), 4), "base_rate": round(float(y.mean()), 4)}


def pbo(delta_by_cfg_group: np.ndarray) -> float:
    """CSCV probability of backtest overfitting over configurations x calendar groups (Bailey et al.)."""
    n_cfg, n_g = delta_by_cfg_group.shape
    logits = []
    for is_g in itertools.combinations(range(n_g), n_g // 2):
        oos_g = [k for k in range(n_g) if k not in is_g]
        is_perf = delta_by_cfg_group[:, list(is_g)].mean(axis=1)
        oos_perf = delta_by_cfg_group[:, oos_g].mean(axis=1)
        best = int(np.argmax(is_perf))
        rank = (np.sum(oos_perf < oos_perf[best]) + 0.5 * (np.sum(oos_perf == oos_perf[best]) - 1)) / n_cfg
        w = min(max(rank + 0.5 / n_cfg, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))
    return round(float(np.mean(np.array(logits) <= 0)), 4)


def ev_breakeven_p(net_r: np.ndarray) -> float:
    """p* at which a trade's expected net R is zero: p*W - (1-p*)L = 0 -> p* = L / (W + L), W = mean winning net R,
    L = |mean losing net R| (net of the full cost stack, training rows only)."""
    w, lo = net_r[net_r > 0], net_r[net_r <= 0]
    if not len(w) or not len(lo):
        return 0.0
    W, L = float(w.mean()), float(abs(lo.mean()))
    return L / (W + L) if (W + L) > 0 else 0.0


def export_model(df: pd.DataFrame, cfg: dict, tau_rule: str = "quantile", target: str = "win") -> dict:
    """tau_rule "quantile" (V1/V2, the shipped Beagle-1): reduce the bottom q of training scores. "ev" (challenger
    RQ-20261116-cc86-01): reduce only where the predicted win probability is below the training breakeven p*, i.e.
    only entries whose predicted net R is negative."""
    X = df[list(FEATURES)].to_numpy(float)
    y, sw = target_labels(df["net_r"].to_numpy(), target)
    mu, sd, (Xs,) = standardise(X)
    coef, b = fit_logistic(Xs, y, cfg["C"], sw=sw)
    tau = (ev_breakeven_p(df["net_r"].to_numpy(float)) if tau_rule == "ev"
           else float(np.quantile(predict(Xs, coef, b), cfg["q"])))
    art = {"features": list(FEATURES), "mean": mu.tolist(), "std": sd.tolist(), "coef": coef.tolist(),
           "intercept": b, "tau": tau, "tau_rule": tau_rule, "multiplier": MULTIPLIER, "config": cfg, "n_train": int(len(df)),
           "rule": RULE_ID}
    if target != "win":
        art["target"] = target
    return art


# ----------------------------------------------------------------------------------------------- family
def parse_family(spec: str) -> tuple[str, list[str], list[str]]:
    name, legs = spec.split(":", 1)
    all_legs, gate = [], []
    for raw in legs.split(","):
        raw = raw.strip()
        if not raw:
            continue
        leg = raw.rstrip("+")
        all_legs.append(leg)
        if raw.endswith("+"):
            gate.append(leg)
    return name, all_legs, gate


def run_family(name: str, legs: list[str], gate: list[str], corpus_dir: Path, runs: dict, ref: Path | None,
               export_dir: Path | None, parity_basis: str = "net_r", holdout: dict | None = None) -> dict:
    rng = np.random.default_rng(SEED)
    frames, legrep = [], {}
    for leg in legs:
        if runs.get(leg, {}).get("state", "ok") != "ok":
            legrep[leg] = {"state": runs[leg]["state"]}
            continue
        d = load_leg(leg, corpus_dir)
        if d.empty:
            legrep[leg] = {"state": "no_trades"}
            continue
        legrep[leg] = {"n_trades": len(d), "n_scored": int(d["scored"].sum()), "n_aligned": int(d["aligned"].sum()),
                       "gate_leg": leg in gate, "net_expectancy_r": round(float(d["net_r"].mean()), 4) if len(d) else None,
                       "parity": parity(leg, d, ref, parity_basis, corpus_dir) if leg in gate else {"state": "training_only"}}
        frames.append(d)
    reasons = []
    for leg in gate:
        lr = legrep.get(leg, {})
        if "n_trades" not in lr:
            reasons.append(f"{leg}: corpus not built ({lr.get('state')})")
        elif lr["parity"].get("state") == "checked" and lr["parity"]["parity_share"] < PARITY_MIN:
            reasons.append(f"{leg}: parity {lr['parity']['parity_share']} < {PARITY_MIN}")
        elif lr["n_aligned"] < lr["n_trades"]:
            reasons.append(f"{leg}: {lr['n_trades'] - lr['n_aligned']} trades not aligned to a decision bar")
    if not frames:
        return {"family": name, "verdict": "INDETERMINATE", "reasons": reasons or ["no legs"], "legs": legrep}
    df = pd.concat(frames, ignore_index=True)
    df = df[df["scored"]].sort_values("entry_time", kind="stable").reset_index(drop=True)
    gate_mask = df["leg"].isin(gate).to_numpy()
    if gate_mask.sum() < N_GATE_MIN:
        reasons.append(f"n_gate {int(gate_mask.sum())} < {N_GATE_MIN}")
    trials = []
    by_cfg_group = []
    primary_eval = None
    for cfg in GRID:
        res = run_cpcv(df, cfg)
        ev = evaluate(df, res, gate_mask, rng)
        trials.append({"config": cfg, "primary": cfg == PRIMARY, "pass": ev["pass"],
                       "delta_mean_r": ev["delta_mean_r"], "delta_lb95_r": ev["delta_lb95_r"],
                       "reduce_rate": ev["reduce_rate"], "folds_passing": ev["folds_passing"]})
        by_cfg_group.append([f.get("delta", 0.0) for f in ev["folds"]])
        if cfg == PRIMARY:
            primary_eval = ev
    ev_all = evaluate(df, run_cpcv(df, PRIMARY), np.ones(len(df), dtype=bool), np.random.default_rng(SEED))
    verdict = "INDETERMINATE" if reasons else ("PASS" if primary_eval["pass"] else "FAIL")
    hold = None
    if holdout is not None:
        hold = run_holdout(gate, df, holdout)
        if verdict == "PASS":
            verdict = {"CONFIRMS": "PASS", "FAILS": "FAIL"}.get(hold["state"], "INDETERMINATE")
            if verdict != "PASS":
                reasons.append(f"fresh-window holdout {hold['state']}: {hold.get('reasons')}")
    out = {"family": name, "legs_all": legs, "legs_gate": gate, "n_pool_scored": int(len(df)),
           "verdict": verdict, "reasons": reasons, "primary": PRIMARY, "primary_eval": primary_eval,
           "pool_eval_primary": {k: ev_all[k] for k in ("n_gate", "delta_mean_r", "delta_lb95_r", "reduce_rate",
                                                         "reduced_mean_r", "take_all_mean_r", "folds_passing")},
           "trials": trials, "n_trials": len(trials), "pbo": pbo(np.array(by_cfg_group)), "legs": legrep,
           "parity_basis": parity_basis, "holdout": hold}
    if CPCV_CHALLENGERS["targets"]:  # --cpcv-challenger: target-variant challengers vs Beagle-1 on the same CPCV splits
        out["cpcv_challengers"] = inherit_family_state(cpcv_challengers(df, gate_mask, CPCV_CHALLENGERS["targets"]), verdict)
        chosen = out["cpcv_challengers"]["chosen"]
        if chosen in LEARNER_ARMS:   # a GBM is not a logistic overlay artifact: a PASS is exported by its own follow-up build
            out["exported_cpcv_challenger"] = None
        elif chosen and CPCV_CHALLENGERS.get("export_dir") is not None:
            ch = export_model(df, PRIMARY, target=chosen)
            ch.update({"family": name, "legs_gate": gate, "legs_train": legs, "role": "challenger",
                       "challenger_of": f"overlay_{name.lower()}.json", "rule": CPCV_RULE_ID})
            cdir = CPCV_CHALLENGERS["export_dir"]
            cdir.mkdir(parents=True, exist_ok=True)
            fp = cdir / f"overlay_{name.lower()}_{chosen}.json"
            fp.write_text(json.dumps(ch, indent=1) + "\n")
            out["exported_cpcv_challenger"] = str(fp)
    if CHALLENGER_EXPORT.get("dir") is not None:  # --export-challenger: the forward-read artifact (shadow only)
        ch = export_model(df, PRIMARY, tau_rule=CHALLENGER_EXPORT["rule"])
        ch.update({"family": name, "legs_gate": gate, "legs_train": legs, "role": "challenger",
                   "challenger_of": f"overlay_{name.lower()}.json", "rule": CHALLENGER_EXPORT["unit_rule"]})
        cdir = CHALLENGER_EXPORT["dir"]
        cdir.mkdir(parents=True, exist_ok=True)
        fp = cdir / f"overlay_{name.lower()}_{CHALLENGER_EXPORT['rule']}.json"
        fp.write_text(json.dumps(ch, indent=1) + "\n")
        out["exported_challenger"] = str(fp)
    if export_dir is not None and verdict == "PASS":
        art = export_model(df, PRIMARY)
        art.update({"family": name, "legs_gate": gate, "legs_train": legs})
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / f"overlay_{name.lower()}.json").write_text(json.dumps(art, indent=1) + "\n")
        out["exported"] = str(export_dir / f"overlay_{name.lower()}.json")
    return out


HOLDOUT_N_MIN = 100
CHALLENGER_EXPORT: dict = {"dir": None, "rule": "ev", "unit_rule": None}
CPCV_CHALLENGERS: dict = {"targets": [], "export_dir": None}
CPCV_RULE_ID = "RULE-RQ20261117-aadc-03-D4-TARGET-CHALLENGER"
MIN_DISAGREE = 0.20   # 2.3x the EV challenger's 0.0869 (cc86-01): what makes a forward paired read reachable in < 1 year


def cpcv_challengers(df: pd.DataFrame, gate_mask: np.ndarray, targets: list[str]) -> dict:
    """RQ-20261117-aadc-03. Base = Beagle-1's recipe (PRIMARY, target win) refit per CPCV split; each challenger = the
    same features, config and q but another TARGET, on the SAME splits. Per arm, on the gate legs' OOS trades:
      own:      the V1 gate (evaluate: a-e) vs take-all;
      paired:   d = (m_ch - m_base) x net_R on path-averaged multipliers (challenger_compare);
      disagree: share of (trade, path) cells where the two arms' multipliers differ.
    Arm PASS iff own pass AND paired mean > 0 AND disagree >= MIN_DISAGREE. chosen = the passing arm with the
    highest paired mean (ties: list order); None if no arm passes. Every arm is counted and reported."""
    base = run_cpcv(df, PRIMARY, "win")
    gdf = df[gate_mask].reset_index(drop=True)
    mb = np.nanmean(base["mult"], axis=1)[gate_mask]
    arms = []
    for i, t in enumerate(targets):
        res = run_cpcv(df, PRIMARY, "win", learner=t) if t in LEARNER_ARMS else run_cpcv(df, PRIMARY, t)
        own = evaluate(df, res, gate_mask, np.random.default_rng(SEED + 10 + i))
        mc = np.nanmean(res["mult"], axis=1)[gate_mask]
        paired = challenger_compare(gdf, mb, mc, np.random.default_rng(SEED + 20 + i))
        bm, cm = base["mult"][gate_mask], res["mult"][gate_mask]
        cells = ~np.isnan(bm) & ~np.isnan(cm)
        dis = float(np.mean(bm[cells] != cm[cells])) if cells.any() else 0.0
        y_rate = float(target_labels(gdf["net_r"].to_numpy(), "win" if t in LEARNER_ARMS else t)[0].mean())
        ok = bool(own["pass"] and paired["delta_ch_vs_base_mean_r"] > 0 and dis >= MIN_DISAGREE)
        arms.append({"target": t, "pass": ok, "disagree_rate_cells": round(dis, 4), "target_base_rate": round(y_rate, 4),
                     "own_checks": own["checks"], "own_delta_mean_r": own["delta_mean_r"], "own_delta_lb95_r": own["delta_lb95_r"],
                     "own_reduce_rate": own["reduce_rate"], "own_reduced_mean_r": own["reduced_mean_r"],
                     "own_folds_passing": own["folds_passing"], "paired": paired})
    passing = [a for a in arms if a["pass"]]
    chosen = max(passing, key=lambda a: a["paired"]["delta_ch_vs_base_mean_r"])["target"] if passing else None
    return {"rule": CPCV_RULE_ID, "n_gate": int(gate_mask.sum()), "min_disagree": MIN_DISAGREE, "arms": arms,
            "n_arms": len(arms), "chosen": chosen, "verdict": "PASS" if chosen else "FAIL"}


def inherit_family_state(cc: dict, family_verdict: str) -> dict:
    """PI-20261117-ZZUFKM1F-0002 (2): the challenger block INHERITS a family INDETERMINATE.

    The registered rule says an INDETERMINATE family (parity < 0.98, a gate leg that failed to build, ...) cannot grade a
    challenger; before this fix each arm still carried pass/fail and a `chosen` arm could be exported, so the results rows and the
    mechanical grader read fail/pass where the rule says indeterminate (aadc-03, hand-graded INDETERMINATE in PR #26694). The
    arms' measurements are kept (reported, never gating); `chosen` is cleared and kept as `chosen_if_determinate`."""
    if family_verdict != "INDETERMINATE":
        return cc
    out = dict(cc)
    out["chosen_if_determinate"] = cc.get("chosen")
    out["chosen"] = None
    out["verdict"] = "INDETERMINATE"
    out["arms"] = [{**a, "pass_if_determinate": a.get("pass"), "pass": False, "verdict": "INDETERMINATE"} for a in cc.get("arms", [])]
    return out


def mlgbm_holdout_scores(train_df: pd.DataFrame, X_hold: np.ndarray, q: float) -> tuple[np.ndarray, float]:
    """(P(win) on the holdout rows, tau): the monotone GBM fit on ``train_df`` only, train-standardised, tau = train-score quantile q."""
    Xt = train_df[list(FEATURES)].to_numpy(float)
    yt, _sw = target_labels(train_df["net_r"].to_numpy(float), "win")
    mu_t, sd_t, (Xs_t,) = standardise(Xt)
    ptr, pte = fit_predict_mlgbm(Xs_t, yt, (X_hold - mu_t) / sd_t, monotone_signs())
    return pte, float(np.quantile(ptr, q))


def run_holdout(gate: list[str], train_df: pd.DataFrame, h: dict, cfg: dict | None = None) -> dict:
    """Fresh-window confirmation (V2, practice M5): the PRIMARY model is fit on the WHOLE main-window family pool
    (tau from those training scores, exactly the artifact that would ship), then scores every gate-leg trade of a
    disjoint earlier window it has never seen. CONFIRMS iff (a) LB > margin, (b), (c) and (d) hold on those
    trades; random permutation within 3 calendar groups. Below HOLDOUT_N_MIN gate trades -> INDETERMINATE."""
    # --holdout-artifact: score the SHIPPED artifact byte for byte (no refit), RQ-20261116 Beagle-1 decisive read
    art = h["artifact"] if h.get("artifact") is not None else export_model(train_df, cfg or PRIMARY)
    wd = h["wd"]
    if h.get("build", True):
        _o, runs = build_corpus(gate, start=h["start"], end=h["end"], days=h["days"], wd=wd,
                                market=h.get("market", "perp"))
    else:
        runs = {}
    frames = []
    for leg in gate:
        if runs.get(leg, {}).get("state", "ok") == "ok" and (wd / f"{leg}__trades.jsonl").exists():
            d = load_leg(leg, wd)
            if d.empty:  # a leg with no candles that early (V2 unit: trend_donchian_sol_prop) contributes nothing
                continue
            frames.append(d[d["scored"] & (d["entry_time"] < h["before"])])
    if not frames:
        return {"state": "INDETERMINATE", "reasons": ["no holdout corpus"], "runs": runs}
    df = pd.concat(frames, ignore_index=True).sort_values("entry_time", kind="stable").reset_index(drop=True)
    X = df[list(FEATURES)].to_numpy(float)
    Xs = (X - np.array(art["mean"])) / np.array(art["std"])
    p = predict(Xs, np.array(art["coef"]), art["intercept"])
    m_base = np.where(p < art["tau"], MULTIPLIER, 1.0)
    # The paired challenger block is computed BEFORE the n floor so it always reports (RQ-20261116-cc86-01 holdout B
    # had n 95 and printed nothing); the holdout verdict below the floor stays INDETERMINATE.
    challenger = None
    if h.get("challenger") == "mlgbm":
        # RQ-20261122-b18a-02: the monotone-GBM learner arm (RQ-20261119-e8a1-03 dev PASS) on the disjoint earlier window. Same recipe as
        # run_cpcv(learner="mlgbm"): fit P(win) on the WHOLE main-window pool, tau = the training-score quantile PRIMARY["q"], standardise
        # with the train mean/std. Nothing here is fitted on the holdout.
        pch, tau_ch = mlgbm_holdout_scores(train_df, X, (cfg or PRIMARY)["q"])
        challenger = challenger_compare(df, m_base, np.where(pch < tau_ch, MULTIPLIER, 1.0), np.random.default_rng(SEED + 2))
        challenger.update(tau_rule="mlgbm_quantile", tau=round(tau_ch, 4))
    elif h.get("challenger"):
        ch = export_model(train_df, cfg or PRIMARY, tau_rule=h["challenger"])
        pch = predict((X - np.array(ch["mean"])) / np.array(ch["std"]), np.array(ch["coef"]), ch["intercept"])
        challenger = challenger_compare(df, m_base, np.where(pch < ch["tau"], MULTIPLIER, 1.0),
                                        np.random.default_rng(SEED + 2))
        challenger.update(tau_rule=h["challenger"], tau=round(float(ch["tau"]), 4))
    if len(df) < HOLDOUT_N_MIN:
        return {"state": "INDETERMINATE", "reasons": [f"n {len(df)} < {HOLDOUT_N_MIN}"], "n": len(df),
                "challenger": challenger, "scored_artifact": h.get("artifact_ref") or "refit PRIMARY on the main-window pool",
                "n_by_leg": df["leg"].value_counts().to_dict(), "runs": runs}
    t = df["entry_time"]
    g = np.minimum(((t - t.min()) / (t.max() - t.min()) * 3).astype(float).to_numpy().astype(int), 2)
    res = {"mult": m_base[:, None], "score": p[:, None], "groups": g,
           "y": (df["net_r"].to_numpy() > 0).astype(float)}
    ev = evaluate(df, res, np.ones(len(df), dtype=bool), np.random.default_rng(SEED + 1), n_groups=3)
    if h.get("calibrator") is not None:  # REFINE calibration: Brier skill of the calibrated score on the holdout
        pc = isotonic_apply(h["calibrator"], p)
        y = res["y"]
        base = float(h.get("base_rate", y.mean()))
        ev["calibration_refine"] = {"brier_raw": round(float(np.mean((p - y) ** 2)), 4),
                                    "brier_cal": round(float(np.mean((pc - y) ** 2)), 4),
                                    "brier_const_train_base": round(float(np.mean((base - y) ** 2)), 4)}
    ck = {k: ev["checks"][k] for k in ("a_noninferior", "b_risk", "c_beats_random", "d_not_vacuous")}
    return {"state": "CONFIRMS" if all(ck.values()) else "FAILS", "reasons": [k for k, v in ck.items() if not v],
            "challenger": challenger,
            "window": [h["start"], str(h["before"])], "n": len(df), "market": h.get("market", "perp"),
            "scored_artifact": h.get("artifact_ref") or "refit PRIMARY on the main-window pool",
            "n_by_leg": df["leg"].value_counts().to_dict(), "checks": ck,
            "eval": {k: v for k, v in ev.items() if k not in ("checks", "pass")}, "runs": runs}


def challenger_compare(df: pd.DataFrame, m_base: np.ndarray, m_ch: np.ndarray, rng: np.random.Generator) -> dict:
    """Paired per-trade comparison on one holdout: d = (m_ch - m_base) * net_R (overlay R of the challenger minus the
    baseline's). Month-block one-sided LBs at ALPHA and ALPHA/3 (the M13 re-read deflation for a third read), maxDD and
    CVaR5 of each arm, and how often they disagree. Each arm's delta vs take-all is reported beside it."""
    order = np.argsort(df["exit_time"].to_numpy())
    r = df["net_r"].to_numpy(float)
    d = (m_ch - m_base) * r
    months = pd.DatetimeIndex(df["entry_time"]).strftime("%Y-%m").to_numpy()
    rb, rc = m_base * r, m_ch * r
    return {"n": int(len(d)), "delta_ch_vs_base_mean_r": round(float(d.mean()), 4),
            "delta_ch_vs_base_lb95_r": round(month_block_lb(d, months, rng, ALPHA), 4),
            "delta_ch_vs_base_lb_deflated_r": round(month_block_lb(d, months, rng, ALPHA / 3), 4),
            "disagree_rate": round(float(np.mean(m_ch != m_base)), 4),
            "reduce_rate_base": round(float(np.mean(m_base < 1)), 4), "reduce_rate_ch": round(float(np.mean(m_ch < 1)), 4),
            "delta_base_vs_take_r": round(float((rb - r).mean()), 4), "delta_ch_vs_take_r": round(float((rc - r).mean()), 4),
            "maxdd_base_r": round(max_dd(rb[order]), 3), "maxdd_ch_r": round(max_dd(rc[order]), 3),
            "cvar5_base_r": round(cvar5(rb), 4), "cvar5_ch_r": round(cvar5(rc), 4)}


# ----------------------------------------------------------------------------------------------- REFINE (V2 follow-ups)
def isotonic_fit(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pool-adjacent-violators isotonic regression of y on p. Returns (block upper edges, block values)."""
    o = np.argsort(p, kind="stable")
    ps, ys = p[o], y[o].astype(float)
    vals, wts, tops = [], [], []
    for pi, yi in zip(ps, ys):
        vals.append(yi), wts.append(1.0), tops.append(pi)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            w = wts[-2] + wts[-1]
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / w
            vals[-2:], wts[-2:], tops[-2:] = [v], [w], [tops[-1]]
    return np.array(tops), np.clip(np.array(vals), 1e-3, 1 - 1e-3)


def isotonic_apply(cal: tuple[np.ndarray, np.ndarray], p: np.ndarray) -> np.ndarray:
    tops, vals = cal
    return vals[np.minimum(np.searchsorted(tops, p, side="left"), len(vals) - 1)]


def run_calibration(df: pd.DataFrame, gate_mask: np.ndarray, rng: np.random.Generator, cfg: dict) -> dict:
    """REFINE-CAL: per CPCV split, the logistic is fit on the EARLIER 75% of the training rows (by entry time) and
    an isotonic calibrator on the LATER 25%; both score the test block. Decisions are NOT changed by this mode
    (a monotone map of a quantile threshold); it measures whether the probabilities carry skill over the
    TRAINING base rate (the climatology a forecaster would otherwise use)."""
    X = df[list(FEATURES)].to_numpy(float)
    y = (df["net_r"].to_numpy() > 0).astype(float)
    n = len(df)
    raw, cal, const = (np.full((n, math.comb(N_GROUPS - 1, K_TEST - 1)), np.nan) for _ in range(3))
    seen = np.zeros(N_GROUPS, dtype=int)
    for _sid, tg, train, test, g in cpcv_splits(df["entry_time"], df["exit_time"]):
        tr = np.where(train)[0]
        cut = tr[: int(len(tr) * 0.75)], tr[int(len(tr) * 0.75):]
        mu, sd, (Xa, Xb, Xte) = standardise(X[cut[0]], X[cut[1]], X[test])
        coef, b = fit_logistic(Xa, y[cut[0]], cfg["C"])
        calr = isotonic_fit(predict(Xb, coef, b), y[cut[1]])
        pte = predict(Xte, coef, b)
        te_idx = np.where(test)[0]
        for k in tg:
            col = seen[k]
            loc = g[te_idx] == k
            raw[te_idx[loc], col] = pte[loc]
            cal[te_idx[loc], col] = isotonic_apply(calr, pte[loc])
            const[te_idx[loc], col] = float(y[tr].mean())
            seen[k] += 1
    yg = y[gate_mask]
    br = np.nanmean((raw - y[:, None]) ** 2, axis=1)[gate_mask]
    bc = np.nanmean((cal - y[:, None]) ** 2, axis=1)[gate_mask]
    bk = np.nanmean((const - y[:, None]) ** 2, axis=1)[gate_mask]
    months = pd.DatetimeIndex(df["entry_time"][gate_mask]).strftime("%Y-%m").to_numpy()
    gain = bk - bc
    return {"n_gate": int(gate_mask.sum()), "base_rate": round(float(yg.mean()), 4),
            "brier_raw": round(float(br.mean()), 5), "brier_cal": round(float(bc.mean()), 5),
            "brier_const": round(float(bk.mean()), 5),
            "bss_raw": round(float(1 - br.mean() / bk.mean()), 5), "bss_cal": round(float(1 - bc.mean() / bk.mean()), 5),
            "cal_gain_lb95": round(month_block_lb(gain, months, rng, ALPHA), 6),
            "ece_raw": calib(np.nanmean(raw, axis=1)[gate_mask], yg).get("ece"),
            "ece_cal": calib(np.nanmean(cal, axis=1)[gate_mask], yg).get("ece")}


def _inner_select(df: pd.DataFrame, train: np.ndarray, gate_mask: np.ndarray) -> dict:
    """Choose a GRID config using ONLY the outer training rows: a purged, embargoed 5-fold time split inside
    them, scoring each config by its mean delta net R on the training rows' gate trades."""
    sub = df[train].reset_index(drop=True)
    gm = gate_mask[train]
    X = sub[list(FEATURES)].to_numpy(float)
    y = (sub["net_r"].to_numpy() > 0).astype(float)
    R = sub["net_r"].to_numpy()
    t, e = sub["entry_time"], sub["exit_time"]
    t0, t1 = t.min(), t.max()
    gi = np.minimum(((t - t0) / (t1 - t0) * 5).astype(float).to_numpy().astype(int), 4)
    edges = [t0 + (t1 - t0) * i / 5 for i in range(6)]
    emb = pd.Timedelta(days=EMBARGO_DAYS)
    score = {}
    for ci, cfg in enumerate(GRID):
        d_sum, d_n = 0.0, 0
        for k in range(5):
            te = gi == k
            tr = ~te & ~((e >= edges[k]).to_numpy() & (t <= edges[k + 1] + emb).to_numpy())
            if tr.sum() < 50 or te.sum() == 0:
                continue
            _m, _s, (Xtr, Xte) = standardise(X[tr], X[te])
            coef, b = fit_logistic(Xtr, y[tr], cfg["C"])
            tau = float(np.quantile(predict(Xtr, coef, b), cfg["q"]))
            mlt = np.where(predict(Xte, coef, b) < tau, MULTIPLIER, 1.0)
            sel = gm[te]
            d_sum += float(np.sum((mlt[sel] - 1.0) * R[te][sel]))
            d_n += int(sel.sum())
        score[ci] = d_sum / max(d_n, 1)
    return GRID[max(score, key=lambda c: (score[c], -c))]


def run_cpcv_nested(df: pd.DataFrame, gate_mask: np.ndarray) -> dict:
    """REFINE-NESTED: like run_cpcv, but each outer split uses the config _inner_select picks from its own
    training rows, so configuration selection is inside the out-of-sample loop (the PBO concern)."""
    X = df[list(FEATURES)].to_numpy(float)
    y = (df["net_r"].to_numpy() > 0).astype(float)
    n = len(df)
    mult = np.full((n, math.comb(N_GROUPS - 1, K_TEST - 1)), np.nan)
    score = np.full_like(mult, np.nan)
    seen = np.zeros(N_GROUPS, dtype=int)
    picks, groups = [], None
    for _sid, tg, train, test, g in cpcv_splits(df["entry_time"], df["exit_time"]):
        groups = g
        cfg = _inner_select(df, train, gate_mask)
        picks.append(cfg)
        _mu, _sd, (Xtr, Xte) = standardise(X[train], X[test])
        coef, b = fit_logistic(Xtr, y[train], cfg["C"])
        tau = float(np.quantile(predict(Xtr, coef, b), cfg["q"]))
        pte = predict(Xte, coef, b)
        te_idx = np.where(test)[0]
        for k in tg:
            col = seen[k]
            loc = g[te_idx] == k
            mult[te_idx[loc], col] = np.where(pte[loc] < tau, MULTIPLIER, 1.0)
            score[te_idx[loc], col] = pte[loc]
            seen[k] += 1
    freq = {json.dumps(c, sort_keys=True): sum(1 for p_ in picks if p_ == c) for c in GRID}
    return {"mult": mult, "score": score, "groups": groups, "y": y, "picks": freq}


def run_refine(mode: str, name: str, legs: list[str], gate: list[str], corpus_dir: Path, holdout: dict | None) -> dict:
    rng = np.random.default_rng(SEED)
    frames = [d for d in (load_leg(leg, corpus_dir) for leg in legs) if not d.empty]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["scored"]].sort_values("entry_time", kind="stable").reset_index(drop=True)
    gate_mask = df["leg"].isin(gate).to_numpy()
    out: dict = {"family": name, "mode": mode, "legs_gate": gate, "n_pool_scored": int(len(df)),
                 "n_gate": int(gate_mask.sum())}
    if gate_mask.sum() < N_GATE_MIN:
        out.update(verdict="INDETERMINATE", reasons=[f"n_gate {int(gate_mask.sum())} < {N_GATE_MIN}"])
        return out
    if mode == "calibration":
        main = run_calibration(df, gate_mask, rng, PRIMARY)
        hold = None
        if holdout is not None:
            tr = np.arange(len(df))
            cut = tr[: int(len(tr) * 0.75)], tr[int(len(tr) * 0.75):]
            X = df[list(FEATURES)].to_numpy(float)
            y = (df["net_r"].to_numpy() > 0).astype(float)
            art = export_model(df.iloc[cut[0]], PRIMARY)
            pb = predict((X[cut[1]] - np.array(art["mean"])) / np.array(art["std"]), np.array(art["coef"]),
                         art["intercept"])
            # build follows the CLI (False only with --holdout-corpus-dir); a hard False left runner holdouts empty (7e18-03)
            h = {**holdout, "calibrator": isotonic_fit(pb, y[cut[1]]), "base_rate": float(y.mean())}
            hold = run_holdout(gate, df.iloc[cut[0]], h)
        hc = ((hold or {}).get("eval") or {}).get("calibration_refine") or {}
        ok_main = main["cal_gain_lb95"] > 0
        ok_hold = bool(hc) and hc["brier_cal"] < hc["brier_const_train_base"]
        verdict = "CALIBRATED" if (ok_main and ok_hold) else (
            "INDETERMINATE" if hold is not None and hold.get("state") == "INDETERMINATE" else "NOT_CALIBRATED")
        out.update(verdict=verdict, main=main, holdout_calibration=hc, holdout_n=(hold or {}).get("n"),
                   checks={"main_cal_gain_lb95_gt_0": ok_main, "holdout_brier_cal_lt_const": ok_hold})
        return out
    res = run_cpcv_nested(df, gate_mask)
    ev = evaluate(df, res, gate_mask, rng)
    picks = res["picks"]
    top = json.loads(max(picks, key=picks.get))
    # build follows the CLI: a hard False here left every runner nested holdout "no holdout corpus" (RQ-20261115-7e18-03)
    hold = run_holdout(gate, df, dict(holdout), cfg=top) if holdout is not None else None
    verdict = "PASS" if ev["pass"] and (hold is None or hold["state"] == "CONFIRMS") else (
        "INDETERMINATE" if hold is not None and hold["state"] == "INDETERMINATE" else "FAIL")
    out.update(verdict=verdict, nested_eval={k: v for k, v in ev.items() if k != "folds"}, folds=ev["folds"],
               selection_frequency=picks, n_outer_splits=sum(picks.values()), modal_config=top,
               modal_share=round(picks[max(picks, key=picks.get)] / max(sum(picks.values()), 1), 4),
               holdout=hold)
    return out


# ----------------------------------------------------------------------------------------------- self-test
def repin_fidelity_verdict(results: list[dict], rule_id: str, corpus: Path, old_ref: Path | None, edge: dict) -> dict:
    """RULE-RQ20261118-04a5-06 (PI-20261117-ZZUFKM1F-0002 part 1). With no --reference-corpus, run_family's reasons are exactly the
    FIDELITY failures (gate leg not built, trades not aligned to a decision bar, n_gate < N_GATE_MIN), so a family PASSES fidelity iff
    it has no reasons. The edge verdict (Beagle-1's recipe on the re-pinned population) and trade parity vs the old reference are
    REPORTED, never gating."""
    fams = {}
    for r in results:
        gate = r.get("legs_gate") or [k for k, v in (r.get("legs") or {}).items() if isinstance(v, dict) and v.get("gate_leg")]
        par = {leg: _trade_parity(leg, old_ref, corpus) for leg in gate} if old_ref is not None else None
        fams[r["family"]] = {"fidelity": "pass" if not r["reasons"] else "fail", "reasons": r["reasons"],
                             "edge_verdict_context": r["verdict"], "n_gate": (r.get("primary_eval") or {}).get("n_gate"),
                             "legs": {k: {kk: v.get(kk) for kk in ("state", "n_trades", "n_aligned", "gate_leg")} if isinstance(v, dict) else v
                                      for k, v in (r.get("legs") or {}).items()},
                             "parity_vs_old_reference": par}
    vs = [f["fidelity"] for f in fams.values()]
    top = "pass" if vs and all(v == "pass" for v in vs) else "fail"
    return {"rule": rule_id, "read_state": "measured", "verdict": top, "window": edge.get("window"),
            "population": "re-pinned TD corpus at current config: " + "; ".join(
                f"{k} n_gate={f['n_gate']} fidelity {f['fidelity']}" for k, f in fams.items()),
            "n": sum(int(f["n_gate"] or 0) for f in fams.values()) or None,
            "note": "fidelity per family: " + ", ".join(f"{k} {f['fidelity']} {f['reasons'] or ''}" for k, f in fams.items())
                    + "; edge verdict (context, not gating): " + str(edge.get("verdict")),
            "families": fams, "corpus_dir": str(corpus), "edge_verdict_context": edge,
            "records": [{"family": k, "verdict": f["fidelity"], "n": f["n_gate"],
                         "population": f"{k} gate legs, re-pinned corpus"} for k, f in fams.items()]}


def _self_test() -> int:
    """Synthetic: an informative feature must PASS non-inferiority and beat random; noise must not beat random."""
    import tempfile
    rng = np.random.default_rng(1)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ts = pd.date_range("2020-01-01", periods=6000, freq="4h", tz="UTC")
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(ts))))
        pd.DataFrame({"timestamp": ts, "open": close, "high": close * 1.004, "low": close * 0.996,
                      "close": close, "volume": 1.0}).to_csv(d / "syn__data.csv", index=False)
        for leg, informative in (("syn", True), ("noise", False)):
            if leg == "noise":
                pd.read_csv(d / "syn__data.csv").to_csv(d / "noise__data.csv", index=False)
            rows = []
            for i in range(300, len(ts) - 10, 9):
                direction = "long" if rng.random() < 0.5 else "short"
                f = decision_features({"high": close[:i + 1] * 1.004, "low": close[:i + 1] * 0.996,
                                       "close": close[:i + 1]}, direction)
                edge = 0.8 * f["ret5_signed"] if informative else 0.0
                win = rng.random() < 1 / (1 + math.exp(-(edge - 0.5)))
                r = (2.0 if win else -1.0) - 0.05
                rows.append({"entry_time": str(ts[i]), "exit_time": str(ts[i + 3]), "direction": direction,
                             "net_r": r, "entry": float(close[i])})
            with open(d / f"{leg}__trades.jsonl", "w") as fh:
                fh.write("\n".join(json.dumps(x) for x in rows) + "\n")
        a = run_family("SYN", ["syn"], ["syn"], d, {}, None, None)
        CPCV_CHALLENGERS.update(targets=["tail1r", "evweight", "mlgbm"])
        try:
            cpa = run_family("SYN", ["syn"], ["syn"], d, {}, None, None)["cpcv_challengers"]
        finally:
            CPCV_CHALLENGERS.update(targets=[])
        b = run_family("NOISE", ["noise"], ["noise"], d, {}, None, None)
        rc = run_refine("calibration", "SYN", ["syn"], ["syn"], d, None)
        rn = run_refine("nested", "SYN", ["syn"], ["syn"], d, None)
    pa, pb = a["primary_eval"], b["primary_eval"]
    # target plumbing: win reproduces the unweighted default; uniform weights are a no-op; tail1r labels >= 1 R
    # holdout mlgbm challenger (RQ-20261122-b18a-02): scores only the holdout rows, tau from TRAIN scores only, plumbing on a synthetic frame
    tdf = pd.DataFrame(rng.normal(size=(400, len(FEATURES))), columns=list(FEATURES))
    tdf["net_r"] = np.where(tdf[FEATURES[0]] + rng.normal(size=400) > 0, 1.5, -1.0)
    hold_X = rng.normal(size=(120, len(FEATURES)))
    ph, tau_h = mlgbm_holdout_scores(tdf, hold_X, 0.25)
    assert ph.shape == (120,) and 0.0 < tau_h < 1.0 and 0.05 <= float(np.mean(ph < tau_h)) <= 0.6, "mlgbm holdout scores"
    r_ = np.array([2.0, -1.0, 0.5, 1.0])
    assert target_labels(r_, "tail1r")[0].tolist() == [1.0, 0.0, 0.0, 1.0]
    assert target_labels(r_, "win")[1] is None and target_labels(r_, "evweight")[1].tolist() == [2.0, 1.0, 0.5, 1.0]
    Xs_ = rng.normal(size=(200, 3))
    ys_ = (Xs_[:, 0] + rng.normal(size=200) > 0).astype(float)
    c1, b1 = fit_logistic(Xs_, ys_, 1.0)
    c2, b2 = fit_logistic(Xs_, ys_, 1.0, sw=np.full(200, 3.0))
    assert np.allclose(c1, c2) and abs(b1 - b2) < 1e-9
    assert cpa["n_arms"] == 3 and all(0.0 <= x["disagree_rate_cells"] <= 1.0 for x in cpa["arms"]), cpa
    assert {x["target"] for x in cpa["arms"]} == {"tail1r", "evweight", "mlgbm"} and cpa["verdict"] in ("PASS", "FAIL")
    # RQ-20261119-e8a1-03: monotone signs come from the committed Beagle-1 coefficients; tiny coefficients are unconstrained
    _sg = monotone_signs()
    assert len(_sg) == len(FEATURES) and set(_sg) <= {-1, 0, 1}
    _art = json.loads((REPO / "ml/overlay/overlay_td.json").read_text())
    _cf = dict(zip(_art["features"], _art["coef"]))
    assert all(sg == 0 if abs(_cf[f]) < MONO_MIN_ABS_COEF else sg == (1 if _cf[f] > 0 else -1) for f, sg in zip(FEATURES, _sg))
    rf_ok = repin_fidelity_verdict([{"family": "F", "reasons": [], "verdict": "FAIL", "legs_gate": ["x"], "legs": {},
                                      "primary_eval": {"n_gate": 250}}], "R", Path("."), None, {"verdict": "fail"})
    rf_bad = repin_fidelity_verdict([{"family": "F", "reasons": ["x: 3 trades not aligned to a decision bar"], "verdict": "INDETERMINATE",
                                       "legs_gate": ["x"], "legs": {}, "primary_eval": {"n_gate": 250}}], "R", Path("."), None, {})
    assert rf_ok["verdict"] == "pass" and rf_ok["n"] == 250 and rf_ok["families"]["F"]["edge_verdict_context"] == "FAIL"
    assert rf_bad["verdict"] == "fail" and rf_bad["records"][0]["verdict"] == "fail"
    inh = inherit_family_state({"chosen": "tail1r", "verdict": "PASS", "arms": [{"target": "tail1r", "pass": True}]}, "INDETERMINATE")
    assert inh["chosen"] is None and inh["verdict"] == "INDETERMINATE" and inh["chosen_if_determinate"] == "tail1r"
    assert inh["arms"][0]["pass"] is False and inh["arms"][0]["verdict"] == "INDETERMINATE" and inh["arms"][0]["pass_if_determinate"] is True
    assert inherit_family_state(cpa, "PASS") is cpa and inherit_family_state(cpa, "FAIL") is cpa
    ok = (pa["checks"]["c_beats_random"] and pa["checks"]["d_not_vacuous"] and pa["delta_mean_r"] > pb["delta_mean_r"]
          and not pb["checks"]["c_beats_random"] and a["n_trials"] == len(GRID) and 0.0 <= a["pbo"] <= 1.0
          and np.allclose(pa["reduce_rate"], PRIMARY["q"], atol=0.08)
          and rc["main"]["brier_cal"] > 0 and rc["verdict"] in ("CALIBRATED", "NOT_CALIBRATED")
          and rn["n_outer_splits"] == math.comb(N_GROUPS, K_TEST) and rn["nested_eval"]["checks"]["c_beats_random"])
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "informative": {k: pa[k] for k in (
        "delta_mean_r", "delta_lb95_r", "random_p_value", "reduce_rate", "folds_passing")},
        "noise": {k: pb[k] for k in ("delta_mean_r", "random_p_value", "reduce_rate")},
        "refine_calibration": {k: rc["main"][k] for k in ("bss_raw", "bss_cal")}, "refine_nested_picks": rn["selection_frequency"]},
        indent=1))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--family", action="append", required=True, help="NAME:leg+,leg,... (+ = real-money gate leg)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--days", type=int, required=True)
    ap.add_argument("--reference-corpus", default=None)
    ap.add_argument("--repin-fidelity", default=None, metavar="RULE_ID",
                    help="RQ-20261118-04a5-06: grade the run by the FIDELITY rule (every gate leg built, all trades aligned, n_gate >= N_GATE_MIN) instead of the edge rule; the edge verdict is reported as context. Use with no --reference-corpus.")
    ap.add_argument("--report-parity-against", default=None,
                    help="report-only trade parity of the built corpus vs this (old) reference corpus, per gate leg; never gating")
    ap.add_argument("--corpus-dir", default=None, help="reuse an already-built corpus dir instead of running the harness")
    ap.add_argument("--export-dir", default=None)
    ap.add_argument("--parity-basis", choices=("net_r", "trade"), default="net_r",
                    help="V1 net_r (default, unchanged); V2 trade = same entry/exit/direction/gross_r")
    ap.add_argument("--holdout-start", default=None, help="V2: disjoint earlier window for the blind confirmation")
    ap.add_argument("--holdout-end", default=None)
    ap.add_argument("--holdout-days", type=int, default=None)
    ap.add_argument("--holdout-corpus-dir", default=None,
                    help="reuse an already-built holdout corpus (same window) instead of re-running the harness")
    ap.add_argument("--holdout-market", choices=("perp", "spot"), default="perp",
                    help="spot = build the holdout from Binance SPOT candles, a labelled perp PROXY (RQ-20261029-5785-05)")
    ap.add_argument("--holdout-artifact", default=None,
                    help="score this committed artifact JSON on the holdout instead of refitting PRIMARY (byte-exact replay)")
    ap.add_argument("--holdout-challenger", choices=("ev", "mlgbm"), default=None,
                    help="also fit a CHALLENGER (tau_rule ev) on the main-window pool and compare it, paired, to the scored "
                         "baseline on the holdout (RQ-20261116-cc86-01)")
    ap.add_argument("--export-challenger", default=None,
                    help="write the tau_rule=ev challenger, fit on the main-window family pool, to this dir "
                         "(the forward shadow read's artifact; training window only, reads no holdout)")
    ap.add_argument("--cpcv-challenger", action="append", choices=("tail1r", "evweight") + LEARNER_ARMS, default=[],
                    help="RQ-20261117-aadc-03: a TARGET-variant challenger compared, paired, with Beagle-1 on the same CPCV "
                         "splits (repeatable; every arm counted)")
    ap.add_argument("--export-cpcv-challenger", default=None,
                    help="write the chosen --cpcv-challenger arm (fit on the main-window pool) here, only if one PASSES")
    ap.add_argument("--refine", choices=("calibration", "nested"), default=None,
                    help="V2 follow-up units: RULE-ML-OVERLAY-CALIBRATION-V1 / RULE-ML-OVERLAY-NESTED-SELECT-V1")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cpcv_challenger:
        CPCV_CHALLENGERS.update(targets=list(dict.fromkeys(a.cpcv_challenger)),
                                export_dir=Path(a.export_cpcv_challenger) if a.export_cpcv_challenger else None)
    if a.export_challenger:
        CHALLENGER_EXPORT.update(dir=Path(a.export_challenger), rule="ev", unit_rule="RULE-RQ20261116-cc86-01-BEAGLE1-CHALLENGER-EV")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fams = [parse_family(s) for s in a.family]
    all_legs = list(dict.fromkeys(leg for _n, legs, _g in fams for leg in legs))
    if a.corpus_dir:
        corpus, runs = Path(a.corpus_dir), {}
    else:
        corpus = out / "corpus"
        corpus.mkdir(parents=True, exist_ok=True)
        _o, runs = build_corpus(all_legs, start=a.start, end=a.end, days=a.days, wd=corpus)
    ref = Path(a.reference_corpus) if a.reference_corpus else None
    holdout = None
    if a.holdout_start:
        hwd = Path(a.holdout_corpus_dir) if a.holdout_corpus_dir else out / "holdout_corpus"
        hwd.mkdir(parents=True, exist_ok=True)
        holdout = {"start": a.holdout_start, "end": a.holdout_end, "days": a.holdout_days, "wd": hwd,
                   "build": not a.holdout_corpus_dir, "market": a.holdout_market, "challenger": a.holdout_challenger,
                   "artifact": json.loads(Path(a.holdout_artifact).read_text()) if a.holdout_artifact else None,
                   "artifact_ref": (f"{a.holdout_artifact} sha256 "
                                    + hashlib.sha256(Path(a.holdout_artifact).read_bytes()).hexdigest())
                                   if a.holdout_artifact else None,
                   "before": pd.Timestamp(a.start, tz="UTC") - pd.Timedelta(days=EMBARGO_DAYS)}
    if a.refine:
        rr = [run_refine(a.refine, n, legs, g, corpus, holdout) for n, legs, g in fams]
        rule = {"calibration": "RULE-ML-OVERLAY-CALIBRATION-V1", "nested": "RULE-ML-OVERLAY-NESTED-SELECT-V1"}[a.refine]
        fv = [r["verdict"] for r in rr]
        good = {"calibration": "CALIBRATED", "nested": "PASS"}[a.refine]
        v = {"rule": rule, "read_state": "measured",
             "verdict": "indeterminate" if "INDETERMINATE" in fv else ("pass" if good in fv else "fail"),
             "population": "; ".join(f"{r['family']} n_gate={r['n_gate']}" for r in rr),
             "n": sum(r["n_gate"] for r in rr) or None,
             "note": "per family: " + ", ".join(f"{r['family']} {r['verdict']}" for r in rr),
             "records": [{"family": r["family"], "state": r["verdict"],
                          "verdict": {"CALIBRATED": "pass", "NOT_CALIBRATED": "fail"}.get(r["verdict"], r["verdict"].lower()),
                          "n": r["n_gate"],
                          "population": f"{r['family']} gate legs {','.join(r['legs_gate'])}"} for r in rr]}
        (out / "measurement.json").write_text(json.dumps({"runs": runs, "families": rr}, indent=1, default=str) + "\n")
        (out / "verdict.json").write_text(json.dumps(v, indent=1) + "\n")
        print(json.dumps(v, indent=1))
        return 0
    results = [run_family(n, legs, g, corpus, runs, ref, Path(a.export_dir) if a.export_dir else None,
                          a.parity_basis, holdout) for n, legs, g in fams]
    verdict = {"rule": RULE_ID if a.parity_basis == "net_r" and not a.holdout_start else RULE_ID.replace("-V1", "-V2"),
               "window": [a.start, a.end], "multiplier": MULTIPLIER, "primary": PRIMARY,
               "grid": GRID, "cpcv": {"n_groups": N_GROUPS, "k_test": K_TEST, "embargo_days": EMBARGO_DAYS},
               "families": {r["family"]: {"verdict": r["verdict"], "reasons": r["reasons"]} for r in results},
               "read_state": "measured"}
    fv = [r["verdict"] for r in results]
    # Top-level token for the research-result collector; each family's own verdict is a fanned-out record.
    verdict["verdict"] = ("indeterminate" if "INDETERMINATE" in fv else "pass" if "PASS" in fv else "fail")
    verdict["population"] = ("real-money gate legs' CPCV out-of-sample Stage-0 trades, per family: " + "; ".join(
        f"{r['family']} n_gate={(r.get('primary_eval') or {}).get('n_gate')} ({','.join(r.get('legs_gate', []))})"
        for r in results))
    verdict["n"] = sum(int((r.get("primary_eval") or {}).get("n_gate") or 0) for r in results) or None
    verdict["note"] = "per family: " + ", ".join(f"{r['family']} {r['verdict']}" for r in results) + (
        ". Top-level pass = at least one family passed; only a PASS family ships." if "PASS" in fv else "")
    verdict["records"] = [{"family": r["family"], "verdict": r["verdict"].lower(), "n": (r.get("primary_eval") or {}).get("n_gate"),
                           "population": f"{r['family']} gate legs {','.join(r.get('legs_gate', []))}",
                           "checks": (r.get("primary_eval") or {}).get("checks"), "reasons": r["reasons"]} for r in results]
    if CPCV_CHALLENGERS["targets"]:
        # The unit's registered rule is the CHALLENGER rule: the family V1 verdict is context, the arms decide.
        cc = [r.get("cpcv_challengers") for r in results]
        fam_state = {r["family"]: r["verdict"] for r in results}
        verdict.update({
            "rule": CPCV_RULE_ID,
            "verdict": ("indeterminate" if any(c is None or fam_state[r["family"]] == "INDETERMINATE"
                                               for c, r in zip(cc, results))
                        else "pass" if any(c["chosen"] for c in cc) else "fail"),
            "note": "; ".join(f"{r['family']}: chosen {c['chosen'] if c else None}, arms " + ", ".join(
                f"{a['target']} {'PASS' if a['pass'] else 'FAIL'} (paired {a['paired']['delta_ch_vs_base_mean_r']:+.4f}, "
                f"disagree {a['disagree_rate_cells']:.3f}, own {'pass' if all(a['own_checks'].values()) else 'fail'})"
                for a in (c["arms"] if c else [])) for c, r in zip(cc, results)),
            "records": [{"family": r["family"], "target": a["target"],
                         "verdict": ("indeterminate" if fam_state[r["family"]] == "INDETERMINATE" else "pass" if a["pass"] else "fail"),
                         "n": c["n_gate"], "population": f"{r['family']} gate legs CPCV OOS trades, arm {a['target']}",
                         "paired": a["paired"], "disagree_rate_cells": a["disagree_rate_cells"], "own_checks": a["own_checks"]}
                        for c, r in zip(cc, results) if c for a in c["arms"]] or verdict["records"],
        })
    if a.repin_fidelity:
        old_ref = Path(a.report_parity_against) if a.report_parity_against else None
        verdict = repin_fidelity_verdict(results, a.repin_fidelity, corpus, old_ref, verdict)
    (out / "measurement.json").write_text(json.dumps({"runs": runs, "families": results}, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
