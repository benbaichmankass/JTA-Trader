#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261112-4654-02.yaml (tau arm) + RQ-20261112-4654-03.yaml (bracket arm) + RQ-20261116-089f-03 (bracket_cond); rows ML-LEVER-PLAN, ML-TIMEFRAME
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

  bracket_cond  RQ-20261116-089f-03: HOLD the base (2/3, tau 0.10) taken decisions fixed and choose, per entry-time cell (side x atr_pct tercile,
            edges fixed on fold 1), which of {2/3, 3/4.5, 4/6} ATR to trade it at, using ONLY the folds before the graded fold (expanding window,
            >= COND_MIN_CELL prior decisions in the cell else 2/3). Fold 1 is burn-in. Graded vs static 2/3 and vs best-static-on-prior-folds.
            No refit: the alternative brackets are looked up on the same (symbol, ts, side) decision in the relabelled dev table.

    python3 scripts/research/ml_entry_cost_levers.py run --lever tau|bracket|bracket_cond --cache DIR --out DIR --unit RQ-... [--rule-id ..]
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


# ----------------------------------------------------------------------------------------------- bracket_cond (RQ-20261116-089f-03)
COND_BRACKETS = ((2.0, 3.0), (3.0, 4.5), (4.0, 6.0))     # static 2/3 first: it is the fallback and the baseline
COND_MIN_CELL = 400            # prior decisions required in a cell before it may leave 2/3
COND_MIN_FOLDS_ELIGIBLE = 5    # gradeable folds in which EVERY cell has >= COND_MIN_CELL prior decisions, else INDETERMINATE
COND_DELTA_R, COND_WINS_PASS, COND_WINS_FAIL = 0.03, 5, 3
COND_BOOT_DRAWS, COND_RANDOM_DRAWS, COND_SEED = 2000, 200, 20261116


def bkey(sl: float, tp: float) -> str:
    return f"{sl:g}/{tp:g}"


def cell_edges(atr_pct_burn_in) -> tuple[float, float]:
    """Tercile edges of atr_pct, fixed once on the burn-in fold's taken decisions and never refreshed."""
    v = np.asarray(atr_pct_burn_in, float)
    v = v[np.isfinite(v)]
    return float(np.quantile(v, 1 / 3)), float(np.quantile(v, 2 / 3))


def assign_cells(side, atr_pct, edges) -> np.ndarray:
    t = np.where(np.asarray(atr_pct, float) <= edges[0], 0, np.where(np.asarray(atr_pct, float) <= edges[1], 1, 2))
    return np.array([f"{s}|T{k}" for s, k in zip(side, t)])


def cond_core(dec: pd.DataFrame, keys: list[str], static: str, min_cell: int = COND_MIN_CELL) -> dict:
    """dec: one row per held-fixed decision with columns fold (0-based, 0 = burn-in), cell, and net_<key> for every bracket key.
    Walk-forward: the choice for fold f uses folds < f only. Returns per-fold arrays for the verdict."""
    folds = sorted(dec.fold.unique())
    cells = sorted(dec.cell.unique())
    rows, choices = [], {}
    for f in folds[1:]:
        prior, cur = dec[dec.fold < f], dec[dec.fold == f]
        ch, eligible = {}, True
        for c in cells:
            pc = prior[prior.cell == c]
            if len(pc) < min_cell:
                ch[c], eligible = static, False
                continue
            means = {k: float(pc[f"net_{k}"].mean()) for k in keys}
            ch[c] = max(keys, key=lambda k: (means[k], k == static))     # ties keep static
        choices[int(f)] = {"choice": ch, "eligible": eligible, "n_prior_by_cell": {c: int((prior.cell == c).sum()) for c in cells}}
        net_cond = np.array([cur.iloc[i][f"net_{ch[c]}"] for i, c in enumerate(cur.cell)]) if len(cur) else np.array([])
        bs = {k: float(prior[f"net_{k}"].mean()) for k in keys}
        best_static = max(keys, key=lambda k: (bs[k], k == static))
        rows.append({"fold": int(f), "n": int(len(cur)), "eligible": eligible, "best_static": best_static,
                     "sum_cond": float(net_cond.sum()), "sum_static": float(cur[f"net_{static}"].sum()),
                     "sum_best": float(cur[f"net_{best_static}"].sum())})
    return {"per_fold": rows, "choices": choices}


def cond_verdict(core: dict, draws: int = COND_BOOT_DRAWS, seed: int = COND_SEED) -> dict:
    pf = core["per_fold"]
    n = np.array([r["n"] for r in pf], float)
    sc, ss, sb = (np.array([r[k] for r in pf], float) for k in ("sum_cond", "sum_static", "sum_best"))
    mean = lambda a, w=None: float(a.sum() / n.sum()) if w is None else float(a[w].sum() / n[w].sum())  # noqa: E731
    n_elig = sum(1 for r in pf if r["eligible"])
    d_static, d_best = mean(sc) - mean(ss), mean(sc) - mean(sb)
    fold_d = [(r["sum_cond"] - r["sum_static"]) / r["n"] if r["n"] else None for r in pf]
    wins = sum(1 for x in fold_d if x is not None and x > 0)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(draws):
        ix = rng.integers(0, len(pf), len(pf))
        if n[ix].sum() > 0:
            bs.append((sc[ix].sum() - ss[ix].sum()) / n[ix].sum())
    lo, hi = (float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))) if bs else (None, None)
    if n_elig < COND_MIN_FOLDS_ELIGIBLE or not len(pf):
        call, why = "INDETERMINATE", f"only {n_elig} gradeable folds have >= {COND_MIN_CELL} prior decisions in every cell (floor {COND_MIN_FOLDS_ELIGIBLE})"
    elif d_static < COND_DELTA_R or wins < COND_WINS_FAIL:
        call, why = "FAIL", f"delta vs static {d_static:+.4f} (bar +{COND_DELTA_R}), wins {wins}/{len(pf)} (fail below {COND_WINS_FAIL})"
    elif d_best > 0 and wins >= COND_WINS_PASS and lo is not None and lo > 0:
        call, why = "PASS", f"delta {d_static:+.4f}, vs best-static {d_best:+.4f}, wins {wins}/{len(pf)}, CI lo {lo:+.4f}"
    else:
        call, why = "INDETERMINATE", f"delta {d_static:+.4f}, vs best-static {d_best:+.4f}, wins {wins}/{len(pf)}, CI [{lo}, {hi}]"
    return {"call": call, "why": why, "n_graded_decisions": int(n.sum()), "n_gradeable_folds": len(pf), "n_eligible_folds": n_elig,
            "mean_net_r": {"cond": mean(sc), "static": mean(ss), "best_static": mean(sb)},
            "delta_vs_static": d_static, "delta_vs_best_static": d_best, "fold_delta_vs_static": fold_d, "wins_vs_static": wins,
            "delta_ci95_fold_block": [lo, hi]}


def cond_random_control(dec: pd.DataFrame, keys: list[str], static: str, draws: int = COND_RANDOM_DRAWS, seed: int = COND_SEED) -> dict:
    """Reported, not gating: the same graded decisions, each at a uniformly random bracket from the same set."""
    g = dec[dec.fold >= 1]
    rng = np.random.default_rng(seed + 1)
    mat = np.column_stack([g[f"net_{k}"].to_numpy() for k in keys])
    base = float(g[f"net_{static}"].mean())
    d = [float(mat[np.arange(len(g)), rng.integers(0, len(keys), len(g))].mean() - base) for _ in range(draws)]
    return {"draws": draws, "mean_delta_vs_static": float(np.mean(d)), "p95_delta": float(np.quantile(d, 0.95))}


def cond_decisions(base_preds, tables: dict[str, pd.DataFrame], keys: list[str], static: str) -> tuple[pd.DataFrame, dict]:
    """Held-fixed decision set = the base (static, tau 0.10) policy's taken decisions per fold, looked up in each bracket's table."""
    base_tab = tables[static]
    taken = []
    for fi, (name, test, pl, ps) in enumerate(base_preds):
        if not (len(test) and len(pl)):
            continue
        tk = E.policy(test, pl, ps, BASE_TAU)
        tk["fold"] = fi
        taken.append(tk)
    t = pd.concat(taken, ignore_index=True)
    n0 = len(t)
    t = t.merge(base_tab[["symbol", "ts", "atr_pct"]], on=["symbol", "ts"], how="left")
    t = t.rename(columns={"net_r": f"net_{static}"})
    for k in keys:
        if k == static:
            continue
        tab = tables[k]
        side_net = tab[["symbol", "ts", "net_long", "net_short"]]
        t = t.merge(side_net, on=["symbol", "ts"], how="left")
        t[f"net_{k}"] = np.where(t.side == "long", t.net_long, t.net_short)
        t = t.drop(columns=["net_long", "net_short"])
    need = [f"net_{k}" for k in keys] + ["atr_pct"]
    dropped = int(t[need].isna().any(axis=1).sum())
    t = t.dropna(subset=need).reset_index(drop=True)
    edges = cell_edges(t.loc[t.fold == t.fold.min(), "atr_pct"])
    t["cell"] = assign_cells(t.side, t.atr_pct, edges)
    return t, {"n_taken_base": n0, "n_dropped_missing_in_alt_table": dropped, "atr_pct_edges": list(edges)}


def run_bracket_cond(a, cache, pop_ok, ref_ok, costs, base_sc, base_preds, t0) -> dict:
    keys = [bkey(*b) for b in COND_BRACKETS]
    static = keys[0]
    tables = {static: base_sc}
    for (sl, tp), k in zip(COND_BRACKETS[1:], keys[1:]):
        tables[k] = dev_table(cache, pop_ok, ref_ok, costs, sl, tp)
    dec, meta = cond_decisions(base_preds, tables, keys, static)
    core = cond_core(dec, keys, static)
    v = cond_verdict(core)
    return {"keys": keys, "decision_meta": meta, "core": core, "verdict": v, "random_control": cond_random_control(dec, keys, static)}


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
    if a.lever == "bracket_cond":
        bc = run_bracket_cond(a, cache, pop_ok, ref_ok, costs, base_sc, base_preds, t0)
        v = bc["verdict"]
        verdict = {"PASS": "pass", "FAIL": "fail"}.get(v["call"], "indeterminate")
        note = f"bracket_cond: {v['call']} | {v['why']} | mean net R cond {v['mean_net_r']['cond']:.4f} static {v['mean_net_r']['static']:.4f} " \
               f"best-static {v['mean_net_r']['best_static']:.4f} (graded n {v['n_graded_decisions']}) | dropped {bc['decision_meta']['n_dropped_missing_in_alt_table']}"
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": verdict,
               "population": (f"base c692-01 taken decisions (tau {BASE_TAU}) held fixed on {len(pop_ok)} scorable symbols of the frozen 2e3b-01 population, "
                              f"dev folds only (held-out never read), per-symbol cost stack; bracket chosen per (side x atr_pct tercile) cell on prior folds"),
               "note": note, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "measurement": {**bc, "base": base, "elapsed_s": round(time.time() - t0)}, "n": v["n_graded_decisions"],
               "produced_by": {"tool": "python3 scripts/research/ml_entry_cost_levers.py run --lever bracket_cond", "where": a.where}}
        (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
        (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
        print(note, flush=True)
        return 0
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
    _self_test_cond()
    print("self-test ok")
    return 0


def _self_test_cond() -> None:
    keys = [bkey(*b) for b in COND_BRACKETS]
    st = keys[0]
    rng = np.random.default_rng(1)

    def mk(n_per_fold, effect, folds=8):
        rows = []
        for f in range(folds):
            for _ in range(n_per_fold):
                c = rng.choice(["long|T0", "long|T1", "long|T2", "short|T0", "short|T1", "short|T2"])
                base = rng.normal(-0.05, 1.0)
                # cell A (long|T2) is better at 4/6 by +effect, cell B (short|T0) worse at 4/6; wide arm equal elsewhere
                shift = effect if c == "long|T2" else (-effect if c == "short|T0" else 0.0)
                rows.append({"fold": f, "cell": c, f"net_{keys[0]}": base, f"net_{keys[1]}": base + shift / 2, f"net_{keys[2]}": base + shift})
        return pd.DataFrame(rows)

    # planted positive: state dependence (cell-wise sign flip) with a big effect -> PASS; the static wide bracket alone cannot get it
    pos = mk(1600, 0.6)
    v = cond_verdict(cond_core(pos, keys, st))
    assert v["call"] == "PASS" and v["delta_vs_static"] >= COND_DELTA_R and v["delta_vs_best_static"] > 0, v
    # planted null: all brackets identical in every cell -> delta exactly 0 -> FAIL
    null = mk(1600, 0.0)
    v = cond_verdict(cond_core(null, keys, st))
    assert v["call"] == "FAIL" and abs(v["delta_vs_static"]) < 1e-9, v
    # thin: cells never reach COND_MIN_CELL prior decisions in >= 5 folds -> INDETERMINATE
    v = cond_verdict(cond_core(mk(80, 0.6), keys, st))
    assert v["call"] == "INDETERMINATE" and v["n_eligible_folds"] < COND_MIN_FOLDS_ELIGIBLE, v
    # no look-ahead: corrupting the graded fold's own labels must not change the choices made for that fold
    c1 = cond_core(pos, keys, st)["choices"]
    bad = pos.copy()
    bad.loc[bad.fold == 7, f"net_{keys[1]}"] += 100.0
    assert cond_core(bad, keys, st)["choices"][7] == c1[7]
    # fold 0 is burn-in: never graded
    assert all(r["fold"] >= 1 for r in cond_core(pos, keys, st)["per_fold"])
    e = cell_edges(np.arange(300))
    assert 98 < e[0] < 101 and 198 < e[1] < 201
    assert cond_random_control(pos, keys, st)["draws"] == COND_RANDOM_DRAWS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--lever", choices=["tau", "bracket", "bracket_cond"])
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
        ap.error("run --lever tau|bracket|bracket_cond --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
