#!/usr/bin/env python3
# wiring: manual-only - the daily re-measure of the schedule-keeper gap (checklist KEEPER-VM-FLOOR; pipeline item re-runs it).
"""Daily max gap between COMPLETED-SUCCESS schedule-keeper.yml runs, vs the smallest stale window of any keeper target.

    python3 scripts/ops/keeper_gap_report.py            # last 48h, public Actions API (GITHUB_TOKEN/GH_TOKEN used if set)
    python3 scripts/ops/keeper_gap_report.py --hours 72 --strict

Why: GitHub drops most of this repo's cron slots, so the keeper's only reliable clock is the stream of bot pushes. If the
longest gap between two successful keeper runs ever exceeds the smallest stale window in schedule_keeper.TARGETS, a target
can go unnoticed: that is the flag (exit 1 with --strict). The hard floor (a trainer-VM timer) is parked in KEEPER-VM-FLOOR
until this number says it is needed. Read-only; nothing here dispatches or changes anything.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics as st
import sys
import urllib.request
from pathlib import Path

REPO_SLUG = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/JTA-Trader")


def _get(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def smallest_stale_window_h() -> float | None:
    """min(stale_hours) over schedule_keeper.TARGETS; None when the module cannot be read (a null, never 0)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import schedule_keeper as sk
        return min(float(v["stale_hours"]) for v in sk.TARGETS.values())
    except Exception:  # noqa: BLE001 - could-not-look is reported, not raised
        return None


def runs(hours: int) -> list[dict]:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, page = [], 1
    while page <= 10:
        d = _get(f"https://api.github.com/repos/{REPO_SLUG}/actions/workflows/schedule-keeper.yml/runs?per_page=100&page={page}")
        rs = d.get("workflow_runs") or []
        out += [r for r in rs if dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since]
        if len(rs) < 100 or dt.datetime.fromisoformat(rs[-1]["created_at"].replace("Z", "+00:00")) < since:
            break
        page += 1
    return out


def report(rs: list[dict], window_h: float | None) -> dict:
    ok = sorted(dt.datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")) for r in rs if r.get("conclusion") == "success")
    gaps = [((b - a).total_seconds() / 60, a, b) for a, b in zip(ok, ok[1:])]
    by_day: dict[str, float] = {}
    for g, a, _b in gaps:
        by_day[a.strftime("%Y-%m-%d")] = max(by_day.get(a.strftime("%Y-%m-%d"), 0.0), g)
    mx = max(gaps, default=None)
    return {"runs": len(rs), "success": len(ok), "cancelled": sum(r.get("conclusion") == "cancelled" for r in rs),
            "schedule_events": sum(r.get("event") == "schedule" for r in rs),
            "median_gap_min": round(st.median([g for g, _, _ in gaps]), 1) if gaps else None,
            "max_gap_min": round(mx[0], 1) if mx else None, "max_gap_between": [mx[1].isoformat(), mx[2].isoformat()] if mx else None,
            "daily_max_gap_min": {k: round(v, 1) for k, v in sorted(by_day.items())},
            "smallest_stale_window_min": round(window_h * 60) if window_h is not None else None,
            "flag": (mx[0] > window_h * 60) if (mx and window_h is not None) else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--strict", action="store_true", help="exit 1 when the max gap exceeds the smallest stale window, 2 when it cannot be judged")
    a = ap.parse_args(argv)
    rep = report(runs(a.hours), smallest_stale_window_h())
    print(json.dumps(rep, indent=1))
    if a.strict:
        return 2 if rep["flag"] is None else (1 if rep["flag"] else 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
