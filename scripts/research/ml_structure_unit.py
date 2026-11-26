#!/usr/bin/env python3
# wiring: scripts/research/ml_entry_levers.py `run --unit 5e01-*` (the ml_entry_v2_run.py `levers` mode reaches it); units RQ-20261101-5e01-09/-10/-11 (row ML-STRUCTURE-UNIT-RUNNER)
"""Structure-based SL+TP arm on the ML entry walk-forward (row ML-STRUCTURE-UNIT-RUNNER, units RQ-20261101-5e01-09/-10/-11).

WHAT IT DOES. The c692 fold models of the ML entry harness (``ml_entry_levers.base_members``, the frozen v1 base) pick the trades exactly as
the declared arm does (``E.policy``, same tau, same one-position-per-symbol rule). The SAME decisions (symbol, decision bar, side) are then
re-scored with the structure bracket of ``ml_structure_bracket.label_cell_structure`` at pivot N in {3, 5, 8}. ENTRIES ARE FIXED: only the
source of the SL and TP changes, so the A-vs-S difference is paired per trade.

THE RULE (registered in the units, RULE-STRUCTURE-EXITS-V1; read it there, this file implements it and decides nothing):
  * the pivot N is the ONLY dev-selected parameter: chosen on 5 of 6 equal calendar bins of entry time, scored on the held bin;
  * PASS_BETTER: mean net R of S exceeds A, the paired week-bootstrap 95% lower bound of (S - A) > 0, in >= 4 of 6 bins, and S's
    mean net R beats the 95th percentile of the 100 matched random-exit controls (R4); n >= 39 else INDETERMINATE;
  * PASS_NONINFERIOR: lower bound of (S - A) > -0.05 R/trade, R4 holds, and R2 (max drawdown or worst-5% weekly outcome cut >= 15%);
  * FAIL otherwise; INDETERMINATE if n < 39, S never differs from A, or a control / detector input is missing.
The 6 bins are regrouped from the walk-forward's OUT-OF-SAMPLE scored trades (each trade came from a model that never saw it), so they are
equal spans of calendar time over the trades, not 6 fresh model fits. Every count here is over the stated population and a read-state is
printed beside every nullable number.

Random-exit control: for each taken trade, exit at the close of a uniformly random bar j in 1..H (H = 24), the declared risk unit, the same
cost stack (``E._cost_r``); 100 seeded draws; one control mean per draw.

Known limits, stated so nobody reads more into the number: (1) one seed (the first of ``SEEDS``) decides the verdict, the other seeds'
means are reported beside it; (2) the harness bracket is the c692 base (SL 2.0 ATR, TP 3.0 ATR) -- the units' prose says TP 1.5R, which is a
different declared exit; (3) positions block on the DECLARED exit's bars, so the structure arm is scored on the declared arm's decisions
rather than on the decisions its own exits would free up.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as E  # noqa: E402
import ml_structure_bracket as SB  # noqa: E402

PIVOTS = (3, 5, 8)
N_BINS = 6
MIN_N = 39
DRAWS = 100
BOOT = 2000
SEED = 20261101
NONINFERIOR = -0.05
STRUCT_COLS = ("gross", "net", "cost", "reason", "bars", "risk_r_unit", "fallback")


# ------------------------------------------------------------------------------------------ structure relabel
def structure_labels(tab: pd.DataFrame, cache: Path, pivot_n: int, hole_safe: bool = True) -> pd.DataFrame:
    """The structure-bracket labels for pivot ``pivot_n`` reindexed onto the table's rows (columns ``<col>_long|short``).
    A row absent from the labelled frame is a keying error and refuses; a NaN net is an unobservable outcome (a data hole)."""
    parts = []
    for sym in tab["symbol"].unique():
        raw = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        lab = SB.label_cell_structure(E.regrid_hourly(raw) if hole_safe else raw, pivot_n)
        lab["symbol"] = sym
        parts.append(lab)
    lab = pd.concat(parts, ignore_index=True)
    cols = [f"{c}_{s}" for c in STRUCT_COLS for s in ("long", "short")]
    got = lab.set_index(pd.MultiIndex.from_frame(lab[["symbol", "i"]]))[cols]
    tkey = pd.MultiIndex.from_frame(tab[["symbol", "i"]])
    if not np.asarray(tkey.isin(got.index)).all():
        raise RuntimeError("structure relabel left rows without labels (keying error, not an unobservable outcome)")
    return got.reindex(tkey)


def rescore(trades: pd.DataFrame, tab: pd.DataFrame, lab: pd.DataFrame) -> pd.DataFrame:
    """The declared arm's decisions re-scored with ``lab``: same (symbol, ts, side), net/gross/cost/reason from the structure labels."""
    key = pd.MultiIndex.from_frame(tab[["symbol", "ts"]])
    pos = pd.Series(np.arange(len(tab)), index=key)
    if pos.index.duplicated().any():
        raise RuntimeError("table has duplicate (symbol, ts) rows: cannot join decisions to labels")
    ix = pos.reindex(pd.MultiIndex.from_frame(trades[["symbol", "ts"]])).to_numpy()
    if np.isnan(ix).any():
        raise RuntimeError("a taken decision is missing from the table")
    ix = ix.astype(int)
    out = trades.copy()
    for new, old in (("net_r", "net"), ("gross_r", "gross"), ("cost_r", "cost"), ("reason", "reason")):
        out[new] = [lab[f"{old}_{s}"].to_numpy()[i] for s, i in zip(trades["side"], ix)]
    out["fallback"] = [lab[f"fallback_{s}"].to_numpy()[i] for s, i in zip(trades["side"], ix)]
    return out


# ------------------------------------------------------------------------------------------ controls
def random_exit_controls(trades: pd.DataFrame, tab: pd.DataFrame, cache: Path, draws: int = DRAWS, seed: int = SEED,
                         hole_safe: bool = True) -> np.ndarray:
    """One mean net R per draw: every taken trade exits at the close of a uniformly random bar j in 1..H, at the declared risk unit."""
    H = E.HORIZON_H
    key = pd.MultiIndex.from_frame(tab[["symbol", "ts"]])
    pos = pd.Series(np.arange(len(tab)), index=key).reindex(pd.MultiIndex.from_frame(trades[["symbol", "ts"]])).to_numpy().astype(int)
    idx = tab["i"].to_numpy()[pos]
    syms = trades["symbol"].to_numpy()
    side = np.where(trades["side"].to_numpy() == "long", 1, -1)
    entry, risk, closes, t_entry, t_ns_all = [], [], [], [], []
    for sym in pd.unique(syms):
        m = syms == sym
        raw = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        df = E.regrid_hourly(raw) if hole_safe else raw
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
        atr = pd.Series(tr).rolling(E.ATR_N, min_periods=E.ATR_N).mean().to_numpy()
        t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
        i = idx[m]
        win = i[:, None] + np.arange(1, H + 1)[None, :]
        entry.append((np.flatnonzero(m), o[i + 1]))
        risk.append((np.flatnonzero(m), E.SL_ATR * atr[i]))
        closes.append((np.flatnonzero(m), c[win]))
        t_entry.append((np.flatnonzero(m), t_ns[i + 1] / 1e9))
        t_ns_all.append((np.flatnonzero(m), t_ns[win] / 1e9))

    def put(parts, width=None):
        n = len(trades)
        arr = np.empty((n, width)) if width else np.empty(n)
        for ix, v in parts:
            arr[ix] = v
        return arr

    entry, risk, t_entry = put(entry), put(risk), put(t_entry)
    closes, t_win = put(closes, H), put(t_ns_all, H)
    rng = np.random.default_rng(seed)
    n = len(trades)
    means = np.empty(draws)
    for d in range(draws):
        j = rng.integers(0, H, size=n)
        px = closes[np.arange(n), j]
        gross = side * (px - entry) / risk
        fee, slip, fund = E._cost_r(entry, px, risk, t_entry, t_win[np.arange(n), j] + 3600.0)
        means[d] = float(np.nanmean(gross - fee - slip - fund))
    return means


# ------------------------------------------------------------------------------------------ the rule
def _bins(ts: pd.Series, n: int = N_BINS) -> np.ndarray:
    t = pd.to_datetime(ts, utc=True).astype("int64").to_numpy()
    edges = np.linspace(t.min(), t.max() + 1, n + 1)
    return np.clip(np.searchsorted(edges, t, side="right") - 1, 0, n - 1)


def week_bootstrap_lb(diff: np.ndarray, weeks: np.ndarray, draws: int = BOOT, seed: int = SEED) -> float | None:
    """Lower end of the paired 95% interval of the mean per-trade difference, resampling WEEKS (the cluster) with replacement."""
    if len(diff) == 0:
        return None
    uw, inv = np.unique(weeks, return_inverse=True)
    sums = np.bincount(inv, weights=diff, minlength=len(uw))
    cnt = np.bincount(inv, minlength=len(uw)).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(uw), size=(draws, len(uw)))
    return float(np.percentile(sums[pick].sum(1) / cnt[pick].sum(1), 2.5))


def _dd(net: np.ndarray) -> float:
    c = np.cumsum(net)
    return float(np.max(np.maximum.accumulate(np.r_[0.0, c])[1:] - c)) if len(c) else 0.0


def _weekly_q5(ts: pd.Series, net: np.ndarray) -> float:
    w = pd.Series(net).groupby(pd.to_datetime(ts, utc=True).dt.to_period("W").astype(str).to_numpy()).sum()
    return float(np.percentile(w.to_numpy(), 5)) if len(w) else 0.0


def judge_structure(a: pd.DataFrame, per_pivot: dict, controls: np.ndarray) -> dict:
    """``a`` = the declared arm's trades (sorted as ``per_pivot[N]``'s rows); ``per_pivot[N]`` = the same decisions scored at pivot N."""
    n = len(a)
    res: dict = {"n": n, "pivots": list(per_pivot), "read_state": "ok"}
    if n < MIN_N:
        return {**res, "verdict": "INDETERMINATE", "why": f"n {n} < {MIN_N}", "read_state": "n_too_small"}
    if not len(controls):
        return {**res, "verdict": "INDETERMINATE", "why": "random-exit controls missing", "read_state": "controls_missing"}
    bins = _bins(a["ts"])
    d = {p: per_pivot[p]["net_r"].to_numpy() - a["net_r"].to_numpy() for p in per_pivot}
    chosen = np.empty(n)
    picked = {}
    for b in range(N_BINS):                                   # leave-one-bin-out: N chosen on the other bins, scored on this one
        tr, te = bins != b, bins == b
        if not te.any():
            picked[b] = None
            continue
        best = max(per_pivot, key=lambda p: (float(d[p][tr].mean()) if tr.any() else -np.inf, -p))
        picked[b] = int(best)
        chosen[te] = per_pivot[best]["net_r"].to_numpy()[te]
    s_net, a_net = chosen, a["net_r"].to_numpy()
    diff = s_net - a_net
    wk = pd.to_datetime(a["ts"], utc=True).dt.to_period("W").astype(str).to_numpy()
    lb = week_bootstrap_lb(diff, wk)
    bins_better = int(sum(1 for b in range(N_BINS) if (bins == b).any() and diff[bins == b].mean() > 0))
    p95 = float(np.percentile(controls, 95))
    r4 = bool(s_net.mean() > p95)
    dd_a, dd_s = _dd(a_net), _dd(s_net)
    q_a, q_s = _weekly_q5(a["ts"], a_net), _weekly_q5(a["ts"], s_net)
    cut_dd = (1 - dd_s / dd_a) if dd_a > 0 else 0.0
    cut_q = (1 - q_s / q_a) if q_a < 0 else 0.0
    r2 = bool(max(cut_dd, cut_q) >= 0.15)
    res.update({"mean_net_r_A": float(a_net.mean()), "mean_net_r_S": float(s_net.mean()), "mean_diff": float(diff.mean()),
                "week_bootstrap_lb": lb, "bins_S_better": bins_better, "pivot_chosen_per_bin": picked,
                "control_p95_mean_net_r": p95, "control_mean": float(np.mean(controls)), "R4": r4, "R2": r2,
                "maxdd_A": dd_a, "maxdd_S": dd_s, "weekly_q5_A": q_a, "weekly_q5_S": q_s,
                "fallback_share": {int(p): float(per_pivot[p]["fallback"].mean()) for p in per_pivot}})
    if not np.any(diff != 0):
        return {**res, "verdict": "INDETERMINATE", "why": "S never differs from A"}
    if s_net.mean() > a_net.mean() and lb is not None and lb > 0 and bins_better >= 4 and r4:
        res["verdict"] = "PASS_BETTER"
    elif lb is not None and lb > NONINFERIOR and r4 and r2:
        res["verdict"] = "PASS_NONINFERIOR"
    else:
        res["verdict"] = "FAIL"
    return res


# ------------------------------------------------------------------------------------------ the unit
def score_structure(base_trades: pd.DataFrame, tab: pd.DataFrame, cache: Path, draws: int = DRAWS) -> dict:
    """Pure over its inputs (the declared arm's trades, the table, the kline cache): labels, rescore, controls, verdict."""
    a = base_trades.sort_values(["ts", "symbol"]).reset_index(drop=True)
    per = {p: rescore(a, tab, structure_labels(tab, cache, p)) for p in PIVOTS}
    controls = random_exit_controls(a, tab, cache, draws)
    return judge_structure(a, per, controls)


def structure_unit(tab: pd.DataFrame, out: Path, n_jobs: int, cache: Path, unit: str = "5e01") -> dict:
    import ml_entry_levers as L  # noqa: PLC0415 -- late: ml_entry_levers dispatches to this module

    brackets = [(E.SL_ATR, E.TP_ATR)]
    tab, dropped = L.drop_unobservable(tab, cache, brackets)
    for p in PIVOTS:                                   # a structure NaN is unobservable too: drop it from EVERY arm, count it
        m = structure_labels(tab, cache, p)[["net_long", "net_short"]].isna().any(axis=1).to_numpy()
        if m.any():
            tab = tab.loc[~m].reset_index(drop=True)
            dropped["n_dropped"] += int(m.sum())
    mem = L.base_members(tab, out, n_jobs)
    res = {"unit": unit, "sealed_windows_read": 0, "unobservable_rows_dropped": dropped, "per_seed": {}}
    for k, sd in enumerate(L.SEEDS):
        trades = L.run_arm(L.fold_frames(tab, mem[sd]), mem[sd])
        r = score_structure(trades, tab, cache)
        res["per_seed"][str(sd)] = r
        print("seed", sd, r["verdict"], flush=True)
        if k == 0:
            res["verdict_seed"] = str(sd)
            res["verdict"] = r["verdict"]
    res["result"] = f"{res['verdict']} (first seed decides; other seeds in per_seed)"
    return res
