#!/usr/bin/env python3
"""Grade the cells under RULE-P5-GATE-BRK-PER-LEG-V3 (scripts/research/prop_gate.py: V2 aggregate + edge CI clause),
stop15 (incumbent, atr_stop_mult 1.5) vs stop10 (proposed, 1.0), same harness/ledger source/windows. Writes summary.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts/research")
import prop_gate as pg  # noqa: E402

D = "docs/research/d6-eth4h-prop-regrade-2026-11-28/"
rows = pg.aggregate_v2(D)
for r in rows:
    ledger = [json.loads(x) for x in Path(f"{D}ledgers/{r['leg']}_{r['window']}.jsonl").read_text().splitlines() if x.strip()]
    r["edge"] = pg.edge_ci(pg.ledger_net_r(ledger, r["account"], r["arm"]))
    r["v3_verdict"] = pg.grade_v3(r["verdict"], r["edge"])
Path(D + "summary.json").write_text(json.dumps(rows, indent=1) + "\n")
print(f"{'leg':7}{'win':5}{'account':12}{'n':>4} {'ceil':>5} {'Bmed':>5} {'Bmax':>5} {'EVmed$':>8} {'EVmin$':>8}  {'edge R [95% CI]':26} v2 / v3")
for r in rows:
    e = r["edge"]
    print(f"{r['leg']:7}{r['window']:5}{r['account']:12}{r['n']:>4} {r['ceiling']:>5} {r['B_median']:>5} {r['B_worst']:>5} {r['ev_median_usd']:>8} "
          f"{r['ev_worst_usd']:>8}  {e['mean_r']:+.3f} [{e['ci_lo']:+.3f}, {e['ci_hi']:+.3f}]   {r['verdict']} / {r['v3_verdict']}")
