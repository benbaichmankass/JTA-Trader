#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::checklist-store-guard (--self-test).
"""WHAT THE DAILY REVIEW'S STEP 4b MEASURES (operator, 2026-11-01): the due set and the flow, in one print.

The manager owns every row and the backlog; once a day (05:52Z review) it runs this, ranks what is due, and
dispatches ONE BACKLOG-DRAIN-<date> lane. This script only MEASURES -- it schedules nothing, refuses nothing,
writes nothing. Every number names its population; a number it could not compute prints COULD NOT LOOK,
never 0.

  rows by state            all rows in docs/claude/work/checklist/ (population stated)
  overdue / due today      non-terminal rows by date: `due_by`, else legacy `observation.due_by`; oldest first
  no date                  non-terminal rows with no date at all (counted apart: not overdue, not on time)
  landed_unproven due      landed_unproven rows whose observation date is today or earlier
  pipeline due             pipeline.py stats().due and .unrouted over the PIPELINE store
  research not_run         research/queue/RQ-*.yaml units with status `queued` (queued, never run)
  opened vs closed 24h/7d  opened = row files ADDED in git history in the window; closed = rows now done/dropped
                           whose `updated_at` is in the window. Needs history: a shallow clone that does not reach
                           the window start prints COULD NOT LOOK for `opened`.

Usage: checklist_daily_measure.py [--top N] [--json] | --self-test
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.checklist_store import STORE, TERMINAL, effective_due, load  # noqa: E402


def _git(*a: str) -> str | None:
    r = subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def flow(rows: list[dict], now: datetime) -> dict:
    out: dict = {}
    shallow = (_git("rev-parse", "--is-shallow-repository") or "").strip() == "true"
    oldest = (_git("log", "--reverse", "--format=%cI", "-1") or "").strip()  # newest-first default; refined below
    first = (_git("log", "--format=%cI") or "").strip().splitlines()
    oldest = first[-1] if first else None
    for label, days in (("24h", 1), ("7d", 7)):
        since = now - timedelta(days=days)
        closed = sum(1 for r in rows if r.get("state") in TERMINAL and str(r.get("updated_at") or "") >= since.strftime("%Y-%m-%dT%H:%M:%SZ"))
        opened = None
        if not (shallow and (oldest is None or datetime.fromisoformat(oldest) > since)):
            names = _git("log", f"--since={since.isoformat()}", "--diff-filter=A", "--name-only", "--format=", "--", str(STORE))
            if names is not None:
                opened = len({n for n in names.splitlines() if n.endswith(".json") and not Path(n).name.startswith("_")})
        out[label] = {"opened": opened, "closed": closed}
    out["history_note"] = f"shallow clone, oldest commit {oldest}" if shallow else "full history"
    return out


def measure(rows: list[dict], today: date, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    live = [r for r in rows if r.get("state") not in TERMINAL]
    dated = [(effective_due(r), r) for r in live]
    over = sorted(((d, r) for d, r in dated if d and d < today), key=lambda x: (x[0], x[1]["id"]))
    m = {"today": today.isoformat(), "rows_total": len(rows), "by_state": dict(collections.Counter(r.get("state") for r in rows)),
         "live": len(live), "overdue": [(d.isoformat(), r["id"], r.get("state")) for d, r in over],
         "due_today": sum(1 for d, _ in dated if d == today), "no_date": sum(1 for d, _ in dated if d is None),
         "lu_observation_due": sum(1 for d, r in dated if r.get("state") == "landed_unproven" and d and d <= today),
         "flow": flow(rows, now)}
    try:
        from scripts.ops import pipeline  # noqa: PLC0415
        st = pipeline.stats(pipeline.read_log(REPO / pipeline.STORE), today)
        m["pipeline"] = {"due": st["due"], "unrouted": st["unrouted"], "open": st["open"], "readable": st["readable"]}
    except Exception as exc:  # noqa: BLE001
        m["pipeline"] = None
        m["pipeline_error"] = type(exc).__name__
    try:
        import yaml  # noqa: PLC0415
        c = collections.Counter()
        for f in (REPO / "research/queue").glob("RQ-*.yaml"):
            u = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            c[u.get("status")] += 1
        m["research"] = {"not_run_queued": c.get("queued", 0), "units_total": sum(c.values())}
    except Exception as exc:  # noqa: BLE001
        m["research"] = None
    return m


def render(m: dict, top: int) -> str:
    f = m["flow"]
    def fl(k):
        o = f[k]["opened"]
        return f"{k}: opened {'COULD NOT LOOK' if o is None else o} / closed {f[k]['closed']}"
    L = [f"## Daily measure {m['today']} (population: {m['rows_total']} checklist rows; {m['live']} non-terminal)",
         "- by state: " + ", ".join(f"{k}={v}" for k, v in sorted(m["by_state"].items(), key=lambda x: str(x[0]))),
         f"- OVERDUE: {len(m['overdue'])} | due today: {m['due_today']} | no date at all: {m['no_date']} | landed_unproven with observation due: {m['lu_observation_due']}",
         "- flow (" + f["history_note"] + "): " + "; ".join(fl(k) for k in ("24h", "7d")),
         "- pipeline: " + ("COULD NOT LOOK" if m["pipeline"] is None else f"due {m['pipeline']['due']}, unrouted {m['pipeline']['unrouted']}, open {m['pipeline']['open']}"),
         "- research units queued (not run): " + ("COULD NOT LOOK" if m["research"] is None else f"{m['research']['not_run_queued']} of {m['research']['units_total']}"),
         "", f"Oldest {min(top, len(m['overdue']))} overdue:"]
    L += [f"  {d}  {i}  [{s}]" for d, i, s in m["overdue"][:top]]
    return "\n".join(L) + "\n"


def _self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    t, now = date(2026, 11, 1), datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
    rows = [{"id": "A", "state": "queued", "due_by": "2026-10-30"},
            {"id": "B", "state": "landed_unproven", "observation": {"due_by": "2026-11-01T00:00Z"}},
            {"id": "C", "state": "queued"},
            {"id": "D", "state": "done", "updated_at": "2026-11-01T01:00:00Z"},
            {"id": "E", "state": "dropped", "updated_at": "2026-10-20T01:00:00Z"}]
    m = measure(rows, t, now)
    ck("overdue = past date, non-terminal", [x[1] for x in m["overdue"]] == ["A"])
    ck("due today counted apart; observation due includes today", m["due_today"] == 1 and m["lu_observation_due"] == 1)
    ck("undated counted apart, not as overdue", m["no_date"] == 1)
    ck("closed in 24h counts only the recent close; 7d excludes the 12d-old one", m["flow"]["24h"]["closed"] == 1 and m["flow"]["7d"]["closed"] == 1)
    ck("rendering names the population and never prints a bare 0 for unknown", "population: 5 checklist rows" in render(m, 5))
    print("checklist-daily-measure self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    m = measure(load()["items"], datetime.now(timezone.utc).date())
    print(json.dumps(m, indent=2, default=str) if a.json else render(m, a.top), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
