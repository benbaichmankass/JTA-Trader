#!/usr/bin/env python3
# wiring: research/queue/RQ-20261102-5e1a-01.yaml (lane ML-ENTRY-PROP-GATE)
"""ONE run of RULE-P5-GATE-BRK-PER-LEG-V3 for ml_entry (ETH+SOL ledger) on breakout_2 / tradeify_1 / velotrade_1.
Cells = prop_gate.SIM params (same as every other gate cell), seeds 1-5, arms firm+cur; verdict taken on the firm arm."""
import json, subprocess, sys, statistics as st
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/research"))
import prop_gate as G
D = Path(__file__).parent
LED = D / "ledgers/ml_entry_ethsol.jsonl"
rows = [json.loads(l) for l in LED.read_text().splitlines()]

def cell(acct, arm, seed):
    out = D / f"cells/ml_entry__3y__{acct}__{arm}__s{seed}.json"
    if out.exists(): return
    sim = G.SIM[acct]
    c, s, sw = G.CUR if arm == "cur" else sim["ven"]
    subprocess.run([sys.executable, str(REPO / "scripts/research/prop_ev_sim.py"), "--trades", f"ml_entry={LED}",
        "--ruleset", str(REPO / f"config/prop_rulesets/{sim['rs']}.yaml"), "--costs", "breakout",
        "--commission-bps-rt", str(c), "--slippage-bps-rt", str(s), "--swap-daily", str(sw), "--swap-model", "prorated",
        "--funded-start", "fresh", "--lev-cap", f"ml_entry={G.lev_cap(acct, 'ml_entry')}", "--sizing", "start",
        "--risk-pct", str(sim["risk"]), "--dd-switch-frac", "0.8", "--seed", str(seed), "--lives", "1000",
        "--outer", "2", "--lives-per-outer", "100", "--modes", "path", "--out", str(out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(REPO))

jobs = [(a, arm, s) for a in G.SIM for arm in ("ven", "cur") for s in range(1, 6)]
with ThreadPoolExecutor(4) as ex: list(ex.map(lambda j: cell(*j), jobs))
# cells with arm "ven" -> file arm token must be 'ven' or 'cur'; aggregate_v2 keys on it
agg = G.aggregate_v2(str(D) + "/")
res = {"rule": G.RULE_V3, "ledger": str(LED.relative_to(REPO)), "firms": {}}
for acct in G.SIM:
    for arm in ("ven", "cur"):
        r = next(x for x in agg if x["account"] == acct and x["arm"] == arm)
        net = G.ledger_net_r(rows, acct, arm)
        edge = G.edge_ci(net)
        null = G.null_cell(rows, "ml_entry", acct, arm, D / f"cells/null_{acct}_{arm}.json", D / "null_work")
        v3 = G.grade_v3(r["verdict"], edge)
        res["firms"].setdefault(acct, {})[arm] = {"v2": r, "edge": edge, "null": null, "v3_verdict": v3}
json.dump(res, open(D / "result.json", "w"), indent=1)
for acct, arms in res["firms"].items():
    for arm, x in arms.items():
        print(acct, arm, x["v3_verdict"], "n", x["v2"]["n"], "ev_med", x["v2"]["ev_median_usd"], "ev_worst", x["v2"]["ev_worst_usd"],
              "B_med/worst", x["v2"]["B_median"], x["v2"]["B_worst"], "c", x["v2"]["ceiling"], "edge", x["edge"]["mean_r"], x["edge"]["ci_lo"], "null_ev", x["null"]["null_ev_usd"])
