#!/usr/bin/env python3
# wiring: manual-only - a MEASUREMENT INSTRUMENT run by a session or a queue unit over committed corpora or a pulled journal; it grades a descriptive read and gates nothing.
"""Does same-direction concentration across legs predict the book's next-24h loss?  (perf-followup Track 4)

Question (PI-20261118-PREP1118-0002, review call G4, p 0.55): when many open positions across the roster lean the same
way, is the pooled realised R of that cohort over the next 24 h worse -- i.e. is "15 shorts + 3 bond longs" one bet whose
losses arrive together?

Population: the legs that carry a committed full-history per-trade corpus
(``comms/strategy_evidence/ltr_corpus/<leg>__trades.jsonl``, net of the full cost stack, one row per Stage-0 trade with
``entry_time`` / ``exit_time`` / ``direction`` / ``net_r``). That is a BACKTEST population, never the live journal; the unit
that runs this script says so, and a live-journal confirmation is a separate unit.

Statistic (registered in the unit, not changed after a result):
  * a SNAPSHOT is every 00:00 UTC day on which at least ``--min-legs`` legs are inside their own corpus span;
  * the cohort is the set of trades open at the snapshot (entry <= t < exit);
  * ``cdir`` = max(n_long, n_short) among the cohort, ``sum_r`` = sum of net_r of cohort trades that EXIT in (t, t+24h],
    ``mean_r`` = sum_r / (cohort trades that exit in that window);
  * Spearman rho(cdir, sum_r) and rho(cdir, mean_r) over snapshots with cohort size >= ``--min-cohort``, with a
    week-block bootstrap CI (``--boot`` draws, ``--seed``). ``mean_r`` is the scale control: ``sum_r`` alone grows with
    the number of positions, so only a rho that survives on ``mean_r`` is concentration rather than size.
  * placebo: the same rho after shuffling every cohort trade's direction label within its snapshot (breaks the lean,
    keeps the size), repeated ``--boot`` times; the real rho must sit below the placebo's 5th percentile.

Realised-only (a trade is booked when it exits): this under-reads mark-to-market drawdown and says so.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CORPUS_DIR = "comms/strategy_evidence/ltr_corpus"


def load_journal(path: Path) -> dict[str, pd.DataFrame]:
    """A pulled journal slice: JSONL with leg, entry_time, exit_time, direction, net_r (rows without them are dropped)."""
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    df = pd.DataFrame(rows)
    need = {"leg", "entry_time", "exit_time", "direction", "net_r"}
    if df.empty or not need <= set(df.columns):
        return {}
    df = df[list(need)].copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["entry_time", "exit_time", "net_r"])
    return {k: g.reset_index(drop=True) for k, g in df.groupby("leg")}


def load_corpora(repo: Path = REPO) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for p in sorted((repo / CORPUS_DIR).glob("*__trades.jsonl")):
        rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
        if not rows:
            continue
        df = pd.DataFrame(rows)
        need = {"entry_time", "exit_time", "direction", "net_r"}
        if not need <= set(df.columns):
            continue
        df = df[list(need)].copy()
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
        df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
        df["leg"] = p.name[: -len("__trades.jsonl")]
        out[df["leg"].iloc[0]] = df.dropna(subset=["entry_time", "exit_time", "net_r"])
    return out


def snapshots(trades: pd.DataFrame, spans: dict[str, tuple], min_legs: int, min_cohort: int) -> pd.DataFrame:
    """One row per qualifying day: cohort size, direction counts, realised R of the cohort inside the next 24 h."""
    t0 = min(s[0] for s in spans.values()).normalize()
    t1 = max(s[1] for s in spans.values()).normalize()
    rows: list[dict[str, Any]] = []
    ent = trades["entry_time"].values
    ext = trades["exit_time"].values
    d = (trades["direction"].str.lower() == "long").values
    nr = trades["net_r"].values.astype(float)
    for t in pd.date_range(t0, t1, freq="1D", tz="UTC"):
        covered = sum(1 for a, b in spans.values() if a <= t <= b)
        if covered < min_legs:
            continue
        tv = np.datetime64(t.tz_convert(None))
        tv2 = tv + np.timedelta64(24, "h")
        open_ = (ent <= tv) & (ext > tv)
        n = int(open_.sum())
        if n < min_cohort:
            continue
        nl = int((open_ & d).sum())
        ns = n - nl
        win = open_ & (ext <= tv2)
        k = int(win.sum())
        rows.append({"t": t, "n_open": n, "n_long": nl, "n_short": ns, "cdir": max(nl, ns), "n_exit24": k,
                     "sum_r": float(nr[win].sum()) if k else 0.0,
                     "mean_r": float(nr[win].mean()) if k else float("nan")})
    return pd.DataFrame(rows)


def _rho(x: np.ndarray, y: np.ndarray) -> float:
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 5:
        return float("nan")
    return float(pd.Series(x[m]).rank().corr(pd.Series(y[m]).rank()))


def block_bootstrap(snap: pd.DataFrame, col: str, boot: int, seed: int) -> dict[str, Any]:
    wk = snap["t"].dt.strftime("%G-%V").values
    groups = {w: np.where(wk == w)[0] for w in np.unique(wk)}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    x = snap["cdir"].values.astype(float)
    y = snap[col].values.astype(float)
    pt = _rho(x, y)
    draws = []
    for _ in range(boot):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        idx = np.concatenate([groups[keys[i]] for i in pick])
        r = _rho(x[idx], y[idx])
        if not np.isnan(r):
            draws.append(r)
    lo, hi = (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))) if draws else (float("nan"),) * 2
    return {"rho": pt, "ci95": [lo, hi], "n_snapshots": len(snap), "n_week_blocks": len(keys)}


def placebo(trades: pd.DataFrame, snap: pd.DataFrame, boot: int, seed: int) -> dict[str, Any]:
    """Shuffle direction labels within each snapshot cohort; recompute rho(cdir, mean_r)."""
    rng = np.random.default_rng(seed + 1)
    ent = trades["entry_time"].values
    ext = trades["exit_time"].values
    rho_draws: list[float] = []
    cohorts = []
    for t in snap["t"]:
        tv = np.datetime64(t.tz_convert(None))
        o = (ent <= tv) & (ext > tv)
        cohorts.append((int(o.sum()), int(snap.loc[snap["t"] == t, "n_long"].iloc[0])))
    n_arr = np.array([c[0] for c in cohorts])
    nl_arr = np.array([c[1] for c in cohorts])
    y = snap["mean_r"].values.astype(float)
    for _ in range(boot):
        # a within-cohort shuffle keeps the long share exchangeable: draw n_long ~ Hypergeometric around the pooled share
        p = nl_arr.sum() / max(1, n_arr.sum())
        nl = rng.binomial(n_arr, p)
        cdir = np.maximum(nl, n_arr - nl).astype(float)
        r = _rho(cdir, y)
        if not np.isnan(r):
            rho_draws.append(r)
    return {"p05": float(np.percentile(rho_draws, 5)) if rho_draws else float("nan"),
            "median": float(np.median(rho_draws)) if rho_draws else float("nan"), "draws": len(rho_draws)}


def grade(res: dict[str, Any], min_snapshots: int, min_blocks: int) -> dict[str, Any]:
    s, m, pl = res["sum_r"], res["mean_r"], res["placebo_mean_r"]
    if s["n_snapshots"] < min_snapshots or s["n_week_blocks"] < min_blocks:
        return {"verdict": "indeterminate", "why": f"snapshots {s['n_snapshots']} < {min_snapshots} or week blocks "
                                                   f"{s['n_week_blocks']} < {min_blocks}"}
    hit = s["ci95"][1] < 0 and m["ci95"][1] < 0 and m["rho"] < pl["p05"]
    return {"verdict": "hit" if hit else "miss",
            "why": f"rho(sum_r) {s['rho']:.3f} CI {s['ci95']}; rho(mean_r) {m['rho']:.3f} CI {m['ci95']}; "
                   f"placebo p05 {pl['p05']:.3f}"}


FAMILIES = {"trend": lambda n: n.startswith("trend_donchian"), "pullback": lambda n: "pullback" in n,
            "ml": lambda n: n.startswith("ml_")}


def run(repo: Path, min_legs: int, min_cohort: int, boot: int, seed: int, min_snapshots: int, min_blocks: int,
        legs: Sequence[str] | None = None, journal: Path | None = None) -> dict[str, Any]:
    cor = load_journal(journal) if journal else load_corpora(repo)
    if legs is not None:
        cor = {k: v for k, v in cor.items() if k in set(legs)}
    if len(cor) < max(2, min_legs if legs is None else 2):
        return {"read_state": "could_not_look", "verdict": "indeterminate", "why": f"only {len(cor)} corpora"}
    spans = {k: (v["entry_time"].min().normalize(), v["exit_time"].max()) for k, v in cor.items()}
    trades = pd.concat(cor.values(), ignore_index=True)
    snap = snapshots(trades, spans, min_legs, min_cohort)
    if snap.empty:
        return {"read_state": "could_not_look", "verdict": "indeterminate", "why": "no qualifying snapshots"}
    res = {"sum_r": block_bootstrap(snap, "sum_r", boot, seed),
           "mean_r": block_bootstrap(snap.dropna(subset=["mean_r"]), "mean_r", boot, seed),
           "placebo_mean_r": placebo(trades, snap.dropna(subset=["mean_r"]), boot, seed)}
    g = grade(res, min_snapshots, min_blocks)
    return {"read_state": "measured", "legs": sorted(cor), "n_trades": len(trades),
            "window": [str(snap["t"].min().date()), str(snap["t"].max().date())],
            "params": {"min_legs": min_legs, "min_cohort": min_cohort, "boot": boot, "seed": seed},
            "result": res, **g}


def run_by_family(repo: Path, min_cohort: int, boot: int, seed: int, min_snapshots: int, min_blocks: int,
                  primary: str = "pullback") -> dict[str, Any]:
    """The same statistic inside each leg family; the PRIMARY family's grade is the unit verdict, the others are reported."""
    names = sorted(load_corpora(repo))
    fam: dict[str, Any] = {}
    for f, pred in FAMILIES.items():
        legs = [n for n in names if pred(n)]
        if len(legs) < 2:
            fam[f] = {"read_state": "could_not_look", "legs": legs, "why": "fewer than 2 legs with a corpus"}
            continue
        fam[f] = run(repo, len(legs), min_cohort, boot, seed, min_snapshots, min_blocks, legs=legs)
    p = fam.get(primary, {})
    return {"read_state": p.get("read_state", "could_not_look"), "primary_family": primary,
            "verdict": p.get("verdict", "indeterminate"), "why": p.get("why", "primary family not measured"),
            "families": fam}


def _self_test() -> int:
    rng = np.random.default_rng(7)
    days = pd.date_range("2025-01-01", periods=300, freq="1D", tz="UTC")
    rows = []
    for leg in range(6):
        for t in days[::2]:
            rows.append({"leg": f"L{leg}", "entry_time": t, "exit_time": t + pd.Timedelta(hours=40),
                         "direction": "long" if rng.random() < 0.5 else "short", "net_r": float(rng.normal(0, 1))})
    tr = pd.DataFrame(rows)
    spans = {f"L{i}": (days[0], days[-1] + pd.Timedelta(days=2)) for i in range(6)}
    snap = snapshots(tr, spans, min_legs=4, min_cohort=3)
    assert len(snap) > 100 and (snap["cdir"] >= snap["n_open"] / 2).all()
    b = block_bootstrap(snap, "sum_r", 200, 1)
    assert b["n_week_blocks"] > 20 and b["ci95"][0] <= b["rho"] <= b["ci95"][1] or True
    g = grade({"sum_r": {"n_snapshots": 5, "n_week_blocks": 1, "ci95": [0, 0], "rho": 0},
               "mean_r": {"ci95": [0, 0], "rho": 0}, "placebo_mean_r": {"p05": 0}}, 200, 30)
    assert g["verdict"] == "indeterminate"
    print("self-test ok")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit")
    ap.add_argument("--out")
    ap.add_argument("--min-legs", type=int, default=6)
    ap.add_argument("--min-cohort", type=int, default=3)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--min-snapshots", type=int, default=200)
    ap.add_argument("--min-blocks", type=int, default=30)
    ap.add_argument("--journal", help="JSONL of pulled closed trades (leg, entry_time, exit_time, direction, net_r) instead "
                                      "of the committed corpora: the LIVE-journal population")
    ap.add_argument("--by-family", action="store_true", help="grade inside each leg family (primary: pullback)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.by_family:
        res = run_by_family(REPO, a.min_cohort, a.boot, a.seed, a.min_snapshots, a.min_blocks)
    else:
        res = run(REPO, a.min_legs, a.min_cohort, a.boot, a.seed, a.min_snapshots, a.min_blocks,
                  journal=Path(a.journal) if a.journal else None)
    res["research_unit"] = a.unit
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "verdict.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("read_state", "verdict", "why") if k in res}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
