#!/usr/bin/env python3
# wiring: scripts/ci/check_research_queue_throughput.py (schedule-keeper alarm) + scripts/ops/render_daily_brief.py §4
"""Research-queue THROUGHPUT — what the queue fired and landed, read from the checkout.

WHY (operator, 2026-09-30, lane RESEARCH-W7): "make sure those tests are running" — the queue not
running is a RECURRING failure. The existing idle alarm (`check_research_queue_health.py` H2) lives
as the LAST STEP of the dispatch job it watches, so a dispatcher whose runs are dropped, skipped or
red before that step raises nothing. This module is the read side; the alarm that uses it runs from
schedule-keeper (push-to-main + cron), outside the thing it watches.

Population: every research/queue/**/*.yaml (stamps) and every research/results/**/*.jsonl row
(`generated_at`), read from the checkout. A stamp is written when a unit FIRES, then lands on main via
a stamp PR ~40-60 min later, so "fired" lags reality by that landing time — the alarm threshold is
chosen with that lag in it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from scripts.research.queue_grade import _parse_ts, health
from scripts.research.queue_replenish import existing_units

#: Alarm when runnable units exist and nothing has FIRED for this long. 12 h was set when the cron
#: was 6-hourly: cron 6 h + GitHub's measured 4-6 h scheduler lag (schedule_keeper.py docstring) is
#: absorbed by the keeper's own dispatch, leaving one cycle (~6 h) + the ~1 h stamp-landing lag; 12 h
#: is that plus one missed cycle. It equals the operator's 2026-09-28 "no unit has run in 12h".
#: The cron went HOURLY on 2026-10-06 (operator: the git infrastructure keeps the queue moving) and
#: this is deliberately KEPT at 12 h: GitHub drops hourly slots outright (schedule_keeper.py, measured
#: 2026-09-20..27), the keeper's own floor is hourly, and a run's stamp still lands through a
#: ~1 h commit-to-main wait, so a tighter alarm would page on scheduler weather rather than on a
#: dispatcher that has actually stopped.
DEFAULT_IDLE_HOURS = 12.0


def throughput(root: Path, *, now: Optional[datetime] = None,
               idle_hours: float = DEFAULT_IDLE_HOURS) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    h = health(root, now=now)
    units, _bad = existing_units(root)
    stamps = [t for u in units.values() if (t := _parse_ts(u.get("last_dispatched_at")))]
    since = now - timedelta(hours=24)
    landed, unreadable = 0, 0
    for f in (root / "research" / "results").glob("*/*.jsonl"):
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                t = _parse_ts(json.loads(ln).get("generated_at"))
                landed += bool(t and t >= since)
        except (OSError, ValueError):
            unreadable += 1
    hrs = h["hours_since_last_dispatch"]
    return {"as_of": now.isoformat(), "runnable": h["runnable"], "queued": h["queued"], "units": h["units"],
            "fired_24h": sum(1 for t in stamps if t >= since),
            "fired_7d": sum(1 for t in stamps if t >= now - timedelta(days=7)),
            "results_landed_24h": landed, "result_files_unreadable": unreadable,
            "last_dispatched_at": h["last_dispatched_at"], "hours_since_last_dispatch": hrs,
            "idle_threshold_hours": idle_hours,
            "idle_alarm": bool(h["runnable"] > 0 and (hrs is None or hrs > idle_hours))}


#: THE FLOOR, in one place (moved here from check_research_queue_health.py by lane RESEARCH-ENGINE-1016,
#: 2026-10-16, so the in-process brief and the CI health check compute the same number). Hours of supply
#: the floor must cover at the observed fire rate -- the research-ops SKILL's own derivation (25 units =
#: ~19 h at fired_24h 32, 2026-10-10), made mechanical.
FLOOR_HOURS = 19.0
MIN_FLOOR = 25
OPS_DIR = Path("comms/research/ops")


def computed_floor(fired_24h: Any, *, minimum: int = MIN_FLOOR) -> int:
    """max(minimum, ceil(fired_24h x FLOOR_HOURS / 24)); `minimum` when the rate is unread."""
    import math
    try:
        return max(minimum, math.ceil(float(fired_24h) * FLOOR_HOURS / 24.0))
    except (TypeError, ValueError):
        return minimum


def floor_gap(t: Dict[str, Any], root: Path) -> Dict[str, Any]:
    """{floor, runnable, gap, below_floor_passes, ops_records_read, since}: today's gap from the throughput
    dict, plus how many CONSECUTIVE newest research-ops records (comms/research/ops/) also ended below
    their own recorded floor -- a gap that research-ops has handed off pass after pass, which is the
    manager-loop failure measured 2026-10-16 (runnable 22 -> 18 -> 9 while the floor rose 25 -> 46 -> 50,
    every handoff naming it, nobody acting). Cheap: reads at most the 12 newest record files."""
    floor = computed_floor(t.get("fired_24h"))
    runnable = int(t.get("runnable") or 0)
    streak, since, read = 0, None, 0
    for f in sorted((root / OPS_DIR).glob("2*.json"), reverse=True)[:12]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            rf = int(d.get("floor") or MIN_FLOOR)
            ra = int((d.get("throughput") or {}).get("runnable_after"))
        except (OSError, ValueError, TypeError):
            break                                   # unreadable or unrecorded: the streak cannot be extended
        read += 1
        if ra >= rf:
            break
        streak, since = streak + 1, f.stem
    return {"floor": floor, "runnable": runnable, "gap": max(0, floor - runnable),
            "below_floor_passes": streak, "ops_records_read": read, "since": since}


def floor_gap_lines(t: Optional[Dict[str, Any]], root: Path) -> list:
    """Brief §0 lines: empty when the floor is met; a declared hole when throughput was unread."""
    if t is None:
        return ["### 🚨 Research floor — COULD NOT BE READ (we did not look; this is not 'met')", ""]
    g = floor_gap(t, root)
    if g["gap"] == 0:
        return []
    streak = (f"; below floor at the end of the last {g['below_floor_passes']} research-ops pass(es) (since {g['since']})"
              if g["below_floor_passes"] else "")
    return [f"### 🚨 RESEARCH FLOOR GAP — runnable {g['runnable']} < floor {g['floor']} (gap {g['gap']}){streak}", "",
            "- This is DUE today: dispatch a same-day authoring lane (manager SKILL § \"The roadmap loop\" / research-ops "
            "step E), sized to the gap and aimed at the themes `check_research_queue_health.py` lists as `H1-THEME`. "
            "A handoff note is not a disposition.", ""]


def summary_line(t: Dict[str, Any]) -> str:
    return (f"research queue (24h): fired {t['fired_24h']} · results landed {t['results_landed_24h']} · "
            f"runnable now {t['runnable']} of {t['queued']} queued · last fire "
            f"{t['hours_since_last_dispatch']} h ago" + (" · ⚠️ IDLE ALARM" if t["idle_alarm"] else ""))
