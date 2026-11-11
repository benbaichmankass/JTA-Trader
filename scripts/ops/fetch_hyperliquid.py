#!/usr/bin/env python3
# wiring: manual-only - research data tooling run by a lane or a research-script-run job; no schedule yet (persistence
# home for daily accrual is an open decision on row HL-DATA-FETCHER).
"""Fetch Hyperliquid / trade[XYZ] public candles and hourly funding to CSV (row HL-DATA-FETCHER).

Why: VENUE-SCOPE-HYPERLIQUID (2026-11-11) filed RQ-20261111-9b09-02 / -03 blocked on "no Hyperliquid data fetcher".
The public info API (``POST https://api.hyperliquid.xyz/info``) is keyless. It serves at most ~5000 recent bars per
interval, so history ACCRUES: every run MERGES into the existing file (union by timestamp, newest value wins, sorted),
never truncates it.

Coins: a validator perp is its name (``BTC``); a HIP-3 builder market is ``<dex>:<coin>`` (``xyz:SILVER``). Files are
filesystem-safe: ``xyz:SILVER`` -> ``xyz_SILVER``, written as ``<out>/<safe>_<interval>.csv`` with
``timestamp,open,high,low,close,volume`` (UTC ISO bar open) and ``<out>/<safe>_funding.csv`` with
``timestamp,funding_rate,premium`` (``funding_rate`` per HOUR, a fraction: 0.0000125 = 0.00125 %/h).

    python3 scripts/ops/fetch_hyperliquid.py --coin xyz:SILVER --coin BTC --interval 1h --funding --out data/

Tier-1 research tooling: public data, no auth, no live path. A page that fails after retries stops that coin with a
non-zero exit and leaves the file as it was (a partial pull is never written over good history).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

INFO_URL = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
RETRY_BACKOFF = (2, 4, 8, 16)
CANDLE_COLS = ("timestamp", "open", "high", "low", "close", "volume")
FUNDING_COLS = ("timestamp", "funding_rate", "premium")

Poster = Callable[[dict], object]


def _post(body: dict, url: str = INFO_URL) -> object:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _retry(post: Poster, body: dict, sleep: Callable[[float], None] = time.sleep) -> object:
    last: Optional[Exception] = None
    for i, wait in enumerate((0,) + RETRY_BACKOFF):
        if wait:
            sleep(wait)
        try:
            return post(body)
        except Exception as exc:  # noqa: BLE001 -- retried, then raised
            last = exc
    raise RuntimeError(f"info {body.get('type')} failed after {len(RETRY_BACKOFF) + 1} tries: {last}")


def safe_name(coin: str) -> str:
    return coin.replace(":", "_").replace("/", "_")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_candles(coin: str, interval: str, start_ms: int, end_ms: int, post: Optional[Poster] = None,
                  sleep: Optional[Callable[[float], None]] = None) -> List[dict]:
    """Page FORWARD from start_ms; rows keyed by bar-open time, oldest first."""
    post, sleep = post or _post, sleep or time.sleep
    step = INTERVAL_MS[interval]
    out: Dict[int, dict] = {}
    cur = start_ms
    while cur < end_ms:
        page = _retry(post, {"type": "candleSnapshot",
                             "req": {"coin": coin, "interval": interval, "startTime": cur, "endTime": end_ms}}, sleep)
        if not isinstance(page, list) or not page:
            break
        for c in page:
            t = int(c["t"])
            out[t] = {"timestamp": _iso(t), "open": c["o"], "high": c["h"], "low": c["l"], "close": c["c"],
                      "volume": c["v"]}
        nxt = max(int(c["t"]) for c in page) + step
        if nxt <= cur:
            break
        cur = nxt
    return [out[k] for k in sorted(out)]


def fetch_funding(coin: str, start_ms: int, end_ms: int, post: Optional[Poster] = None,
                  sleep: Optional[Callable[[float], None]] = None) -> List[dict]:
    post, sleep = post or _post, sleep or time.sleep
    out: Dict[int, dict] = {}
    cur = start_ms
    while cur < end_ms:
        page = _retry(post, {"type": "fundingHistory", "coin": coin, "startTime": cur, "endTime": end_ms}, sleep)
        if not isinstance(page, list) or not page:
            break
        for f in page:
            t = int(f["time"])
            out[t] = {"timestamp": _iso(t), "funding_rate": f["fundingRate"], "premium": f.get("premium", "")}
        nxt = max(int(f["time"]) for f in page) + 1
        if nxt <= cur:
            break
        cur = nxt
    return [out[k] for k in sorted(out)]


def merge_write(path: Path, rows: List[dict], cols: tuple) -> Dict[str, int]:
    """Union with the existing file by timestamp (new rows win), sorted; atomic replace. Returns counts."""
    old: Dict[str, dict] = {}
    if path.exists():
        with path.open() as fh:
            for r in csv.DictReader(fh):
                if r.get("timestamp"):
                    old[r["timestamp"]] = r
    before = len(old)
    for r in rows:
        old[r["timestamp"]] = {k: r.get(k, "") for k in cols}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols))
        w.writeheader()
        for k in sorted(old):
            w.writerow({c: old[k].get(c, "") for c in cols})
    tmp.replace(path)
    return {"before": before, "fetched": len(rows), "after": len(old)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coin", action="append", required=True, help="BTC, or <dex>:<coin> e.g. xyz:SILVER (repeatable)")
    ap.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    ap.add_argument("--days", type=int, default=400, help="look back this many days (the API caps ~5000 bars anyway)")
    ap.add_argument("--funding", action="store_true", help="also fetch hourly funding history")
    ap.add_argument("--out", default="data", help="output directory")
    a = ap.parse_args(argv)
    end = int(time.time() * 1000)
    start = end - a.days * 86_400_000
    out, rc = Path(a.out), 0
    for coin in a.coin:
        try:
            c = merge_write(out / f"{safe_name(coin)}_{a.interval}.csv", fetch_candles(coin, a.interval, start, end),
                            CANDLE_COLS)
            print(json.dumps({"coin": coin, "kind": "candles", "interval": a.interval, **c}))
            if a.funding:
                f = merge_write(out / f"{safe_name(coin)}_funding.csv", fetch_funding(coin, start, end), FUNDING_COLS)
                print(json.dumps({"coin": coin, "kind": "funding", **f}))
        except Exception as exc:  # noqa: BLE001 -- one coin's failure is reported, the others still run
            print(json.dumps({"coin": coin, "error": str(exc)[:300]}))
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
