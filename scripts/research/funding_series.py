#!/usr/bin/env python3
# wiring: library for scripts/research/frontier_momentum_runner.py (research-script-run.yml); `--self-test` is run by tests/test_frontier_momentum_runner.py.
"""Runner-fetched perp FUNDING series from the Binance public data archive.

Why: ``scripts/backtest_xsec_momentum.py`` and ``scripts/backtest_tsmom.py`` charge funding on every
held perp leg; a flat ``funding_bps_per_window`` is a drag with no sign and no regime. The SETTLED rates
are public and keyless at ``data.binance.vision/data/futures/um/monthly/fundingRate/<SYM>/`` (the same
archive and the same reachability as the kline lane in ``scripts/ops/fetch_backtest_candles.py``).

Output unit: a UTC-day-indexed Series of the SUM of the settled ``last_funding_rate`` values stamped on
that day (a fraction of notional, e.g. ``0.0003`` = 3 bps; three 8h settlements on a normal day). A
long pays a positive rate and a short receives it; that sign is applied by the harness, not here.

Read-state is explicit: a month the archive does not carry (the current, still-accumulating month has
no monthly zip) is returned in ``missing_months`` -- never filled with zeros -- and the caller decides.
Tier-1 research tooling; network is injected (``fetch_zip``) so tests never touch it.
"""
from __future__ import annotations

import csv
import io
import sys
import time
import zipfile
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
_BACKOFF = [2, 4, 8, 16]


def parse_funding_csv(text: str) -> List[Tuple[int, float]]:
    """Rows ``calc_time(ms or us), funding_interval_hours, last_funding_rate`` -> ``[(ts_ms, rate)]``.
    Header / malformed rows are skipped (a row we cannot parse is dropped, counted by the caller)."""
    out: List[Tuple[int, float]] = []
    for fields in csv.reader(io.StringIO(text)):
        try:
            ts = int(fields[0])
            rate = float(fields[2])
        except (ValueError, IndexError):
            continue
        out.append((ts // 1000 if ts >= 10**14 else ts, rate))
    return out


def daily_sum(rows: List[Tuple[int, float]]) -> pd.Series:
    """Sum settled rates per UTC day. Empty input -> empty Series (read-state decided upstream)."""
    if not rows:
        return pd.Series(dtype=float, name="funding")
    ts = pd.to_datetime([r[0] for r in rows], unit="ms", utc=True).normalize()
    s = pd.Series([r[1] for r in rows], index=pd.DatetimeIndex(ts), name="funding")
    return s.groupby(level=0).sum().sort_index()


def _http_zip(url: str) -> Optional[bytes]:
    import requests
    for attempt in range(len(_BACKOFF)):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == len(_BACKOFF) - 1:
                raise
            time.sleep(_BACKOFF[attempt])
    return None


def fetch_funding(symbol: str, start: datetime, end: datetime, *,
                  fetch_zip: Callable[[str], Optional[bytes]] = _http_zip) -> Dict[str, object]:
    """Fetch + aggregate settled funding for ``symbol`` over ``[start, end]`` (UTC datetimes).

    Returns ``{"series": daily Series, "months_ok": [...], "missing_months": [...], "n_settlements": int}``.
    """
    months: List[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    rows: List[Tuple[int, float]] = []
    ok: List[str] = []
    missing: List[str] = []
    for ym in months:
        raw = fetch_zip(f"{BASE}/{symbol}/{symbol}-fundingRate-{ym}.zip")
        if raw is None:
            missing.append(ym)
            continue
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8")
        got = parse_funding_csv(text)
        if got:
            rows.extend(got)
            ok.append(ym)
        else:
            missing.append(ym)
    s = daily_sum(rows)
    lo, hi = pd.Timestamp(start).tz_convert("UTC").normalize(), pd.Timestamp(end).tz_convert("UTC").normalize()
    s = s[(s.index >= lo) & (s.index <= hi)]
    return {"series": s, "months_ok": ok, "missing_months": missing, "n_settlements": len(rows)}


def _self_test() -> int:
    import io as _io
    import zipfile as _zf
    csv_text = ("calc_time,funding_interval_hours,last_funding_rate\n"
                "1704067200000,8,0.0001\n1704096000000,8,0.0002\n1704124800000,8,-0.00005\n"
                "1704153600000,8,0.0003\n")
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("x.csv", csv_text)
    calls: List[str] = []

    def fake(url: str) -> Optional[bytes]:
        calls.append(url)
        return buf.getvalue() if "2024-01" in url else None

    res = fetch_funding("BTCUSDT", datetime(2024, 1, 1, tzinfo=timezone.utc),
                        datetime(2024, 2, 5, tzinfo=timezone.utc), fetch_zip=fake)
    s = res["series"]
    assert res["months_ok"] == ["2024-01"] and res["missing_months"] == ["2024-02"], res
    assert abs(s.loc[pd.Timestamp("2024-01-01", tz="UTC")] - 0.00025) < 1e-12, s
    assert abs(s.loc[pd.Timestamp("2024-01-02", tz="UTC")] - 0.0003) < 1e-12, s
    assert res["n_settlements"] == 4
    print("funding_series SELF-TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test())
