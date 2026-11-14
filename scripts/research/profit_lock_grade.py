#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-05 (conditional profit lock) dispatches it as its last command
"""Grade the CONDITIONAL PROFIT LOCK: arms L2 / L25 / L2T vs arm A (the leg config-exact) per leg, two windows.

Row PROFIT-LOCK-CONDITIONAL-TEST (manager 2026-11-14 09:07Z, after the operator's directed +2R lock on the real-money
ADA short at 08:56Z). Reads ONE ``exit_lever_ablation`` run per leg per window (``<out>/rec_<leg>``, ``<out>/pre_<leg>``)
carrying arms A, L2, L25 and L2T on one feed:
  L2   once the trade has SEEN >= 2R, stop to entry + 1R      (--be-floor-r 2   --be-floor-lock-r 1)
  L25  once the trade has SEEN >= 2.5R, stop to entry + 1.5R  (--be-floor-r 2.5 --be-floor-lock-r 1.5)
  L2T  L2, armed only while the resting TP is within 0.5R of the trade's extreme (--be-floor-tp-within-r 0.5)

THE RULE (registered in RQ-20261114-db1a-05 before the run; this module only applies it):
  pooled   per lock arm X: sum of X net_r minus sum of A net_r over the graded legs is > 0 on the RECORD window AND
           > 0 on the PRIOR window. The UNIT verdict is the PRIMARY arm L2's (the operator's k=2); L25 and L2T are
           records of their own and never change the unit verdict.
  per leg  X passes Stage 0 on the record window (net_r > 0, n >= the leg's floor, >= fold_majority of n_folds
           positive) AND beats A there, AND on the prior window X net_r > 0 and > A's. A per-leg pass is a Tier-3
           exit-param candidate (exit-refinement skill); X under its n floor is indeterminate.
  verdict  pass / fail on L2's pooled clause; indeterminate iff fewer than MIN_LEGS legs are graded on both windows.

Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

UNIT = "RQ-20261114-db1a-05"
RULE = "RULE-PROFIT-LOCK-CONDITIONAL-20261114"
PRIMARY = "L2"
LOCK_ARMS = ("L2", "L25", "L2T")
MIN_LEGS = 14


def read_arms(run_dir: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    p = run_dir / "verdict.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
    arms = ((v.get("measurement") or {}).get("arms")) or None
    return arms if isinstance(arms, dict) else None


def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) else None


def arm_grade(x: str, rec: dict, pre: dict, n_floor: int, fold_majority: int) -> Dict[str, Any]:
    a_r, x_r = _num(rec["A"].get("net_r")), _num(rec[x].get("net_r"))
    a_p, x_p = _num(pre["A"].get("net_r")), _num(pre[x].get("net_r"))
    folds = rec[x].get("folds") or []
    pos = sum(1 for f in folds if isinstance(f.get("net_r"), (int, float)) and f["net_r"] > 0)
    n_x = rec[x].get("n")
    under = not (isinstance(n_x, int) and n_x >= n_floor)
    stage0 = bool(x_r is not None and x_r > 0 and not under and pos >= fold_majority)
    beats = x_r is not None and a_r is not None and x_r > a_r
    holds = x_p is not None and a_p is not None and x_p > 0 and x_p > a_p
    ok = bool(stage0 and beats and holds)
    return {"verdict": "pass" if ok else ("indeterminate" if under else "fail"),
            "record": {"net_r": x_r, "n": n_x, "folds_positive": pos, "n_folds": len(folds), "stage0": stage0,
                       "beats_A": beats, "delta_vs_A": None if x_r is None or a_r is None else round(x_r - a_r, 4)},
            "prior": {"net_r": x_p, "n": pre[x].get("n"), "holds": holds,
                      "delta_vs_A": None if x_p is None or a_p is None else round(x_p - a_p, 4)}}


def leg_grade(leg: str, rec: Optional[dict], pre: Optional[dict], n_floor: int, fold_majority: int) -> Dict[str, Any]:
    need = ("A",) + LOCK_ARMS
    if not rec or not pre or not all(k in rec and k in pre for k in need):
        return {"leg": leg, "verdict": "indeterminate", "read_state": "producer_failed", "n": None,
                "note": f"a window run or an arm ({'/'.join(need)}) wrote no verdict"}
    arms = {x: arm_grade(x, rec, pre, n_floor, fold_majority) for x in LOCK_ARMS}
    for g in arms.values():
        if g["verdict"] == "indeterminate":
            g["note"] = f"under the n floor {n_floor}"
    a = {"record": {"net_r": _num(rec["A"].get("net_r")), "n": rec["A"].get("n")},
         "prior": {"net_r": _num(pre["A"].get("net_r")), "n": pre["A"].get("n")}}
    passing = [x for x in LOCK_ARMS if arms[x]["verdict"] == "pass"]
    p = arms[PRIMARY]
    return {"leg": leg, "verdict": p["verdict"], "read_state": "measured",
            "n": int(rec["A"].get("n") or 0) + int(pre["A"].get("n") or 0), "A": a, "arms": arms,
            "arms_passing": passing,
            "note": (f"A rec {a['record']['net_r']} / pre {a['prior']['net_r']}; "
                     + "; ".join(f"{x} d_rec {arms[x]['record']['delta_vs_A']} d_pre {arms[x]['prior']['delta_vs_A']}"
                                 f" ({arms[x]['verdict']})" for x in LOCK_ARMS))}


def pooled(graded: List[Dict[str, Any]], x: str) -> Dict[str, Any]:
    def s(win, key):
        return round(sum(g["arms"][x][win][key] if key != "A" else g["A"][win]["net_r"] for g in graded), 4)
    d_rec = round(sum(g["arms"][x]["record"]["delta_vs_A"] for g in graded), 4)
    d_pre = round(sum(g["arms"][x]["prior"]["delta_vs_A"] for g in graded), 4)
    return {"arm": x, "A_record": s("record", "A"), "X_record": s("record", "net_r"), "A_prior": s("prior", "A"),
            "X_prior": s("prior", "net_r"), "delta_record": d_rec, "delta_prior": d_pre,
            "verdict": "pass" if d_rec > 0 and d_pre > 0 else "fail",
            "legs_passing": sorted(g["leg"] for g in graded if g["arms"][x]["verdict"] == "pass")}


def grade_unit(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    graded = [g for g in legs if g["read_state"] == "measured"
              and all(g["arms"][x][w]["delta_vs_A"] is not None for x in LOCK_ARMS for w in ("record", "prior"))]
    pop = (f"{len(legs)} rostered crypto pullback/trend legs (demo floor + real money); arms L2 / L25 / L2T vs A "
           "config-exact inside the harness; record 2025-11-13..2026-11-12 and prior 2024-11-13..2025-11-12; full cost "
           "stack")
    if len(graded) < MIN_LEGS:
        return {"verdict": "indeterminate", "read_state": "producer_failed", "n": None, "population": pop,
                "note": f"graded legs {len(graded)} < {MIN_LEGS}", "legs": legs}
    by_arm = {x: pooled(graded, x) for x in LOCK_ARMS}
    v = by_arm[PRIMARY]["verdict"]
    return {"verdict": v, "read_state": "measured", "n": sum(int(g["n"] or 0) for g in graded), "population": pop,
            "primary_arm": PRIMARY, "pooled": by_arm, "graded_legs": len(graded),
            "note": "; ".join(f"{x} pooled d_rec {p['delta_record']}R d_pre {p['delta_prior']}R ({p['verdict']}), "
                              f"per-leg passes {p['legs_passing']}" for x, p in by_arm.items()),
            "legs": legs}


def _self_test() -> int:
    def arm(n, net, folds):
        return {"n": n, "net_r": net, "folds": [{"net_r": x} for x in folds]}
    rec = {"A": arm(80, -6.0, [1, -2, -3, -2]), "L2": arm(80, 4.0, [2, 1, 3, -2]),
           "L25": arm(80, -7.0, [1] * 4), "L2T": arm(80, -6.0, [1] * 4)}
    pre = {"A": arm(70, 7.0, [1] * 4), "L2": arm(70, 8.0, [1] * 4), "L25": arm(70, 7.5, [1] * 4),
           "L2T": arm(70, 7.0, [1] * 4)}
    g = leg_grade("x", rec, pre, 30, 3)
    assert g["verdict"] == "pass" and g["arms_passing"] == ["L2"], g
    assert g["arms"]["L25"]["verdict"] == "fail" and g["arms"]["L2T"]["verdict"] == "fail"
    assert leg_grade("x", rec, dict(pre, L2=arm(70, 6.0, [1] * 4)), 30, 3)["verdict"] == "fail"
    assert leg_grade("x", dict(rec, L2=arm(10, 4.0, [1] * 4)), pre, 30, 3)["verdict"] == "indeterminate"
    assert leg_grade("x", None, pre, 30, 3)["read_state"] == "producer_failed"
    assert leg_grade("x", {"A": rec["A"]}, pre, 30, 3)["read_state"] == "producer_failed"
    u = grade_unit([g] * 14)
    assert u["verdict"] == "pass" and u["pooled"]["L2"]["delta_record"] == 140.0, u
    assert u["pooled"]["L2"]["delta_prior"] == 14.0 and u["pooled"]["L25"]["verdict"] == "fail"
    assert u["pooled"]["L2T"]["verdict"] == "fail"  # zero delta is not > 0
    bad = leg_grade("y", rec, dict(pre, L2=arm(70, 5.0, [1] * 4)), 30, 3)
    assert grade_unit([bad] * 14)["verdict"] == "fail"
    assert grade_unit([g] * 13)["verdict"] == "indeterminate"
    print("profit_lock_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out")
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--n-floor", type=int, default=30)
    ap.add_argument("--n-floor-leg", action="append", default=[], metavar="LEG=N")
    ap.add_argument("--fold-majority", type=int, default=3)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not a.leg:
        ap.error("--out and at least one --leg are required")
    out = Path(a.out)
    floors = {k: int(v) for k, _, v in (x.partition("=") for x in a.n_floor_leg)}
    legs = [leg_grade(leg, read_arms(out / f"rec_{leg}"), read_arms(out / f"pre_{leg}"), floors.get(leg, a.n_floor),
                      a.fold_majority) for leg in a.leg]
    v = grade_unit(legs)
    recs = [{"leg": f"POOLED:{x}_minus_A", "verdict": p["verdict"], "read_state": "measured", "n": v["n"],
             "population": v["population"], "note": f"d_rec {p['delta_record']}R d_pre {p['delta_prior']}R"
             + (" (PRIMARY: the unit verdict)" if x == PRIMARY else " (secondary record)")}
            for x, p in (v.get("pooled") or {}).items()]
    if not recs:
        recs = [{"leg": "POOLED", "verdict": v["verdict"], "read_state": v["read_state"], "n": v["n"],
                 "population": v["population"], "note": v.get("note")}]
    v.update({"research_unit": UNIT, "rule": RULE,
              "records": recs + [{"leg": g["leg"], "verdict": g["verdict"], "read_state": g["read_state"], "n": g["n"],
                                  "population": f"{g['leg']}: arms L2/L25/L2T vs A, record + prior windows",
                                  "note": g.get("note")} for g in legs]})
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"unit: {v['verdict']} (n {v['n']}) {v.get('note')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
