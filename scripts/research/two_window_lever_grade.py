#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-06 (trend_donchian_eth_prop min_confidence 0.8) dispatches it as its last command
"""Grade ONE lever arm X vs arm A (the leg config-exact) per leg on two windows: the record year and the year before.

Row DEMO-FLOOR-ITER-20261113 (census candidates, manager 2026-11-14). Reads ONE ``exit_lever_ablation`` run per leg per
window (``<out>/rec_<leg>``, ``<out>/pre_<leg>``) carrying arms A and X on one feed. The unit carries its own rule id.

THE RULE (registered in the calling unit before the run; this module only applies it):
  per leg  X passes Stage 0 on the record window (net_r > 0, n >= the leg's floor, >= fold_majority of n_folds positive)
           AND beats A there, AND on the prior window X net_r > 0 and > A's. X under its n floor is indeterminate; a
           missing run or arm is indeterminate (producer_failed). A per-leg pass is a Tier-3 proposal candidate.
  unit     pass iff every graded leg passes; fail iff any graded leg fails; indeterminate iff no leg is graded.

Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def leg_grade(leg: str, x: str, rec: Optional[dict], pre: Optional[dict], n_floor: int,
              fold_majority: int) -> Dict[str, Any]:
    if not rec or not pre or not all(k in rec and k in pre for k in ("A", x)):
        return {"leg": leg, "verdict": "indeterminate", "read_state": "producer_failed", "n": None,
                "note": f"a window run or an arm (A/{x}) wrote no verdict"}
    a_r, x_r, a_p, x_p = (_num(rec["A"].get("net_r")), _num(rec[x].get("net_r")),
                          _num(pre["A"].get("net_r")), _num(pre[x].get("net_r")))
    folds = rec[x].get("folds") or []
    pos = sum(1 for f in folds if isinstance(f.get("net_r"), (int, float)) and f["net_r"] > 0)
    n_x = rec[x].get("n")
    under = not (isinstance(n_x, int) and n_x >= n_floor)
    stage0 = bool(x_r is not None and x_r > 0 and not under and pos >= fold_majority)
    beats = x_r is not None and a_r is not None and x_r > a_r
    holds = x_p is not None and a_p is not None and x_p > 0 and x_p > a_p
    ok = bool(stage0 and beats and holds)
    return {"leg": leg, "verdict": "pass" if ok else ("indeterminate" if under else "fail"), "read_state": "measured",
            "n": int(rec["A"].get("n") or 0) + int(pre["A"].get("n") or 0),
            "record": {"A_net_r": a_r, "A_n": rec["A"].get("n"), "X_net_r": x_r, "X_n": n_x, "X_folds_positive": pos,
                       "X_n_folds": len(folds), "X_stage0": stage0, "X_beats_A": beats},
            "prior": {"A_net_r": a_p, "A_n": pre["A"].get("n"), "X_net_r": x_p, "X_n": pre[x].get("n"), "holds": holds},
            "note": (f"record {x} {x_r} (n {n_x}, {pos}/{len(folds)}) vs A {a_r}; prior {x} {x_p} vs A {a_p}"
                     + (f" -- {x} under the n floor {n_floor}" if under else ""))}


def grade_unit(legs: List[Dict[str, Any]], x: str, population: str) -> Dict[str, Any]:
    graded = [g for g in legs if g["verdict"] in ("pass", "fail")]
    if not graded:
        return {"verdict": "indeterminate", "read_state": "producer_failed" if all(
            g["read_state"] != "measured" for g in legs) else "measured", "n": None, "population": population,
                "note": "no leg graded", "legs": legs}
    v = "pass" if all(g["verdict"] == "pass" for g in graded) else "fail"
    return {"verdict": v, "read_state": "measured", "n": sum(int(g["n"] or 0) for g in graded), "population": population,
            "arm": x, "note": "; ".join(f"{g['leg']} {g['verdict']}: {g['note']}" for g in legs), "legs": legs}


def _self_test() -> int:
    def arm(n, net, folds):
        return {"n": n, "net_r": net, "folds": [{"net_r": f} for f in folds]}
    rec = {"A": arm(160, -9.0, [1, -2, -3, -2]), "M": arm(130, 6.0, [2, 1, 3, -1])}
    pre = {"A": arm(180, -4.0, [1] * 4), "M": arm(150, 3.0, [1] * 4)}
    g = leg_grade("x", "M", rec, pre, 30, 3)
    assert g["verdict"] == "pass", g
    assert leg_grade("x", "M", rec, dict(pre, M=arm(150, -1.0, [1] * 4)), 30, 3)["verdict"] == "fail"
    assert leg_grade("x", "M", dict(rec, M=arm(20, 6.0, [1] * 4)), pre, 30, 3)["verdict"] == "indeterminate"
    assert leg_grade("x", "M", dict(rec, M=arm(130, 6.0, [1, 1, -1, -1])), pre, 30, 3)["verdict"] == "fail"
    assert leg_grade("x", "M", None, pre, 30, 3)["read_state"] == "producer_failed"
    assert grade_unit([g], "M", "p")["verdict"] == "pass"
    assert grade_unit([leg_grade("x", "M", None, pre, 30, 3)], "M", "p")["verdict"] == "indeterminate"
    print("two_window_lever_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out")
    ap.add_argument("--arm", default="M")
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--unit")
    ap.add_argument("--rule")
    ap.add_argument("--population", default=None,
                    help="population text; default names the legs, the arm and the two windows (a run token may not "
                         "contain '..', so the unit leaves this to the default)")
    ap.add_argument("--n-floor", type=int, default=30)
    ap.add_argument("--fold-majority", type=int, default=3)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not a.leg or not a.unit or not a.rule:
        ap.error("--out, --unit, --rule and at least one --leg are required")
    out = Path(a.out)
    legs = [leg_grade(leg, a.arm, read_arms(out / f"rec_{leg}"), read_arms(out / f"pre_{leg}"), a.n_floor,
                      a.fold_majority) for leg in a.leg]
    pop = a.population or (f"{', '.join(a.leg)}: arm {a.arm} vs A (config-exact), record 2025-11-13 to 2026-11-12 and "
                           "prior 2024-11-13 to 2025-11-12, full cost stack")
    v = grade_unit(legs, a.arm, pop)
    v.update({"research_unit": a.unit, "rule": a.rule,
              "records": [{"leg": g["leg"], "verdict": g["verdict"], "read_state": g["read_state"], "n": g["n"],
                           "population": f"{g['leg']}: arm {a.arm} vs A, record + prior windows", "note": g.get("note")}
                          for g in legs]})
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"unit: {v['verdict']} (n {v['n']}) {v.get('note')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
