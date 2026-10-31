#!/usr/bin/env python3
"""Prop EV/survival gate RULE-P5-GATE-BRK-PER-LEG -- ONE implementation (v2 grading + v3 edge clause).

v2 (RQ-20261029-9a2c-01, registered 2026-10-29): breach ceiling c = 1 - 2F/W and EV > 0 at every seed.
It is NOT sensitive to edge: a cheap evaluation fee against 80% of a 9-12% profit target plus a
near-break-even ceiling makes a ~zero-edge random walk +EV per attempt (PI-20261030-9KC5G3FG-0007).

v3 (RULE-P5-GATE-BRK-PER-LEG-V3, registered 2026-10-31) = v2 AND the ledger's net-of-cost per-trade edge,
priced under the SAME cost arm the cell used, has its two-sided 95% CI lower bound > 0
(mean - 1.96 * sd / sqrt(n); trades treated as independent -- a stated simplification, it flatters
the edge if trades cluster, so it can only let a PASS through, never wrongly fail a real edge).
Every verdict also carries the zero-edge NULL EV: the same ledger with gross_r shifted so mean net R = 0
(costs, timing, stops and mfe untouched), re-simulated -- how much EV the rule structure alone produces.

Used by docs/research/{e4-prop-sim-2026-10-30,prop-replacement-2026-10-30,
prop-gate-rerun-2026-10-29/RQ-20261029-9a2c-01}/aggregate.py. Change the rule HERE only.
"""
from __future__ import annotations

import glob
import json
import math
import statistics as st
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prop_ev_sim as pes  # noqa: E402

RULE_V2 = "RULE-P5-GATE-BRK-PER-LEG-V2"
RULE_V3 = "RULE-P5-GATE-BRK-PER-LEG-V3"
N_FLOOR = 88
Z95 = 1.959964

# account -> (size, fee F, profit target, split) ceiling c = 1 - 2F/(split*target*size)
ACCT = {  # size, ceiling
    "breakout_2": (5000, 1 - 2 * 20 / (0.8 * 0.09 * 5000)),
    "tradeify_1": (10000, 1 - 2 * 120 / (0.8 * 0.12 * 10000)),
    "velotrade_1": (5000, 1 - 2 * 54 / (0.8 * 0.10 * 5000)),
}
# the cells' simulator parameters (run_cells.sh of the three research dirs)
SIM = {
    "breakout_2": dict(rs="breakout_turbo_1step", risk=0.0035, ven=(8.0, 3.0, 0.00033)),
    "tradeify_1": dict(rs="tradeify_247_1step", risk=0.005, ven=(8.0, 3.0, 0.00033)),
    "velotrade_1": dict(rs="velotrade_classic_1step", risk=0.005, ven=(6.0, 3.0, 0.0005)),
}
CUR = (11.0, 3.0, 0.0003)


def arm_costs(acct: str, arm: str) -> "pes.CostConfig":
    c, s, sw = CUR if arm == "cur" else SIM[acct]["ven"]
    return pes.CostConfig(mode="breakout", commission_bps_rt=c, slippage_bps_rt=s, swap_daily=sw, swap_model="prorated")


def lev_cap(acct: str, leg: str) -> int:
    """tradeify caps SOL legs at 2x (run_cells.sh of the rerun + replacement dirs); everything else 5."""
    return 2 if (acct == "tradeify_1" and "sol" in leg) else 5


# ---------------------------------------------------------------- v3 edge clause
def edge_ci(net_r: List[float]) -> Dict[str, Any]:
    n = len(net_r)
    if n < 2:
        return {"n": n, "mean_r": None, "ci_lo": None, "ci_hi": None, "read_state": "n<2"}
    m = st.fmean(net_r)
    se = st.stdev(net_r) / math.sqrt(n)
    return {"n": n, "mean_r": round(m, 5), "se_r": round(se, 5), "ci_lo": round(m - Z95 * se, 5),
            "ci_hi": round(m + Z95 * se, 5), "read_state": "ok"}


def ledger_net_r(rows: List[Dict[str, Any]], acct: str, arm: str) -> List[float]:
    trades, _, _ = pes.build_trades({"x": rows}, arm_costs(acct, arm))
    return [t.net_r for t in trades]


def demean_rows(rows: List[Dict[str, Any]], acct: str, arm: str) -> List[Dict[str, Any]]:
    """Same ledger, gross_r shifted so mean net R == 0 under this arm's costs."""
    m = st.fmean(ledger_net_r(rows, acct, arm))
    out = []
    for r in rows:
        r = dict(r)
        r["gross_r"] = float(r["gross_r"]) - m
        if r.get("mfe_r") is not None:
            r["mfe_r"] = max(float(r["mfe_r"]), r["gross_r"])
        out.append(r)
    return out


def grade_v3(v2_verdict: str, edge: Dict[str, Any]) -> str:
    """v3 verdict from the v2 verdict and the edge CI. Only a v2 PASS can be downgraded."""
    if v2_verdict != "PASS":
        return v2_verdict
    lo = edge.get("ci_lo")
    if lo is None:
        return "INDETERMINATE"      # we could not look: never PASS on a missing edge read
    return "PASS" if lo > 0 else "FAIL_EDGE"


# ---------------------------------------------------------------- v2 grading (moved verbatim from the aggregate.py copies)
def aggregate_v2(root: str, leg_prefix: str = "", leg_suffix: str = "") -> List[Dict[str, Any]]:
    cells: Dict[tuple, list] = {}
    for f in sorted(glob.glob(root + "cells/*.json")):
        leg, win, acct, arm, s = f.split("/")[-1][:-5].split("__")
        with open(f) as fh:
            d = json.load(fh)
        p = d["results"]["path"]
        cells.setdefault((leg, win, acct, arm), []).append({
            "seed": int(s[1:]), "ev": p["ev_net_usd_per_life"],
            "B": min(1.0, p["p_breach_max_dd_in_eval"] + p["p_breach_daily_loss_in_eval"]),
            "life": p["p_breach_max_dd"], "n": d["inputs"]["n_trades"], "pass_eval": p["p_pass_eval"]})
    rows = []
    for (leg, win, acct, arm), cs in sorted(cells.items()):
        size, c = ACCT[acct]
        evs = [x["ev"] for x in cs]
        Bs = [x["B"] for x in cs]
        n = cs[0]["n"]
        ok = n >= N_FLOOR and st.median(Bs) < c and max(Bs) < c and st.median(evs) > 0 and min(evs) > 0
        v = "INDETERMINATE" if n < N_FLOOR else ("PASS" if ok else "FAIL")
        rows.append({"leg": f"{leg_prefix}{leg}{leg_suffix}", "window": win, "account": acct, "arm": arm, "seeds": len(cs), "n": n, "ceiling": round(c, 3),
                     "B_median": round(st.median(Bs), 3), "B_worst": round(max(Bs), 3),
                     "life_p_breach_median": round(st.median(x["life"] for x in cs), 3),
                     "life_p_breach_worst": round(max(x["life"] for x in cs), 3),
                     "ev_median_usd": round(st.median(evs), 2), "ev_worst_usd": round(min(evs), 2),
                     "ev_median_pct": round(100 * st.median(evs) / size, 2), "ev_worst_pct": round(100 * min(evs) / size, 2),
                     "p_pass_eval_median": round(st.median(x["pass_eval"] for x in cs), 3), "verdict": v})
    return rows


def run_aggregate(root: str, leg_prefix: str = "", leg_suffix: str = "") -> None:
    """What each research dir's aggregate.py does: write summary.json (v2 columns) and print the table."""
    rows = aggregate_v2(root, leg_prefix, leg_suffix)
    with open(root + "summary.json", "w") as fh:
        json.dump(rows, fh, indent=1)
    print(f"{'leg':6}{'win':5}{'acct':12}{'arm':4}{'sd':3}{'n':5}{'c':6}{'Bmed':6}{'Bmax':6}{'lifeMax':8}{'EVmed$':8}{'EVmin$':8}{'EVmed%':7}{'EVmin%':7} verdict")
    for r in rows:
        print(f"{r['leg'][-8:]:8}{r['window']:5}{r['account']:12}{r['arm']:4}{r['seeds']:<3}{r['n']:<5}{r['ceiling']:<6}{r['B_median']:<6}{r['B_worst']:<6}{r['life_p_breach_worst']:<8}{r['ev_median_usd']:<8}{r['ev_worst_usd']:<8}{r['ev_median_pct']:<7}{r['ev_worst_pct']:<7} {r['verdict']}")


# ---------------------------------------------------------------- null-EV simulation (one seed, the cells' protocol)
def null_cell(rows: List[Dict[str, Any]], leg: str, acct: str, arm: str, out_json: Path, work: Path, seed: int = 1) -> Dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    led = work / f"{leg}__{acct}__{arm}.null.jsonl"
    led.write_text("\n".join(json.dumps(r) for r in demean_rows(rows, acct, arm)) + "\n")
    c, s, sw = CUR if arm == "cur" else SIM[acct]["ven"]
    sim = SIM[acct]
    cmd = [sys.executable, str(REPO / "scripts/research/prop_ev_sim.py"), "--trades", f"{leg}={led}",
           "--ruleset", str(REPO / f"config/prop_rulesets/{sim['rs']}.yaml"), "--costs", "breakout",
           "--commission-bps-rt", str(c), "--slippage-bps-rt", str(s), "--swap-daily", str(sw), "--swap-model", "prorated",
           "--funded-start", "fresh", "--lev-cap", f"{leg}={lev_cap(acct, leg)}", "--sizing", "start",
           "--risk-pct", str(sim["risk"]), "--dd-switch-frac", "0.8", "--seed", str(seed), "--lives", "1000",
           "--outer", "2", "--lives-per-outer", "100", "--modes", "path", "--out", str(out_json)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(REPO))
    p = json.loads(out_json.read_text())["results"]["path"]
    return {"null_ev_usd": p["ev_net_usd_per_life"],
            "null_B": min(1.0, p["p_breach_max_dd_in_eval"] + p["p_breach_daily_loss_in_eval"])}
