#!/usr/bin/env python3
"""Run one desk-trigger build job OUTSIDE the trader's cgroup (DESK-TRIGGER-SCAN-TIMEOUT).

Started by ``ict-desk-build@<job>.service`` (a oneshot template unit, its own cgroup) so a deploy restart of
``ict-trader-live`` -- which SIGTERMs the trader's whole cgroup -- no longer kills an in-flight build.
``<job>`` names ``runtime_logs/desk/jobs/<job>/job.json``: ``{"stages": [{"name", "argv", "timeout_s"}], "env": {...}}``.
Each stage keeps the caller's own timeout (420 s today); a stage that exceeds it is killed and recorded.
Writes ``result.json`` (``state`` ok|failed|timeout, per-stage ``outcome`` + ``wall_s``, stderr tail) atomically, ALWAYS --
the record a build leaves even when the trader that asked for it is gone. No halting: it runs once and exits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / "runtime_logs" / "desk" / "jobs"


def run(job_dir: Path) -> dict:
    spec = json.loads((job_dir / "job.json").read_text())
    env = dict(os.environ, **{str(k): str(v) for k, v in (spec.get("env") or {}).items()})
    res = {"state": "ok", "stages": [], "started_at": time.time(), "path": "unit"}
    for st in spec["stages"]:
        t0 = time.monotonic()
        try:
            r = subprocess.run(st["argv"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=float(st["timeout_s"]))
        except subprocess.TimeoutExpired:
            res["stages"].append({"stage": st["name"], "outcome": "timeout", "wall_s": round(time.monotonic() - t0, 1)})
            res["state"] = "timeout"
            break
        row = {"stage": st["name"], "outcome": f"exit {r.returncode}", "wall_s": round(time.monotonic() - t0, 1)}
        if r.returncode != 0:
            row["tail"] = (r.stderr or r.stdout).strip()[-160:]
            res["stages"].append(row)
            res["state"] = "failed"
            break
        res["stages"].append(row)
    return res


def main(argv: list) -> int:
    if len(argv) != 2 or not argv[1].replace("-", "").isalnum():
        print("usage: desk_build_job.py <job-id>", file=sys.stderr)
        return 2
    job_dir = JOBS / argv[1]
    try:
        res = run(job_dir)
    except Exception as exc:  # noqa: BLE001 -- the record is the point; never exit without one
        res = {"state": "failed", "stages": [], "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    res["finished_at"] = time.time()
    tmp = job_dir / "result.json.tmp"
    tmp.write_text(json.dumps(res, indent=1))
    os.replace(tmp, job_dir / "result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
