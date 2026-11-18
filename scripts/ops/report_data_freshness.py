#!/usr/bin/env python3
# wiring: deploy/trainer/ict-candle-refresh.service (ExecStartPost, never fails the unit)
"""Report-only freshness of the trainer's data/*.csv candle and funding files.

PI-20261118-MANAYJZO-0002 step 3. Prints one JSON line per file (last bar, age
in days, stale flag) and a summary line. It REPORTS and never gates: exit code
is always 0, no unit is skipped on a stale flag. A file whose last bar cannot be
read is reported as ``read_state: unreadable`` with ``last_bar: null`` (never as
age 0).

    python3 scripts/ops/report_data_freshness.py --data-dir data
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# A file is flagged stale when its last bar is older than this many days.
# 1d series tolerate a weekend + holiday; intraday and funding do not.
_STALE_DAYS = {"5m": 2.0, "15m": 2.0, "1h": 2.0, "4h": 3.0, "1d": 5.0}
_DEFAULT_STALE_DAYS = 3.0
_GRAIN = re.compile(r"_(\d+[mhd])(?:_|\.csv$)")


def _last_data_line(path: Path) -> str | None:
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        step = min(size, 4096)
        fh.seek(size - step)
        lines = [ln for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-1] if len(lines) >= 2 else None


def _parse_ts(cell: str) -> datetime | None:
    cell = cell.strip().strip('"')
    try:
        if cell.replace(".", "", 1).isdigit():
            v = float(cell)
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
        dt = datetime.fromisoformat(cell.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def report(data_dir: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for path in sorted(data_dir.glob("*.csv")):
        m = _GRAIN.search(path.name)
        if not m and "funding" not in path.name and "multiyear" not in path.name:
            continue
        grain = m.group(1) if m else "other"
        limit = _STALE_DAYS.get(grain, _DEFAULT_STALE_DAYS)
        row = {"file": path.name, "grain": grain, "stale_after_days": limit}
        try:
            line = _last_data_line(path)
            ts = _parse_ts(line.split(",")[0]) if line else None
        except OSError:
            ts = None
        if ts is None:
            row.update(read_state="unreadable", last_bar=None, age_days=None, stale=None)
        else:
            age = (now - ts).total_seconds() / 86400
            row.update(read_state="ok", last_bar=ts.isoformat(), age_days=round(age, 2), stale=age > limit)
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args(argv)
    rows = report(Path(args.data_dir))
    for r in rows:
        print(json.dumps(r, sort_keys=True))
    stale = [r["file"] for r in rows if r["stale"]]
    unread = [r["file"] for r in rows if r["read_state"] != "ok"]
    print(json.dumps({"summary": True, "files": len(rows), "stale": len(stale),
                      "unreadable": len(unread), "stale_files": stale}, sort_keys=True))
    return 0  # report-only: never a gate


if __name__ == "__main__":
    sys.exit(main())
