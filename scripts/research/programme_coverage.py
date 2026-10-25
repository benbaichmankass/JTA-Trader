#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (programme-coverage); scripts/ci/check_research_queue_health.py (health line)
"""Programme coverage: does every question a research programme PLAN asks have a node in
its machine-read tree (research/programmes/<NN>-*.yaml)?

WHY THIS EXISTS (lane RESEARCH-ENGINE-1016, operator 2026-10-16: "We have the plan. We
have ideas. Why can't we actually follow through ... we have all the pieces but can't put
them together"). `queue_replenish.py` reads research/programmes/*.yaml as its sixth source:
a `unit:` node is emitted once its prerequisites close, a `needs_authoring:` node is listed
in the authoring queue research-ops drafts from first. A question that is in the PLAN
(docs/research/programmes/<NN>-*.md) but in NO tree node is invisible to all of that --
it never reaches the authoring queue, never becomes a unit, never gets graded. MEASURED
2026-10-16 07:30Z on main: plans 01..06 exist; trees exist only for 01 and 02, so every
question of 03 STRATEGY, 04 MACRO, 05 PROP and 06 DATA was unreachable by the machine,
and 01/02 cover only some of theirs (run this script for the current numbers).

WHAT COUNTS
  question  a top-level `Q<n>` (or `Q<n>-<X>`, e.g. Q2-C) named in the plan's "Questions"
            section: the first cell of a table row (`| **Q1** | ...`) or a `### Q<n>` heading
            (every Q<n> on that heading line: "### Q6 / Q7"). Sub-rungs (Q1.2) are the tree's
            business, not the plan index's.
  covered   a tree node whose id is `P<n>-<Q>` or starts `P<n>-<Q>.` / `P<n>-<Q>-` (P2-Q2.1-fail
            covers Q2), or carries `question: <Q>`.
  carried   the tree's top-level `questions:` map discharges it explicitly:
            `Q6: {state: carried|closed|by_design, by: "<checklist row | RQ id>", why: "..."}`.
            A build question is a checklist row (CLAUDE.md "two categories"); a question the
            plan keeps dormant by design says so. `by` and `why` are required -- a bare
            discharge is refused, so "carried" can never be a quiet way to read green.
  uncovered everything else, including every question of a plan with no tree file.

THE GUARD (--check) is a RATCHET over scripts/research/programme_coverage_baseline.json:
a programme's uncovered count may never rise above its baseline, a plan with no baseline
entry may not have uncovered questions, and a plan without a tree file is always reported.
The baseline only moves DOWN (`--write-baseline` refuses to raise an entry). It does not
fail on today's gap -- that gap is work, owned by the programme lanes the manager dispatches.

Tier-1 research tooling: reads docs + research/programmes, writes only the baseline file.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
PLANS = Path("docs/research/programmes")
TREES = Path("research/programmes")
BASELINE = Path("scripts/research/programme_coverage_baseline.json")
_PLAN_RE = re.compile(r"^(\d{2})-[A-Z0-9-]+\.md$")
_Q = r"Q\d+(?:-[A-Z])?"
_ROW_RE = re.compile(r"^\|\s*\**\s*(" + _Q + r")\s*\**\s*(?:—[^|]*)?\|")
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")
_DISCHARGE_STATES = ("carried", "closed", "by_design")


def plan_questions(text: str) -> List[str]:
    """Top-level question ids in the plan's "Questions" section, in order of first mention."""
    out: List[str] = []
    level: Optional[int] = None
    for line in text.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            lv = len(h.group(1))
            if level is not None and lv <= level:
                level = None                      # left the Questions section
            if level is None and re.search(r"\bQuestions\b", h.group(2)) and lv == 2:
                level = lv
                continue
            if level is not None:
                for q in re.findall(r"\b(" + _Q + r")\b", h.group(2).split("—")[0] + " " +
                                    " ".join(re.findall(r"and (" + _Q + r")\b", h.group(2)))):
                    if q not in out:
                        out.append(q)
            continue
        if level is None:
            continue
        m = _ROW_RE.match(line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _node_covers(node: Dict[str, Any], prog: str, q: str) -> bool:
    if str(node.get("question") or "") == q:
        return True
    nid = str(node.get("id") or "")
    stem = f"{prog}-{q}"
    return nid == stem or nid.startswith(stem + ".") or nid.startswith(stem + "-")


def _discharge_problem(entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return "not a mapping"
    if entry.get("state") not in _DISCHARGE_STATES:
        return f"state must be one of {_DISCHARGE_STATES}"
    for k in ("by", "why"):
        if not str(entry.get(k) or "").strip():
            return f"`{k}` is required"
    return None


def coverage(root: Path) -> Dict[str, Any]:
    """{programmes: [{programme, plan, tree, questions, covered, carried, uncovered, problems}]}."""
    import yaml
    trees: Dict[str, Dict[str, Any]] = {}
    for p in sorted((root / TREES).glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        num = p.name[:2]
        trees[num] = {"path": p.relative_to(root).as_posix(), "doc": doc}
    rows = []
    for p in sorted((root / PLANS).glob("*.md")):
        m = _PLAN_RE.match(p.name)
        if not m:
            continue                                   # RESEARCH-MAP.md and friends: not a programme plan
        num = m.group(1)
        qs = plan_questions(p.read_text(encoding="utf-8"))
        prog = f"P{int(num)}"
        tree = trees.get(num)
        row: Dict[str, Any] = {"programme": prog, "plan": p.relative_to(root).as_posix(),
                               "tree": tree["path"] if tree else None, "questions": qs,
                               "covered": {}, "carried": {}, "uncovered": [], "problems": []}
        if not qs:
            row["problems"].append("no questions found in the plan's '## ... Questions ...' section")
        nodes = (tree["doc"].get("nodes") or []) if tree else []
        disch = (tree["doc"].get("questions") or {}) if tree else {}
        if tree and str(tree["doc"].get("programme") or "") != prog:
            row["problems"].append(f"tree declares programme {tree['doc'].get('programme')!r}, expected {prog}")
        if tree and str(tree["doc"].get("plan") or "") != row["plan"]:
            row["problems"].append(f"tree `plan:` is {tree['doc'].get('plan')!r}, expected {row['plan']}")
        for q in qs:
            hit = [str(n.get("id")) for n in nodes if _node_covers(n, prog, q)]
            if hit:
                row["covered"][q] = hit
            elif q in disch and _discharge_problem(disch[q]) is None:
                row["carried"][q] = {"state": disch[q]["state"], "by": disch[q]["by"]}
            else:
                row["uncovered"].append(q)
                if q in disch:
                    row["problems"].append(f"questions.{q}: {_discharge_problem(disch[q])}")
        for q in sorted(set(disch) - set(qs)):
            row["problems"].append(f"questions.{q} discharges a question the plan does not ask")
        if not tree:
            row["problems"].append(f"no tree file research/programmes/{num}-*.yaml -- nothing in this plan "
                                   "can reach the authoring queue")
        rows.append(row)
    return {"programmes": rows}


def load_baseline(root: Path) -> Dict[str, int]:
    p = root / BASELINE
    if not p.is_file():
        return {}
    return {k: int(v) for k, v in (json.loads(p.read_text(encoding="utf-8")).get("max_uncovered") or {}).items()}


def check(cov: Dict[str, Any], baseline: Dict[str, int]) -> List[str]:
    """Ratchet failures (empty = pass)."""
    fails = []
    for r in cov["programmes"]:
        n = len(r["uncovered"])
        cap = baseline.get(r["programme"], 0)
        if n > cap:
            fails.append(f"{r['programme']} ({r['plan']}): {n} uncovered question(s) {r['uncovered']} > baseline {cap} "
                         "-- add a node (a `needs_authoring:` line is enough) or a reasoned `questions:` discharge")
        for prob in r["problems"]:
            # A malformed `questions:` discharge fails (it would read as covered). A tree whose
            # `programme:` / `plan:` header disagrees with its plan is WARNED, never failed: the
            # programme lanes write these trees, and a header typo must not block their PR (manager,
            # 2026-10-16) -- the questions still count as uncovered until a node names them.
            if prob.startswith("questions."):
                fails.append(f"{r['programme']}: {prob}")
    return fails


def summary_line(cov: Dict[str, Any]) -> str:
    parts = []
    for r in cov["programmes"]:
        q = len(r["questions"])
        parts.append(f"{r['programme']} {len(r['uncovered'])}/{q} uncovered" + ("" if r["tree"] else " (NO TREE)"))
    return "; ".join(parts)


def _self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / PLANS).mkdir(parents=True)
        (r / TREES).mkdir(parents=True)
        (r / PLANS / "01-ALPHA.md").write_text(
            "# P\n## 1. Goal\n| Q9 | not in section |\n## 2. Questions, in dependency order\n"
            "| Q | question |\n|---|---|\n| **Q1** | a |\n| **Q2** | b |\n| **Q2-C** | c |\n| Q3 | d |\n"
            "### Q4 / Q5 — two\n### Q6 — x and Q7 — y\n## 3. Ladders\n| **Q8** | outside |\n")
        (r / PLANS / "02-BETA.md").write_text("# B\n## 3. Questions\n### Q0 — m\n### Q1 — n\n")
        (r / PLANS / "RESEARCH-MAP.md").write_text("## Questions\n| **Q1** | ignored |\n")
        assert plan_questions((r / PLANS / "01-ALPHA.md").read_text()) == \
            ["Q1", "Q2", "Q2-C", "Q3", "Q4", "Q5", "Q6", "Q7"], plan_questions((r / PLANS / "01-ALPHA.md").read_text())
        (r / TREES / "01-alpha.yaml").write_text(
            "programme: P1\nplan: docs/research/programmes/01-ALPHA.md\n"
            "questions:\n  Q6: {state: carried, by: 'checklist:ROW', why: 'a build'}\n"
            "  Q7: {state: carried, by: ''}\n"
            "nodes:\n  - {id: P1-Q1-fail, needs_authoring: x}\n  - {id: P1-Q2.1, needs_authoring: y}\n"
            "  - {id: P1-Qx, question: Q3, needs_authoring: z}\n  - {id: P1-Q10, needs_authoring: not Q1}\n")
        cov = coverage(r)
        a, b = cov["programmes"]
        assert a["programme"] == "P1" and set(a["covered"]) == {"Q1", "Q2", "Q3"}, a
        assert "Q2-C" in a["uncovered"], "P1-Q2.1 must not cover Q2-C"
        assert set(a["carried"]) == {"Q6"} and "Q7" in a["uncovered"], a      # bare discharge refused
        assert any("questions.Q7" in p for p in a["problems"])
        assert b["tree"] is None and b["uncovered"] == ["Q0", "Q1"] and any("no tree" in p for p in b["problems"])
        # ratchet: at baseline passes (except the malformed discharge), above fails, unknown plan fails
        base = {"P1": len(a["uncovered"]), "P2": 2}
        f = check(cov, base)
        assert len(f) == 1 and "questions.Q7" in f[0], f
        assert any("P2" in x for x in check(cov, {"P1": 9}))
        assert any("P1" in x and "> baseline" in x for x in check(cov, {"P1": 0, "P2": 2}))
        assert "P2 2/2 uncovered (NO TREE)" in summary_line(cov)
        # a tree that LANDS later can only lower the count; a header mismatch warns, never fails
        (r / TREES / "02-beta.yaml").write_text("programme: P9\nplan: wrong.md\nnodes:\n  - {id: P2-Q0, needs_authoring: x}\n")
        cov2 = coverage(r)
        b2 = cov2["programmes"][1]
        assert b2["uncovered"] == ["Q1"] and any(p.startswith("tree ") for p in b2["problems"]), b2
        assert not [x for x in check(cov2, base) if x.startswith("P2")], check(cov2, base)
    print("programme-coverage self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check", action="store_true", help="ratchet against the baseline; exit 1 on a regression")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-baseline", action="store_true",
                    help="lower baseline entries to today's counts (never raises one)")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    cov = coverage(_REPO)
    if args.write_baseline:
        old = load_baseline(_REPO)
        new = {}
        for r in cov["programmes"]:
            n = len(r["uncovered"])
            new[r["programme"]] = min(n, old[r["programme"]]) if r["programme"] in old else n
        raised = [k for k in new if k in old and new[k] > old[k]]
        assert not raised, raised
        (_REPO / BASELINE).write_text(json.dumps({
            "_doc": "Ratchet for scripts/research/programme_coverage.py --check: a programme's uncovered "
                    "plan questions may never exceed this. Lower it with --write-baseline; never raise it by hand.",
            "max_uncovered": new}, indent=2) + "\n", encoding="utf-8")
        print(f"programme-coverage: baseline written {new}")
        return 0
    if args.json:
        print(json.dumps(cov, indent=2))
    else:
        print(f"programme-coverage: {summary_line(cov)}")
        for r in cov["programmes"]:
            if r["uncovered"]:
                print(f"  {r['programme']} uncovered: {', '.join(r['uncovered'])}")
    if args.check:
        fails = check(cov, load_baseline(_REPO))
        for r in cov["programmes"]:
            for prob in r["problems"]:
                if prob.startswith("tree ") or prob.startswith("no tree"):
                    print(f"::warning::programme-coverage: {r['programme']}: {prob}")
        for f in fails:
            print(f"::error::programme-coverage: {f}")
        print("programme-coverage --check: " + ("OK" if not fails else f"FAIL ({len(fails)})"))
        return 1 if fails else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
