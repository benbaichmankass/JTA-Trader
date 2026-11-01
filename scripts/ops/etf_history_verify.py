#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml (read-back + freshness step, runs after every backfill/refresh)
"""Depth + freshness read-back of the ETF/equity bar store, from its MANIFEST (never needs the multi-GB store on the runner).

Per expected series (universe symbols x timeframes): status, first bar, last bar, rows, years, long gaps (> 5 days between
consecutive bars), age. The expected set is config/data_universe.yaml -- so a symbol the pipeline never collected is
``MISSING``, not silently absent.

Verdicts (one flag, never a halt):
  * STALE     : status ok, last bar older than ``--stale-days`` (default 5) -- EXCEPT delisted S&P 500 names, whose series
                legitimately end (``ended``).
  * NO_DATA   : the vendor serves nothing for it (typo / delisted / not listed on the feed). Red for a symbol we expect to be live
                (core / ETFs / current S&P 500 members) so the config can be edited; informational for removed S&P 500 names.
  * MISSING   : in the universe but not in the manifest. Red, except with ``--progress`` (a backfill still running).
Exit 1 on any red. ``--table`` prints the depth table (``--all`` for every series, default the core set); the summary always prints.

``--deep`` additionally re-reads year files under ``--root`` (when present) to check each manifest row count against the data and to
count dates present in SPY but missing from a symbol (the "missing sessions" gap measure). Use it where the store is local (trainer).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_universe as du  # noqa: E402


def _age_days(last: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 86400.0


def classify(u: Dict[str, Any], manifest: Dict[str, Any], tfs: List[str], now: datetime, stale_days: float,
             progress: bool) -> List[Dict[str, Any]]:
    syms = du.equity_symbols(u)
    removed = set(du.delisted_symbols(u))
    etf_like = set(syms) - removed
    rows = []
    for tf in tfs:
        for sym in syms:
            m = (manifest.get("series") or {}).get(f"{sym}/{tf}")
            r: Dict[str, Any] = {"symbol": sym, "tf": tf, "removed": sym in removed}
            if not m:
                r.update(verdict="PENDING" if progress else "MISSING", red=not progress)
            elif m.get("status") == "no_data":
                r.update(verdict="NO_DATA", red=sym in etf_like)
            else:
                age = _age_days(m["last"], now)
                ended = sym in removed
                stale = age > stale_days and not ended
                r.update(rows=m["rows"], first=m["first"], last=m["last"], years=round(
                    (datetime.fromisoformat(m["last"].replace("Z", "+00:00")) - datetime.fromisoformat(m["first"].replace("Z", "+00:00"))).days / 365.25, 2),
                    long_gaps=m.get("long_gaps"), age_days=round(age, 2), feed=m.get("feed"),
                    verdict="STALE" if stale else ("ended" if age > stale_days else "ok"), red=stale)
            rows.append(r)
    return rows


def summarize(rows: List[Dict[str, Any]], tfs: List[str]) -> List[str]:
    out = []
    for tf in tfs:
        rs = [r for r in rows if r["tf"] == tf]
        ok = [r for r in rs if "rows" in r]
        counts: Dict[str, int] = {}
        for r in rs:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        if ok:
            ys = sorted(r["years"] for r in ok)
            feeds = sorted({r["feed"] for r in ok})
            out.append(f"[{tf}] series={len(rs)} {counts} | with data={len(ok)} years min/median/max={ys[0]}/{statistics.median(ys)}/{ys[-1]} "
                       f"| total rows={sum(r['rows'] for r in ok):,} | feeds={feeds}")
        else:
            out.append(f"[{tf}] series={len(rs)} {counts} | with data=0")
    return out


def table(rows: List[Dict[str, Any]]) -> List[str]:
    out = ["| symbol | tf | rows | first | last | years | long_gaps | age_d | feed | verdict |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['symbol']} | {r['tf']} | {r.get('rows', '—')} | {str(r.get('first') or '—')[:10]} | {str(r.get('last') or '—')[:16]} | "
                   f"{r.get('years', '—')} | {r.get('long_gaps', '—')} | {r.get('age_days', '—')} | {r.get('feed', '—')} | {r['verdict']} |")
    return out


def deep(root: Path, rows: List[Dict[str, Any]], ref: str = "SPY") -> List[str]:
    """Where the store is local: recount rows from the year files and count dates SPY has that the symbol lacks."""
    import pandas as pd
    from fetch_etf_history import read_bars

    msgs = []
    for tf in sorted({r["tf"] for r in rows}):
        rb = read_bars(root, ref, tf)
        ref_dates = set(pd.to_datetime(rb["timestamp"], utc=True).dt.date) if len(rb) else set()
        for r in rows:
            if r["tf"] != tf or "rows" not in r:
                continue
            df = read_bars(root, r["symbol"], tf)
            if len(df) != r["rows"]:
                msgs.append(f"DEEP rowcount mismatch {r['symbol']}/{tf}: manifest {r['rows']} vs data {len(df)}")
            if len(df) and ref_dates:
                ds = set(pd.to_datetime(df["timestamp"], utc=True).dt.date)
                lo, hi = min(ds), max(ds)
                r["missing_dates_vs_ref"] = sum(1 for d in ref_dates if lo <= d <= hi and d not in ds)
    return msgs


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="data/etf_history")
    ap.add_argument("--universe", default=None)
    ap.add_argument("--tfs", default=None)
    ap.add_argument("--stale-days", type=float, default=5.0)
    ap.add_argument("--progress", action="store_true", help="a backfill is in progress: an uncollected series is PENDING, not red")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--all", action="store_true", help="with --table: every series, not just the core set")
    ap.add_argument("--deep", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    u = du.load(a.universe)
    tfs = [t for t in a.tfs.split(",") if t] if a.tfs else list((u.get("us_equity_bars") or {}).get("timeframes") or ["1h", "5m"])
    mp = root / "MANIFEST.json"
    manifest = json.loads(mp.read_text()) if mp.exists() else {"series": {}}
    now = datetime.now(timezone.utc)
    rows = classify(u, manifest, tfs, now, a.stale_days, a.progress)
    extra = deep(root, rows) if a.deep else []
    for line in summarize(rows, tfs):
        print(line)
    core = set((u.get("us_equity_bars") or {}).get("core") or [])
    shown = rows if a.all else [r for r in rows if r["symbol"] in core]
    if a.table:
        print("\n".join(table(shown)))
    red = [f"{r['symbol']}/{r['tf']}:{r['verdict']}" for r in rows if r["red"]]
    run = manifest.get("run") or {}
    print(f"manifest run={run} corporate_actions={manifest.get('corporate_actions')}")
    for m in extra[:50]:
        print(m)
    print(f"red={len(red)} {red[:60]}{' ...' if len(red) > 60 else ''}")
    return 1 if (red or extra) else 0


if __name__ == "__main__":
    raise SystemExit(main())
