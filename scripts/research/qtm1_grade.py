#!/usr/bin/env python3
# wiring: research/queue/RQ-20261029-7294-02.yaml (pre_run_amendment names this grader); run by hand after tm_bench score
"""Grade a TM-BENCH `score` verdict under RULE-RQ20261029-7294-02-QTM1-SOFFLINE as amended before the run (2026-10-30T10:47Z).

    python3 scripts/research/qtm1_grade.py <tm_bench out dir>/verdict.json [--out <results jsonl>]

Graded arms: lgbm_action_value at each check-in cell. Holm across those arms on p_one_sided. Per arm, against
bar = max(0, B1 pooled delta vs B0): gain >= +0.03 R/trade, CI lower - bar > 0, >= 5 of 6 folds where the arm beats
max(0, B1 fold delta), max DD <= B0 on every leg, net R per capital-day >= B0, beats B2 at the same cell, beats its causal
B4 (p_random_ge_arm <= 0.05), beats the logit twin at the same cell by >= +0.01 R/trade, Holm p < 0.05. B5 is not available
in TM-BENCH, so an arm clearing every other clause is `pass_pending_b5` and the unit reads INDETERMINATE, never PASS.
An arm FAILS if CI upper - bar < +0.03. The unit FAILS if every graded arm fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

RULE_ID = "RULE-RQ20261029-7294-02-QTM1-SOFFLINE"
MIN_GAIN, MIN_FOLDS, TWIN_MARGIN, ALPHA, MIN_N = 0.03, 5, 0.01, 0.05, 2000


def holm(ps: Dict[str, float]) -> Dict[str, float]:
    order = sorted(ps, key=ps.get)
    out, run = {}, 0.0
    for k, key in enumerate(order):
        run = max(run, min(1.0, (len(order) - k) * ps[key]))
        out[key] = run
    return out


def grade(v: Dict[str, Any]) -> Dict[str, Any]:
    m = v["measurement"]
    arms = {a["arm_id"]: a for a in m["arms"]}
    b1 = arms["B1_best_static_rule"]
    bar = max(0.0, b1["delta_vs_b0_r"])
    graded = [a for a in m["arms"] if a["arm_id"].startswith("lgbm_action_value@") and a.get("read_state") == "measured"]
    hp = holm({a["arm_id"]: a["p_one_sided"] for a in graded})
    rows: List[Dict[str, Any]] = []
    for a in graded:
        cell = a["checkin"]
        b2, twin = arms.get(f"B2_distance_logit@{cell}"), arms.get(f"logit_action_value@{cell}")
        b4 = a.get("b4_matched_random") or {}
        folds_ok = sum(1 for f, d in a["folds"].items() if d > max(0.0, b1["folds"].get(f, 0.0)))
        c = {"gain_ge_0.03": a["delta_vs_b0_r"] - bar >= MIN_GAIN,
             "ci_lo_minus_bar_gt_0": a["ci95"][0] - bar > 0,
             "folds_ge_5": folds_ok >= MIN_FOLDS,
             "maxdd_le_b0": a["maxdd_ok"],
             "capday_ge_b0": (a["net_r_per_capital_day"] or -1e9) >= (a["b0_net_r_per_capital_day"] or 0.0),
             "beats_b2": b2 is not None and a["delta_vs_b0_r"] > b2["delta_vs_b0_r"],
             "beats_b4_causal": b4.get("mode") == "causal" and b4.get("p_random_ge_arm", 1.0) <= ALPHA,
             "beats_twin_by_0.01": twin is not None and twin.get("read_state") == "measured"
             and a["delta_vs_b0_r"] - twin["delta_vs_b0_r"] >= TWIN_MARGIN,
             "holm_p_lt_0.05": hp[a["arm_id"]] < ALPHA,
             "beats_b5": None}
        fail = a["ci95"][1] - bar < MIN_GAIN
        ok = all(x for k, x in c.items() if k != "beats_b5")
        rows.append({"arm_id": a["arm_id"], "verdict": "fail" if fail else ("pass_pending_b5" if ok else "indeterminate"),
                     "delta_vs_b0_r": a["delta_vs_b0_r"], "ci95_vs_b0": a["ci95"], "gain_vs_bar_r": round(a["delta_vs_b0_r"] - bar, 5),
                     "ci95_vs_bar": [round(a["ci95"][0] - bar, 5), round(a["ci95"][1] - bar, 5)],
                     "folds_beating_bar": folds_ok, "action_rate": a["action_rate"], "n_acted": a["n_acted"],
                     "delta_acted_r": a["delta_acted_r"], "act_threshold_by_fold": a.get("act_threshold_by_fold"),
                     "b2_delta_r": None if b2 is None else b2["delta_vs_b0_r"],
                     "twin_delta_r": None if twin is None else twin.get("delta_vs_b0_r"),
                     "b4": b4, "p_one_sided": a["p_one_sided"], "p_holm": round(hp[a["arm_id"]], 5),
                     "maxdd_per_leg": a["maxdd_per_leg"], "capday": [a["net_r_per_capital_day"], a["b0_net_r_per_capital_day"]],
                     "checks": c})
    n = v.get("n") or 0
    sc_ok = (m.get("selfcheck") or {}).get("pass", False)
    if n < MIN_N or not sc_ok or not graded:
        verdict, why = "indeterminate", f"n {n} / selfcheck {sc_ok} / graded arms {len(graded)}"
    elif all(r["verdict"] == "fail" for r in rows):
        verdict, why = "fail", "every graded lgbm arm: CI upper - bar < +0.03 R/trade"
    else:
        verdict, why = "indeterminate", "not every arm fails; " + (
            "an arm clears every clause but B5 (not available)" if any(r["verdict"] == "pass_pending_b5" for r in rows)
            else "no arm clears the PASS clauses")
    return {"verdict": verdict, "why": why, "bar_r": round(bar, 5), "b1_delta_r": b1["delta_vs_b0_r"],
            "b1_ci95": b1["ci95"], "b1_folds": b1["folds"], "arms": rows,
            "engine": m.get("engine"), "engine_fidelity": m.get("engine_fidelity"), "oracle": {
                k: m["oracle"].get(k) for k in ("census_best_close_saving_r_per_trade", "action_value_ceiling_r_per_trade_oos")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("verdict_json")
    ap.add_argument("--out", default=None, help="write the graded record as JSON here")
    a = ap.parse_args(argv)
    v = json.loads(Path(a.verdict_json).read_text())
    g = grade(v)
    txt = json.dumps(g, indent=1)
    if a.out:
        Path(a.out).write_text(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
