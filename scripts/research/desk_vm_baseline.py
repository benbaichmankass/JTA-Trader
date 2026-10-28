#!/usr/bin/env python3
# wiring: library - imported by desk_edge_ceiling / desk_edge_1m (row scorers); the replay driver has its own in-engine form.
"""DESK-S3-VOL-MATCHED-BASELINE -- COMPANION statistics to the registered e535 S3. They never replace it.

WHY. S3 = (picks' net R) - (random entries' net R, drawn from the whole fold). Net R = gross R - cost_r, and cost_r is a
fixed bps stack divided by the stop distance, so it is SMALL in R when the bracket is wide in price, i.e. when ATR% is
high. A rule that merely picks high-ATR% moments therefore earns S3 from cheaper-cost-in-R alone, with no timing.
Measured 2026-10-27 (DESK-EDGE-PROGRAM, doc 4.6): a model-free ATR% rule scores S3 +0.285 at 5-min holds with gross
R +0.016 (comms/research/desk_edge/ceiling-1m/vol-rule-mechanism.json).

TWO COMPANIONS (names are fixed; both are reported BESIDE S3, neither enters a decision rule):

  gross_excess  picks' GROSS R (net_r + cost_r, before cost) minus the random baseline's gross R  -- is there timing at all?
                (`gross_excess_matched`: the same against the volatility-matched cell's gross R)
  S3_matched    picks' net R minus the mean net R of random entries drawn from the SAME symbol, the SAME fold (and, for
                the row scorers, the same side and hold) and the SAME ATR%-decile as the pick. ATR% = ATR/close at the
                decision bar; deciles are per symbol over the population handed in.

Row scorers (`annotate`): the population IS the random-time population (the hourly / per-bar grid), so the matched
baseline of a pick is the mean of every action in its cell (symbol, side, hold, fold, decile). The cell includes the
pick itself; with the cell sizes of the committed builds (hundreds to thousands) the effect on the mean is < 1/n.
The same cell is what desk_edge_info.vm_labels uses; the two agree by construction.
The replay driver (desk_gen_replay_driver.score) draws the matched baseline by simulation from the same decile pool.
"""
from __future__ import annotations

import collections
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

N_DECILES = 10


def decile_edges(values: Sequence[float], n: int = N_DECILES) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    return np.quantile(v, np.linspace(0, 1, n + 1)[1:-1]) if len(v) else np.array([])


def decile_of(edges: np.ndarray, x: float) -> int:
    return int(np.searchsorted(edges, x)) if np.isfinite(x) else -1


def annotate(rows: List[dict], atr_pct: Callable[[dict], float], n: int = N_DECILES) -> List[dict]:
    """Adds, in place, to each row (needs symbol, side, hold|geom, fold, net_r, cost_r): vol_dec, y_vm (net minus the
    cell's mean net), g_vm (gross minus the cell's mean gross). A row with no ATR% (NaN) gets y_vm = g_vm = None.
    Cells never span symbols, folds, sides or holds/geometries."""
    per_sym: Dict[str, Dict[Any, float]] = collections.defaultdict(dict)
    for r in rows:
        per_sym[r["symbol"]][(r.get("cutoff"), r["symbol"])] = float(atr_pct(r))
    edges = {s: decile_edges(list(m.values()), n) for s, m in per_sym.items()}
    cell: Dict[tuple, List[int]] = collections.defaultdict(list)
    for j, r in enumerate(rows):
        a = float(atr_pct(r))
        r["vol_dec"] = decile_of(edges[r["symbol"]], a)
        if r["vol_dec"] < 0:
            r["y_vm"] = r["g_vm"] = None
            continue
        cell[(r["symbol"], r["side"], r.get("hold", r.get("geom")), r["fold"], r["vol_dec"])].append(j)
    for ix in cell.values():
        mn = float(np.mean([rows[j]["net_r"] for j in ix]))
        mg = float(np.mean([rows[j]["net_r"] + rows[j]["cost_r"] for j in ix]))
        for j in ix:
            rows[j]["y_vm"] = rows[j]["net_r"] - mn
            rows[j]["g_vm"] = rows[j]["net_r"] + rows[j]["cost_r"] - mg
    return rows


def companions(rows: List[dict], picks: Sequence[int], cluster_stats: Callable[..., Dict[str, Any]],
               cluster_ci: Optional[Callable[..., Any]] = None, alpha: float = 0.05) -> Dict[str, Any]:
    """S3 (the registered statistic, y), gross_excess, gross_excess_matched and S3_matched over the picks, each with its n
    and weekly-cluster 95% CI. `rows` must be annotate()d. gross_excess = pick gross minus the whole-population gross (the
    brief's definition: S3 with cost removed); gross_excess_matched = pick gross minus its cell's gross (g_vm).
    """
    def stat(fn: Callable[[dict], Optional[float]]) -> Dict[str, Any]:
        sr = [{"week": rows[j]["week"], "net_r": rows[j]["net_r"], "days": rows[j]["days"], "diff": fn(rows[j])} for j in picks]
        sr = [x for x in sr if x["diff"] is not None]
        if not sr:
            return {"n": 0, "mean": None, "ci95": None}
        st = cluster_stats(sr, draws=3000)
        out = {"n": st["n"], "weeks": st["weeks"], "mean": st.get("paired_diff_vs_random"), "ci95": st.get("paired_diff_ci95")}
        if cluster_ci is not None:
            out["ci_corrected"] = list(cluster_ci(sr, "diff", alpha, draws=3000))
        return out

    allg = float(np.mean([r["net_r"] + r["cost_r"] for r in rows])) if rows else float("nan")
    return {"S3": stat(lambda r: r.get("y")),
            "gross_excess": stat(lambda r: r["net_r"] + r["cost_r"] - allg),
            "gross_excess_matched": stat(lambda r: r.get("g_vm")),
            "S3_matched": stat(lambda r: r.get("y_vm")),
            "population_rows": len(rows), "picks": len(picks)}
