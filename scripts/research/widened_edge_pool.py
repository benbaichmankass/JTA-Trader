#!/usr/bin/env python3
"""Widened-evidence edge test for one leg (RQ-20261031-422a-01, lane PROP-GATE-EDGE-SENSITIVE).

Runs the canonical cost-complete harness (exit_lever_ablation.py, arm P = the prop stack) for the leg on its own
symbol over a LONG window, and on config-exact twins (same config, only symbols[0] replaced via --symbol) over a
common window, then reports the V3 edge (mean net R, two-sided 95% CI lower bound) for the ETH arm, per twin, and
POOLED across the twins + the leg's own symbol. The pooled CI is a CLUSTER bootstrap by calendar month (crypto
trades in one month are correlated; an iid CI would overstate n). Writes verdict.json; the rule is in the unit.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROP_STACK = "P=--fee-bps-roundtrip=8;--slippage-bps-roundtrip=3;--funding-bps-per-window=5;--funding-window-hours=24"
Z = 1.959964


def run_arm(leg, symbol, start, end, days, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", leg, "--arm", PROP_STACK,
           "--days", str(days), "--start", start, "--end", end, "--grade", "stage0", "--baseline", "P",
           "--delta-r", "0", "--fold-majority", "3", "--n-floor", "39", "--out", str(out)]
    if symbol:
        cmd += ["--symbol", symbol]
    subprocess.run(cmd, check=True, cwd=str(REPO))
    rows = [json.loads(x) for x in (out / "arms" / "P__trades.jsonl").read_text().splitlines() if x.strip()]
    return rows


def net(r):
    return float(r["net_r"])


def month(r):
    return str(r.get("entry_time", r.get("entry_ts", "")))[:7]


def iid_ci(xs):
    n = len(xs)
    if n < 2:
        return {"n": n, "mean_r": None, "ci_lo": None, "ci_hi": None, "read_state": "n<2"}
    m = st.fmean(xs)
    se = st.stdev(xs) / math.sqrt(n)
    return {"n": n, "mean_r": round(m, 5), "ci_lo": round(m - Z * se, 5), "ci_hi": round(m + Z * se, 5), "read_state": "ok"}


def cluster_ci(rows, draws=2000, seed=1):
    by = defaultdict(list)
    for r in rows:
        by[month(r)].append(net(r))
    keys = sorted(by)
    if len(keys) < 6:
        return {"n": len(rows), "clusters": len(keys), "mean_r": None, "ci_lo": None, "ci_hi": None, "read_state": "clusters<6"}
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        xs = [x for k in (rng.choice(keys) for _ in keys) for x in by[k]]
        means.append(st.fmean(xs) if xs else 0.0)
    means.sort()
    allx = [net(r) for r in rows]
    return {"n": len(rows), "clusters": len(keys), "mean_r": round(st.fmean(allx), 5),
            "ci_lo": round(means[int(0.025 * draws)], 5), "ci_hi": round(means[int(0.975 * draws) - 1], 5), "read_state": "ok"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="trend_donchian_eth_prop")
    ap.add_argument("--symbols", default="BTCUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT,ADAUSDT")
    ap.add_argument("--own-start", default="2020-01-01", help="the leg's own symbol: as far back as the harness has data")
    ap.add_argument("--common-start", default="2021-02-01", help="pooled window start (all twins listed)")
    ap.add_argument("--end", default="2026-10-11 20:00")
    ap.add_argument("--own-days", type=int, default=2490)
    ap.add_argument("--common-days", type=int, default=2080)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    res = {"leg": a.leg, "stack": PROP_STACK, "per_symbol": {}}
    own = run_arm(a.leg, None, a.own_start, a.end, a.own_days, out / "own_long")
    res["own_long"] = iid_ci([net(r) for r in own])
    pooled = []
    own_common = run_arm(a.leg, None, a.common_start, a.end, a.common_days, out / "own_common")
    res["own_common"] = iid_ci([net(r) for r in own_common])
    pooled += own_common
    for sym in [s for s in a.symbols.split(",") if s]:
        try:
            rows = run_arm(a.leg, sym, a.common_start, a.end, a.common_days, out / sym)
            res["per_symbol"][sym] = iid_ci([net(r) for r in rows])
            pooled += rows
        except Exception as e:  # noqa: BLE001 # allow-silent: contained per item (no halting), recorded in the result as could_not_run, never dropped
            res["per_symbol"][sym] = {"read_state": f"could_not_run: {type(e).__name__}"}
    res["pooled"] = cluster_ci(pooled)
    p, o = res["pooled"], res["own_long"]
    if p["read_state"] != "ok" or o["read_state"] != "ok":
        verdict = "INCONCLUSIVE"
    elif p["ci_lo"] > 0 and o["mean_r"] > 0:
        verdict = "PASS"
    elif p["ci_lo"] <= 0 and p["n"] >= 400:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"
    res["verdict"] = verdict
    res["read_state"] = "ok"
    (out / "verdict.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("own_long", "own_common", "pooled", "verdict")}, indent=1))
    return 0


def _self_test() -> int:
    rows = [{"net_r": 0.5 if i % 2 else -0.5, "entry_time": f"2024-{(i % 12) + 1:02d}-01"} for i in range(240)]
    c = cluster_ci(rows)
    assert c["read_state"] == "ok" and c["ci_lo"] < 0 < c["ci_hi"], c
    pos = [{"net_r": 0.6 + (0.1 if i % 2 else -0.1), "entry_time": f"2024-{(i % 12) + 1:02d}-01"} for i in range(240)]
    assert cluster_ci(pos)["ci_lo"] > 0
    assert cluster_ci(rows[:5])["read_state"] == "clusters<6"
    print("self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test() if "--self-test" in sys.argv else main())
