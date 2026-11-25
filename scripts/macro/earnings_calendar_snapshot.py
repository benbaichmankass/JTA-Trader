#!/usr/bin/env python3
# wiring: .github/workflows/earnings-calendar-snapshot.yml (daily, off-VM); row DESK-MACRO-DAILY (spec section 4, the earnings-calendar gap)
"""Earnings calendar, POINT-IN-TIME: append today's view of the next N days' earnings to an append-only JSONL.

Tier 1 observability producer (macro-research invariants): off-VM only (refuses without ICT_OFFVM_BUILD_HOST), keyless source probed
first (Nasdaq `api.nasdaq.com/api/calendar/earnings?date=`; fixture comms/macro/earnings_calendar_probe_20261125/), append-only with
`observed_at` (a changed consensus is a NEW line, never an edit), idempotent (an unchanged row for the same symbol + report date is
not re-appended). History from this source is NOT treated as point-in-time consensus (unverified); the forward snapshots are.

  ICT_OFFVM_BUILD_HOST=1 python3 scripts/macro/earnings_calendar_snapshot.py --days 7 [--out comms/macro/earnings_calendar_snapshots.jsonl]
  python3 scripts/macro/earnings_calendar_snapshot.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "comms" / "macro" / "earnings_calendar_snapshots.jsonl"
URL = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
UA = "Mozilla/5.0 (research; jta-trader earnings snapshot)"
KEEP = ("symbol", "name", "time", "epsForecast", "noOfEsts", "eps", "surprise", "marketCap", "fiscalQuarterEnding")


def fetch_day(d: date, get=None) -> list[dict]:
    """One report date's rows from the Nasdaq calendar (retried); raises after the last attempt."""
    if get is None:
        import requests
        get = lambda url: requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)  # noqa: E731
    last = None
    for wait in (0, 2, 5, 10):
        time.sleep(wait)
        try:
            r = get(URL.format(d=d.isoformat()))
            r.raise_for_status()
            return list(((r.json().get("data") or {}).get("rows")) or [])
        except Exception as e:  # noqa: BLE001  # allow-silent: retried with backoff; the final failure raises below
            last = e
    raise RuntimeError(f"nasdaq earnings fetch failed for {d}: {last}")


def rows_for(d: date, raw: list[dict], observed_at: str) -> list[dict]:
    return [{"report_date": d.isoformat(), "observed_at": observed_at, "source": "nasdaq_calendar",
             **{k: (r.get(k) if r.get(k) not in ("", "N/A") else None) for k in KEEP}} for r in raw if r.get("symbol")]


def _key(r: dict) -> tuple:
    return (r["symbol"], r["report_date"])


def _payload(r: dict) -> tuple:
    return tuple(r.get(k) for k in KEEP)


def append_new(path: Path, rows: list[dict]) -> int:
    """Append rows whose (symbol, report_date) payload differs from the LAST observation already in the log. Returns the count added."""
    last: dict[tuple, tuple] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                o = json.loads(line)
                last[_key(o)] = _payload(o)
    new = [r for r in rows if last.get(_key(r)) != _payload(r)]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for r in new:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    return len(new)


def run(days: int, out: Path, today: date | None = None, get=None) -> dict:
    if os.environ.get("ICT_OFFVM_BUILD_HOST") != "1":
        raise SystemExit("off-VM only: set ICT_OFFVM_BUILD_HOST=1 on a runner (macro-research invariant 1)")
    today = today or datetime.now(timezone.utc).date()
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, failed = [], []
    for i in range(days + 1):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            rows += rows_for(d, fetch_day(d, get), observed_at)
        except RuntimeError as e:
            failed.append(str(e))
    added = append_new(out, rows)
    return {"observed_at": observed_at, "days": days, "rows_seen": len(rows), "rows_added": added, "failed_days": failed}


def self_test() -> int:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + name)
    fx = json.loads((REPO / "comms/macro/earnings_calendar_probe_20261125/nasdaq_calendar_2026-11-24.json").read_text())

    class R:
        def __init__(self, rows):
            self._rows = rows

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"rows": self._rows}}
    rows = rows_for(date(2026, 11, 24), fx["rows_sample"], "2026-11-25T12:30:00Z")
    check("rows carry report_date, observed_at and the kept fields", rows and all(set(KEEP) <= set(r) and r["observed_at"] for r in rows))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "e.jsonl"
        check("first append adds every row", append_new(p, rows) == len(rows))
        check("an identical re-run adds nothing (idempotent)", append_new(p, rows) == 0)
        changed = [dict(rows[0], epsForecast="$9.99", observed_at="2026-11-25T13:30:00Z")]
        check("a changed consensus is a NEW line, never an edit", append_new(p, changed) == 1 and len(p.read_text().splitlines()) == len(rows) + 1)
        os.environ["ICT_OFFVM_BUILD_HOST"] = "1"
        res = run(2, Path(td) / "r.jsonl", today=date(2026, 11, 23), get=lambda url: R(fx["rows_sample"]))
        check("run skips weekends and appends", res["rows_added"] > 0 and not res["failed_days"])
        os.environ.pop("ICT_OFFVM_BUILD_HOST")
        try:
            run(1, Path(td) / "x.jsonl", get=lambda url: R([]))
            check("refuses to run without ICT_OFFVM_BUILD_HOST", False)
        except SystemExit:
            check("refuses to run without ICT_OFFVM_BUILD_HOST", True)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    res = run(a.days, Path(a.out))
    print(json.dumps(res))
    return 0 if not res["failed_days"] or res["rows_seen"] else 1


if __name__ == "__main__":
    sys.exit(main())
