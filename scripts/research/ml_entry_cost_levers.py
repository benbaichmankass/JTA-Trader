#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261112-4654-02.yaml (tau arm) + RQ-20261112-4654-03.yaml (bracket arm); rows ML-LEVER-PLAN, ML-TIMEFRAME
"""ENTRY cost levers under the PER-SYMBOL cost stack (rows ML-LEVER-PLAN / ML-TIMEFRAME; AM-ML overnight queue item 3, 2026-11-12).

WHY. RQ-20261112-2e3b-01 scored the frozen ml_entry on its 51-symbol Bybit population with each symbol's own cost stack and read a mean
GROSS of +0.0709 R per decision against a mean COST of 0.1389 R (net -0.0680, n 12,746). The round-1 lever units (b601 brackets, b602
selectivity, b625/b626 4h) were judged under the flat c692-01 stack (fee 11 + slippage 3 + funding 1 bps/8h), so they never priced
the cost that actually kills the model. Cost in R is (round-trip bps) x price / risk, and risk = SL_ATR x ATR, so a lever that makes the
trade bigger in R terms (wider bracket) or keeps only the decisions whose predicted net R is large (higher tau) attacks the ratio
directly. This harness re-tests exactly those two levers with the 2e3b-01 cost stack, on the DEV FOLDS ONLY.

DEV ONLY. Every table is clipped to ts < ml_decision_entry.HOLDOUT_START (2025-10-01) before anything is fitted or scored; the held-out
year (already read 12+ times by family ENTRY) is never touched. A WIN here is a CANDIDATE for one later fresh-window read, nothing more.

COST STACK (imported, not re-implemented): ml_entry_population_test.symbol_costs + .recost -- fee 11.0 + max(3.0, quoted spread +
sqrt impact at Q 5,000 USD) + max(1.0, the symbol-month's mean |funding| per 8h) x windows crossed, on the frozen 2e3b-01 population
(comms/research/RQ-20261112-2e3b-01/freeze/population.json). Funding is fetched for the dev months here (the 2e3b harness fetches only its
own window); a month with no file is charged the 1.0 floor and counted.

ARMS (one factor each against the base: the c692-01 recipe refit per dev fold, SL 2 / TP 3 ATR, 24 h horizon, tau 0.10):
  tau      tau in {0.20, 0.30, 0.50} on the BASE fold predictions (same models, a stricter entry threshold)
  bracket  (SL, TP) in {(3.0, 4.5), (4.0, 6.0)} ATR (the base geometry scaled x1.5 and x2; horizon unchanged): relabel, refit per fold

RULE (registered in each unit before any run; constants below are copied from the units, none is a tuning knob):
  an arm WINS iff  pooled dev n >= ARM_MIN_N  and every fold has n >= FOLD_MIN_N
             and  arm pooled mean net R >= base pooled mean net R + DELTA_R
             and  arm fold mean net R > base fold mean net R in >= MIN_FOLDS_BETTER of the folds
  INDETERMINATE iff a floor is not met; LOSS otherwise. A unit PASSes iff at least one of its arms WINS.

    python3 scripts/research/ml_entry_cost_levers.py run --lever tau|bracket --cache DIR --out DIR --unit RQ-... [--rule-id ..]
    python3 scripts/research/ml_entry_cost_levers.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import functools
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402
import ml_entry_population_test as P  # noqa: E402

TAUS = (0.20, 0.30, 0.50)
BRACKETS = ((3.0, 4.5), (4.0, 6.0))
BASE_TAU, BASE_BRACKET = 0.10, (E.SL_ATR, E.TP_ATR)
ARM_MIN_N, FOLD_MIN_N = 1000, 100
DELTA_R = 0.03
MIN_FOLDS_BETTER = 6          # of the 8 c692-01 dev folds
KLINES_END = "2026-10-31"     # symbol_costs needs RATIO_MONTH 2026-10 for the Bybit/Binance turnover ratio
DEV_FUND_MONTHS = ("2021-07", "2025-09")


# ----------------------------------------------------------------------------------------------- relabel
@contextlib.contextmanager
def bracket(sl: float, tp: float):
    """Run E.label_symbol at a different bracket. label_symbol reads E.SL_ATR (risk) and calls E.bracket_outcome at call time, so both
    are swapped for the duration and restored after; at the base geometry the labels are byte-identical (self-test)."""
    orig_sl, orig_bo = E.SL_ATR, E.bracket_outcome
    E.SL_ATR = sl
    E.bracket_outcome = functools.partial(orig_bo, sl_atr=sl, tp_atr=tp)
    try:
        yield
    finally:
        E.SL_ATR, E.bracket_outcome = orig_sl, orig_bo


# ----------------------------------------------------------------------------------------------- data
def fetch_dev_funding(sym: str) -> dict[str, float]:
    out = {}
    for m in P.months(*DEV_FUND_MONTHS):
        d = P._zip_csv(f"{P._FR}/{sym}/{sym}-fundingRate-{m}.zip")
        if d is None or d.empty:
            continue
        d = d.iloc[:, :3]
        d.columns = ["calc_time", "interval_h", "rate"]
        iv = pd.to_numeric(d.interval_h, errors="coerce").median()
        rate = pd.to_numeric(d.rate, errors="coerce").abs().mean()
        if np.isfinite(iv) and iv > 0 and np.isfinite(rate):
            out[m] = float(1e4 * rate * 8.0 / iv)
    return out


def dev_table(cache: Path, pop: list[str], ref: list[str], costs: dict, sl: float, tp: float) -> pd.DataFrame:
    with bracket(sl, tp):
        tab = E.build_table(cache, sorted(set(pop) | set(ref)), xs_symbols=ref, recost_inputs=True)
    tab = tab[tab.symbol.isin(pop) & (tab.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC"))].reset_index(drop=True)
    sc = P.recost(tab, costs)
    return sc[sc.cost_ok].reset_index(drop=True)


# ----------------------------------------------------------------------------------------------- walk-forward
def fold_predictions(sc: pd.DataFrame, fit_predict=None) -> list[tuple[str, pd.DataFrame, np.ndarray, np.ndarray]]:
    fit_predict = fit_predict or E.fit_predict
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [pd.Timestamp(E.HOLDOUT_START, tz="UTC")]
    out = []
    for a, b in itertools.pairwise(bounds):
        test = sc[(sc.ts >= a) & (sc.ts < b - pd.Timedelta(hours=E.HORIZON_H + 1))].reset_index(drop=True)
        train = E.purge_train(sc[sc.ts < a], a)
        if len(test) == 0 or len(train) == 0:
            out.append((str(a.date()), test, np.array([]), np.array([])))
            continue
        pl, ps = fit_predict(train, test)
        out.append((str(a.date()), test, pl, ps))
    return out


def score(preds, tau: float) -> dict:
    folds, taken = {}, []
    for name, test, pl, ps in preds:
        tk = E.policy(test, pl, ps, tau) if len(test) and len(pl) else pd.DataFrame(columns=["net_r", "gross_r", "cost_r"])
        folds[name] = {"n": len(tk), "mean_net_r": float(tk.net_r.mean()) if len(tk) else None,
                       "mean_gross_r": float(tk.gross_r.mean()) if len(tk) else None,
                       "mean_cost_r": float(tk.cost_r.mean()) if len(tk) else None}
        taken.append(tk)
    allt = pd.concat(taken, ignore_index=True) if taken else pd.DataFrame(columns=["net_r"])
    pooled = {"n": len(allt), "mean_net_r": float(allt.net_r.mean()) if len(allt) else None,
              "mean_gross_r": float(allt.gross_r.mean()) if len(allt) else None,
              "mean_cost_r": float(allt.cost_r.mean()) if len(allt) else None,
              "se_net_r": float(allt.net_r.std(ddof=1) / np.sqrt(len(allt))) if len(allt) > 1 else None}
    return {"pooled": pooled, "folds": folds}


def judge(base: dict, arm: dict) -> dict:
    fn = [f["n"] for f in arm["folds"].values()]
    if arm["pooled"]["n"] < ARM_MIN_N or not fn or min(fn) < FOLD_MIN_N or base["pooled"]["mean_net_r"] is None:
        return {"call": "INDETERMINATE", "why": f"pooled n {arm['pooled']['n']} (floor {ARM_MIN_N}), min fold n {min(fn) if fn else 0} "
                                                f"(floor {FOLD_MIN_N})"}
    delta = arm["pooled"]["mean_net_r"] - base["pooled"]["mean_net_r"]
    better = sum(1 for k, f in arm["folds"].items()
                 if f["mean_net_r"] is not None and base["folds"][k]["mean_net_r"] is not None
                 and f["mean_net_r"] > base["folds"][k]["mean_net_r"])
    win = delta >= DELTA_R and better >= MIN_FOLDS_BETTER
    return {"call": "WIN" if win else "LOSS", "delta_mean_net_r": delta, "folds_better": better, "n_folds": len(arm["folds"]),
            "why": f"delta {delta:+.4f} (bar +{DELTA_R}), better in {better}/{len(arm['folds'])} folds (bar {MIN_FOLDS_BETTER})"}


def unit_verdict(calls: dict) -> str:
    vals = [c["call"] for c in calls.values()]
    if "WIN" in vals:
        return "pass"
    if vals and all(v == "LOSS" for v in vals):
        return "fail"
    return "indeterminate"


# ----------------------------------------------------------------------------------------------- run
def run(a) -> int:
    out, cache = Path(a.out), Path(a.cache)
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    frz = json.loads(Path(a.population).read_text())
    pop, spec = frz["population"], frz["spec"]
    ref = P._xs_ref()
    syms = sorted(set(pop) | set(ref))
    rep = E.fetch(cache, syms, end=KLINES_END)
    have = {s for s, r in rep.items() if r.get("rows")}
    pop_ok, ref_ok = [s for s in pop if s in have], [s for s in ref if s in have]
    with cf.ThreadPoolExecutor(8) as ex:
        fund = dict(zip(pop_ok, ex.map(fetch_dev_funding, pop_ok)))
    costs = {s: P.symbol_costs(pd.read_pickle(cache / f"{s}.pkl"), spec[s], fund.get(s, {})) for s in pop_ok}
    print(f"fetched pop {len(pop_ok)}/{len(pop)} ref {len(ref_ok)}/{len(ref)} t={time.time()-t0:.0f}s", flush=True)
    base_sc = dev_table(cache, pop_ok, ref_ok, costs, *BASE_BRACKET)
    base_preds = fold_predictions(base_sc)
    base = score(base_preds, BASE_TAU)
    arms, calls = {}, {}
    if a.lever == "tau":
        for t in TAUS:
            arms[f"tau={t}"] = score(base_preds, t)
    else:
        for sl, tp in BRACKETS:
            sc = dev_table(cache, pop_ok, ref_ok, costs, sl, tp)
            arms[f"bracket={sl}/{tp}"] = score(fold_predictions(sc), BASE_TAU)
    for k, v in arms.items():
        calls[k] = judge(base, v)
    verdict = unit_verdict(calls)
    fund_def = int(sum(int(v[v.month.between(*DEV_FUND_MONTHS)].fund_defaulted.sum()) for v in costs.values()))
    note = f"{a.lever}: {verdict} | base dev mean net R {base['pooled']['mean_net_r']} (gross {base['pooled']['mean_gross_r']}, cost " \
           f"{base['pooled']['mean_cost_r']}, n {base['pooled']['n']}) | " + " | ".join(f"{k}: {c['call']} ({c['why']})" for k, c in calls.items())
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": verdict,
           "population": (f"c692-01 recipe refit per dev fold ({E.DEV_FOLDS[0]}..{E.HOLDOUT_START}, held-out never read) on the {len(pop_ok)} "
                          f"scorable symbols of the frozen 2e3b-01 population, each decision re-costed with its own fee 11 + max(3, quoted spread + "
                          f"sqrt impact Q 5000) + |funding| per 8h; one-position-per-symbol policy"),
           "note": note, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {"base": base, "arms": arms, "calls": calls, "funding_months_defaulted_dev": fund_def,
                           "thresholds": {"arm_min_n": ARM_MIN_N, "fold_min_n": FOLD_MIN_N, "delta_r": DELTA_R,
                                          "min_folds_better": MIN_FOLDS_BETTER}, "elapsed_s": round(time.time() - t0)},
           "n": base["pooled"]["n"],
           "produced_by": {"tool": f"python3 scripts/research/ml_entry_cost_levers.py run --lever {a.lever}", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(note, flush=True)
    return 0


def self_test() -> int:
    import tempfile

    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    df = pd.read_pickle(root / f"{syms[0]}.pkl")
    a = E.label_symbol(df, recost_inputs=True)
    with bracket(*BASE_BRACKET):
        b = E.label_symbol(df, recost_inputs=True)
    pd.testing.assert_frame_equal(a, b)                       # base geometry is byte-identical
    with bracket(4.0, 6.0):
        w = E.label_symbol(df, recost_inputs=True)
    assert E.SL_ATR == 2.0 and not np.allclose(a.net_long, w.net_long)   # restored, and a wider bracket changes the label
    assert (w.per_r_long < a.per_r_long).mean() > 0.9          # wider stop -> smaller price-per-R -> smaller cost in R
    base = {"pooled": {"n": 2000, "mean_net_r": -0.05}, "folds": {str(i): {"n": 200, "mean_net_r": -0.05} for i in range(8)}}
    good = {"pooled": {"n": 1500, "mean_net_r": 0.0}, "folds": {str(i): {"n": 150, "mean_net_r": 0.0} for i in range(8)}}
    thin = {"pooled": {"n": 500, "mean_net_r": 0.5}, "folds": {str(i): {"n": 60, "mean_net_r": 0.5} for i in range(8)}}
    flat = {"pooled": {"n": 1500, "mean_net_r": -0.04}, "folds": {str(i): {"n": 150, "mean_net_r": -0.04} for i in range(8)}}
    assert judge(base, good)["call"] == "WIN" and judge(base, thin)["call"] == "INDETERMINATE" and judge(base, flat)["call"] == "LOSS"
    assert unit_verdict({"x": {"call": "WIN"}, "y": {"call": "LOSS"}}) == "pass"
    assert unit_verdict({"x": {"call": "LOSS"}, "y": {"call": "LOSS"}}) == "fail"
    assert unit_verdict({"x": {"call": "LOSS"}, "y": {"call": "INDETERMINATE"}}) == "indeterminate"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--lever", choices=["tau", "bracket"])
    ap.add_argument("--cache", default="/tmp/ml_entry_cost_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_cost_levers_out")
    ap.add_argument("--population", default=str(P.POPULATION))
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit or not a.lever:
        ap.error("run --lever tau|bracket --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
