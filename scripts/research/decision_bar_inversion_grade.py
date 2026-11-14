#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-01 (FORMING-BAR-INVERSION diagnosis) dispatches it as its last command
"""Grade the FORMING-BAR INVERSION diagnosis: would these legs pass deciding on the CLOSED bar?

Row DEMO-FLOOR-ITER-20261113, manager ruling 2026-11-14 04:07Z. Of the closed-bar responders re-run
on the forming bar in round 3 (RQ-20261113-f251-10, -14, -19, -21, -22, -23), none passed. Two
readings compete: (i) the decision bar matters (a closed-bar edge needs the bar's close), or
(ii) the WINDOW matters (the closed-bar passes were measured over 2020..2026; the forming re-runs
over one bad year), and the bar is incidental. This grader reads ONE exit_lever_ablation run per
leg per window, each carrying every arm on the SAME candle CSV and 1m feed:

  F       the leg config-exact on the FORMING bar (the incumbent; as f251 ran it)
  C       the same config with ``decision_bar: closed`` (the pure bar switch)
  C_<x>   ``decision_bar: closed`` plus ONE lever already run forming in round 3

THE RULE (registered in RQ-20261114-db1a-01 before the run; this module only applies it):
  candidate  every closed arm (C and C_<x>) of a leg.
  passes     on the RECORD window: net_r > 0 net of the full cost stack, n >= n_floor, >= fold_majority
             of n_folds calendar folds positive, AND net_r > F's net_r; AND on the CONFIRMATION window
             (the equal-length window before it): net_r > 0 AND net_r > F's net_r there.
  leg        pass if any candidate passes (``closed_only_pass`` says whether the bare switch C did);
             fail if every candidate is graded and none passes; indeterminate if a run or the F arm
             is missing, or a non-passing candidate sits under its n floor on the record window.
  unit       indeterminate if any leg is; else pass if any leg passes; else fail.

DESCRIPTIVE (no verdict depends on it): per window, the bar effect C - F and the entry overlap of
C and F (Jaccard on entry_time); per lever, the closed lever delta C_<x> - C. Reading (ii) predicts
the closed lever delta on the record window has the SAME sign as the forming one; reading (i)
predicts it does not.

Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

UNIT = "RQ-20261114-db1a-01"
RULE = "RULE-DBINV-FORMING-INVERSION-20261114"


def stage0(arm: Dict[str, Any], n_floor: int, fold_majority: int) -> Dict[str, Any]:
    """Stage-0 clauses for one arm summary (exit_lever_ablation measurement.arms[label])."""
    folds = arm.get("folds") or []
    pos = sum(1 for f in folds if isinstance(f.get("net_r"), (int, float)) and f["net_r"] > 0)
    n, net = arm.get("n"), arm.get("net_r")
    ok = (isinstance(n, int) and isinstance(net, (int, float)) and net > 0 and n >= n_floor
          and pos >= fold_majority)
    return {"n": n, "net_r": net, "folds_positive": pos, "n_folds": len(folds), "stage0": ok,
            "under_floor": not (isinstance(n, int) and n >= n_floor)}


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


def entries(run_dir: Path, label: str) -> Optional[set]:
    p = run_dir / "arms" / f"{label}__trades.jsonl"
    if not p.exists():
        return None
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
        except ValueError:
            continue
        out.add((str(t.get("entry_time")), str(t.get("direction") or t.get("side"))))
    return out


def jaccard(a: Optional[set], b: Optional[set]) -> Optional[float]:
    if a is None or b is None or not (a | b):
        return None
    return round(len(a & b) / len(a | b), 4)


def grade_leg(leg: str, rec: Optional[Dict[str, Any]], pre: Optional[Dict[str, Any]], forming: str,
              n_floor: int, fold_majority: int, rec_dir: Optional[Path] = None,
              pre_dir: Optional[Path] = None) -> Dict[str, Any]:
    pop = (f"{leg}: closed-bar arms vs the forming incumbent {forming!r} on the same candle CSV and 1m feed, "
           "record window + the equal-length window before it, net of the full cost stack")
    if rec is None or pre is None or forming not in rec or forming not in pre:
        return {"leg": leg, "verdict": "indeterminate", "read_state": "producer_failed", "n": None,
                "population": pop, "note": "a window run or the forming arm wrote no verdict"}
    f_rec, f_pre = rec[forming].get("net_r"), pre[forming].get("net_r")
    cands = sorted(k for k in rec if k != forming)
    if not cands:
        return {"leg": leg, "verdict": "indeterminate", "read_state": "producer_failed", "n": None,
                "population": pop, "note": "the record run carries no closed-bar arm"}
    rows: List[Dict[str, Any]] = []
    passing, under = [], []
    for c in cands:
        g = stage0(rec[c], n_floor, fold_majority)
        cp = pre.get(c) or {}
        conf = cp.get("net_r")
        beats = isinstance(g["net_r"], (int, float)) and isinstance(f_rec, (int, float)) and g["net_r"] > f_rec
        holds = (isinstance(conf, (int, float)) and isinstance(f_pre, (int, float)) and conf > 0 and conf > f_pre)
        ok = bool(g["stage0"] and beats and holds)
        if ok:
            passing.append(c)
        elif g["under_floor"]:
            under.append(c)
        rows.append({"arm": c, "record": g, "beats_forming_record": beats, "confirm_net_r": conf,
                     "confirm_n": cp.get("n"), "holds_on_confirmation": holds, "pass": ok})
    desc: Dict[str, Any] = {}
    for w, arms, d in (("record", rec, rec_dir), ("confirmation", pre, pre_dir)):
        c0 = (arms.get("C") or {}).get("net_r")
        f0 = (arms.get(forming) or {}).get("net_r")
        desc[w] = {"bar_effect_C_minus_F": (round(c0 - f0, 4) if isinstance(c0, (int, float))
                                            and isinstance(f0, (int, float)) else None),
                   "entry_jaccard_C_F": (jaccard(entries(d, "C"), entries(d, forming)) if d else None),
                   "closed_lever_delta_vs_C": {k: round(arms[k]["net_r"] - c0, 4) for k in arms
                                               if k not in ("C", forming) and isinstance(c0, (int, float))
                                               and isinstance((arms.get(k) or {}).get("net_r"), (int, float))}}
    n_total = sum(int(r["record"]["n"]) for r in rows if isinstance(r["record"]["n"], int)) + int(rec[forming].get("n") or 0)
    base = {"leg": leg, "population": pop, "n": n_total, "read_state": "measured", "forming_record_net_r": f_rec,
            "forming_confirm_net_r": f_pre, "arms": rows, "descriptive": desc}
    if passing:
        best = max(passing, key=lambda k: rec[k]["net_r"])
        return dict(base, verdict="pass", best_arm=best, closed_only_pass="C" in passing,
                    note=f"{passing} pass on the record window and hold on the confirmation window; best {best}")
    if under:
        return dict(base, verdict="indeterminate", n=None,
                    note=f"no closed arm passes, but {under} are under the n floor on the record window")
    return dict(base, verdict="fail", closed_only_pass=False,
                note="no closed arm passes Stage 0, beats the forming incumbent and holds on the confirmation window")


def grade_unit(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    vs = [g["verdict"] for g in legs]
    if "indeterminate" in vs:
        top, rs = "indeterminate", "measured"
    elif "pass" in vs:
        top, rs = "pass", "measured"
    else:
        top, rs = "fail", "measured"
    n = None if top == "indeterminate" else sum(int(g.get("n") or 0) for g in legs)
    return {"verdict": top, "read_state": rs, "n": n, "research_unit": UNIT, "rule": RULE,
            "population": ("closed-bar arms vs the forming incumbent for " + ", ".join(g["leg"] for g in legs)
                           + "; record + confirmation windows; full cost stack"),
            "records": [{"leg": g["leg"], "verdict": g["verdict"], "read_state": g["read_state"], "n": g.get("n"),
                         "population": g["population"], "note": g.get("note")} for g in legs],
            "legs": legs}


def _self_test() -> int:
    def arm(n, net, folds):
        return {"n": n, "net_r": net, "folds": [{"net_r": x} for x in folds]}
    rec = {"F": arm(80, -6.0, [1, -2, -3, -2]), "C": arm(70, 5.0, [2, 1, 3, -1]), "C_X": arm(60, 9.0, [3, 3, 3, 0])}
    pre = {"F": arm(70, 7.0, [1] * 4), "C": arm(65, 8.0, [1] * 4), "C_X": arm(55, 6.0, [1] * 4)}
    g = grade_leg("leg", rec, pre, "F", 30, 3)
    assert g["verdict"] == "pass" and g["best_arm"] == "C" and g["closed_only_pass"], g
    # C_X fails confirmation (6 < F's 7) although it is best on the record window
    assert [r["arm"] for r in g["arms"] if r["pass"]] == ["C"], g["arms"]
    assert g["descriptive"]["record"]["bar_effect_C_minus_F"] == 11.0
    assert g["descriptive"]["record"]["closed_lever_delta_vs_C"] == {"C_X": 4.0}
    pre_bad = dict(pre, C=arm(65, -1.0, [0] * 4))
    g2 = grade_leg("leg", rec, pre_bad, "F", 30, 3)
    assert g2["verdict"] == "fail", g2
    rec_small = dict(rec, C=arm(10, -1.0, [1, -1, -1, -1]), C_X=arm(60, -2.0, [1, 1, -1, -3]))
    assert grade_leg("leg", rec_small, pre, "F", 30, 3)["verdict"] == "indeterminate"
    assert grade_leg("leg", None, pre, "F", 30, 3)["verdict"] == "indeterminate"
    assert grade_leg("leg", {"C": rec["C"]}, pre, "F", 30, 3)["verdict"] == "indeterminate"
    assert grade_leg("leg", {"F": rec["F"]}, pre, "F", 30, 3)["verdict"] == "indeterminate"
    u = grade_unit([g, g2])
    assert u["verdict"] == "pass" and u["n"] == g["n"] + g2["n"], u
    assert grade_unit([g2, g2])["verdict"] == "fail"
    assert grade_unit([g, grade_leg("x", None, None, "F", 30, 3)])["verdict"] == "indeterminate"
    assert jaccard({1, 2}, {2, 3}) == round(1 / 3, 4) and jaccard(None, {1}) is None
    print("decision_bar_inversion_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out", help="the unit's out_dir; reads <out>/<rec-prefix><leg> and <out>/<pre-prefix><leg>")
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--forming", default="F", help="the forming-incumbent arm label")
    ap.add_argument("--rec-prefix", default="rec_")
    ap.add_argument("--pre-prefix", default="pre_")
    ap.add_argument("--n-floor", type=int, default=30)
    ap.add_argument("--n-floor-leg", action="append", default=[], metavar="LEG=N",
                    help="a per-leg record-window n floor (the leg's own f251 floor), overriding --n-floor")
    ap.add_argument("--fold-majority", type=int, default=3)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not a.leg:
        ap.error("--out and at least one --leg are required")
    out = Path(a.out)
    floors = {k: int(v) for k, _, v in (x.partition("=") for x in a.n_floor_leg)}
    legs = []
    for leg in a.leg:
        rd, pd_ = out / f"{a.rec_prefix}{leg}", out / f"{a.pre_prefix}{leg}"
        legs.append(grade_leg(leg, read_arms(rd), read_arms(pd_), a.forming, floors.get(leg, a.n_floor),
                              a.fold_majority, rd, pd_))
    v = grade_unit(legs)
    v["params"] = {"n_floor": a.n_floor, "n_floor_leg": floors, "fold_majority": a.fold_majority,
                   "forming_arm": a.forming}
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    for g in legs:
        print(f"{g['leg']:28s} {g['verdict']:13s} {g.get('note')}")
    print(f"unit: {v['verdict']} (n {v['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
