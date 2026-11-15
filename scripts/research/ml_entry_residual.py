#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-4654-01.yaml (runner unit); lane FRONTIER-RESEARCH; work item FRONTIER-Q-RESID-ENTRY
"""Market-residual TARGET for the served crypto ENTRY recipe (frontier scan 2026-11-11 K1; FRONTIER-Q-RESID-ENTRY).

Question: the served ENTRY replay's result flips with the market's direction (RQ-20261108-98e3-23 SIDE-DRIVER). Does training the
SAME recipe (features, LightGBM params, purge, tau) on a target with the common BTC move removed beat training it on the raw target,
when BOTH are graded on the trades they would actually take, at the actual net R (the canonical cost stack, outright, unhedged)?

Three arms, each refit at the same 13 monthly origins over the frozen v1's clean held-out year (the RQ-20261108-98e3-26 design),
each scoring the 28 days after its origin, both-sides policy at the served tau:

  RAW      targets net_long / net_short (the served recipe)                                       -- the baseline
  RESID    targets net_long - m / net_short + m, where m = beta_i,t x BTC fwd return, in the asset's R units
  PLACEBO  as RESID but the BTC fwd return is PERMUTED across timestamps (same magnitudes, wrong times)

  m = beta x (BTC close[t+H] / BTC close[t] - 1) x entry / (SL_ATR x ATR)     (the asset's own R scale)
  beta = 720-bar rolling OLS slope of the asset's hourly log return on BTC's, through bar t (point-in-time), clipped to [-1, 3]

The fwd BTC return is in the LABEL only (as every label is forward); E.purge_train's embargo covers it. BTCUSDT is excluded from all
three arms (its residual target is degenerate: beta 1). The frozen v1 is reported on the same rows for context, not graded.

Rule (registered before the run, research/queue/RQ-20261112-4654-01.yaml):
  paired windows = windows where RAW and RESID each took >= 30 decisions; d_w = RESID mean - RAW mean (net R/decision)
  PASS          iff >= 10 paired windows, mean d >= +0.06, 95% t-CI low > 0, RESID pooled n >= 300, and the PLACEBO does not pass
                (PLACEBO paired mean vs RAW < +0.06 or its CI low <= 0) and RESID pooled mean > PLACEBO pooled mean
  FAIL          iff >= 10 paired windows and (mean d <= 0 or PLACEBO paired mean >= RESID paired mean)
  INDETERMINATE otherwise (below the n floors, or 0 < mean d with the CI or the +0.06 bar not met)

    python3 scripts/research/ml_entry_residual.py run --cache DIR --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..]
    python3 scripts/research/ml_entry_residual.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402

START, END, STEP_DAYS = "2025-10-01", "2026-09-30", 28
BETA_WIN, BETA_LO, BETA_HI = 720, -1.0, 3.0
WIN_N, MIN_WINDOWS, POOL_N, DELTA = 30, 10, 300, 0.06
PLACEBO_SEED = 20261112
ARMS = ("raw", "resid", "placebo")
#: FRONTIER-Q-XSEC-RANK-ENTRY (not part of RQ-20261112-4654-01): the ranking objective in regression form -- each side's net R
#: minus its cross-sectional mean over the symbols at the same decision timestamp, so only the relative order at a time is learned.
EXTRA_ARMS = ("xsdemean", "ens", "ridge", "conf")
# ens / ridge (FRONTIER-Q-ENS-RIDGE-ENTRY): the RAW target with a different learner -- ridge alone, or the equal-weight
# average of the LightGBM and ridge predictions (a heterogeneous ensemble). They change the learner, not the target.
LEARNER_ARMS = {"ens": "raw", "ridge": "raw"}
RIDGE_ALPHA = 10.0
# conf (FRONTIER-Q-CONFORMAL-ENTRY): uncertainty-normalised selection at MATCHED COVERAGE. Inside each refit's training
# rows (time order): PROPER (first 70%) fits mu_p; CAL-A (next 15%) fits sigma = E|y - mu_p|; CAL-B (last 15%) picks the
# score threshold s* so E.policy on (mu_p / sigma) takes as many decisions there as E.policy on mu_p at tau. A 25-hour gap
# (label horizon + 1) separates the slices. On the test window the score is mu_full / sigma (mu_full = the RAW fit on
# all training rows, so the arm differs from RAW only in WHICH decisions it takes). Point-in-time: nothing reads the test window.
CONF_SPLIT = (0.70, 0.85)
CONF_SIGMA_FLOOR_Q = 0.05
LEARNER_ARMS["conf"] = "raw"
TAU_ARMS = ("conf",)


# ----------------------------------------------------------------------------------------------- target
def market_component(tab: pd.DataFrame, cache: Path, permute: bool = False, seed: int = PLACEBO_SEED) -> np.ndarray:
    """m per row in the asset's R units. Point-in-time beta; forward BTC return (label side only)."""
    btc = pd.read_pickle(cache / "BTCUSDT.pkl").reset_index(drop=True)
    bts = pd.to_datetime(btc["ts"], utc=True)
    bc = pd.Series(btc["close"].astype(float).to_numpy(), index=bts)
    blr = np.log(bc).diff()
    fwd = bc.shift(-E.HORIZON_H) / bc - 1.0
    fwd_map = fwd.copy()
    if permute:
        vals = fwd.dropna()
        rng = np.random.default_rng(seed)
        fwd_map = pd.Series(np.nan, index=fwd.index)
        fwd_map.loc[vals.index] = rng.permutation(vals.to_numpy())
    beta_parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        s = pd.Series(df["close"].astype(float).to_numpy(), index=pd.to_datetime(df["ts"], utc=True))
        alr = np.log(s).diff()
        b = blr.reindex(alr.index)
        cov = (alr * b).rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean() - \
            alr.rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean() * b.rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean()
        var = b.rolling(BETA_WIN, min_periods=BETA_WIN // 2).var(ddof=0)
        beta = (cov / var.replace(0, np.nan)).clip(BETA_LO, BETA_HI)
        beta_parts.append(pd.Series(beta.reindex(g["ts"]).to_numpy(), index=g.index))
    beta = pd.concat(beta_parts).reindex(tab.index).to_numpy()
    r_btc = fwd_map.reindex(tab["ts"]).to_numpy()
    per_r = tab["entry"].to_numpy(float) / (E.SL_ATR * tab["atr"].to_numpy(float))
    return beta * r_btc * per_r


def add_targets(tab: pd.DataFrame, cache: Path) -> pd.DataFrame:
    t = tab[tab.symbol != "BTCUSDT"].copy()
    for arm, perm in (("resid", False), ("placebo", True)):
        m = market_component(t, cache, permute=perm)
        t[f"y_long_{arm}"] = t["net_long"].to_numpy() - m
        t[f"y_short_{arm}"] = t["net_short"].to_numpy() + m
    t["y_long_raw"], t["y_short_raw"] = t["net_long"], t["net_short"]
    for side in ("long", "short"):           # xsdemean: market-neutral by construction (relative order at each timestamp)
        t[f"y_{side}_xsdemean"] = t[f"net_{side}"] - t.groupby("ts")[f"net_{side}"].transform("mean")
    keep = np.isfinite(t[[f"y_{s}_{a}" for s in ("long", "short") for a in ARMS]].to_numpy()).all(axis=1)
    return t[keep].reset_index(drop=True)


def fit_arm(train: pd.DataFrame, arm: str, sample: int | None = None, tau: float | None = None) -> dict:
    import lightgbm as lgb
    if sample:
        train = train.sample(min(len(train), sample), random_state=0)
    if arm == "conf":
        return fit_conf(train, tau if tau is not None else 0.0)
    target = LEARNER_ARMS.get(arm, arm)
    out = {}
    for side in ("long", "short"):
        y = train[f"y_{side}_{target}"]
        ridge = None
        if arm in LEARNER_ARMS:
            from sklearn.impute import SimpleImputer
            from sklearn.linear_model import Ridge
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            ridge = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=RIDGE_ALPHA))
            ridge.fit(train[E.FEATURES], y)
        if arm == "ridge":
            out[side] = ridge
            continue
        m = lgb.LGBMRegressor(**E.LGB_PARAMS)
        m.fit(train[E.FEATURES], y)
        out[side] = _Blend(m, ridge) if arm == "ens" else m
    return out


def _slices(train: pd.DataFrame) -> tuple:
    t = train.sort_values("ts")
    ts = t["ts"].sort_values().unique()
    gap = pd.Timedelta(hours=E.HORIZON_H + 1)
    c1, c2 = (pd.Timestamp(ts[int(len(ts) * q)]) for q in CONF_SPLIT)
    return (t[t.ts < c1 - gap], t[(t.ts >= c1) & (t.ts < c2 - gap)], t[t.ts >= c2])


def _match_threshold(cal: pd.DataFrame, z: dict, n_target: int, tau: float) -> float:
    """The score threshold s* at which E.policy on z takes n_target decisions on ``cal`` (bisection; count falls as s rises)."""
    lo = float(min(z["long"].min(), z["short"].min())) - 1.0
    hi = float(max(z["long"].max(), z["short"].max())) + 1.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        n = len(E.policy(cal, z["long"] - mid + tau, z["short"] - mid + tau, tau))
        lo, hi = (mid, hi) if n > n_target else (lo, mid)
    return 0.5 * (lo + hi)


def fit_conf(train: pd.DataFrame, tau: float) -> dict:
    import lightgbm as lgb
    proper, cal_a, cal_b = _slices(train)
    full = fit_arm(train, "raw")
    out, z_b, mu_b = {}, {}, {}
    sig = {}
    for side in ("long", "short"):
        y = f"y_{side}_raw"
        mp = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(proper[E.FEATURES], proper[y])
        # provenance: predict -- mu_p, the PROPER-slice regressed net R, read on CAL-A to form the absolute residual sigma learns
        res_a = (cal_a[y] - mp.predict(cal_a[E.FEATURES])).abs()
        ms = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(cal_a[E.FEATURES], res_a)
        # provenance: predict -- sigma, the regressed absolute residual of mu_p (an uncertainty scale in R), floored
        floor = max(float(np.quantile(ms.predict(cal_a[E.FEATURES]), CONF_SIGMA_FLOOR_Q)), 1e-6)
        sig[side] = (ms, floor)
        # provenance: predict -- mu_p and sigma on CAL-B, to match coverage there
        mu_b[side] = mp.predict(cal_b[E.FEATURES])
        z_b[side] = mu_b[side] / np.maximum(ms.predict(cal_b[E.FEATURES]), floor)
    n_raw = len(E.policy(cal_b, mu_b["long"], mu_b["short"], tau))
    s_star = _match_threshold(cal_b, z_b, n_raw, tau)
    for side in ("long", "short"):
        out[side] = _Normalised(full[side], *sig[side], s_star, tau)
    out["_conf"] = {"s_star": s_star, "n_cal_b_raw": n_raw, "n_rows": [len(proper), len(cal_a), len(cal_b)]}
    return out


class _Normalised:
    """mu_full / sigma shifted so E.policy's ``> tau`` test means ``mu / sigma > s*``."""

    def __init__(self, mu, sigma, floor, s_star, tau):
        self.mu, self.sigma, self.floor, self.s_star, self.tau = mu, sigma, floor, s_star, tau

    def predict(self, x):
        # provenance: predict -- the RAW booster's regressed net R over the sigma model's absolute-residual scale, shifted
        return self.mu.predict(x) / np.maximum(self.sigma.predict(x), self.floor) - self.s_star + self.tau


class _Blend:
    """Equal-weight average of two fitted regressors' predictions (both in net-R units of the same target)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def predict(self, x):
        # provenance: predict -- mean of the LightGBM and ridge regressed net R, not a probability
        return 0.5 * (self.a.predict(x) + self.b.predict(x))


# ----------------------------------------------------------------------------------------------- statistics
def _stats(t: pd.DataFrame | None) -> dict:
    if t is None or len(t) == 0:
        return {"n": 0, "mean_net_r": None}
    se = float(t.net_r.std(ddof=1) / math.sqrt(len(t))) if len(t) > 1 else None
    by_side = {s: {"n": int((t.side == s).sum()), "mean_net_r": float(t.net_r[t.side == s].mean()) if (t.side == s).any() else None}
               for s in ("long", "short")}
    return {"n": len(t), "mean_net_r": float(t.net_r.mean()), "se": se, "by_side": by_side}


def _paired(rows: list[dict], a: str, b: str) -> dict:
    d = [r[a]["mean_net_r"] - r[b]["mean_net_r"] for r in rows
         if r[a]["n"] >= WIN_N and r[b]["n"] >= WIN_N]
    k = len(d)
    if k < 2:
        return {"k": k, "mean": float(np.mean(d)) if d else None, "sd": None, "ci95": None}
    from scipy import stats as st
    mu, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    h = float(st.t.ppf(0.975, k - 1) * sd / math.sqrt(k))
    return {"k": k, "mean": mu, "sd": sd, "ci95": [mu - h, mu + h]}


def decide(p_res: dict, p_pla: dict, pooled: dict) -> str:
    if p_res["k"] < MIN_WINDOWS or p_res["mean"] is None:
        return "INDETERMINATE"
    pla_mean = p_pla["mean"] if p_pla["mean"] is not None else -math.inf
    if p_res["mean"] <= 0 or pla_mean >= p_res["mean"]:
        return "FAIL"
    placebo_passes = (p_pla["mean"] is not None and p_pla["ci95"] is not None
                      and p_pla["mean"] >= DELTA and p_pla["ci95"][0] > 0)
    if (p_res["mean"] >= DELTA and p_res["ci95"] is not None and p_res["ci95"][0] > 0
            and pooled["resid"]["n"] >= POOL_N and not placebo_passes
            and pooled["resid"]["mean_net_r"] > (pooled["placebo"]["mean_net_r"] if pooled["placebo"]["mean_net_r"] is not None else -math.inf)):
        return "PASS"
    return "INDETERMINATE"


def decide_vs_raw(p: dict, pooled_arm: dict) -> str:
    """The RESID bar without the placebo clause, for an EXTRA_ARMS unit (its own unit registers this rule before its run):
    PASS iff >= MIN_WINDOWS paired windows, mean >= DELTA, 95% CI low > 0 and pooled n >= POOL_N; FAIL iff >= MIN_WINDOWS and
    mean <= 0; INDETERMINATE otherwise."""
    if p.get("k", 0) < MIN_WINDOWS or p.get("mean") is None:
        return "INDETERMINATE"
    if p["mean"] <= 0:
        return "FAIL"
    if p["mean"] >= DELTA and p.get("ci95") and p["ci95"][0] > 0 and (pooled_arm.get("n") or 0) >= POOL_N:
        return "PASS"
    return "INDETERMINATE"


def replay(tab: pd.DataFrame, tau: float, frozen: dict | None = None, start: str = START, end: str = END,
           step_days: int = STEP_DAYS, fit=None, arms: tuple = ARMS) -> dict:
    fit = fit or fit_arm
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    rows, alls = [], {a: [] for a in tuple(arms) + ("frozen",)}
    for k in range(int((ts1 - ts0).days // step_days)):
        a0 = ts0 + pd.Timedelta(days=k * step_days)
        a1 = a0 + pd.Timedelta(days=step_days)
        win = tab[(tab.ts >= a0) & (tab.ts < a1)].reset_index(drop=True)
        if len(win) == 0:
            continue
        train = E.purge_train(tab[tab.ts < a0], a0)
        row = {"start": str(a0.date())}
        for arm in arms:
            m = fit(train, arm, tau=tau) if arm in TAU_ARMS else fit(train, arm)
            # provenance: predict -- regressed target of each side (policy() thresholds at tau), not a probability
            taken = E.policy(win, m["long"].predict(win[E.FEATURES]), m["short"].predict(win[E.FEATURES]), tau)
            row[arm] = _stats(taken)
            if "_conf" in m:                 # conf: the matched threshold and slice sizes behind this window's decisions
                row[f"{arm}_info"] = m["_conf"]
            alls[arm].append(taken)
        if frozen is not None:
            # provenance: predict -- the frozen v1 booster's regressed net R of each side (policy() thresholds at tau), not a probability
            fro = E.policy(win, frozen["long"].predict(win[E.FEATURES]), frozen["short"].predict(win[E.FEATURES]), tau)
            row["frozen"] = _stats(fro)
            alls["frozen"].append(fro)
        win_btc = win.drop_duplicates("ts")
        row["btc_ret24_mean"] = float(win_btc["btc_ret24"].mean()) if "btc_ret24" in win_btc else None
        rows.append(row)
    pooled = {a: _stats(pd.concat(v)) if v else _stats(None) for a, v in alls.items()}
    p_res = _paired(rows, "resid", "raw") if "resid" in arms else {"k": 0, "mean": None, "sd": None, "ci95": None}
    p_pla = _paired(rows, "placebo", "raw") if "placebo" in arms else {"k": 0, "mean": None, "sd": None, "ci95": None}
    extra = {a: _paired(rows, a, "raw") for a in arms if a not in ARMS}
    if "resid" in arms:
        verdict = decide(p_res, p_pla, pooled)
    else:                                    # an EXTRA_ARMS unit: the same paired bar against RAW, no placebo arm
        a0 = next(iter(extra), None)
        verdict = decide_vs_raw(extra[a0], pooled.get(a0, {})) if a0 else "INDETERMINATE"
    return {"verdict": verdict, "paired_resid_vs_raw": p_res, "paired_placebo_vs_raw": p_pla,
            "paired_extra_vs_raw": extra, "arms": list(arms), "pooled": pooled,
            "windows": rows, "tau": tau, "window": {"start": start, "end": end, "step_days": step_days},
            "thresholds": {"win_n": WIN_N, "min_windows": MIN_WINDOWS, "pool_n": POOL_N, "delta": DELTA,
                           "beta_win": BETA_WIN, "beta_clip": [BETA_LO, BETA_HI], "placebo_seed": PLACEBO_SEED}}


# ----------------------------------------------------------------------------------------------- entry points
def run(a) -> int:
    import ml_entry_retrain as RT
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    syms = E.universe()
    rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = add_targets(E.build_table(cache, syms), cache)
    meta, frozen = E._frozen_models(REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json")
    assert str(meta["train_end_exclusive"]) < START, "the frozen model must not have seen the replay year"
    arms = tuple(x for x in a.arms.split(",") if x)
    bad = [x for x in arms if x not in ARMS + EXTRA_ARMS]
    if bad or "raw" not in arms:
        raise SystemExit(f"--arms must include raw and only {ARMS + EXTRA_ARMS}; got {arms}")
    d = replay(tab, float(meta["tau"]), frozen=frozen, arms=arms)
    v = d["verdict"]
    verdict = {"PASS": "pass", "FAIL": "fail"}.get(v, "indeterminate")
    pr = d["paired_resid_vs_raw"]
    if "resid" in arms:
        note = (f"RESID-TARGET: {v} | paired resid-raw mean {pr['mean']} over k={pr['k']} windows, ci95 {pr['ci95']} | "
                f"placebo-raw mean {d['paired_placebo_vs_raw']['mean']} | pooled n raw/resid/placebo "
                f"{d['pooled']['raw']['n']}/{d['pooled']['resid']['n']}/{d['pooled']['placebo']['n']}")
    else:
        note = f"EXTRA-ARM: {v} | " + " | ".join(f"paired {k}-raw mean {p['mean']} k={p['k']} ci95 {p['ci95']} n={d['pooled'][k]['n']}"
                                                  for k, p in d["paired_extra_vs_raw"].items())
    head_arm = "resid" if "resid" in arms else next(x for x in arms if x != "raw")
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": verdict,
           "population": (f"ml_decision_entry recipe refit at 13 monthly origins over {START}..{END} ({STEP_DAYS}-day windows), "
                          f"{tab.symbol.nunique()} symbols (BTCUSDT excluded), both-sides at served tau, canonical cost stack, outright trades"),
           "note": note, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "latest_bar": max(x["last_bar"] for x in rep.values())}, "n": d["pooled"][head_arm]["n"],
           "produced_by": {"tool": "python3 scripts/research/ml_entry_residual.py run", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(note, flush=True)
    return 0


def self_test() -> int:
    import tempfile

    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    assert "BTCUSDT" in syms, syms
    tab = add_targets(E.build_table(root, syms), root)
    assert "BTCUSDT" not in set(tab.symbol) and len(tab) > 0
    # residual and placebo differ from raw, and the placebo is a permutation of the same magnitudes
    assert not np.allclose(tab.y_long_resid, tab.y_long_raw) and not np.allclose(tab.y_long_placebo, tab.y_long_resid)
    m_res = (tab.y_long_raw - tab.y_long_resid).to_numpy()
    assert np.allclose(tab.y_short_resid - tab.y_short_raw, m_res)

    def fit(t, arm, **kw):
        return fit_arm(t, arm, sample=15000, **kw)

    start = (tab.ts.max() - pd.Timedelta(days=56)).strftime("%Y-%m-%d")
    end = (tab.ts.max() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit)
    assert d["verdict"] in ("PASS", "FAIL", "INDETERMINATE") and len(d["windows"]) >= 1
    # decide(): the branches
    pooled = {"resid": {"n": 400, "mean_net_r": 0.1}, "placebo": {"n": 400, "mean_net_r": 0.0}}
    good = {"k": 13, "mean": 0.08, "ci95": [0.02, 0.14]}
    weak_pla = {"k": 13, "mean": 0.01, "ci95": [-0.03, 0.05]}
    assert decide(good, weak_pla, pooled) == "PASS"
    assert decide({"k": 13, "mean": -0.01, "ci95": [-0.05, 0.03]}, weak_pla, pooled) == "FAIL"
    assert decide(good, {"k": 13, "mean": 0.09, "ci95": [0.03, 0.15]}, pooled) == "FAIL"
    assert decide({"k": 13, "mean": 0.04, "ci95": [-0.01, 0.09]}, weak_pla, pooled) == "INDETERMINATE"
    assert decide({"k": 8, "mean": 0.2, "ci95": [0.1, 0.3]}, weak_pla, pooled) == "INDETERMINATE"
    # xsdemean (FRONTIER-Q-XSEC-RANK-ENTRY): zero cross-sectional mean at every timestamp; an extra-arm replay uses decide_vs_raw
    g = tab.groupby("ts")["y_long_xsdemean"].mean().abs().max()
    assert g < 1e-9, g
    d2 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "xsdemean"))
    assert "xsdemean" in d2["paired_extra_vs_raw"] and d2["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    # ens / ridge (FRONTIER-Q-ENS-RIDGE-ENTRY): same raw target, different learner; the verdict is on the FIRST extra arm (ens)
    mr = fit_arm(tab, "raw", sample=15000)
    me = fit_arm(tab, "ens", sample=15000)
    mg = fit_arm(tab, "ridge", sample=15000)
    xx = tab[E.FEATURES].head(50)
    # provenance: predict -- regressed net R of the long side for the raw / ens / ridge fits (a self-test identity check)
    assert np.allclose(me["long"].predict(xx), 0.5 * (mr["long"].predict(xx) + mg["long"].predict(xx)))
    d3 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "ens", "ridge"))
    assert set(d3["paired_extra_vs_raw"]) == {"ens", "ridge"} and d3["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    # conf (FRONTIER-Q-CONFORMAL-ENTRY): slices are time-ordered and gapped, coverage on CAL-B is matched to RAW's
    pr, ca, cb = _slices(tab)
    gap = pd.Timedelta(hours=E.HORIZON_H + 1)
    assert pr.ts.max() < ca.ts.min() - gap + pd.Timedelta(hours=1) and ca.ts.max() < cb.ts.min() - gap + pd.Timedelta(hours=1)
    mc = fit_conf(tab, 0.0)
    info = mc["_conf"]
    assert info["n_cal_b_raw"] > 0 and np.isfinite(info["s_star"]), info
    d4 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "conf"))
    assert "conf" in d4["paired_extra_vs_raw"] and d4["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    assert decide_vs_raw({"k": 13, "mean": 0.08, "ci95": [0.02, 0.14]}, {"n": 400}) == "PASS"
    assert decide_vs_raw({"k": 13, "mean": -0.01, "ci95": [-0.05, 0.03]}, {"n": 400}) == "FAIL"
    assert decide_vs_raw({"k": 8, "mean": 0.2, "ci95": [0.1, 0.3]}, {"n": 400}) == "INDETERMINATE"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_residual_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-12")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    ap.add_argument("--arms", default=",".join(ARMS), help="comma list; default = the RQ-20261112-4654-01 arms (raw,resid,placebo). "
                    "xsdemean (FRONTIER-Q-XSEC-RANK-ENTRY), ens,ridge (FRONTIER-Q-ENS-RIDGE-ENTRY) and conf (FRONTIER-Q-CONFORMAL-ENTRY) are EXTRA arms for their own units; "
                    "the verdict is on the first extra arm listed")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit:
        ap.error("run --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
