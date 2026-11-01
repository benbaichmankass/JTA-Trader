#!/usr/bin/env python3
"""ENTRY lever harness, round 1 (rows ML-LEVER-HARNESS / ML-LEVER-PLAN; units RQ-20261101-b601-01 brackets, -b602-01 selectivity,
-b604-01 calibration, -a508-01 traded slice). DEV FOLDS ONLY: the table is clipped to ts < HOLDOUT_START on load.

Every arm is ONE factor against the frozen v1 base (20 baseline features, baseline LightGBM params, entry tau 0.10, the c692-01
walk-forward folds, purge and embargo) and is scored with the same one-position-per-symbol policy and cost stack. The arm rule is
the common rule of the units (registered before any run):

  WIN iff every fold keeps >= 1000 decisions, the seed-mean beats the base by >= 2 x max(0.0034, base seed range), it is better in
  >= 6 of 8 folds, and its delta over the base is positive in >= 3 of 4 calendar years.  A win is a CANDIDATE for the one combined
  held-out read, nothing more.

    python3 scripts/research/ml_entry_levers.py build-table --streams S --out O
    python3 scripts/research/ml_entry_levers.py run --unit b601-01|b602-01|b604-01|a508-01 --table T --out O [--n-jobs 4]
    python3 scripts/research/ml_entry_levers.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as E
import ml_entry_recipe as R

SEEDS = R.SEEDS
TAU = 0.10
SPREAD_FLOOR = 0.0034          # MEASURED 2026-11-01: v1 dev seed range, pooled 60, fixed tau
MIN_FOLD_N = 1000
ABSTAIN = -9.0
YEARS = (2022, 2023, 2024, 2025)
TRADED = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
MAJORS, ALTS = ["BTCUSDT", "ETHUSDT"], ["XRPUSDT", "ADAUSDT", "SOLUSDT"]


# ----------------------------------------------------------------------------------------------- bracket relabel
def label_cell(df: pd.DataFrame, sl: float, tp: float) -> pd.DataFrame:
    """``E.label_symbol`` with the bracket as arguments (the module defaults are bound at import, so the constants cannot be patched).
    Identical to ``E.label_symbol`` at (SL_ATR, TP_ATR); proved in the self-test."""
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(E.ATR_N, min_periods=E.ATR_N).mean().to_numpy()
    ts = df["ts"]
    close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
    N, H = len(df), E.HORIZON_H
    cand = np.where((close_hour % E.DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
    cand = cand[cand + H < N]
    t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
    cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * 3_600_000_000_000]
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
    entry, a = Ob[:, 0], atr[cand]
    risk = sl * a
    out = {"i": cand}
    t_entry_s = t_ns[cand + 1] / 1e9
    for name, side in (("long", 1), ("short", -1)):
        px, j, reason = E.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=sl, tp_atr=tp)
        gross = side * (px - entry) / risk
        fee, slip, fund = E._cost_r(entry, px, risk, t_entry_s, t_ns[cand + j] / 1e9 + 3600.0)
        out[f"gross_{name}"], out[f"net_{name}"] = gross, gross - fee - slip - fund
        out[f"cost_{name}"], out[f"reason_{name}"], out[f"bars_{name}"] = fee + slip + fund, reason, j
    return pd.DataFrame(out)


LABEL_COLS = [f"{k}_{s}" for k in ("gross", "net", "cost", "reason", "bars") for s in ("long", "short")]


def relabel_table(tab: pd.DataFrame, cache: Path, sl: float, tp: float) -> pd.DataFrame:
    """The dev table with the label columns recomputed for bracket (sl, tp); rows, features and order unchanged."""
    parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        lab = label_cell(pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True), sl, tp)
        lab["symbol"] = sym
        parts.append(lab)
    lab = pd.concat(parts, ignore_index=True)
    key = pd.MultiIndex.from_frame(lab[["symbol", "i"]])
    cols = lab.set_index(key)[LABEL_COLS]
    got = cols.reindex(pd.MultiIndex.from_frame(tab[["symbol", "i"]]))
    if got[["net_long", "net_short"]].isna().any().any():
        raise RuntimeError("relabel left rows without labels")
    out = tab.copy()
    for c in LABEL_COLS:
        out[c] = got[c].to_numpy()
    return out


# ----------------------------------------------------------------------------------------------- arms and the rule
def base_members(tab: pd.DataFrame, out: Path, n_jobs: int, seeds=SEEDS) -> dict:
    return {sd: R.ens_member(tab, "R0", "S0", sd, out, n_jobs) for sd in seeds}


def fold_frames(tab: pd.DataFrame, member: dict) -> list:
    return [tab.loc[member[f"pos{k}"]] for k in range(8)]


def run_arm(frames: list, member: dict, tau: float = TAU, tweak=None) -> pd.DataFrame:
    """Trades of one arm for one seed: the shared policy on the (optionally tweaked) predictions. ``tweak(k, test, pl, ps)`` returns the
    predictions to use; abstention is a prediction of ABSTAIN, so the position-blocking mechanics stay those of the policy."""
    rows = []
    for k, test in enumerate(frames):
        pl, ps = member[f"pl{k}"].copy(), member[f"ps{k}"].copy()
        if tweak is not None:
            pl, ps, tk_tau = tweak(k, test, pl, ps)
        else:
            tk_tau = tau
        tk = E.policy(test, pl, ps, tk_tau)
        tk["fold"] = k
        rows.append(tk)
    t = pd.concat(rows, ignore_index=True)
    t["year"] = pd.to_datetime(t.ts, utc=True).dt.year
    return t


def stats(trades: pd.DataFrame, mask=None) -> dict:
    t = trades if mask is None else trades[mask(trades)]
    pf = [(int((t.fold == k).sum()), float(t[t.fold == k].net_r.mean()) if (t.fold == k).any() else None) for k in range(8)]
    py = {int(y): (int((t.year == y).sum()), float(t[t.year == y].net_r.mean()) if (t.year == y).any() else None) for y in YEARS}
    return {"n": len(t), "mean": float(t.net_r.mean()) if len(t) else None, "gross": float(t.gross_r.mean()) if len(t) else None,
            "cost": float(t.cost_r.mean()) if len(t) else None, "per_fold": pf, "per_year": py,
            "min_fold_n": min(n for n, _ in pf)}


def judge(base: list, arm: list) -> dict:
    """The common rule over per-seed stats lists (same seed order)."""
    bm, am = np.mean([s["mean"] for s in base]), np.mean([s["mean"] for s in arm])
    rng = float(max(s["mean"] for s in base) - min(s["mean"] for s in base))
    thr = 2 * max(SPREAD_FLOOR, rng)
    bf = [np.mean([s["per_fold"][k][1] for s in base]) for k in range(8)]
    af = [np.mean([s["per_fold"][k][1] if s["per_fold"][k][1] is not None else np.nan for s in arm]) for k in range(8)]
    better = int(sum(1 for x, y in zip(af, bf) if x > y))
    yd = {y: np.mean([s["per_year"][y][1] for s in arm]) - np.mean([s["per_year"][y][1] for s in base]) for y in YEARS}
    yrs = int(sum(1 for v in yd.values() if v > 0))
    grad = min(s["min_fold_n"] for s in arm) >= MIN_FOLD_N
    ok = grad and (am - bm) >= thr and better >= 6 and yrs >= 3
    return {"arm_mean": float(am), "base_mean": float(bm), "delta": float(am - bm), "threshold": float(thr), "base_seed_range": rng,
            "arm_seed_means": [s["mean"] for s in arm], "n": [s["n"] for s in arm], "min_fold_n": min(s["min_fold_n"] for s in arm),
            "folds_better": better, "years_delta_positive": yrs, "year_delta": {str(k): float(v) for k, v in yd.items()},
            "verdict": "win" if ok else ("indeterminate" if not grad else "no_win")}


# ----------------------------------------------------------------------------------------------- b601: bracket geometry
BRACKET_CELLS = [(2.0, 3.0), (2.0, 4.0), (2.0, 6.0), (1.5, 4.0), (3.0, 4.0)]      # base first; SL sweep at TP 4, TP sweep at SL 2


def bracket_unit(tab, out, n_jobs, cache: Path) -> dict:
    mem = base_members(tab, out, n_jobs)
    res = {"unit": "RQ-20261101-b601-01", "sealed_windows_read": 0, "cells": {}}
    per = {}
    for sl, tp in BRACKET_CELLS:
        t = relabel_table(tab, cache, sl, tp)
        per[(sl, tp)] = [stats(run_arm(fold_frames(t, mem[sd]), mem[sd])) for sd in SEEDS]
        print("cell", sl, tp, np.mean([s["mean"] for s in per[(sl, tp)]]), flush=True)
    base = per[BRACKET_CELLS[0]]
    for cell in BRACKET_CELLS:
        res["cells"][f"{cell[0]}/{cell[1]}"] = judge(base, per[cell]) if cell != BRACKET_CELLS[0] else {
            "arm_mean": float(np.mean([s["mean"] for s in base])), "n": [s["n"] for s in base], "verdict": "base"}
    # smoothness: a winning cell's one-step neighbours (SL and TP directions) must be within 0.01 of it
    m = {c: res["cells"][f"{c[0]}/{c[1]}"]["arm_mean"] for c in BRACKET_CELLS}
    for c in BRACKET_CELLS[1:]:
        r = res["cells"][f"{c[0]}/{c[1]}"]
        nb = [k for k in BRACKET_CELLS if k != c and (k[0] == c[0] or k[1] == c[1])]
        r["neighbour_gaps"] = {f"{k[0]}/{k[1]}": float(m[c] - m[k]) for k in nb}
        r["smooth"] = bool(all(abs(g) <= 0.01 for g in r["neighbour_gaps"].values()))
        if r["verdict"] == "win" and not r["smooth"]:
            r["verdict"] = "island_rejected"
    wins = [k for k, v in res["cells"].items() if v["verdict"] == "win"]
    res["result"] = f"candidate: {max(wins, key=lambda k: res['cells'][k]['arm_mean'])}" if wins else "no bracket cell clears the rule on the dev folds"
    return res


# ----------------------------------------------------------------------------------------------- b602: selectivity
def _cap(q, m):
    def tw(k, test, pl, ps):
        other = np.concatenate([np.maximum(m[f"pl{j}"], m[f"ps{j}"]) for j in range(8) if j != k])     # OTHER folds' out-of-sample scores, no labels
        c = np.quantile(other, q)
        sc = np.maximum(pl, ps)
        pl[sc > c] = ABSTAIN
        ps[sc > c] = ABSTAIN
        return pl, ps, TAU
    return tw


def _regime(col, j, cuts):
    def tw(k, test, pl, ps):
        lo, hi = cuts[col]
        v = test[col].to_numpy()
        inside = (v <= lo) if j == 0 else ((v > lo) & (v <= hi)) if j == 1 else (v > hi)
        pl[inside] = ABSTAIN
        ps[inside] = ABSTAIN
        return pl, ps, TAU
    return tw


def _side(drop):
    def tw(k, test, pl, ps):
        (pl if drop == "long" else ps)[:] = ABSTAIN
        return pl, ps, TAU
    return tw


def make_tweak(spec, m, cuts):
    kind, arg = spec
    return {"cap": lambda: _cap(arg, m), "btc": lambda: _regime("btc_ret24", arg, cuts), "vol": lambda: _regime("vol24", arg, cuts),
            "side": lambda: _side(arg)}[kind]()


def selectivity_unit(tab, out, n_jobs) -> dict:
    mem = base_members(tab, out, n_jobs)
    frames = {sd: fold_frames(tab, mem[sd]) for sd in SEEDS}
    dev_btc, dev_vol = tab["btc_ret24"], tab["vol24"]
    cuts = {"btc_ret24": dev_btc.quantile([1 / 3, 2 / 3]).to_numpy(), "vol24": dev_vol.quantile([1 / 3, 2 / 3]).to_numpy()}

    arms = {"base": None, "A_cap_q0.80": ("cap", 0.80), "A_cap_q0.90": ("cap", 0.90), "B_tau0.05": ("tau", 0.05), "B_tau0.15": ("tau", 0.15),
            **{f"C_btc_ret24_abstain_t{j}": ("btc", j) for j in range(3)}, **{f"C_vol24_abstain_t{j}": ("vol", j) for j in range(3)},
            "D_drop_long": ("side", "long"), "D_drop_short": ("side", "short")}
    per = {}
    for name, spec in arms.items():
        per[name] = []
        for sd in SEEDS:
            m, fr = mem[sd], frames[sd]
            if spec is None:
                tr = run_arm(fr, m)
            elif spec[0] == "tau":
                tr = run_arm(fr, m, tau=spec[1])
            else:
                tr = run_arm(fr, m, tweak=make_tweak(spec, m, cuts))
            per[name].append(stats(tr))
        print("arm", name, np.mean([s["mean"] for s in per[name]]), flush=True)
    res = {"unit": "RQ-20261101-b602-01", "sealed_windows_read": 0, "arms": {}}
    for name in arms:
        if name == "base":
            res["arms"][name] = {"arm_mean": float(np.mean([s["mean"] for s in per[name]])), "n": [s["n"] for s in per[name]], "verdict": "base"}
            continue
        r = judge(per["base"], per[name])
        if name.startswith("D_"):          # a side may be dropped only if that side is negative in >= 3 of 4 years (dev flips predict held-out failure)
            drop = name.split("_")[-1]
            sd_years = []
            for sd in SEEDS:
                tr = run_arm(frames[sd], mem[sd])
                sd_years.append(stats(tr, lambda t, d=drop: t.side == d)["per_year"])
            neg = sum(1 for y in YEARS if np.mean([py[y][1] for py in sd_years]) < 0)
            r["dropped_side_negative_years"] = int(neg)
            if r["verdict"] == "win" and neg < 3:
                r["verdict"] = "side_unstable_rejected"
        res["arms"][name] = r
    wins = [k for k, v in res["arms"].items() if v["verdict"] == "win"]
    res["result"] = f"candidates: {wins}" if wins else "no selectivity arm clears the rule on the dev folds"
    # tau curve and score-quintile reading, reported beside the arms
    curve = {}
    for tau in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
        curve[str(tau)] = float(np.mean([stats(run_arm(frames[sd], mem[sd], tau=tau))["mean"] for sd in SEEDS]))
    res["tau_curve_seed_mean"] = curve
    return res


# ----------------------------------------------------------------------------------------------- b604: calibration
def decile_table(score: np.ndarray, net: np.ndarray) -> dict:
    q = pd.qcut(pd.Series(score).rank(method="first"), 10, labels=False)
    d = pd.DataFrame({"s": score, "n": net, "q": q}).groupby("q").agg(pred=("s", "mean"), real=("n", "mean"), rows=("s", "size"))
    sp = float(d.reset_index()[["q", "real"]].corr(method="spearman").iloc[0, 1])
    slope = float(np.polyfit(d.pred.to_numpy(), d.real.to_numpy(), 1)[0])
    return {"deciles": d.round(4).reset_index().to_dict("records"), "spearman_decile_vs_realised": sp, "slope_realised_on_predicted": slope,
            "calibrated": bool(sp >= 0.8 and 0.7 <= slope <= 1.3)}


def row_scores(frames: list, member: dict):
    sc, net, fold = [], [], []
    for k, test in enumerate(frames):
        pl, ps = member[f"pl{k}"], member[f"ps{k}"]
        long_ = pl >= ps
        sc.append(np.where(long_, pl, ps))
        net.append(np.where(long_, test.net_long.to_numpy(), test.net_short.to_numpy()))
        fold.append(np.full(len(test), k))
    return np.concatenate(sc), np.concatenate(net), np.concatenate(fold)


def remap_isotonic(s_tr, n_tr):
    from sklearn.isotonic import IsotonicRegression
    m = IsotonicRegression(out_of_bounds="clip").fit(s_tr, n_tr)
    return m.predict


def remap_binned(s_tr, n_tr, bins=20, shrink=200.0):
    edges = np.quantile(s_tr, np.linspace(0, 1, bins + 1)[1:-1])
    b = np.digitize(s_tr, edges)
    g = float(np.mean(n_tr))
    val = np.array([(n_tr[b == j].sum() + shrink * g) / ((b == j).sum() + shrink) for j in range(bins)])
    return lambda s: val[np.digitize(s, edges)]


def calibration_unit(tab, out, n_jobs) -> dict:
    mem = base_members(tab, out, n_jobs)
    frames = {sd: fold_frames(tab, mem[sd]) for sd in SEEDS}
    res = {"unit": "RQ-20261101-b604-01", "sealed_windows_read": 0, "arms": {}}
    cal = {}
    per = {"base": [], "R1_isotonic": [], "R2_binned": []}
    for sd in SEEDS:
        s, n, f = row_scores(frames[sd], mem[sd])
        cal[sd] = decile_table(s, n)
        share = [float((np.maximum(mem[sd][f"pl{k}"], mem[sd][f"ps{k}"]) > TAU).mean()) for k in range(8)]
        per["base"].append(stats(run_arm(frames[sd], mem[sd])))
        for name, fit in (("R1_isotonic", remap_isotonic), ("R2_binned", remap_binned)):
            def tw(k, test, pl, ps, fit=fit, sd=sd, s=s, n=n, f=f, share=share):
                fn = fit(s[f != k], n[f != k])                      # fitted on the OTHER folds' out-of-sample scores and outcomes
                long_ = pl >= ps
                sc = np.where(long_, pl, ps)
                rs = fn(sc)
                thr = np.quantile(rs, 1 - share[k]) if share[k] > 0 else np.inf
                npl = np.where(long_ & (rs > thr), rs, ABSTAIN)
                nps = np.where(~long_ & (rs > thr), rs, ABSTAIN)
                return npl, nps, thr - 1e-12 if np.isfinite(thr) else 1e9
            per[name].append(stats(run_arm(frames[sd], mem[sd], tweak=tw)))
        print("seed", sd, [round(per[k][-1]["mean"], 4) for k in per], flush=True)
    res["base_calibration_by_seed"] = {str(k): v for k, v in cal.items()}
    for name in ("R1_isotonic", "R2_binned"):
        res["arms"][name] = judge(per["base"], per[name])
    res["base"] = {"mean": float(np.mean([s["mean"] for s in per["base"]])), "n": [s["n"] for s in per["base"]]}
    res["result"] = ("base score is CALIBRATED" if all(v["calibrated"] for v in cal.values()) else
                     "base score is NOT calibrated on the dev folds (decile Spearman < 0.8 or slope outside [0.7, 1.3])")
    return res


# ----------------------------------------------------------------------------------------------- a508: the traded slice
def traded_unit(tab, out, n_jobs) -> dict:
    seeds = (E.SEED, *SEEDS)
    mem = base_members(tab, out, n_jobs, seeds)
    tr = {sd: run_arm(fold_frames(tab, mem[sd]), mem[sd]) for sd in seeds}
    res = {"unit": "RQ-20261101-a508-01", "sealed_windows_read": 0, "seeds": list(seeds), "A0": {}, "flags": {}}
    pooled = pd.concat(tr.values())
    for sym in TRADED:
        per = [stats(t, lambda x, s=sym: x.symbol == s) for t in tr.values()]
        g = pooled[pooled.symbol == sym].net_r
        mean = float(np.mean([p["mean"] for p in per]))
        se = float(g.std() / np.sqrt(len(g) / len(seeds)))               # per-decision SD over the seed-mean n
        t_stat = mean / se if se else None
        yrs = {y: float(np.mean([p["per_year"][y][1] for p in per])) for y in YEARS}
        yn = {y: float(np.mean([p["per_year"][y][0] for p in per])) for y in YEARS}
        pos_years = sum(1 for y in YEARS if yrs[y] >= 0 and yn[y] >= 100)
        flag = "HARM" if (mean < 0 and t_stat is not None and t_stat <= -2) else "SUPPORTED" if (mean >= 0 and pos_years >= 3) else "UNDETERMINED"
        res["A0"][sym] = {"mean": mean, "se": se, "t": t_stat, "n_per_seed": float(np.mean([p["n"] for p in per])), "year": yrs, "year_n": yn}
        res["flags"][sym] = flag
    traded = [stats(t, lambda x: x.symbol.isin(TRADED)) for t in tr.values()]
    rest = [stats(t, lambda x: ~x.symbol.isin(TRADED)) for t in tr.values()]
    res["traded5"] = {"mean": float(np.mean([s["mean"] for s in traded])), "seed_range": float(max(s["mean"] for s in traded) - min(s["mean"] for s in traded)),
                      "n_per_seed": float(np.mean([s["n"] for s in traded])), "gross": float(np.mean([s["gross"] for s in traded])),
                      "cost": float(np.mean([s["cost"] for s in traded]))}
    res["other55"] = {"mean": float(np.mean([s["mean"] for s in rest])), "gross": float(np.mean([s["gross"] for s in rest])),
                      "cost": float(np.mean([s["cost"] for s in rest])), "n_per_seed": float(np.mean([s["n"] for s in rest]))}
    # A1: the traded trades re-priced at the other symbols' mean cost per R (only cost changes)
    oc = res["other55"]["cost"]
    a1 = [float((t[t.symbol.isin(TRADED)].gross_r - oc).mean()) for t in tr.values()]
    res["A1_cost_neutral_traded5_mean"] = float(np.mean(a1))
    # A3: majors vs the other three
    m = [stats(t, lambda x: x.symbol.isin(MAJORS))["mean"] for t in tr.values()]
    a = [stats(t, lambda x: x.symbol.isin(ALTS))["mean"] for t in tr.values()]
    res["A3"] = {"BTC_ETH": float(np.mean(m)), "ADA_SOL_XRP": float(np.mean(a)), "gap": float(np.mean(m) - np.mean(a))}
    rng = res["traded5"]["seed_range"]
    cost_driven = res["A1_cost_neutral_traded5_mean"] >= 0
    coin_driven = (not cost_driven) and (res["A3"]["gap"] <= -2 * rng)
    res["causes"] = {"cost_driven": bool(cost_driven), "coin_driven": bool(coin_driven), "cadence_driven": "untested (A2 runs with RQ-20261101-b603-01)"}
    res["result"] = f"flags {res['flags']}; causes coin={coin_driven} cost={cost_driven}"
    return res


# ----------------------------------------------------------------------------------------------- self-test + CLI
def _self_test() -> None:
    rng = np.random.default_rng(3)
    n = 800
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * (1 + rng.uniform(0, 0.003, n)),
                       "low": np.minimum(o, c) * (1 - rng.uniform(0, 0.003, n)), "close": c, "volume": 1.0})
    a, b = E.label_symbol(df), label_cell(df, E.SL_ATR, E.TP_ATR)
    for col in LABEL_COLS + ["i"]:
        assert np.array_equal(a[col].to_numpy(), b[col].to_numpy()), col           # the parameterised relabel IS the production label at (2, 3)
    w = label_cell(df, 2.0, 6.0)
    assert not np.array_equal(w["net_long"].to_numpy(), b["net_long"].to_numpy())  # and a different bracket changes the outcome
    # judge: a clear win, a thin win, an unstable one
    def mk(mean, nfold=2000, folds=None, yrs=None):
        return {"mean": mean, "min_fold_n": nfold, "n": 10000, "per_fold": [(nfold, (folds or [mean] * 8)[k]) for k in range(8)],
                "per_year": {y: (500, (yrs or {}).get(y, mean)) for y in YEARS}}

    base = [mk(0.005), mk(0.006), mk(0.007)]
    assert judge(base, [mk(0.03)] * 3)["verdict"] == "win"
    assert judge(base, [mk(0.009)] * 3)["verdict"] == "no_win"                       # delta 0.003 < 2 x 0.0034
    assert judge(base, [mk(0.03, nfold=500)] * 3)["verdict"] == "indeterminate"      # a fold under 1000 decisions
    assert judge(base, [mk(0.03, folds=[0.03, 0.03, 0.03, 0.03, 0.03, 0.0, 0.0, 0.0])] * 3)["verdict"] == "no_win"   # only 5 of 8 folds
    assert judge(base, [mk(0.03, yrs={2022: 0.0, 2023: 0.0, 2024: 0.0})] * 3)["verdict"] == "no_win"                 # delta positive in 1 of 4 years
    # calibration statistics: a perfectly monotone relation is calibrated, a top-band loser is not
    s = np.linspace(0, 1, 10000)
    assert decile_table(s, s + rng.normal(0, 0.01, len(s)))["calibrated"]
    bad = np.where(s > 0.8, -s, s)
    assert not decile_table(s, bad)["calibrated"]
    # binned remap is fitted from the training scores only and shrinks toward the global mean
    fn = remap_binned(np.linspace(0, 1, 4000), np.r_[np.zeros(2000), np.ones(2000)])
    assert fn(np.array([0.0]))[0] < fn(np.array([1.0]))[0]
    # the table is clipped to the dev window by the shared loader (no sealed row can enter)
    assert R.E.HOLDOUT_START == "2025-10-01"
    print("ml_entry_levers self-test OK")


def build_base_table(streams: Path, out: Path) -> Path:
    """Baseline-feature table from the 12-column klines streams only (no families), same cache conversion as ml_entry_v2.build_table."""
    import ml_entry_families as F
    import ml_entry_v2 as V
    cache = out / "klines"
    cache.mkdir(parents=True, exist_ok=True)
    syms = []
    for s in E.universe():
        p = streams / "klines12" / f"{s}.pkl"
        if not p.exists():
            continue
        k = pd.read_pickle(p)
        k["ts"] = F._ts(k["open_time"])
        k = k.sort_values("ts").drop_duplicates("ts")
        for c in ("open", "high", "low", "close", "volume"):
            k[c] = k[c].astype(float)
        k = k[~((k["volume"] == 0) & (k["high"] == k["low"])) & (k.ts >= pd.Timestamp(E.START, tz="UTC"))]
        k[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(cache / f"{s}.pkl")
        syms.append(s)
    tab = E.build_table(cache, syms)
    tab["ts"] = tab["ts"].astype("datetime64[ns, UTC]")
    tab.to_pickle(out / "table.pkl")
    del V
    return out / "table.pkl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["run", "build-table"])
    ap.add_argument("--streams", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--table", default="")
    ap.add_argument("--out", default="/tmp/ml_entry_levers")
    ap.add_argument("--n-jobs", type=int, default=4)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "build-table":
        print(build_base_table(Path(a.streams), out))
        return 0
    if a.cmd != "run":
        ap.print_help()
        return 0
    tpath = Path(a.table)
    tab = pd.read_pickle(tpath)
    tab = tab[tab.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC")].reset_index(drop=True)          # dev only: a sealed row never enters
    assert tab.ts.max() < pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    u = a.unit.split("-")[-2] if a.unit.startswith("RQ-") else a.unit.split("-")[0]
    fn = {"b601": lambda: bracket_unit(tab, out, a.n_jobs, tpath.parent / "klines"), "b602": lambda: selectivity_unit(tab, out, a.n_jobs),
          "b604": lambda: calibration_unit(tab, out, a.n_jobs), "a508": lambda: traded_unit(tab, out, a.n_jobs)}[u]
    res = fn()
    (out / f"{u}_result.json").write_text(json.dumps(res, indent=1, default=str))
    print(res["result"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
