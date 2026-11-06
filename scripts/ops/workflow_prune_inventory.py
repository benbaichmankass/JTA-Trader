#!/usr/bin/env python3
"""Per-workflow Actions inventory for the workflow prune (WORKFLOW-PRUNE, 2026-11-06).

Read-only: only `gh api` GETs. Companion to actions_capacity_inventory.py (which classifies a 7-day window by compute class);
this one is per workflow over 90 days, and adds job-hours from a job sample.

  python3 scripts/ops/workflow_prune_inventory.py --days 90 --out comms/ci/workflow-prune-inventory-<date>.json

Population (printed into the output): every workflow the repo-level `actions/workflows` listing returns.
Per workflow: runs created in the window (all, and scheduled), the latest run ever, and per-conclusion counts for the LAST 7 DAYS
(90-day conclusion counts would need ~10x the reads; the 7-day mix is the stated population for every rate). Mean job-minutes
comes from up to --sample non-skipped runs of the last 7 days; job_h_per_wk = mean job-minutes x non-skipped 7-day runs / 60.
Limits stated, not hidden: a filtered listing reports total_count capped at 2500, so any window that reaches 2500 is split in
halves until it does not; a read that fails is listed under read_failures with its path and is never counted as 0.
"""
# wiring: manual-only - an on-demand measurement run by a session (WORKFLOW-PRUNE); no schedule, so it spends no runner
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def repo_slug() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, check=False).stdout
    return re.sub(r"\.git$", "", re.sub(r"^.*github\.com[:/]|^.*/git/", "", url.strip()))


SLUG = repo_slug()
FAILS: list = []


def api(path: str, tries: int = 4):
    for i in range(tries):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
        if r.returncode == 0:
            return json.loads(r.stdout)
        time.sleep(2 ** i)
    FAILS.append({"path": path, "err": r.stderr.strip()[:200]})
    return None


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


CAP = 2500  # observed: a filtered runs listing reports total_count capped at 2500, so a count >= CAP is split in halves


def count(wid: int, extra: str, lo: datetime, hi: datetime) -> int | None:
    """Exact count of runs created in [lo, hi) with the extra filters, splitting any window that hits the API cap."""
    d = api(f"repos/{SLUG}/actions/workflows/{wid}/runs?per_page=1&created={iso(lo)}..{iso(hi)}" + (f"&{extra}" if extra else ""))
    if d is None:
        return None
    n = d["total_count"]
    if n < CAP or (hi - lo) <= timedelta(minutes=30):
        return n
    mid = lo + (hi - lo) / 2
    a, b = count(wid, extra, lo, mid), count(wid, extra, mid, hi)
    return None if a is None or b is None else a + b


def one(w: dict, now: datetime, days: int, sample: int) -> dict:
    wid = w["id"]
    lo90, lo7 = now - timedelta(days=days), now - timedelta(days=7)
    out = {"id": wid, "name": w["name"], "path": w["path"], "state": w["state"]}
    first = api(f"repos/{SLUG}/actions/workflows/{wid}/runs?per_page=1")  # latest run ever (no window)
    out["last_run"] = first["workflow_runs"][0]["created_at"] if first and first["workflow_runs"] else None
    out["last_event"] = first["workflow_runs"][0]["event"] if first and first["workflow_runs"] else None
    out["runs_90d"] = count(wid, "", lo90, now)
    out["schedule_90d"] = count(wid, "event=schedule", lo90, now)
    for c in ("success", "failure", "cancelled", "skipped"):
        out[f"{c}_7d"] = count(wid, f"status={c}", lo7, now)
    out["runs_7d"] = count(wid, "", lo7, now)
    out["nonskipped_7d"] = None if None in (out["runs_7d"], out["skipped_7d"]) else out["runs_7d"] - out["skipped_7d"]
    mins = []
    if out["nonskipped_7d"]:
        for st in ("success", "failure"):
            d = api(f"repos/{SLUG}/actions/workflows/{wid}/runs?per_page={sample}&created=%3E%3D{iso(lo7)}&status={st}")
            for r in (d or {}).get("workflow_runs", []):
                if len(mins) >= sample:
                    break
                j = api(f"repos/{SLUG}/actions/runs/{r['id']}/jobs?per_page=100")
                tot = 0.0
                for job in (j or {}).get("jobs", []):
                    if job.get("runner_id") is None or not job.get("started_at") or not job.get("completed_at"):
                        continue
                    a = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                    b = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                    tot += max((b - a).total_seconds(), 0) / 60
                mins.append(tot)
            if len(mins) >= sample:
                break
    out["job_min_sampled_runs"] = len(mins)
    out["mean_job_min"] = round(sum(mins) / len(mins), 2) if mins else None
    out["job_h_per_wk"] = round(out["mean_job_min"] * out["nonskipped_7d"] / 60, 2) if mins else (0.0 if out["nonskipped_7d"] == 0 else None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--sample", type=int, default=6)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    s90 = iso(now - timedelta(days=a.days))
    wfs, page = [], 1
    while True:
        d = api(f"repos/{SLUG}/actions/workflows?per_page=100&page={page}")
        if not d or not d["workflows"]:
            break
        wfs += d["workflows"]
        if len(wfs) >= d["total_count"]:
            break
        page += 1
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda w: one(w, now, a.days, a.sample), wfs))
    res = {"generated_at": iso(now), "repo": SLUG, "window_days": a.days, "since": s90,
           "population": f"{len(wfs)} workflows from the actions/workflows listing", "read_failures": FAILS,
           "could_not_look": len(FAILS), "workflows": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(f"{len(wfs)} workflows, {len(FAILS)} failed reads -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
