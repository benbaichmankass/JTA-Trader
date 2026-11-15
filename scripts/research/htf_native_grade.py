#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-04 (harness-native HTF long gate) dispatches it as its last command
"""Grade the HARNESS-NATIVE HTF long gate: arm H (``--htf-long-sma-days 200``) vs arm A (the leg config-exact) per leg.

Row DEMO-FLOOR-ITER-20261113, manager GO 2026-11-14 07:15Z (b), after RQ-20261114-db1a-03's post-hoc PASS. Here the gate
runs INSIDE the harness, so a skipped long frees the position for the next signal (path effects modelled). Reads ONE
``exit_lever_ablation`` run per leg per window (``<out>/rec_<leg>``, ``<out>/pre_<leg>``) carrying arms A and H on one feed.

THE RULE (registered in RQ-20261114-db1a-04 before the run; this module only applies it):
  pooled   sum of H net_r minus sum of A net_r over the graded legs is > 0 on the RECORD window AND > 0 on the PRIOR window.
  per leg  H passes Stage 0 on the record window (net_r > 0, n >= the leg's floor, >= fold_majority of n_folds positive)
           AND beats A there, AND on the prior window H net_r > 0 and > A's. A per-leg pass is a Tier-3 proposal candidate.
  verdict  pass iff the pooled clause holds; fail iff graded and it does not; indeterminate iff fewer than 12 legs are
           graded on both windows. Per-leg verdicts are records of their own and never change the unit verdict.

Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

UNIT = "RQ-20261114-db1a-04"
RULE = "RULE-DFR-HTF-NATIVE-20261114"
MIN_LEGS = 12


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


def leg_grade(leg: str, rec: Optional[dict], pre: Optional[dict], n_floor: int, fold_majority: int) -> Dict[str, Any]:
    if not rec or not pre or not all(k in rec and k in pre for k in ("A", "H")):
        return {"leg": leg, "verdict": "indeterminate", "read_state": "producer_failed", "n": None,
                "note": "a window run or an arm (A/H) wrote no verdict"}
    a_r, h_r, a_p, h_p = (_num(rec["A"].get("net_r")), _num(rec["H"].get("net_r")),
                          _num(pre["A"].get("net_r")), _num(pre["H"].get("net_r")))
    folds = rec["H"].get("folds") or []
    pos = sum(1 for f in folds if isinstance(f.get("net_r"), (int, float)) and f["net_r"] > 0)
    n_h = rec["H"].get("n")
    stage0 = bool(h_r is not None and h_r > 0 and isinstance(n_h, int) and n_h >= n_floor and pos >= fold_majority)
    beats = h_r is not None and a_r is not None and h_r > a_r
    holds = h_p is not None and a_p is not None and h_p > 0 and h_p > a_p
    ok = bool(stage0 and beats and holds)
    under = not (isinstance(n_h, int) and n_h >= n_floor)
    return {"leg": leg, "verdict": "pass" if ok else ("indeterminate" if under else "fail"),
            "read_state": "measured", "n": (rec["A"].get("n") or 0) + (n_h or 0),
            "record": {"A_net_r": a_r, "A_n": rec["A"].get("n"), "H_net_r": h_r, "H_n": n_h,
                       "H_folds_positive": pos, "H_n_folds": len(folds), "H_stage0": stage0, "H_beats_A": beats},
            "prior": {"A_net_r": a_p, "A_n": pre["A"].get("n"), "H_net_r": h_p, "H_n": pre["H"].get("n"), "holds": holds},
            "note": (f"record H {h_r} (n {n_h}, {pos}/{len(folds)}) vs A {a_r}; prior H {h_p} vs A {a_p}"
                     + (f" -- H under the n floor {n_floor}" if under else ""))}


def grade_unit(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    graded = [g for g in legs if g["read_state"] == "measured"]
    pop = (f"{len(legs)} crypto demo-floor pullback/trend legs; arm H = --htf-long-sma-days 200 inside the harness vs arm A "
           "config-exact; record 2025-11-13..2026-11-12 and prior 2024-11-13..2025-11-12; full cost stack")
    if len(graded) < MIN_LEGS:
        return {"verdict": "indeterminate", "read_state": "producer_failed", "n": None, "population": pop,
                "note": f"graded legs {len(graded)} < {MIN_LEGS}", "legs": legs}
    d_rec = round(sum(g["record"]["H_net_r"] - g["record"]["A_net_r"] for g in graded), 4)
    d_pre = round(sum(g["prior"]["H_net_r"] - g["prior"]["A_net_r"] for g in graded), 4)
    pooled = {"A_record": round(sum(g["record"]["A_net_r"] for g in graded), 4),
              "H_record": round(sum(g["record"]["H_net_r"] for g in graded), 4),
              "A_prior": round(sum(g["prior"]["A_net_r"] for g in graded), 4),
              "H_prior": round(sum(g["prior"]["H_net_r"] for g in graded), 4),
              "delta_record": d_rec, "delta_prior": d_pre}
    ok = d_rec > 0 and d_pre > 0
    passing = sorted(g["leg"] for g in legs if g["verdict"] == "pass")
    return {"verdict": "pass" if ok else "fail", "read_state": "measured", "n": sum(int(g["n"] or 0) for g in graded),
            "population": pop, "pooled": pooled, "legs_passing": passing,
            "note": f"pooled H-A: record {d_rec}R, prior {d_pre}R; per-leg passes {passing}", "legs": legs}


def _self_test() -> int:
    def arm(n, net, folds):
        return {"n": n, "net_r": net, "folds": [{"net_r": x} for x in folds]}
    rec = {"A": arm(80, -6.0, [1, -2, -3, -2]), "H": arm(60, 4.0, [2, 1, 3, -2])}
    pre = {"A": arm(70, 7.0, [1] * 4), "H": arm(60, 8.0, [1] * 4)}
    g = leg_grade("x", rec, pre, 30, 3)
    assert g["verdict"] == "pass", g
    assert leg_grade("x", rec, dict(pre, H=arm(60, 6.0, [1] * 4)), 30, 3)["verdict"] == "fail"
    assert leg_grade("x", dict(rec, H=arm(10, 4.0, [1, 1, 1, 1])), pre, 30, 3)["verdict"] == "indeterminate"
    assert leg_grade("x", None, pre, 30, 3)["verdict"] == "indeterminate"
    assert leg_grade("x", {"A": rec["A"]}, pre, 30, 3)["verdict"] == "indeterminate"
    legs = [g] * 12
    u = grade_unit(legs)
    assert u["verdict"] == "pass" and u["pooled"]["delta_record"] == 120.0 and u["pooled"]["delta_prior"] == 12.0, u
    bad = leg_grade("y", rec, dict(pre, H=arm(60, 5.0, [1] * 4)), 30, 3)
    assert grade_unit([bad] * 12)["verdict"] == "fail"
    assert grade_unit([g] * 11)["verdict"] == "indeterminate"
    print("htf_native_grade self-test: ok")
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
    v.update({"research_unit": UNIT, "rule": RULE,
              "records": [{"leg": "POOLED:H_minus_A", "verdict": v["verdict"], "read_state": v["read_state"], "n": v["n"],
                           "population": v["population"], "note": v.get("note")}]
              + [{"leg": g["leg"], "verdict": g["verdict"], "read_state": g["read_state"], "n": g["n"],
                  "population": f"{g['leg']}: arm H vs A, record + prior windows", "note": g.get("note")} for g in legs]})
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"unit: {v['verdict']} (n {v['n']}) {v.get('note')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
