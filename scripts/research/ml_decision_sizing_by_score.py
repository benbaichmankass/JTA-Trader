#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-a7e8-04.yaml (row ML-QUEUE-DIVERSIFY, a SIZING unit), run.command via research-script-run.yml
"""Does sizing ml_decision_entry's decisions by its OWN predicted net R beat flat sizing, net of cost, out of sample?

WHY THIS EXISTS (row ML-QUEUE-DIVERSIFY, operator 2026-11-11 a6 "Accept, and diversify the queue": every queued ML unit was regime or
direction work). The served model takes a decision when its predicted net R clears tau 0.1 and then sizes every decision the same.
If the prediction carries magnitude information, risking more on high-score decisions earns more per unit of risk; if it carries only
a sign, it does not. This answers the SIZING question on the held-out window, with the decision set held fixed (same trades, only
their weights change), so it is independent of the direction question RQ-20261112-a7e8-03 read as indeterminate.

THE STATISTIC. Taken decisions of the frozen ml_decision_entry_v1 (tau 0.1) on held-out window A of RQ-20261112-8d20-01
(2025-10-01..2026-09-29). Weight per decision, FIXED before the run and point in time: w = clip(pred / 0.2, 0.5, 2.0) (pred = the
model's predicted net R of the taken side; tau 0.1 -> 0.5x, 0.2 -> 1x, >= 0.4 -> 2x). Per unit of risk:
  delta = sum(w * net_r) / sum(w) - mean(net_r)
95% interval by a decision-time CLUSTER bootstrap (2000 resamples of decision timestamps, seed fixed).

RULE (registered in the unit before any run): INDETERMINATE if n < 100. PASS iff delta > 0 AND bootstrap 95% LB > 0. FAIL iff
delta <= 0. INDETERMINATE otherwise (positive, interval spans 0). Reported, not graded: Spearman(pred, net_r), the same delta in gross R,
by-side, and the max drawdown of both weightings on the time-ordered sequence.

Tier-1 research tooling: public Binance Vision candles, the committed served booster read-only, writes only under --out.
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

RULE_ID = "RULE-RQ20261112-a7e8-04-SIZE-BY-SCORE"
N_MIN = 100
W_REF, W_LO, W_HI = 0.2, 0.5, 2.0
BOOT, SEED = 2000, 20261112


def weights(pred: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(pred, float) / W_REF, W_LO, W_HI)


def delta(r: np.ndarray, w: np.ndarray) -> float:
    return float((w * r).sum() / w.sum() - r.mean())


def boot_ci(t: pd.DataFrame, col: str, n_boot: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    groups = [g for _, g in t.groupby("ts")]
    r_g = [g[col].to_numpy(float) for g in groups]
    w_g = [g["w"].to_numpy(float) for g in groups]
    G = len(groups)
    out = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, G, G)
        r = np.concatenate([r_g[i] for i in idx])
        w = np.concatenate([w_g[i] for i in idx])
        out[b] = delta(r, w)
    return float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))


def max_dd(seq: np.ndarray) -> float:
    c = np.cumsum(seq)
    return float((np.maximum.accumulate(np.r_[0.0, c])[1:] - c).max()) if len(c) else 0.0


def evaluate(taken: pd.DataFrame, n_boot: int = BOOT) -> dict:
    t = taken.assign(w=weights(taken["pred"].to_numpy()))
    n = len(t)
    if n < N_MIN:
        return {"n": n, "verdict": "indeterminate", "why": f"n {n} < {N_MIN}"}
    r, w = t.net_r.to_numpy(float), t.w.to_numpy(float)
    d = delta(r, w)
    lo, hi = boot_ci(t, "net_r", n_boot)
    gd = delta(t.gross_r.to_numpy(float), w)
    o = t.sort_values("ts")
    wn = o.w.to_numpy() / o.w.mean()
    if d <= 0:
        v, why = "fail", f"delta {d:+.4f} R per unit risk <= 0: score-proportional sizing does not beat flat"
    elif lo > 0:
        v, why = "pass", f"delta {d:+.4f} R per unit risk, cluster-bootstrap 95% [{lo:+.4f}, {hi:+.4f}] > 0"
    else:
        v, why = "indeterminate", f"delta {d:+.4f} > 0 but 95% [{lo:+.4f}, {hi:+.4f}] spans 0"
    return {"n": n, "verdict": v, "why": why, "delta_net": round(d, 5), "ci95": [round(lo, 5), round(hi, 5)],
            "delta_gross": round(gd, 5), "flat_mean_net": round(float(r.mean()), 5),
            "weighted_mean_net": round(float((w * r).sum() / w.sum()), 5),
            "spearman_pred_net": round(float(pd.Series(t.pred).corr(pd.Series(t.net_r), method="spearman")), 4),
            "weight_mix": {"0.5x": int((w <= W_LO + 1e-12).sum()), "mid": int(((w > W_LO + 1e-12) & (w < W_HI - 1e-12)).sum()),
                           "2x": int((w >= W_HI - 1e-12).sum())},
            "by_side": {s: (round(delta(g.net_r.to_numpy(float), g.w.to_numpy(float)), 5), int(len(g))) for s, g in t.groupby("side")},
            "max_dd_r": {"flat": round(max_dd(o.net_r.to_numpy(float)), 3), "weighted_unit_risk": round(max_dd(o.net_r.to_numpy(float) * wn), 3)},
            "n_ts_clusters": int(t.ts.nunique()), "boot": n_boot, "seed": SEED}


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
        claim = holdout_lock.claim_read("ENTRY-v1-size-by-score", H.A_START, H.A_LAST_TS[:10], a.unit, a.reader, holdout_lock.LEDGER,
                                        train_end=str(meta["train_end_exclusive"])[:10], family="ENTRY")
    taken = H.score_frozen(tab, models, feats, H.A_START, H.A_LAST_TS)
    ev = evaluate(taken)
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": ev["verdict"], "note": ev["why"],
           "n": ev["n"], "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-12", "registered_before_run": True},
           "population": {"n": ev["n"], "description": (f"frozen ml_decision_entry_v1 (tau {H.TAU}) taken decisions on the {len(syms)}-perp "
                          f"universe, held-out {H.A_START}..{H.A_LAST_TS[:10]}; weights clip(pred/{W_REF}, {W_LO}, {W_HI}) vs flat, per unit risk")},
           "measurement": {**ev, "holdout_claim": claim, "git_sha": E._git_sha(), "runtime_s": round(time.time() - t0)},
           "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "produced_by": {"tool": "python3 scripts/research/ml_decision_sizing_by_score.py", "where": a.reader}}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{ev['verdict'].upper()}: {ev['why']}", flush=True)
    return 0


def self_test() -> int:
    rng = np.random.default_rng(5)
    ts = np.repeat(pd.date_range("2025-10-01", periods=400, freq="4h", tz="UTC"), 3)
    pred = rng.uniform(0.1, 0.5, len(ts))
    good = pd.DataFrame({"ts": ts, "side": "long", "pred": pred, "net_r": (pred - 0.25) * 4 + rng.normal(0, 0.5, len(ts))})
    good["gross_r"] = good.net_r + 0.05
    assert evaluate(good, 300)["verdict"] == "pass"
    bad = good.assign(net_r=-(good.pred - 0.25) * 4 + rng.normal(0, 0.5, len(ts)))
    assert evaluate(bad, 300)["verdict"] == "fail"
    assert evaluate(good.head(50), 300)["verdict"] == "indeterminate"
    assert np.allclose(weights(np.array([0.1, 0.2, 0.4, 0.9])), [0.5, 1.0, 2.0, 2.0])
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out")
    ap.add_argument("--unit", default="RQ-20261112-a7e8-04")
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
