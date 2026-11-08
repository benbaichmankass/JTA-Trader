#!/usr/bin/env python3
# wiring: research/queue/RQ-20261108-98e3-23.yaml (runner unit); lane ML-ENTRY-EQ-STRUCTURE-RETEST; drift-remediation SKILL step 2
"""Decompose the served ml_entry REPLAY grade against the live book (drift-remediation: "replay says negative, live book is positive").

The replay grade comms/research/ml_entry_grade/42473814600 reads -0.13 R net (n=317, 48 symbols, both sides, fixed 2/3 ATR bracket,
window 2026-10-25..2026-11-07; longs -0.90 R n=51, shorts +0.02 R n=266). bybit_2's live record is 5 closed trades since 2026-11-02, all
shorts, +$4.93, 3 winners. NOT a demotion signal. This job re-cuts the SAME served-model replay window five ways and prints one verdict
line per cut, each by a rule registered BEFORE the run (research/queue/RQ-20261108-98e3-23.yaml):

  side        long vs short                                       SIDE-DRIVER if n_long >= 30 and long mean <= -0.30 and short mean >= -0.05
  population  the live book's symbols (bybit_2 roster, both sides) POPULATION-DRIVER if live-pop n >= 30 and its mean >= 0 and the pool mean < 0
  exit        the live structure exit pivot=5;sl_only vs bracket  EXIT-DRIVER if (structure mean - bracket mean) >= +0.05 and structure mean >= 0
  decay       first 7 days vs last 7 days of the window           DECAY if both halves n >= 100 and (last - first) <= -0.10
  noise       live 5 trades vs replay short win-rate              NOISE-COMPATIBLE if P(>= 3 wins of 5 | replay short win share) >= 0.05

The replay uses the SAME frozen served boosters, tau, table and cost stack as the grade (ml_decision_entry: fee 11 bps + slippage + funding).
Declared gaps, not hidden: the live leg also runs a first-passage TP revision (extend-only) that this replay does not model; the structure
arm replaces only the stop path (SL-only, tighten-only) with the live replay function.

    python3 scripts/research/ml_entry_replay_decompose.py run --cache /tmp/ml_entry_klines --out DIR --unit RQ-... [--run-date 2026-11-08]
    python3 scripts/research/ml_entry_replay_decompose.py --self-test
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

WINDOW_START = "2026-10-25"
WINDOW_END = "2026-11-07"                       # inclusive; the grade's window
LIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]   # config/strategies.yaml ml_entry.account_symbols.bybit_2 (== bybit_portfolio)
LIVE_RECORD = {"account": "bybit_2", "since": "2026-11-02", "n_closed": 5, "sides": "all short", "pnl_usd": 4.93, "winners": 3}
STRUCT_SPEC = "pivot=5;sl_only"
SIDE_N, SIDE_LONG_MAX, SIDE_SHORT_MIN = 30, -0.30, -0.05
POP_N = 30
EXIT_DELTA = 0.05
DECAY_N, DECAY_DELTA = 100, -0.10
NOISE_P = 0.05


def _stats(tk: pd.DataFrame) -> dict:
    if tk is None or len(tk) == 0:
        return {"n": 0, "mean_net_r": None}
    n = len(tk)
    se = float(tk.net_r.std(ddof=1) / math.sqrt(n)) if n > 1 else None
    return {"n": int(n), "mean_net_r": float(tk.net_r.mean()), "se": se,
            "ci95": None if se is None else [float(tk.net_r.mean() - 1.96 * se), float(tk.net_r.mean() + 1.96 * se)],
            "mean_gross_r": float(tk.gross_r.mean()), "mean_cost_r": float(tk.cost_r.mean()),
            "win_share": float((tk.net_r > 0).mean()), "n_symbols": int(tk.symbol.nunique())}


def _struct_side(df: pd.DataFrame, cand: np.ndarray, entry: np.ndarray, atr: np.ndarray, side: int, spec: str):
    """First-passage under the live SL-only structure exit for ``side`` (the equity harness did LONG only)."""
    import ml_entry_tp_revision as R
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    px, jj, rs = np.empty(len(cand)), np.empty(len(cand), int), np.empty(len(cand), int)
    for r, i in enumerate(cand):
        path = R.structure_sl_path(h, lo, c, int(i), float(entry[r]), float(atr[r]), side, spec)
        sl = slice(i + 1, i + 1 + E.HORIZON_H)
        px[r], jj[r], rs[r], _ = R.walk(o[sl], h[sl], lo[sl], c[sl], float(entry[r]), float(atr[r]), side, None, sl_path=path)
    return px, jj, rs


def structure_table(cache: Path, win: pd.DataFrame, spec: str = STRUCT_SPEC) -> pd.DataFrame:
    """The window rows with BOTH sides' outcomes replaced by the structure-exit replay, costed by the canonical stack."""
    parts = []
    for sym, g in win.groupby("symbol", sort=False):
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        cand, entry, atr = g["i"].to_numpy(int), g["entry"].to_numpy(float), g["atr"].to_numpy(float)
        risk = E.SL_ATR * atr
        t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
        add = {}
        for name, side in (("long", 1), ("short", -1)):
            px, jj, rs = _struct_side(df, cand, entry, atr, side, spec)
            fee, slip, fund = E._cost_r(entry, px, risk, t_ns[cand + 1] / 1e9, t_ns[cand + jj] / 1e9 + 3600.0)
            gross = side * (px - entry) / risk
            add.update({f"gross_{name}": gross, f"cost_{name}": fee + slip + fund, f"net_{name}": gross - fee - slip - fund,
                        f"reason_{name}": rs, f"bars_{name}": jj})
        parts.append(g.assign(**add))
    return pd.concat(parts)


def _binom_ge(k: int, n: int, p: float) -> float:
    return float(sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1)))


def decompose(tab: pd.DataFrame, models: dict, tau: float, cache: Path, start: str = WINDOW_START, end: str = WINDOW_END,
              live_symbols=LIVE_SYMBOLS, live: dict = LIVE_RECORD, spec: str = STRUCT_SPEC) -> dict:
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    win = tab[(tab.ts >= ts0) & (tab.ts < ts1)].reset_index(drop=True)
    # provenance: predict -- the regressed net R of each side (policy() thresholds it at tau), not a probability
    pl, ps = models["long"].predict(win[E.FEATURES]), models["short"].predict(win[E.FEATURES])
    brk = E.policy(win, pl, ps, tau)
    stw = structure_table(cache, win, spec)
    stk = E.policy(stw, pl, ps, tau)
    pool, pool_s = _stats(brk), _stats(stk)
    cuts = {"pool_bracket": pool, "pool_structure": pool_s}
    # (a) side
    cuts["side"] = {s: _stats(brk[brk.side == s]) for s in ("long", "short")}
    # (b) symbol
    per = {s: _stats(g) for s, g in brk.groupby("symbol")}
    cuts["symbol"] = {"per_symbol": {k: v for k, v in sorted(per.items(), key=lambda kv: kv[1]["n"], reverse=True)[:15]},
                      "ex_most_negative_sum": None}
    if len(brk):
        sums = brk.groupby("symbol").net_r.sum()
        worst = sums.idxmin()
        cuts["symbol"]["ex_most_negative_sum"] = {"symbol": worst, **_stats(brk[brk.symbol != worst])}
    # (c) live population
    lp = brk[brk.symbol.isin(live_symbols)]
    cuts["live_population"] = {"symbols": list(live_symbols), "both_sides": _stats(lp),
                               "by_side": {s: _stats(lp[lp.side == s]) for s in ("long", "short")},
                               "structure_both_sides": _stats(stk[stk.symbol.isin(live_symbols)])}
    short_share = float((lp.side == "short").mean()) if len(lp) else None
    cuts["live_population"]["why_all_shorts"] = {
        "side_filter": "ABSENT for bybit_2/bybit_portfolio (both sides allowed; config/accounts.yaml has none, long-only is alpaca_live)",
        "replay_short_share_of_live_population_trades": short_share,
        "p_all_5_short_if_independent": None if short_share is None else short_share ** live["n_closed"]}
    # (e) time
    mid = ts0 + pd.Timedelta(days=7)
    first, last = brk[pd.to_datetime(brk.ts, utc=True) < mid], brk[pd.to_datetime(brk.ts, utc=True) >= mid]
    cuts["time"] = {"first_7d": _stats(first), "last_7d": _stats(last)}
    # live record next to the replay (n is 5: no CI is claimed)
    sh = cuts["side"]["short"]
    cuts["live_record"] = {**live, "note": "n=5 closed trades; R per trade not in this job's inputs, so only winners/n is compared"}
    if sh["n"]:
        cuts["live_record"]["p_ge_winners_of_n_given_replay_short_win_share"] = _binom_ge(live["winners"], live["n_closed"], sh["win_share"])

    v = {}
    lg, st = cuts["side"]["long"], cuts["side"]["short"]
    v["side"] = ("INDETERMINATE" if lg["n"] < SIDE_N else
                 "SIDE-DRIVER" if (lg["mean_net_r"] <= SIDE_LONG_MAX and (st["mean_net_r"] or -9) >= SIDE_SHORT_MIN) else "NOT-SIDE")
    lpb = cuts["live_population"]["both_sides"]
    v["population"] = ("INDETERMINATE" if lpb["n"] < POP_N else
                       "POPULATION-DRIVER" if (lpb["mean_net_r"] >= 0 and (pool["mean_net_r"] or 0) < 0) else "NOT-POPULATION")
    if pool["n"] and pool_s["n"]:
        d = pool_s["mean_net_r"] - pool["mean_net_r"]
        v["exit"] = "EXIT-DRIVER" if (d >= EXIT_DELTA and pool_s["mean_net_r"] >= 0) else ("EXIT-PARTIAL" if d >= EXIT_DELTA else "NOT-EXIT")
        cuts["exit_delta_structure_minus_bracket"] = d
    else:
        v["exit"] = "INDETERMINATE"
    f7, l7 = cuts["time"]["first_7d"], cuts["time"]["last_7d"]
    v["decay"] = ("INDETERMINATE" if min(f7["n"], l7["n"]) < DECAY_N else
                  "DECAY" if (l7["mean_net_r"] - f7["mean_net_r"]) <= DECAY_DELTA else "NOT-DECAY")
    p_n = cuts["live_record"].get("p_ge_winners_of_n_given_replay_short_win_share")
    v["noise"] = "INDETERMINATE" if p_n is None else ("NOISE-COMPATIBLE" if p_n >= NOISE_P else "NOT-NOISE")
    lines = [f"{k}: {x}" for k, x in v.items()]
    return {"verdict_lines": lines, "verdicts": v, "cuts": cuts, "window": {"start": start, "end": end}, "tau": tau,
            "n_decision_rows": int(len(win)), "structure_exit": spec,
            "declared_gaps": ["live leg also runs the first-passage TP revision (extend-only); not modelled here",
                              "live record is n=5: no CI, winners/n only"]}


ROLL_START, ROLL_END, ROLL_DAYS = "2025-10-01", "2026-09-30", 14   # the frozen v1's clean held-out year (v1 train_end_exclusive 2025-09-22)
CURRENT_FORTNIGHT_MEAN = -0.1316                                   # served v1r20261106, grade 42473814600 (n=317)
ROLL_SIDE_N, ROLL_LONG_MAX, ROLL_GAP = 300, -0.10, 0.15
LEVER_N, LEVER_DELTA = 300, 0.02
BAND_WINDOWS, BAND_WINDOW_N, BAND_PCT = 20, 30, 5


def rolling(tab: pd.DataFrame, models: dict, tau: float, start: str = ROLL_START, end: str = ROLL_END, window_days: int = ROLL_DAYS,
            current: float = CURRENT_FORTNIGHT_MEAN) -> dict:
    """Frozen-model replay over consecutive ``window_days`` windows: both-sides, long-only and short-only policies, per window and pooled."""
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    win = tab[(tab.ts >= ts0) & (tab.ts < ts1)].reset_index(drop=True)
    # provenance: predict -- regressed net R of each side, not a probability
    pl, ps = models["long"].predict(win[E.FEATURES]), models["short"].predict(win[E.FEATURES])
    neg = np.full(len(win), -1e9)
    both, short = E.policy(win, pl, ps, tau), E.policy(win, neg, ps, tau)
    long_ = E.policy(win, pl, neg, tau)
    rows = []
    for k in range(int((ts1 - ts0).days // window_days)):
        a0, a1 = ts0 + pd.Timedelta(days=k * window_days), ts0 + pd.Timedelta(days=(k + 1) * window_days)
        t = both[(pd.to_datetime(both.ts, utc=True) >= a0) & (pd.to_datetime(both.ts, utc=True) < a1)]
        st = _stats(t)
        rows.append({"start": str(a0.date()), "n": st["n"], "mean_net_r": st["mean_net_r"],
                     "long_n": int((t.side == "long").sum()), "short_n": int((t.side == "short").sum())})
    pooled = {"both": _stats(both), "long_side_of_both": _stats(both[both.side == "long"]), "short_side_of_both": _stats(both[both.side == "short"]),
              "short_only_policy": _stats(short), "long_only_policy": _stats(long_)}
    lg, sh = pooled["long_side_of_both"], pooled["short_side_of_both"]
    v = {}
    v["side_persistence"] = ("INDETERMINATE" if lg["n"] < ROLL_SIDE_N else
                             "SIDE-PERSISTENT" if (lg["mean_net_r"] <= ROLL_LONG_MAX and (sh["mean_net_r"] - lg["mean_net_r"]) >= ROLL_GAP) else "SIDE-WINDOW-SPECIFIC")
    so, bo = pooled["short_only_policy"], pooled["both"]
    v["short_only_lever"] = ("INDETERMINATE" if so["n"] < LEVER_N or bo["n"] < LEVER_N else
                             "SHORT-ONLY-LEVER" if so["mean_net_r"] >= bo["mean_net_r"] + LEVER_DELTA else "NO-LEVER")
    ok = [r["mean_net_r"] for r in rows if r["n"] >= BAND_WINDOW_N and r["mean_net_r"] is not None]
    pct = float(np.percentile(ok, BAND_PCT)) if len(ok) >= BAND_WINDOWS else None
    v["fortnight_band"] = "INDETERMINATE" if pct is None else ("ANOMALOUS" if current < pct else "WITHIN-BAND")
    return {"verdicts": v, "verdict_lines": [f"{k}: {x}" for k, x in v.items()], "pooled": pooled, "windows": rows,
            "band": {"n_windows_used": len(ok), "p5": pct, "current_fortnight_mean": current,
                     "median": float(np.median(ok)) if ok else None}, "tau": tau, "window": {"start": start, "end": end, "days": window_days}}


def run_rolling(a) -> int:
    import ml_entry_retrain as RT
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    syms = E.universe()
    rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = E.build_table(cache, syms)
    served = REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json"
    meta, models = E._frozen_models(served)
    assert str(meta["train_end_exclusive"]) < ROLL_START, "the frozen model must not have seen the replay window"
    d = rolling(tab, models, float(meta["tau"]))
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate",
           "population": (f"ROLLING replay of the frozen ml_decision_entry_v1 (train_end {meta['train_end_exclusive']}, tau {meta['tau']}) over "
                          f"{ROLL_START}..{ROLL_END} in {ROLL_DAYS}-day windows, {tab.symbol.nunique()} symbols, canonical cost stack; descriptive"),
           "note": " | ".join(d["verdict_lines"]), "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "latest_bar": max(v["last_bar"] for v in rep.values())}, "n": d["pooled"]["both"]["n"],
           "produced_by": {"tool": "python3 scripts/research/ml_entry_replay_decompose.py rolling", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("ROLLING: " + row["note"], flush=True)
    return 0


def run(a) -> int:
    import ml_entry_retrain as RT
    from src.runtime.ml_entry_served import served_artifact
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    syms = E.universe()
    rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = E.build_table(cache, syms)
    path = served_artifact()
    meta, models = E._frozen_models(path)
    assert list(meta.get("features", E.FEATURES)) == list(E.FEATURES), "served feature list differs from the harness list"
    d = decompose(tab, models, float(meta["tau"]), cache)
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate",
           "population": (f"DECOMPOSITION of the served ml_entry replay window {WINDOW_START}..{WINDOW_END} ({path.parent.name}, tau {meta['tau']}, "
                          f"{tab.symbol.nunique()} symbols, canonical cost stack); descriptive, five registered cuts"),
           "note": " | ".join(d["verdict_lines"]), "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "served": {"path": str(path.relative_to(REPO)), "model_id": meta.get("model_id")},
                           "latest_bar": max(v["last_bar"] for v in rep.values())},
           "n": d["cuts"]["pool_bracket"]["n"], "produced_by": {"tool": "python3 scripts/research/ml_entry_replay_decompose.py run", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("DECOMPOSE: " + row["note"], flush=True)
    return 0


def self_test() -> int:
    import tempfile
    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    tab = E.build_table(root, syms)
    train = tab[tab.ts < tab.ts.max() - pd.Timedelta(days=40)]
    models = E.fit_models(train.sample(min(len(train), 20000), random_state=0))
    end = (tab.ts.max() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    start = (tab.ts.max() - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    d = decompose(tab, models, 0.0, root, start=start, end=end, live_symbols=syms[:3],
                  live={"n_closed": 5, "winners": 3, "pnl_usd": 1.0, "sides": "all short", "account": "x", "since": "2026-11-02"})
    assert set(d["verdicts"]) == {"side", "population", "exit", "decay", "noise"}, d["verdicts"]
    assert len(d["verdict_lines"]) == 5 and d["cuts"]["pool_bracket"]["n"] >= 0
    assert d["cuts"]["pool_structure"]["n"] >= 0 and "live_population" in d["cuts"] and "time" in d["cuts"]
    assert abs(_binom_ge(0, 5, 0.3) - 1.0) < 1e-12 and abs(_binom_ge(5, 5, 0.5) - 0.5 ** 5) < 1e-12
    r = rolling(tab, models, 0.0, start=start, end=end, window_days=7, current=-0.1)
    assert set(r["verdicts"]) == {"side_persistence", "short_only_lever", "fortnight_band"} and len(r["windows"]) >= 1, r
    assert r["pooled"]["short_only_policy"]["n"] >= 0 and r["pooled"]["both"]["n"] >= 0
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run", "rolling"])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_decompose_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-08")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd not in ("run", "rolling") or not a.unit:
        ap.error("run|rolling --unit RQ-... (or --self-test)")
    return run_rolling(a) if a.cmd == "rolling" else run(a)


if __name__ == "__main__":
    sys.exit(main())
