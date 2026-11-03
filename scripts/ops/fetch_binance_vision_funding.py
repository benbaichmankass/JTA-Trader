#!/usr/bin/env python3
"""Fetch USDT-perp funding-rate history from the Binance Vision archive (runner-reachable).

Why this exists (FUNDING-CARRY-HARNESS-FIX, PI-20261007-X9UFEF4U-0001): ``fetch_bybit_funding.py`` calls
api.bybit.com, which answers HTTP 403 from GitHub-hosted runners, so every funding_carry dispatch landed
``producer_failed``. ``data.binance.vision`` answers 200 for the monthly ``futures/um/monthly/fundingRate``
archive, the same host the candle fetcher already uses.

Output shape is exactly what ``scripts/backtest_funding_carry.py --funding-data`` reads: ``timestamp,funding_rate``,
oldest first, one row per SETTLEMENT (``funding_rate`` is the rate actually settled at that time, a fraction;
Binance's interval is 8h for most symbols and 4h for some -- the harness accrues per settlement, so the
interval does not need normalising; the interval column is kept in ``--interval-out`` form only as a warning).

The archive publishes COMPLETE months only, so the current partial month is absent: the series ends at the last
full month (stated on stderr). A missing month in the middle is an ERROR, never silently skipped, and an empty
result exits non-zero -- an empty funding series must not be used quietly.

Tier-1 research tooling: public data, no auth, no live path.
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"


def _months(start: datetime, end: datetime) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_month_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    low = {c.lower(): c for c in df.columns}
    ts, rate = low.get("calc_time"), low.get("last_funding_rate")
    if ts is None or rate is None:
        raise ValueError(f"unexpected funding archive columns: {list(df.columns)}")
    out = pd.DataFrame({"timestamp": pd.to_datetime(df[ts], unit="ms", utc=True),
                        "funding_rate": pd.to_numeric(df[rate], errors="coerce")})
    return out.dropna()


def fetch(symbol: str, days: int, now: datetime | None = None, session=None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    sess = session or requests
    start = (pd.Timestamp(now) - pd.Timedelta(days=days)).to_pydatetime()
    last_full = (pd.Timestamp(now).replace(day=1) - pd.Timedelta(days=1)).to_pydatetime()
    frames = []
    for ym in _months(start, last_full):
        r = sess.get(BASE.format(sym=symbol, ym=ym), timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"{symbol} {ym}: HTTP {r.status_code} from data.binance.vision")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        frames.append(parse_month_csv(z.read(z.namelist()[0]).decode()))
    df = pd.concat(frames).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df = df[df["timestamp"] >= pd.Timestamp(start)]
    if df.empty:
        raise RuntimeError(f"{symbol}: no funding rows in the last {days} days")
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    df = fetch(a.symbol, a.days)
    df.to_csv(a.output, index=False)
    print(f"{a.symbol}: {len(df)} settlements {df['timestamp'].iloc[0]} .. {df['timestamp'].iloc[-1]} "
          f"(complete months only) -> {a.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
