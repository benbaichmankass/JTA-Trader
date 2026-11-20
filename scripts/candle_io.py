#!/usr/bin/env python3
"""Shared OHLCV load + resample helpers for the research harnesses.

WHY THIS EXISTS
---------------
``scripts/research/backtest_trend.py`` was retired
(``BL-20260808-RESEARCH-TREND-ENGINE-RETIREMENT-BLOCKED-BY-TEST-COUPLING``), but
three research scripts imported its ``_load`` / ``_resample`` as **pure IO
helpers** — nothing to do with its engine. Those two functions were the only
reason the retirement was blocked on ``regime_adx_cutpoint_sweep.py`` and
``regime_tag_emitted.py`` at all, so they are lifted here rather than left to
die with the engine.

**Lifted VERBATIM.** The bodies below are byte-for-byte the retired engine's
``_load`` / ``_norm_rule`` / ``_resample``, so every consumer's behaviour is
unchanged by the move. That is deliberate: a retirement PR must not also be a
silent behaviour change to the callers it rescues.

THE ENGINE USES THIS TOO
------------------------
``scripts/backtest_trend.py::_load_candles`` delegates here. It used to be a
private CSV/Parquet-only reader, and retiring the research engine removed the
only trend harness that could read **JSONL** — which broke
``build_continuous_contract.py``'s documented workflow (it writes the canonical
``market_raw`` shape as JSONL and tells you to backtest that file). So there is
now ONE reader, not two that disagree about input format.

The delegation was verified before it was made, not assumed: 18 full-summary
backtest comparisons (2 committed corpora x 5min/15min/1h x 3 configs, incl. the
config-exact ``trend_donchian`` block) came out **identical**, and the loaded
frames compared equal with ``DataFrame.equals``. This reader is a strict
superset of what the engine previously accepted — it additionally handles JSONL
and the IBKR pull's ``ts`` column, and coerces OHLC to numeric so a row with an
unparseable price is dropped rather than poisoning the arithmetic downstream.
``BL-20260809-TWO-CANDLE-READERS-DIVERGE-ON-JSONL``.

Research only (Tier-1); no live-path touch.
"""
from __future__ import annotations

import json
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from candle_variance import (  # noqa: F401  (re-exported for callers)
    DegenerateSeriesError,
    VarianceGrade,
    grade_close_variance,
)

__all__ = [
    "load_candles",
    "resample_ohlcv",
    "norm_rule",
    "assert_non_degenerate",
    "grade_close_variance",
    "DegenerateSeriesError",
    "VarianceGrade",
]


def assert_non_degenerate(df: pd.DataFrame, path: str) -> VarianceGrade:
    """Refuse a FLAT candle frame at the read. Returns the grade regardless.

    MI-157. The rule itself lives in :mod:`candle_variance` — this is only
    the policy: raise on ``degenerate``, WARN on ``not_gradeable`` (a frame
    too short to have a return series is "we could not look", which is a
    different decision from a flat one and is not this reader's to make),
    pass on ``non_degenerate``. All three states are branched on here, which
    is what stops the grade collapsing back into a boolean.
    """
    closes = df["close"] if "close" in getattr(df, "columns", []) else []
    grade = grade_close_variance(closes)
    if grade.state == "degenerate":
        raise DegenerateSeriesError(
            f"{path}: candle series is DEGENERATE — {grade.detail} "
            "Fetch real candle history first "
            "(scripts/ops/fetch_backtest_candles.py). See MI-157."
        )
    if grade.state == "not_gradeable":
        logging.getLogger(__name__).warning(
            "%s: candle variance NOT GRADEABLE — %s", path, grade.detail
        )
    return grade


def load_candles(path: str) -> pd.DataFrame:
    """Read OHLCV from CSV / Parquet / JSONL into a normalised frame.

    Accepts the IBKR pull's ``ts`` timestamp column, coerces OHLC to numeric,
    and drops any row missing a timestamp or a price. Returned frame is sorted
    ascending with a fresh RangeIndex.
    """
    if path.endswith('.parquet'):
        df = pd.read_parquet(path)
    elif path.endswith('.jsonl'):
        rows = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        df = pd.DataFrame(rows)
    else:
        df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    # the IBKR pull writes the timestamp column as `ts`; normalise to `timestamp`
    if 'timestamp' not in cols and 'ts' in cols:
        df = df.rename(columns={cols['ts']: 'timestamp'})
        cols = {c.lower(): c for c in df.columns}
    for need in ['timestamp', 'open', 'high', 'low', 'close']:
        if need in cols and cols[need] != need:
            df = df.rename(columns={cols[need]: need})
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
    for col in ('open', 'high', 'low', 'close'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    out = (df.dropna(subset=['timestamp', 'open', 'high', 'low', 'close'])
             .sort_values('timestamp').reset_index(drop=True))
    # MI-157: refuse a flat series at the READ, not at the eyeball. A silent
    # fallback to a constant-price series is the defect being fixed here.
    assert_non_degenerate(out, path)
    return out


def norm_rule(rule: str) -> str:
    """pandas 3.0 dropped the lowercase 'm' minutes alias — normalise to 'min'."""
    r = rule.strip().lower()
    return r[:-1] + 'min' if (r.endswith('m') and not r.endswith('min')) else r


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """OPEN-stamped OHLC resample: buckets [T, T+rule) labelled T, the grid of the native exchange files and of the
    harnesses since #27566 (PI-20261120-7ITMUEB1-0006; right/right grouped the sub-bars opened in (T-rule, T]).

    Open stamps are causal for SAME-FRAME consumers and for an entry lookup when the ledger's entry grain equals the
    rule (the decision bar is closed at fill time). A consumer that maps a FINER ledger onto these bars must not read
    the bar an entry sits inside: use :func:`entry_bar_locator`, which detects that case and falls back to the last
    bar that closed at or before the entry."""
    return (df.set_index('timestamp')
            .resample(norm_rule(rule), label='left', closed='left')
            .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
            .dropna().reset_index())


def entry_bar_locator(bar_ts, entry_times):
    """Causal index of the OPEN-stamped bar a trade entry may read (PI-20261120-7ITMUEB1-0006).

    ``bar_ts``: the bars' open stamps (sorted). ``entry_times``: every parseable entry time of the ledger.
    * Every entry ON the bar grid (ledger grain == bar grain, the regime taggers' documented contract): the entry's
      own decision bar (stamp <= entry), which is closed at fill time -- the live stamp.
    * ANY entry OFF the grid (a finer ledger): for ALL entries, the last bar whose close (stamp + bar period) is
      <= the entry -- never the bar the entry sits inside.
    Returns ``(locate, mode)``; ``locate(et)`` -> int index (-1 if none) and ``mode`` in {"aligned", "finer_ledger",
    "empty"}. The bar period is the modal stamp spacing."""
    ts = pd.DatetimeIndex(pd.to_datetime(pd.Series(bar_ts), utc=True, errors="coerce").dropna())
    ets = [pd.Timestamp(e) for e in entry_times if e is not None and not pd.isna(e)]
    if len(ts) == 0:
        return (lambda et: -1), "empty"
    grid = set(ts)
    aligned = all(e in grid for e in ets)
    if aligned:
        return (lambda et: int(ts.searchsorted(et, side="right")) - 1), "aligned"
    period = pd.Series(ts).diff().mode()
    step = period.iloc[0] if len(period) else pd.Timedelta(0)
    return (lambda et: int(ts.searchsorted(et - step, side="right")) - 1), "finer_ledger"

