"""index_capitulation_1x — daily-bar, long-only capitulation-bounce leg on 1x index ETFs (row INDEX-CAPIT-1X-LEG).

THE SPEC (frozen; ``comms/research/INDEX-CAPIT-1X-LEG/spec.json``, PR #28680)
--------------------------------------------------------------------------------
* Flush bar: ``close <= mean(close, 5) - 1.5 x ATR14`` AND ``low < min(low of the prior 20 bars)``.
  ATR14 is the SIMPLE 14-bar mean of the true range (the harness's ``_atr``; not Wilder).
* Signal bar: the first up-close (``close > previous close``) within 5 sessions after the flush bar.
* Entry: the NEXT session's open (signal bar i -> entry bar i+1). Live, the leg decides on the CLOSED daily bars and enters on the
  first tick of the entry session, at the current price (= the open on the first tick).
* Stop: the lowest low from the flush bar through the signal bar. Skipped when the stop is not below the entry or the risk is under
  0.25% of the entry.
* Take-profit: ``entry + K* x risk``, K* per ticker (``k_star`` in ``config/strategies.yaml``; calibrated on the first 60% of that
  ticker's no-TP trades in the evidence, never 50 -- TP doctrine).
* Hold cap: 10 sessions including the entry session; the harness exits at the 10th session's close. ``monitor()`` closes in the last
  minutes of the 10th session (and at once if a session was missed).
* One position per ticker; long only; 1x; no filter (the SMA200 and credit-spread gates FAILED their out-of-time reads, 1e06-09/-11).

PARITY
------
``capitulation_signals`` is a line-for-line port of ``scripts/research/index_signal_etf_harness.py::signals_capitulation`` with
``flush_atr = FLUSH_ATR_WIDE`` (1.5). ``tests/test_index_capitulation_1x.py`` pins the port against the harness function on
generated frames, and ``scripts/research/index_capit_live_parity.py`` replays the evidence trades through ``order_package`` and
writes ``comms/research/INDEX-CAPIT-1X-LEG/live_parity.json``.

Pure signal generator: knows nothing about accounts, sizing or dry/live (``_base`` contract). Sizing is the RiskManager's.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

NAME = "index_capitulation_1x"

# --- registered parameters (copied from the harness; changing one here is a different strategy) --------------------------------
DONCHIAN = 20
ATR_LEN = 14
FLUSH_MEAN = 5
FLUSH_ATR = 1.5            # harness FLUSH_ATR_WIDE (family capitulation_wide)
FLUSH_UP_WINDOW = 5
HOLD_CAP_SESSIONS = 10
MIN_RISK_FRAC = 0.0025
#: minutes before the 16:00 ET close at which the 10th session's hold-cap close is sent (the harness exits at that close)
HOLD_CAP_CLOSE_MINUTES_BEFORE = 10


def _p(cfg: Dict[str, Any], key: str, default: Any) -> Any:
    v = (cfg or {}).get(key)
    return default if v is None else v


# ----------------------------------------------------------------------------------------------------------- signal (the port)
def _atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def capitulation_signals(h: np.ndarray, lo: np.ndarray, c: np.ndarray, flush_atr: float = FLUSH_ATR) -> List[Dict[str, Any]]:
    """Every signal bar in the frame: ``[{"i", "flush_i", "stop"}]``. Bar ``i`` needs a bar ``i+1`` (the entry bar), so the last row
    of the frame is never a signal bar: live, that row is the forming entry-session bar. Port of the harness's
    ``signals_capitulation`` (same loop bounds, same state machine); ``flush_i`` is added for the audit trail only."""
    h, lo, c = (np.asarray(x, dtype=float) for x in (h, lo, c))
    n = len(c)
    atr = _atr(h, lo, c, ATR_LEN)
    m5 = pd.Series(c).rolling(FLUSH_MEAN).mean().to_numpy()
    out: List[Dict[str, Any]] = []
    start: Optional[int] = None
    for i in range(max(DONCHIAN, ATR_LEN) + 1, n - 1):
        flush = (not np.isnan(atr[i])) and c[i] <= m5[i] - flush_atr * atr[i] and lo[i] < np.min(lo[i - DONCHIAN:i])
        if start is not None and i - start > FLUSH_UP_WINDOW:
            start = None
        if start is None:
            if flush:
                start = i
            continue
        if c[i] > c[i - 1]:
            out.append({"i": i, "flush_i": start, "stop": float(np.min(lo[start:i + 1]))})
            start = None
    return out


# --------------------------------------------------------------------------------------------------------------- frame helpers
def _session_dates(candles_df: Any) -> List[Any]:
    """US session date of each daily row. A venue daily bar is stamped at midnight ET (04:00/05:00Z) or 00:00Z on its session date,
    so the UTC calendar date IS the session date either way (converting to ET would move a 00:00Z stamp to the previous day).
    A tz-naive stamp is read as the session date itself."""
    if "timestamp" in getattr(candles_df, "columns", []):
        raw = pd.Series(candles_df["timestamp"])
        if pd.api.types.is_numeric_dtype(raw):
            unit = "ms" if float(raw.iloc[-1]) > 1e11 else "s"
            ts = pd.DatetimeIndex(pd.to_datetime(raw, unit=unit, utc=True))
        else:
            ts = pd.DatetimeIndex(pd.to_datetime(raw))
    else:
        ts = pd.DatetimeIndex(pd.to_datetime(pd.Series(candles_df.index)))
    if ts.tz is not None:
        ts = ts.tz_convert("UTC")
    return [t.date() for t in ts]


def _ohlc(candles_df: Any) -> tuple:
    return tuple(candles_df[col].to_numpy(dtype=float) for col in ("open", "high", "low", "close"))


# --------------------------------------------------------------------------------------------------------------------- package
def order_package(cfg: dict, candles_df: Any = None) -> dict:
    """The entry package for the entry session, or ``ValueError`` (no actionable signal).

    ``candles_df``: daily bars whose LAST row is the entry session's forming bar (the signal builder guarantees it via
    ``_fetch_session_frame``). The signal is decided on the closed rows only; the entry reference is the forming bar's latest close.
    """
    from src.units.strategies._base import require_candles

    df = require_candles(candles_df, NAME)
    symbol = str(_p(cfg, "symbol", "") or "")
    k_map = _p(cfg, "k_star", {}) or {}
    if symbol not in k_map:
        raise ValueError(f"no_k_star_for_symbol:{symbol}")
    k = float(k_map[symbol])
    if not (k > 0 and k < 50):
        raise ValueError(f"k_star_out_of_range:{symbol}:{k}")
    if len(df) < max(DONCHIAN, ATR_LEN) + 3:
        raise ValueError(f"insufficient_bars:{len(df)}")
    _o, h, lo, c = _ohlc(df)
    sigs = capitulation_signals(h, lo, c, float(_p(cfg, "flush_atr", FLUSH_ATR)))
    last_closed = len(df) - 2
    if not sigs or sigs[-1]["i"] != last_closed:
        raise ValueError("no_signal_on_last_closed_bar")
    sig = sigs[-1]
    entry = float(c[-1])                      # current price of the forming entry-session bar (the open on its first tick)
    stop = float(sig["stop"])
    if not stop < entry:
        raise ValueError(f"stop_wrong_side_at_entry: stop {stop} >= entry {entry}")
    risk = entry - stop
    if not (risk > 0 and risk / entry >= MIN_RISK_FRAC and stop > 0):
        raise ValueError(f"risk_degenerate: risk {risk:.4f} on entry {entry}")
    tp = entry + k * risk
    dates = _session_dates(df)
    hold_cap = int(_p(cfg, "hold_cap_sessions", HOLD_CAP_SESSIONS))
    return {
        "symbol": symbol,
        "direction": "long",
        "entry": entry,
        "sl": stop,
        "tp": tp,
        "confidence": float(_p(cfg, "confidence", 1.0)),
        "meta": {
            "strategy_name": NAME,
            "timeframe": "1d",
            "signal_date": str(dates[last_closed]),
            "flush_date": str(dates[sig["flush_i"]]),
            "entry_session": str(dates[-1]),
            "entry_time": str(dates[-1]),          # signal identity (order_bridge.signal_key_for_package)
            "entry_open": float(_o[-1]),
            "risk_per_unit": risk,
            "k_star": k,
            "tp_r": k,
            "tp_basis": f"per-ticker K* {k} x risk, calibrated on the first 60% of {symbol}'s no-TP evidence trades "
                        "(comms/research/INDEX-CAPIT-1X-LEG/spec.json; TP doctrine)",
            "hold_cap_sessions": hold_cap,
            "rule": "INDEX-CAPIT-1X-LEG spec (capitulation_wide, 1x, unfiltered); evidence RQ-20261124-1e06-06 + 1e06-08",
        },
    }


# --------------------------------------------------------------------------------------------------------------------- monitor
def _now() -> datetime:
    return datetime.fromtimestamp(time.time(), tz=timezone.utc)


def sessions_held(candles_df: Any, entry_session: str) -> Optional[int]:
    """Sessions from the entry session through the frame's last row, both counted. ``None`` when unreadable."""
    try:
        if candles_df is None or len(candles_df) == 0:
            return None
        want = pd.Timestamp(entry_session).date()
        return int(sum(1 for d in _session_dates(candles_df) if d >= want))
    except Exception:  # noqa: BLE001
        return None


def monitor(cfg: dict, candles_df: Any, open_pkg: dict) -> Optional[dict]:
    """The 10-session hold cap; the resting SL/TP at the broker are the rest of the plan (no trail, no retarget). Never raises.

    Closes when the frame's last row is the 10th session and the time is within ``HOLD_CAP_CLOSE_MINUTES_BEFORE`` of the close
    (the harness exits at the 10th session's close), or at once in RTH when more than 10 sessions have printed (a missed close).
    Outside regular hours it returns ``None`` (the venue cannot fill a market close; the bracket stays armed).
    """
    try:
        from src.runtime.market_hours import us_equity_session

        meta = open_pkg.get("meta") or {}
        entry_session = meta.get("entry_session")
        if not entry_session:
            return None
        now = _now()
        if us_equity_session(now) != "rth":
            return None
        cap = int(meta.get("hold_cap_sessions") or _p(cfg, "hold_cap_sessions", HOLD_CAP_SESSIONS))
        held = sessions_held(candles_df, entry_session)
        if held is None:
            return None
        if held > cap:
            return {"action": "close", "reason": f"{NAME}_hold_cap_{cap}_sessions_missed_close"}
        if held == cap:
            from src.runtime.market_hours import _FULL_DST_MONTHS
            et = now.hour * 60 + now.minute - (4 if now.month in _FULL_DST_MONTHS else 5) * 60
            if et >= 16 * 60 - HOLD_CAP_CLOSE_MINUTES_BEFORE:
                return {"action": "close", "reason": f"{NAME}_hold_cap_{cap}_sessions"}
    except Exception:  # noqa: BLE001
        return None
    return None
