#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-8d20-01.yaml (row ML-ENTRY-HTF-COUNTERTREND)
"""Split the frozen crypto ENTRY v1 (ml_entry) decisions by 4h trend alignment and 4h ADX bucket (Tier-1 research).

Pre-registered rule: research/queue/RQ-20261112-8d20-01.yaml (RULE-RQ20261112-8d20-01-HTF-CT). Everything that decides a
trade -- labels, features, the one-position-per-symbol policy, the full cost stack -- is imported from
scripts/research/ml_decision_entry.py (the harness ml_entry's evidence RQ-20261101-c692-01 uses), unchanged. This script
only ADDS 4h context at each decision and groups the taken decisions.

4h context (point in time): the 1h bars are resampled to 4h bars starting at UTC 00/04/08/...; a decision is made at the
close of a 1h bar whose close hour is a multiple of 4, so the 4h bar that has just closed starts at ``ts - 3h`` (``ts`` is
the decision bar's open time). Only that bar and earlier 4h bars feed the indicators.

* PRIMARY: direction D = sign(+DI14 - -DI14), strength ADX14 (Wilder smoothing, alpha 1/14).
* r1 (reported): sign(EMA20 - EMA50) of the 4h close.
* r2 (reported): Donchian-20 state: +1 after a 4h close above the prior 20-bar high, -1 after one below the prior 20-bar low,
  held until the opposite break.

Populations: A held-out 2025-10-01..2026-09-29 (frozen artifact; ledger read recorded), B dev walk-forward OOS folds (the
c692-01 recipe refit per fold, tau 0.1), C forward 2026-10-01..2026-10-30 (frozen artifact; ledger read recorded).

    python3 scripts/research/ml_entry_htf_trend_split.py --self-test
    python3 scripts/research/ml_entry_htf_trend_split.py --cache /tmp/ml_decision_klines --unit RQ-20261112-8d20-01 --out /tmp/o
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E

SCHEMA = "ml_entry_htf_trend_split/1"
RULE_ID = "RULE-RQ20261112-8d20-01-HTF-CT"
SERVED = REPO / "ml/served/ml_decision_entry_v1/model.json"
FETCH_END = "2026-10-31"
A_START, A_LAST_TS = "2025-10-01", "2026-09-29 23:00"     # last decision whose 24h label ends inside September (as c692-01)
C_START, C_LAST_TS = "2026-10-01", "2026-10-30 23:00"
TAU = 0.1
ADX_N = 14
N_MIN = 40
T_BAR = -2.0
BYBIT2 = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
BUCKETS = [("lt25", -np.inf, 25.0), ("25to40", 25.0, 40.0), ("gt40", 40.0, np.inf)]


# ------------------------------------------------------------------------------------------------ 4h context
def htf_frame(df1h: pd.DataFrame) -> pd.DataFrame:
    """4h indicators keyed by the 4h bar's START time. Incomplete 4h bars (fewer than 4 hourly bars) are dropped."""
    g = df1h.set_index("ts").resample("4h", label="left", closed="left", origin="epoch")
    b = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "n": g["close"].count()})
    b = b[b.n == 4].drop(columns="n")
    h, lo, c = b.high, b.low, b.close
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -lo.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = 1.0 / ADX_N
    atr = tr.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean()
    pdi = 100 * pd.Series(pdm, index=b.index).ewm(alpha=a, adjust=False, min_periods=ADX_N).mean() / atr
    mdi = 100 * pd.Series(mdm, index=b.index).ewm(alpha=a, adjust=False, min_periods=ADX_N).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=a, adjust=False, min_periods=ADX_N).mean()
    ema20, ema50 = c.ewm(span=20, adjust=False, min_periods=20).mean(), c.ewm(span=50, adjust=False, min_periods=50).mean()
    hi20, lo20 = h.rolling(20).max().shift(1), lo.rolling(20).min().shift(1)
    brk = pd.Series(np.where(c > hi20, 1.0, np.where(c < lo20, -1.0, np.nan)), index=b.index).ffill()
    out = pd.DataFrame({"adx": adx, "dmi_dir": np.sign(pdi - mdi), "ema_dir": np.sign(ema20 - ema50), "don_dir": brk})
    # a 4h bar is non-contiguous with its predecessor across a data hole; the smoothed values still only use the past
    return out


def attach_htf(taken: pd.DataFrame, htf: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if taken.empty:
        return taken.assign(adx=np.nan, dmi_dir=np.nan, ema_dir=np.nan, don_dir=np.nan)
    parts = []
    for sym, g in taken.groupby("symbol", sort=False):
        key = pd.to_datetime(g.ts, utc=True) - pd.Timedelta(hours=3)
        f = htf[sym].reindex(key)
        parts.append(g.assign(**{k: f[k].to_numpy() for k in f.columns}))
    t = pd.concat(parts, ignore_index=True)
    side = np.where(t.side == "long", 1.0, -1.0)
    for d in ("dmi", "ema", "don"):
        t[f"align_{d}"] = np.where(t[f"{d}_dir"].isna() | (t[f"{d}_dir"] == 0), "none",
                                   np.where(side == t[f"{d}_dir"], "with", "against"))
    t["adx_bucket"] = pd.cut(t.adx, [b[1] for b in BUCKETS] + [np.inf], labels=[b[0] for b in BUCKETS], right=True).astype(str)
    return t


# ------------------------------------------------------------------------------------------------ statistics
def cell_stats(x: pd.DataFrame) -> dict:
    n = len(x)
    if n == 0:
        return {"n": 0, "mean_net_r": None}
    r = x.net_r.to_numpy(float)
    m = float(r.mean())
    out = {"n": n, "mean_net_r": round(m, 4), "sum_net_r": round(float(r.sum()), 2), "n_ts_clusters": int(x.ts.nunique()),
           "n_symbols": int(x.symbol.nunique())}
    if n > 1:
        se = float(r.std(ddof=1) / np.sqrt(n))
        out.update({"se_iid": round(se, 4), "t_iid": round(m / se, 2) if se > 0 else None})
        res = pd.Series(r - m).groupby(x.ts.to_numpy()).sum().to_numpy()
        G = len(res)
        if G > 1:
            sec = float(np.sqrt((res ** 2).sum() * G / (G - 1)) / n)     # CR1 cluster-robust SE of the mean, clustered on decision time
            out.update({"se_ts_clustered": round(sec, 4), "t_ts_clustered": round(m / sec, 2) if sec > 0 else None})
    return out


def grid(t: pd.DataFrame, align_col: str) -> dict:
    g = {}
    for a in ("with", "against"):
        for name, _, _ in BUCKETS:
            g[f"{a}_{name}"] = cell_stats(t[(t[align_col] == a) & (t.adx_bucket == name)])
        g[f"{a}_all"] = cell_stats(t[t[align_col] == a])
    g["unclassified"] = cell_stats(t[(t[align_col] == "none") | (t.adx_bucket == "nan")])
    return g


def by_side(t: pd.DataFrame, cell: pd.Series) -> dict:
    return {s: cell_stats(t[cell & (t.side == s)]) for s in ("long", "short")}


def filter_effect(t: pd.DataFrame, drop: pd.Series) -> dict:
    return {"before": cell_stats(t), "after": cell_stats(t[~drop]), "n_removed": int(drop.sum()),
            "sum_removed": round(float(t.net_r[drop].sum()), 2)}


def population(t: pd.DataFrame) -> dict:
    ct40 = (t.align_dmi == "against") & (t.adx_bucket == "gt40")
    ct25 = (t.align_dmi == "against") & (t.adx_bucket == "25to40")
    b2 = t[t.symbol.isin(BYBIT2)]
    return {"all": cell_stats(t), "primary_dmi": grid(t, "align_dmi"), "r1_ema": grid(t, "align_ema"), "r2_donchian": grid(t, "align_don"),
            "ct40_by_side": by_side(t, ct40), "filter_ct40": filter_effect(t, ct40), "filter_ct40_ct25": filter_effect(t, ct40 | ct25),
            "bybit2_slice": {"all": cell_stats(b2), "primary_dmi": grid(b2, "align_dmi")} if len(b2) else None}


def judge(cell: str, A: dict, B: dict) -> dict:
    a, b = A["primary_dmi"][f"against_{cell}"], B["primary_dmi"][f"against_{cell}"]
    w = A["primary_dmi"]["with_gt40"]
    if a["n"] < N_MIN:
        return {"verdict": "indeterminate", "why": f"A n {a['n']} < {N_MIN}"}
    c1 = a["mean_net_r"] < 0 and (a.get("t_ts_clustered") or 0) <= T_BAR
    c2 = w["mean_net_r"] is not None and w["mean_net_r"] >= a["mean_net_r"]
    c3 = b["mean_net_r"] is not None and b["mean_net_r"] < 0
    why = (f"(1) A mean {a['mean_net_r']} t_cl {a.get('t_ts_clustered')} n {a['n']} -> {c1}; (2) A with_gt40 {w['mean_net_r']} >= "
           f"{a['mean_net_r']} -> {c2}; (3) B mean {b['mean_net_r']} n {b['n']} < 0 -> {c3}")
    return {"verdict": "pass" if (c1 and c2 and c3) else "fail", "why": why, "clauses": [c1, c2, c3]}


# ------------------------------------------------------------------------------------------------ run
def _frozen():
    meta, models = E._frozen_models(SERVED)
    feats = meta["features"] if isinstance(meta["features"], list) else json.loads(meta["features"].replace("'", '"'))
    assert abs(float(meta["tau"]) - TAU) < 1e-12, meta["tau"]
    return meta, models, feats


def score_frozen(tab: pd.DataFrame, models, feats, start: str, last_ts: str) -> pd.DataFrame:
    w = tab[(tab.ts >= pd.Timestamp(start, tz="UTC")) & (tab.ts <= pd.Timestamp(last_ts, tz="UTC"))]
    # provenance: predict — Booster.predict is the regressed net R of that side, not a probability
    return E.policy(w, models["long"].predict(w[feats]), models["short"].predict(w[feats]), TAU)


def dev_oos(tab: pd.DataFrame) -> pd.DataFrame:
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [hs]
    out = []
    for a, b in itertools.pairwise(bounds):
        test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=E.HORIZON_H + 1))]
        pl, ps = E.fit_predict(E.purge_train(dev, a), test)
        tk = E.policy(test, pl, ps, TAU)
        print(json.dumps({"fold": str(a.date()), "n": len(tk), "mean": round(float(tk.net_r.mean()), 4)}), flush=True)
        out.append(tk)
    return pd.concat(out, ignore_index=True)


def run(a) -> int:
    t0 = time.time()
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = E.universe()
    rep = E.fetch(cache, syms, end=FETCH_END)
    tab = E.build_table(cache, syms)
    htf = {s: htf_frame(pd.read_pickle(cache / f"{s}.pkl").reset_index(drop=True)) for s in syms}
    meta, models, feats = _frozen()
    claims = {}
    if not a.no_ledger:
        import holdout_lock
        for (s, e) in ((A_START, A_LAST_TS[:10]), (C_START, C_LAST_TS[:10])):
            claims[f"{s}..{e}"] = holdout_lock.claim_read("ENTRY-v1-htf-split", s, e, a.unit, a.reader, holdout_lock.LEDGER,
                                                          train_end=str(meta["train_end_exclusive"])[:10], family="ENTRY")
    A = attach_htf(score_frozen(tab, models, feats, A_START, A_LAST_TS), htf)
    C = attach_htf(score_frozen(tab, models, feats, C_START, C_LAST_TS), htf)
    print(f"A n={len(A)} mean={A.net_r.mean():.4f} C n={len(C)} t={time.time()-t0:.0f}s", flush=True)
    B = attach_htf(dev_oos(tab), htf)
    PA, PB, PC = population(A), population(B), population(C)
    j40, j25 = judge("gt40", PA, PB), judge("25to40", PA, PB)
    verdict = j40["verdict"]
    res = {"schema": SCHEMA, "unit": a.unit, "rule_id": RULE_ID, "git_sha": E._git_sha(), "tau": TAU, "served": str(SERVED.relative_to(REPO)),
           "train_end_exclusive": meta["train_end_exclusive"], "fetch_rows": {k: v.get("rows") for k, v in rep.items()},
           "holdout_claims": claims, "A_heldout": PA, "B_dev_oos": PB, "C_forward": PC,
           "judge_ct40": j40, "judge_ct25": j25, "verdict": verdict, "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    for name, t in (("A", A), ("B", B), ("C", C)):
        t.to_csv(out / f"decisions_{name}.csv.gz", index=False)
    vj = {"verdict": verdict, "read_state": "measured", "n": PA["primary_dmi"]["against_gt40"]["n"], "note": j40["why"],
          "population": ("frozen ml_decision_entry_v1 (tau 0.1) decisions, 60-perp bp2 universe, reference bracket 2/3 ATR 24h, net of fee 11 + "
                         "slip 3 bps + funding 1 bps/8h; A held-out 2025-10-01..2026-09-29, B dev walk-forward OOS 2022-01..2025-09, "
                         "C forward 2026-10; split by 4h DMI direction x 4h ADX14 bucket"),
          "measurement": {"ct40_A": PA["primary_dmi"]["against_gt40"], "ct40_B": PB["primary_dmi"]["against_gt40"],
                          "ct40_C": PC["primary_dmi"]["against_gt40"], "with_gt40_A": PA["primary_dmi"]["with_gt40"],
                          "judge_ct40": j40, "judge_ct25": j25}}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": verdict, "why": j40["why"], "ct25": j25}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def self_test() -> int:
    idx = pd.date_range("2024-01-01", periods=24 * 40, freq="1h", tz="UTC")
    up = pd.DataFrame({"ts": idx, "open": np.arange(len(idx)) + 100.0})
    up["close"] = up.open + 0.9
    up["high"], up["low"] = up.close + 0.1, up.open - 0.1
    f = htf_frame(up)
    assert f.adx.iloc[-1] > 40 and f.dmi_dir.iloc[-1] == 1 and f.ema_dir.iloc[-1] == 1 and f.don_dir.iloc[-1] == 1, f.tail(2)
    # point in time: the decision at the 1h bar opening 03:00 (close 04:00) reads the 4h bar starting 00:00
    ts = pd.Timestamp("2024-01-20 03:00", tz="UTC")
    tk = pd.DataFrame({"symbol": ["X", "X"], "ts": [ts, ts + pd.Timedelta(hours=4)], "side": ["short", "long"], "net_r": [-1.0, 1.5]})
    t = attach_htf(tk, {"X": f})
    assert t.adx.iloc[0] == f.adx.loc[pd.Timestamp("2024-01-20 00:00", tz="UTC")]
    assert list(t.align_dmi) == ["against", "with"] and list(t.adx_bucket) == ["gt40", "gt40"], t
    s = cell_stats(pd.DataFrame({"ts": [1, 1, 2, 2, 3], "symbol": list("abcab"), "net_r": [-1, -1, 1, 1, -1.0]}))
    assert s["n"] == 5 and s["n_ts_clusters"] == 3 and s["se_ts_clustered"] > s["se_iid"], s
    print("self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_htf_split")
    ap.add_argument("--unit", default="RQ-20261112-8d20-01")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--no-ledger", action="store_true", help="skip recording the held-out reads (tests only)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    return self_test() if a.self_test else run(a)


if __name__ == "__main__":
    raise SystemExit(main())
