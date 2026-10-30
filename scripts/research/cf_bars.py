#!/usr/bin/env python3
# wiring: library — historical bar source + paged package reader for cf_core consumers (CF-B0-ENGINE-LIFT); no scheduler.
"""cf_bars: price paths and package pages for the counterfactual engine, for HISTORY (the live grader's ``fetch_candles``
reaches back only ~16h at 1m).

* ``package_pages`` pages a journal read by ``offset`` (the live ``load_sources`` reads ``limit=150`` once, so it cannot
  backfill). The fetcher is injected; nothing here knows the transport.
* ``historical_bars`` returns the engine's bar shape ``{time, open, high, low, close, dur}`` (epoch seconds) for
  ``[t0, t1)`` from an injected fetcher; the default is the Binance Vision archive reader the backtest CSVs use
  (``scripts/ops/fetch_backtest_candles.py``), imported lazily so importing this module never touches the network.
* ``bars_for_package`` is the window a closed package needs: ``[t_entry, t_close + horizon)``. No bars is a recorded
  state (``could_not_grade: no_bars``), never an empty success.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
# the venue's interval names are the repo's: 1m=1, 1h=60, ... (fetch_backtest_candles._interval_ms)
_VENUE_INTERVAL = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "D"}


def package_pages(fetch_page: Callable[[int, int], Sequence[dict]], *, page_size: int = 150, max_pages: int = 10_000) -> Iterator[dict]:
    """Yield every row of a paged journal read. ``fetch_page(limit, offset)`` returns up to ``limit`` rows; a short
    page ends the read. ``max_pages`` bounds a fetcher that never short-pages (a stuck offset), and exhausting it
    raises: a truncated history must not read as a complete one."""
    for page in range(max_pages):
        rows = fetch_page(page_size, page * page_size)
        for r in rows:
            yield r
        if len(rows) < page_size:
            return
    raise RuntimeError(f"package_pages: still full after {max_pages} pages of {page_size}; refusing a possibly truncated read")


def rows_to_bars(rows: Sequence[dict], tf: str) -> List[dict]:
    """Normalise fetcher rows (``timestamp`` datetime | ``time`` epoch s) to engine bars, oldest-first, de-duplicated."""
    sec = TF_SECONDS[tf]
    out: Dict[float, dict] = {}
    for r in rows:
        ts = r.get("time")
        if ts is None:
            ts = r["timestamp"].timestamp()
        ts = float(ts)
        out[ts] = {"time": ts, "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                   "close": float(r["close"]), "dur": float(sec)}
    return [out[k] for k in sorted(out)]


def _default_fetcher(symbol: str, tf: str, t0: float, t1: float) -> List[dict]:
    from scripts.ops.fetch_backtest_candles import fetch_klines_binance_vision
    return fetch_klines_binance_vision(symbol, _VENUE_INTERVAL[tf], int(t0 * 1000), int(t1 * 1000))


def historical_bars(symbol: str, tf: str, t0: float, t1: float,
                    fetcher: Optional[Callable[[str, str, float, float], Sequence[dict]]] = None) -> List[dict]:
    """Bars of ``tf`` covering ``[t0, t1)``: a bar is kept when it ends after t0 and opens before t1."""
    if tf not in TF_SECONDS:
        raise ValueError(f"unknown timeframe {tf!r}")
    rows = (fetcher or _default_fetcher)(symbol, tf, t0, t1)
    sec = TF_SECONDS[tf]
    return [b for b in rows_to_bars(rows, tf) if b["time"] + sec > t0 and b["time"] < t1]


def bars_for_package(pkg: dict, *, t_entry: float, t_close: float, horizon_s: float, tf: str,
                     fetcher: Optional[Callable[[str, str, float, float], Sequence[dict]]] = None) -> Tuple[Optional[List[dict]], Optional[str]]:
    """``(bars, None)`` or ``(None, 'no_bars')``. The window is [t_entry, t_close + horizon): what ``grade_package`` trims to."""
    bars = historical_bars(str(pkg.get("symbol")), tf, t_entry, t_close + horizon_s, fetcher)
    return (bars, None) if bars else (None, "no_bars")
