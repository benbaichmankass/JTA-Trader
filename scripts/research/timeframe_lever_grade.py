#!/usr/bin/env python3
"""Grade the TIMEFRAME lever family across per-timeframe Stage-0 runs -- row DEMO-FLOOR-ITER-20261113.

A bar size cannot be an arm inside one ``exit_lever_ablation`` run (one run = one data feed), so a timeframe unit runs
the leg once per timeframe (``exit_lever_ablation --timeframe TF --grade stage0 --out <out>/tf_<TF>``) and this script
grades them together under the unit's registered rule:

  baseline   the leg's own timeframe (``--baseline-tf``), run through the SAME harness and window
  candidate  every other timeframe
  PASS       some candidate passes its own Stage-0 grade (net_r > 0 net of the full cost stack, n >= n_floor, >= fold
             majority positive folds -- exit_lever_ablation's stage0 clauses, thresholds from the unit's flags) AND its
             net_r exceeds the baseline timeframe's net_r over the same pinned window
  FAIL       every candidate is graded (n >= n_floor) and none passes both clauses
  INDETERMINATE  a run produced no verdict, the baseline did not run, or a candidate is below its n floor

The same grade serves any ONE-ARM-PER-RUN lever (``--family direction`` / ``filter``): each arm runs as its own Stage-0
run (``--prefix`` names the per-run directory, default ``tf_``), so a candidate must clear Stage 0 on its own -- net_r > 0
net of cost, the n floor and the positive-fold majority -- AND beat the baseline arm. ``exit_lever_ablation --grade
replace`` checks only the second clause (an arm that beats a losing incumbent but still loses would read pass there).

Writes ``<out>/verdict.json`` (E5: verdict / read_state / population / n + one ``records`` row per timeframe).
Tier 1: research tooling; reads only the per-timeframe verdicts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_tf(out: Path, tf: str, prefix: str = "tf_") -> Optional[Dict[str, Any]]:
    p = out / f"{prefix}{tf}" / "verdict.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
    g = ((v.get("measurement") or {}).get("grade")) or {}
    return {"tf": tf, "verdict": v.get("verdict"), "read_state": v.get("read_state"), "label": g.get("label"),
            "net_r": g.get("net_r"), "n": g.get("n"), "folds_positive": g.get("folds_positive"),
            "n_folds": g.get("n_folds"), "n_floor": g.get("n_floor"), "max_drawdown_r": g.get("max_drawdown_r")}


def grade(rows: Dict[str, Optional[Dict[str, Any]]], baseline_tf: str, leg: str,
          family: str = "timeframe") -> Dict[str, Any]:
    base = rows.get(baseline_tf)
    records = []
    for tf, r in rows.items():
        if r is None:
            records.append({"leg": f"{leg}@{tf}", "verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                            "population": f"{leg} at {tf}: the per-timeframe run wrote no verdict", "note": "no verdict.json"})
            continue
        measured = isinstance(r.get("n"), int) and r.get("read_state") == "measured"
        records.append({"leg": f"{leg}@{tf}", "verdict": r["verdict"] if measured else "not_applicable",
                        "read_state": "measured" if measured else (r.get("read_state") or "producer_failed"),
                        "n": r["n"] if measured else None, "role": "baseline" if tf == baseline_tf else "candidate",
                        "net_r": r.get("net_r"), "folds_positive": r.get("folds_positive"), "n_folds": r.get("n_folds"),
                        "max_drawdown_r": r.get("max_drawdown_r"),
                        "population": f"{leg} at {tf}: Stage-0 over the unit's pinned window, net of the full cost stack",
                        "note": f"stage0 {r.get('label')}: net_r {r.get('net_r')} over n {r.get('n')}, "
                                f"folds+ {r.get('folds_positive')}/{r.get('n_folds')}"})
    pop = (f"{leg}: the {family} lever family, {sorted(rows)} through the same harness and pinned window; baseline "
           f"{baseline_tf}; net of the full cost stack")
    if base is None or base.get("net_r") is None:
        return {"verdict": "indeterminate", "read_state": "producer_failed", "n": None, "population": pop,
                "note": f"the baseline timeframe {baseline_tf} produced no graded run", "records": records}
    cands = {tf: r for tf, r in rows.items() if tf != baseline_tf}
    if any(r is None for r in cands.values()):
        return {"verdict": "indeterminate", "read_state": "measured", "n": None, "population": pop,
                "note": "a candidate timeframe run wrote no verdict", "records": records}
    under = [tf for tf, r in cands.items() if not (isinstance(r.get("n"), int) and r.get("n_floor") is not None
                                                  and r["n"] >= r["n_floor"])]
    passing = [tf for tf, r in cands.items() if r.get("verdict") == "pass"
               and isinstance(r.get("net_r"), (int, float)) and r["net_r"] > base["net_r"]]
    n_total = sum(r["n"] for r in rows.values() if r and isinstance(r.get("n"), int))
    if passing:
        best = max(passing, key=lambda t: cands[t]["net_r"])
        return {"verdict": "pass", "read_state": "measured", "n": n_total, "population": pop, "best_tf": best,
                "note": (f"{best} passes Stage 0 (net_r {cands[best]['net_r']}, folds+ {cands[best]['folds_positive']}/"
                         f"{cands[best]['n_folds']}) and beats the {baseline_tf} baseline (net_r {base['net_r']})"),
                "records": records}
    if under:
        return {"verdict": "indeterminate", "read_state": "measured", "n": n_total, "population": pop,
                "note": f"no candidate passes, but {under} are below their n floor -- no FAIL claim", "records": records}
    return {"verdict": "fail", "read_state": "measured", "n": n_total, "population": pop,
            "note": (f"no candidate {family} arm passes Stage 0 and beats the {baseline_tf} baseline (net_r {base['net_r']}): "
                     + "; ".join(f"{tf} {r.get('label')} net_r {r.get('net_r')}" for tf, r in cands.items())),
            "records": records}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=False)
    ap.add_argument("--leg")
    ap.add_argument("--baseline-tf")
    ap.add_argument("--tf", action="append", default=[], help="every timeframe run, baseline included")
    ap.add_argument("--family", default="timeframe", help="the lever family named in the population (timeframe / direction / filter)")
    ap.add_argument("--prefix", default="tf_", help="per-run directory prefix under --out (default tf_)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.out and a.leg and a.baseline_tf and a.tf):
        ap.error("--out, --leg, --baseline-tf and --tf (repeat) are required")
    if a.baseline_tf not in a.tf:
        ap.error("--baseline-tf must be one of the --tf values")
    out = Path(a.out)
    v = grade({tf: read_tf(out, tf, a.prefix) for tf in a.tf}, a.baseline_tf, a.leg, a.family)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, default=str))
    return 0


def _self_test() -> int:
    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    def r(tf, v, net, n=100, floor=30, fp=4):
        return {"tf": tf, "verdict": v, "read_state": "measured", "label": "x", "net_r": net, "n": n,
                "folds_positive": fp, "n_folds": 6, "n_floor": floor, "max_drawdown_r": 5.0}
    g = grade({"15m": r("15m", "fail", -80.0), "1h": r("1h", "fail", -20.0), "4h": r("4h", "pass", 12.0)}, "15m", "L")
    check("a candidate passing Stage 0 and beating the baseline -> pass", g["verdict"] == "pass" and g["best_tf"] == "4h")
    g = grade({"15m": r("15m", "fail", -80.0), "1h": r("1h", "fail", -20.0), "4h": r("4h", "fail", -5.0)}, "15m", "L")
    check("every candidate fails -> fail", g["verdict"] == "fail")
    g = grade({"15m": r("15m", "pass", 20.0), "4h": r("4h", "pass", 10.0)}, "15m", "L")
    check("a passing candidate below the baseline's net R does not pass", g["verdict"] == "fail")
    g = grade({"15m": r("15m", "fail", -80.0), "4h": r("4h", "indeterminate", 3.0, n=12)}, "15m", "L")
    check("a candidate under its n floor -> indeterminate, never fail", g["verdict"] == "indeterminate")
    g = grade({"15m": None, "4h": r("4h", "pass", 3.0)}, "15m", "L")
    check("no baseline -> indeterminate / producer_failed", g["verdict"] == "indeterminate" and g["read_state"] == "producer_failed")
    g = grade({"15m": r("15m", "fail", -80.0), "4h": None}, "15m", "L")
    check("a missing candidate run -> indeterminate", g["verdict"] == "indeterminate")
    g = grade({"A": r("A", "fail", -3.35), "L": r("L", "fail", 0.9, n=40)}, "A", "L", family="direction")
    check("a direction arm that beats a losing baseline but fails its own Stage 0 -> fail", g["verdict"] == "fail"
          and "direction lever family" in g["population"])
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "arm_L").mkdir()
        (Path(td) / "arm_L" / "verdict.json").write_text(json.dumps(
            {"verdict": "pass", "read_state": "measured", "measurement": {"grade": {"label": "x", "net_r": 2.0, "n": 40}}}))
        check("--prefix reads <out>/<prefix><label>/verdict.json", (read_tf(Path(td), "L", "arm_") or {}).get("net_r") == 2.0)
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
