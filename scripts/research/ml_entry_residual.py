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
    keep = np.isfinite(t[[f"y_{s}_{a}" for s in ("long", "short") for a in ARMS]].to_numpy()).all(axis=1)
    return t[keep].reset_index(drop=True)


def fit_arm(train: pd.DataFrame, arm: str, sample: int | None = None) -> dict:
    import lightgbm as lgb
    if sample:
        train = train.sample(min(len(train), sample), random_state=0)
    out = {}
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**E.LGB_PARAMS)
        m.fit(train[E.FEATURES], train[f"y_{side}_{arm}"])
        out[side] = m
    return out


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


def replay(tab: pd.DataFrame, tau: float, frozen: dict | None = None, start: str = START, end: str = END,
           step_days: int = STEP_DAYS, fit=None) -> dict:
    fit = fit or fit_arm
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    rows, alls = [], {a: [] for a in ARMS + ("frozen",)}
    for k in range(int((ts1 - ts0).days // step_days)):
        a0 = ts0 + pd.Timedelta(days=k * step_days)
        a1 = a0 + pd.Timedelta(days=step_days)
        win = tab[(tab.ts >= a0) & (tab.ts < a1)].reset_index(drop=True)
        if len(win) == 0:
            continue
        train = E.purge_train(tab[tab.ts < a0], a0)
        row = {"start": str(a0.date())}
        for arm in ARMS:
            m = fit(train, arm)
            # provenance: predict -- regressed target of each side (policy() thresholds at tau), not a probability
            taken = E.policy(win, m["long"].predict(win[E.FEATURES]), m["short"].predict(win[E.FEATURES]), tau)
            row[arm] = _stats(taken)
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
    p_res, p_pla = _paired(rows, "resid", "raw"), _paired(rows, "placebo", "raw")
    verdict = decide(p_res, p_pla, pooled)
    return {"verdict": verdict, "paired_resid_vs_raw": p_res, "paired_placebo_vs_raw": p_pla, "pooled": pooled,
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
    d = replay(tab, float(meta["tau"]), frozen=frozen)
    v = d["verdict"]
    verdict = {"PASS": "pass", "FAIL": "fail"}.get(v, "indeterminate")
    pr = d["paired_resid_vs_raw"]
    note = (f"RESID-TARGET: {v} | paired resid-raw mean {pr['mean']} over k={pr['k']} windows, ci95 {pr['ci95']} | "
            f"placebo-raw mean {d['paired_placebo_vs_raw']['mean']} | pooled n raw/resid/placebo "
            f"{d['pooled']['raw']['n']}/{d['pooled']['resid']['n']}/{d['pooled']['placebo']['n']}")
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": verdict,
           "population": (f"ml_decision_entry recipe refit at 13 monthly origins over {START}..{END} ({STEP_DAYS}-day windows), "
                          f"{tab.symbol.nunique()} symbols (BTCUSDT excluded), both-sides at served tau, canonical cost stack, outright trades"),
           "note": note, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "latest_bar": max(x["last_bar"] for x in rep.values())}, "n": d["pooled"]["resid"]["n"],
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

    def fit(t, arm):
        return fit_arm(t, arm, sample=15000)

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
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit:
        ap.error("run --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
