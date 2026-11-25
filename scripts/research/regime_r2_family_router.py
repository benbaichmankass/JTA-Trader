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

ITERATION 2 (``--books symbol``, unit RQ-20261124-f1a0-18, RULE-REGIME-R2B-SYMBOL-BOOKS-20261124), from f1a0-16 (run 45511033292): ``persist`` was
INDETERMINATE (+0.021 R/trade, t 0.76, random share 0.10, 4 of 5 years positive) and ``logit`` FAILED (anti-predictive, 0.49 books/week). With only 8
books the week-clustered se is wide. Iteration 2 makes each book a family x SYMBOL x direction (hundreds of books, so many more routing decisions
per week) and runs the ``persist`` arm ONLY (logit dropped as failed); everything else is unchanged. One arm, so random share <= 0.05.

R4, REGIME-CONDITIONED SIZING (``--books symbol --mode tilt``, unit RQ-20261125-f1a0-19, RULE-REGIME-R4-BOOK-TILT-20261125), from f1a0-18 (run 45513198865):
the trailing-book signal beat ALL 200 random routings (share 0.00) but its money delta (+0.018 R/trade, t 1.14) was small against week-to-week variance,
and routing DROPS 61% of trades. R4 keeps EVERY trade and tilts risk instead: weight TILT[0] where the book's trailing 13-week mean > 0, TILT[1] where
it is <= 0, 1.0 where there is no history; renormalised each week so the weighted trade count equals the actual count (pure reallocation, same total
risk). Statistic: weighted net R per trade minus the unweighted; se from 1,000 week-bootstrap draws; control: the same weights PERMUTED across books within
each week (200 draws).

R3, STATE CLASSIFIERS ON MONEY (``--books symbol --mode state``, unit RQ-20261125-f1a0-20, RULE-REGIME-R3-STATE-CELLS-20261125), from f1a0-19 (run 45515431409):
the book's OWN trailing performance carries real but small, decaying information (R4 +0.0098, t 1.27, permutation share 0.00, 2025-26 flat). R3 asks
whether the MARKET STATE says which books earn: each week gets a BTC state cell from a classifier using data before the week, and each book is tilted
TILT[0] / TILT[1] by the sign of its mean net R per trade in PRIOR weeks of the SAME cell (>= STATE_MIN_N trades there, else 1.0); same renormalisation,
statistic and within-week permutation control as R4. Classifiers (fixed, no search):
  advol   2 x 2: BTC close above / below its 50-day mean x 20-day realised vol above / below its trailing 365-day median (last daily close before the week)
  hmm2    a 2-state Gaussian HMM on weekly BTC log returns, fit by EM on weeks before TEST_START only; the week's cell is the FILTERED (forward) most
          probable state given returns through the previous week.
Two classifiers, so each needs permutation share <= 0.025.
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


RULE_SYMBOL = dict(RULE, id="RULE-REGIME-R2B-SYMBOL-BOOKS-20261124", max_random_share=0.05)
TILT = (2.0, 0.5)
RULE_TILT = {"id": "RULE-REGIME-R4-BOOK-TILT-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05, "min_years_positive": 4,
             "n_test_years": 5, "fail_random_share": 0.5}


def weekly_books(trades: pd.DataFrame, level: str = "family") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(sum R, n) frames indexed by week start (Monday, UTC), one column per book 'family|direction' (level 'family') or
    'family|symbol|direction' (level 'symbol')."""
    t = trades.copy()
    t["book"] = (t.family + "|" + t.direction) if level == "family" else (t.family + "|" + t.symbol + "|" + t.direction)
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


def arm_verdict(g: Dict[str, Any], rule: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, bool]]:
    RULE = rule or globals()["RULE"]
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
    except Exception:  # noqa: BLE001  # allow-silent: provenance only (git sha in the summary); "unknown" is recorded, never a measurement
        return "unknown"


RULE_STATE = dict(RULE_TILT, id="RULE-REGIME-R3-STATE-CELLS-20261125", max_random_share=0.025)
STATE_MIN_N = 20
BTC_CACHE = "/tmp/ml_entry_klines"


def btc_daily(cache: str = BTC_CACHE) -> pd.Series:
    """Daily BTCUSDT closes (UTC) from the ml_entry klines cache (fetched by ml_entry_retrain.fetch_through when absent)."""
    p = Path(cache) / "BTCUSDT.pkl"
    if not p.exists():
        from datetime import date
        import ml_entry_retrain as RT
        RT.fetch_through(Path(cache), ["BTCUSDT"], RT.plan(date(2026, 11, 22)))
    d = pd.read_pickle(p)
    s_ = d.set_index(pd.to_datetime(d.ts, utc=True))["close"].astype(float)
    return s_.resample("1D").last().dropna()


def cells_advol(close: pd.Series, weeks: Sequence[pd.Timestamp]) -> pd.Series:
    sma = close.rolling(50).mean()
    rv = np.log(close).diff().rolling(20).std()
    med = rv.rolling(365, min_periods=180).median()
    st = pd.DataFrame({"up": close > sma, "hv": rv > med, "ok": sma.notna() & med.notna()})
    out = {}
    for w in weeks:
        prev = st[st.index < pd.Timestamp(w, tz="UTC")]
        if prev.empty or not prev.ok.iloc[-1]:
            out[w] = None
        else:
            out[w] = f"{'up' if prev.up.iloc[-1] else 'dn'}_{'hv' if prev.hv.iloc[-1] else 'lv'}"
    return pd.Series(out)


def _hmm2_fit(x: np.ndarray, iters: int = 200) -> Dict[str, np.ndarray]:
    """2-state Gaussian HMM by EM (numpy). States ordered by mean (0 = lower mean)."""
    mu = np.array([np.percentile(x, 25), np.percentile(x, 75)])
    sd = np.array([x.std(), x.std()]) + 1e-9
    A = np.array([[0.9, 0.1], [0.1, 0.9]])
    pi = np.array([0.5, 0.5])
    for _ in range(iters):
        B = np.exp(-0.5 * ((x[:, None] - mu) / sd) ** 2) / sd + 1e-300
        T = len(x)
        al, c = np.zeros((T, 2)), np.zeros(T)
        al[0] = pi * B[0]
        c[0] = al[0].sum()
        al[0] /= c[0]
        for t in range(1, T):
            al[t] = (al[t - 1] @ A) * B[t]
            c[t] = al[t].sum()
            al[t] /= c[t]
        be = np.ones((T, 2))
        for t in range(T - 2, -1, -1):
            be[t] = (A @ (B[t + 1] * be[t + 1])) / c[t + 1]
        g = al * be
        g /= g.sum(1, keepdims=True)
        xi = np.zeros((2, 2))
        for t in range(T - 1):
            m = al[t][:, None] * A * (B[t + 1] * be[t + 1])[None, :]
            xi += m / m.sum()
        A = xi / xi.sum(1, keepdims=True)
        pi = g[0]
        mu = (g * x[:, None]).sum(0) / g.sum(0)
        sd = np.sqrt((g * (x[:, None] - mu) ** 2).sum(0) / g.sum(0)) + 1e-9
    o = np.argsort(mu)
    return {"mu": mu[o], "sd": sd[o], "A": A[np.ix_(o, o)], "pi": pi[o]}


def cells_hmm2(close: pd.Series, weeks: Sequence[pd.Timestamp], fit_end: str = TEST_START) -> Tuple[pd.Series, Dict[str, Any]]:
    wk = close.resample("W-SUN").last().dropna()
    r = np.log(wk).diff().dropna()
    tr = r[r.index < pd.Timestamp(fit_end, tz="UTC")].to_numpy()
    par = _hmm2_fit(tr)
    B = np.exp(-0.5 * ((r.to_numpy()[:, None] - par["mu"]) / par["sd"]) ** 2) / par["sd"] + 1e-300
    al = np.zeros((len(r), 2))
    a = par["pi"] * B[0]
    al[0] = a / a.sum()
    for t in range(1, len(r)):
        a = (al[t - 1] @ par["A"]) * B[t]
        al[t] = a / a.sum()
    filt = pd.Series(np.argmax(al, 1), index=r.index)
    out = {}
    for w in weeks:
        prev = filt[filt.index < pd.Timestamp(w, tz="UTC")]
        out[w] = None if prev.empty else f"s{int(prev.iloc[-1])}"
    info = {"n_fit_weeks": int(len(tr)), "mu": [round(float(v), 5) for v in par["mu"]], "sd": [round(float(v), 5) for v in par["sd"]],
            "A": [[round(float(v), 4) for v in row] for row in par["A"]]}
    return pd.Series(out), info


def state_raw(f: pd.DataFrame, cell_by_week: pd.Series) -> pd.Series:
    """Per (week, book) row: TILT by the sign of the book's mean net R per trade in PRIOR weeks of the same cell (>= STATE_MIN_N trades), else 1."""
    d = f[["week", "book", "y_sum", "y_n"]].copy()
    d["cell"] = d.week.map(cell_by_week)
    d = d.sort_values(["book", "week"])
    d["cs"] = d.groupby(["book", "cell"], dropna=True).y_sum.cumsum() - d.y_sum
    d["cn"] = d.groupby(["book", "cell"], dropna=True).y_n.cumsum() - d.y_n
    raw = np.where(d.cell.isna() | (d.cn < STATE_MIN_N), 1.0, np.where(d.cs / d.cn.replace(0, np.nan) > 0, TILT[0], TILT[1]))
    return pd.Series(raw, index=d.index).reindex(f.index)


def tilt_weights(t: pd.DataFrame, raw: np.ndarray) -> np.ndarray:
    """Renormalise ``raw`` per week so sum(w * n) == sum(n) within each week (same total risk)."""
    w = np.asarray(raw, float).copy()
    n = t.y_n.to_numpy(float)
    wk = t.week.to_numpy()
    df = pd.DataFrame({"wk": wk, "wn": w * n, "n": n})
    g = df.groupby("wk").agg(wn=("wn", "sum"), n=("n", "sum"))
    scale = (g.n / g.wn.replace(0, np.nan)).fillna(1.0)
    return w * scale.reindex(wk).to_numpy()


def grade_tilt(f: pd.DataFrame, test_weeks: Sequence[pd.Timestamp], rng: np.random.Generator, raw_all: Optional[pd.Series] = None) -> Dict[str, Any]:
    sel = f.week.isin(test_weeks) & (f.y_n > 0)
    t = f[sel].reset_index(drop=True)
    if raw_all is None:
        raw = np.where(t["m13"].isna(), 1.0, np.where(t["m13"] > 0, TILT[0], TILT[1]))
    else:
        raw = raw_all[sel].to_numpy(float)
    w = tilt_weights(t, raw)
    ys, yn = t.y_sum.to_numpy(float), t.y_n.to_numpy(float)
    wk = t.week.to_numpy()
    weeks = np.unique(wk)
    idx = {x: np.flatnonzero(wk == x) for x in weeks}
    ws_ = np.array([float((w[idx[x]] * ys[idx[x]]).sum()) for x in weeks])
    bs_ = np.array([float(ys[idx[x]].sum()) for x in weeks])
    n_ = np.array([float(yn[idx[x]].sum()) for x in weeks])
    m_arm, m_base = ws_.sum() / n_.sum(), bs_.sum() / n_.sum()
    delta = float(m_arm - m_base)
    boots = []
    for _ in range(N_BOOT):
        ix = rng.integers(0, len(weeks), len(weeks))
        boots.append((ws_[ix].sum() - bs_[ix].sum()) / n_[ix].sum())
    se = float(np.std(boots))
    draws = []
    for _ in range(N_RANDOM):
        rw = raw.copy()
        for x in weeks:
            ii = idx[x]
            rw[ii] = rw[ii][rng.permutation(len(ii))]
        pw = tilt_weights(t, rw)
        draws.append(float((pw * ys).sum() / yn.sum()))
    draws = np.array(draws)
    share = float(np.mean(draws >= m_arm))
    years = {}
    for y in sorted({pd.Timestamp(x).year for x in weeks}):
        sel = np.array([pd.Timestamp(x).year == y for x in weeks])
        years[str(y)] = round(float((ws_[sel].sum() - bs_[sel].sum()) / n_[sel].sum()), 4)
    return {"n_weeks": int(len(weeks)), "trades": int(yn.sum()), "money_arm": round(float(m_arm), 5), "money_base": round(float(m_base), 5),
            "delta": round(delta, 5), "se_week_boot": round(se, 5), "t": round(delta / se, 3) if se > 0 else None,
            "random": {"draws": N_RANDOM, "kind": "weights permuted across books within each week", "mean": round(float(draws.mean()), 5),
                       "p95": round(float(np.percentile(draws, 95)), 5), "share_ge_arm": round(share, 4)},
            "yearly_delta": years, "share_book_weeks_up": round(float((raw == TILT[0]).mean()), 4), "trade_share": 1.0}


def tilt_verdict(g: Dict[str, Any], rule: Dict[str, Any] = RULE_TILT) -> Tuple[str, Dict[str, bool]]:
    yrs = [v for v in g["yearly_delta"].values() if v == v]
    chk = {"delta_ge_min": g["delta"] >= rule["min_delta_r"], "t_ge_min": (g["t"] or 0) >= rule["min_t"],
           "beats_random": g["random"]["share_ge_arm"] <= rule["max_random_share"], "years_positive": sum(1 for v in yrs if v > 0) >= rule["min_years_positive"]}
    if all(chk.values()):
        return "pass", chk
    if g["delta"] <= 0 or g["random"]["share_ge_arm"] >= rule["fail_random_share"]:
        return "fail", chk
    return "indeterminate", chk


def run(trades: pd.DataFrame, seed: int = SEED, level: str = "family", mode: str = "route", btc: Optional[pd.Series] = None) -> Dict[str, Any]:
    if mode == "state":
        S, N = weekly_books(trades, level)
        f = features(S, N)
        test_weeks = [w for w in S.index if w >= pd.Timestamp(TEST_START)]
        btc = btc if btc is not None else btc_daily()
        arms, verdicts = {}, {}
        ca = cells_advol(btc, list(S.index))
        ch, hinfo = cells_hmm2(btc, list(S.index))
        for name, cells in (("advol", ca), ("hmm2", ch)):
            g = grade_tilt(f, test_weeks, np.random.default_rng(seed), raw_all=state_raw(f, cells))
            v, g["checks"] = tilt_verdict(g, RULE_STATE)
            g["verdict"] = verdicts[name] = v
            g["cell_counts_test"] = {str(k): int(n) for k, n in cells[[w for w in test_weeks if w in cells.index]].value_counts(dropna=False).items()}
            arms[name] = g
        arms["hmm2"]["hmm"] = hinfo
        census = {"n_books": int(S.shape[1]), "trades": int(N.to_numpy().sum()), "sum_r": round(float(S.to_numpy().sum()), 2)}
        return {"arms": arms, "verdict": unit_verdict(verdicts), "books": census, "n_test_weeks": len(test_weeks), "level": level, "mode": mode,
                "rule": RULE_STATE}
    if mode == "tilt":
        S, N = weekly_books(trades, level)
        f = features(S, N)
        test_weeks = [w for w in S.index if w >= pd.Timestamp(TEST_START)]
        g = grade_tilt(f, test_weeks, np.random.default_rng(seed))
        v, g["checks"] = tilt_verdict(g)
        g["verdict"] = v
        census = {"n_books": int(S.shape[1]), "trades": int(N.to_numpy().sum()), "sum_r": round(float(S.to_numpy().sum()), 2)}
        return {"arms": {"tilt": g}, "verdict": v, "books": census, "n_test_weeks": len(test_weeks), "level": level, "mode": mode, "rule": RULE_TILT}
    S, N = weekly_books(trades, level)
    f = features(S, N)
    test_weeks = [w for w in S.index if w >= pd.Timestamp(TEST_START)]
    rng = np.random.default_rng(seed)
    picks = {"persist": choose_persist(f)} if level == "symbol" else {"persist": choose_persist(f), "logit": choose_logit(f, test_weeks)}
    res = {a: grade(f, p, test_weeks, rng) for a, p in picks.items()}
    rule = RULE_SYMBOL if level == "symbol" else RULE
    verdicts = {}
    for a, g in res.items():
        verdicts[a], g["checks"] = arm_verdict(g, rule)
        g["verdict"] = verdicts[a]
    if level == "symbol":
        book_census = {"n_books": int(S.shape[1]), "trades": int(N.to_numpy().sum()), "sum_r": round(float(S.to_numpy().sum()), 2)}
    else:
        book_census = {b: {"trades": int(N[b].sum()), "sum_r": round(float(S[b].sum()), 2)} for b in S.columns}
    return {"arms": res, "verdict": unit_verdict(verdicts), "books": book_census, "n_test_weeks": len(test_weeks), "level": level, "rule": rule}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/regime_r2")
    ap.add_argument("--unit", default="")
    ap.add_argument("--books", choices=["family", "symbol"], default="family")
    ap.add_argument("--mode", choices=["route", "tilt", "state"], default="route")
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
    m = run(trades, level=a.books, mode=a.mode)
    fp = corpus_fingerprint(trades)
    pop = (f"backtest trade corpus (cf_bulk.TRADE_GLOBS, {counts.get('files')} files, {counts.get('distinct_jobs')} distinct jobs) -> {len(trades)} unique crypto "
           f"trades of {list(FAMILIES)} with entries {DATA_START}..{DATA_END} (variants averaged), {m['books']['n_books'] if a.books == 'symbol' else 8} {'family x symbol x direction' if a.books == 'symbol' else 'family x direction'} books, weekly; test weeks "
           f"{TEST_START}..{DATA_END} ({m['n_test_weeks']}); harness net_r (fee + slippage + funding)")
    why = "; ".join(f"{k}: {g['verdict']} delta {g['delta']:+.4f} t {g['t']} random share {g['random']['share_ge_arm']} trade share {g['trade_share']}"
                    for k, g in m["arms"].items())
    dw = {"data_start": DATA_START, "data_end": DATA_END, "test_start": TEST_START, "corpus_sha256": fp, "n_unique_trades": int(len(trades)),
          "n_files": counts.get("files")}
    summ = {"schema": "regime_r2_family_router/1", "unit": a.unit, "verdict": m["verdict"], "why": why, "rule": m["rule"], "population": pop,
            "data_window": dw, "load_counts": counts, "measurement": m, "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": m["verdict"], "read_state": "measured", "n": int(len(trades)), "note": why, "population": pop,
                                                  "rule": m["rule"], "data_window": dw, "measurement": m}, indent=1, default=str) + "\n")
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
    ms = run(tr, level="symbol")
    check("symbol books: persist only, symbol-level rule", list(ms["arms"]) == ["persist"] and ms["rule"]["max_random_share"] == 0.05
          and ms["books"]["n_books"] > 8)
    check("symbol books: persistent regimes beat baseline", ms["arms"]["persist"]["delta"] > 0.05)
    mt = run(tr, level="symbol", mode="tilt")
    check("tilt: keeps every trade, persistent regimes beat baseline and the permuted control", mt["arms"]["tilt"]["delta"] > 0.02
          and mt["arms"]["tilt"]["random"]["share_ge_arm"] <= 0.05 and mt["rule"]["id"] == RULE_TILT["id"])
    t0_ = pd.DataFrame({"week": [1, 1, 2], "y_n": [10.0, 30.0, 5.0]})
    wt = tilt_weights(t0_, np.array([2.0, 0.5, 2.0]))
    check("tilt weights renormalise per week", abs((wt[:2] * t0_.y_n[:2]).sum() - 40.0) < 1e-9 and abs(wt[2] - 1.0) < 1e-9)
    mt0 = run(_synthetic(seed=4, persistent=False), level="symbol", mode="tilt")
    check("tilt: no regimes, no pass", mt0["verdict"] != "pass")
    x_ = np.r_[np.random.default_rng(1).normal(-0.05, 0.02, 60), np.random.default_rng(2).normal(0.05, 0.02, 60)]
    hp = _hmm2_fit(x_)
    check("hmm2 recovers two separated means", hp["mu"][0] < -0.03 and hp["mu"][1] > 0.03)
    # state mode on synthetic trades whose edge sign follows a synthetic BTC trend: advol must find it
    days = pd.date_range("2019-01-01", "2026-10-26", freq="1D", tz="UTC")
    rng_ = np.random.default_rng(5)
    regime = np.repeat(rng_.choice([1.0, -1.0], size=len(days) // 60 + 1), 60)[:len(days)]
    btc_ = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng_.normal(0, 0.01, len(days)))), index=days)
    trd = _synthetic(persistent=False)
    up = btc_ > btc_.rolling(50).mean()
    sgn = np.where(trd.direction == "long", 1.0, -1.0)
    st = up.reindex(trd.ts.dt.floor("D")).fillna(False).to_numpy()
    trd = trd.assign(net_r=trd.net_r + 0.3 * sgn * np.where(st, 1.0, -1.0))
    ms_ = run(trd, level="symbol", mode="state", btc=btc_)
    check("state mode: a trend-conditioned edge is found by advol", ms_["arms"]["advol"]["delta"] > 0.02
          and ms_["arms"]["advol"]["random"]["share_ge_arm"] <= 0.05)
    check("verdict mapping", unit_verdict({"a": "fail", "b": "indeterminate"}) == "indeterminate" and unit_verdict({"a": "fail", "b": "fail"}) == "fail")
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
