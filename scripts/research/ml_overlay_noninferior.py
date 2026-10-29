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
import json
import math
import sys
from pathlib import Path
from typing import Any

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


# ----------------------------------------------------------------------------------------------- model
def fit_logistic(X: np.ndarray, y: np.ndarray, C: float, iters: int = 50) -> tuple[np.ndarray, float]:
    """L2-penalised logistic regression by Newton/IRLS (penalty 1/(2C)||w||^2, intercept unpenalised).
    Deterministic; numpy only (the research runner installs no sklearn)."""
    n, p = X.shape
    Xa = np.hstack([np.ones((n, 1)), X])
    w = np.zeros(p + 1)
    lam = np.full(p + 1, 1.0 / C)
    lam[0] = 0.0
    for _ in range(iters):
        z = np.clip(Xa @ w, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-z))
        g = Xa.T @ (mu - y) + lam * w
        H = (Xa * (mu * (1 - mu))[:, None]).T @ Xa + np.diag(lam) + 1e-9 * np.eye(p + 1)
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
def build_corpus(legs: list[str], *, start: str, end: str, days: int, wd: Path) -> tuple[dict, dict]:
    """Run each leg's config-exact harness with --emit-paths (one argv builder, path_metric_giveback)."""
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
            _paths, meta = run_leg_paths(leg, base, days=days, start=start, end=end, wd=wd, data_csv=None,
                                         non_crypto_source="auto")
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


def run_cpcv(df: pd.DataFrame, cfg: dict) -> dict:
    """Out-of-sample reduce decisions per trade per CPCV path. Returns m (n x paths multiplier), p (scores)."""
    X = df[list(FEATURES)].to_numpy(float)
    y = (df["net_r"].to_numpy() > 0).astype(float)
    n = len(df)
    n_paths = math.comb(N_GROUPS - 1, K_TEST - 1)
    mult = np.full((n, n_paths), np.nan)
    score = np.full((n, n_paths), np.nan)
    seen = np.zeros(N_GROUPS, dtype=int)
    groups = None
    for _sid, tg, train, test, g in cpcv_splits(df["entry_time"], df["exit_time"]):
        groups = g
        _mu, _sd, (Xtr, Xte) = standardise(X[train], X[test])
        coef, b = fit_logistic(Xtr, y[train], cfg["C"])
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


def export_model(df: pd.DataFrame, cfg: dict) -> dict:
    X = df[list(FEATURES)].to_numpy(float)
    y = (df["net_r"].to_numpy() > 0).astype(float)
    mu, sd, (Xs,) = standardise(X)
    coef, b = fit_logistic(Xs, y, cfg["C"])
    tau = float(np.quantile(predict(Xs, coef, b), cfg["q"]))
    return {"features": list(FEATURES), "mean": mu.tolist(), "std": sd.tolist(), "coef": coef.tolist(),
            "intercept": b, "tau": tau, "multiplier": MULTIPLIER, "config": cfg, "n_train": int(len(df)),
            "rule": RULE_ID}


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
        hold = run_holdout(name, legs, gate, df, holdout)
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
    if export_dir is not None and verdict == "PASS":
        art = export_model(df, PRIMARY)
        art.update({"family": name, "legs_gate": gate, "legs_train": legs})
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / f"overlay_{name.lower()}.json").write_text(json.dumps(art, indent=1) + "\n")
        out["exported"] = str(export_dir / f"overlay_{name.lower()}.json")
    return out


HOLDOUT_N_MIN = 100


def run_holdout(name: str, legs: list[str], gate: list[str], train_df: pd.DataFrame, h: dict) -> dict:
    """Fresh-window confirmation (V2, practice M5): the PRIMARY model is fit on the WHOLE main-window family pool
    (tau from those training scores, exactly the artifact that would ship), then scores every gate-leg trade of a
    disjoint earlier window it has never seen. CONFIRMS iff (a) LB > margin, (b), (c) and (d) hold on those
    trades; random permutation within 3 calendar groups. Below HOLDOUT_N_MIN gate trades -> INDETERMINATE."""
    art = export_model(train_df, PRIMARY)
    wd = h["wd"]
    if h.get("build", True):
        _o, runs = build_corpus(gate, start=h["start"], end=h["end"], days=h["days"], wd=wd)
    else:
        runs = {}
    frames = []
    for leg in gate:
        if runs.get(leg, {}).get("state", "ok") == "ok" and (wd / f"{leg}__trades.jsonl").exists():
            d = load_leg(leg, wd)
            frames.append(d[d["scored"] & (d["entry_time"] < h["before"])])
    if not frames:
        return {"state": "INDETERMINATE", "reasons": ["no holdout corpus"], "runs": runs}
    df = pd.concat(frames, ignore_index=True).sort_values("entry_time", kind="stable").reset_index(drop=True)
    if len(df) < HOLDOUT_N_MIN:
        return {"state": "INDETERMINATE", "reasons": [f"n {len(df)} < {HOLDOUT_N_MIN}"], "n": len(df), "runs": runs}
    X = df[list(FEATURES)].to_numpy(float)
    Xs = (X - np.array(art["mean"])) / np.array(art["std"])
    p = predict(Xs, np.array(art["coef"]), art["intercept"])
    t = df["entry_time"]
    g = np.minimum(((t - t.min()) / (t.max() - t.min()) * 3).astype(float).to_numpy().astype(int), 2)
    res = {"mult": np.where(p < art["tau"], MULTIPLIER, 1.0)[:, None], "score": p[:, None], "groups": g,
           "y": (df["net_r"].to_numpy() > 0).astype(float)}
    ev = evaluate(df, res, np.ones(len(df), dtype=bool), np.random.default_rng(SEED + 1), n_groups=3)
    ck = {k: ev["checks"][k] for k in ("a_noninferior", "b_risk", "c_beats_random", "d_not_vacuous")}
    return {"state": "CONFIRMS" if all(ck.values()) else "FAILS", "reasons": [k for k, v in ck.items() if not v],
            "window": [h["start"], str(h["before"])], "n": len(df),
            "n_by_leg": df["leg"].value_counts().to_dict(), "checks": ck,
            "eval": {k: v for k, v in ev.items() if k not in ("checks", "pass")}, "runs": runs}


# ----------------------------------------------------------------------------------------------- self-test
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
        b = run_family("NOISE", ["noise"], ["noise"], d, {}, None, None)
    pa, pb = a["primary_eval"], b["primary_eval"]
    ok = (pa["checks"]["c_beats_random"] and pa["checks"]["d_not_vacuous"] and pa["delta_mean_r"] > pb["delta_mean_r"]
          and not pb["checks"]["c_beats_random"] and a["n_trials"] == len(GRID) and 0.0 <= a["pbo"] <= 1.0
          and np.allclose(pa["reduce_rate"], PRIMARY["q"], atol=0.08))
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "informative": {k: pa[k] for k in (
        "delta_mean_r", "delta_lb95_r", "random_p_value", "reduce_rate", "folds_passing")},
        "noise": {k: pb[k] for k in ("delta_mean_r", "random_p_value", "reduce_rate")}}, indent=1))
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
    ap.add_argument("--corpus-dir", default=None, help="reuse an already-built corpus dir instead of running the harness")
    ap.add_argument("--export-dir", default=None)
    ap.add_argument("--parity-basis", choices=("net_r", "trade"), default="net_r",
                    help="V1 net_r (default, unchanged); V2 trade = same entry/exit/direction/gross_r")
    ap.add_argument("--holdout-start", default=None, help="V2: disjoint earlier window for the blind confirmation")
    ap.add_argument("--holdout-end", default=None)
    ap.add_argument("--holdout-days", type=int, default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
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
        hwd = out / "holdout_corpus"
        hwd.mkdir(parents=True, exist_ok=True)
        holdout = {"start": a.holdout_start, "end": a.holdout_end, "days": a.holdout_days, "wd": hwd,
                   "before": pd.Timestamp(a.start, tz="UTC") - pd.Timedelta(days=EMBARGO_DAYS)}
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
    (out / "measurement.json").write_text(json.dumps({"runs": runs, "families": results}, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
