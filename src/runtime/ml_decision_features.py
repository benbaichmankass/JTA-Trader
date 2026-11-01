"""Point-in-time features for the ML ENTRY decision model (row ML-ENTRY-LIVE-ADAPTER; Tier-1 read path).

The SERVING copy of ``scripts/research/ml_decision_entry.features_symbol`` and its cross-sectional context, so the
live adapter (``src/units/strategies/ml_entry.py``) computes exactly what the model was trained on. Parity with the
research harness is pinned by ``tests/test_ml_entry_adapter.py::test_features_match_research_harness`` (same frame in,
same numbers out); a change here without the harness (or the reverse) fails that test.

Every input is a CLOSED 1h bar at or before the decision bar: the caller passes frames whose last row is the decision
bar (the forming bar already dropped).
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

ATR_N = 14
FEATURES = ["ret_1", "ret_4", "ret_12", "ret_24", "ret_72", "ret_168", "vol24", "vol_ratio", "atr_pct",
            "range_pos_24", "range_pos_168", "vol_z", "rsi14", "hour", "dow",
            "xs_rank_ret24", "btc_ret24", "btc_vol24", "breadth_up24", "rel_vol"]
MIN_BARS = 169 + 168  # ret_168 needs 168 bars of vol24 history plus 168 of returns; vol_z needs a 168-bar window


def features_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar own-symbol features. ``df`` has columns ts (UTC bar OPEN time), open, high, low, close, volume."""
    c, h, lo, v = (df[k].astype(float) for k in ("close", "high", "low", "volume"))
    lr = np.log(c).diff()
    vol24 = lr.rolling(24).std()
    vol168 = lr.rolling(168).std()
    f = pd.DataFrame({"ts": df["ts"]})
    for k in (1, 4, 12, 24, 72, 168):
        f[f"ret_{k}"] = (np.log(c) - np.log(c.shift(k))) / (vol24 * np.sqrt(k))
    f["vol24"] = vol24
    f["vol_ratio"] = vol24 / vol168
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    f["atr_pct"] = tr.rolling(ATR_N).mean() / c
    for k in (24, 168):
        hi, lw = h.rolling(k).max(), lo.rolling(k).min()
        f[f"range_pos_{k}"] = (c - lw) / (hi - lw).replace(0, np.nan)
    lv = np.log1p(v)
    f["vol_z"] = (lv - lv.rolling(168).mean()) / lv.rolling(168).std()
    up = lr.clip(lower=0).rolling(14).mean()
    dn = (-lr.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = up / (up + dn).replace(0, np.nan)
    close_ts = df["ts"] + pd.Timedelta(hours=1)
    f["hour"] = close_ts.dt.hour
    f["dow"] = close_ts.dt.dayofweek
    f["ret24_raw"] = np.log(c) - np.log(c.shift(24))
    return f


def atr_last(df: pd.DataFrame, n: int = ATR_N) -> float:
    """ATR14 (simple mean of true range) at the last bar, as the harness labels it."""
    h, lo, c = (df[k].astype(float) for k in ("high", "low", "close"))
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n, min_periods=n).mean().iloc[-1])


def _asof(fr: pd.DataFrame, close_ts: pd.Timestamp) -> pd.DataFrame:
    """``fr`` truncated to the bars CLOSED at or before ``close_ts`` (a 1h bar opening at ts closes at ts + 1h)."""
    return fr[fr["ts"] + pd.Timedelta(hours=1) <= close_ts]


def decision_row(symbol: str, frames: Mapping[str, pd.DataFrame],
                 reference: Optional[Iterable[str]] = None) -> Optional[Dict[str, float]]:
    """The 20-feature row for ``symbol`` at the last bar of ``frames[symbol]``.

    Cross-sectional context is read AS-OF that bar's close: each reference frame is cut to its bars closed at or
    before it, and is used only if its last closed bar closed within the hour before it (a stale or missing
    reference is skipped and counted). For a 24/7 perp whose bars share the decision timestamp this is exactly the
    previous equal-timestamp rule. For a symbol OUTSIDE the reference set (an ETF on alpaca_paper, row
    ALPACA-LIVE-ACTIVITY-ML) its 24-bar return is ranked among the references with itself inserted, and breadth /
    median vol are the references' -- the definition scripts/research/ml_entry_alpaca_score.py scored.
    ``reference``: the model's reference symbols (``meta["xs_reference"]``); ``None`` treats ``symbol`` as one of
    them (the pre-2026-11-01 behaviour). ``None`` if the row cannot be formed."""
    own = frames.get(symbol)
    if own is None or len(own) < MIN_BARS:
        return None
    close = own["ts"].iloc[-1] + pd.Timedelta(hours=1)
    fo = features_symbol(own).iloc[-1]
    r24, v24 = {}, {}
    for s, fr in frames.items():
        if fr is None or s == symbol:
            continue
        cut = _asof(fr, close)
        if len(cut) < 25 or cut["ts"].iloc[-1] + pd.Timedelta(hours=2) <= close:
            continue
        ff = features_symbol(cut.iloc[-200:].reset_index(drop=True)).iloc[-1]
        r24[s], v24[s] = ff["ret24_raw"], ff["vol24"]
    if "BTCUSDT" not in r24 and symbol != "BTCUSDT":
        return None
    in_reference = reference is None or symbol in set(reference)
    rv_ref = pd.Series(r24, dtype=float)
    vv_ref = pd.Series(v24, dtype=float)
    rv = pd.concat([rv_ref, pd.Series({symbol: float(fo["ret24_raw"])})])
    vv = pd.concat([vv_ref, pd.Series({symbol: float(fo["vol24"])})])
    rank = rv.rank(pct=True)
    row = {k: float(fo[k]) for k in FEATURES if k in fo.index}
    row["xs_rank_ret24"] = float(rank[symbol])
    row["btc_ret24"] = float(rv["BTCUSDT"])
    row["btc_vol24"] = float(vv["BTCUSDT"])
    if in_reference:   # the perp universe includes the symbol itself (the c692 training definition)
        row["breadth_up24"] = float((rv > 0).sum() / rv.notna().sum())
        row["rel_vol"] = float(fo["vol24"] / vv.median())
    else:              # an outside symbol: breadth / median vol of the references only
        row["breadth_up24"] = float((rv_ref > 0).sum() / rv_ref.notna().sum())
        row["rel_vol"] = float(fo["vol24"] / vv_ref.median())
    if any(not np.isfinite(row.get(k, np.nan)) for k in FEATURES):
        return None
    row["_n_reference"] = float(len(rv))
    return row
