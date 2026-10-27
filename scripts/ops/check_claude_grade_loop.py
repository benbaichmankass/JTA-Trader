#!/usr/bin/env python3
# wiring: manual-only — weekly-audit CORE C13 (CLAUDE-GRADE-LOOP) runs it every Monday; no timer.
"""Did the Claude grading loop run? weekly-audit C13 (CLAUDE-GRADE-LOOP).

    python3 scripts/ops/check_claude_grade_loop.py --live      # all three checks (LTR needs the journal)
    python3 scripts/ops/check_claude_grade_loop.py             # desk + briefs only; LTR reads could_not_look
    python3 scripts/ops/check_claude_grade_loop.py --self-test

Three checks, each printing its population:

1. LTR GRADED. Every live-review row whose trade CLOSED more than ``GRACE_DAYS`` ago has a row in
   ``comms/live_review/outcomes.jsonl`` (``live_review_grade.py --live --write-outcomes`` ran). Needs the
   journal (``--live``); without it the check reads ``could_not_look``, never pass.
2. DESK GRADED. Every desk decision whose grading window (``desk_grade.grading_window``) ended more than
   ``GRACE_DAYS`` ago has a row in ``comms/desk/outcomes.jsonl`` (``desk_outcomes.py`` ran) -- a
   ``not_computable`` row with its reason counts, a missing row does not.
3. BRIEF AMENDMENTS HAVE A GRADED BASIS. Every version of live-trade-review ``SKILL.md`` /
   ``REVIEWER-BRIEF.md`` and trading-desk ``DESK-BRIEF.md``
   committed after ``LOOP_START`` (each distinct blob sha in ``git log``) has an entry in the brief's
   sibling ``AMENDMENTS.md`` naming that ``new_skill_sha`` with a ``basis:`` that states ``n=``. A shallow
   clone whose oldest commit is not older than ``LOOP_START`` cannot see the whole window, so it reads
   ``could_not_look`` (exit 2), never pass.

4. ROLE GRADE RAN ON ITS SCHEDULE. ``comms/desk/role_grade.json`` (``claude_role_grade.py``, written by the hourly
   ``desk-decisions-mirror`` workflow, DESK-9-GRADING) exists and its ``generated_at`` is no older than
   ``ROLE_GRADE_MAX_AGE_DAYS``. A missing or stale snapshot is a FINDING: the grading is wired to a schedule, so a
   silent schedule is the failure this check exists to catch.

Exit 0 all pass · 1 a finding · 2 could not look (a check could not read its input; findings still print).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_grade as dg  # noqa: E402

GRACE_DAYS = 1
ROLE_GRADE = REPO / "comms" / "desk" / "role_grade.json"
ROLE_GRADE_MAX_AGE_DAYS = 2
LOOP_START = "2026-10-27T00:00:00Z"
BRIEFS = {                      # every contract a judging session follows (its blob sha is the row's skill_sha)
    ".claude/skills/live-trade-review/SKILL.md": ".claude/skills/live-trade-review/AMENDMENTS.md",
    ".claude/skills/live-trade-review/REVIEWER-BRIEF.md": ".claude/skills/live-trade-review/AMENDMENTS.md",
    ".claude/skills/trading-desk/DESK-BRIEF.md": ".claude/skills/trading-desk/AMENDMENTS.md",
}
_ENTRY = re.compile(r"new_skill_sha:\s*`?([0-9a-f]{7,40})`?.*?basis:\s*(.+)$", re.I)


def ltr_check(reviews: List[dict], outcomes: List[dict], trades: Optional[Dict[int, dict]], now: datetime) -> Dict[str, Any]:
    if trades is None:
        return {"state": "could_not_look", "reason": "journal not read (run with --live)"}
    have = {o["review_id"] for o in outcomes}
    due, missing = 0, []
    for r in reviews:
        t = trades.get(int(r["trade_id"])) if r.get("trade_id") is not None else None
        closed = dg._ts((t or {}).get("closed_at")) if t and str(t.get("status") or "").lower() == "closed" else None
        if closed and closed < now - timedelta(days=GRACE_DAYS):
            due += 1
            if r["review_id"] not in have:
                missing.append(r["review_id"])
    return {"state": "fail" if missing else "pass", "population": f"{len(reviews)} reviews; {due} on trades closed > {GRACE_DAYS}d ago",
            "missing_outcome": missing}


def desk_check(decisions: List[dict], outcomes: List[dict], now: datetime) -> Dict[str, Any]:
    have = {o["decision_id"] for o in outcomes}
    due, missing = 0, []
    for d in decisions:
        w = dg.grading_window(d)
        if w and w[1] < now - timedelta(days=GRACE_DAYS):
            due += 1
            if d["decision_id"] not in have:
                missing.append(d["decision_id"])
    return {"state": "fail" if missing else "pass", "population": f"{len(decisions)} decisions; {due} past their window + {GRACE_DAYS}d",
            "missing_outcome": missing}


def role_grade_check(snapshot: Optional[dict], now: datetime) -> Dict[str, Any]:
    if snapshot is None:
        return {"state": "fail", "population": "comms/desk/role_grade.json", "findings": ["snapshot missing: the desk-decisions-mirror grade step has not landed one"]}
    t = dg._ts(snapshot.get("generated_at"))
    if t is None:
        return {"state": "fail", "population": "comms/desk/role_grade.json", "findings": ["generated_at unreadable"]}
    age = (now - t).total_seconds() / 86400
    stale = age > ROLE_GRADE_MAX_AGE_DAYS
    return {"state": "fail" if stale else "pass", "population": f"{len(snapshot.get('rows') or [])} role/class rows, generated {snapshot['generated_at']}",
            "findings": [f"snapshot is {age:.1f}d old (> {ROLE_GRADE_MAX_AGE_DAYS}d): the scheduled grade step is not landing"] if stale else []}


def amendment_entries(text: str) -> Dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = _ENTRY.search(line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def _git(*args: str) -> Optional[str]:
    p = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def brief_versions(brief: str) -> Optional[List[str]]:
    """Blob shas of ``brief`` at each commit after LOOP_START, or None when history cannot be trusted."""
    shallow = (_git("rev-parse", "--is-shallow-repository") or "").strip()
    if shallow != "false":
        # a shallow clone is complete for our window only when its oldest commit predates LOOP_START
        oldest = (_git("log", "--reverse", "--format=%cI") or "").split("\n", 1)[0].strip()
        if shallow != "true" or not oldest or dg._ts(oldest) is None or dg._ts(oldest) >= dg._ts(LOOP_START):
            return None
    log = _git("log", f"--since={LOOP_START}", "--format=%H", "--", brief)
    if log is None:
        return None
    shas = []
    for c in log.split():
        b = _git("rev-parse", f"{c}:{brief}")
        if b:
            shas.append(b.strip())
    return sorted(set(shas))


def brief_check(versions: Optional[List[str]], entries: Dict[str, str]) -> Dict[str, Any]:
    if versions is None:
        return {"state": "could_not_look", "reason": "shallow clone or git unreadable: run `git fetch --unshallow` first"}
    bad = []
    for v in versions:
        basis = next((b for k, b in entries.items() if v.startswith(k) or k.startswith(v)), None)
        if basis is None:
            bad.append(f"{v[:8]}: no AMENDMENTS.md entry")
        elif not re.search(r"\bn\s*=\s*\d+", basis):
            bad.append(f"{v[:8]}: basis states no n= ({basis[:60]})")
    return {"state": "fail" if bad else "pass", "population": f"{len(versions)} version(s) since {LOOP_START}", "findings": bad}


def run(live: bool, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    res: Dict[str, Any] = {}
    reviews = dg.read_jsonl(REPO / "comms/live_review/reviews.jsonl")
    trades = None
    if live:
        import live_review_counterfactual as cf
        try:
            trades = cf.load_live_sources(reviews)[1]
        except (RuntimeError, ValueError) as exc:
            print(f"check_claude_grade_loop: journal unreadable: {exc}", file=sys.stderr)
    res["ltr_graded"] = ltr_check(reviews, dg.read_jsonl(REPO / "comms/live_review/outcomes.jsonl"), trades, now)
    res["desk_graded"] = desk_check(dg.read_jsonl(dg.DECISIONS), dg.read_jsonl(dg.OUTCOMES), now)
    try:
        snap = json.loads(ROLE_GRADE.read_text(encoding="utf-8")) if ROLE_GRADE.exists() else None
    except ValueError:
        snap = {}
    res["role_grade_fresh"] = role_grade_check(snap, now)
    for brief, log in BRIEFS.items():
        lp = REPO / log
        res[f"amendments:{brief.split('/')[2]}/{brief.rsplit('/', 1)[1]}"] = brief_check(brief_versions(brief),
                                                               amendment_entries(lp.read_text(encoding="utf-8")) if lp.exists() else {})
    return res


def _self_test() -> int:
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    rv = [{"review_id": "LR-1", "trade_id": 1}, {"review_id": "LR-2", "trade_id": 2}]
    tr = {1: {"status": "closed", "closed_at": "2026-10-28T00:00:00Z"}, 2: {"status": "open"}}
    cases = [
        ("ltr: closed trade with no outcome row fails", ltr_check(rv, [], tr, now)["state"] == "fail"),
        ("ltr: graded passes", ltr_check(rv, [{"review_id": "LR-1"}], tr, now)["state"] == "pass"),
        ("ltr: no journal is could_not_look, not pass", ltr_check(rv, [], None, now)["state"] == "could_not_look"),
        ("desk: past-window decision without a row fails",
         desk_check([{"decision_id": "D1", "info_cutoff_at": "2026-10-26T13:39:00Z", "packet_id": "DP-x-scan-1h"}], [], now)["state"] == "fail"),
        ("desk: not_computable row counts as graded",
         desk_check([{"decision_id": "D1", "info_cutoff_at": "2026-10-26T13:39:00Z", "packet_id": "DP-x-scan-1h"}],
                    [{"decision_id": "D1", "kind": "not_computable"}], now)["state"] == "pass"),
        ("brief: version without entry fails", brief_check(["abcdef1234"], {})["state"] == "fail"),
        ("brief: entry without n fails", brief_check(["abcdef1234"], {"abcdef12": "vibes"})["state"] == "fail"),
        ("brief: entry with n passes", brief_check(["abcdef1234"], amendment_entries(
            "- 2026-11-01 · new_skill_sha: `abcdef12` · prior: `1111111` · basis: live_review_grade --json since 10-26, n=24 hold graded"))["state"] == "pass"),
        ("role grade: missing snapshot fails", role_grade_check(None, now)["state"] == "fail"),
        ("role grade: fresh passes", role_grade_check({"generated_at": "2026-11-01T00:00:00Z", "rows": []}, now)["state"] == "pass"),
        ("role grade: stale fails", role_grade_check({"generated_at": "2026-10-28T00:00:00Z", "rows": []}, now)["state"] == "fail"),
        ("brief: shallow is could_not_look", brief_check(None, {})["state"] == "could_not_look"),
    ]
    bad = [n for n, ok in cases if not ok]
    for n in bad:
        print(f"SELF-TEST FAIL: {n}")
    print(f"check_claude_grade_loop self-test: {len(cases) - len(bad)}/{len(cases)} passed")
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    res = run(a.live)
    print(json.dumps(res, indent=1))
    states = {v["state"] for v in res.values()}
    return 1 if "fail" in states else 2 if "could_not_look" in states else 0


if __name__ == "__main__":
    sys.exit(main())
