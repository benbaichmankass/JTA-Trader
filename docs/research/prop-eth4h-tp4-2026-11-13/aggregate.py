#!/usr/bin/env python3
"""Grade unit RQ-20261113-e44a-01 under RULE-RQ20261113e44a01-ETH4H-TP4-PROP-V3 (= RULE-P5-GATE-BRK-PER-LEG-V3, unchanged).

v2 columns from prop_gate.aggregate_v2 over cells/, then the v3 edge clause per (leg, window, account) with
prop_gate.edge_ci(prop_gate.ledger_net_r(ledger, account, "cur")). Writes summary.json and verdict.json.
Run from the repo root: python3 docs/research/prop-eth4h-tp4-2026-11-13/aggregate.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts/research")
import prop_ev_sim as pes  # noqa: E402
import prop_gate as pg  # noqa: E402

D = Path("docs/research/prop-eth4h-tp4-2026-11-13")
ACCOUNTS = ["breakout_2", "tradeify_1", "velotrade_1"]


def main() -> int:
    rows = pg.aggregate_v2(str(D) + "/")
    for r in rows:
        ledger = pes.load_rows(D / "ledgers" / f"{r['leg']}_{r['window']}.jsonl")
        edge = pg.edge_ci(pg.ledger_net_r(ledger, r["account"], r["arm"]))
        r["edge"] = edge
        r["verdict_v3"] = pg.grade_v3(r["verdict"], edge)
    (D / "summary.json").write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n")

    def cell(leg, win, acct):
        return next((r for r in rows if r["leg"] == leg and r["window"] == win and r["account"] == acct and r["arm"] == "cur"), None)

    primary = {a: cell("eth4hT4", "3y", a) for a in ACCOUNTS}
    missing = [a for a, c in primary.items() if c is None or c["seeds"] != 5]
    if missing:
        verdict = "indeterminate"
        why = f"primary cell missing or short of 5 seeds on {missing}"
    else:
        v3 = {a: c["verdict_v3"] for a, c in primary.items()}
        v2 = {a: c["verdict"] for a, c in primary.items()}
        if all(v == "PASS" for v in v3.values()):
            verdict = "pass"
        elif all(v == "PASS" for v in v2.values()):
            verdict = "fail_edge"
        else:
            verdict = "fail"
        why = f"primary (eth4hT4, 3y, cur) v2 {v2}; v3 {v3}"
    contested = {}
    for a in ACCOUNTS:
        p, y = primary.get(a), cell("eth4hT4", "365d", a)
        if p and y and p["verdict_v3"] == "PASS" and y["ev_median_usd"] <= 0:
            contested[a] = "CONTESTED (365d EV sign flips) -> DE-RISK, not add"
    out = {
        "research_unit": "RQ-20261113-e44a-01",
        "decision_rule": {"id": "RULE-RQ20261113e44a01-ETH4H-TP4-PROP-V3", "registered_at": "2026-11-13"},
        "verdict": verdict, "why": why, "contested": contested,
        "primary": primary,
        "paired_baseline_A_3y": {a: cell("eth4hA", "3y", a) for a in ACCOUNTS},
        "t4_365d": {a: cell("eth4hT4", "365d", a) for a in ACCOUNTS},
        "population": "ledgers/ (RQ-20261028-a7c3-04 run 40826186111 arms A and T4, sliced to the record's 3y window and its 365d tail)",
    }
    (D / "verdict.json").write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    for r in rows:
        print(f"{r['leg']:8} {r['window']:5} {r['account']:12} n={r['n']:<4} B med/worst {r['B_median']}/{r['B_worst']} "
              f"(c {r['ceiling']}) EV med/worst {r['ev_median_usd']}/{r['ev_worst_usd']} v2 {r['verdict']:13} "
              f"edge {r['edge'].get('mean_r')} [{r['edge'].get('ci_lo')}, {r['edge'].get('ci_hi')}] v3 {r['verdict_v3']}")
    print("VERDICT:", verdict, "|", why, "|", contested or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
