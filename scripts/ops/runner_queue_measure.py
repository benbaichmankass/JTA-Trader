#!/usr/bin/env python3
"""Measure GitHub Actions queue latency per job class over the last N hours (lane QUEUE-FILL-STANDING-W47b, 2026-11-19).

Latency is the JOB's started_at - created_at (the run-level run_started_at equals created_at and measures nothing).
Classes: research (workflow name starts with research-script-run or in RESEARCH_NAMES), alarm (the short-job workflows
listed in research_compute.yaml limits.repo_queued_ignore_workflows), ci (everything else).
# wiring: manual-only - an operator/lane-run measurement (re-run after dispatcher limit changes); nothing schedules it
Read-only; needs `gh` auth. Usage: python3 scripts/ops/runner_queue_measure.py --hours 48 [--repo owner/name]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_PREFIXES = ("research-script-run", "e35-bracket-sweep")


def _gh(args):
    r = subprocess.run(["gh", "api", "-X", "GET", *args], capture_output=True, text=True, check=False)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def classify(name, alarm_names):
    if name in alarm_names:
        return "alarm"
    if name.startswith(RESEARCH_PREFIXES):
        return "research"
    return "ci"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--repo", default=None)
    a = ap.parse_args(argv)
    repo = a.repo or subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True,
                                    cwd=REPO_ROOT, check=False).stdout.strip().split("github.com/")[-1].split("github.com:")[-1].removesuffix(".git")
    cfg = yaml.safe_load((REPO_ROOT / "scripts/research/research_compute.yaml").read_text())
    alarm = set(cfg.get("limits", {}).get("repo_queued_ignore_workflows") or [])
    now = datetime.now(timezone.utc)
    t = now - timedelta(hours=a.hours)
    runs = {}
    while t < now:
        t2 = min(t + timedelta(hours=2), now)
        for page in range(1, 11):
            ls = _gh([f"repos/{repo}/actions/runs", "-f", f"created={t:%Y-%m-%dT%H:%M:%SZ}..{t2:%Y-%m-%dT%H:%M:%SZ}",
                      "-f", "per_page=100", "-f", f"page={page}", "--jq", ".workflow_runs[] | [.id,.name,.event] | @json"])
            for ln in ls:
                v = json.loads(ln)
                runs[v[0]] = v
            if len(ls) < 100:
                break
        t = t2
    lat = {"research": [], "alarm": [], "ci": []}
    for rid, name, _ev in runs.values():
        for ln in _gh([f"repos/{repo}/actions/runs/{rid}/jobs", "-f", "per_page=100", "--jq",
                      ".jobs[] | [.created_at,(.started_at//\"\")] | @json"]):
            c, s = json.loads(ln)
            if s:
                lat[classify(name, alarm)].append((_ts(s) - _ts(c)).total_seconds() / 60)
    print(f"population: {len(runs)} runs created in the last {a.hours:g} h in {repo}; jobs with a start time only")
    for k, v in lat.items():
        if v:
            v.sort()
            p90 = v[int(0.9 * (len(v) - 1))]
            print(f"{k:9s} n={len(v):5d} median={statistics.median(v):6.1f} min  p90={p90:6.1f} min  max={v[-1]:6.1f} min")
        else:
            print(f"{k:9s} n=0 (no started jobs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
