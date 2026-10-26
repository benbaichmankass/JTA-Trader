#!/usr/bin/env python3
"""Workplan §0.WS-5 — macro-producer cron **liveness + validity** monitor.

The "silently-skipped scheduled job" failure class made concrete: a scheduled
producer whose cron quietly stops firing (a workflow disabled after 60 days of
repo inactivity, a broken commit-to-main hop, a renamed secret) leaves its
append-only ledger frozen — and *nothing notices*, because the ledger still
exists and still reads cleanly. The gate downstream just keeps replaying a log
that stopped growing. This is the exact shape of the incidents the "if you see
something, say something" directive exists to kill (a stale data feed that
everyone walks past).

This monitor is the dead-man switch for that class. It asserts TWO things per
registered producer, because freshness alone provably does not cover the class
(every liveness signal was green while `econ_event_study` computed a verdict from
`price_bars: 0` for the producer's entire life — BL-20260730-M1-PRICE-JOIN-DEAD):

1. **STALENESS** — the freshest ``observed_at`` across the ledger is older than a
   per-producer threshold ⇒ the cron may have stopped firing.
2. **VACUITY of the latest run** (T3, 2026-08-02, RESEARCH-PROGRAM-2026-07-30) —
   the ledger is fresh AND still growing, but the **newest producer batch** (the
   rows sharing the max ``observed_at``) carries fewer than ``min_inputs``
   *load-bearing* rows ⇒ the producer fired and appended, but measured nothing
   (e.g. an all-null FRED batch). This is the ledger analogue of the scorecard
   vacuity that ``scripts/ops/check_artifact_validity.py`` guards on the OUTPUT
   side — and it is strictly stronger than that script's whole-file
   ``jsonl_min_rows`` check, which a frozen-but-nonempty ledger passes forever:
   this looks only at the *latest batch*, so a producer that keeps firing but
   writes empty batches is caught here even while its ledger row-count grows.

It is **read-only** — it never fetches, never mutates a ledger, never touches a
VM. The alerting (Telegram + a GitHub issue) lives in the
``macro-producer-liveness`` workflow that invokes this script; the script's job
is the honest verdict and a non-zero exit on any bad status — the same exit-code
contract the workflow already branches on, so both STALE and VACUOUS surface
through the existing alert path with no workflow change.

Registered scheduled producers (the ``PRODUCERS`` registry below is the
authoritative list — a new scheduled producer is one entry, not a rewrite):

    * ``comms/macro/valuation_snapshots.jsonl``     — daily 07:30 UTC
      (``macro-valuation-snapshot.yml``); load-bearing key ``value`` (a null
      value is FRED returning nothing).
    * ``comms/macro/econ_calendar_snapshots.jsonl`` — daily ~22:30 UTC
      (``econ-calendar-produce.yml``); each newest-batch row is a captured
      calendar event.

Dispatch/issue-driven one-shots (COT, the valuation backfill) have no schedule,
so they cannot "silently skip a cron" and are deliberately out of scope. The
weekly ``econ-event-study`` writes a scorecard (a single JSON artifact, not an
append-only ledger) and is covered on the vacuity side by
``check_artifact_validity.py``. The check stays generic
(``--ledger PATH:MAX_AGE_HOURS``) so an ad-hoc freshness probe of any ledger is
one flag away.

Freshness basis: the maximum ``observed_at`` over all rows (the ledger is
append-only and NOT guaranteed sorted, so we scan for the max rather than trust
the last line). ``observed_at`` is an ISO-8601 UTC stamp (``...Z`` /
``+00:00`` / naive all accepted, treated as UTC) — the same convention the diag
audit-query path uses.

Exit codes:
    0  every registered producer is FRESH and its latest batch is non-vacuous
       (or, with --allow-missing, absent)
    1  at least one producer is STALE, VACUOUS, missing (default), or unreadable
    2  a usage / argument error

Stdlib-only (mirrors the other stdlib ops scripts) so it runs on a bare
GitHub-hosted runner with no repo install.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Daily producer → allow 2 missed runs before we call it stale. Generous enough
# that a single skipped cron (or a slow FRED publish) is not a false alarm, tight
# enough that a genuinely-dead producer surfaces within ~2 days.
DEFAULT_MAX_AGE_HOURS = 48.0

# Authoritative registry of the SCHEDULED (cron) producers. Each entry asserts
# freshness (max_age_hours) AND latest-batch vacuity (value_key / min_inputs):
#   value_key  — dotted key on a row that must be present + non-null for the row
#                to count as a load-bearing input in the newest batch. None ⇒
#                every newest-batch row counts (mere presence of the batch).
#   min_inputs — floor of load-bearing rows the newest batch must carry; below it
#                the latest run is VACUOUS. It is a "measured *something*" floor,
#                NOT a statistical-power bar (that lives in each artifact's own
#                min_honest_n).
PRODUCERS: tuple[dict[str, Any], ...] = (
    {
        "path": "comms/macro/valuation_snapshots.jsonl",
        "max_age_hours": DEFAULT_MAX_AGE_HOURS,
        "value_key": "value",
        "min_inputs": 1,
        "label": "daily FRED valuation snapshot (macro-valuation-snapshot.yml)",
    },
    {
        "path": "comms/macro/econ_calendar_snapshots.jsonl",
        "max_age_hours": DEFAULT_MAX_AGE_HOURS,
        "value_key": "event_name",
        "min_inputs": 1,
        "label": "daily PIT economic-calendar snapshot (econ-calendar-produce.yml)",
    },
)


def _parse_iso_utc(raw: str) -> datetime | None:
    """Parse an ISO-8601 stamp to an aware UTC datetime; None if unparseable."""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    # Normalise a trailing Z to +00:00 for fromisoformat.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dotted_get(obj: Any, dotted: str) -> Any:
    """Fetch a value by a dotted path; None if any segment is missing."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def scan_ledger(
    path: Path, value_key: Optional[str]
) -> tuple[Optional[datetime], int, int, int]:
    """Scan an append-only ledger in one pass.

    Returns ``(newest_observed_at, total_rows, newest_batch_rows,
    newest_batch_loadbearing)``:

    * ``newest_observed_at`` — max parseable ``observed_at`` across all rows
      (append-only ledgers are not guaranteed sorted, so we scan for the max
      rather than trust the last line); None if no row carries a parseable stamp.
    * ``newest_batch_rows`` — count of rows sharing that exact newest stamp (one
      producer run appends a batch under a single ``observed_at``).
    * ``newest_batch_loadbearing`` — of those, how many carry a non-null
      ``value_key`` (or all of them when ``value_key`` is None).

    A row with no / unparseable ``observed_at`` contributes to ``total_rows`` but
    to no batch.
    """
    parsed: list[tuple[datetime, bool]] = []
    rows = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            dt = _parse_iso_utc(obj.get("observed_at", ""))
            if dt is None:
                continue
            load_bearing = (
                True if value_key is None else _dotted_get(obj, value_key) is not None
            )
            parsed.append((dt, load_bearing))

    if not parsed:
        return None, rows, 0, 0

    newest = max(dt for dt, _ in parsed)
    batch = [lb for dt, lb in parsed if dt == newest]
    return newest, rows, len(batch), sum(1 for lb in batch if lb)


def check_ledger(
    path: Path,
    max_age_hours: float,
    *,
    now: datetime,
    allow_missing: bool,
    value_key: Optional[str] = None,
    min_inputs: int = 1,
) -> dict:
    """Evaluate one producer ledger. Returns a verdict dict (never raises on IO)."""
    result: dict = {
        "ledger": str(path),
        "max_age_hours": max_age_hours,
        "present": path.exists(),
        "rows": 0,
        "newest_observed_at": None,
        "age_hours": None,
        "value_key": value_key,
        "min_inputs": min_inputs,
        "newest_batch_rows": None,
        "newest_batch_inputs": None,
        "status": "unknown",
        "detail": "",
    }
    if not path.exists():
        result["status"] = "missing_ok" if allow_missing else "missing"
        result["detail"] = f"ledger not found: {path}"
        return result
    try:
        newest, rows, batch_rows, batch_inputs = scan_ledger(path, value_key)
    except OSError as exc:
        result["status"] = "unreadable"
        result["detail"] = f"read error: {exc}"
        return result
    result["rows"] = rows
    if newest is None:
        result["status"] = "no_timestamp"
        result["detail"] = (
            f"{rows} row(s) but no parseable observed_at — cannot judge freshness"
        )
        return result
    age_hours = (now - newest).total_seconds() / 3600.0
    result["newest_observed_at"] = newest.isoformat(timespec="seconds")
    result["age_hours"] = round(age_hours, 2)
    result["newest_batch_rows"] = batch_rows
    result["newest_batch_inputs"] = batch_inputs
    # STALENESS takes precedence — if the producer stopped firing, the vacuity of
    # its last (old) batch is moot; the headline is "the cron is dead."
    if age_hours > max_age_hours:
        result["status"] = "stale"
        result["detail"] = (
            f"newest row is {age_hours:.1f}h old "
            f"(threshold {max_age_hours:.0f}h) — producer cron may have stopped firing"
        )
        return result
    # Fresh — now assert the LATEST run measured something. `value_key` names the
    # load-bearing field; below the floor the producer fired but produced nothing.
    if batch_inputs < min_inputs:
        keydesc = f"non-null `{value_key}`" if value_key else "row"
        result["status"] = "vacuous"
        result["detail"] = (
            f"fresh ({age_hours:.1f}h old) but the newest batch has "
            f"{batch_inputs} {keydesc}(s) of {batch_rows} row(s) "
            f"(floor {min_inputs}) — producer fired but measured nothing"
        )
        return result
    result["status"] = "fresh"
    inputdesc = (
        f", {batch_inputs}/{batch_rows} load-bearing in latest batch"
        if value_key
        else f", latest batch {batch_rows} row(s)"
    )
    result["detail"] = f"newest row {age_hours:.1f}h old (≤ {max_age_hours:.0f}h){inputdesc}"
    return result


# ---------------------------------------------------------------------------
# CONSUMER-SIDE feed checks (DATA-FEEDS-NEWS-CALENDAR, 2026-10-26).
# This monitor used to watch only what producers WRITE: econ_calendar_snapshots.jsonl stayed
# fresh while config/economic_calendar.yaml - the file the live news layer READS - sat at its
# 2026-07-30 newest event. These watch the CONSUMED artifacts. Statuses: fresh | stale (looked,
# bad) | could_not_look (no verdict; printed, never folded into fresh).
# news N=12h: over the 999 inter-row gaps of the 1000-row news_decisions tail (2026-10-07..26)
# the median is 7 min and only 1 gap > 12h (9 > 6h). Population: that one VM log tail.
# ---------------------------------------------------------------------------
CALENDAR_REL = "config/economic_calendar.yaml"
CAPTURES_REL = "comms/macro/econ_calendar_captures"
MIN_HORIZON = timedelta(days=7)
MAX_REFRESH_AGE = timedelta(hours=36)
NEWS_MAX_GAP_H = 12.0
_EVENT_TIME = re.compile(r'time:\s*"([0-9T:\-]+Z?)"')
_CAPTURE_TS = re.compile(r"^[A-Za-z]{2,4}-(\d{8}T\d{6}Z)\.")


def _verdict(feed: str, status: str, detail: str) -> dict:
    return {"ledger": feed, "status": status, "detail": detail}


def check_calendar_horizon(path: Path, now: datetime) -> dict:
    feed = CALENDAR_REL + " [horizon]"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return _verdict(feed, "could_not_look", f"calendar unreadable: {type(exc).__name__}")
    times = [t for t in (_parse_iso_utc(m) for m in _EVENT_TIME.findall(text)) if t]
    if not times:
        return _verdict(feed, "stale", "calendar carries no events")
    newest = max(times)
    ahead = (newest - now).total_seconds() / 86400
    if ahead * 86400 < MIN_HORIZON.total_seconds():
        return _verdict(feed, "stale", f"newest event {newest.isoformat()} is {ahead:.1f}d ahead (< 7d)")
    return _verdict(feed, "fresh", f"newest event {newest.isoformat()} is {ahead:.1f}d ahead")


def check_calendar_refresh(captures_dir: Path, now: datetime) -> dict:
    feed = CAPTURES_REL + " [last successful refresh]"
    d = Path(captures_dir)
    if not d.is_dir():
        return _verdict(feed, "could_not_look", "captures dir absent")
    stamps = [datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
              for m in (_CAPTURE_TS.match(p.name) for p in d.iterdir()) if m]
    if not stamps:
        return _verdict(feed, "stale", "no captures")
    last = max(stamps)
    age = now - last
    hrs = age.total_seconds() / 3600
    if age > MAX_REFRESH_AGE:
        return _verdict(feed, "stale", f"last successful capture {last.isoformat()} is {hrs:.1f}h old (> 36h)")
    return _verdict(feed, "fresh", f"last successful capture {last.isoformat()} ({hrs:.1f}h old)")


def check_news(log_tail: Any, open_packages: Any, now: datetime, max_gap_h: float = NEWS_MAX_GAP_H) -> dict:
    feed = "runtime_logs/news_decisions.jsonl [diag log_file]"
    if not isinstance(log_tail, dict) or not log_tail.get("present"):
        return _verdict(feed, "could_not_look", "news_decisions log not readable (diag absent or log not present)")
    if not isinstance(open_packages, dict) or open_packages.get("db_state") != "read":
        return _verdict(feed, "could_not_look", "open packages not readable")
    crypto = sorted({str(p.get("symbol")) for p in open_packages.get("packages", [])
                     if str(p.get("symbol", "")).upper().endswith("USDT")})
    last = None
    for ln in log_tail.get("lines", []):
        try:
            t = _parse_iso_utc(json.loads(ln).get("ts"))
        except (ValueError, AttributeError):
            continue
        if t and (last is None or t > last):
            last = t
    if not crypto:
        return _verdict(feed, "fresh", "no crypto package open - nothing to be stale for")
    if last is None:
        return _verdict(feed, "could_not_look", "no parseable row in the log tail")
    gap_h = (now - last).total_seconds() / 3600
    if gap_h > max_gap_h:
        return _verdict(feed, "stale", f"no news_decisions row for {gap_h:.1f}h (> {max_gap_h:g}h) with crypto open: {','.join(crypto)}")
    return _verdict(feed, "fresh", f"last row {gap_h:.1f}h ago; crypto open: {','.join(crypto)}")


def _load_json(path: str | None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None


def _is_bad(status: str) -> bool:
    """A status that should drive a non-zero exit + an alert."""
    return status in {"stale", "vacuous", "missing", "unreadable", "no_timestamp"}


def _parse_ledger_arg(spec: str) -> tuple[str, float]:
    """Parse a ``PATH`` or ``PATH:MAX_AGE_HOURS`` --ledger value."""
    # rsplit on ':' once so a Windows-y path (unlikely here) or a path with no
    # colon still works; a trailing numeric field is the threshold.
    if ":" in spec:
        head, _, tail = spec.rpartition(":")
        try:
            return head, float(tail)
        except ValueError:
            # No numeric suffix — treat the whole thing as a path.
            return spec, DEFAULT_MAX_AGE_HOURS
    return spec, DEFAULT_MAX_AGE_HOURS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Macro-producer cron liveness + validity monitor (workplan §0.WS-5). "
            "Reports STALE when a scheduled producer's ledger stops growing, and "
            "VACUOUS when its latest run appended a batch that measured nothing."
        )
    )
    parser.add_argument(
        "--ledger",
        action="append",
        default=None,
        metavar="PATH[:MAX_AGE_HOURS]",
        help=(
            "Ad-hoc freshness-only probe of one ledger + optional per-ledger "
            f"staleness threshold in hours (default {DEFAULT_MAX_AGE_HOURS:.0f}). "
            "Repeatable. Overrides the registry (no vacuity assertion on an ad-hoc "
            "ledger — those are declared per-producer in the registry). Omit to "
            "check every registered scheduled producer."
        ),
    )
    parser.add_argument("--news-log-json", help="diag log_file?name=news_decisions JSON (consumer-side news check)")
    parser.add_argument("--open-packages-json", help="diag open_packages JSON (consumer-side news check)")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root that relative ledger paths resolve against (default: cwd).",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help=(
            "Treat a not-yet-created ledger as OK rather than a failure "
            "(for the pre-first-run window)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the verdict as JSON (for machine consumption / the workflow).",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root)
    now = datetime.now(timezone.utc)

    if args.ledger:
        # Ad-hoc freshness-only probes (no registry vacuity assertion).
        results = [
            check_ledger(
                root / rel,
                max_age,
                now=now,
                allow_missing=args.allow_missing,
            )
            for rel, max_age in (_parse_ledger_arg(spec) for spec in args.ledger)
        ]
    else:
        results = [
            check_ledger(
                root / prod["path"],
                prod["max_age_hours"],
                now=now,
                allow_missing=args.allow_missing,
                value_key=prod.get("value_key"),
                min_inputs=prod.get("min_inputs", 1),
            )
            for prod in PRODUCERS
        ]
        results += [
            check_calendar_horizon(root / CALENDAR_REL, now),
            check_calendar_refresh(root / CAPTURES_REL, now),
            check_news(_load_json(args.news_log_json), _load_json(args.open_packages_json), now),
        ]
    bad = [r for r in results if _is_bad(r["status"])]

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": now.isoformat(timespec="seconds"),
                    "ok": not bad,
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        for r in results:
            marker = "🚨" if _is_bad(r["status"]) else "⚠️" if r["status"] == "could_not_look" else "✅"
            print(f"{marker} {r['ledger']} [{r['status']}] — {r['detail']}")
        if bad:
            names = ", ".join(Path(r["ledger"]).name for r in bad)
            print(f"\nFAIL: {len(bad)} producer(s) need attention: {names}")
        else:
            print(f"\nOK: all {len(results)} producer ledger(s) fresh + non-vacuous")

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
