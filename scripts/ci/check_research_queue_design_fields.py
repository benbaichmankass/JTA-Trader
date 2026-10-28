#!/usr/bin/env python3
"""Every NEW research-queue unit declares its practice precedent; every NEW intervention test its controls.

WHY THIS EXISTS
---------------
Operator 2026-10-28: designs must rest on real-world practice, not ad hoc choices treated as definitive
(`docs/reference/trading-and-model-practice-principles.md` R1, T1, M6). Checklist rows
`RESEARCH-PRACTICE-PRECEDENT-FIELD` and `RESEARCH-INTERVENTION-CONTROL-SET`. Same grading as
`check_research_queue_decision_rule.py`: a unit NEW on this branch is graded, one that existed at the
merge-base is GRANDFATHERED (counted, never failed), and the population-wide counts print on every run.

RULE 1 -- `practice_precedent` (every new unit). A string that is either
    `none: <reason, >= 10 chars>`   -- no precedent was found or the question is house-specific, said so; or
    a source reference: a principle id (T1..T10, M1..M10, R1..R6), a practice-review tag (S<n>), an http(s) URL,
    or a `docs/research|reference/` path.

RULE 2 -- `intervention_controls` (every new HAND-WRITTEN unit, i.e. one without a `generated:` block, whose title/question is an intervention / exit /
active-management test, detected by keyword or by the block being present). A mapping with
    hold_to_bracket   truthy
    matched_random    {draws: int >= 100}
    best_static       {grid: non-empty list, excludes_test_folds: true}
    bootstrap_group   non-empty (e.g. `trade`)
or `{not_applicable: <reason>}` for a keyword hit that is not an intervention test. The harness is
`scripts/research/intervention_controls.py`.

States, never collapsed (`graded` / `no_base` / `base_unresolved`) are those of the decision-rule guard.

Run:
    python3 scripts/ci/check_research_queue_design_fields.py --base origin/main
    python3 scripts/ci/check_research_queue_design_fields.py --self-test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_research_queue_decision_rule import (  # noqa: E402
    _load_yaml, existed_at_merge_base, queue_files)

_REF = re.compile(r"\b(?:[TMR]\d{1,2}|S\d{1,3})\b|https?://|docs/(?:research|reference)/")
_INTERVENTION = re.compile(
    r"intervention|active[- ]management|trade[- ]management|tighten|partial[_ ]close|in-trade", re.I)
MIN_DRAWS = 100


def precedent_errors(entry: dict) -> List[str]:
    v = entry.get("practice_precedent")
    if not (isinstance(v, str) and v.strip()):
        return ["`practice_precedent` is missing -- cite a principle id / [S#] tag / URL / docs path, "
                "or write `none: <reason>`"]
    s = v.strip()
    if s.lower().startswith("none"):
        if not re.match(r"none:\s*\S.{8,}", s, re.I | re.S):
            return ["`practice_precedent: none` needs a reason of >= 10 characters (`none: <reason>`)"]
        return []
    if not _REF.search(s):
        return [f"`practice_precedent` {s[:60]!r} cites no source: use a principle id (T1..M10, R1..R6), "
                "an [S#] tag, a URL or a docs/research|reference path, or `none: <reason>`"]
    return []


def is_intervention_test(entry: dict) -> bool:
    if "intervention_controls" in entry:
        return True
    text = f"{entry.get('title') or ''} {entry.get('question') or ''}"
    return bool(_INTERVENTION.search(text))


def controls_errors(entry: dict) -> List[str]:
    if not is_intervention_test(entry):
        return []
    c = entry.get("intervention_controls")
    if not isinstance(c, dict):
        return ["intervention/management test with no `intervention_controls` block "
                "(hold_to_bracket + matched_random + best_static; see scripts/research/intervention_controls.py)"]
    na = c.get("not_applicable")
    if na is not None:
        return [] if isinstance(na, str) and len(na.strip()) >= 10 else [
            "`intervention_controls.not_applicable` needs a reason of >= 10 characters"]
    errs = []
    if not c.get("hold_to_bracket"):
        errs.append("`intervention_controls.hold_to_bracket` is required")
    mr = c.get("matched_random")
    d = mr.get("draws") if isinstance(mr, dict) else None
    if not (isinstance(d, int) and not isinstance(d, bool) and d >= MIN_DRAWS):
        errs.append(f"`intervention_controls.matched_random.draws` must be an int >= {MIN_DRAWS}")
    bs = c.get("best_static")
    if not (isinstance(bs, dict) and isinstance(bs.get("grid"), list) and bs["grid"]
            and bs.get("excludes_test_folds") is True):
        errs.append("`intervention_controls.best_static` needs a non-empty `grid` and `excludes_test_folds: true`")
    g = c.get("bootstrap_group")
    if not (isinstance(g, str) and g.strip()):
        errs.append("`intervention_controls.bootstrap_group` is required (e.g. `trade`)")
    return errs


def scan(root: Path, base: Optional[str]) -> Tuple[List[str], dict, str]:
    files = queue_files(root)
    counts = {"units": len(files), "missing_precedent": 0, "intervention_units": 0, "missing_controls": 0,
              "generated_not_graded_for_controls": 0}
    failures: List[str] = []
    base_state = "no_base"
    merge_base_ok = True
    if base is not None:
        p = subprocess.run(["git", "-C", str(root), "merge-base", base, "HEAD"], capture_output=True, text=True)
        merge_base_ok = p.returncode == 0 and bool(p.stdout.strip())
        base_state = "graded" if merge_base_ok else "base_unresolved"
    for rel in files:
        entry, err = _load_yaml(root / rel)
        if err is not None:
            continue  # unreadable is reported by the decision-rule guard; not double-counted here
        errs = [("precedent", e) for e in precedent_errors(entry)]
        # Generated units (template / programme node) are authored once, at the template or programme,
        # and reviewed there; their controls are owned by the programme-authoring lane, so they are
        # counted below and not graded here. Hand-written units are graded.
        if entry.get("generated"):
            counts["generated_not_graded_for_controls"] += is_intervention_test(entry)
        else:
            errs += [("controls", e) for e in controls_errors(entry)]
        counts["intervention_units"] += is_intervention_test(entry)
        counts["missing_precedent"] += any(k == "precedent" for k, _ in errs)
        counts["missing_controls"] += any(k == "controls" for k, _ in errs)
        if not errs or base is None:
            continue
        if merge_base_ok and existed_at_merge_base(root, base, rel):
            continue  # grandfathered: counted, never failed
        why = "NEW unit" if merge_base_ok else "merge-base unreadable, newness UNKNOWN (refusing)"
        failures.append(f"{rel}: {why}: " + "; ".join(e for _, e in errs))
    return failures, counts, base_state


# --------------------------------------------------------------------- self-test
_UNIT = "id: {id}\ntitle: t\nquestion: {q}\nstatus: queued\n{extra}"
_FULL_CONTROLS = """intervention_controls:
  hold_to_bracket: true
  matched_random: {draws: 1000}
  best_static: {grid: [close], excludes_test_folds: true}
  bootstrap_group: trade
"""


def _self_test() -> int:
    bad = 0

    def check(label: str, cond: bool) -> None:
        nonlocal bad
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        bad += not cond

    check("precedent: principle id ok", not precedent_errors({"practice_precedent": "T1, M6 (principles doc)"}))
    check("precedent: [S#] tag ok", not precedent_errors({"practice_precedent": "S18 ACAD"}))
    check("precedent: none with reason ok", not precedent_errors({"practice_precedent": "none: house-specific prop rule"}))
    check("precedent: missing caught", bool(precedent_errors({})))
    check("precedent: bare none caught", bool(precedent_errors({"practice_precedent": "none"})))
    check("precedent: prose with no source caught", bool(precedent_errors({"practice_precedent": "it seemed sensible"})))
    check("controls: non-intervention unit not graded", not controls_errors({"question": "does X predict Y"}))
    check("controls: keyword hit with no block caught", bool(controls_errors({"question": "does a tighten rule help"})))
    check("controls: full block ok", not controls_errors(
        {"question": "intervention?", "intervention_controls": {
            "hold_to_bracket": True, "matched_random": {"draws": 1000},
            "best_static": {"grid": ["a"], "excludes_test_folds": True}, "bootstrap_group": "trade"}}))
    check("controls: few draws caught", bool(controls_errors(
        {"question": "intervention?", "intervention_controls": {
            "hold_to_bracket": True, "matched_random": {"draws": 10},
            "best_static": {"grid": ["a"], "excludes_test_folds": True}, "bootstrap_group": "trade"}})))
    check("controls: best_static fit on test folds caught", bool(controls_errors(
        {"question": "intervention?", "intervention_controls": {
            "hold_to_bracket": True, "matched_random": {"draws": 1000},
            "best_static": {"grid": ["a"], "excludes_test_folds": False}, "bootstrap_group": "trade"}})))
    check("controls: not_applicable with reason ok", not controls_errors(
        {"question": "tighten", "intervention_controls": {"not_applicable": "a static sweep, not an active action"}}))
    check("controls: not_applicable without reason caught", bool(controls_errors(
        {"question": "tighten", "intervention_controls": {"not_applicable": "n/a"}})))

    def git(r: Path, *a: str) -> None:
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "research" / "queue").mkdir(parents=True)
        q = root / "research" / "queue"
        git(root, "init", "-q", "-b", "trunk")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "t")
        (q / "OLD.yaml").write_text(_UNIT.format(id="OLD", q="tighten the stop", extra=""))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "b")
        git(root, "checkout", "-q", "-b", "f")
        (q / "NEW-BAD.yaml").write_text(_UNIT.format(id="NEW-BAD", q="tighten the stop", extra=""))
        (q / "NEW-GOOD.yaml").write_text(_UNIT.format(
            id="NEW-GOOD", q="tighten the stop", extra="practice_precedent: T1 M6\n" + _FULL_CONTROLS))
        (q / "NEW-GEN.yaml").write_text(_UNIT.format(
            id="NEW-GEN", q="tighten the stop", extra="practice_precedent: T1\ngenerated: {family: x}\n"))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "f")
        f, c, st = scan(root, "trunk")
        check("graded state", st == "graded")
        check("NEW unit without either field FAILS (both reasons)",
              any("NEW-BAD" in x and "practice_precedent" in x and "intervention_controls" in x for x in f))
        check("NEW unit with both fields passes", not any("NEW-GOOD" in x for x in f))
        check("OLD unit grandfathered, but counted", not any("OLD" in x for x in f) and c["missing_precedent"] == 2)
        check("generated intervention unit is counted, not graded for controls",
              not any("NEW-GEN" in x for x in f) and c["generated_not_graded_for_controls"] == 1)
        check("no_base fails nothing", scan(root, None)[0] == [])
        f2, _, st2 = scan(root, "does-not-exist")
        check("base_unresolved refuses rather than grants", st2 == "base_unresolved" and any("OLD" in x for x in f2))
    print(f"research-queue-design-fields-guard --self-test: {bad} failure(s)")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    failures, c, st = scan(REPO, a.base)
    print(f"research-queue-design-fields-guard: base_state={st} units={c['units']} "
          f"missing_practice_precedent={c['missing_precedent']} intervention_units={c['intervention_units']} "
          f"missing_controls={c['missing_controls']} "
          f"generated_intervention_units_not_graded={c['generated_not_graded_for_controls']} failures={len(failures)}")
    for f in failures:
        print(f"::error::research-queue-design-fields-guard: {f}")
    if failures:
        return 1
    print("research-queue-design-fields-guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
