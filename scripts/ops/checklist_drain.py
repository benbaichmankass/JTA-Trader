#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::checklist-store-guard (--self-test).
"""THE DUE-DRAIN: nothing that is due can sit unseen. A PROCESS, not a gate.

WHY (operator, 2026-11-01): "we don't need gates, we need processes ... structurally making sure that work
items don't get dropped and anything that needs to wait and be observed later actually gets observed later."
Every earlier fix was a rule that depended on a session remembering; nothing ACTED on the date. This does.

WHAT IT DOES, for every non-terminal checklist row whose date (`due_by`, else `observe.when`, else the legacy
`observation.due_by`) is today or earlier:
  (a) the row names a RUNNABLE check -- `observe: {when, how}` where `how` is one allowlisted command -- and
      `--run` executes it (no shell, 60 s timeout) and writes the result to the row (`observe.last_result`,
      `observe.last_run_at`, exit code, last 600 chars of output). It does NOT close or re-date the row: a
      result is evidence, and reading it is the manager's call -- but it is now on the row, not in a head.
  (b) otherwise (or after (a)) the row is listed as DUE NOW with how many times it has slipped (`slips`,
      +1 per `--run` that finds it still due), top of the manager's wake and of the brief.
Plus any pipeline id collision (`pipeline.py --check` DISPLACED/SHADOWED warning) is surfaced as a due item.

ALLOWLIST for `how` (a row is data; it must not become a shell): `python3 scripts/<...>.py [args]` or
`curl -sS https://ict-bot.duckdns.org/api/<...>`; no shell metacharacters (; & | ` $ > < newline).

SCHEDULE (Tier-2, a routine, NOT created by this PR): hourly, `python3 scripts/ops/checklist_drain.py --run
--write-report comms/` on the VM or an Actions cron, plus a wake of the manager session with `--report`'s output.
Gates this adds or changes: none -- defaults plus a scheduled drain.

Usage: checklist_drain.py [--report] [--run] [--limit N] [--json] | --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.checklist_store import TERMINAL, _as_date, effective_due, load  # noqa: E402

_META = re.compile(r"[;&|`$><\n\\]")
_OK = (re.compile(r"^python3 scripts/[A-Za-z0-9_./-]+\.py(?: [A-Za-z0-9_./:=,@%+ -]*)?$"),
       re.compile(r"^curl -sS https://ict-bot\.duckdns\.org/api/[A-Za-z0-9_./?=&%-]*$"))


def runnable(how) -> bool:
    return isinstance(how, str) and not _META.search(how) and any(p.match(how.strip()) for p in _OK)


def due_date(row: dict) -> date | None:
    obs = row.get("observe") if isinstance(row.get("observe"), dict) else {}
    return _as_date(row.get("due_by")) or _as_date(obs.get("when")) or effective_due(row)


def due_now(rows: list[dict], today: date) -> list[dict]:
    out = [r for r in rows if isinstance(r, dict) and r.get("state") not in TERMINAL
           and (d := due_date(r)) is not None and d <= today]
    return sorted(out, key=lambda r: (due_date(r), r["id"]))


def run_one(row: dict) -> dict:
    how = (row.get("observe") or {}).get("how")
    res = subprocess.run(shlex.split(how), cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    return {"last_run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "exit": res.returncode,
            "last_result": ((res.stdout or "") + (res.stderr or ""))[-600:]}


def pipeline_collisions() -> int | None:
    try:
        out = subprocess.run([sys.executable, "scripts/ops/pipeline.py", "--check"], cwd=REPO, capture_output=True,
                             text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"pipeline: (\d+) id\(s\) with a DISPLACED/SHADOWED", out.stdout + out.stderr)
    return int(m.group(1)) if m else 0


def lines(rows: list[dict], today: date, limit: int = 25) -> list[str]:
    d = due_now(rows, today)
    L = [f"### DUE NOW -- {len(d)} checklist row(s) due today or earlier (population: non-terminal rows with a date)", ""]
    for r in d[:limit]:
        runs = "runnable" if runnable((r.get("observe") or {}).get("how")) else "manual"
        L.append(f"- **{r['id']}** [{r.get('state')}] due {due_date(r)} slips={r.get('slips', 0)} {runs} "
                 f"owner {r.get('owner') or 'UNOWNED'} -- {str(r.get('title') or '')[:100]}")
    if len(d) > limit:
        L.append(f"- ... and {len(d) - limit} more")
    return L + [""]


def _self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    t = date(2026, 11, 1)
    ck("allowlist: a scripts/ python command runs", runnable("python3 scripts/ops/checklist_overdue.py --json"))
    ck("allowlist: the live API GET runs", runnable("curl -sS https://ict-bot.duckdns.org/api/bot/work/brief"))
    ck("allowlist: a shell chain is refused", not runnable("python3 scripts/ops/x.py; rm -rf /"))
    ck("allowlist: other hosts / commands are refused", not runnable("curl -sS https://evil.example/x") and not runnable("rm -rf /"))
    ck("allowlist: command substitution / redirect refused", not runnable("python3 scripts/a.py $(id)") and not runnable("python3 scripts/a.py > /etc/x"))
    rows = [{"id": "A", "state": "queued", "due_by": "2026-10-30"},
            {"id": "B", "state": "landed_unproven", "observe": {"when": "2026-11-01", "how": "python3 scripts/ops/checklist_overdue.py --self-test"}},
            {"id": "C", "state": "queued", "due_by": "2026-11-02"},
            {"id": "D", "state": "done", "due_by": "2020-01-01"}]
    ck("due now = date <= today, non-terminal, oldest first", [r["id"] for r in due_now(rows, t)] == ["A", "B"])
    res = run_one(rows[1])
    ck("a runnable observation executes and records exit + output", res["exit"] == 0 and "PASS" in res["last_result"])
    ck("lines name the population and slips", "slips=0" in "\\n".join(lines(rows, t)) and "non-terminal rows with a date" in lines(rows, t)[0])
    print("checklist-drain self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--run", action="store_true", help="execute runnable observe.how and write results/slips to the rows")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    today = datetime.now(timezone.utc).date()
    rows = load()["items"]
    if a.run:
        sys.path.insert(0, str(REPO / "scripts" / "ops"))
        import checklist as ck  # noqa: PLC0415
        for r in due_now(rows, today):
            f: dict = {"slips": int(r.get("slips") or 0) + 1}
            if runnable((r.get("observe") or {}).get("how")):
                try:
                    f["observe"] = dict(r["observe"], **run_one(r))
                except (OSError, subprocess.TimeoutExpired) as exc:
                    f["observe"] = dict(r["observe"], last_result=f"drain could not run it: {type(exc).__name__}")
            ck.op_set(REPO, r["id"], f, "checklist_drain")
        rows = load()["items"]
    coll = pipeline_collisions()
    out = lines(rows, today, a.limit)
    out.append(f"### PIPELINE COLLISIONS -- {coll if coll is not None else 'COULD NOT LOOK'} displaced/shadowed id(s) "
               "(grandfathered ones are known; a NEW one is due work)")
    if a.json:
        print(json.dumps({"due": [r["id"] for r in due_now(rows, today)], "pipeline_collisions": coll}))
    else:
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
