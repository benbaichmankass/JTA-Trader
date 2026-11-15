#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-a7e8-03.yaml (row ML-DECISION-LABEL-VOL-CONFOUND), run.command via research-script-run.yml
"""Is the served ml_decision_entry selecting symbols by COST PER R (volatility) rather than by direction?

WHY THIS EXISTS (row ML-DECISION-LABEL-VOL-CONFOUND, due 2026-11-18). FEATURE-IMPACT M2 (PR #24996 scratch run, 60 symbols,
2020-07..2026-09): the net_long label ranks cross-sectionally on atr_pct (+0.486) and vol24 (+0.423), while the raw 24h forward
return ranks slightly the OTHER way (atr_pct -0.084). net R = gross R - cost_bps / stop distance, so a wide-ATR symbol pays less
cost per R. The row asks for a committed read that "decomposes the served model's held-out net R into a vol-bucket tilt vs
within-bucket ranking" and "checks whether the gross-R label shows the same".

THE DECOMPOSITION (Brinson-style, exact). For every TAKEN decision k (served model v1, tau 0.1, held-out window A of
RQ-20261112-8d20-01: 2025-10-01..2026-09-29) with side s at decision time ts:
  pool(ts, s)      = every candidate row at ts with a label on side s (the whole universe, not only free symbols)
  bucket b_k       = the atr_pct tercile of k's symbol within pool(ts, s) (cross-sectional, point in time)
  excess_k = r_k - mean(pool)                         = tilt_k + select_k
  tilt_k   = mean(pool in b_k) - mean(pool)            (what picking that VOLATILITY bucket earned)
  select_k = r_k - mean(pool in b_k)                   (what picking that symbol WITHIN its bucket earned)
computed in net R and in gross R (cost removed). Means are over k; t statistics are clustered on ts (CR1).

RULE (registered in the unit before any run; restated, not re-decided here):
  INDETERMINATE if n taken < 100, or the mean net excess <= 0 (nothing to attribute; reported).
  CONFOUND (verdict "pass" = the row's hypothesis holds) iff tilt_net / excess_net >= 0.5 AND the gross within-bucket selection
    is not positive at ts-clustered t >= 2.0.
  DIRECTION (verdict "fail" = hypothesis rejected) iff the gross within-bucket selection mean > 0 at ts-clustered t >= 2.0.
  INDETERMINATE otherwise (named).

Tier-1 research tooling: public Binance Vision candles, the frozen served booster read-only, writes only under --out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E  # noqa: E402
import ml_entry_htf_trend_split as H  # noqa: E402

RULE_ID = "RULE-RQ20261112-a7e8-03-VOL-DECOMP"
N_MIN = 100
SHARE = 0.5
T_BAR = 2.0


def _t_clustered(v: np.ndarray, ts: np.ndarray) -> dict:
    n = len(v)
    if n < 2:
        return {"n": n, "mean": float(v.mean()) if n else None, "t_ts_clustered": None}
    m = float(v.mean())
    res = pd.Series(v - m).groupby(ts).sum().to_numpy()
    G = len(res)
    se = float(np.sqrt((res ** 2).sum() * G / (G - 1)) / n) if G > 1 else None
    return {"n": n, "mean": round(m, 4), "se_ts_clustered": None if se is None else round(se, 4),
            "t_ts_clustered": round(m / se, 2) if se else None, "n_ts_clusters": G}


def decompose(window: pd.DataFrame, taken: pd.DataFrame) -> dict:
    """window: every candidate row (symbol, ts, atr_pct, net_long/short, gross_long/short); taken: (symbol, ts, side, net_r, gross_r)."""
    rows = []
    for side in ("long", "short"):
        tk = taken[taken.side == side]
        if tk.empty:
            continue
        pool = window[["symbol", "ts", "atr_pct", f"net_{side}", f"gross_{side}"]].dropna()
        pool = pool.rename(columns={f"net_{side}": "net", f"gross_{side}": "gross"})
        pool["bucket"] = pool.groupby("ts")["atr_pct"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 3, labels=False) if len(x) >= 3 else np.nan)
        allm = pool.groupby("ts")[["net", "gross"]].mean().add_prefix("all_")
        bm = pool.groupby(["ts", "bucket"])[["net", "gross"]].mean().add_prefix("b_").reset_index()
        k = tk.merge(pool[["symbol", "ts", "bucket"]], on=["symbol", "ts"], how="left")
        k = k.join(allm, on="ts").merge(bm, on=["ts", "bucket"], how="left")
        rows.append(k.assign(side=side))
    if not rows:
        return {"n": 0}
    k = pd.concat(rows, ignore_index=True).dropna(subset=["bucket", "all_net", "b_net"])
    ts = k.ts.astype("int64").to_numpy() if hasattr(k.ts, "astype") else k.ts.to_numpy()
    out = {"n": len(k), "n_dropped_unbucketed": int(len(taken) - len(k)),
           "taken_bucket_mix": {str(int(b)): int(c) for b, c in k.bucket.value_counts().sort_index().items()}}
    for lab in ("net", "gross"):
        r = k[f"{lab}_r"].to_numpy(float)
        ex = r - k[f"all_{lab}"].to_numpy(float)
        tilt = k[f"b_{lab}"].to_numpy(float) - k[f"all_{lab}"].to_numpy(float)
        sel = r - k[f"b_{lab}"].to_numpy(float)
        out[lab] = {"taken_mean": _t_clustered(r, ts), "excess": _t_clustered(ex, ts), "tilt": _t_clustered(tilt, ts),
                    "select": _t_clustered(sel, ts),
                    "tilt_share": (round(float(tilt.mean() / ex.mean()), 4) if ex.mean() != 0 else None)}
    out["by_side"] = {s: int((k.side == s).sum()) for s in ("long", "short")}
    return out


def judge(d: dict) -> dict:
    if d.get("n", 0) < N_MIN:
        return {"verdict": "indeterminate", "why": f"n taken {d.get('n', 0)} < {N_MIN}"}
    net, gross = d["net"], d["gross"]
    if net["excess"]["mean"] is None or net["excess"]["mean"] <= 0:
        return {"verdict": "indeterminate", "why": f"mean net excess over the pool {net['excess']['mean']} <= 0: nothing to attribute"}
    gs, gt = gross["select"]["mean"], gross["select"]["t_ts_clustered"]
    direction = gs is not None and gs > 0 and gt is not None and gt >= T_BAR
    share = net["tilt_share"]
    if direction:
        return {"verdict": "fail", "why": f"DIRECTION: gross within-bucket selection {gs} at t {gt} >= {T_BAR} (tilt share of net excess {share})"}
    if share is not None and share >= SHARE:
        return {"verdict": "pass", "why": f"CONFOUND: tilt share of net excess {share} >= {SHARE}; gross within-bucket selection {gs} (t {gt}) not >= {T_BAR}"}
    return {"verdict": "indeterminate", "why": f"tilt share {share} < {SHARE} and gross selection {gs} (t {gt}) not significant"}


def run(a) -> int:
    t0 = time.time()
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = E.universe()
    E.fetch(cache, syms, end=H.FETCH_END)
    tab = E.build_table(cache, syms)
    meta, models, feats = H._frozen()
    claim = None
    if not a.no_ledger:
        import holdout_lock
        claim = holdout_lock.claim_read("ENTRY-v1-vol-decomp", H.A_START, H.A_LAST_TS[:10], a.unit, a.reader, holdout_lock.LEDGER,
                                        train_end=str(meta["train_end_exclusive"])[:10], family="ENTRY")
    w = tab[(tab.ts >= pd.Timestamp(H.A_START, tz="UTC")) & (tab.ts <= pd.Timestamp(H.A_LAST_TS, tz="UTC"))]
    taken = H.score_frozen(tab, models, feats, H.A_START, H.A_LAST_TS)
    d = decompose(w, taken)
    j = judge(d)
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": j["verdict"], "note": j["why"],
           "n": d.get("n"), "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-12", "registered_before_run": True},
           "population": (f"frozen ml_decision_entry_v1 (tau {H.TAU}) taken decisions on the {len(syms)}-perp universe, held-out "
                          f"{H.A_START}..{H.A_LAST_TS[:10]}; pool = every candidate row at the same decision time and side; atr_pct terciles"),
           "measurement": {**d, "judge": j, "holdout_claim": claim, "git_sha": E._git_sha(), "runtime_s": round(time.time() - t0)},
           "produced_by": {"tool": "python3 scripts/research/ml_decision_vol_decomp.py", "where": a.reader}}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{j['verdict'].upper()}: {j['why']}", flush=True)
    return 0


def self_test() -> int:
    """A planted pure vol tilt (high-ATR rows earn more NET R only through lower cost) must read CONFOUND; a planted
    within-bucket gross pick must read DIRECTION; the decomposition must be exact (excess = tilt + select)."""
    rng = np.random.default_rng(11)
    ts = pd.date_range("2025-10-01", periods=300, freq="4h", tz="UTC")
    rows = []
    for t in ts:
        for s in range(30):
            atr = 0.005 + 0.001 * s
            g = rng.normal(0, 0.3)
            rows.append({"symbol": f"S{s}", "ts": t, "atr_pct": atr, "gross_long": g, "net_long": g - 0.0011 / atr,
                         "gross_short": -g, "net_short": -g - 0.0011 / atr})
    w = pd.DataFrame(rows)
    hi = w[w.atr_pct >= w.atr_pct.quantile(0.8)].groupby("ts").head(2)       # take high-ATR names at random
    tk = hi.assign(side="long", net_r=hi.net_long, gross_r=hi.gross_long)[["symbol", "ts", "side", "net_r", "gross_r"]]
    d = decompose(w, tk)
    for lab in ("net", "gross"):
        assert abs(d[lab]["excess"]["mean"] - d[lab]["tilt"]["mean"] - d[lab]["select"]["mean"]) < 1e-3, d[lab]
    assert judge(d)["verdict"] == "pass", judge(d)
    best = w.sort_values("gross_long").groupby(["ts"]).tail(2)              # the best GROSS names: direction
    tk2 = best.assign(side="long", net_r=best.net_long, gross_r=best.gross_long)[["symbol", "ts", "side", "net_r", "gross_r"]]
    assert judge(decompose(w, tk2))["verdict"] == "fail"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out")
    ap.add_argument("--unit", default="RQ-20261112-a7e8-03")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.out:
        ap.error("--out is required")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
