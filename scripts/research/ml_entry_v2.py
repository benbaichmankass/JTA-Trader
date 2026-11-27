#!/usr/bin/env python3
"""ENTRY v2 harness (rows ML-FS-ENTRY-V2; units RQ-20261101-fs01-01 dev ablation and RQ-20261101-fs02-01 one forward read).

The recipe is ``ml_decision_entry`` unchanged (labels, cost stack, LightGBM parameters, tau grid, purge/embargo, 60-perp
universe). Only the FEATURES change: the 20 baseline columns plus whole families from ``ml_entry_families``.

Subcommands
  build-table      cache + family table  -> <out>/table.pkl   (reads the Binance Vision stream dirs of vision_streams.py)
  arm              one ablation arm on the DEV folds only (never reads a sealed window) -> <out>/arm_<X>.json
  combine          applies the registered admission rule over arm_*.json -> <out>/ablation.json
  forward          fs02-01: fit through the day before W1, claim ONE read in HOLDOUT-LOCK, score W1, benchmarks -> <out>/forward.json

Admission rule (registered in RQ-20261101-fs01-01 before any run): leave-one-fold-out tau; ADMIT a family iff pooled
delta vs arm A >= +0.010 R per decision AND delta > 0 in at least 6 of 8 folds AND the family is present on >= 40 percent
of dev decision rows.
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
import holdout_lock
import ml_decision_entry as E
import ml_entry_families as F

ARMS = {"A": [], "A2": [], "B": ["F1"], "C": ["F2"], "D": ["F3"], "E": ["F4"], "F": ["F5"], "G": ["F1", "F2", "F3", "F4", "F5"]}
ARMS["M"] = ["F8"]   # D3-POINT-IN-TIME-MACRO-BUILDER: cross-asset / macro-state family, evaluated by the ablation_macro run mode only
ARMS["T"] = ["F7"]   # TREND-ALIGNMENT-FEATURE step 5: trend-align directional family, evaluated by the ablation_trend run mode only
# COMPACT-DERIVS (plan docs/research/ml-entry-new-information-classes-2026-11-27.md, unit RQ-20261127-26ac-01). fs01-01
# read each family against the bare baseline while 9 pure-noise columns alone cost -0.0167 R/decision: the recipe pays a
# per-column cost that hides information. These arms keep ONE normalised column per concept (no raw level beside its
# z-score, no moving average beside its source) and are graded against a placebo of the SAME width (N4 / N8: seeded
# N(0,1) columns), so the column cost is priced out. Columns fixed before any run of this unit.
COMPACT = {
    "F2c": ["f2_prem_z168", "f2_fund_z21", "f2_prem8_minus_fund", "f2_prem_chg4"],          # basis / funding state
    "F5c": ["f5_semivar_ratio24", "f5_er24", "f5_dist_hi168_atr", "f5_dist_lo168_atr"],   # path shape
}
ARMS.update({"P2": ["F2c"], "P5": ["F5c"], "P25": ["F2c", "F5c"], "N4": [], "N8": []})
PLACEBO_WIDTH = {"N4": 4, "N8": 8}
PLACEBO_FOR = {"P2": "N4", "P5": "N4", "P25": "N8"}
PLACEBO_SEED = 20261127
COMPACT_DELTA, COMPACT_FOLDS, COMPACT_YEARS = 0.010, 6, 3
# one-sided Sidak family bar for k = 3 arms at alpha 0.05 on the K = 8 per-fold deltas (df 7): t_{1-0.016952, 7}
COMPACT_T_BAR = 2.6302
FAM_COLS = {k: [c for c in v if c != "f3_present"] if k == "F3" else v for k, v in F.FAMILIES.items()}
ALL_FAM_COLS = [c for v in F.FAMILIES.values() for c in v]
EXTRA_DEV_FOLDS = ["2025-10-01", "2026-01-01", "2026-04-01", "2026-07-01"]   # used ONLY by the forward unit (dev through W1 start)
W1 = ("2026-10-01", "2026-10-31")
ADMIT_DELTA, ADMIT_FOLDS, ADMIT_COVERAGE = 0.010, 6, 0.40
SEEDS = {"A2": 7}   # A2 = arm A with another LightGBM seed: the harness noise floor, measured, not assumed


# ----------------------------------------------------------------------------------------------- tables
def _load(d: Path, st: str, sym: str):
    p = d / st / f"{sym}.pkl"
    return pd.read_pickle(p) if p.exists() else None


def _cat(frames):
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None


def build_table(streams: Path, oct_dir: Path | None, out: Path, syms: list[str], macro_dir: Path | None = None) -> pd.DataFrame:
    cache = out / "klines"
    cache.mkdir(parents=True, exist_ok=True)
    fam, frames = [], {}
    for s in syms:
        k12 = _cat([_load(streams, "klines12", s), _load(oct_dir, "klines12d", s) if oct_dir else None])
        if k12 is None:
            continue
        prem = _cat([_load(streams, "premium", s), _load(oct_dir, "premiumd", s) if oct_dir else None])
        fund = _cat([_load(streams, "funding", s), _load(oct_dir, "funding", s) if oct_dir else None])
        met = _load(streams, "metrics", s)
        fr = F.symbol_frame(k12, prem, fund, met)
        # ENTRY cache frame (ts, o, h, l, c, v) from the same bars, START-clipped as ml_decision_entry.fetch does
        k = k12.copy()
        k["ts"] = F._ts(k["open_time"])
        k = k.sort_values("ts").drop_duplicates("ts")
        for c in ("open", "high", "low", "close", "volume"):
            k[c] = k[c].astype(float)
        # explicit delisting mask: a frozen bar (zero volume, flat) is not a market bar
        keep = ~((k["volume"] == 0) & (k["high"] == k["low"]))
        k = k[keep & (k.ts >= pd.Timestamp(E.START, tz="UTC"))]
        k[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(cache / f"{s}.pkl")
        mom = np.log(fr["_close"]) - np.log(fr["_close"].shift(720))
        fr["b_mom720"] = mom
        fr["symbol"] = s
        frames[s] = fr
        fam.append(fr.drop(columns=["_close", "_lr"]))
    tab = E.build_table(cache, [s for s in syms if s in frames])
    cs = F.cross_section({s: f for s, f in frames.items()})
    famdf = pd.concat(fam, ignore_index=True)
    tab["ts"] = tab["ts"].astype("datetime64[ns, UTC]")
    tab = tab.merge(famdf, on=["symbol", "ts"], how="left").merge(cs, on=["symbol", "ts"], how="left")
    if macro_dir is not None:
        # F8 is market-wide: computed once per decision ts, then joined to every symbol's row at that ts
        uts = pd.Series(tab["ts"].drop_duplicates().sort_values().to_numpy())
        tab = tab.merge(F.f8(uts, F.load_macro_daily(macro_dir)), on="ts", how="left")
    for c in ALL_FAM_COLS:
        if c not in tab.columns:
            tab[c] = np.nan
    tab.to_pickle(out / "table.pkl")
    return tab


def coverage(tab: pd.DataFrame, fam: str, end: str = E.HOLDOUT_START) -> float:
    dev = tab[tab.ts < pd.Timestamp(end, tz="UTC")]
    col = "f3_present" if fam == "F3" else F.FAMILIES[fam][0]
    return float((dev[col] > 0).mean()) if fam == "F3" else float(dev[col].notna().mean())


# ----------------------------------------------------------------------------------------------- ablation
def _fam_cols(fam: str) -> list[str]:
    return COMPACT[fam] if fam in COMPACT else F.FAMILIES[fam]


def placebo_cols(width: int) -> list[str]:
    return [f"nz_{j}" for j in range(width)]


def add_placebo(tab: pd.DataFrame, width: int) -> pd.DataFrame:
    """``width`` seeded N(0,1) columns, one value per table row, identical on every run (the matched-width placebo).
    Row order is fixed by (symbol, ts) so the draw does not depend on how the table was assembled."""
    t = tab.sort_values(["symbol", "ts"]).copy()
    rng = np.random.default_rng(PLACEBO_SEED + width)
    for c in placebo_cols(width):
        t[c] = rng.standard_normal(len(t))
    return t.sort_index()


def features_for(arm: str) -> list[str]:
    if arm in PLACEBO_WIDTH:
        return E.FEATURES + placebo_cols(PLACEBO_WIDTH[arm])
    return E.FEATURES + [c for fam in ARMS[arm] for c in _fam_cols(fam)]


def lofo(folds: list[dict]) -> dict:
    """Leave-one-fold-out tau: tau for fold k = argmax pooled mean over the OTHER folds (n >= TAU_MIN_DEV_N), tie -> larger."""
    per_fold, tot_n, tot_sum = [], 0, 0.0
    for k, f in enumerate(folds):
        best, bt = None, None
        for tau in E.TAU_GRID:
            n = sum(g[f"tau_{tau}"]["n"] for j, g in enumerate(folds) if j != k)
            sm = sum(g[f"tau_{tau}"].get("sum_net_r", 0.0) for j, g in enumerate(folds) if j != k)
            if n >= E.TAU_MIN_DEV_N and (best is None or (sm / n, tau) > best):
                best, bt = (sm / n, tau), tau
        t = f[f"tau_{bt}"] if bt is not None else {"n": 0, "sum_net_r": 0.0}
        per_fold.append({"fold": f["test_start"], "tau": bt, "n": t["n"],
                         "mean_net_r": (t["sum_net_r"] / t["n"]) if t["n"] else None})
        tot_n += t["n"]
        tot_sum += t["sum_net_r"]
    return {"per_fold": per_fold, "n": tot_n, "mean_net_r": (tot_sum / tot_n) if tot_n else None}


def run_arm(tab: pd.DataFrame, arm: str, out: Path, n_jobs: int) -> dict:
    t0 = time.time()
    feats = features_for(arm)
    if arm in PLACEBO_WIDTH:
        tab = add_placebo(tab, PLACEBO_WIDTH[arm])
    base_params = dict(E.LGB_PARAMS)
    if arm in SEEDS:
        E.LGB_PARAMS["random_state"] = SEEDS[arm]
    try:
        wf = E.walk_forward(tab, feats, n_jobs=n_jobs)
    finally:
        E.LGB_PARAMS.clear()
        E.LGB_PARAMS.update(base_params)
    res = {"arm": arm, "families": ARMS[arm], "n_features": len(feats), "features": feats, "walk_forward": wf,
           "lofo": lofo(wf["folds"]), "elapsed_s": round(time.time() - t0)}
    (out / f"arm_{arm}.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def combine(tab: pd.DataFrame, out: Path) -> dict:
    arms = {p.stem[4:]: json.loads(p.read_text()) for p in sorted(out.glob("arm_*.json"))}
    if "A" not in arms:
        raise SystemExit("arm A (baseline) is required")
    a = arms["A"]["lofo"]
    res = {"read_state": "read", "rule": "ADMIT iff pooled LOFO delta >= +0.010 R per decision AND delta > 0 in >= 6 of 8 folds "
           "AND delta >= the measured seed noise |A - A2| AND present on >= 40 percent of dev decision rows", "baseline_A": {"n": a["n"], "mean_net_r": a["mean_net_r"]},
           "arms": {}, "admitted_families": [], "variants_read_on_sealed_window": 0,
           "not_run": ["H (bookDepth): not fetched; rule of fs01-01 arm H stays unevaluated"]}
    noise = None
    if "A2" in arms and arms["A2"]["lofo"]["mean_net_r"] is not None and a["mean_net_r"] is not None:
        noise = abs(arms["A2"]["lofo"]["mean_net_r"] - a["mean_net_r"])
    res["noise_floor_abs_A_minus_A2"] = noise
    if noise is None:
        raise SystemExit("arm A2 (seed noise floor) is required by the registered rule")
    for arm, r in arms.items():
        if arm in ("A", "A2", "G"):
            continue
        fam = ARMS[arm][0]
        lf = r["lofo"]
        d = (lf["mean_net_r"] - a["mean_net_r"]) if (lf["mean_net_r"] is not None and a["mean_net_r"] is not None) else None
        pos = sum(1 for x, y in zip(lf["per_fold"], a["per_fold"]) if x["mean_net_r"] is not None and y["mean_net_r"] is not None
                  and x["mean_net_r"] > y["mean_net_r"])
        cov = coverage(tab, fam)
        if cov < ADMIT_COVERAGE:
            verdict = "indeterminate"
        else:
            verdict = "admit" if (d is not None and d >= max(ADMIT_DELTA, noise) and pos >= ADMIT_FOLDS) else "reject"
        res["arms"][arm] = {"family": fam, "n": lf["n"], "mean_net_r": lf["mean_net_r"], "delta_vs_A": d, "folds_better_than_A": pos,
                            "dev_coverage": cov, "verdict": verdict}
        if verdict == "admit":
            res["admitted_families"].append(fam)
    if "G" in arms:
        g = arms["G"]["lofo"]
        res["arms"]["G"] = {"families": ARMS["G"], "n": g["n"], "mean_net_r": g["mean_net_r"],
                            "delta_vs_A": (g["mean_net_r"] - a["mean_net_r"]) if g["mean_net_r"] is not None else None,
                            "note": "reported beside B..F; never substitutes for them"}
    (out / "ablation.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def compact_coverage(tab: pd.DataFrame, fams: list[str], end: str = E.HOLDOUT_START) -> float:
    dev = tab[tab.ts < pd.Timestamp(end, tz="UTC")]
    return float(min(dev[COMPACT[f][0]].notna().mean() for f in fams))


def combine_placebo(tab: pd.DataFrame, out: Path) -> dict:
    """RQ-20261127-26ac-01 rule (registered before any run). Per arm X in P2 / P5 / P25 against its matched-width placebo
    N = PLACEBO_FOR[X], on the LOFO per-fold means (tau chosen on the other folds, as fs01-01):
      PASS iff pooled delta (X - N) >= +0.010 R/decision AND delta > 0 in >= 6 of 8 folds AND the one-sided t on the 8
           per-fold deltas >= COMPACT_T_BAR (Sidak, k = 3) AND the per-year mean delta > 0 in >= 3 of 4 years
           AND the arm's families are present on >= 40 percent of dev rows;
      INDETERMINATE if coverage < 40 percent or fewer than 8 folds carry both means; FAIL otherwise.
    The unit's verdict is PASS if any arm passes (the largest pooled delta is named), FAIL if every arm fails, else
    INDETERMINATE. Baseline A and seed-noise A2 are reported, never graded."""
    arms = {p.stem[4:]: json.loads(p.read_text()) for p in sorted(out.glob("arm_*.json"))}
    for need in ("A", "A2", "N4", "N8"):
        if need not in arms:
            raise SystemExit(f"arm {need} is required by the registered rule")
    res = {"read_state": "read", "rule": combine_placebo.__doc__, "t_bar": COMPACT_T_BAR, "arms": {},
           "baseline_A": {"n": arms["A"]["lofo"]["n"], "mean_net_r": arms["A"]["lofo"]["mean_net_r"]},
           "seed_noise_abs_A_minus_A2": (abs(arms["A2"]["lofo"]["mean_net_r"] - arms["A"]["lofo"]["mean_net_r"])
                                        if None not in (arms["A2"]["lofo"]["mean_net_r"], arms["A"]["lofo"]["mean_net_r"]) else None),
           "placebos": {k: {"n": arms[k]["lofo"]["n"], "mean_net_r": arms[k]["lofo"]["mean_net_r"]} for k in PLACEBO_WIDTH},
           "variants_read_on_sealed_window": 0}
    for arm, pl in PLACEBO_FOR.items():
        if arm not in arms:
            res["arms"][arm] = {"verdict": "indeterminate", "why": "arm did not run"}
            continue
        x, n = arms[arm]["lofo"], arms[pl]["lofo"]
        pairs = [(a["fold"], a["mean_net_r"] - b["mean_net_r"]) for a, b in zip(x["per_fold"], n["per_fold"])
                 if a["mean_net_r"] is not None and b["mean_net_r"] is not None]
        d = [v for _, v in pairs]
        pooled = (x["mean_net_r"] - n["mean_net_r"]) if None not in (x["mean_net_r"], n["mean_net_r"]) else None
        t = None
        if len(d) >= 2:
            sd = float(np.std(d, ddof=1))
            t = (float(np.mean(d)) / (sd / np.sqrt(len(d)))) if sd > 0 else None
        years: dict = {}
        for fold, v in pairs:
            years.setdefault(str(fold)[:4], []).append(v)
        yearly = {y: float(np.mean(v)) for y, v in sorted(years.items())}
        cov = compact_coverage(tab, ARMS[arm])
        pos = sum(1 for v in d if v > 0)
        ypos = sum(1 for v in yearly.values() if v > 0)
        if cov < ADMIT_COVERAGE or len(d) < len(E.DEV_FOLDS):
            verdict = "indeterminate"
        elif (pooled is not None and pooled >= COMPACT_DELTA and pos >= COMPACT_FOLDS and t is not None
              and t >= COMPACT_T_BAR and ypos >= COMPACT_YEARS):
            verdict = "pass"
        else:
            verdict = "fail"
        res["arms"][arm] = {"families": ARMS[arm], "columns": [c for f in ARMS[arm] for c in COMPACT[f]], "placebo": pl,
                            "n": x["n"], "mean_net_r": x["mean_net_r"], "pooled_delta_vs_placebo": pooled,
                            "fold_deltas": dict(pairs), "folds_positive": pos, "t_fold": t, "yearly_delta": yearly,
                            "years_positive": ypos, "dev_coverage": cov, "verdict": verdict,
                            "delta_vs_A": (x["mean_net_r"] - arms["A"]["lofo"]["mean_net_r"])
                            if None not in (x["mean_net_r"], arms["A"]["lofo"]["mean_net_r"]) else None}
    vs = [r["verdict"] for r in res["arms"].values()]
    passed = [a for a, r in res["arms"].items() if r["verdict"] == "pass"]
    res["verdict"] = "pass" if passed else ("fail" if vs and all(v == "fail" for v in vs) else "indeterminate")
    res["best_arm"] = max(passed, key=lambda a: res["arms"][a]["pooled_delta_vs_placebo"]) if passed else None
    (out / "compact.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------------------------------------- forward (fs02-01)
def signal_baseline(test: pd.DataFrame, sidefn) -> dict:
    t = test.sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for row in g.itertuples(index=False):
            if row.i <= busy:
                continue
            side = sidefn(row)
            if side is None:
                continue
            out.append((sym, getattr(row, f"net_{side}")))
            busy = row.i + getattr(row, f"bars_{side}")
    df = pd.DataFrame(out, columns=["symbol", "net_r"])
    return {"n": len(df), "mean_net_r": float(df.net_r.mean()) if len(df) else None}


def benchmarks(test: pd.DataFrame) -> dict:
    """Reported beside v2, never gating (manager 2026-11-01, audit ML-M1-POOLED-ENTRY). Same one-position mechanics and cost stack."""
    def ts(r):
        return None if pd.isna(r.b_mom720) else ("long" if r.b_mom720 > 0 else "short")

    def xs(r):
        return None if pd.isna(r.f4_rank_ret168) else ("long" if r.f4_rank_ret168 >= 2 / 3 else "short" if r.f4_rank_ret168 <= 1 / 3 else None)

    def cy(r):
        return None if (pd.isna(r.f2_fund) or abs(r.f2_fund) < 1e-4) else ("short" if r.f2_fund > 0 else "long")

    return {"tsmom_sign_of_720h_return": signal_baseline(test, ts),
            "xsmom_top_third_long_bottom_third_short_by_168h_rank": signal_baseline(test, xs),
            "funding_carry_opposite_to_funding_when_abs_ge_1bp": signal_baseline(test, cy)}


def forward(tab: pd.DataFrame, out: Path, ablation: Path, unit: str, reader: str, n_jobs: int, ledger: Path) -> dict:
    ab = json.loads(ablation.read_text())
    fams = ab["admitted_families"]
    if not fams:
        res = {"verdict": "not_run", "why": "fs01-01 admitted no family: 20 features was sufficient on the dev folds",
               "read_state": "read", "variants_on_window": 0}
        (out / "forward.json").write_text(json.dumps(res, indent=1))
        return res
    feats = E.FEATURES + [c for f in fams for c in F.FAMILIES[f]]
    w0, w1 = W1
    t0 = time.time()
    wf = E.walk_forward(tab, feats, dev_folds=E.DEV_FOLDS + EXTRA_DEV_FOLDS, dev_end=w0, n_jobs=n_jobs)
    tau = wf["tau_star"]
    if tau is None:
        res = {"verdict": "indeterminate", "why": "no tau reaches dev n >= 1000", "walk_forward": wf}
        (out / "forward.json").write_text(json.dumps(res, indent=1, default=str))
        return res
    train_end = str((pd.Timestamp(w0) - pd.Timedelta(days=1)).date())   # E.holdout fits on rows strictly before w0
    # every read is recorded; a re-read of the ENTRY family on W1 is graded on the ledger's deflated bar (HOLDOUT-DEFLATED-REUSE)
    claim = holdout_lock.claim_read("ENTRY-v2-" + "+".join(fams), w0, w1, unit, reader, ledger, train_end=train_end)
    h = E.holdout(tab, tau, feats, w0, w1, n_jobs)
    test = tab[(tab.ts >= pd.Timestamp(w0, tz="UTC")) & (tab.ts < pd.Timestamp(w1, tz="UTC") + pd.Timedelta(days=1))]
    v, why = E.verdict(h, claim["bar"])
    res = {"unit": unit, "verdict": v, "why": why, "read_state": "read", "families": fams, "n_features": len(feats), "tau_star": tau,
           "window": [w0, w1], "holdout_lock": claim, "variants_on_window": claim["variants_on_window"],
           "holdout": h, "benchmarks_reported_not_gating": benchmarks(test), "dev_walk_forward": wf,
           "elapsed_s": round(time.time() - t0)}
    # reported reference: the frozen v1 recipe (20 features) on the same window; a second model read, so the lock counts it
    claim1 = holdout_lock.claim_read("ENTRY-v1-frozen-ref", w0, w1, unit + "-v1ref", reader, ledger, train_end=train_end)
    tau1 = 0.10
    res["v1_reference"] = {"tau": tau1, "holdout_lock": claim1, "holdout": E.holdout(tab, tau1, None, w0, w1, n_jobs)["model"]}
    res["variants_on_window"] = claim1["variants_on_window"]
    (out / "forward.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------------------------------------- self-test + CLI
def _self_test() -> None:
    F.self_test()
    # lofo: tau chosen without the held fold; a fold whose tau pool has n < 1000 elsewhere gets no tau
    def mk(ts, n, sm):
        return {"test_start": ts, **{f"tau_{t}": {"n": n, "sum_net_r": sm} for t in E.TAU_GRID}}

    folds = [mk(f"2022-0{i}-01", 600, 6.0) for i in range(1, 5)]
    lf = lofo(folds)
    assert lf["n"] == 2400 and abs(lf["mean_net_r"] - 0.01) < 1e-12, lf
    # forward: a second read of the window is recorded and graded on a stricter bar; a window overlapping training is refused
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "l.jsonl"
        te = str((pd.Timestamp(W1[0]) - pd.Timedelta(days=1)).date())
        c1 = holdout_lock.claim_read("ENTRY-m", *W1, "u", "t", led, train_end=te)
        c2 = holdout_lock.claim_read("ENTRY-m", *W1, "u", "t", led, train_end=te)
        assert c1["n_tries"] == 1 and c2["n_tries"] == 2 and c2["bar"]["ci_z"] > c1["bar"]["ci_z"]
        try:
            holdout_lock.claim_read("ENTRY-m", *W1, "u", "t", led, train_end=W1[0])
            raise AssertionError("a window overlapping training was allowed")
        except holdout_lock.WindowOverlapsTraining:
            pass
    # no arm may read a sealed date: the dev walk's last bound is HOLDOUT_START
    assert E.HOLDOUT_START == "2025-10-01" and "2025-10-01" not in E.DEV_FOLDS
    _self_test_compact()
    print("ml_entry_v2 self-test OK")


def _self_test_compact() -> None:
    """COMPACT-DERIVS: the placebo is deterministic and row-order independent; the compact columns are real family
    columns; combine_placebo grades against the matched placebo (not A) and applies every clause of the rule."""
    import tempfile
    for fam, cols in COMPACT.items():
        src = F.FAMILIES["F2" if fam == "F2c" else "F5"]
        assert set(cols) <= set(src) and len(cols) == 4, (fam, cols)
    tab = pd.DataFrame({"symbol": ["B", "A", "B", "A"], "ts": pd.to_datetime([2, 1, 1, 2], unit="h", utc=True)})
    p1, p2 = add_placebo(tab, 4), add_placebo(tab.sample(frac=1, random_state=3), 4)
    k = ["symbol", "ts"]
    assert p1.sort_values(k)[placebo_cols(4)].to_numpy().tolist() == p2.sort_values(k)[placebo_cols(4)].to_numpy().tolist()
    assert features_for("N8")[-8:] == placebo_cols(8) and features_for("P25")[-8:] == COMPACT["F2c"] + COMPACT["F5c"]
    folds = E.DEV_FOLDS

    def arm(means):
        return {"lofo": {"n": 8000, "mean_net_r": float(np.mean(means)),
                         "per_fold": [{"fold": f, "tau": 0.1, "n": 1000, "mean_net_r": m} for f, m in zip(folds, means)]}}
    base = [0.0] * len(folds)
    good = [0.03, 0.02, 0.025, 0.03, 0.02, 0.028, 0.022, 0.03]       # +0.026, 8/8 folds, every year positive
    flat = [0.01, -0.01, 0.012, -0.011, 0.009, -0.01, 0.011, -0.012]  # ~0, 4/8 folds
    big_a = [0.05] * len(folds)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        for name, m in (("A", big_a), ("A2", big_a), ("N4", base), ("N8", base), ("P2", good), ("P5", flat), ("P25", flat)):
            (out / f"arm_{name}.json").write_text(json.dumps(arm(m)))
        cov_tab = pd.DataFrame({"ts": pd.to_datetime(["2023-01-01"] * 3, utc=True),
                                **{c: [1.0, 1.0, np.nan] for f in COMPACT.values() for c in f}})
        r = combine_placebo(cov_tab, out)
        assert r["arms"]["P2"]["verdict"] == "pass", r["arms"]["P2"]          # graded vs N4, not vs A (A is higher)
        assert r["arms"]["P2"]["delta_vs_A"] < 0
        assert r["arms"]["P5"]["verdict"] == "fail" and r["verdict"] == "pass" and r["best_arm"] == "P2"
        low = pd.DataFrame({"ts": pd.to_datetime(["2023-01-01"] * 3, utc=True),
                            **{c: [1.0, np.nan, np.nan] for f in COMPACT.values() for c in f}})
        assert combine_placebo(low, out)["arms"]["P2"]["verdict"] == "indeterminate"   # coverage < 40 percent
        (out / "arm_P2.json").write_text(json.dumps(arm([0.03] * 7 + [-0.2])))       # one bad fold kills the t / mean
        assert combine_placebo(cov_tab, out)["arms"]["P2"]["verdict"] == "fail"
        (out / "arm_N8.json").unlink()
        try:
            combine_placebo(cov_tab, out)
            raise AssertionError("a missing placebo was allowed")
        except SystemExit:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["build-table", "arm", "combine", "combine-compact", "forward"])
    ap.add_argument("--streams", default="")
    ap.add_argument("--oct-dir", default="")
    ap.add_argument("--macro-dir", default="", help="F8: the <TICKER>.csv daily closes ml_entry_families.fetch_macro_daily wrote")
    ap.add_argument("--out", default="/tmp/ml_entry_v2")
    ap.add_argument("--arm", default="A")
    ap.add_argument("--n-jobs", type=int, default=2)
    ap.add_argument("--ablation", default="")
    ap.add_argument("--unit", default="RQ-20261101-fs02-01")
    ap.add_argument("--reader", default="lane ML-FEATURE-INFRA")
    ap.add_argument("--ledger", default=str(holdout_lock.LEDGER))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "build-table":
        tab = build_table(Path(a.streams), Path(a.oct_dir) if a.oct_dir else None, out, E.universe(),
                          macro_dir=Path(a.macro_dir) if a.macro_dir else None)
        print(f"table rows={len(tab)} symbols={tab.symbol.nunique()}", flush=True)
        return 0
    tab = pd.read_pickle(out / "table.pkl")
    tab[ALL_FAM_COLS] = tab[ALL_FAM_COLS].astype(float)   # object dtypes from older table builds break LightGBM
    if a.cmd == "arm":
        r = run_arm(tab, a.arm, out, a.n_jobs)
        print(a.arm, json.dumps(r["lofo"])[:300], flush=True)
    elif a.cmd == "combine":
        print(json.dumps(combine(tab, out), indent=1, default=str))
    elif a.cmd == "combine-compact":
        print(json.dumps(combine_placebo(tab, out), indent=1, default=str)[:4000])
    elif a.cmd == "forward":
        print(json.dumps(forward(tab, out, Path(a.ablation), a.unit, a.reader, a.n_jobs, Path(a.ledger)), indent=1, default=str)[:3000])
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
