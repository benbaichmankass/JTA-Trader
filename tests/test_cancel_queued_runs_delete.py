"""cancel-queued-runs.yml delete mode (row ACTIONS-ZOMBIE-QUEUED-RUNS, GH-API-RATE-LIMIT-1126).

The step is shell inside a workflow, so the tests extract it and run it under bash with a stub `gh`: a dry run deletes nothing,
a run that is never refused deletes every eligible id oldest-first, a rate-limit message stops the loop at once, and ten
generic refusals in a row stop it too (it must not hammer an endpoint that keeps refusing).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "cancel-queued-runs.yml"

STUB = r'''
IDS="${STUB_IDS}"
gh() {
  case "$1" in
    run)   if printf '%s ' "$@" | grep -q "length"; then echo 42; else printf '%s\n' ${IDS}; fi ;;
    api)
      if printf '%s ' "$@" | grep -q "rate_limit"; then echo "core remaining=900 limit=1000 resets_at=2026-11-26T19:00:00Z"; return 0; fi
      if printf '%s ' "$@" | grep -q -- "--method DELETE"; then
        id=$(printf '%s\n' "$@" | grep -o 'runs/[0-9]*' | head -1 | cut -d/ -f2)
        echo "$id" >> "$DELETE_CALLS"
        n=$(wc -l < "$DELETE_CALLS")
        case "$STUB_MODE" in
          ok) return 0 ;;
          rate_at_3) if [ "$n" -ge 3 ]; then echo "gh: API rate limit exceeded for installation (HTTP 403)" >&2; return 1; fi; return 0 ;;
          always_403) echo "gh: Could not delete the workflow run (HTTP 403)" >&2; return 1 ;;
        esac
      fi
      echo 0 ;;   # the jobs lookup: no job started
  esac
}
'''


def _step() -> str:
    steps = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["cancel"]["steps"]
    return next(s for s in steps if s.get("id") == "zombies")["run"]


def _run(tmp_path, *, mode: str, dry: str, ids: str):
    calls = tmp_path / "deletes"
    calls.write_text("")
    script = STUB + "\n" + _step()
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "REPO": "o/r", "MIN_AGE_HOURS": "24", "THROTTLE": "0", "DRY_RUN": dry,
                            "STUB_IDS": ids, "STUB_MODE": mode, "DELETE_CALLS": str(calls)})
    return p, [x for x in calls.read_text().splitlines() if x]


def test_a_dry_run_deletes_nothing_and_lists_every_eligible_run(tmp_path):
    p, deletes = _run(tmp_path, mode="ok", dry="true", ids="30 10 20")
    assert deletes == []
    assert p.stdout.count("WOULD DELETE") == 3
    assert "deleted=0" in p.stdout and "eligible=3" in p.stdout and "stopped=none" in p.stdout


def test_a_live_run_deletes_oldest_first_and_prints_the_rate_limit_before_and_after(tmp_path):
    p, deletes = _run(tmp_path, mode="ok", dry="false", ids="30 10 20")
    assert deletes == ["10", "20", "30"]                         # ascending, whatever order the listing came in
    assert "deleted=3" in p.stdout and "refused=0" in p.stdout and "stopped=none" in p.stdout
    assert "rate limit BEFORE: core remaining=900" in p.stdout and "rate limit AFTER: core remaining=900" in p.stdout


def test_a_rate_limit_message_stops_the_loop_at_once(tmp_path):
    p, deletes = _run(tmp_path, mode="rate_at_3", dry="false", ids="1 2 3 4 5 6 7 8")
    assert deletes == ["1", "2", "3"]                            # the third call was refused; nothing after it was tried
    assert "stopped=rate_limit" in p.stdout and "deleted=2" in p.stdout and "refused=1" in p.stdout
    assert "STOP: rate-limit message" in p.stdout


def test_ten_generic_refusals_in_a_row_stop_the_loop_and_the_api_message_is_printed(tmp_path):
    p, deletes = _run(tmp_path, mode="always_403", dry="false", ids=" ".join(str(i) for i in range(1, 30)))
    assert len(deletes) == 10
    assert "stopped=consecutive_refusals" in p.stdout and "deleted=0" in p.stdout and "refused=10" in p.stdout
    assert "refused 1: gh: Could not delete the workflow run (HTTP 403)" in p.stdout     # the API's own words are in the log


def test_a_run_that_started_a_job_is_kept_never_deleted(tmp_path):
    script = STUB.replace('echo 0 ;;   # the jobs lookup: no job started', 'echo 1 ;;') + "\n" + _step()
    calls = tmp_path / "deletes"
    calls.write_text("")
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "REPO": "o/r", "MIN_AGE_HOURS": "24", "THROTTLE": "0", "DRY_RUN": "false",
                            "STUB_IDS": "5 6", "STUB_MODE": "ok", "DELETE_CALLS": str(calls)})
    assert calls.read_text() == ""
    assert "kept=2" in p.stdout and "deleted=0" in p.stdout
