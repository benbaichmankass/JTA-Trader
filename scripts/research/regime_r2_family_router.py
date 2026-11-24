#!/usr/bin/env python3
# wiring: research/queue/RQ-20261124-f1a0-16.yaml (REGIME-PROGRAM R2, lane ML-PRIMARY); reads the backtest trade corpus through cf_bulk.discover / load_jobs
"""REGIME-PROGRAM R2: strategy-performance regimes. Does routing risk to the strategy BOOKS that a causal classifier expects to earn next week
beat trading every book, and beat RANDOM routing with the same number of books per week? (Tier-1 research; no gate, no config.)

Why (R1, RQ-20261124-f1a0-13, run 45507416598): the BTC regime STATE persists (30d-return acf 0.87 week to week) but WHICH SIDE earns does not
(side-gap r -0.06 at 1w, +0.08 at 1m, -0.35 at 1q). A side router on regime state is therefore ruled out; R2 labels each week by which strategy
family x direction EARNED, and asks whether that label is predictable one week ahead from information available at the week's start.

Population: the backtest trade corpus the cf tooling reads (``cf_bulk.TRADE_GLOBS``: comms/research/**/*trades*.jsonl*, comms/strategy_evidence/...),
crypto symbols (``*USDT``) of the four families with multi-year coverage (trend_donchian, htf_pullback, fade_breakout, squeeze_breakout), entries in
[DATA_START, DATA_END) (the end is PINNED so later landed results cannot move the window). One row per UNIQUE trade (family, symbol, timeframe,
entry time, direction); parameter-sweep variants of the same trade are AVERAGED (the family's average configuration). R is each harness's own
``net_r`` (fee + slippage + funding, the full cost stack the harnesses emit), at constant money risk per trade.

Books: family x direction = 8. Week w (ISO week of entry): per book, n trades and summed net R.
Features for week w use weeks < w ONLY: each book's trailing mean net R per trade over 1 / 4 / 13 / 26 weeks and its trailing 4-week trade count,
plus the cross-book mean of the 4-week and 13-week trailing means (the "which family is in season" context).

Arms (registered; each chooses, every test week, a SUBSET of books to trade; all other books are skipped that week):
  persist  books whose trailing 13-week mean net R per trade > 0.
  logit    a pooled L2 logistic model, P(book's next-week mean net R > 0) from the features + book one-hot, refit every REFIT_WEEKS on all
           weeks before the refit point (expanding window, a 1-week embargo); trade the book when p > 0.5.
Grade per arm over the test weeks [TEST_START, DATA_END):
  money       mean net R per trade TAKEN (sum R of chosen book-weeks / their trades); baseline = all books every week.
  delta       arm money - baseline money; se from a 1,000-draw bootstrap over WEEKS (the week is the cluster).
  random      200 draws keeping each week's NUMBER of chosen books, choosing which at random; share of draws whose money >= the arm's.
  years       delta per calendar year of the test window.
RULE-REGIME-R2-FAMILY-ROUTER-20261124: an arm PASSES iff delta >= +0.02 R/trade AND delta/se >= 2 AND random share <= 0.025 (two arms, Bonferroni
of 0.05) AND delta > 0 in >= 4 of the 5 test years AND the arm takes >= 30% of the baseline's trades. The unit PASSES iff either arm passes;
FAILS iff both arms have delta <= 0 or random share >= 0.5; INDETERMINATE otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

FAMILIES = ("trend_donchian", "htf_pullback", "fade_breakout", "squeeze_breakout")
DATA_START = "2020-09-01"
DATA_END = "2026-10-26"          # pinned (a Monday); entries on or after it are excluded
TEST_START = "2022-01-03"        # first Monday of 2022; weeks before it are training only
TRAIL = (1, 4, 13, 26)
REFIT_WEEKS = 13
RIDGE = 1.0
N_BOOT = 1000
N_RANDOM = 200
SEED = 20261124
RULE = {"id": "RULE-REGIME-R2-FAMILY-ROUTER-20261124", "min_delta_r": 0.02, "min_t": 2.0, "max_random_share": 0.025, "min_years_positive": 4,
        "n_test_years": 5, "min_trade_share": 0.30, "fail_random_share": 0.5}


def family_of(strategy: Any) -> Optional[str]:
    s = str(strategy or "")
    for f in FAMILIES:
        if s.startswith(f):
            return f
    return None


def unique_trades(jobs: Dict[str, dict]) -> pd.DataFrame:
    """One row per unique (family, symbol, tf, entry_time, direction) crypto trade in the window; variant net_r averaged."""
    rows = []
    for r in jobs.values():
        f = family_of(r.get("strategy"))
        sym = str(r.get("symbol") or "")
        if f is None or not sym.endswith("USDT") or r.get("net_r") is None:
            continue
        rows.append((f, sym, r.get("_tf") or "na", str(r["entry_time"])[:19], str(r["direction"]), float(r["net_r"])))
    df = pd.DataFrame(rows, columns=["family", "symbol", "tf", "entry_time", "direction", "net_r"])
    df["ts"] = pd.to_datetime(df.entry_time, utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    df = df[(df.ts >= pd.Timestamp(DATA_START, tz="UTC")) & (df.ts < pd.Timestamp(DATA_END, tz="UTC"))]
    g = df.groupby(["family", "symbol", "tf", "entry_time", "direction"], as_index=False).agg(net_r=("net_r", "mean"), n_variants=("net_r", "size"),
                                                                                              ts=("ts", "first"))
    return g


def weekly_books(trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(sum R, n) frames indexed by week start (Monday, UTC), one column per book 'family|direction'."""
    t = trades.copy()
    t["book"] = t.family + "|" + t.direction
    t["week"] = (t.ts.dt.tz_convert(None).dt.normalize() - pd.to_timedelta(t.ts.dt.weekday, unit="D"))
    s = t.pivot_table(index="week", columns="book", values="net_r", aggfunc="sum").fillna(0.0)
    n = t.pivot_table(index="week", columns="book", values="net_r", aggfunc="size").fillna(0).astype(float)
    full = pd.date_range(s.index.min(), s.index.max(), freq="7D")
    return s.reindex(full, fill_value=0.0), n.reindex(full, fill_value=0.0)


def features(S: pd.DataFrame, N: pd.DataFrame) -> pd.DataFrame:
    """Long frame (week, book) of features built from weeks strictly before ``week`` (shift 1)."""
    out = []
    ctx = {}
    for L in (4, 13):
        m = (S.rolling(L, min_periods=1).sum() / N.rolling(L, min_periods=1).sum().replace(0, np.nan)).shift(1)
        ctx[L] = m.mean(axis=1)
    for b in S.columns:
        d = pd.DataFrame(index=S.index)
        for L in TRAIL:
            d[f"m{L}"] = (S[b].rolling(L, min_periods=1).sum() / N[b].rolling(L, min_periods=1).sum().replace(0, np.nan)).shift(1)
        d["cnt4"] = N[b].rolling(4, min_periods=1).sum().shift(1)
        d["ctx4"], d["ctx13"] = ctx[4], ctx[13]
        d["book"] = b
        d["y_sum"], d["y_n"] = S[b], N[b]
        out.append(d)
    f = pd.concat(out).reset_index().rename(columns={"index": "week"})
    return f


def _logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE, iters: int = 50) -> np.ndarray:
    """L2 logistic regression by Newton/IRLS (intercept unpenalised); numpy only."""
    Xb = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(Xb.shape[1])
    P = np.eye(Xb.shape[1]) * ridge
    P[0, 0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ w, -30, 30)))
        g = Xb.T @ (p - y) + P @ w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + P + np.eye(len(w)) * 1e-9
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def _design(f: pd.DataFrame, books: Sequence[str], mu: Optional[np.ndarray] = None, sd: Optional[np.ndarray] = None):
    cols = [f"m{L}" for L in TRAIL] + ["cnt4", "ctx4", "ctx13"]
    X = f[cols].to_numpy(float)
    X = np.where(np.isnan(X), 0.0, X)
    X[:, cols.index("cnt4")] = np.log1p(X[:, cols.index("cnt4")])
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    X = (X - mu) / sd
    oh = np.column_stack([(f.book.to_numpy() == b).astype(float) for b in books[1:]]) if len(books) > 1 else np.zeros((len(f), 0))
    return np.column_stack([X, oh]), mu, sd


def choose_persist(f: pd.DataFrame) -> pd.Series:
    return (f["m13"].fillna(-1.0) > 0).astype(bool)


def choose_logit(f: pd.DataFrame, test_weeks: Sequence[pd.Timestamp]) -> pd.Series:
    books = sorted(f.book.unique())
    pick = pd.Series(False, index=f.index)
    tw = sorted(test_weeks)
    for i in range(0, len(tw), REFIT_WEEKS):
        start = tw[i]
        block = tw[i:i + REFIT_WEEKS]
        tr = f[(f.week < start - pd.Timedelta(days=7)) & (f.y_n > 0)]
        if len(tr) < 50 or tr.y_sum.gt(0).nunique() < 2:
            continue
        Xtr, mu, sd = _design(tr, books)
        w = _logit_fit(Xtr, (tr.y_sum > 0).to_numpy(float))
        te = f[f.week.isin(block)]
        Xte, _, _ = _design(te, books, mu, sd)
        p = 1.0 / (1.0 + np.exp(-(np.column_stack([np.ones(len(Xte)), Xte]) @ w)))
        pick.loc[te.index] = p > 0.5
    return pick


def grade(f: pd.DataFrame, pick: pd.Series, test_weeks: Sequence[pd.Timestamp], rng: np.random.Generator) -> Dict[str, Any]:
    t = f[f.week.isin(test_weeks)].copy()
    t["pick"] = pick.loc[t.index].to_numpy()
    wk = t.groupby("week")
    base_s, base_n = wk.y_sum.sum(), wk.y_n.sum()
    arm_s = t[t.pick].groupby("week").y_sum.sum().reindex(base_s.index, fill_value=0.0)
    arm_n = t[t.pick].groupby("week").y_n.sum().reindex(base_s.index, fill_value=0.0)

    def money(s, n):
        return float(s.sum() / n.sum()) if n.sum() > 0 else float("nan")

    m_arm, m_base = money(arm_s, arm_n), money(base_s, base_n)
    delta = m_arm - m_base
    W = len(base_s)
    a_s, a_n, b_s, b_n = arm_s.to_numpy(), arm_n.to_numpy(), base_s.to_numpy(), base_n.to_numpy()
    boots = []
    for _ in range(N_BOOT):
        ix = rng.integers(0, W, W)
        if a_n[ix].sum() > 0 and b_n[ix].sum() > 0:
            boots.append(a_s[ix].sum() / a_n[ix].sum() - b_s[ix].sum() / b_n[ix].sum())
    se = float(np.std(boots)) if boots else float("nan")
    # random routing: same number of books chosen each week, which ones at random
    k_by_week = t.groupby("week").pick.sum()
    groups = {w: g for w, g in t.groupby("week")}
    draws = []
    for _ in range(N_RANDOM):
        s_tot = n_tot = 0.0
        for w, g in groups.items():
            k = int(k_by_week.loc[w])
            if k == 0:
                continue
            ix = rng.choice(len(g), size=k, replace=False)
            s_tot += float(g.y_sum.to_numpy()[ix].sum())
            n_tot += float(g.y_n.to_numpy()[ix].sum())
        draws.append(s_tot / n_tot if n_tot > 0 else float("nan"))
    draws = np.array(draws)
    share = float(np.nanmean(draws >= m_arm)) if np.isfinite(m_arm) else float("nan")
    years = {}
    for y in sorted({w.year for w in base_s.index}):
        sel = [w.year == y for w in base_s.index]
        years[str(y)] = round(money(arm_s[sel], arm_n[sel]) - money(base_s[sel], base_n[sel]), 4)
    return {"n_weeks": W, "trades_arm": int(a_n.sum()), "trades_base": int(b_n.sum()), "trade_share": round(float(a_n.sum() / max(b_n.sum(), 1)), 4),
            "money_arm": round(m_arm, 5), "money_base": round(m_base, 5), "delta": round(delta, 5), "se_week_boot": round(se, 5),
            "t": round(delta / se, 3) if se and np.isfinite(se) and se > 0 else None, "sum_r_arm": round(float(a_s.sum()), 2),
            "sum_r_base": round(float(b_s.sum()), 2), "random": {"draws": N_RANDOM, "mean": round(float(np.nanmean(draws)), 5),
                                                                  "p95": round(float(np.nanpercentile(draws, 95)), 5), "share_ge_arm": round(share, 4)},
            "yearly_delta": years, "mean_books_per_week": round(float(k_by_week.mean()), 3)}


def arm_verdict(g: Dict[str, Any]) -> Tuple[str, Dict[str, bool]]:
    yrs = [v for v in g["yearly_delta"].values() if v == v]
    chk = {"delta_ge_min": g["delta"] >= RULE["min_delta_r"], "t_ge_min": (g["t"] or 0) >= RULE["min_t"],
           "beats_random": g["random"]["share_ge_arm"] <= RULE["max_random_share"],
           "years_positive": sum(1 for v in yrs if v > 0) >= RULE["min_years_positive"], "trade_share": g["trade_share"] >= RULE["min_trade_share"]}
    if all(chk.values()):
        return "pass", chk
    if g["delta"] <= 0 or g["random"]["share_ge_arm"] >= RULE["fail_random_share"]:
        return "fail", chk
    return "indeterminate", chk


def unit_verdict(arms: Dict[str, str]) -> str:
    if any(v == "pass" for v in arms.values()):
        return "pass"
    if all(v == "fail" for v in arms.values()):
        return "fail"
    return "indeterminate"


def corpus_fingerprint(trades: pd.DataFrame) -> str:
    h = hashlib.sha256()
    for r in trades.sort_values(["family", "symbol", "tf", "entry_time", "direction"]).itertuples(index=False):
        h.update(f"{r.family}|{r.symbol}|{r.tf}|{r.entry_time}|{r.direction}|{r.net_r:.6f}\n".encode())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance only
        return "unknown"


def run(trades: pd.DataFrame, seed: int = SEED) -> Dict[str, Any]:
    S, N = weekly_books(trades)
    f = features(S, N)
    test_weeks = [w for w in S.index if w >= pd.Timestamp(TEST_START)]
    rng = np.random.default_rng(seed)
    picks = {"persist": choose_persist(f), "logit": choose_logit(f, test_weeks)}
    res = {a: grade(f, p, test_weeks, rng) for a, p in picks.items()}
    verdicts = {}
    for a, g in res.items():
        verdicts[a], g["checks"] = arm_verdict(g)
        g["verdict"] = verdicts[a]
    book_census = {b: {"trades": int(N[b].sum()), "sum_r": round(float(S[b].sum()), 2)} for b in S.columns}
    return {"arms": res, "verdict": unit_verdict(verdicts), "books": book_census, "n_test_weeks": len(test_weeks)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/regime_r2")
    ap.add_argument("--unit", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    import cf_bulk
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = cf_bulk.discover()
    jobs, counts = cf_bulk.load_jobs(files)
    trades = unique_trades(jobs)
    m = run(trades)
    fp = corpus_fingerprint(trades)
    pop = (f"backtest trade corpus (cf_bulk.TRADE_GLOBS, {counts.get('files')} files, {counts.get('distinct_jobs')} distinct jobs) -> {len(trades)} unique crypto "
           f"trades of {list(FAMILIES)} with entries {DATA_START}..{DATA_END} (variants averaged), 8 family x direction books, weekly; test weeks "
           f"{TEST_START}..{DATA_END} ({m['n_test_weeks']}); harness net_r (fee + slippage + funding)")
    why = "; ".join(f"{k}: {g['verdict']} delta {g['delta']:+.4f} t {g['t']} random share {g['random']['share_ge_arm']} trade share {g['trade_share']}"
                    for k, g in m["arms"].items())
    dw = {"data_start": DATA_START, "data_end": DATA_END, "test_start": TEST_START, "corpus_sha256": fp, "n_unique_trades": int(len(trades)),
          "n_files": counts.get("files")}
    summ = {"schema": "regime_r2_family_router/1", "unit": a.unit, "verdict": m["verdict"], "why": why, "rule": RULE, "population": pop,
            "data_window": dw, "load_counts": counts, "measurement": m, "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": m["verdict"], "read_state": "measured", "n": int(len(trades)), "note": why, "population": pop,
                                                  "rule": RULE, "data_window": dw, "measurement": m}, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": m["verdict"], "why": why}), flush=True)
    return 0


def _synthetic(seed: int = 3, persistent: bool = True) -> pd.DataFrame:
    """Synthetic trades: 8 books; with ``persistent`` each book has a slowly-switching sign of edge (a learnable regime)."""
    rng = np.random.default_rng(seed)
    weeks = pd.date_range("2020-09-07", "2026-10-19", freq="7D", tz="UTC")
    rows = []
    for fi, fam in enumerate(FAMILIES):
        for d in ("long", "short"):
            state = 1.0
            for w in weeks:
                if rng.random() < (0.04 if persistent else 0.5):
                    state = -state
                mu = 0.25 * state if persistent else 0.0
                for j in range(int(rng.integers(5, 15))):
                    ts = w + pd.Timedelta(hours=int(rng.integers(0, 160)))
                    rows.append((fam, f"S{j % 5}USDT", "1h", str(ts)[:19], d, float(rng.normal(mu, 1.0)), 1, ts))
    return pd.DataFrame(rows, columns=["family", "symbol", "tf", "entry_time", "direction", "net_r", "n_variants", "ts"]).drop_duplicates(
        subset=["family", "symbol", "tf", "entry_time", "direction"])


def _self_test() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    # feature causality: week w features never use week w's outcome
    tr = _synthetic(persistent=True)
    S, N = weekly_books(tr)
    f = features(S, N)
    b = S.columns[0]
    w = S.index[30]
    row = f[(f.book == b) & (f.week == w)].iloc[0]
    check("m1 is the previous week's mean", abs(row.m1 - S[b].iloc[29] / N[b].iloc[29]) < 1e-9)
    check("logit fit separates a separable toy", _logit_fit(np.array([[-2.0], [-1.0], [1.0], [2.0]]), np.array([0.0, 0, 1, 1]))[1] > 0)
    m = run(tr)
    check("persistent regimes: persist arm beats baseline", m["arms"]["persist"]["delta"] > 0.05)
    check("persistent regimes: persist arm beats random", m["arms"]["persist"]["random"]["share_ge_arm"] <= 0.05)
    check("persistent regimes: logit arm beats baseline", m["arms"]["logit"]["delta"] > 0.05)
    m0 = run(_synthetic(seed=4, persistent=False))
    check("no regimes: no arm passes", m0["verdict"] != "pass")
    check("verdict mapping", unit_verdict({"a": "fail", "b": "indeterminate"}) == "indeterminate" and unit_verdict({"a": "fail", "b": "fail"}) == "fail")
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
