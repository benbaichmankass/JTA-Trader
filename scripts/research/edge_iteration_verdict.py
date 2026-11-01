#!/usr/bin/env python3
# wiring: research-script-run units RQ-20261101-d1f3-05 (movement-capture cost-ceiling iteration); reads two harness result.json files, writes verdict.json.
"""Combine a control run and one ablation arm of an edge harness into the verdict.json the research-script-run record needs.

The harness (edge_movement_capture.py) grades ONE grid per invocation. A one-factor cost ablation is two invocations (control at the
registered cost, arm at the ceiling cost) over the SAME grid; this reads both and states the registered reading:

  PASS  iff the ARM's selected config clears the unchanged registered rule (all `verdict.checks`, DSR at the CUMULATIVE trial count
        the arm run was given) -- then ONE holdout read is next, never a book;
  FAIL  iff the arm computed and did not clear it: THIS cost level does not rescue the family at the tested geometry (the map
        records the response; no family is closed by it);
  INDETERMINATE iff either side did not compute.
Usage: edge_iteration_verdict.py --control ctl.json --arm arm.json --out <out_dir> [--factor "round-trip cost bps"] [--self-test]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def combine(ctl: dict, arm: dict, factor: str) -> dict:
    def top(r):
        sel = r.get("selected")
        c = (r.get("configs") or {}).get(sel) or {}
        p, st = c.get("primary") or {}, c.get("stress") or {}
        return sel, p, st
    cs, cp, _ = top(ctl)
    asel, ap_, ast = top(arm)
    ok = bool(cp.get("sharpe_net") is not None and ap_.get("sharpe_net") is not None)
    v = ("indeterminate" if not ok else "pass" if (arm.get("verdict") or {}).get("verdict") == "pass" else "fail")
    meas = {"factor": factor, "control": {"selected": cs, "sharpe": cp.get("sharpe_net"), "ann": cp.get("ann_return_net"),
                                          "verdict": (ctl.get("verdict") or {}).get("verdict")},
            "arm": {"selected": asel, "sharpe": ap_.get("sharpe_net"), "ann": ap_.get("ann_return_net"), "stress_sharpe": ast.get("sharpe_net"),
                    "dsr": ap_.get("dsr"), "checks": (arm.get("verdict") or {}).get("checks"),
                    "per_config_sharpe": {k: (c.get("primary") or {}).get("sharpe_net") for k, c in (arm.get("configs") or {}).items()}},
            "delta_sharpe": (round(ap_["sharpe_net"] - cp["sharpe_net"], 3) if ok else None)}
    return {"verdict": v, "read_state": "measured" if ok else "insufficient", "n": ap_.get("n_days"),
            "population": f"{factor}: control vs arm over the same {len(arm.get('configs') or {})}-config grid, {len(arm.get('universe') or [])} symbols, "
                          f"daily, n_days={ap_.get('n_days')}, arm DSR N={arm.get('n_trials')}",
            "note": f"arm selected {asel} Sharpe {ap_.get('sharpe_net')} vs control {cs} {cp.get('sharpe_net')}; arm verdict "
                    f"{(arm.get('verdict') or {}).get('verdict')}", "measurement": meas}


def _self_test() -> int:
    mk = lambda sh, vd: {"selected": "X", "configs": {"X": {"primary": {"sharpe_net": sh, "ann_return_net": 0.1, "dsr": 0.9, "n_days": 9}, "stress": {"sharpe_net": 0.1}}},
                         "verdict": {"verdict": vd, "checks": {"a": vd == "pass"}}, "n_trials": 16, "universe": ["A"]}
    r1 = combine(mk(-0.7, "fail"), mk(0.2, "fail"), "f")
    r2 = combine(mk(-0.7, "fail"), mk(1.2, "pass"), "f")
    r3 = combine(mk(-0.7, "fail"), {"selected": None, "configs": {}}, "f")
    ok = r1["verdict"] == "fail" and r2["verdict"] == "pass" and r3["verdict"] == "indeterminate" and r1["measurement"]["delta_sharpe"] == 0.9
    print(("PASS" if ok else "FAIL") + " combine: pass only when the arm clears the rule; missing arm is indeterminate, never fail")
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--control", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--factor", default="round-trip cost bps")
    a = ap.parse_args()
    doc = combine(json.loads(Path(a.control).read_text()), json.loads(Path(a.arm).read_text()), a.factor)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "verdict.json").write_text(json.dumps(doc, indent=1, default=str))
    print(json.dumps({k: doc[k] for k in ("verdict", "note")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
