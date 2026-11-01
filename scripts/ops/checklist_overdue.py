#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::checklist-store-guard (--self-test).
"""OVERDUE ROWS: non-terminal checklist rows whose due date is past, oldest first.

WHY (operator, 2026-11-01, lane CHECKLIST-OWNER-DUE): the manager owns every task and "it is just a
question of when we are getting to them". A date nobody sees is not a date, so overdue work renders at
the TOP of GET /api/bot/work/brief (`brief_lines`, wired in render_daily_brief.py) and is the first thing
the manager runs at start of session (`python3 scripts/ops/checklist_overdue.py`).

Due date = the row's `due_by`, else the legacy `observation.due_by` (rows filed before the contract).
A non-terminal row with NO date is reported separately as `undated` -- "we could not say when", never
"not overdue". Population is always printed.

Usage: checklist_overdue.py [--limit N] [--json] | --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.checklist_store import TERMINAL, effective_due, is_overdue, load  # noqa: E402


def view(rows: list[dict], today: date) -> dict:
    live = [r for r in rows if isinstance(r, dict) and r.get("state") not in TERMINAL]
    over = sorted((r for r in live if is_overdue(r, today)), key=lambda r: (effective_due(r), r["id"]))
    undated = [r for r in live if effective_due(r) is None]
    return {"today": today.isoformat(), "live": len(live), "overdue": over, "undated": len(undated),
            "undated_ids": [r["id"] for r in undated]}


def brief_lines(rows: list[dict], today: date, limit: int = 15) -> list[str]:
    v = view(rows, today)
    n = len(v["overdue"])
    L = [f"### OVERDUE -- {n} of {v['live']} non-terminal checklist rows are past their due date "
         f"({v['undated']} have no date at all: not counted overdue, not on time either)", ""]
    for r in v["overdue"][:limit]:
        days = (today - effective_due(r)).days
        L.append(f"- **{r['id']}** [{r.get('state')}] due {effective_due(r).isoformat()} ({days}d overdue) "
                 f"owner {r.get('owner') or 'UNOWNED'} -- {str(r.get('title') or '')[:110]}")
    if n > limit:
        L.append(f"- ... and {n - limit} more (python3 scripts/ops/checklist_overdue.py)")
    return L + [""]


def _self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    t = date(2026, 11, 1)
    rows = [{"id": "A", "state": "queued", "due_by": "2026-10-30", "owner": "manager", "title": "a"},
            {"id": "B", "state": "landed_unproven", "observation": {"due_by": "2026-10-23T00:00Z"}, "title": "b"},
            {"id": "C", "state": "queued", "due_by": "2026-11-01", "title": "due today is not overdue"},
            {"id": "D", "state": "done", "due_by": "2020-01-01", "title": "closed"},
            {"id": "E", "state": "queued", "title": "no date"}]
    v = view(rows, t)
    ck("overdue = past due and non-terminal, oldest first", [r["id"] for r in v["overdue"]] == ["B", "A"])
    ck("legacy observation.due_by counts", "B" in [r["id"] for r in v["overdue"]])
    ck("due today is not overdue; done is never overdue", "C" not in [r["id"] for r in v["overdue"]] and "D" not in [r["id"] for r in v["overdue"]])
    ck("undated rows are counted apart, not as on time", v["undated"] == 1 and v["undated_ids"] == ["E"])
    ck("brief lines name the population", "of 4 non-terminal" in brief_lines(rows, t)[0])
    print("checklist-overdue self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    today = datetime.now(timezone.utc).date()
    rows = load()["items"]
    if a.json:
        v = view(rows, today)
        v["overdue"] = [{"id": r["id"], "state": r.get("state"), "due": effective_due(r).isoformat(),
                         "owner": r.get("owner"), "title": r.get("title")} for r in v["overdue"]]
        print(json.dumps(v, indent=2))
    else:
        print("\n".join(brief_lines(rows, today, a.limit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
