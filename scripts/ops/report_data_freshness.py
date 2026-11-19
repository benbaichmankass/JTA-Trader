#!/usr/bin/env python3
# wiring: deploy/trainer/ict-candle-refresh.service (ExecStartPost, never fails the unit)
"""Report-only freshness of the trainer's data/*.csv candle and funding files.

``--alert-rostered`` (TRAINER-1D-STALE-ROSTERED, 2026-11-19) adds ONE red flag: when a ROSTERED symbol's 1d
file is stale or unreadable it enqueues one operator ping (at most one per ``ALERT_COOLDOWN_S``) and, with
``UNIT_FAILURE_FORWARD=live`` (the trainer), forwards it to the live VM's queue the same way the unit-failure
notifier does. Why: GDX/SCHA/USO froze in June/July 2026 and this reporter printed ``stale: true`` into a
journal nobody reads, so nothing fired for 4-5 months. An alert, never a gate: exit code stays 0.

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
import os
import re
import sys
import time
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


REPO_ROOT = Path(__file__).resolve().parents[2]
ALERT_COOLDOWN_S = 24 * 3600
#: rostered symbol -> trainer data/ file stem, where it differs (micro futures read their proxy's file).
_STEM = {"MGC": "GC_F", "MHG": "HG_F", "MES": "ES_F", "SPYM": "SPLG"}


def _strategies(repo: Path) -> dict:
    """``strategies.yaml``'s ``strategies:`` map (raises on an unreadable file; the caller reports it)."""
    import yaml  # noqa: PLC0415
    return (yaml.safe_load((repo / "config" / "strategies.yaml").read_text()) or {}).get("strategies") or {}


def rostered_symbols(repo: Path = REPO_ROOT) -> dict[str, set[str]] | None:
    """{symbol: {timeframes its rostered legs trade}} for every enabled leg on a configured account's roster;
    None = could not look. A symbol's 1d file is always watched too (HTF filters and daily harnesses read it)."""
    try:
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from src.config.accounts_loader import load_accounts_dict  # noqa: PLC0415  (the canonical accounts.yaml reader)
        accounts = load_accounts_dict(repo / "config" / "accounts.yaml")
        strategies = _strategies(repo)
    except (ImportError, OSError, ValueError, AttributeError) as exc:
        print(json.dumps({"alert": "rostered_symbols_unreadable", "error": repr(exc)[:200]}))
        return None
    if not accounts or not strategies:
        return None
    out: dict[str, set[str]] = {}
    for a in accounts.values():
        if not isinstance(a, dict) or a.get("configured") is False:
            continue
        for leg in a.get("strategies") or []:
            c = strategies.get(leg)
            if isinstance(c, dict) and c.get("enabled") is not False:
                for s in c.get("symbols") or []:
                    out.setdefault(str(s), set()).update({"1d", str(c.get("timeframe") or "1h")})
    return out


def stale_rostered(rows: list[dict], symbols) -> list[dict]:
    """Rows for a rostered symbol's 1d file OR the timeframe its legs trade (``symbols`` is the
    rostered_symbols() mapping; a bare set means 1d only) that are stale or unreadable. A missing file is not
    a row here. TRAINER-1D-STALE-ROSTERED: USO_1h (uso_trend_1h) froze at 2026-06-18 unseen, like the 1d files."""
    tfs = symbols if isinstance(symbols, dict) else {s: {"1d"} for s in symbols}
    want = {(_STEM.get(s, s.replace("=", "_")), tf) for s, v in tfs.items() for tf in (v | {"1d"})}
    out = []
    for r in rows:
        stem = r["file"].removesuffix(".csv")
        sym, _, tf = stem.rpartition("_")
        if (sym, r["grain"]) in want and tf == r["grain"] and (r["stale"] or r["read_state"] != "ok"):
            out.append(r)
    return out


def alert(bad: list[dict], logs: Path, now: float) -> str:
    """'pinged' | 'suppressed' | 'clean'. One ping per cooldown for the whole set; never raises."""
    if not bad:
        return "clean"
    state_path = logs / "data_freshness_alert_state.json"
    try:
        last = float(json.loads(state_path.read_text()).get("last_ping", 0))
    except (OSError, ValueError, AttributeError):
        last = 0.0
    if now - last < ALERT_COOLDOWN_S:
        return "suppressed"
    files = ", ".join(f"{r['file']} (last {str(r['last_bar'])[:10]})" for r in bad[:12])
    try:
        logs.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"last_ping": now, "files": [r["file"] for r in bad]}))
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from scripts.send_ping import enqueue  # noqa: PLC0415
        path = enqueue(f"[WARN] trainer data stale for ROSTERED symbols: {files}. Backtests and ML datasets "
                       f"reading these files are truncated. Fix: the lake build + extend_data_from_lake.py "
                       f"NAME_MAP (TRAINER-1D-STALE-ROSTERED).", priority="high")
        if os.environ.get("UNIT_FAILURE_FORWARD", "").strip().lower() == "live":
            from scripts.ops.notify_unit_failure import forward_to_live  # noqa: PLC0415
            forward_to_live(Path(path), logs)
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({"alert": "ping_failed", "error": repr(exc)[:200]}))
        return "ping_failed"
    return "pinged"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--alert-rostered", action="store_true",
                    help="ping once per 24h when a rostered symbol's 1d file is stale (an alert, never a gate)")
    args = ap.parse_args(argv)
    rows = report(Path(args.data_dir))
    for r in rows:
        print(json.dumps(r, sort_keys=True))
    stale = [r["file"] for r in rows if r["stale"]]
    unread = [r["file"] for r in rows if r["read_state"] != "ok"]
    print(json.dumps({"summary": True, "files": len(rows), "stale": len(stale),
                      "unreadable": len(unread), "stale_files": stale}, sort_keys=True))
    if args.alert_rostered:
        syms = rostered_symbols()
        if syms is None:
            print(json.dumps({"alert": "rostered_symbols_unreadable"}))   # could not look: said, never 'clean'
        else:
            bad = stale_rostered(rows, syms)
            logs = REPO_ROOT / "runtime_logs"
            try:
                from src.utils.paths import runtime_logs_dir  # noqa: PLC0415
                logs = runtime_logs_dir()
            except ImportError:
                pass
            print(json.dumps({"alert": alert(bad, logs, time.time()), "stale_rostered": [r["file"] for r in bad]}))
    return 0  # report-only: never a gate


if __name__ == "__main__":
    sys.exit(main())
