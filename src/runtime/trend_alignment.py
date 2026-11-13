"""TREND-ALIGN-V1, live-trader copy (row TREND-ALIGNMENT-FEATURE step 3).

The live ENTRY path stamps the prevailing-trend state onto an order package's ``meta`` (observe-only, never a gate). The
DEFINITION lives in ``docs/research/trend-alignment-framework-2026-11-13.md`` and the research labeller
``scripts/research/trend_alignment.py``; the live trader must not import ``scripts/``, so the pure functions are DUPLICATED
here and pinned EQUAL to the research module by ``tests/test_trend_align_parity.py`` (bit-for-bit on a fixture). A drift in
either side fails that test.

``meta_for_entry`` returns the compact dict the builder attaches as ``meta.trend_align``:
    {"definition": "TREND-ALIGN-V1", "LEG": {...}, "D1": {...}, "agreement": "...", "side": "long"|"short"}
It never raises and never gates: any missing input (no 1d candles, too little history) yields a null label with a reason.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

DEFINITION_ID = "TREND-ALIGN-V1"
ADX_PERIOD = 14
TREND_MIN_ADX = 25.0          # src/runtime/regime/detector.py::TREND_MIN_ADX
MIN_BARS = 30                 # src/runtime/regime/detector.py::_MIN_BARS
LABELS = ("with_trend", "counter_trend", "neutral")
MISSING_REASONS = ("no_candles", "insufficient_history", "adx_nan", "no_entry_time", "no_side", "no_timeframe")
TF_DELTA = {"1m": timedelta(minutes=1), "3m": timedelta(minutes=3), "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15), "30m": timedelta(minutes=30), "1h": timedelta(hours=1),
            "2h": timedelta(hours=2), "4h": timedelta(hours=4), "6h": timedelta(hours=6), "8h": timedelta(hours=8),
            "12h": timedelta(hours=12), "1d": timedelta(days=1)}


def dmi(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    """Wilder DMI (adx, pdi, mdi), aligned to df.index. Identical to scripts/research/trend_alignment.dmi, which is in
    turn copied from src/runtime/regime/detector.wilder_adx (ADX equality pinned by the parity + detector tests)."""
    h, low, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)) * down.clip(lower=0)
    pc = c.shift(1)
    tr = pd.concat([(h - low), (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=alpha, adjust=False).mean(), "pdi": pdi, "mdi": mdi}, index=df.index)


def regime_label(adx: Optional[float]) -> str:
    from src.runtime.regime.detector import regime_label as _rl
    return _rl(adx)


def _utc(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True)


def resample(base: pd.DataFrame, tf: str) -> pd.DataFrame:
    """OHLC bars of timeframe ``tf`` from a finer frame with tz-aware ``open_time``; adds ``close_time``. Left-closed,
    anchored to the UTC epoch — identical to the research resample."""
    d = TF_DELTA[tf]
    s = base.set_index("open_time").sort_index()
    out = s.resample(d, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    out["close_time"] = out["open_time"] + d
    return out


def closed_before(bars: pd.DataFrame, entry: pd.Timestamp) -> pd.DataFrame:
    return bars[bars["close_time"] <= entry]


def _missing(reason: str, **extra: Any) -> Dict[str, Any]:
    assert reason in MISSING_REASONS, reason
    return {"label": None, "missing_reason": reason, "adx": None, "pdi": None, "mdi": None, "regime_label": None,
            "bar_close_used": None, "n_bars_used": extra.get("n_bars_used")}


def label_tf(bars: Optional[pd.DataFrame], entry: Optional[pd.Timestamp], side: Optional[int]) -> Dict[str, Any]:
    """TREND-ALIGN-V1 for one timeframe. ``bars`` carry open_time/close_time/OHLC (tz-aware UTC); ``side`` is +1 / -1.
    Reads only bars CLOSED before ``entry``. Byte-identical to scripts/research/trend_alignment.label_tf."""
    if entry is None:
        return _missing("no_entry_time")
    if side not in (1, -1):
        return _missing("no_side")
    if bars is None or len(bars) == 0:
        return _missing("no_candles")
    hist = closed_before(bars, entry)
    if len(hist) < MIN_BARS:
        return _missing("insufficient_history", n_bars_used=int(len(hist)))
    last = dmi(hist).iloc[-1]
    adx, pdi, mdi = (float(last[k]) for k in ("adx", "pdi", "mdi"))
    if any(v != v for v in (adx, pdi, mdi)):
        return _missing("adx_nan", n_bars_used=int(len(hist)))
    if adx < TREND_MIN_ADX or pdi == mdi:
        label = "neutral"
    else:
        label = "with_trend" if int(np.sign(pdi - mdi)) == side else "counter_trend"
    return {"label": label, "missing_reason": None, "adx": round(adx, 4), "pdi": round(pdi, 4), "mdi": round(mdi, 4),
            "regime_label": regime_label(adx), "bar_close_used": hist["close_time"].iloc[-1].isoformat(),
            "n_bars_used": int(len(hist))}


def agreement(leg: Dict[str, Any], d1: Dict[str, Any]) -> str:
    a, b = leg.get("label"), d1.get("label")
    if a == b == "with_trend":
        return "both_with"
    if a == b == "counter_trend":
        return "both_counter"
    if {a, b} == {"with_trend", "counter_trend"}:
        return "split"
    return "other"


def side_of(direction: Any) -> Optional[int]:
    d = str(direction or "").strip().lower()
    return 1 if d in ("long", "buy") else -1 if d in ("short", "sell") else None


# ── live helper ───────────────────────────────────────────────────────────────────────────────────────────────────
def _as_bars(candles: Any) -> Optional[pd.DataFrame]:
    """A pipeline candle frame (timestamp/open/high/low/close, the bar's OPEN time) -> open_time/close_time/OHLC bars.
    Returns None when the frame is unusable. Never raises."""
    try:
        df = candles if hasattr(candles, "columns") else pd.DataFrame(candles)
        tcol = "timestamp" if "timestamp" in df.columns else ("open_time" if "open_time" in df.columns else None)
        if tcol is None or df.empty:
            return None
        ot = _utc(df[tcol])
        if pd.api.types.is_numeric_dtype(df[tcol]):
            ot = pd.to_datetime(df[tcol], unit="ms", utc=True)
        out = pd.DataFrame({"open_time": ot})
        for c in ("open", "high", "low", "close"):
            out[c] = pd.to_numeric(df[c], errors="coerce")
        out = out.dropna(subset=["high", "low", "close"]).sort_values("open_time").reset_index(drop=True)
        return out if len(out) else None
    except Exception:  # noqa: BLE001 — observe-only, never break a tick
        return None


def _infer_step(bars: Optional[pd.DataFrame]) -> Optional[pd.Timedelta]:
    if bars is None or len(bars) < 2:
        return None
    d = bars["open_time"].diff().dropna()
    return pd.Timedelta(d.median()) if len(d) else None


def meta_for_entry(candles_leg: Any, candles_d1: Any, direction: Any, timeframe: Optional[str]) -> Dict[str, Any]:
    """The ``meta.trend_align`` dict for an entry: the LEG-timeframe label (from the leg's own frame) and the D1 label
    (from a 1d frame), plus their agreement. The entry time is the leg frame's last bar close, so only CLOSED bars are
    read (matching TREND-ALIGN-V1 and the backfill labeller). Observe-only; any missing input yields a null label."""
    side = side_of(direction)
    base_leg = _as_bars(candles_leg)
    # LEG: the frame is already at the leg timeframe; build close_time from the inferred bar step.
    leg: Dict[str, Any]
    entry: Optional[pd.Timestamp] = None
    if base_leg is None:
        leg = _missing("no_candles")
    else:
        step = TF_DELTA.get(str(timeframe or "")) or _infer_step(base_leg)
        if step is None:
            leg = _missing("no_timeframe")
        else:
            lb = base_leg.copy()
            lb["close_time"] = lb["open_time"] + step
            entry = lb["close_time"].iloc[-1]                     # decide as of the last bar's close: labels on bars before it
            leg = label_tf(lb, entry, side)
    # D1: resample the 1d frame (or the leg frame if it is already daily) and label as of the same entry.
    d1_src = _as_bars(candles_d1) if candles_d1 is not None else (base_leg if str(timeframe) == "1d" else None)
    if d1_src is None:
        d1 = _missing("no_candles")
    else:
        d1b = resample(d1_src[["open_time", "open", "high", "low", "close"]], "1d")
        d1 = label_tf(d1b, entry if entry is not None else (d1b["close_time"].iloc[-1] if len(d1b) else None), side)
    return {"definition": DEFINITION_ID, "LEG": leg, "D1": d1, "agreement": agreement(leg, d1),
            "side": "long" if side == 1 else "short" if side == -1 else None}
