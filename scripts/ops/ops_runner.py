#!/usr/bin/env python3
# wiring: run by deploy/ict-ops-runner.service, which deploy/ict-ops-runner.path starts whenever the ops queue dir
# (/data/bot-data/runtime_logs/ops/queue) is not empty.
"""Drain the direct ops channel's queue (MANAGER-VM-DIRECT-OPS; design § 2.3).

The web API (``POST /api/bot/ops/actions``) only writes job files; this runner, in its own systemd unit, runs them,
so a ``restart-service ict-web-api`` job cannot kill the process that is serving it. Every job is claimed by an
atomic rename, run through ``src.runtime.ops_actions.run_job`` and journaled; the queue is always left empty so the
path unit does not re-trigger on a stuck file. Exit 0 always (a failed job is the JOB's state, not the runner's);
no halting.
"""
from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.runtime import ops_actions  # noqa: E402


def main() -> int:
    for job in ops_actions.run_queue():
        print(json.dumps({k: job.get(k) for k in ("job_id", "action", "state", "exit", "run_s")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
