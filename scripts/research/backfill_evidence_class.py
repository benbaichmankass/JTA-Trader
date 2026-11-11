#!/usr/bin/env python3
# wiring: row EVIDENCE-CLASS-BACKFILL (2026-11-11); one-shot + re-runnable, reads research/queue/*.yaml, prints a report
"""Backfill ``evidence_class`` on research units whose evidence DESIGN is fixed by structured fields.

WHY (row EVIDENCE-CLASS-BACKFILL, split from RESEARCH-SLO-HELDOUT-SURVIVORS / PR #24983). The diagnostic
``heldout_registered_passes_30d`` (scripts/research/research_slo.py) reads only structured fields. MEASURED
2026-11-11: 382 registered-rule passes graded in the previous 30 days, 314 with no class (``unknown``). A class
is a fact about the unit's DESIGN, so it can be stamped from the argv / workflow inputs that fix the design,
without re-reading a result. This script stamps ONLY those cases; anything else stays unknown and is listed for
a per-unit read (owner proposed: the weekly programme review).

RULES (first match wins; each names the field it reads). holdout per research/queue/PLANNING.md § 1e.
  T1  generated.family == m20-exit-lever                       -> holdout_window, edge   (IS and OOS both graded)
  T2  generated.family == roster-walkforward                   -> in_sample, edge        (variant chosen on all folds)
  T3  generated.family == leg-corpus-s1                        -> none, other            (coverage census)
  T4  generated.family == e35-bracket                          -> holdout_window, edge   (IS/OOS gate)
  T5  generated.family == prop-fit-breakout                    -> in_sample, edge        (EV sim over history)
  T6  generated.family == macro-valuation                      -> none, other            (backfill freshness)
  E1  run.command runs exit_lever_ablation.py --grade holdout  -> holdout_window, edge   (select on discovery, read the
                                                                  latest span once; the script's HoldoutLeak contract)
  E2  run.command runs exit_lever_ablation.py, any other grade -> in_sample, edge        (every arm over the whole window)
  H1  run.command runs harness_stage0.py                       -> in_sample, edge        (calendar folds over the window)
  H2  run.workflow == research-harness-dispatch.yml            -> in_sample, edge        (Stage-0 net R over the window)
  M1  run.workflow == m20-exit-lever-sweep.yml with run.inputs.split_mode containing "oos"
                                                               -> holdout_window, edge
  P1  run.command runs prop_ev_grid.py                         -> in_sample, edge        (EV sim over committed trades)
A unit that already carries ``evidence_class`` is never touched. ``in_sample`` is a real class (counted, and NOT
held-out); it replaces ``unknown``, it does not upgrade anything.

WRITE. The block is inserted as text immediately BEFORE the top-level ``decision_rule:`` line, so the edit is a
pure line addition away from ``last_dispatched_at`` (the dispatcher's stamp line) and the rest of the file is
byte-identical. Editing existing units is a held surface (check_pr_landing STAMP_ONLY_SURFACE): the PR is the
manager's merge.

    python3 scripts/research/backfill_evidence_class.py                     # report only
    python3 scripts/research/backfill_evidence_class.py --write --since 2026-10-12 --include-open
    python3 scripts/research/backfill_evidence_class.py --self-test
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
QUEUE = REPO / "research" / "queue"

FAMILY = {"m20-exit-lever": ("holdout_window", "edge", "T1"), "roster-walkforward": ("in_sample", "edge", "T2"),
          "leg-corpus-s1": ("none", "other", "T3"), "e35-bracket": ("holdout_window", "edge", "T4"),
          "prop-fit-breakout": ("in_sample", "edge", "T5"), "macro-valuation": ("none", "other", "T6")}


def _cmd(unit: Dict[str, Any]) -> List[str]:
    run = unit.get("run") or {}
    cmd = run.get("command") or []
    if not cmd and isinstance(run.get("commands"), list) and run["commands"]:
        cmd = run["commands"][0]
    return [str(t) for t in cmd] if isinstance(cmd, list) else []


def classify(unit: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """(holdout, claim, rule_id) when a rule fixes the design; else None."""
    gen = unit.get("generated") or {}
    fam = str(gen.get("family") or "")
    if fam in FAMILY:
        return FAMILY[fam]
    cmd = _cmd(unit)
    run = unit.get("run") or {}
    if "scripts/research/exit_lever_ablation.py" in cmd:
        grade = cmd[cmd.index("--grade") + 1] if "--grade" in cmd and cmd.index("--grade") + 1 < len(cmd) else None
        return ("holdout_window", "edge", "E1") if grade == "holdout" else ("in_sample", "edge", "E2")
    if "scripts/research/harness_stage0.py" in cmd:
        return "in_sample", "edge", "H1"
    if run.get("workflow") == "research-harness-dispatch.yml":
        return "in_sample", "edge", "H2"
    if run.get("workflow") == "m20-exit-lever-sweep.yml" and "oos" in str((run.get("inputs") or {}).get("split_mode") or ""):
        return "holdout_window", "edge", "M1"
    if "scripts/research/prop_ev_grid.py" in cmd:
        return "in_sample", "edge", "P1"
    return None


_DR = re.compile(r"^decision_rule:", re.M)


def stamp(text: str, holdout: str, claim: str, rule: str) -> Optional[str]:
    m = _DR.search(text)
    if not m:
        return None
    block = (f"evidence_class:  # EVIDENCE-CLASS-BACKFILL 2026-11-11, rule {rule} "
             f"(scripts/research/backfill_evidence_class.py)\n  holdout: {holdout}\n  claim: {claim}\n")
    return text[:m.start()] + block + text[m.start():]


def in_scope(unit: Dict[str, Any], since: str, passes_only: bool, include_open: bool = False) -> bool:
    g = unit.get("grading")
    if include_open and not isinstance(g, dict) and str(unit.get("status")) in ("queued", "blocked"):
        return True  # a future pass: stamp the design now so it is never counted unknown
    if not isinstance(g, dict) or str(g.get("graded_at") or "") < since:
        return False
    if passes_only and str(g.get("verdict")) != "pass":
        return False
    return True


def run(since: str, write: bool, passes_only: bool, include_open: bool = False) -> Dict[str, Any]:
    import yaml
    rules: Counter = Counter()
    left: Counter = Counter()
    left_files: Dict[str, List[str]] = {}
    written, skipped_present, no_anchor = 0, 0, []
    paths = sorted(QUEUE.glob("*.yaml")) + sorted((QUEUE / "blocked").glob("*.yaml"))
    for p in paths:
        text = p.read_text(encoding="utf-8")
        try:
            u = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if not isinstance(u, dict) or not in_scope(u, since, passes_only, include_open):
            continue
        if (u.get("decision_rule") or {}).get("registered_before_run") is not True:
            continue
        if "evidence_class" in u:
            skipped_present += 1
            continue
        if isinstance(u.get("ml_bakeoff"), dict) or str(u.get("kind") or "") == "deterministic":
            continue  # research_slo infers these; not stamped here
        c = classify(u)
        if c is None:
            gen = u.get("generated") or {}
            key = str(gen.get("family") or f"hand:{u.get('theme')}")
            left[key] += 1
            left_files.setdefault(key, []).append(p.stem)
            continue
        rules[c[2]] += 1
        if write:
            new = stamp(text, *c)
            if new is None:
                no_anchor.append(p.stem)
                continue
            p.write_text(new, encoding="utf-8")
            written += 1
    return {"since": since, "passes_only": passes_only, "classified_by_rule": dict(sorted(rules.items())),
            "classified": sum(rules.values()), "still_unknown": sum(left.values()),
            "still_unknown_by_group": dict(left.most_common()), "still_unknown_units": left_files,
            "already_declared": skipped_present, "written": written, "no_decision_rule_anchor": no_anchor}


def _self_test() -> int:
    ok = True
    u_hold = {"run": {"command": ["python3", "scripts/research/exit_lever_ablation.py", "--grade", "holdout"]}}
    u_rep = {"run": {"command": ["python3", "scripts/research/exit_lever_ablation.py", "--grade", "replace"]}}
    u_gen = {"generated": {"family": "roster-walkforward"}, "run": {"command": ["x"]}}
    u_m20 = {"run": {"workflow": "m20-exit-lever-sweep.yml", "inputs": {"split_mode": "oos-trades"}}}
    u_m20_no = {"run": {"workflow": "m20-exit-lever-sweep.yml", "inputs": {}}}
    u_none = {"run": {"command": ["python3", "scripts/research/macro_event_study_run.py"]}}
    cases = [(u_hold, ("holdout_window", "edge", "E1")), (u_rep, ("in_sample", "edge", "E2")),
             (u_gen, ("in_sample", "edge", "T2")), (u_m20, ("holdout_window", "edge", "M1")), (u_m20_no, None),
             (u_none, None)]
    for u, want in cases:
        got = classify(u)
        if got != want:
            print("  FAIL classify", u, got, want)
            ok = False
    txt = "id: X\npower:\n  n: 1\ndecision_rule:\n  id: R\nlast_dispatched_at: null\n"
    new = stamp(txt, "in_sample", "edge", "E2")
    import yaml
    d = yaml.safe_load(new)
    if d.get("evidence_class") != {"holdout": "in_sample", "claim": "edge"} or not new.endswith("last_dispatched_at: null\n") \
            or new.replace(new[new.index("evidence_class:"):new.index("decision_rule:")], "") != txt:
        print("  FAIL stamp", repr(new))
        ok = False
    if stamp("id: X\n", "none", "other", "T3") is not None:
        print("  FAIL stamp without anchor should be None")
        ok = False
    print("backfill_evidence_class self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", default="2026-10-12", help="graded_at >= this (YYYY-MM-DD)")
    ap.add_argument("--all-verdicts", action="store_true", help="also stamp graded non-passes in the window")
    ap.add_argument("--include-open", action="store_true", help="also stamp ungraded queued / blocked units")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    import json
    r = run(a.since, a.write, passes_only=not a.all_verdicts, include_open=a.include_open)
    short = {k: v for k, v in r.items() if k != "still_unknown_units"}
    print(json.dumps(short, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
