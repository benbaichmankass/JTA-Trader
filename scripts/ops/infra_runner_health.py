#!/usr/bin/env python3
"""Keep vars.INFRA_RUNS_ON honest: hosted fallback when no `jta-infra` runner is online (row GH-CAPACITY-INFRA-RUNNER).

Prime Directive (no halting): a moved workflow must never sit queued forever behind a dead self-hosted runner.
Decision table (pure function `decide`, pinned by tests/test_infra_runner_health.py):

    var unset                      -> noop   (never smoked: stays hosted by the workflows' default)
    var=self-hosted, online == 0 or trainer disk < 15 GB / unreadable
                                   -> fallback  (set '"ubuntu-latest"'; exit 1 once = ONE red flag)
    var=hosted,      online >= 1   -> resmoke  (dispatch infra-runner-smoke.yml; it re-arms on green),
                                      unless a smoke run started < 60 min ago
    otherwise                      -> noop

Needs GH_TOKEN = BRANCH_PROTECTION_TOKEN (Administration read for the runner list, Variables read+write).
Reads/writes nothing else. Gates this adds or changes: none.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

SELF_HOSTED = '["self-hosted","jta-infra"]'
HOSTED = '"ubuntu-latest"'
LABEL = "jta-infra"


DISK_FLOOR_GB = 15.0  # one job clones ~7 GB; 2026-11-03 14:10Z the trainer disk hit 100% and a real-money close died


def decide(var_value: str | None, online: int, minutes_since_smoke: float | None,
           disk_free_gb: float | None = None) -> str:
    """disk_free_gb: trainer root free space; None = could not look (treated as unknown, not as fine
    when routing is armed -- an unreadable disk falls back, because a full disk halts every job)."""
    if var_value is None:
        return "noop"
    v = var_value.replace(" ", "")
    disk_bad = disk_free_gb is None or disk_free_gb < DISK_FLOOR_GB
    if "jta-infra" in v and (online == 0 or disk_bad):
        return "fallback"
    if "jta-infra" not in v and online >= 1 and not disk_bad:
        if minutes_since_smoke is not None and minutes_since_smoke < 60:
            return "noop"
        return "resmoke"
    return "noop"


def _api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GH_REPO']}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {}


def main() -> int:
    code, runners = _api("GET", "/actions/runners?per_page=100")
    if code != 200:
        print(f"::error::runner list HTTP {code} — could not look (not 'zero online')")
        return 1
    mine = [r for r in runners.get("runners", []) if any(lb["name"] == LABEL for lb in r.get("labels", []))]
    online = sum(1 for r in mine if r.get("status") == "online")
    for r in mine:
        print(f"runner {r['name']} status={r['status']} busy={r.get('busy')}")

    code, var = _api("GET", "/actions/variables/INFRA_RUNS_ON")
    if code not in (200, 404):
        print(f"::error::variable read HTTP {code} — could not look")
        return 1
    value = var.get("value") if code == 200 else None

    code, smokes = _api("GET", "/actions/workflows/infra-runner-smoke.yml/runs?per_page=1")
    since = None
    if code == 200 and smokes.get("workflow_runs"):
        t = dt.datetime.fromisoformat(smokes["workflow_runs"][0]["created_at"].replace("Z", "+00:00"))
        since = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60

    raw = os.environ.get("TRAINER_DISK_FREE_GB", "").strip()
    try:
        disk = float(raw) if raw else None
    except ValueError:
        disk = None
    action = decide(value, online, since, disk)
    print(f"INFRA_RUNS_ON={value!r} online={online}/{len(mine)} trainer_disk_free_gb={disk} "
          f"(floor {DISK_FLOOR_GB}) minutes_since_smoke={since} action={action}")
    if action == "fallback":
        c, _ = _api("PATCH", "/actions/variables/INFRA_RUNS_ON", {"name": "INFRA_RUNS_ON", "value": HOSTED})
        print(f"::error::no online {LABEL} runner or trainer disk below {DISK_FLOOR_GB} GB / unreadable "
              f"(online={online}, disk={disk}) — INFRA_RUNS_ON set to hosted (HTTP {c}); moved workflows run on ubuntu-latest")
        return 1
    if action == "resmoke":
        c, _ = _api("POST", "/actions/workflows/infra-runner-smoke.yml/dispatches", {"ref": "main"})
        print(f"runner back online — dispatched infra-runner-smoke (HTTP {c}); it re-arms INFRA_RUNS_ON on green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
