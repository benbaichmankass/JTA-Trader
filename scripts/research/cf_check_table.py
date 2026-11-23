#!/usr/bin/env python3
# wiring: manual-only - performance-review C14 (counterfactual CHECK table); reads a cf_bulk_live run dir: python3 scripts/research/cf_check_table.py --run <dir> [--json]  (or --live to run the bulk grader first)
"""cf_check_table: the counterfactual CHECK table of the weekly performance review (CHECK C14, CF-D4-PERFREVIEW-TABLE).

Input: a ``cf_bulk_live`` run directory (``records.jsonl.gz``, ``manifest.json``, ``fidelity.json``). Output: one row per leg
(strategy), every number with its population, nothing interpreted. NO GATE: this prints; it refuses nothing and decides nothing.

Per leg, over the graded packages in the run (a package is one decision; windows are the run's whole history unless ``--since``):
  n_graded        packages graded by the engine for this leg
  fidelity        the REGISTERED rule's verdict for the leg (abs_gap_r <= 0.10 on >= 80%, n >= 10 else INDETERMINATE)
  actual_net_r    mean net R of the recorded outcome (venue closed-pnl where priced, else journal): ESTIMATED where the journal priced it
  replayed_net_r  mean net R of the engine's replay of the leg's own management (the like-for-like baseline)
  best_arm        the counterfactual arm (any family but actual/replayed) with the highest mean net R minus the replay, over packages
                  where BOTH resolved; ``delta`` is that mean difference with a 95% bootstrap CI that resamples PACKAGES
  arms_searched   how many arms the best was picked from. The best of N arms is an IN-SAMPLE maximum: a positive delta is a
                  LEAD for a pre-registered test, never a result (design § 1.1: the best static arm is chosen on train folds only)
  readable        True only when fidelity is PASS; otherwise the arms are ESTIMATED_LOW_FIDELITY and the row says so
A leg with no graded package is not in the table; the run's ``could_not_grade`` reasons are printed under it (a count of 0
means nothing was looked at only if the run's manifest says it could not look: the manifest's counts are quoted, not recomputed).
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

NOT_ARMS = {"actual", "replayed_actual", "original_brackets"}
N_BOOT = 1000
SEED = 11


def _arm_map(rec: dict) -> Dict[str, dict]:
    return {a["arm_id"]: a for a in rec.get("arms", []) if a.get("arm_id")}


def _mean(v: Sequence[float]) -> Optional[float]:
    return None if not v else sum(v) / len(v)


def _ci(diffs: List[float]) -> Optional[List[float]]:
    if len(diffs) < 2:
        return None
    rng = random.Random(SEED)
    m = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(N_BOOT))
    return [round(m[int(0.025 * N_BOOT)], 4), round(m[min(N_BOOT - 1, int(0.975 * N_BOOT))], 4)]


def leg_row(leg: str, recs: List[dict], fid: dict) -> Dict[str, Any]:
    maps = [_arm_map(r) for r in recs]
    act = [m["actual"]["net_r"] for m in maps if m.get("actual") and m["actual"].get("net_r") is not None]
    rep = [m["replayed_actual"]["net_r"] for m in maps if m.get("replayed_actual") and m["replayed_actual"].get("net_r") is not None]
    diffs: Dict[str, List[float]] = defaultdict(list)
    for m in maps:
        base = m.get("replayed_actual")
        if not base or base.get("net_r") is None or not base.get("resolved", True):
            continue
        for aid, a in m.items():
            if aid in NOT_ARMS or a.get("net_r") is None or not a.get("resolved", True):
                continue
            diffs[aid].append(a["net_r"] - base["net_r"])
    ranked = sorted(((sum(v) / len(v), aid, v) for aid, v in diffs.items() if len(v) >= 5), key=lambda x: -x[0])
    lf = (fid.get("per_leg") or {}).get(leg) or {}
    verdict = lf.get("verdict", "INDETERMINATE")
    row: Dict[str, Any] = {"leg": leg, "n_graded": len(recs), "fidelity": verdict, "fidelity_frac_within_tol": lf.get("frac_within_tol"),
                           "fidelity_n": lf.get("n_with_gap"), "actual_net_r": None if not act else round(_mean(act), 4), "actual_n": len(act),
                           "replayed_net_r": None if not rep else round(_mean(rep), 4), "replayed_n": len(rep),
                           "arms_searched": len(ranked), "readable": verdict == "PASS", "provenance": "ESTIMATED"}
    if ranked:
        d, aid, v = ranked[0]
        row["best_arm"] = {"arm_id": aid, "n": len(v), "delta_net_r": round(d, 4), "ci95": _ci(v),
                           "note": "IN-SAMPLE best of arms_searched; a lead, not a result"}
    else:
        row["best_arm"] = None
    return row


def build(run: Path, since: Optional[str] = None) -> Dict[str, Any]:
    recs = [json.loads(ln) for ln in gzip.open(run / "records.jsonl.gz", "rt", encoding="utf-8")]
    if since:
        recs = [r for r in recs if str(((r.get("path") or {}).get("t_entry")) or "") >= since]
    fid = json.loads((run / "fidelity.json").read_text())
    man = json.loads((run / "manifest.json").read_text())
    by: Dict[str, List[dict]] = defaultdict(list)
    for r in recs:
        by[str(r.get("strategy"))].append(r)
    rows = sorted((leg_row(k, v, fid) for k, v in by.items()), key=lambda r: -r["n_graded"])
    return {"schema": "cf_check_table/1", "run": run.name, "population": {"closed_n": (man.get("population") or {}).get("closed_n"),
            "graded": len(recs), "could_not_grade_by_reason": man.get("could_not_grade_by_reason"), "window": since or "whole run history"},
            "fidelity_overall": fid.get("overall"), "rule": fid.get("rule"), "legs": rows, "provenance": "ESTIMATED"}


def render(t: Dict[str, Any]) -> str:
    f = lambda x: "—" if x is None else (f"{x:+.3f}" if isinstance(x, float) else str(x))
    pc = lambda x: "—" if x is None else f"{x:.1%}"
    o = t["fidelity_overall"] or {}
    out = [f"## C14 Counterfactual CHECK table — run {t['run']}",
           f"population: {t['population']['graded']} graded of {t['population']['closed_n']} closed packages ({t['population']['window']}); "
           f"not graded: {t['population']['could_not_grade_by_reason']}",
           f"fidelity (registered rule abs_gap_r <= {t['rule']['tol_r']} on >= {t['rule']['frac']:.0%}): overall {o.get('verdict')} "
           f"{pc(o.get('frac_within_tol'))} within tol, n={o.get('n_with_gap')}, median abs gap {f(o.get('median_abs_gap_r'))} R", "",
           "| leg | n | fidelity (frac, n) | actual net R | replayed net R | best arm vs replay (n, ΔR, 95% CI, of N searched) | readable |",
           "|---|---|---|---|---|---|---|"]
    for r in t["legs"]:
        b = r["best_arm"]
        best = "—" if not b else f"{b['arm_id']} (n={b['n']}, {b['delta_net_r']:+.3f}, {b['ci95']}, of {r['arms_searched']})"
        out.append(f"| {r['leg']} | {r['n_graded']} | {r['fidelity']} ({pc(r['fidelity_frac_within_tol'])}, {r['fidelity_n']}) | "
                   f"{f(r['actual_net_r'])} | {f(r['replayed_net_r'])} | {best} | {'yes' if r['readable'] else 'no: ESTIMATED_LOW_FIDELITY'} |")
    out += ["", "Best arm = in-sample maximum over the arms searched; a positive ΔR is a lead for a pre-registered test, not a result. "
            "Provenance ESTIMATED. A '—' means it could not be read."]
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a cf_bulk_live run dir")
    ap.add_argument("--since", help="keep graded packages whose entry is >= this ISO date")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write the table here (json)")
    a = ap.parse_args(argv)
    t = build(Path(a.run), a.since)
    if a.out:
        Path(a.out).write_text(json.dumps(t, indent=1) + "\n")
    print(json.dumps(t, indent=1) if a.json else render(t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
