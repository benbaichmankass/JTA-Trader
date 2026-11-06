#!/usr/bin/env python3
"""S2 importer + shadow parity for the work store (row WSD-S2-IMPORTER-PARITY).

Design: docs/plans/WORK-STORE-DESIGN-2026-11.md § 4 steps 1-2. Logic lives in
``src/runtime/work_store_import.py``; this is the CLI and the VM timer's entry point.

    python3 scripts/ops/work_store_import.py --dry-run          # import into a scratch copy, print counts + parity
    python3 scripts/ops/work_store_import.py --apply            # the timer: import into work_store.db, append parity
    python3 scripts/ops/work_store_import.py --summary [--hours 48]   # the shadow window, from the parity log

``--apply`` is ONE-WAY (files -> store) and never writes a file under docs/. Its parity report is
appended to ``runtime_logs/work_store_parity.jsonl`` (and ``work_store_parity_latest.json``), served by
``GET /api/bot/work/parity``. A failed run writes a report with ``readState: could_not_look`` -- it is
never read as clean -- and exits 1 so the unit shows failed; the next timer tick tries again (no halting).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime import work_store as ws  # noqa: E402
from src.runtime import work_store_import as wi  # noqa: E402

LOG_NAME = "work_store_parity.jsonl"
LATEST_NAME = "work_store_parity_latest.json"
#: The design's closing window: 2 days of clean parity.
WINDOW_HOURS = 48
#: The timer fires every 5 min; a window is only "covered" if the runs actually happened.
EXPECTED_RUNS_PER_HOUR = 12


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head(repo: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip() or None
    except Exception:  # noqa: BLE001 -- provenance only; None is "could not look"
        return None


def log_dir() -> Path:
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir())


def run(repo: Path, db_path: str, *, today=None) -> dict:
    t0 = time.monotonic()
    report: dict = {"at": _now(), "head_sha": _head(repo), "db": db_path}
    try:
        store = ws.WorkStore(db_path)
        src = wi.read_sources(repo)
        report["import"] = wi.run_import(repo, store, src)
        par = wi.parity(repo, store, src, today=today)
        report.update(par)
        report["readState"] = "read"
    except Exception as exc:  # allow-silent: not silent -- the report carries the error + traceback and readState could_not_look; exit 1
        report.update(readState="could_not_look", clean=False, error=f"{type(exc).__name__}: {exc}",
                      traceback=traceback.format_exc()[-4000:])
    report["duration_s"] = round(time.monotonic() - t0, 2)
    return report


def append_report(report: dict, out_dir: Path | None = None) -> None:
    out_dir = out_dir or log_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(report, sort_keys=True, separators=(",", ":"))
    with open(out_dir / LOG_NAME, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    tmp = out_dir / (LATEST_NAME + ".tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out_dir / LATEST_NAME)


def summarize(lines: list[dict], *, hours: int = WINDOW_HOURS, now: datetime | None = None) -> dict:
    """The shadow window: every run in the last ``hours``, how many were clean, and the
    current clean streak. ``window_clean`` needs EVERY run clean AND the runs to cover the
    window (a timer that stopped is not a clean window)."""
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(hours=hours)

    def ts(r):
        try:
            return datetime.strptime(r["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    runs = [r for r in lines if (t := ts(r)) is not None and t >= cut]
    unclean = [r for r in runs if not r.get("clean")]
    streak_start = None
    for r in reversed([r for r in lines if ts(r) is not None]):
        if not r.get("clean"):
            break
        streak_start = r["at"]
    first = min((ts(r) for r in runs), default=None)
    expected = hours * EXPECTED_RUNS_PER_HOUR
    covered = bool(first and first <= cut + timedelta(minutes=15) and len(runs) >= 0.9 * expected)
    return {
        "window_hours": hours, "runs": len(runs), "expected_runs": expected, "clean_runs": len(runs) - len(unclean),
        "unclean_runs": len(unclean),
        "unclean_sample": [{"at": r.get("at"), "readState": r.get("readState"), "error": r.get("error"),
                            "rows_differing": (r.get("rows") or {}).get("differing_count"),
                            "items_differing": (r.get("items") or {}).get("differing_count"),
                            "appendix_equal": (r.get("appendix_a") or {}).get("equal")} for r in unclean[-10:]],
        "clean_streak_since": streak_start, "window_covered": covered,
        "window_clean": bool(covered and not unclean),
    }


def read_log(out_dir: Path | None = None) -> list[dict]:
    path = (out_dir or log_dir()) / LOG_NAME
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            out.append({"at": None, "clean": False, "readState": "unreadable_line"})
    return out


def _short(report: dict) -> dict:
    keep = ("at", "head_sha", "readState", "clean", "duration_s", "import", "chain", "error",
            "native_db_only", "pipeline_unreadable", "pipeline_collisions")
    out = {k: report.get(k) for k in keep if k in report}
    for k in ("rows", "items"):
        if k in report:
            out[k] = {kk: report[k][kk] for kk in report[k] if kk not in ("differing", "missing_in_db", "db_only")}
            out[k]["differing_sample"] = report[k]["differing"][:5]
    if "appendix_a" in report:
        out["appendix_a"] = report["appendix_a"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="import into a scratch COPY of the store (or an empty one) and print the parity; writes nothing live")
    g.add_argument("--apply", action="store_true", help="import into work_store.db and append the parity report")
    g.add_argument("--summary", action="store_true", help="print the shadow-window summary from the parity log")
    ap.add_argument("--db", help="store path (default: src.utils.paths.work_store_db_path())")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--hours", type=int, default=WINDOW_HOURS)
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    if a.summary:
        print(json.dumps(summarize(read_log(), hours=a.hours), indent=1))
        return 0

    from src.utils.paths import work_store_db_path
    live = a.db or work_store_db_path()
    if a.dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = str(Path(tmp) / "work_store.db")
            if Path(live).is_file():
                # sqlite's own backup API: a consistent copy even while the live API writes.
                import sqlite3
                src_c, dst_c = sqlite3.connect(live), sqlite3.connect(scratch)
                with dst_c:
                    src_c.backup(dst_c)
                src_c.close()
                dst_c.close()
            report = run(repo, scratch)
        report["dry_run"] = True
        report["db"] = f"scratch copy of {live}" if Path(live).is_file() else "empty scratch store"
        print(json.dumps(_short(report), indent=1))
        return 0 if report.get("readState") == "read" else 1

    report = run(repo, live)
    append_report(report)
    print(json.dumps(_short(report), sort_keys=True))
    return 0 if report.get("readState") == "read" else 1


if __name__ == "__main__":
    raise SystemExit(main())
