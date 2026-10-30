#!/usr/bin/env python3
"""Aggregate cells for RULE-P5-GATE-BRK-PER-LEG-V2 (unit RQ-20261029-9a2c-01), lane PROP-REPLACEMENT."""
import glob
import json
import statistics as st

ROOT = "docs/research/prop-replacement-2026-10-30/"
ACCT = {  # ruleset, size, ceiling c = 1 - 2F/W
    "breakout_2": (5000, 1 - 2 * 20 / (0.8 * 0.09 * 5000)),
    "tradeify_1": (10000, 1 - 2 * 120 / (0.8 * 0.12 * 10000)),
    "velotrade_1": (5000, 1 - 2 * 54 / (0.8 * 0.10 * 5000)),
}
cells = {}
for f in sorted(glob.glob(ROOT + "cells/*.json")):
    leg, win, acct, arm, s = f.split("/")[-1][:-5].split("__")
    with open(f) as fh:
        d = json.load(fh)
    p = d["results"]["path"]
    cells.setdefault((leg, win, acct, arm), []).append({
        "seed": int(s[1:]), "ev": p["ev_net_usd_per_life"], "B": min(1.0, p["p_breach_max_dd_in_eval"] + p["p_breach_daily_loss_in_eval"]),
        "life": p["p_breach_max_dd"], "n": d["inputs"]["n_trades"], "pass_eval": p["p_pass_eval"]})
rows = []
for (leg, win, acct, arm), cs in sorted(cells.items()):
    size, c = ACCT[acct]
    evs = [x["ev"] for x in cs]
    Bs = [x["B"] for x in cs]
    n = cs[0]["n"]
    ok = n >= 88 and st.median(Bs) < c and max(Bs) < c and st.median(evs) > 0 and min(evs) > 0
    v = "INDETERMINATE" if n < 88 else ("PASS" if ok else "FAIL")
    rows.append({"leg": leg, "window": win, "account": acct, "arm": arm, "seeds": len(cs), "n": n, "ceiling": round(c, 3),
                 "B_median": round(st.median(Bs), 3), "B_worst": round(max(Bs), 3), "life_p_breach_median": round(st.median(x["life"] for x in cs), 3),
                 "life_p_breach_worst": round(max(x["life"] for x in cs), 3),
                 "ev_median_usd": round(st.median(evs), 2), "ev_worst_usd": round(min(evs), 2),
                 "ev_median_pct": round(100 * st.median(evs) / size, 2), "ev_worst_pct": round(100 * min(evs) / size, 2),
                 "p_pass_eval_median": round(st.median(x["pass_eval"] for x in cs), 3), "verdict": v})
with open(ROOT + "summary.json", "w") as fh:
    json.dump(rows, fh, indent=1)
print(f"{'leg':6}{'win':5}{'acct':12}{'arm':4}{'sd':3}{'n':5}{'c':6}{'Bmed':6}{'Bmax':6}{'lifeMax':8}{'EVmed$':8}{'EVmin$':8}{'EVmed%':7}{'EVmin%':7} verdict")
for r in rows:
    print(f"{r['leg']:8}{r['window']:5}{r['account']:12}{r['arm']:4}{r['seeds']:<3}{r['n']:<5}{r['ceiling']:<6}{r['B_median']:<6}{r['B_worst']:<6}{r['life_p_breach_worst']:<8}{r['ev_median_usd']:<8}{r['ev_worst_usd']:<8}{r['ev_median_pct']:<7}{r['ev_worst_pct']:<7} {r['verdict']}")
