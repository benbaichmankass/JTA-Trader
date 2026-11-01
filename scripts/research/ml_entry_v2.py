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


def build_table(streams: Path, oct_dir: Path | None, out: Path, syms: list[str]) -> pd.DataFrame:
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
def features_for(arm: str) -> list[str]:
    return E.FEATURES + [c for fam in ARMS[arm] for c in F.FAMILIES[fam]]


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
        l = r["lofo"]
        d = (l["mean_net_r"] - a["mean_net_r"]) if (l["mean_net_r"] is not None and a["mean_net_r"] is not None) else None
        pos = sum(1 for x, y in zip(l["per_fold"], a["per_fold"]) if x["mean_net_r"] is not None and y["mean_net_r"] is not None
                  and x["mean_net_r"] > y["mean_net_r"])
        cov = coverage(tab, fam)
        if cov < ADMIT_COVERAGE:
            verdict = "indeterminate"
        else:
            verdict = "admit" if (d is not None and d >= max(ADMIT_DELTA, noise) and pos >= ADMIT_FOLDS) else "reject"
        res["arms"][arm] = {"family": fam, "n": l["n"], "mean_net_r": l["mean_net_r"], "delta_vs_A": d, "folds_better_than_A": pos,
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
    ts = lambda r: None if pd.isna(r.b_mom720) else ("long" if r.b_mom720 > 0 else "short")
    xs = lambda r: None if pd.isna(r.f4_rank_ret168) else ("long" if r.f4_rank_ret168 >= 2 / 3 else "short" if r.f4_rank_ret168 <= 1 / 3 else None)
    cy = lambda r: None if (pd.isna(r.f2_fund) or abs(r.f2_fund) < 1e-4) else ("short" if r.f2_fund > 0 else "long")
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
    claim = holdout_lock.claim_read("ENTRY-v2-" + "+".join(fams), w0, w1, unit, reader, ledger)   # ONE read; refuses a second
    h = E.holdout(tab, tau, feats, w0, w1, n_jobs)
    test = tab[(tab.ts >= pd.Timestamp(w0, tz="UTC")) & (tab.ts < pd.Timestamp(w1, tz="UTC") + pd.Timedelta(days=1))]
    v, why = E.verdict(h)
    res = {"unit": unit, "verdict": v, "why": why, "read_state": "read", "families": fams, "n_features": len(feats), "tau_star": tau,
           "window": [w0, w1], "holdout_lock": claim, "variants_on_window": claim["variants_on_window"],
           "holdout": h, "benchmarks_reported_not_gating": benchmarks(test), "dev_walk_forward": wf,
           "elapsed_s": round(time.time() - t0)}
    # reported reference: the frozen v1 recipe (20 features) on the same window; a second model read, so the lock counts it
    claim1 = holdout_lock.claim_read("ENTRY-v1-frozen-ref", w0, w1, unit + "-v1ref", reader, ledger)
    tau1 = 0.10
    res["v1_reference"] = {"tau": tau1, "holdout_lock": claim1, "holdout": E.holdout(tab, tau1, None, w0, w1, n_jobs)["model"]}
    res["variants_on_window"] = claim1["variants_on_window"]
    (out / "forward.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------------------------------------- self-test + CLI
def _self_test() -> None:
    F.self_test()
    # lofo: tau chosen without the held fold; a fold whose tau pool has n < 1000 elsewhere gets no tau
    mk = lambda ts, n, sm: {"test_start": ts, **{f"tau_{t}": {"n": n, "sum_net_r": sm} for t in E.TAU_GRID}}
    folds = [mk(f"2022-0{i}-01", 600, 6.0) for i in range(1, 5)]
    l = lofo(folds)
    assert l["n"] == 2400 and abs(l["mean_net_r"] - 0.01) < 1e-12, l
    # forward refuses a second read of the same model on an overlapping window
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "l.jsonl"
        holdout_lock.claim_read("m", *W1, "u", "t", led)
        try:
            holdout_lock.claim_read("m", *W1, "u", "t", led)
            raise AssertionError("second read allowed")
        except holdout_lock.HoldoutAlreadyRead:
            pass
    # no arm may read a sealed date: the dev walk's last bound is HOLDOUT_START
    assert E.HOLDOUT_START == "2025-10-01" and "2025-10-01" not in E.DEV_FOLDS
    print("ml_entry_v2 self-test OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["build-table", "arm", "combine", "forward"])
    ap.add_argument("--streams", default="")
    ap.add_argument("--oct-dir", default="")
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
        tab = build_table(Path(a.streams), Path(a.oct_dir) if a.oct_dir else None, out, E.universe())
        print(f"table rows={len(tab)} symbols={tab.symbol.nunique()}", flush=True)
        return 0
    tab = pd.read_pickle(out / "table.pkl")
    tab[ALL_FAM_COLS] = tab[ALL_FAM_COLS].astype(float)   # object dtypes from older table builds break LightGBM
    if a.cmd == "arm":
        r = run_arm(tab, a.arm, out, a.n_jobs)
        print(a.arm, json.dumps(r["lofo"])[:300], flush=True)
    elif a.cmd == "combine":
        print(json.dumps(combine(tab, out), indent=1, default=str))
    elif a.cmd == "forward":
        print(json.dumps(forward(tab, out, Path(a.ablation), a.unit, a.reader, a.n_jobs, Path(a.ledger)), indent=1, default=str)[:3000])
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
