"""Point-in-time features for the ML ENTRY decision model (row ML-ENTRY-LIVE-ADAPTER; Tier-1 read path).

The SERVING copy of ``scripts/research/ml_decision_entry.features_symbol`` and its cross-sectional context, so the
live adapter (``src/units/strategies/ml_entry.py``) computes exactly what the model was trained on. Parity with the
research harness is pinned by ``tests/test_ml_entry_adapter.py::test_features_match_research_harness`` (same frame in,
same numbers out); a change here without the harness (or the reverse) fails that test.

Every input is a CLOSED 1h bar at or before the decision bar: the caller passes frames whose last row is the decision
bar (the forming bar already dropped).
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional

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


def decision_row(symbol: str, frames: Mapping[str, pd.DataFrame]) -> Optional[Dict[str, float]]:
    """The 20-feature row for ``symbol`` at the last bar of ``frames[symbol]``; cross-sectional context from every
    frame whose last bar has the SAME timestamp (the reference symbols). ``None`` if the row cannot be formed."""
    own = frames.get(symbol)
    if own is None or len(own) < MIN_BARS:
        return None
    t = own["ts"].iloc[-1]
    fo = features_symbol(own).iloc[-1]
    r24, v24 = {}, {}
    for s, fr in frames.items():
        if fr is None or len(fr) < 25 or fr["ts"].iloc[-1] != t:
            continue
        ff = features_symbol(fr.iloc[-200:].reset_index(drop=True)).iloc[-1]
        r24[s], v24[s] = ff["ret24_raw"], ff["vol24"]
    if "BTCUSDT" not in r24 or symbol not in r24:
        return None
    rv = pd.Series(r24, dtype=float)
    vv = pd.Series(v24, dtype=float)
    rank = rv.rank(pct=True)
    row = {k: float(fo[k]) for k in FEATURES if k in fo.index}
    row["xs_rank_ret24"] = float(rank[symbol])
    row["btc_ret24"] = float(rv["BTCUSDT"])
    row["btc_vol24"] = float(vv["BTCUSDT"])
    row["breadth_up24"] = float((rv > 0).sum() / rv.notna().sum())
    row["rel_vol"] = float(fo["vol24"] / vv.median())
    if any(not np.isfinite(row.get(k, np.nan)) for k in FEATURES):
        return None
    row["_n_reference"] = float(len(rv))
    return row
