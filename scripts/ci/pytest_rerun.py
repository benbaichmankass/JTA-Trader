#!/usr/bin/env python3
# wiring: .github/workflows/pytest-rerun.yml (calls `--run-id`), tests/test_pytest_rerun.py
"""Decide whether a finished `pytest-run` deserves ONE automatic rerun.

WHY (row AUTO-PYTEST-RERUN, plan act M-b): attempt-1 jobs cancelled by the job timeout, or
dead before the tests started, were rerun by hand on every busy day.

THE RULE IS NARROW ON PURPOSE. A rerun is allowed only when ALL hold:
  1. the run is attempt 1, and NO run for the same head sha has ever been a rerun
     (at most ONCE per head sha);
  2. the run ended `cancelled` or `failure`;
  3. the PR (or branch) head is still this sha - a superseded run is cancelled by
     concurrency on purpose and must not be revived;
  4. the evidence says infrastructure, never tests:
       - the `Run tests` step FAILED                      -> real failure, NEVER rerun;
       - `Run tests` was CANCELLED and the job ran for at least
         (timeout-minutes - 3) -> cancelled AT its timeout -> rerun;
       - `Run tests` was cancelled sooner (superseded / manual cancel) -> no rerun;
       - `Run tests` never started and the job failed (checkout / python / pip died) -> rerun;
       - anything else, or jobs we could not read -> no rerun (unknown is not a reason).
It never skips, disables or quarantines a test; it only re-queues the same run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "pytest-run.yml"
TESTS_STEP = "Run tests"
MARGIN_MIN = 3


def timeout_minutes(workflow: Path = WORKFLOW) -> int:
    m = re.search(r"^\s+timeout-minutes:\s*(\d+)\s*$", workflow.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise RuntimeError(f"no timeout-minutes in {workflow}")
    return int(m.group(1))


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def job_minutes(job: dict):
    a, b = _ts(job.get("started_at")), _ts(job.get("completed_at"))
    return (b - a).total_seconds() / 60 if a and b else None


def decide(run: dict, jobs: list, current_head: str | None, shas_with_rerun: bool,
           timeout_min: int) -> tuple[bool, str]:
    """Pure. `run` and `jobs` are GitHub API objects; returns (rerun?, reason)."""
    if (run.get("run_attempt") or 1) != 1:
        return False, "not attempt 1"
    if shas_with_rerun:
        return False, "this head sha has already been rerun once"
    if run.get("conclusion") not in ("cancelled", "failure"):
        return False, f"conclusion {run.get('conclusion')!r} needs no rerun"
    if not current_head:
        return False, "current head unknown (not a reason to rerun)"
    if current_head != run.get("head_sha"):
        return False, "head moved on: run was superseded"
    job = next((j for j in jobs if j.get("name") == "pytest-run"), None)
    if job is None:
        return False, "no pytest-run job readable"
    step = next((s for s in job.get("steps") or [] if s.get("name") == TESTS_STEP), None)
    sc = (step or {}).get("conclusion")
    if sc == "failure":
        return False, "the test step FAILED: a real failure is never rerun"
    if sc == "cancelled":
        mins = job_minutes(job)
        if mins is None:
            return False, "cancelled but job duration unknown"
        if mins >= timeout_min - MARGIN_MIN:
            return True, f"tests cancelled at the job timeout ({mins:.0f} of {timeout_min} min)"
        return False, f"tests cancelled after {mins:.0f} min, before the timeout: superseded or manual"
    if sc in (None, "skipped") and job.get("conclusion") == "failure":
        dead = [s.get("name") for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
        return True, f"died before the tests ran (failed step: {', '.join(map(str, dead)) or 'unknown'})"
    return False, f"test step {sc!r}, job {job.get('conclusion')!r}: not an infrastructure death"


def _gh(*args) -> object:
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    repo = a.repo
    run = _gh(f"repos/{repo}/actions/runs/{a.run_id}")
    jobs = _gh(f"repos/{repo}/actions/runs/{a.run_id}/jobs?per_page=100")["jobs"]
    prs = run.get("pull_requests") or []
    try:
        if prs:
            pr = _gh(f"repos/{repo}/pulls/{prs[0]['number']}")
            head = pr["head"]["sha"] if pr.get("state") == "open" else None
        else:
            head = _gh(f"repos/{repo}/branches/{run['head_branch']}")["commit"]["sha"]
        siblings = _gh(f"repos/{repo}/actions/workflows/pytest-run.yml/runs"
                       f"?head_sha={run['head_sha']}&per_page=100")["workflow_runs"]
    except subprocess.CalledProcessError as exc:
        print(f"pytest-rerun: cannot read state ({exc}); NOT rerunning")
        return 0
    rerun_seen = any((r.get("run_attempt") or 1) > 1 for r in siblings)
    ok, why = decide(run, jobs, head, rerun_seen, timeout_minutes())
    print(f"pytest-rerun: run {a.run_id} sha {run['head_sha'][:8]}: {'RERUN' if ok else 'no rerun'} - {why}")
    if ok and not a.dry_run:
        subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/actions/runs/{a.run_id}/rerun"], check=True)
        print("pytest-rerun: rerun requested (the one allowed for this sha)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
