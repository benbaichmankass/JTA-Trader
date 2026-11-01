#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml (read-back + freshness step, runs after every backfill/refresh)
"""Read the ETF history store BACK and report depth + freshness per symbol/timeframe.

For every ``<SYM>/<tf>.parquet``: first bar, last bar, row count, calendar span in years, and GAPS.
Gap definition (stated, not implied): the symbol's trading DATES are compared with the reference symbol's (SPY by
default; the most liquid series, so a date SPY has and the symbol lacks is a hole, not a holiday). Reported as
``missing_dates_vs_ref`` and the count of intra-series gaps longer than ``--max-gap-days`` calendar days.

FRESHNESS: a series whose last bar is older than ``--stale-days`` calendar days (default 5: a long weekend plus a
day) is STALE. Exit 1 on any stale/missing series so the workflow turns red -- ONE flag; the pipeline itself keeps
running (no self-halt). ``--table`` prints the markdown depth table.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_etf_history import UNIVERSE, read_bars  # noqa: E402


def series_report(root: Path, sym: str, tf: str, ref_dates: set, max_gap_days: float, now: datetime) -> Dict[str, Any]:
    df = read_bars(root, sym, tf)
    if df.empty:
        return {"symbol": sym, "tf": tf, "rows": 0, "stale": True, "first": None, "last": None}
    ts = pd.to_datetime(df["timestamp"], utc=True)
    dates = set(ts.dt.date)
    gaps = ts.diff().dropna()
    first, last = ts.min(), ts.max()
    missing = sorted(d for d in ref_dates if first.date() <= d <= last.date() and d not in dates)
    age_days = (now - last.to_pydatetime()).total_seconds() / 86400.0
    return {"symbol": sym, "tf": tf, "rows": int(len(df)), "first": str(first), "last": str(last),
            "years": round((last - first).days / 365.25, 2),
            "long_gaps": int((gaps > pd.Timedelta(days=max_gap_days)).sum()),
            "missing_dates_vs_ref": len(missing), "age_days": round(age_days, 2), "stale": False}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="data/etf_history")
    ap.add_argument("--symbols", default=",".join(UNIVERSE))
    ap.add_argument("--tfs", default="1h,5m")
    ap.add_argument("--ref", default="SPY")
    ap.add_argument("--stale-days", type=float, default=5.0)
    ap.add_argument("--max-gap-days", type=float, default=5.0)
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args(argv)
    root, now = Path(a.root), datetime.now(timezone.utc)
    tfs = [t for t in a.tfs.split(",") if t]
    rows: List[Dict[str, Any]] = []
    bad: List[str] = []
    for tf in tfs:
        ref = read_bars(root, a.ref, tf)
        ref_dates = set(pd.to_datetime(ref["timestamp"], utc=True).dt.date) if len(ref) else set()
        for sym in [s for s in a.symbols.split(",") if s]:
            r = series_report(root, sym, tf, ref_dates, a.max_gap_days, now)
            if r["rows"] == 0 or r.get("age_days", 1e9) > a.stale_days:
                r["stale"] = True
                bad.append(f"{sym}/{tf}")
            rows.append(r)
    if a.table:
        print("| symbol | tf | rows | first | last | years | long_gaps | missing_dates_vs_ref | age_d | status |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            print(f"| {r['symbol']} | {r['tf']} | {r['rows']} | {str(r.get('first') or '—')[:16]} | {str(r.get('last') or '—')[:16]} | "
                  f"{r.get('years', '—')} | {r.get('long_gaps', '—')} | {r.get('missing_dates_vs_ref', '—')} | "
                  f"{r.get('age_days', '—')} | {'STALE/MISSING' if r['stale'] else 'ok'} |")
    print(f"series={len(rows)} stale_or_missing={len(bad)} {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
