#!/usr/bin/env python3
# wiring: scripts/ops/render_daily_brief.py §0 (in-process in the web-api's /api/bot/work/brief), scripts/research/research_slo.py
"""Read side of the research-pipeline SLO status files (RESEARCH-PIPELINE-SLO, 2026-10-16).

Lives under scripts/ops/ (a runtime path) rather than in scripts/research/research_slo.py because the daily brief
imports it in-process in the web-api: scripts/research/ is non-runtime for deploy_pull_restart.sh except a measured
allowlist, and this keeps the brief's import closure inside paths the deploy already restarts on. The producer
(scripts/research/research_slo.py) writes comms/research/health/<date>.json and reuses these two functions.
Stdlib only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HEALTH_DIR = Path("comms/research/health")
OK = "ok"


def _ts(raw: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return round((a - b).total_seconds() / 3600.0, 2)


def _fmt(v: Any) -> str:
    return "—" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def latest_status(root: Path) -> tuple:
    """(doc, read_state) of the newest dated status file: read / absent / unreadable."""
    files = sorted((root / HEALTH_DIR).glob("2*.json"))
    if not files:
        return None, "absent"
    try:
        return json.loads(files[-1].read_text(encoding="utf-8")), "read"
    except (OSError, ValueError):
        return None, "unreadable"


def table_lines(doc: Optional[Dict[str, Any]], read_state: str, now: Optional[datetime] = None,
                stale_hours: float = 6.0) -> List[str]:
    """Brief §0 lines: the SLO table, or a declared hole. Never a silent zero."""
    if doc is None:
        return [f"### 🚨 Research pipeline SLOs — COULD NOT BE READ (status file {read_state}; we did not look, this is not 'ok')", ""]
    now = now or datetime.now(timezone.utc)
    asof = _ts(doc.get("as_of"))
    age = _hours(now, asof) if asof else None
    stale = age is None or age > stale_hours
    bad = [r for r in doc.get("latest") or [] if r.get("state") != OK]
    icon = "🚨" if bad or stale else "✅"
    hdr = (f"### {icon} Research pipeline SLOs — {len(bad)} not ok of {len(doc.get('latest') or [])} "
           f"(as of {doc.get('as_of')}, {_fmt(age)} h old{'; STALE — the monitor has not written for > %g h' % stale_hours if stale else ''})")
    L = [hdr, "", "| SLO | value | target | state |", "|---|---|---|---|"]
    for r in doc.get("latest") or []:
        st = {"ok": "ok", "breach": "**BREACH**", "could_not_look": "**could not look**"}.get(r.get("state"), str(r.get("state")))
        L.append(f"| {r['slo']} | {_fmt(r.get('value'))} | {r.get('op')} {_fmt(r.get('threshold'))} | {st} |")
    L.append("")
    if bad:
        L += ["- A red research SLO is DUE today: dispatch an authoring / fix lane (manager SKILL § \"Research SLO "
              "escalation\"). A note is not a disposition.", ""]
    return L
