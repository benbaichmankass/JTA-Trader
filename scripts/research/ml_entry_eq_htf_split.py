#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261112-8d20-02.yaml (the instrument its blocked_on names), run.command via research-script-run.yml
"""RQ-20261112-8d20-02: do ml_entry_eq_struct's LONG decisions taken AGAINST a strong DAILY downtrend lose, net of cost?

WHY THIS EXISTS. The unit's blocked_on: "NO DECISION-LEVEL DUMP. ml_entry_equity.py confirm/structure stages write aggregates
only ... Needs a subcommand that refits the graded ensemble (config B, seeds 1-5, rows <= 2025-06-30), scores 2025-07-15..2026-10-31
at tau 0.25 and splits the taken decisions by the daily DMI/ADX, reusing ml_entry_htf_trend_split.cell_stats." This is that
instrument, as its own module so the graded ml_entry_equity.py stages stay byte-identical. Everything that defines the model and its
labels is IMPORTED from ml_entry_equity.py (pool, bars, table with the live structure exit, purge, the pinned ensemble, the session
gate, the restricted-long take rule); nothing is re-implemented.

REPRODUCTION CHECK (gating the read). The refit's booster sha256 (concatenated texts, the confirm stage's rule) must start with the
graded run's 0afc49948a41671a (ml/candidates/ml_entry_eq_v3_struct_ens5/model.json::confirm_booster_sha256_expected). On a mismatch
the unit writes read_state measured, verdict indeterminate, "the graded model did not reproduce", and does NOT read the cells.

DAILY CONTEXT (point in time). Daily bars = the RTH 1h bars of each session, grouped by the America/New_York date of the bar close.
A decision on day d sees only sessions with date < d. Indicators: Wilder DMI/ADX14, EMA20 vs EMA50 (robustness, reported).
A long is AGAINST when sign(+DI - -DI) = -1. ADX buckets < 25, 25..40, > 40.

RULE (the unit's, RULE-RQ20261112-8d20-02-HTF-CT-EQ, registered 2026-11-12): primary cell CT40 = AGAINST and daily ADX14 > 40.
INDETERMINATE if CT40 n < 40. PASS if CT40 mean net R < 0 AND decision-date-clustered t <= -2.0 AND the WITH, ADX > 40 cell mean >=
CT40 mean. FAIL otherwise.

Tier-1 research tooling: read-only Alpaca market data (runner secrets), writes only under --out. No config, roster or order path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import holdout_lock as HL  # noqa: E402
import ml_entry_equity as Q  # noqa: E402
from ml_entry_htf_trend_split import BUCKETS, cell_stats  # noqa: E402

RULE_ID = "RULE-RQ20261112-8d20-02-HTF-CT-EQ"
CONFIG = "B"
SEEDS = [1, 2, 3, 4, 5]
TAU = 0.25
START, END = Q.CONFIRM_START, "2026-10-31"
EXPECT_SHA = "0afc49948a41671a"
ADX_N = 14
N_MIN = 40
T_BAR = -2.0


def daily_frame(df1h: pd.DataFrame) -> pd.DataFrame:
    """Daily indicators keyed by NY session date (the date the indicator is KNOWN AT END OF)."""
    d = df1h.assign(day=pd.to_datetime(df1h.close_ts, utc=True).dt.tz_convert("America/New_York").dt.date)
    g = d.groupby("day")
    b = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    h, lo, c = b.high, b.low, b.close
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -lo.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=b.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=b.index)
    a = 1.0 / ADX_N
    atr = tr.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean()
    pdi = 100 * pdm.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean() / atr
    mdi = 100 * mdm.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean()
    ema20, ema50 = c.ewm(span=20, adjust=False, min_periods=20).mean(), c.ewm(span=50, adjust=False, min_periods=50).mean()
    return pd.DataFrame({"adx": adx, "dmi_dir": np.sign(pdi - mdi), "ema_dir": np.sign(ema20 - ema50)})


def attach_daily(taken: pd.DataFrame, daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """For each decision, the indicator row of the LAST session strictly before the decision's NY date."""
    if taken.empty:
        return taken.assign(adx=np.nan, dmi_dir=np.nan, ema_dir=np.nan, align_dmi="none", align_ema="none", adx_bucket="nan")
    parts = []
    for sym, g in taken.groupby("symbol", sort=False):
        f = daily.get(sym)
        dday = pd.to_datetime(g.ts, utc=True).dt.tz_convert("America/New_York").dt.date
        if f is None or f.empty:
            parts.append(g.assign(adx=np.nan, dmi_dir=np.nan, ema_dir=np.nan))
            continue
        days = np.array(f.index)
        idx = np.searchsorted(days, dday.to_numpy(), side="left") - 1     # strictly before
        ok = idx >= 0
        vals = {k: np.where(ok, f[k].to_numpy()[np.clip(idx, 0, None)], np.nan) for k in f.columns}
        parts.append(g.assign(**vals))
    t = pd.concat(parts, ignore_index=True)
    for k in ("dmi", "ema"):   # long-only leg: with = dir +1, against = dir -1
        t[f"align_{k}"] = np.where(t[f"{k}_dir"].isna() | (t[f"{k}_dir"] == 0), "none",
                                   np.where(t[f"{k}_dir"] > 0, "with", "against"))
    t["adx_bucket"] = pd.cut(t.adx, [b[1] for b in BUCKETS] + [np.inf], labels=[b[0] for b in BUCKETS], right=True).astype(str)
    return t


def clustered_by_date(x: pd.DataFrame) -> dict:
    """cell_stats plus the rule's DECISION-DATE clustered t (CR1 on the NY date)."""
    out = cell_stats(x)
    n = len(x)
    if n > 1:
        r = x.net_r.to_numpy(float)
        m = r.mean()
        day = pd.to_datetime(x.ts, utc=True).dt.tz_convert("America/New_York").dt.date.to_numpy()
        res = pd.Series(r - m).groupby(day).sum().to_numpy()
        G = len(res)
        if G > 1:
            se = float(np.sqrt((res ** 2).sum() * G / (G - 1)) / n)
            out.update({"n_date_clusters": G, "se_date_clustered": round(se, 4), "t_date_clustered": round(m / se, 2) if se > 0 else None})
    return out


def grid(t: pd.DataFrame, col: str) -> dict:
    g = {}
    for a in ("with", "against"):
        for name, _, _ in BUCKETS:
            g[f"{a}_{name}"] = clustered_by_date(t[(t[col] == a) & (t.adx_bucket == name)])
        g[f"{a}_all"] = clustered_by_date(t[t[col] == a])
    g["unclassified"] = clustered_by_date(t[(t[col] == "none") | (t.adx_bucket == "nan")])
    return g


def judge(g: dict) -> dict:
    ct, w = g["against_gt40"], g["with_gt40"]
    if ct["n"] < N_MIN:
        return {"verdict": "indeterminate", "why": f"CT40 n={ct['n']} < {N_MIN}: underpowered (the unit's expected outcome), no change"}
    t = ct.get("t_date_clustered")
    neg = ct["mean_net_r"] < 0 and t is not None and t <= T_BAR
    worse = w["mean_net_r"] is not None and w["mean_net_r"] >= ct["mean_net_r"]
    if neg and worse:
        return {"verdict": "pass", "why": f"CT40 mean {ct['mean_net_r']} at n={ct['n']}, date-clustered t {t} <= {T_BAR}; WITH>40 mean "
                                          f"{w['mean_net_r']} >= CT40 -> Tier-3 proposal held for the manager"}
    return {"verdict": "fail", "why": f"CT40 mean {ct['mean_net_r']} at n={ct['n']}, date-clustered t {t}; WITH>40 mean {w['mean_net_r']}: "
                                      "not a losing slice by the registered rule"}


def score(tab: pd.DataFrame) -> tuple[pd.DataFrame, str, int]:
    feats = Q.CONFIGS[CONFIG]["features"]
    params = {**Q.CONFIGS[CONFIG]["params"], "_ens_seeds": SEEDS}
    te = pd.Timestamp(Q.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    tr = Q.purge(tab[tab.ts < te], te).dropna(subset=feats + ["net_long"])
    m = Q._lgb(params).fit(tr[feats], tr["net_long"])
    sha = hashlib.sha256("".join(x.booster_.model_to_string() for x in m.models).encode()).hexdigest()
    hs, he = pd.Timestamp(START, tz="UTC"), pd.Timestamp(END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].dropna(subset=feats + ["net_long"])
    test = test[Q.session_mask(test.ts)]
    pred = m.predict(test[feats])  # provenance: predict -- the regressed LONG net R, not a probability
    return Q.taken_trades(test, pred, TAU), sha, len(tr)


def run(a) -> int:
    from src.runtime.execution_costs import (
        resolve_cost_policy,
        resolve_fee_bps_roundtrip,
    )
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    slip, _ = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    pool, _prep, bars, client = Q._pool_and_bars(a, END)
    tab = Q.build_table(bars, pool, slip, fee, struct=Q.STRUCT_SPEC)
    print(f"[table] {len(tab)} rows, {tab.symbol.nunique()} symbols t={time.time() - t0:.0f}s", flush=True)
    claim = None
    if not a.no_ledger:   # a re-cut of an already-graded window is still a READ: record it before scoring
        ledger = out / "ledger" / "holdout_reads.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        if HL.LEDGER.exists() and not ledger.exists():
            shutil.copy(HL.LEDGER, ledger)
        claim = HL.claim_read("ENTRY-EQ-v3-STRUCT-ENS5-htf-split", START, END, a.unit, "lane ML standing p3 (research-script-run)",
                              ledger=ledger, symbols=pool, train_end=Q.TRAIN_END, family=Q.FAMILY)
    taken, sha, n_train = score(tab)
    base = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured",
            "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-12", "registered_before_run": True},
            "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "population": (f"ml_entry_eq_struct (config B, 5-seed pinned ensemble, tau {TAU}) restricted-LONG decisions on the {len(pool)}-ETF "
                           f"Alpaca pool, confirming window {START}..{END}, structure exit {Q.STRUCT_SPEC}, net of fee {fee} + slip {slip} + "
                           f"regulatory {Q.S.REGULATORY_BPS} bps; split by the DAILY DMI/ADX14 of the last session before the decision day"),
            "produced_by": {"tool": "python3 scripts/research/ml_entry_eq_htf_split.py", "where": a.where}}
    if not sha.startswith(EXPECT_SHA):
        row = {**base, "verdict": "indeterminate", "n": None,
               "note": f"the graded model did not reproduce: refit sha {sha[:16]} != {EXPECT_SHA}; cells NOT read",
               "measurement": {"booster_sha256": sha, "expected": EXPECT_SHA, "train_rows": n_train, "holdout_claim": claim}}
    else:
        daily = {s: daily_frame(bars[s]) for s in pool if s in bars}
        t = attach_daily(taken, daily)
        g_dmi, g_ema = grid(t, "align_dmi"), grid(t, "align_ema")
        j = judge(g_dmi)
        row = {**base, "verdict": j["verdict"], "note": j["why"], "n": g_dmi["against_gt40"]["n"],
               "measurement": {"booster_sha256": sha, "sha_match": True, "train_rows": n_train, "all": clustered_by_date(t),
                               "primary_dmi": g_dmi, "robust_ema": g_ema, "judge": j, "holdout_claim": claim,
                               "alpaca_calls": client.calls, "runtime_s": round(time.time() - t0, 1)}}
        t.to_csv(out / "decisions.csv.gz", index=False)
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{row['verdict'].upper()}: {row['note']}", flush=True)
    return 0


def self_test() -> int:
    """Point-in-time daily attach: a decision on day d must read the indicators of day d-1 (never d)."""
    days = pd.bdate_range("2024-01-02", periods=80, tz="America/New_York")
    rows = []
    rng = np.random.default_rng(3)
    px = 100.0
    for d in days:
        for hh in range(10, 17):
            px *= 1 + rng.normal(-0.002, 0.004)    # steady downtrend -> -DI > +DI
            ct = d + pd.Timedelta(hours=hh)
            rows.append({"close_ts": ct.tz_convert("UTC"), "open": px, "high": px * 1.002, "low": px * 0.998, "close": px})
    df = pd.DataFrame(rows)
    f = daily_frame(df)
    assert f.dmi_dir.dropna().iloc[-1] == -1.0
    dec_day = days[60]
    tk = pd.DataFrame({"symbol": ["X"], "ts": [(dec_day + pd.Timedelta(hours=12)).tz_convert("UTC")], "net_r": [-0.5]})
    t = attach_daily(tk, {"X": f})
    prev = days[59].date()
    assert abs(t.adx.iloc[0] - f.loc[prev, "adx"]) < 1e-12, "must read the PREVIOUS session"
    assert t.align_dmi.iloc[0] == "against"
    x = pd.DataFrame({"symbol": ["X"] * 50, "ts": [(days[i % 40] + pd.Timedelta(hours=12)).tz_convert("UTC") for i in range(50)],
                      "net_r": rng.normal(-0.3, 1.0, 50)})
    s = clustered_by_date(x)
    assert s["n"] == 50 and s["n_date_clusters"] == 40
    g = {"against_gt40": {"n": 10, "mean_net_r": -1.0}, "with_gt40": {"n": 10, "mean_net_r": 0.0}}
    assert judge(g)["verdict"] == "indeterminate"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cache", default="/tmp/ml_entry_equity")
    ap.add_argument("--out")
    ap.add_argument("--unit", default="RQ-20261112-8d20-02")
    ap.add_argument("--where", default="local")
    ap.add_argument("--no-ledger", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.out:
        ap.error("--out is required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
