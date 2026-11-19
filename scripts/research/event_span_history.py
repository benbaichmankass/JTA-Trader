#!/usr/bin/env python3
# wiring: row EVENT-SPAN-HISTORY -> research/queue RQ-20261118-a5b3-01 / -02 (via comms/research/event_span_history/)
"""EVENT-SPAN-HISTORY: a committed point-in-time US release history (fomc_decision, fomc_minutes, cpi, nfp), UTC.

Built from the committed calendar snapshots (comms/macro/econ_calendar_snapshots.jsonl = the live collector,
comms/macro/econ_calendar_snapshots_survey_backfill.jsonl = the survey backfill), one row per release:
    {"class", "date", "release_utc", "source", "derived", "basis"}
  * fomc_decision <- kind `fomc`; cpi <- kind `cpi_mom`; nfp <- kind `nfp` (scheduled_at, UTC, as the source states it).
  * fomc_minutes: the live collector holds only 2026-07 onward, so each minutes release is DERIVED as its decision date
    + 21 days at 14:00 America/New_York (the Fed's practice since 2005), marked derived=true. The rule is checked against
    every OBSERVED minutes row: build() refuses (exit 1) if any observed row disagrees, so a schedule change cannot pass
    silently. MEASURED 2026-11-19: 4 of 4 observed minutes match, across a DST change (18:00Z and 19:00Z).
Only releases at or before --asof are written (the snapshots also hold scheduled future dates).

    python3 scripts/research/event_span_history.py --self-test
    python3 scripts/research/event_span_history.py build --asof 2026-11-19 --out comms/research/event_span_history/us_releases.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
SNAPSHOTS = ["comms/macro/econ_calendar_snapshots.jsonl", "comms/macro/econ_calendar_snapshots_survey_backfill.jsonl"]
KIND_TO_CLASS = {"fomc": "fomc_decision", "cpi_mom": "cpi", "nfp": "nfp"}
START = "2021-01-01"
MINUTES_LAG_DAYS = 21


def derive_minutes(decision_date: str) -> str:
    d = datetime.fromisoformat(decision_date) + timedelta(days=MINUTES_LAG_DAYS)
    et = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    return et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(lines: Iterable[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{class: {date: row}} over every snapshot line; the first row with a scheduled_at wins per (class, date)."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {"fomc_decision": {}, "cpi": {}, "nfp": {}, "fomc_minutes_observed": {}}
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        k = r.get("kind")
        cls = KIND_TO_CLASS.get(k) or ("fomc_minutes_observed" if k == "fomc_minutes" else None)
        at = r.get("scheduled_at")
        d = r.get("scheduled_for") or (at or "")[:10]
        if not cls or not at or not d:
            continue
        if d not in out[cls]:
            out[cls][d] = {"release_utc": at.replace("+00:00", "Z"), "source": r.get("source") or r.get("expectation_source")}
    return out


def build_rows(col: Dict[str, Dict[str, Dict[str, Any]]], asof: str) -> List[Dict[str, Any]]:
    rows = []
    for cls in ("fomc_decision", "cpi", "nfp"):
        for d, x in col[cls].items():
            if START <= d <= asof:
                rows.append({"class": cls, "date": d, "release_utc": x["release_utc"], "source": x["source"], "derived": False,
                             "basis": "calendar snapshot scheduled_at"})
    bad = []
    for d, x in col["fomc_minutes_observed"].items():
        prior = [p for p in col["fomc_decision"] if p < d]
        if not prior or derive_minutes(max(prior))[:16] != x["release_utc"][:16]:
            bad.append((d, x["release_utc"], derive_minutes(max(prior)) if prior else None))
    if bad:
        raise SystemExit(f"fomc_minutes derivation disagrees with observed rows: {bad}")
    for d in col["fomc_decision"]:
        m = derive_minutes(d)
        if START <= m[:10] <= asof:
            obs = col["fomc_minutes_observed"].get(m[:10])
            rows.append({"class": "fomc_minutes", "date": m[:10], "release_utc": m, "source": (obs or {}).get("source") or "derived",
                         "derived": obs is None, "basis": f"decision {d} + {MINUTES_LAG_DAYS} d at 14:00 America/New_York"
                                                          + ("" if obs is None else " (matches the observed row)")})
    return sorted(rows, key=lambda r: (r["release_utc"], r["class"]))


def build(asof: str, out: Path) -> Dict[str, Any]:
    lines: List[str] = []
    for f in SNAPSHOTS:
        lines += (REPO / f).read_text(encoding="utf-8").splitlines()
    col = collect(lines)
    rows = build_rows(col, asof)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    return {"rows": len(rows), "by_class": counts, "observed_minutes_checked": len(col["fomc_minutes_observed"]), "out": str(out)}


def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    check("minutes derive to decision + 21 d at 14:00 ET (EDT -> 18:00Z)", derive_minutes("2026-06-17") == "2026-07-08T18:00:00Z")
    check("minutes derive across DST (EST -> 19:00Z)", derive_minutes("2026-10-28") == "2026-11-18T19:00:00Z")
    lines = [json.dumps(x) for x in [
        {"kind": "fomc", "scheduled_for": "2026-06-17", "scheduled_at": "2026-06-17T18:00:00Z", "source": "s"},
        {"kind": "fomc", "scheduled_for": "2026-06-17", "scheduled_at": "2026-06-17T18:00:00Z", "source": "dup"},
        {"kind": "cpi_mom", "scheduled_for": "2026-07-14", "scheduled_at": "2026-07-14T12:30:00Z", "source": "s"},
        {"kind": "fomc_minutes", "scheduled_for": "2026-07-08", "scheduled_at": "2026-07-08T18:00:00Z", "source": "s"},
        {"kind": "nfp", "scheduled_for": "2027-01-01", "scheduled_at": "2027-01-01T13:30:00Z", "source": "s"},
        {"kind": "ppi_mom", "scheduled_for": "2026-07-15", "scheduled_at": "2026-07-15T12:30:00Z"}]]
    rows = build_rows(collect(lines), "2026-11-19")
    check("deduped, classes mapped, unrelated kinds dropped, future dropped",
          sorted((r["class"], r["date"]) for r in rows) == [("cpi", "2026-07-14"), ("fomc_decision", "2026-06-17"), ("fomc_minutes", "2026-07-08")])
    check("an observed minutes row is marked not derived", [r for r in rows if r["class"] == "fomc_minutes"][0]["derived"] is False)
    bad = lines + [json.dumps({"kind": "fomc_minutes", "scheduled_for": "2026-07-09", "scheduled_at": "2026-07-09T18:00:00Z"})]
    try:
        build_rows(collect(bad), "2026-11-19")
        check("a disagreeing observed minutes row refuses the build", False)
    except SystemExit:
        check("a disagreeing observed minutes row refuses the build", True)
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("--asof", required=True)
    b.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "build":
        ap.error("build or --self-test")
    print(json.dumps(build(a.asof, Path(a.out))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
