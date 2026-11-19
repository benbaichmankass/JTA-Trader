#!/usr/bin/env python3
# wiring: manual-only - the daily runner is deploy/trainer/ict-candle-refresh.timer, shipped as its own held Tier-2 PR (#14518) so it cannot ride this Tier-1 change.
"""Extend the trainer's multi-year candle CSVs forward, never truncating them.

OWNER of the refresh for ``data/<SYM>_<tf>.csv`` (PI-20260929-FCJRWVAK-0002):
before this, nothing fetched candles on the trainer and every study reading
those files ended on the day of one manual batch (2026-06-18).

Behaviour: read the file's last bar, fetch Bybit linear perp klines (the SAME venue as
the history: MEASURED trainer diag #14515, old SOL/ETH/XRP 15m files match Bybit at median
0.000 bps, volume ratio 1.000; Binance USD-M differs 0.5-1.4 bps median with 2.6-4.5x volume,
so it is deliberately NOT a fallback -- a venue swap changes the population) from the next bar to now, append bars strictly after the last
existing timestamp (dedupe on timestamp), write atomically. Existing rows are
never modified or dropped; the write is refused if the result would be shorter.

    python3 scripts/ops/refresh_candle_history.py --data-dir data \
        SOLUSDT:15 XRPUSDT:15 ETHUSDT:15
    (pair = [source:]SYMBOL:interval[=FILE]; 15 -> data/SYMBOL_15m.csv;
     BTCUSDT:5=backtest_BTCUSDT_5m.csv extends that existing file; yf:GC=F:60=GC_F_1h.csv reads yfinance)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_backtest_candles as fbc  # noqa: E402
import candle_io  # noqa: E402  (the canonical loader: parses WITHOUT format='mixed')

_TF_LABEL = {"5": "5m", "15": "15m", "60": "1h", "120": "2h", "240": "4h"}


_BASE_COLS = {"timestamp", "open", "high", "low", "close", "volume"}


def merge_extend(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Append rows of ``new`` strictly after ``old``'s last timestamp.

    REFUSES when the old file carries columns beyond timestamp/OHLCV (e.g.
    ``taker_buy_base``): Bybit klines cannot fill them, and appending rows with
    NaN there would silently poison every study that reads those columns.
    """
    extra = [c for c in old.columns if c not in _BASE_COLS]
    if extra:
        raise RuntimeError(
            f"existing file has columns {extra} that the Bybit feed cannot fill; "
            f"refusing to append NaN-filled rows")
    ots = pd.to_datetime(old["timestamp"], utc=True, format="mixed")
    nts = pd.to_datetime(new["timestamp"], utc=True, format="mixed")
    add = new[nts > ots.max()].copy()
    add = add.drop_duplicates("timestamp")
    add = add.reindex(columns=[c for c in old.columns if c in add.columns])
    out = pd.concat([old, add], ignore_index=True)
    assert len(out) >= len(old), "refresh would shrink the file"
    return out


def ts_formatter(sample: str):
    """Return f(datetime)->str reproducing the file's OWN timestamp spelling.

    The canonical loaders (candle_io.load_candles, backtest_pullback) parse
    without ``format='mixed'``: rows spelled differently from the first row
    become NaT and are silently DROPPED. So new rows must match the file.
    """
    sample = str(sample).strip()
    sep = "T" if "T" in sample else " "
    if sample.endswith("Z"):
        tz = "Z"
    elif len(sample) > 6 and sample[-6] in "+-" and sample[-3] == ":":
        tz = sample[-6:]
    elif len(sample) > 5 and sample[-5] in "+-" and sample[-5:-1].isdigit():
        tz = sample[-5:]
    else:
        tz = ""  # timezone-naive file (UTC by convention)
    return lambda t: t.strftime(f"%Y-%m-%d{sep}%H:%M:%S") + tz


def closed_end_ms(now: datetime, interval: str) -> int:
    """End of the last CLOSED bar: floor ``now`` to the current bar's start, so
    the still-forming bar is never fetched (fetch_klines drops start >= end).
    Same rule as src/runtime/closed_bars.py (FIX-CA-23)."""
    step = fbc._interval_ms(interval)
    return (int(now.timestamp() * 1000) // step) * step


def fetch_yfinance(ticker: str, interval: str, start_ms: int, end_ms: int) -> list:
    """CLOSED yfinance bars in [start_ms, end_ms), oldest first, as fetch_klines-shaped rows.

    Only for a file whose history IS yfinance (GC_F_1h.csv: yfinance GC=F, parity MEASURED 2026-11-19,
    trainer-vm-diag #27293: 12 overlapping bars, median close diff 0.0 bps). Raises on any failure;
    never falls back to another venue (a venue swap changes the population)."""
    import yfinance as yf  # noqa: PLC0415  (trainer venv)
    step = fbc._interval_ms(interval)
    yf_iv = {"60": "1h", "5": "5m", "15": "15m"}[interval]
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    df = yf.download(ticker, start=start, end=end, interval=yf_iv, progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    idx = pd.to_datetime(df.index, utc=True)
    rows = []
    for ts, r in zip(idx, df.itertuples(index=False)):
        ms = int(ts.timestamp() * 1000)
        if ms < start_ms or ms + step > end_ms:   # outside the window, or the still-forming bar
            continue
        rec = r._asdict()
        rows.append({"timestamp": ts.to_pydatetime(), "open": float(rec["Open"]), "high": float(rec["High"]),
                     "low": float(rec["Low"]), "close": float(rec["Close"]),
                     "volume": float(rec.get("Volume") or 0.0)})
    return rows


def fetch_dukascopy_rth(instrument: str, interval: str, start_ms: int, end_ms: int) -> list:
    """CLOSED Dukascopy BID bars, US cash session only, in [start_ms, end_ms), oldest first.

    Only for the RTH ETF files whose history IS Dukascopy ETF-CFD BID RTH (SPY/QQQ/GLD/IEF/IWM/SLV/TLT/USO_1h):
    parity MEASURED 2026-11-19 (trainer-vm-diag #27294), 12 overlapping bars each, close diff 0.0 bps
    median AND max, volume ratio 1.0. Uses fetch_dukascopy_ohlcv.fetch + rth_filter, the same filter the
    history was cut with. Raises on any failure; never falls back."""
    import fetch_dukascopy_ohlcv as fd  # noqa: PLC0415  (scripts/ops, trainer venv has dukascopy_python)
    step = fbc._interval_ms(interval)
    iv = {"60": "1h", "5": "5m", "15": "15m"}[interval]
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    df = fd.fetch(instrument, start, end, iv)
    if df is None or len(df) == 0:
        return []
    df = fd.rth_filter(df)
    rows = []
    for r in df.itertuples(index=False):
        ts = pd.Timestamp(r.timestamp)
        ms = int(ts.timestamp() * 1000)
        if ms < start_ms or ms + step > end_ms:   # outside the window, or the still-forming bar
            continue
        rows.append({"timestamp": ts.to_pydatetime(), "open": float(r.open), "high": float(r.high),
                     "low": float(r.low), "close": float(r.close),
                     "volume": float(getattr(r, "volume", 0.0) or 0.0)})
    return rows


#: source name -> fetch(symbol, interval, start_ms, end_ms) -> rows. Bybit is the default and the venue of
#: every crypto file; others are allowed ONLY for files whose history came from that same source.
SOURCES = {"bybit": lambda s, iv, a, b: fbc.fetch_klines(s, iv, a, b), "yf": fetch_yfinance,
           "dk": fetch_dukascopy_rth}


def parse_pair(pair: str, data_dir: Path):
    """``[source:]SYMBOL:INTERVAL[=FILE]`` -> (source, symbol, interval, path).

    ``SOLUSDT:15`` -> bybit, data/SOLUSDT_15m.csv (unchanged). ``BTCUSDT:5=backtest_BTCUSDT_5m.csv`` -> bybit into
    that existing file (no new native file: the m20 resolver reads backtest_BTCUSDT_5m.csv for BTC 5m legs).
    ``yf:GC=F:60=GC_F_1h.csv`` -> yfinance GC=F into GC_F_1h.csv. ``dk:INSTRUMENT_ETF_CFD_US_SPY_US_USD:60=SPY_1h.csv``
    -> Dukascopy BID, US cash session, into SPY_1h.csv. The FILE must already exist (extend, never create)."""
    head, _, target = pair.rpartition(":")
    iv, _, fname = target.partition("=")
    parts = head.split(":", 1)
    source, sym = (parts[0], parts[1]) if len(parts) == 2 and parts[0] in SOURCES else ("bybit", head)
    if iv not in _TF_LABEL:
        raise ValueError(f"{pair}: interval {iv!r} not in {sorted(_TF_LABEL)}")
    path = Path(data_dir) / (fname or f"{sym}_{_TF_LABEL[iv]}.csv")
    return source, sym, iv, path


def refresh_one(path: Path, symbol: str, interval: str, now: datetime, source: str = "bybit") -> str:
    old = pd.read_csv(path)
    last = pd.to_datetime(old["timestamp"], utc=True, format="mixed").max()
    start_ms = int(last.timestamp() * 1000) + fbc._interval_ms(interval)
    end_ms = closed_end_ms(now, interval)
    if start_ms >= end_ms:
        return f"{path.name}: already current (last {last})"
    rows = SOURCES[source](symbol, interval, start_ms, end_ms)  # raises, never falls back to another venue
    if not rows:
        return f"{path.name}: no new bars after {last}"
    new = pd.DataFrame(rows)
    fmt = ts_formatter(old["timestamp"].iloc[-1])
    new["timestamp"] = new["timestamp"].map(fmt)
    out = merge_extend(old, new)
    tmp = path.with_suffix(".csv.tmp")
    out.to_csv(tmp, index=False)
    # Read back through the CANONICAL loader: every row must survive.
    try:
        loaded = candle_io.load_candles(str(tmp))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if len(loaded) != len(out):
        tmp.unlink()
        raise RuntimeError(
            f"{path.name}: canonical loader reads {len(loaded)} of {len(out)} rows "
            f"after refresh (timestamp format mismatch?); original left untouched")
    os.replace(tmp, path)
    return f"{path.name}: {len(old)} -> {len(out)} rows, last {out['timestamp'].iloc[-1]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("pairs", nargs="+")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    rc = 0
    for pair in args.pairs:
        try:
            source, sym, iv, path = parse_pair(pair, Path(args.data_dir))
        except ValueError as exc:
            print(f"{pair}: BAD PAIR {exc}", file=sys.stderr)
            rc = 1
            continue
        if not path.exists():
            print(f"{path}: MISSING (refresh extends, never creates)", file=sys.stderr)
            rc = 1
            continue
        try:
            print(refresh_one(path, sym, iv, now, source))
        except Exception as exc:  # one bad symbol must not block the others
            print(f"{path.name}: FAILED {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
