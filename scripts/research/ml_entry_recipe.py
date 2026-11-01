#!/usr/bin/env python3
"""ENTRY recipe + target harness (rows ML-FS-RECIPE / ML-FS-LABELS; units RQ-20261101-fs05-01 and RQ-20261101-fs06-01).

Everything except the lever under test is ``ml_decision_entry`` unchanged: labels, cost stack, policy, 8 dev folds, tau grid,
purge/embargo, 60-perp universe and the leave-one-fold-out tau of ``ml_entry_v2.lofo``. The harness replaces ONLY
``E.fit_predict`` (the model fit), so no other code path differs between arms. DEV FOLDS ONLY: the table is clipped to
``ts < HOLDOUT_START`` on load and a sealed date aborts the run.

fs05-01 (recipe)   arms R0 baseline | R1 colsample 0.5, min_child 2000, lambda 50 | R2 R1 + leaves 15, lr 0.02, 450 trees |
                   R3 baseline params + fold-internal shadow-feature selection
                   sets S0 20 baseline columns | S1 S0 + 9 pure-noise columns (NOISE CONTROL) | S2 S0 + families F1..F5
                   (S3 = S0 + families admitted by fs01-01 = the empty set, so S3 == S0 and is not run again)
fs06-01 (target)   targets T0 raw net R | T1 minus same-timestamp cross-sectional mean | T2 same-timestamp rank in [-1, 1] |
                   T3 clipped to [-3, 3] | T4 first-passage 3-class classifier (score = sum P(class) x class mean net R)
                   sets S0 and S1; recipe fixed at R0. Scoring is ALWAYS raw net R.
Seeds 7, 11, 13 for every cell.

Interpretation fixed BEFORE any run (the registered text of fs05-01 reads "max over sets of the across-seed range of LOFO(S0)"):
``spread`` = the across-seed range (max - min) of that arm's S0 pooled LOFO mean; the max-over-{S0,S1,S2} range is reported
beside it as a sensitivity and never gates.

    python3 scripts/research/ml_entry_recipe.py run     --unit recipe|labels --table T --out O [--n-jobs 4]
    python3 scripts/research/ml_entry_recipe.py combine --unit recipe|labels --out O
    python3 scripts/research/ml_entry_recipe.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as E
import ml_entry_v2 as V

SEEDS = (7, 11, 13)
N_NOISE = 9
MIN_XS = 10                  # T1/T2 train only on timestamps with at least this many symbols
MIN_FOLD_N = 1000
SHADOW_FIT_FRAC, SHADOW_EMBARGO_DAYS, SHADOW_VAL_ROWS, SHADOW_REPEATS = 0.80, 7, 40000, 2

BASE = dict(E.LGB_PARAMS)
RECIPES = {
    "R0": {},
    "R1": {"colsample_bytree": 0.5, "min_child_samples": 2000, "reg_lambda": 50.0},
    "R2": {"colsample_bytree": 0.5, "min_child_samples": 2000, "reg_lambda": 50.0, "num_leaves": 15,
           "learning_rate": 0.02, "n_estimators": 450},
    "R3": {},                # baseline parameters; selection happens before the fit
}
TARGETS = ("T0", "T1", "T2", "T3", "T4")
NOISE_COLS = [f"nz{k}" for k in range(N_NOISE)]
FSETS = {"S0": list(E.FEATURES), "S1": list(E.FEATURES) + NOISE_COLS, "S2": V.features_for("G")}
UNITS = {
    "recipe": {"id": "RQ-20261101-fs05-01", "recipes": ["R0", "R1", "R2", "R3"], "targets": ["T0"], "sets": ["S0", "S1", "S2"]},
    "labels": {"id": "RQ-20261101-fs06-01", "recipes": ["R0"], "targets": list(TARGETS), "sets": ["S0", "S1"]},
}


# ----------------------------------------------------------------------------------------------- table
def load_table(path: Path) -> pd.DataFrame:
    tab = pd.read_pickle(path)
    tab = tab[tab.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC")].reset_index(drop=True)   # sealed rows never enter the harness
    assert tab.ts.max() < pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    tab[V.ALL_FAM_COLS] = tab[V.ALL_FAM_COLS].astype(float)
    return tab


def with_noise(tab: pd.DataFrame, seed: int) -> pd.DataFrame:
    """9 columns of N(0,1) that cannot carry information: deterministic per seed, independent of every row attribute."""
    rng = np.random.default_rng(10_000 + seed)
    noise = rng.standard_normal((len(tab), N_NOISE))
    return tab.assign(**{c: noise[:, k] for k, c in enumerate(NOISE_COLS)})


# ----------------------------------------------------------------------------------------------- targets
def xs_count(df: pd.DataFrame) -> pd.Series:
    return df.groupby("ts")["ts"].transform("size")


def xs_demean(df: pd.DataFrame, col: str) -> pd.Series:
    """net R minus the mean of the same column over the rows at the SAME decision timestamp (only same-ts values enter)."""
    return df[col] - df.groupby("ts")[col].transform("mean")


def xs_rank(df: pd.DataFrame, col: str) -> pd.Series:
    """Same-timestamp rank of ``col`` mapped to (-1, 1): 2 * (rank - 0.5) / n - 1, ties averaged."""
    r = df.groupby("ts")[col].rank(method="average")
    return 2.0 * (r - 0.5) / xs_count(df) - 1.0


def regression_target(train: pd.DataFrame, side: str, target: str) -> tuple[pd.Series, pd.Series]:
    col = f"net_{side}"
    keep = pd.Series(True, index=train.index)
    if target == "T0":
        y = train[col]
    elif target == "T1":
        y, keep = xs_demean(train, col), xs_count(train) >= MIN_XS
    elif target == "T2":
        y, keep = xs_rank(train, col), xs_count(train) >= MIN_XS
    elif target == "T3":
        y = train[col].clip(-3.0, 3.0)
    else:
        raise ValueError(target)
    return y, keep


def class_scores(proba: np.ndarray, classes: np.ndarray, class_mean: dict[int, float]) -> np.ndarray:
    """T4 score = sum over classes of P(class) x mean net R of that class (class means from the TRAIN rows only)."""
    return proba @ np.array([class_mean[int(c)] for c in classes])


# ----------------------------------------------------------------------------------------------- shadow selection (R3)
def shadow_select(train: pd.DataFrame, feats: list[str], params: dict, seed: int) -> dict:
    """Fold-internal Boruta-style filter. Inside ONE training fold: fit on the first 80 percent by time, score permutation
    importance (MSE increase, summed over the long and short models) on the last 20 percent after a 7-day embargo, with 9
    injected N(0,1) shadow columns; keep a real column only if its importance exceeds the maximum shadow importance."""
    import lightgbm as lgb
    t = train.sort_values("ts")
    cut = t.ts.iloc[int(len(t) * SHADOW_FIT_FRAC)]
    fit, val = t[t.ts < cut], t[t.ts >= cut + pd.Timedelta(days=SHADOW_EMBARGO_DAYS)]
    if len(val) > SHADOW_VAL_ROWS:
        val = val.sample(SHADOW_VAL_ROWS, random_state=seed)
    rng = np.random.default_rng(20_000 + seed + len(train))
    sh = [f"sh{k}" for k in range(N_NOISE)]
    fit = fit.assign(**{c: rng.standard_normal(len(fit)) for c in sh})
    val = val.assign(**{c: rng.standard_normal(len(val)) for c in sh})
    cols = list(feats) + sh
    imp = np.zeros(len(cols))
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**params).fit(fit[cols], fit[f"net_{side}"])
        y = val[f"net_{side}"].to_numpy()
        base = float(np.mean((m.predict(val[cols]) - y) ** 2))
        for j, c in enumerate(cols):
            d = 0.0
            for r in range(SHADOW_REPEATS):
                x = val[cols].copy()
                x[c] = rng.permutation(x[c].to_numpy())
                d += float(np.mean((m.predict(x) - y) ** 2)) - base
            imp[j] += d / SHADOW_REPEATS
    thr = float(imp[len(feats):].max())
    kept = [c for j, c in enumerate(feats) if imp[j] > thr]
    return {"kept": kept, "threshold": thr, "n_fit": len(fit), "n_val": len(val),
            "kept_noise_candidates": [c for c in kept if c in NOISE_COLS]}


# ----------------------------------------------------------------------------------------------- the fit hook
def make_fit(recipe: str, target: str, seed: int, log: list):
    import lightgbm as lgb
    params = {**BASE, **RECIPES[recipe], "random_state": seed}

    def fit_predict(train, test, features=None, n_jobs=None):
        feats = list(features)
        p = {**params, "n_jobs": n_jobs or params["n_jobs"]}
        entry = {"n_train": len(train)}
        if recipe == "R3":
            sel = shadow_select(train, feats, p, seed)
            entry.update(n_kept=len(sel["kept"]), n_features=len(feats), kept=sel["kept"],
                         kept_noise_candidates=sel["kept_noise_candidates"], threshold=sel["threshold"])
            feats = sel["kept"]
        log.append(entry)
        out = []
        for side in ("long", "short"):
            if not feats:                                   # nothing survived the filter: constant (train mean) prediction
                out.append(np.full(len(test), float(train[f"net_{side}"].mean())))
                continue
            if target == "T4":
                cls = train[f"reason_{side}"].astype(int)
                mean = train.groupby(cls)[f"net_{side}"].mean().to_dict()
                m = lgb.LGBMClassifier(**{**p, "objective": "multiclass"}).fit(train[feats], cls)
                out.append(class_scores(m.predict_proba(test[feats]), m.classes_, mean))
            else:
                y, keep = regression_target(train, side, target)
                m = lgb.LGBMRegressor(**p).fit(train.loc[keep, feats], y[keep])
                out.append(m.predict(test[feats]))
        return out[0], out[1]
    return fit_predict


def run_cell(tab: pd.DataFrame, recipe: str, target: str, fset: str, seed: int, out: Path, n_jobs: int) -> dict:
    key = f"{recipe}_{target}_{fset}_s{seed}"
    path = out / "runs" / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    t0, log = time.time(), []
    feats = FSETS[fset]
    work = with_noise(tab, seed) if fset == "S1" else tab
    orig = E.fit_predict
    E.fit_predict = make_fit(recipe, target, seed, log)
    try:
        wf = E.walk_forward(work, feats, n_jobs=n_jobs)
    finally:
        E.fit_predict = orig
    res = {"key": key, "recipe": recipe, "target": target, "set": fset, "seed": seed, "n_features": len(feats),
           "walk_forward": wf, "lofo": V.lofo(wf["folds"]), "fold_fit_log": log, "elapsed_s": round(time.time() - t0)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=1, default=str))
    print(key, json.dumps({k: res["lofo"][k] for k in ("n", "mean_net_r")}), f"{res['elapsed_s']}s", flush=True)
    return res


def grid(unit: str) -> list[tuple]:
    u = UNITS[unit]
    return [(r, t, s, seed) for seed in SEEDS for r in u["recipes"] for t in u["targets"] for s in u["sets"]]


# ----------------------------------------------------------------------------------------------- combine (registered rules)
def _load(out: Path, unit: str) -> dict:
    return {k: json.loads((out / "runs" / f"{'_'.join(map(str, k[:3]))}_s{k[3]}.json").read_text())
            for k in grid(unit) if (out / "runs" / f"{'_'.join(map(str, k[:3]))}_s{k[3]}.json").exists()}


def _agg(runs: dict, recipe: str, target: str, fset: str) -> dict | None:
    rs = [runs[(recipe, target, fset, s)] for s in SEEDS if (recipe, target, fset, s) in runs]
    if len(rs) < len(SEEDS):
        return None
    means = [r["lofo"]["mean_net_r"] for r in rs]
    folds = [[f["mean_net_r"] for f in r["lofo"]["per_fold"]] for r in rs]
    fold_mean = [float(np.mean([f[i] for f in folds if f[i] is not None])) for i in range(len(folds[0]))]
    fold_n_min = min(f["n"] for r in rs for f in r["lofo"]["per_fold"])
    return {"seed_means": means, "mean": float(np.mean(means)), "range": float(max(means) - min(means)),
            "per_fold_mean_over_seeds": fold_mean, "fold_sd": float(np.std(fold_mean)), "min_fold_n": int(fold_n_min),
            "n_pooled": [r["lofo"]["n"] for r in rs]}


def combine_recipe(out: Path) -> dict:
    runs = _load(out, "recipe")
    res = {"unit": UNITS["recipe"]["id"], "read_state": "read", "sealed_windows_read": 0, "arms": {}, "S3": "empty set (fs01-01 admitted nothing): S3 == S0, not run again",
           "spread_definition": "across-seed range of the arm's S0 pooled LOFO mean (gating); max over S0/S1/S2 reported as sensitivity"}
    immune = []
    for r in UNITS["recipe"]["recipes"]:
        a = {s: _agg(runs, r, "T0", s) for s in ("S0", "S1", "S2")}
        if any(v is None for v in a.values()):
            res["arms"][r] = {"verdict": "indeterminate", "why": "fewer than 3 seeds for some set"}
            continue
        spread = a["S0"]["range"]
        sens = max(a[s]["range"] for s in a)
        noise_delta = a["S1"]["mean"] - a["S0"]["mean"]
        small = min(v["min_fold_n"] for v in a.values()) < MIN_FOLD_N
        arm = {"S0": a["S0"]["mean"], "S1": a["S1"]["mean"], "S2": a["S2"]["mean"], "seed_means": {s: a[s]["seed_means"] for s in a},
               "spread": spread, "spread_sensitivity_max_over_sets": sens, "noise_delta_S1_minus_S0": noise_delta,
               "noise_immune": (noise_delta >= -spread) and not small, "min_fold_n": min(v["min_fold_n"] for v in a.values())}
        if small:
            arm["verdict"] = "indeterminate"
            arm["why"] = f"a fold has fewer than {MIN_FOLD_N} scored decisions"
        else:
            adm = {}
            for s in ("S2",):   # S3 == S0
                d = a[s]["mean"] - a["S0"]["mean"]
                better = sum(1 for x, y in zip(a[s]["per_fold_mean_over_seeds"], a["S0"]["per_fold_mean_over_seeds"]) if x > y)
                adm[s] = {"delta_vs_S0": d, "folds_better": better, "admits": bool(arm["noise_immune"] and d >= 2 * spread and better >= 6)}
            arm["family_admission"] = adm
            arm["verdict"] = "noise_immune" if arm["noise_immune"] else "not_noise_immune"
            if arm["noise_immune"]:
                immune.append(r)
        arm["per_fold_S0_mean_over_seeds"] = a["S0"]["per_fold_mean_over_seeds"]
        arm["per_fold_S1_mean_over_seeds"] = a["S1"]["per_fold_mean_over_seeds"]
        arm["per_fold_S2_mean_over_seeds"] = a["S2"]["per_fold_mean_over_seeds"]
        arm["folds"] = [f["fold"] for f in runs[(r, "T0", "S0", SEEDS[0])]["lofo"]["per_fold"]]
        if r == "R3":
            arm["shadow_keep_counts_per_fold"] = {f"{s}_s{sd}": [x.get("n_kept") for x in runs[("R3", "T0", s, sd)]["fold_fit_log"]]
                                                  for s in ("S0", "S1", "S2") for sd in SEEDS}
            arm["shadow_kept_noise_candidates_S1"] = {f"s{sd}": [len(x.get("kept_noise_candidates", [])) for x in runs[("R3", "T0", "S1", sd)]["fold_fit_log"]]
                                                      for sd in SEEDS}
        res["arms"][r] = arm
    res["fixed_recipe"] = max(immune, key=lambda r: res["arms"][r]["S0"]) if immune else None
    res["result"] = (f"fixed recipe = {res['fixed_recipe']}" if immune else
                     "no recipe fix found; the next lever is the target (RQ-20261101-fs06-01)") if all(
        res["arms"][r]["verdict"] != "indeterminate" for r in res["arms"]) or immune else "INDETERMINATE"
    res["admitted_by_arm"] = {r: [s for s, v in a.get("family_admission", {}).items() if v["admits"]] for r, a in res["arms"].items()}
    return res


def combine_labels(out: Path) -> dict:
    runs = _load(out, "labels")
    res = {"unit": UNITS["labels"]["id"], "read_state": "read", "sealed_windows_read": 0, "arms": {}}
    t0 = {s: _agg(runs, "R0", "T0", s) for s in ("S0", "S1")}
    if any(v is None for v in t0.values()):
        res.update(result="INDETERMINATE", why="T0 lacks 3 seeds, spread cannot be computed")
        return res
    spread = t0["S0"]["range"]
    res["T0"] = {"S0": t0["S0"]["mean"], "S1": t0["S1"]["mean"], "spread": spread, "seed_means_S0": t0["S0"]["seed_means"],
                 "per_fold_S0": t0["S0"]["per_fold_mean_over_seeds"], "fold_sd": t0["S0"]["fold_sd"]}
    admitted = []
    for t in TARGETS[1:]:
        a = {s: _agg(runs, "R0", t, s) for s in ("S0", "S1")}
        if any(v is None for v in a.values()):
            res["arms"][t] = {"verdict": "indeterminate", "why": "fewer than 3 seeds"}
            continue
        d = a["S0"]["mean"] - t0["S0"]["mean"]
        better = sum(1 for x, y in zip(a["S0"]["per_fold_mean_over_seeds"], t0["S0"]["per_fold_mean_over_seeds"]) if x > y)
        nd = a["S1"]["mean"] - a["S0"]["mean"]
        small = min(v["min_fold_n"] for v in a.values()) < MIN_FOLD_N
        ok = (d >= 2 * spread) and better >= 6 and nd >= -spread and not small
        res["arms"][t] = {"S0": a["S0"]["mean"], "S1": a["S1"]["mean"], "seed_means_S0": a["S0"]["seed_means"], "delta_vs_T0": d,
                          "two_x_spread": 2 * spread, "folds_better_than_T0": better, "noise_delta_S1_minus_S0": nd,
                          "fold_sd": a["S0"]["fold_sd"], "min_fold_n": a["S0"]["min_fold_n"],
                          "per_fold_S0": a["S0"]["per_fold_mean_over_seeds"], "own_seed_range": a["S0"]["range"],
                          "verdict": "indeterminate" if small else ("admit" if ok else "reject")}
        if ok:
            admitted.append(t)
    res["admitted"] = admitted
    res["result"] = (f"admitted: {admitted}" if admitted else
                     "target change does not help the dev folds; the pooled bar-level recipe has no measured edge above the seed noise")
    return res


def write_result(unit: str, res: dict, out: Path) -> None:
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str))
    L = [f"# {res['unit']} dev-fold result", "", f"read_state: {res['read_state']}; sealed windows read: {res['sealed_windows_read']}", "",
         f"**Result:** {res['result']}", ""]
    if unit == "recipe":
        L += ["| arm | S0 | S1 (noise) | S2 (F1..F5) | spread | S1-S0 | immune | S2-S0 | folds S2>S0 |", "|---|---|---|---|---|---|---|---|---|"]
        for r, a in res["arms"].items():
            if "S0" not in a:
                L.append(f"| {r} | {a['verdict']} |||||||")
                continue
            ad = a.get("family_admission", {}).get("S2", {})
            L.append(f"| {r} | {a['S0']:+.4f} | {a['S1']:+.4f} | {a['S2']:+.4f} | {a['spread']:.4f} | {a['noise_delta_S1_minus_S0']:+.4f} | "
                     f"{a['noise_immune']} | {ad.get('delta_vs_S0', float('nan')):+.4f} | {ad.get('folds_better', '-')} |")
        L += ["", "Per-fold means over seeds (S0 / S1 / S2):", ""]
        for r, a in res["arms"].items():
            if "S0" in a:
                L.append(f"- {r} folds {a['folds']}")
                for s in ("S0", "S1", "S2"):
                    L.append(f"  - {s}: " + ", ".join(f"{x:+.3f}" for x in a[f"per_fold_{s}_mean_over_seeds"]))
    else:
        t = res.get("T0", {})
        L += [f"T0 S0 {t.get('S0')}, S1 {t.get('S1')}, spread {t.get('spread')}", "",
              "| target | S0 | delta vs T0 | 2x spread | folds better | S1-S0 | fold sd | verdict |", "|---|---|---|---|---|---|---|---|"]
        for k, a in res["arms"].items():
            if "S0" in a:
                L.append(f"| {k} | {a['S0']:+.4f} | {a['delta_vs_T0']:+.4f} | {a['two_x_spread']:.4f} | {a['folds_better_than_T0']} | "
                         f"{a['noise_delta_S1_minus_S0']:+.4f} | {a['fold_sd']:.3f} | {a['verdict']} |")
    (out / "RESULT.md").write_text("\n".join(L) + "\n")


# ----------------------------------------------------------------------------------------------- self-test + CLI
def _self_test() -> None:
    import tempfile
    rng = np.random.default_rng(0)
    # 1. noise columns: N(0,1), deterministic per seed, different across seeds, uncorrelated with a row attribute
    base = pd.DataFrame({"x": rng.standard_normal(5000)})
    a, b, c = with_noise(base, 7), with_noise(base, 7), with_noise(base, 11)
    assert all(a[k].equals(b[k]) for k in NOISE_COLS) and not a["nz0"].equals(c["nz0"])
    assert abs(a[NOISE_COLS].to_numpy().mean()) < 0.03 and abs(a[NOISE_COLS].to_numpy().std() - 1) < 0.03
    assert all(abs(np.corrcoef(a["x"], a[k])[0, 1]) < 0.06 for k in NOISE_COLS) and len(NOISE_COLS) == 9 == N_NOISE
    # 2. no sealed date: a table with a sealed row is clipped on load, and the harness aborts on a sealed max
    with tempfile.TemporaryDirectory() as d:
        ts = pd.to_datetime(["2025-09-30 20:00", "2025-10-01 00:00", "2026-10-05 00:00"], utc=True)
        t = pd.DataFrame({"ts": ts, "symbol": "X"})
        for col in V.ALL_FAM_COLS:
            t[col] = 0.0
        t.to_pickle(Path(d) / "t.pkl")
        lt = load_table(Path(d) / "t.pkl")
        assert len(lt) == 1 and lt.ts.max() < pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    # 3. cross-sectional targets use ONLY same-timestamp values (truncation invariance)
    ts = np.repeat(pd.date_range("2024-01-01", periods=30, freq="4h", tz="UTC"), 12)
    full = pd.DataFrame({"ts": ts, "net_long": rng.standard_normal(len(ts))})
    cut = full[full.ts <= full.ts.unique()[14]]
    for fn in (xs_demean, xs_rank):
        assert np.allclose(fn(full, "net_long").loc[cut.index], fn(cut, "net_long"), atol=0, rtol=0)
    assert abs(xs_demean(full, "net_long").groupby(full.ts).mean()).max() < 1e-12
    r = xs_rank(full, "net_long")
    assert r.min() > -1 and r.max() < 1 and abs(r.groupby(full.ts).mean()).max() < 1e-12
    # mutating a FUTURE timestamp's values must not move an earlier timestamp's target
    mut = full.copy()
    mut.loc[mut.ts == mut.ts.unique()[20], "net_long"] += 5.0
    assert np.array_equal(xs_demean(mut, "net_long")[full.ts < mut.ts.unique()[20]], xs_demean(full, "net_long")[full.ts < mut.ts.unique()[20]])
    # 4. clipping and the T4 score mapping
    y, keep = regression_target(pd.DataFrame({"ts": ts[:3], "net_long": [-9.0, 0.5, 9.0]}), "long", "T3")
    assert list(y) == [-3.0, 0.5, 3.0] and keep.all()
    assert abs(class_scores(np.array([[0.2, 0.5, 0.3]]), np.array([0, 1, 2]), {0: 0.1, 1: -1.0, 2: 2.0})[0] - (0.02 - 0.5 + 0.6)) < 1e-12
    # 5. shadow selection keeps a real signal column and rejects pure noise
    n = 12000
    d = pd.DataFrame({"ts": pd.date_range("2022-01-01", periods=n, freq="1h", tz="UTC"), "sig": rng.standard_normal(n), "junk": rng.standard_normal(n)})
    d["net_long"] = 0.6 * d.sig + rng.standard_normal(n) * 0.5
    d["net_short"] = -0.6 * d.sig + rng.standard_normal(n) * 0.5
    p = {**BASE, "n_jobs": 2, "min_child_samples": 50, "n_estimators": 60, "random_state": 7}
    sel = shadow_select(d, ["sig", "junk"], p, 7)
    assert "sig" in sel["kept"] and "junk" not in sel["kept"], sel
    # 6. recipes differ from the baseline only in the registered keys
    assert set(RECIPES["R1"]) == {"colsample_bytree", "min_child_samples", "reg_lambda"} and RECIPES["R2"]["n_estimators"] == 450
    # 7. grid sizes
    assert len(grid("recipe")) == 36 and len(grid("labels")) == 30
    print("ml_entry_recipe self-test OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["run", "combine"])
    ap.add_argument("--unit", choices=list(UNITS))
    ap.add_argument("--table", default="")
    ap.add_argument("--out", default="/tmp/ml_entry_recipe")
    ap.add_argument("--n-jobs", type=int, default=4)
    ap.add_argument("--only-seed", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "run":
        tab = load_table(Path(a.table))
        for (r, t, s, seed) in grid(a.unit):
            if a.only_seed and seed != a.only_seed:
                continue
            run_cell(tab, r, t, s, seed, out, a.n_jobs)
    elif a.cmd == "combine":
        res = combine_recipe(out) if a.unit == "recipe" else combine_labels(out)
        write_result(a.unit, res, out)
        print(res["result"])
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
