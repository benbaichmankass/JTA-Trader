#!/usr/bin/env python3
# wiring: manual-only — rebuilds comms/live_review/candles/ (the VM-resident candle store live_review_outcomes falls back to); run when a leg's candle pull is refreshed, then commit.
"""Build the live-review candle store: one trimmed, gzip'd OHLC file per (symbol, timeframe).

WHY: ``deploy/vm-sparse-checkout`` removes ``comms/research/**/candles/`` and ``*.csv`` from the live VM, so the
VM-side packet builder found no candles and priced every tighten ``no_candles``. ``comms/live_review/candles/`` is
outside those rules. ``find_candles`` uses it only when the research tree has nothing.

    python3 scripts/research/build_ltr_candle_store.py [--max-mb 6] [--dry-run]

Pairs come from the committed evidence records (symbol from the corpus, timeframe from the record); the file chosen
is the one ``find_candles(..., widest_span=True)`` picks. Only the five OHLC columns are kept; output is
deterministic (gzip mtime 0)."""
from __future__ import annotations

import argparse
import glob
import gzip
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import live_review_outcomes as L  # noqa: E402

COLS = ["timestamp", "open", "high", "low", "close"]


def needed_pairs(repo: Path = REPO) -> dict:
    pairs: dict = {}
    for f in sorted(glob.glob(str(repo / "comms/strategy_evidence/*.json"))):
        leg = Path(f).stem
        tf = json.loads(Path(f).read_text()).get("timeframe")
        if not tf:
            continue
        try:
            trades, _ = L.load_trades(leg, repo, corpus="auto")
        except (FileNotFoundError, OSError, ValueError):
            continue
        sym = trades[0].get("symbol") if trades else None
        if sym:
            pairs.setdefault((sym, tf), []).append(leg)
    return pairs


def write_store(src: str, dst: Path) -> int:
    df = L.pd.read_csv(src, usecols=COLS)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode())
    return dst.stat().st_size


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-mb", type=float, default=6.0, help="skip a source file larger than this (5m/15m pulls)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    total = 0
    for (sym, tf), legs in sorted(needed_pairs().items()):
        src = L._find_candles_research(sym, tf, REPO, True)
        if not src:
            print(f"MISSING {sym} {tf} (legs: {', '.join(legs)}) - no research candle file to copy")
            continue
        mb = Path(src).stat().st_size / 1e6
        if mb > a.max_mb:
            print(f"SKIP    {sym} {tf} {mb:.1f}MB > --max-mb")
            continue
        dst = REPO / L.LTR_CANDLE_STORE / f"{sym}_{tf}.csv.gz"
        sz = 0 if a.dry_run else write_store(src, dst)
        total += sz
        print(f"OK      {sym} {tf} <- {Path(src).relative_to(REPO)} -> {dst.name} {sz/1e6:.2f}MB")
    print(f"store total {total/1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
