#!/usr/bin/env python3
"""Liveness for the two feeds the live news layer reads: the economic calendar and the news log.

Checklist row ``DATA-FEEDS-NEWS-CALENDAR`` (operator, 2026-10-26: *"Those should be routinely
maintained and updated data feeds, not one off uploads"*). Run daily by
``macro-producer-liveness.yml`` (already in CADENCE_REGISTRY and claude-run-failure-alert), so no new cron.

Three verdicts, each ``ok`` | ``stale`` | ``could_not_look`` — *looked and found it stale* and *could not
look* are different facts and are never folded together:

* ``calendar_horizon`` — newest event in ``config/economic_calendar.yaml`` is < 7 days ahead of now.
* ``calendar_refresh`` — newest successful FXStreet capture (a failed fetch writes none) is > 36 h old.
* ``news`` — ``news_decisions`` has no row for > ``NEWS_MAX_GAP_H`` while a crypto package is open.
  N = 12 h: measured over the 999 inter-row gaps of the 1000-row tail (2026-10-07..10-26) the median gap
  is 7 min and only 1 gap exceeds 12 h (9 exceed 6 h, 3 exceed 8 h); rows are written per actionable
  signal, so a quiet market is not a dead feed. No crypto package open → ``ok`` (nothing to be stale
  for). Population: that one VM log tail, not the full file.

Read-only; stdlib-only; exit 0 = all ok, 1 = any stale, 2 = no stale but something could not be looked at.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CALENDAR = REPO_ROOT / "config" / "economic_calendar.yaml"
CAPTURES = REPO_ROOT / "comms" / "macro" / "econ_calendar_captures"

MIN_HORIZON = timedelta(days=7)
MAX_REFRESH_AGE = timedelta(hours=36)
NEWS_MAX_GAP_H = 12.0

_EVENT_TIME = re.compile(r'time:\s*"([0-9T:\-]+Z?)"')
_CAPTURE_TS = re.compile(r"^[A-Za-z]{2,4}-(\d{8}T\d{6}Z)\.")


def _verdict(state: str, detail: str, **extra: Any) -> dict:
    return {"state": state, "detail": detail, **extra}


def _parse_iso(raw: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def check_calendar_horizon(path: Path, now: datetime) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return _verdict("could_not_look", f"calendar unreadable: {type(exc).__name__}")
    times = [t for t in (_parse_iso(m) for m in _EVENT_TIME.findall(text)) if t]
    if not times:
        return _verdict("stale", "calendar carries no events", newest_event=None)
    newest = max(times)
    ahead = newest - now
    if ahead < MIN_HORIZON:
        return _verdict("stale", f"newest event {newest.isoformat()} is {ahead.total_seconds() / 86400:.1f}d ahead (< 7d)",
                        newest_event=newest.isoformat())
    return _verdict("ok", f"newest event {newest.isoformat()} is {ahead.total_seconds() / 86400:.1f}d ahead",
                    newest_event=newest.isoformat())


def check_calendar_refresh(captures_dir: Path, now: datetime) -> dict:
    d = Path(captures_dir)
    if not d.is_dir():
        return _verdict("could_not_look", "captures dir absent")
    stamps = []
    for p in d.iterdir():
        m = _CAPTURE_TS.match(p.name)
        if m:
            stamps.append(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    if not stamps:
        return _verdict("stale", "no captures", last_success=None)
    last = max(stamps)
    age = now - last
    if age > MAX_REFRESH_AGE:
        return _verdict("stale", f"last successful capture {last.isoformat()} is {age.total_seconds() / 3600:.1f}h old (> 36h)",
                        last_success=last.isoformat())
    return _verdict("ok", f"last successful capture {last.isoformat()} ({age.total_seconds() / 3600:.1f}h old)",
                    last_success=last.isoformat())


def check_news(log_tail: Optional[dict], open_packages: Optional[dict], now: datetime,
               max_gap_h: float = NEWS_MAX_GAP_H) -> dict:
    if not isinstance(log_tail, dict) or not log_tail.get("present"):
        return _verdict("could_not_look", "news_decisions log not readable (diag absent or log not present)")
    if not isinstance(open_packages, dict) or open_packages.get("db_state") != "read":
        return _verdict("could_not_look", "open packages not readable")
    crypto = sorted({str(p.get("symbol")) for p in open_packages.get("packages", [])
                     if str(p.get("symbol", "")).upper().endswith("USDT")})
    last: Optional[datetime] = None
    for ln in log_tail.get("lines", []):
        try:
            t = _parse_iso(json.loads(ln).get("ts"))
        except (ValueError, AttributeError):
            continue
        if t and (last is None or t > last):
            last = t
    if not crypto:
        return _verdict("ok", "no crypto package open — nothing to be stale for", last_row=last.isoformat() if last else None)
    if last is None:
        return _verdict("could_not_look", "no parseable row in the log tail")
    gap_h = (now - last).total_seconds() / 3600
    if gap_h > max_gap_h:
        return _verdict("stale", f"no news_decisions row for {gap_h:.1f}h (> {max_gap_h:g}h) with crypto open: {','.join(crypto)}",
                        last_row=last.isoformat())
    return _verdict("ok", f"last row {gap_h:.1f}h ago; crypto open: {','.join(crypto)}", last_row=last.isoformat())


def _load(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--calendar", default=str(CALENDAR))
    ap.add_argument("--captures-dir", default=str(CAPTURES))
    ap.add_argument("--news-log-json", help="diag log_file?name=news_decisions JSON")
    ap.add_argument("--open-packages-json", help="diag open_packages JSON")
    ap.add_argument("--now", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    now = _parse_iso(args.now) if args.now else datetime.now(timezone.utc)

    results = {
        "calendar_horizon": check_calendar_horizon(Path(args.calendar), now),
        "calendar_refresh": check_calendar_refresh(Path(args.captures_dir), now),
        "news": check_news(_load(args.news_log_json), _load(args.open_packages_json), now),
    }
    states = {v["state"] for v in results.values()}
    rc = 1 if "stale" in states else 2 if "could_not_look" in states else 0
    if args.json:
        print(json.dumps({"results": results, "rc": rc}, indent=2))
    else:
        for k, v in results.items():
            print(f"[{v['state']}] {k}: {v['detail']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
