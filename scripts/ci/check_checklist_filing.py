#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::checklist-filing-guard (--self-test, --check --base origin/main).
"""THE FILING CONTRACT GUARD: every changed, non-terminal checklist row has an owner, a due_by and a roadmap ref.

WHY (operator, 2026-11-01, lane CHECKLIST-OWNER-DUE): "I don't understand how items are still being
filed without an owner or a date ... the manager is the owner of all the tasks. It's just a question of
when we're getting to them, or they need to be related to a roadmap item ... this is exactly how we
end up with situations where we find things that need to get done, and then they never actually get
done." MEASURED 2026-11-01 over docs/claude/work/checklist/*.json: of 601 non-terminal rows, 2 carried
a top-level `due_by`, 102 had no owner, 105 no `roadmap`.

WHAT IT CHECKS (diff-scoped, like roadmap-map-guard, so an old row never reddens an unrelated PR):
a row that this diff adds or SUBSTANTIVELY changes (anything beyond updated_at / updated_by / _seq) and
whose state is not done/dropped must satisfy `checklist_store.filing_problems`:
  owner   non-empty (the CLI default is `manager`)
  due_by  an ISO date (YYYY-MM-DD)
  roadmap a milestone list, or ["unmapped"] with a `roadmap_unmapped_reason` (>= 10 chars)
Terminal rows are exempt. Whether a `roadmap` id names a real milestone is roadmap-map-guard's job.

Gates this adds or changes: ONE gate -- a PR (or push) that adds/changes a non-terminal checklist row
without those three fields is refused. Operator permission: the 2026-11-01 dispatch ("I also don't
understand how items are still being filed without an owner or a date ... we need to make sure that
this cannot keep happening"). Until the backfill lands, a PR that touches a legacy open row must date it.

Usage: check_checklist_filing.py --self-test | --check [--base REF]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.runtime.checklist_store import STORE, filing_problems  # noqa: E402

BOOKKEEPING = {"updated_at", "updated_by", "_seq"}


def grade(head_rows: dict, base_rows: dict) -> list[str]:
    bad: list[str] = []
    for rid, row in sorted(head_rows.items()):
        old = base_rows.get(rid)
        if old is not None and {k: v for k, v in old.items() if k not in BOOKKEEPING} == \
                {k: v for k, v in row.items() if k not in BOOKKEEPING}:
            continue
        for why in filing_problems(row):
            bad.append(f"row {rid}: {why}")
    return bad


def _git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, check=False).stdout


def diff_inputs(base: str) -> tuple[dict, dict]:
    head, old = {}, {}
    for p in [x for x in _git("diff", "--name-only", base, "--", str(STORE)).split("\n") if x]:
        if not p.endswith(".json") or Path(p).name.startswith("_"):
            continue
        f = REPO / p
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            head[d["id"]] = d
        prev = _git("show", f"{base}:{p}")
        if prev.strip():
            od = json.loads(prev)
            old[od["id"]] = od
    return head, old


def self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    good = {"id": "G", "state": "queued", "owner": "manager", "due_by": "2026-11-03", "roadmap": ["L-OPS"]}
    ck("a compliant new row is clean", grade({"G": good}, {}) == [])
    for k in ("owner", "due_by", "roadmap"):
        r = {x: v for x, v in good.items() if x != k}
        ck(f"a new row missing {k} FAILS", len(grade({"G": r}, {})) == 1)
    ck("unmapped without a reason FAILS", len(grade({"G": dict(good, roadmap=["unmapped"])}, {})) == 1)
    ck("unmapped with a reason is clean",
       grade({"G": dict(good, roadmap=["unmapped"], roadmap_unmapped_reason="one-off, no milestone")}, {}) == [])
    legacy = {"id": "L", "state": "queued", "owner": None, "note": "a"}
    ck("a substantively changed legacy row FAILS", len(grade({"L": dict(legacy, note="b")}, {"L": legacy})) == 3)
    ck("a bookkeeping-only change is not graded", grade({"L": dict(legacy, updated_at="t")}, {"L": legacy}) == [])
    ck("closing a legacy row is exempt", grade({"L": dict(legacy, state="done")}, {"L": legacy}) == [])
    ck("an untouched legacy row is never in the diff", grade({}, {"L": legacy}) == [])
    print("checklist-filing-guard self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--base", default="origin/main")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.check:
        bad = grade(*diff_inputs(a.base))
        for b in bad:
            print("FAIL:", b)
        print(f"checklist-filing: {'FAIL' if bad else 'ok'} ({len(bad)} problem(s) on rows this diff changes vs {a.base})")
        return 1 if bad else 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
