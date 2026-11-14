# wiring: research harness helper - scripts/backtest_pullback.py and scripts/backtest_trend.py load it by file for --htf-long-sma-days
"""Higher-timeframe long gate for the research harnesses (scripts/backtest_pullback.py, scripts/backtest_trend.py).

Row DEMO-FLOOR-ITER-20261113, manager GO 2026-11-14 07:15Z, after RQ-20261114-db1a-03 (post-hoc PASS): skip a LONG entry
when the symbol's last COMPLETED UTC daily close before the entry bar is below the N-day simple moving average of daily
closes ending at that day. Shorts are never gated. A day whose SMA has no full N-day history never gates (permissive).

Opt-in only (``--htf-long-sma-days N``; default 0 = off = byte-identical): the harness builds the gate from the bars it
loaded BEFORE the --start/--end trim, so the SMA has its warm-up even when the run window is one year. Daily closes come
from those intraday bars: the close of a UTC day is the close of its last intraday bar, which equals the venue's daily
kline close on the same UTC day boundary (Binance / Bybit daily bars open at 00:00 UTC).

The LIVE unit is not touched. A live port would read the venue's 1d candles (e.g. src.runtime.market_data.fetch_candles
with the symbol and '1d'), take the last COMPLETED daily bar (yesterday's close, never the forming day) and the mean of
the last N completed daily closes, and refuse a long when close < SMA.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date
from typing import Any, List, Optional, Tuple

import pandas as pd


class HtfLongGate:
    """``skip(ts)`` is True when a long at bar timestamp ``ts`` is gated."""

    def __init__(self, table: List[Tuple[date, float, Optional[float]]], days: int):
        self.days = int(days)
        self._dates = [d for d, _, _ in table]
        self._rows = table

    def state(self, ts: Any) -> str:
        """below | above | unknown, from the last daily bar strictly before ``ts``'s UTC date."""
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        d = t.tz_convert("UTC").date()
        i = bisect_left(self._dates, d) - 1
        if i < 0:
            return "unknown"
        _, close, sma = self._rows[i]
        if sma is None:
            return "unknown"
        return "below" if close < sma else "above"

    def skip(self, ts: Any) -> bool:
        return self.state(ts) == "below"


def build_gate(df: pd.DataFrame, days: int) -> Optional[HtfLongGate]:
    """The gate from intraday bars (``timestamp``, ``close``); None when ``days`` <= 0 (off)."""
    if not days or int(days) <= 0:
        return None
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    s = pd.Series(pd.to_numeric(df["close"], errors="coerce").to_numpy(), index=ts)
    s = s[s.index.notna()].sort_index()
    daily = s.resample("1D").last().dropna()
    sma = daily.rolling(int(days), min_periods=int(days)).mean()
    table = [(idx.date(), float(c), (None if pd.isna(m) else float(m))) for idx, c, m in zip(daily.index, daily, sma)]
    return HtfLongGate(table, int(days))
