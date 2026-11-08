#!/usr/bin/env python3
# wiring: research/queue/RQ-20261108-98e3-26.yaml (runner unit); lane ML-ENTRY-EQ-STRUCTURE-RETEST; drift-remediation SKILL step 2
"""Retrain-cadence + decay test for the served ml_entry recipe (is the recent decline age (fixable by retraining) or regime?).

Over the frozen v1's clean held-out year, replay (a) the FROZEN v1 and (b) a model REFIT at each monthly origin (the registered
recipe, purged by ``E.purge_train``, ``tau`` carried) on the SAME decision rows: each refit scores the 28 days after its origin.
Both-sides policy, canonical cost stack. Three verdicts, rule in research/queue/RQ-20261108-98e3-26.yaml (registered before the run):

  cadence  CADENCE-LEVER iff refit n >= 300 and frozen n >= 300 and refit mean >= frozen mean + 0.03; NO-LEVER otherwise
  age      AGE-DECAY iff >= 10 windows with n >= 30 and Spearman(months since v1 train_end, frozen window mean) <= -0.40
  regime   REGIME-LINKED iff >= 10 windows and |Spearman(window pool-mean 24h realised vol (vol24), frozen window mean)| >= 0.50 and age not AGE-DECAY

    python3 scripts/research/ml_entry_cadence.py run --cache DIR --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..]
    python3 scripts/research/ml_entry_cadence.py --self-test
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
LEVER_N, LEVER_DELTA = 300, 0.03
WIN_N, MIN_WINDOWS, AGE_RHO, REGIME_RHO = 30, 10, -0.40, 0.50


def _spearman(x, y) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _stats(t: pd.DataFrame) -> dict:
    if t is None or len(t) == 0:
        return {"n": 0, "mean_net_r": None}
    return {"n": int(len(t)), "mean_net_r": float(t.net_r.mean()),
            "se": float(t.net_r.std(ddof=1) / math.sqrt(len(t))) if len(t) > 1 else None}


def cadence(tab: pd.DataFrame, frozen: dict, tau: float, train_end: str, start: str = START, end: str = END,
            step_days: int = STEP_DAYS, fit=None, vol_col: str = "vol24") -> dict:
    fit = fit or E.fit_models
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    t_end = pd.Timestamp(train_end, tz="UTC")
    rows, fro_all, ref_all = [], [], []
    for k in range(int((ts1 - ts0).days // step_days)):
        a0 = ts0 + pd.Timedelta(days=k * step_days)
        a1 = a0 + pd.Timedelta(days=step_days)
        win = tab[(tab.ts >= a0) & (tab.ts < a1)].reset_index(drop=True)
        if len(win) == 0:
            continue
        # provenance: predict -- regressed net R of each side (policy() thresholds at tau), not a probability
        fro = E.policy(win, frozen["long"].predict(win[E.FEATURES]), frozen["short"].predict(win[E.FEATURES]), tau)
        m = fit(E.purge_train(tab[tab.ts < a0], a0))
        ref = E.policy(win, m["long"].predict(win[E.FEATURES]), m["short"].predict(win[E.FEATURES]), tau)
        sf, sr = _stats(fro), _stats(ref)
        rows.append({"start": str(a0.date()), "months_since_train_end": float((a0 - t_end).days / 30.4375),
                     "frozen": sf, "refit": sr, "vol24_mean": float(win[vol_col].mean()) if vol_col in win else None})
        fro_all.append(fro)
        ref_all.append(ref)
    fro_p = _stats(pd.concat(fro_all)) if fro_all else _stats(None)
    ref_p = _stats(pd.concat(ref_all)) if ref_all else _stats(None)
    v = {}
    v["cadence"] = ("INDETERMINATE" if min(fro_p["n"], ref_p["n"]) < LEVER_N else
                    "CADENCE-LEVER" if ref_p["mean_net_r"] >= fro_p["mean_net_r"] + LEVER_DELTA else "NO-LEVER")
    ok = [r for r in rows if r["frozen"]["n"] >= WIN_N and r["frozen"]["mean_net_r"] is not None]
    rho_age = _spearman([r["months_since_train_end"] for r in ok], [r["frozen"]["mean_net_r"] for r in ok]) if len(ok) >= MIN_WINDOWS else None
    v["age"] = "INDETERMINATE" if rho_age is None else ("AGE-DECAY" if rho_age <= AGE_RHO else "NOT-AGE")
    okv = [r for r in ok if r["vol24_mean"] is not None]
    rho_vol = _spearman([r["vol24_mean"] for r in okv], [r["frozen"]["mean_net_r"] for r in okv]) if len(okv) >= MIN_WINDOWS else None
    v["regime"] = ("INDETERMINATE" if rho_vol is None else
                   "REGIME-LINKED" if (abs(rho_vol) >= REGIME_RHO and v["age"] != "AGE-DECAY") else "NOT-REGIME")
    return {"verdicts": v, "verdict_lines": [f"{k}: {x}" for k, x in v.items()], "windows": rows,
            "pooled": {"frozen": fro_p, "refit": ref_p}, "rho_age": rho_age, "rho_vol24": rho_vol, "tau": tau,
            "window": {"start": start, "end": end, "step_days": step_days}}


def run(a) -> int:
    import ml_entry_retrain as RT
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    syms = E.universe()
    rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = E.build_table(cache, syms)
    meta, frozen = E._frozen_models(REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json")
    assert str(meta["train_end_exclusive"]) < START, "the frozen model must not have seen the replay year"
    d = cadence(tab, frozen, float(meta["tau"]), str(meta["train_end_exclusive"]))
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate",
           "population": (f"frozen ml_decision_entry_v1 vs monthly-origin refits of the same recipe over {START}..{END} in {STEP_DAYS}-day windows, "
                          f"{tab.symbol.nunique()} symbols, canonical cost stack; descriptive about the recipe, not a promotion read"),
           "note": " | ".join(d["verdict_lines"]), "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "latest_bar": max(v["last_bar"] for v in rep.values())}, "n": d["pooled"]["frozen"]["n"],
           "produced_by": {"tool": "python3 scripts/research/ml_entry_cadence.py run", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("CADENCE: " + row["note"], flush=True)
    return 0


def self_test() -> int:
    import tempfile
    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    tab = E.build_table(root, syms)
    train = tab[tab.ts < tab.ts.max() - pd.Timedelta(days=60)]
    fit = lambda t: E.fit_models(t.sample(min(len(t), 15000), random_state=0))
    frozen = fit(train)
    start = (tab.ts.max() - pd.Timedelta(days=56)).strftime("%Y-%m-%d")
    end = (tab.ts.max() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d = cadence(tab, frozen, 0.0, str(train.ts.max()), start=start, end=end, step_days=14, fit=fit)
    assert set(d["verdicts"]) == {"cadence", "age", "regime"} and len(d["windows"]) >= 1, d["verdicts"]
    assert _spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0 and _spearman([1, 1, 1], [1, 2, 3]) is None
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_cadence_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-08")
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
