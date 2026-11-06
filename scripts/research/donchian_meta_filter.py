#!/usr/bin/env python3
"""Meta-label FILTER over the prop baseline legs' own signals (unit RQ-20261105-d256-02, lane PROP-BASELINE-AND-ML).

Question: does a model that sees ONLY what is known at each trend_donchian_{eth,sol}_4h entry select a subset of
that leg's own trades with more net-of-cost edge than taking every trade, and does the kept ledger clear the V3
prop gate (scripts/research/ml_variant_prop_gate.py, unchanged)?

Design (registered in research/queue/RQ-20261105-d256-02.yaml BEFORE any run; nothing here is tuned):
  * population  : the gap-fixed Stage-0 ledgers docs/research/prop-replacement-2026-10-30/ledgers/{eth4h,sol4h}_3y.jsonl
  * features    : per trade, at entry only -- side, stop distance (% of entry), leg confidence, entry hour (sin/cos),
                  symbol, the leg's own trailing mean net R over its last 3 CLOSED trades (exit_time <= entry_time),
                  log1p(days since its last closed exit). NO market-wide or cross-sectional feature (a market-wide
                  feature identifies the date: PI-20261105-GEXSLEAK-0001).
  * label       : net_r > 0 (the ledger's current-stack net R)
  * model       : sklearn LogisticRegression(C=1.0) on standardised features; one fixed arm, no grid, no tuning
  * walk-forward: expanding, refit at every calendar-quarter start on trades whose exit_time < that start (purged:
                  a still-open trade never trains); a quarter is scored only when >= 40 training trades exist
  * policy      : KEEP a trade iff p(net_r > 0) >= the training base rate
  * held-out    : entries 2025-10-11 .. 2026-10-11 (the trailing 365d slice), scored by the same walk-forward,
                  reported separately; no choice anywhere in this script reads it (there is no choice).

Outputs under --out: ledger_all_oos.jsonl, ledger_kept_oos.jsonl, result.json; then the V3 gate on the kept ledger.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
LEDGERS = {"trend_donchian_eth_4h": "docs/research/prop-replacement-2026-10-30/ledgers/eth4h_3y.jsonl",
           "trend_donchian_sol_4h": "docs/research/prop-replacement-2026-10-30/ledgers/sol4h_3y.jsonl"}
HOLDOUT_START, HOLDOUT_END = "2025-10-11", "2026-10-11"
MIN_TRAIN = 40
N_GATE_FLOOR = 88          # prop_gate n floor (RULE-P5-GATE-BRK-PER-LEG-V2/V3)
SEED = 20261105
BOOT = 2000
FEATS = ["is_long", "stop_pct", "confidence", "hour_sin", "hour_cos", "is_sol", "trail3_net_r", "log_days_since_exit"]
LEG_KEY = "donchian_meta_ethsol_cap2"   # prop_gate.lev_cap: contains "sol" -> tradeify 2x (the conservative cap)


def load(paths: dict[str, str]) -> pd.DataFrame:
    rows = []
    for leg, p in paths.items():
        for line in (REPO / p).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["leg"] = leg
                rows.append(r)
    d = pd.DataFrame(rows)
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
    return d.sort_values("entry_time").reset_index(drop=True)


def features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["is_long"] = (d["direction"] == "long").astype(float)
    d["stop_pct"] = (d["entry"].astype(float) - d["sl"].astype(float)).abs() / d["entry"].astype(float) * 100
    d["confidence"] = d["confidence"].astype(float).fillna(d["confidence"].astype(float).median())
    h = d["entry_time"].dt.hour + d["entry_time"].dt.minute / 60
    d["hour_sin"], d["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    d["is_sol"] = (d["symbol"] == "SOLUSDT").astype(float)
    t3, ds = [], []
    for i, r in d.iterrows():   # the leg's OWN closed history at entry (never another leg, never the market)
        prev = d[(d.leg == r.leg) & (d.exit_time <= r.entry_time)].sort_values("exit_time")
        t3.append(float(prev["net_r"].tail(3).mean()) if len(prev) else 0.0)
        ds.append(math.log1p((r.entry_time - prev["exit_time"].iloc[-1]).total_seconds() / 86400) if len(prev) else math.log1p(30.0))
    d["trail3_net_r"], d["log_days_since_exit"] = t3, ds
    return d


def walk_forward(d: pd.DataFrame) -> pd.DataFrame:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    q = pd.date_range(d.entry_time.min().normalize() - pd.offsets.QuarterBegin(1), d.entry_time.max() + pd.offsets.QuarterBegin(1),
                      freq="QS", tz="UTC")
    out = []
    for lo, hi in itertools.pairwise(q):
        te = d[(d.entry_time >= lo) & (d.entry_time < hi)]
        tr = d[d.exit_time < lo]                       # purged: only trades CLOSED before the refit
        if te.empty or len(tr) < MIN_TRAIN or tr["y"].nunique() < 2:
            continue
        m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(tr[FEATS], tr["y"])
        base = float(tr["y"].mean())
        te = te.assign(p=m.predict_proba(te[FEATS])[:, 1], base_rate=base, fold=str(lo.date()), n_train=len(tr))
        te["keep"] = te["p"] >= te["base_rate"]
        out.append(te)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def edge(x) -> dict:
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return {"n": n, "mean_r": float(x.mean()) if n else None, "ci_lo": None, "ci_hi": None}
    se = x.std(ddof=1) / math.sqrt(n)
    return {"n": n, "mean_r": round(float(x.mean()), 4), "sum_r": round(float(x.sum()), 3), "ci_lo": round(float(x.mean() - 1.96 * se), 4),
            "ci_hi": round(float(x.mean() + 1.96 * se), 4)}


def lift(o: pd.DataFrame) -> dict:
    """kept-minus-all mean net R, with a bootstrap over trades (paired by resampling the scored set)."""
    rng = np.random.default_rng(SEED)
    n = len(o)
    diffs = []
    net, keep = o["net_r"].to_numpy(), o["keep"].to_numpy()
    for _ in range(BOOT):
        i = rng.integers(0, n, n)
        if keep[i].sum() == 0:
            continue
        diffs.append(net[i][keep[i]].mean() - net[i].mean())
    diffs = np.asarray(diffs)
    return {"kept_minus_all_mean_r": round(float(net[keep].mean() - net.mean()), 4) if keep.any() else None,
            "boot_ci95": [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)] if len(diffs) else None,
            "boot_draws": len(diffs)}


def split(o: pd.DataFrame) -> dict:
    hs, he = pd.Timestamp(HOLDOUT_START, tz="UTC"), pd.Timestamp(HOLDOUT_END, tz="UTC")
    h = o[(o.entry_time >= hs) & (o.entry_time <= he)]
    dev = o[o.entry_time < hs]
    return {name: {"all": edge(g["net_r"]), "kept": edge(g.loc[g.keep, "net_r"]), "dropped": edge(g.loc[~g.keep, "net_r"]),
                   "lift": lift(g) if len(g) else None,
                   "by_leg": {leg: {"all": edge(x["net_r"]), "kept": edge(x.loc[x.keep, "net_r"])} for leg, x in g.groupby("leg")}}
            for name, g in (("oos_all", o), ("dev_oos", dev), ("heldout", h))}


def write_ledger(p: Path, g: pd.DataFrame) -> None:
    cols = [c for c in g.columns if c not in FEATS + ["y", "keep", "p", "base_rate", "fold", "n_train"]]
    recs = []
    for r in g[cols].to_dict("records"):
        r["entry_time"], r["exit_time"] = str(r["entry_time"]), str(r["exit_time"])
        recs.append(r)
    p.write_text("".join(json.dumps(r, default=str) + "\n" for r in recs))


def decide(s: dict, gate: dict | None) -> dict:
    """The rule registered in RQ-20261105-d256-02 (decision_rule.rule), applied mechanically."""
    k = s["oos_all"]["kept"]
    h = s["heldout"]
    if k["n"] < N_GATE_FLOOR or gate is None or gate.get("read_state") != "graded":
        return {"verdict": "INDETERMINATE", "reason": f"kept OOS n={k['n']} < {N_GATE_FLOOR} or gate not graded"}
    firms = {a: {arm: gate["firms"][a][arm]["v3_verdict"] for arm in ("ven", "cur")} for a in gate["firms"]}
    passing = [a for a, v in firms.items() if all(x == "PASS" for x in v.values())]
    lift_ok = (s["oos_all"]["lift"]["kept_minus_all_mean_r"] or 0) > 0
    held_ok = (h["kept"]["mean_r"] is not None and h["kept"]["mean_r"] > 0 and h["all"]["mean_r"] is not None
               and h["kept"]["mean_r"] > h["all"]["mean_r"])
    v = "PASS" if (passing and lift_ok and held_ok) else "FAIL"
    return {"verdict": v, "pass_accounts": passing if v == "PASS" else [], "v3_by_firm": firms, "E_lift_pos": lift_ok, "E_heldout_dir": held_ok}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-gate", action="store_true", help="skip the V3 gate (self-check only)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    d = features(load(LEDGERS))
    d["y"] = (d["net_r"] > 0).astype(int)
    o = walk_forward(d)
    s = split(o)
    write_ledger(out / "ledger_all_oos.jsonl", o)
    write_ledger(out / "ledger_kept_oos.jsonl", o[o.keep])
    gate = None
    if not a.no_gate and len(o[o.keep]) >= 2:
        gd = out / "prop_gate"
        subprocess.run([sys.executable, str(REPO / "scripts/research/ml_variant_prop_gate.py"), "--variant", "donchian-meta-filter",
                        "--ledger", str(out / "ledger_kept_oos.jsonl"), "--out-dir", str(gd), "--symbols", "ETHUSDT,SOLUSDT",
                        "--leg-key", LEG_KEY, "--jobs", "4"], check=True, cwd=str(REPO), stdout=subprocess.DEVNULL)
        gate = json.loads((gd / "result.json").read_text())
    res = {"schema": "donchian_meta_filter/1", "unit": "RQ-20261105-d256-02", "population": {
               "ledgers": LEDGERS, "n_trades_total": len(d), "n_scored_oos": len(o), "first_scored_fold": o["fold"].min() if len(o) else None,
               "heldout": [HOLDOUT_START, HOLDOUT_END]},
           "features": FEATS, "kept_share_oos": round(float(o.keep.mean()), 4) if len(o) else None,
           "folds": o.groupby("fold").agg(n=("net_r", "size"), kept=("keep", "sum"), n_train=("n_train", "first")).reset_index().to_dict("records") if len(o) else [],
           "split": s, "gate": ({k: gate.get(k) for k in ("read_state", "n", "firms", "edge", "verdict")} if gate else None)}
    res["decision"] = decide(s, gate)
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({"decision": res["decision"], "kept_oos": s["oos_all"]["kept"], "all_oos": s["oos_all"]["all"],
                      "heldout": {k: s["heldout"][k] for k in ("all", "kept")}}, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
