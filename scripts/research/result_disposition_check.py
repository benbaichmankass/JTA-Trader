#!/usr/bin/env python3
# wiring: scripts/ci/check_research_queue_health.py (health line); scripts/ci/run_guards.py
#   (research-queue-autonomy-selftests: --self-test only)
"""Result disposition: does every unit with a LANDED result have a disposition?

WHY THIS EXISTS (lane RESEARCH-ENGINE-1016, manager input 2026-10-16 07:19Z, from the
programme audits of PR #18532): results landed in every programme with no rule applied --
`4a4c-03/05/06/07/08`, `77dc-02`, `ca42-01` among them -- while the research-ops record
counted them as "read". Read is not "rule applied and follow-up filed". A result that
nobody graded is a finding nobody acts on, so this check makes the population a number.

POPULATION: every unit under research/queue/**/*.yaml whose research/results/<id>/ holds at
least one readable row (`dispatch_queue.latest_result_at`). Each lands in exactly one state:

  graded            grading.verdict is set (the grader's or a session's grading: block)
  needs_review      grading.needs_review is true AND grading.owner names who triages it
  needs_review_unowned   needs_review true, no owner -- a FINDING (who reads it?)
  legacy_prose      status done with a prose `result:` and no grading block: closed by hand
                    before grading blocks existed. Counted, never a finding (grandfathered).
  retired           status retired
  in_grace          newest row younger than GRACE_HOURS: the 6-hourly grader has not had
                    its turn yet. Counted, never a finding.
  non_verdict_only  every row is producer_failed / no_data: a ROUTE problem the dispatcher
                    re-arms (dispatch_queue.MAX_NONVERDICT_RETRIES), not an unread result.
  ungraded          everything else -- a FINDING: a measured result with no verdict, no owner.

Output is a WARNING surface (check_research_queue_health.py prints it every dispatch
cycle; research-ops step C/D works it), never a CI gate: results land through automation
PRs, and a grader that is a day late must not turn unrelated PRs red.

Not covered (said aloud): a result written somewhere OTHER than research/results/<id>/ (the
audit's `RQ-20261007-080`, whose rows landed under comms/) is invisible to this population
by construction -- that is a collector/lands.store finding, not a grading one.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

GRACE_HOURS = 24.0
FINDING_STATES = ("ungraded", "needs_review_unowned")


def _rows(rdir: Path) -> List[Dict[str, Any]]:
    out = []
    for f in sorted(rdir.glob("*.jsonl")) if rdir.is_dir() else []:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                r = json.loads(ln) if ln.strip() else None
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
    return out


def classify(u: Dict[str, Any], rows: List[Dict[str, Any]], latest: Optional[datetime],
             now: datetime) -> str:
    from scripts.research.dispatch_queue import NON_VERDICT_READ_STATES
    g = u.get("grading") if isinstance(u.get("grading"), dict) else {}
    if g.get("verdict"):
        return "graded"
    if g.get("needs_review"):
        return "needs_review" if str(g.get("owner") or "").strip() else "needs_review_unowned"
    if u.get("status") == "retired":
        return "retired"
    if u.get("status") == "done" and str(u.get("result") or "").strip():
        return "legacy_prose"
    if rows and all(str(r.get("read_state") or "") in NON_VERDICT_READ_STATES for r in rows):
        return "non_verdict_only"
    if latest is not None and now - latest < timedelta(hours=GRACE_HOURS):
        return "in_grace"
    return "ungraded"


def census(root: Path, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    from scripts.research.dispatch_queue import latest_result_at
    from scripts.research.queue_replenish import existing_units
    now = now or datetime.now(timezone.utc)
    units, bad = existing_units(root)
    states: Dict[str, List[str]] = {}
    for uid, u in sorted(units.items()):
        rdir = root / "research" / "results" / uid
        latest, n = latest_result_at(uid, root / "research" / "results")
        if n == 0:
            continue
        states.setdefault(classify(u, _rows(rdir), latest, now), []).append(uid)
    with_results = sum(len(v) for v in states.values())
    return {"as_of": now.isoformat(), "units": len(units), "unreadable": bad, "with_results": with_results,
            "counts": {k: len(v) for k, v in sorted(states.items())}, "states": states,
            "findings": sum(len(states.get(k, [])) for k in FINDING_STATES)}


def summary_line(c: Dict[str, Any]) -> str:
    cnt = c["counts"]
    return (f"result disposition: {c['with_results']} unit(s) with landed results -- graded {cnt.get('graded', 0)}, "
            f"needs_review owned {cnt.get('needs_review', 0)} / UNOWNED {cnt.get('needs_review_unowned', 0)}, "
            f"UNGRADED {cnt.get('ungraded', 0)}, in grace {cnt.get('in_grace', 0)}, non-verdict only "
            f"{cnt.get('non_verdict_only', 0)}, legacy prose {cnt.get('legacy_prose', 0)}, retired {cnt.get('retired', 0)}")


def _self_test() -> int:
    import tempfile
    now = datetime(2030, 1, 10, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        q, res = r / "research" / "queue", r / "research" / "results"
        q.mkdir(parents=True)
        old = (now - timedelta(days=3)).isoformat()
        fresh = (now - timedelta(hours=2)).isoformat()
        cases = {
            "RQ-20300101-001": ("status: done\ngrading: {verdict: pass}\n", [("pass", "measured", old)], "graded"),
            "RQ-20300101-002": ("status: queued\ngrading: {needs_review: true, owner: RESEARCH-OPS}\n",
                                [("pass", "measured", old)], "needs_review"),
            "RQ-20300101-003": ("status: queued\ngrading: {needs_review: true}\n", [("pass", "measured", old)],
                                "needs_review_unowned"),
            "RQ-20300101-004": ("status: done\nresult: 'DONE by hand, no_action_warranted'\n",
                                [("fail", "measured", old)], "legacy_prose"),
            "RQ-20300101-005": ("status: queued\n", [("pass", "measured", fresh)], "in_grace"),
            "RQ-20300101-006": ("status: queued\n", [("not_applicable", "producer_failed", old)], "non_verdict_only"),
            "RQ-20300101-007": ("status: queued\n", [("pass", "measured", old)], "ungraded"),
            "RQ-20300101-008": ("status: done\n", [("fail", "measured", old)], "ungraded"),   # done, no rule applied
            "RQ-20300101-009": ("status: retired\n", [("pass", "measured", old)], "retired"),
            "RQ-20300101-010": ("status: queued\n", [], None),                                 # no result: not in population
        }
        for uid, (body, rows, _want) in cases.items():
            (q / f"{uid}.yaml").write_text(f"id: {uid}\n{body}")
            if rows:
                (res / uid).mkdir(parents=True)
                (res / uid / "1.jsonl").write_text("".join(
                    json.dumps({"verdict": v, "read_state": rs, "generated_at": ts}) + "\n" for v, rs, ts in rows))
        c = census(r, now=now)
        for uid, (_b, _rows_, want) in cases.items():
            got = next((k for k, v in c["states"].items() if uid in v), None)
            assert got == want, (uid, got, want)
        assert c["with_results"] == 9 and c["findings"] == 3, c
        assert "UNGRADED 2" in summary_line(c) and "UNOWNED 1" in summary_line(c)
    print("result-disposition self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="also list every unit in a finding state")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    c = census(_REPO)
    if args.json:
        print(json.dumps(c, indent=2))
        return 0
    print(summary_line(c))
    if args.list:
        for k in FINDING_STATES:
            for uid in c["states"].get(k, []):
                print(f"  {k:<22} {uid}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
