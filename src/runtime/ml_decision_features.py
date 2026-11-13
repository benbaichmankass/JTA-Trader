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
#: The default cross-sectional anchor (``btc_ret24`` / ``btc_vol24``): the symbol the v1/v2 artifacts were trained on.
ANCHOR = "BTCUSDT"
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


def regrid_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """A 24/7 perp's bars on a complete hourly grid, so a data hole becomes NaN bars instead of a seam (row
    ML-ENTRY-SERVING-HOLE-GUARD; the serving twin of ``scripts/research/ml_decision_entry.regrid_hourly``, the
    ``build_table(hole_safe=True)`` step). Without it the positional rolling features (ret_k, vol_ratio, vol_z,
    range_pos, atr_pct) silently span the hole: MEASURED in research, one 2026-10-28 hole moved a 14-day grade from
    -0.2127 to -0.1316. A row whose windows touch a NaN bar is non-finite, so ``decision_row`` returns None for that
    symbol on that tick (``feature_row_unformable``) -- a per-tick skip, never a halt -- and the symbol trades again
    once its windows have cleared the hole. A CONTIGUOUS frame is returned AS IS (the same object), so every
    hole-free decision is byte-identical to the pre-guard build. Used on the equal-timestamp (perp) path only: an
    equity frame on the as-of path has legitimate session gaps and is never regridded."""
    if df is None or len(df) < 2:
        return df
    ts = df["ts"]
    if ts.is_monotonic_increasing and not ts.duplicated().any() and (ts.iloc[-1] - ts.iloc[0]) == pd.Timedelta(hours=len(df) - 1):
        return df
    d = df.drop_duplicates("ts", keep="last").sort_values("ts")
    full = pd.date_range(d["ts"].iloc[0], d["ts"].iloc[-1], freq="1h")
    return d.set_index("ts").reindex(full).rename_axis("ts").reset_index()


def atr_last(df: pd.DataFrame, n: int = ATR_N) -> float:
    """ATR14 (simple mean of true range) at the last bar, as the harness labels it."""
    h, lo, c = (df[k].astype(float) for k in ("high", "low", "close"))
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n, min_periods=n).mean().iloc[-1])


def _asof(fr: pd.DataFrame, close_ts: pd.Timestamp) -> pd.DataFrame:
    """``fr`` truncated to the bars CLOSED at or before ``close_ts`` (a 1h bar opening at ts closes at ts + 1h)."""
    return fr[fr["ts"] + pd.Timedelta(hours=1) <= close_ts]


def _same_ts_row(symbol: str, frames: Mapping[str, pd.DataFrame], anchor: str = ANCHOR) -> Optional[Dict[str, float]]:
    """The pre-2026-11-01 rule, unchanged: cross-sectional context from every frame whose last bar has the SAME
    timestamp as ``symbol``'s (``symbol`` itself among them). ``ml_decision_shadow.decision_rows`` is pinned
    bit-identical to this."""
    own = frames.get(symbol)
    if own is None or len(own) < MIN_BARS:
        return None
    t = own["ts"].iloc[-1]
    fo = features_symbol(regrid_hourly(own)).iloc[-1]
    r24, v24 = {}, {}
    for s, fr in frames.items():
        if fr is None or len(fr) < 25 or fr["ts"].iloc[-1] != t:
            continue
        ff = features_symbol(regrid_hourly(fr.iloc[-200:].reset_index(drop=True))).iloc[-1]
        r24[s], v24[s] = ff["ret24_raw"], ff["vol24"]
    if anchor not in r24 or symbol not in r24:
        return None
    rv = pd.Series(r24, dtype=float)
    vv = pd.Series(v24, dtype=float)
    rank = rv.rank(pct=True)
    row = {k: float(fo[k]) for k in FEATURES if k in fo.index}
    row["xs_rank_ret24"] = float(rank[symbol])
    row["btc_ret24"] = float(rv[anchor])
    row["btc_vol24"] = float(vv[anchor])
    row["breadth_up24"] = float((rv > 0).sum() / rv.notna().sum())
    row["rel_vol"] = float(fo["vol24"] / vv.median())
    if any(not np.isfinite(row.get(k, np.nan)) for k in FEATURES):
        return None
    row["_n_reference"] = float(len(rv))
    return row


def decision_row(symbol: str, frames: Mapping[str, pd.DataFrame],
                 reference: Optional[Iterable[str]] = None, anchor: str = ANCHOR) -> Optional[Dict[str, float]]:
    """The 20-feature row for ``symbol`` at the last bar of ``frames[symbol]``. ``None`` if it cannot be formed.

    ``reference``: the model's reference symbols (``meta["xs_reference"]``). A symbol IN the reference set (every
    bybit perp), or ``reference=None``, takes the unchanged same-timestamp rule (``_same_ts_row``), so the real-money
    bybit_2 path and the shadow decision log are byte-for-byte what they were. Only a symbol OUTSIDE it (an ETF on
    alpaca_paper, row ALPACA-LIVE-ACTIVITY-ML) reads the references AS-OF its bar's close: each reference frame is cut
    to its bars closed at or before it and used only if its last closed bar closed within the hour before it; the
    symbol's 24-bar return is ranked among the references with itself inserted, and breadth / median vol are the
    references' -- the definition scripts/research/ml_entry_alpaca_score.py scored.

    ``anchor``: the symbol behind the ``btc_ret24`` / ``btc_vol24`` columns (row ML-ENTRY-ALL-ACCOUNTS: per-account
    config via ``src/runtime/ml_entry_profile.py``). Default ``BTCUSDT``, the symbol the artifact was trained on."""
    if reference is None or symbol in set(reference):
        return _same_ts_row(symbol, frames, anchor)
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
    if anchor not in r24:
        return None
    rv_ref = pd.Series(r24, dtype=float)
    vv_ref = pd.Series(v24, dtype=float)
    fx = features_symbol(own.iloc[-200:].reset_index(drop=True)).iloc[-1]
    rv = pd.concat([rv_ref, pd.Series({symbol: float(fx["ret24_raw"])})])
    rank = rv.rank(pct=True)
    row = {k: float(fo[k]) for k in FEATURES if k in fo.index}
    row["xs_rank_ret24"] = float(rank[symbol])
    row["btc_ret24"] = float(rv_ref[anchor])
    row["btc_vol24"] = float(vv_ref[anchor])
    row["breadth_up24"] = float((rv_ref > 0).sum() / rv_ref.notna().sum())
    row["rel_vol"] = float(fo["vol24"] / vv_ref.median())
    if any(not np.isfinite(row.get(k, np.nan)) for k in FEATURES):
        return None
    row["_n_reference"] = float(len(rv))
    return row
