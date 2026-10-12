#!/usr/bin/env python3
"""NEWS-HIST-REPLAY helper -- pull public 1h (or any interval) OHLCV to the CSV shape the harnesses read.

Source: Binance public market-data mirror (``data-api.binance.vision``, keyless, spot). Used when the
canonical Bybit perp frames are not reachable (e.g. a cloud session whose egress is blocked from api.bybit.com).
SPOT closes track the perp to within a few bps at 1h, which is immaterial for a 24h-horizon event study;
the trainer-resident perp frames are the canonical source for a promotion-grade run and are preferred there.

    python3 scripts/research/news_hist_candles.py --symbol BTCUSDT --interval 1h \
        --start 2023-09-01 --end 2026-10-12 --out /tmp/btc_1h.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

URL = "https://data-api.binance.vision/api/v3/klines?symbol={s}&interval={i}&startTime={st}&endTime={en}&limit=1000"


def fetch(symbol: str, interval: str, start: datetime, end: datetime):
    st, en = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    rows = []
    while st < en:
        for k in range(4):
            try:
                with urllib.request.urlopen(URL.format(s=symbol, i=interval, st=st, en=en), timeout=30) as r:
                    batch = json.loads(r.read())
                break
            except Exception:  # noqa: BLE001  # allow-silent: retried with backoff, re-raised on the 4th failure
                if k == 3:
                    raise
                time.sleep(2 ** (k + 1))
        if not batch:
            break
        rows.extend(batch)
        st = batch[-1][0] + 1
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    p = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731
    rows = fetch(a.symbol, a.interval, p(a.start), p(a.end))
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc).isoformat(), r[1], r[2], r[3], r[4], r[5]])
    print(f"{a.symbol} {a.interval}: {len(rows)} bars -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
