#!/usr/bin/env python3
# wiring: manual-only - dispatched through the trainer-vm-diag relay first; wired into deploy/trainer/ict-candle-refresh.service as a separate Tier-2 hold.
"""Extend the trainer's ``data/funding_<SYMBOL>.csv`` forward from Bybit, never truncating.

PI-20261118-MANAYJZO-0002: the funding files stopped at their last manual pull
(2026-05-24 BTC, 2026-06-20 the rest). Same contract as
``refresh_candle_history.py``: extend-only (rows strictly after the file's last
timestamp), the file's OWN timestamp spelling is reproduced, atomic replace, a
shrinking write is refused, one failing symbol never blocks the others, and a
file that is missing or has an unexpected header is reported and left alone
(this extends, never creates). Run it ON THE TRAINER: Bybit public data is
geo-blocked from some hosts and is reachable from the trainer.

    python3 scripts/ops/refresh_funding_history.py --data-dir data \
        ADAUSDT AVAXUSDT BTCUSDT ETHUSDT SOLUSDT XRPUSDT
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_bybit_funding as fbf

_HEADER = "timestamp,funding_rate"


def _parse(cell: str) -> datetime:
    cell = cell.strip().strip('"')
    dt = datetime.fromisoformat(cell.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([T ])\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$")


def _spelling(sample: str):
    """f(datetime)->str reproducing the file's own timestamp spelling; raises on any other spelling.

    Strict on purpose: a guessed spelling writes rows the canonical loaders silently drop
    (2026-11-18, extend_data_from_lake.py read a date-only '2026-07-07' as a '-07-07' tz suffix).
    """
    sample = sample.strip().strip('"')
    m = _TS.match(sample)
    if not m:
        raise ValueError(f"unrecognised timestamp spelling {sample!r}")
    sep, tz = m.group(1), m.group(2) or ""
    return lambda t: t.strftime(f"%Y-%m-%d{sep}%H:%M:%S") + tz


def refresh_one(path: Path, symbol: str, now: datetime, fetch=fbf.fetch_funding) -> str:
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if not lines or lines[0].strip() != _HEADER or len(lines) < 2:
        return f"{path.name}: REFUSED header/rows not {_HEADER!r} (extends, never repairs)"
    last_cell = lines[-1].split(",")[0]
    last = _parse(last_cell)
    start_ms = int(last.timestamp() * 1000) + 1
    end_ms = int(now.timestamp() * 1000)
    if start_ms >= end_ms:
        return f"{path.name}: already current (last {last})"
    rows = fetch(symbol, start_ms, end_ms)
    rows = [r for r in rows if r["timestamp"] > last]
    if not rows:
        return f"{path.name}: no new rows after {last}"
    fmt = _spelling(last_cell)
    add = [f"{fmt(r['timestamp'])},{r['funding_rate']!r}" for r in rows]
    before = "\n".join(lines) + "\n"
    out = before + "\n".join(add) + "\n"
    assert len(out) >= len(before), "refresh would shrink the file"
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_text(out)
    os.replace(tmp, path)
    return f"{path.name}: {len(lines) - 1} -> {len(lines) - 1 + len(add)} rows, last {add[-1].split(',')[0]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("symbols", nargs="+")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    rc = 0
    for sym in args.symbols:
        path = Path(args.data_dir) / f"funding_{sym}.csv"
        if not path.exists():
            print(f"{path}: MISSING (refresh extends, never creates)", file=sys.stderr)
            rc = 1
            continue
        try:
            print(refresh_one(path, sym, now))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not block the others
            print(f"{path.name}: FAILED {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
