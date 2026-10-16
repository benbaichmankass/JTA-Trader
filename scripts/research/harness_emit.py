"""Shared OPT-IN emits for the backtest harnesses (Tier-1 research tooling).

Two builds live here so every harness that adopts them emits the SAME columns
with the SAME meaning:

* ``PathRecorder`` -- EXIT-PATH-EMIT-OFFLINE. One JSONL row per (trade, bar)
  from the bar after entry to the exit bar, driven from INSIDE the harness's
  own bar loop (no re-walk). Each row carries the bar in R from entry, the stop
  and target IN FORCE during that bar (so trailing, TP revision and lever exits
  are the leg's own), and the running state after the bar: open_r, peak_r (the
  harness's own ``mfe`` variable, so ``max(peak_r) == mfe_r`` by construction
  and the parity test pins that the recorder sees every bar), mae_r,
  bars_since_peak, ATR and ADX at the bar.

* ``DecisionContext`` -- METALABEL-EMIT-FEATURES. Decision-time context columns
  at the ENTRY bar, computed with the live detectors' own primitives
  (``src.runtime.regime.detector.wilder_adx`` / ``regime_label`` and
  ``src.runtime.regime_shadow.rolling_log_return_vol``) rather than lookalikes.

BOTH ARE OFF BY DEFAULT. A harness only constructs these objects when its
``--emit-paths`` / ``--emit-features`` flag is passed, so a run without the
flags allocates nothing here and its outputs stay byte-identical
(tests/test_harness_emit.py pins that for both harnesses).

Conventions (all R values are DIRECTION-SIGNED: + is favourable):
  * ``fav_r`` / ``adv_r`` -- the bar's favourable / adverse extreme in R
    (high/low for a long, low/high for a short).
  * ``stop_r`` / ``target_r`` -- the levels the bar was TESTED against
    (in force entering the bar). ``target_r`` is None when no target exists.
  * ``peak_r`` / ``mae_r`` / ``open_r`` / ``bars_since_peak`` -- state AFTER
    the bar, i.e. what a decision at the next bar's open would know.
  * MAE on the exit bar: a stop/trail exit fills AT the stop, so the adverse
    extreme counted on that bar is capped at the exit price; every other exit
    counts the bar's full range (the harness assumes it traded through it).

What this does NOT carry: the live ``vol_regime`` (calm/volatile) needs the
deployed head's frozen bucket edges from the model registry, which an offline
harness run does not have. ``f_regime_cell`` is therefore the trend label x the
TRAILING ATR-percentile tercile -- a stated offline proxy, never the live cell.
Funding z and ``fc_*`` are not in the harness's candle frame and are omitted
rather than emitted as fabricated nulls-that-look-measured.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PATH_SCHEMA = "harness_path_v1"
FEATURES_SCHEMA = "harness_decision_v1"

# Exit reasons that fill AT the stop level (MAE capped at the exit price).
_STOP_EXITS = frozenset({"stop", "trail_stop"})


def _r(px: float, entry: float, risk: float, is_long: bool) -> float:
    return ((px - entry) if is_long else (entry - px)) / risk


def _rnd(x: Optional[float], nd: int = 4) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f, nd)


def _wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    # The live regime detector's ADX -- one implementation, imported lazily so a
    # flag-off run never pays the import.
    from src.runtime.regime.detector import wilder_adx
    return wilder_adx(df, period=period).reset_index(drop=True)


class PathRecorder:
    """Collects per-bar in-trade path rows from inside a harness bar loop.

    Usage inside the harness (one recorder per RUN, ``start`` per trade)::

        rec.start(trade_key=..., entry_i=..., entry=..., risk=..., is_long=...)
        for j in ...:
            rec.bar(j, stop=trail, target=tp_price, peak_r=mfe, peak_j=peak_j)
            ... harness body, possibly ``break`` ...
        rec.finish(exit_idx, exit_price, exit_reason, peak_r=mfe, peak_j=peak_j)

    ``bar(j)`` FIRST closes the previous bar's row with the state as it stands
    at the top of iteration j (= the end state of bar j-1), then opens bar j
    with the stop/target in force during it. ``finish`` closes the last open
    row (the exit bar, or the timeout bar) with the final state. So every
    in-trade bar the loop visits yields exactly one row, whichever ``break``
    ended the loop.
    """

    def __init__(self, df: pd.DataFrame, *, strategy: str, symbol: str,
                 keep_rows: bool, adx_period: int = 14) -> None:
        self._ts = df["timestamp"].reset_index(drop=True)
        self._o = df["open"].to_numpy(dtype=float) if "open" in df else df["close"].to_numpy(dtype=float)
        self._h = df["high"].to_numpy(dtype=float)
        self._l = df["low"].to_numpy(dtype=float)
        self._c = df["close"].to_numpy(dtype=float)
        self._atr = (df["atr"].to_numpy(dtype=float) if "atr" in df else None)
        self._adx = _wilder_adx(df, adx_period).to_numpy(dtype=float)
        self.strategy = strategy
        self.symbol = symbol
        self.keep_rows = keep_rows
        self.rows: List[Dict[str, Any]] = []
        self._trade: Optional[Dict[str, Any]] = None
        self._pending: Optional[Dict[str, Any]] = None
        self._worst = 0.0

    # -- per trade --------------------------------------------------------- #
    def start(self, *, trade_key: str, entry_i: int, entry: float, risk: float,
              is_long: bool) -> None:
        self._trade = dict(key=trade_key, entry_i=entry_i, entry=entry,
                           risk=risk, is_long=is_long)
        self._pending = None
        self._worst = 0.0
        self._trade_rows: List[Dict[str, Any]] = []

    def _close_pending(self, *, peak_r: float, peak_j: int,
                       exit_price: Optional[float] = None,
                       exit_reason: Optional[str] = None) -> None:
        p = self._pending
        if p is None:
            return
        t = self._trade
        j = p["bar_index"]
        adv = self._pending_adv
        if exit_reason is not None and exit_reason in _STOP_EXITS and exit_price is not None:
            adv = max(adv, _r(exit_price, t["entry"], t["risk"], t["is_long"]))
        self._worst = min(self._worst, adv)
        close_px = exit_price if exit_price is not None else self._c[j]
        p["open_r"] = round(_r(close_px, t["entry"], t["risk"], t["is_long"]), 6)
        p["peak_r"] = round(float(peak_r), 6)
        p["mae_r"] = round(max(0.0, -self._worst), 6)
        p["bars_since_peak"] = int(j - peak_j)
        if exit_reason is not None:
            p["is_exit"] = True
            p["exit_reason"] = exit_reason
        self._trade_rows.append(p)
        self._pending = None

    def bar(self, j: int, *, stop: float, target: Optional[float],
            peak_r: float, peak_j: int) -> None:
        self._close_pending(peak_r=peak_r, peak_j=peak_j)
        t = self._trade
        e, rk, lg = t["entry"], t["risk"], t["is_long"]
        hi_r, lo_r = _r(self._h[j], e, rk, lg), _r(self._l[j], e, rk, lg)
        fav, adv = (hi_r, lo_r) if lg else (lo_r, hi_r)
        atr_j = None if self._atr is None else self._atr[j]
        self._pending_adv = adv     # unrounded: MAE accumulates on the raw value
        self._pending = {
            "schema": PATH_SCHEMA,
            "trade_key": t["key"], "strategy": self.strategy, "symbol": self.symbol,
            "bar_index": int(j), "bar_offset": int(j - t["entry_i"]),
            "ts": str(self._ts.iloc[j]),
            "o_r": round(_r(self._o[j], e, rk, lg), 4),
            "c_r": round(_r(self._c[j], e, rk, lg), 4),
            "fav_r": round(fav, 4), "adv_r": round(adv, 4),
            "stop_r": round(_r(stop, e, rk, lg), 4),
            "target_r": None if target is None else round(_r(target, e, rk, lg), 4),
            "dist_to_stop_r": round(_r(self._c[j], e, rk, lg) - _r(stop, e, rk, lg), 4),
            "dist_to_target_r": (None if target is None
                                 else round(_r(target, e, rk, lg) - _r(self._c[j], e, rk, lg), 4)),
            "atr_r": _rnd(None if atr_j is None else atr_j / rk),
            "adx_14": _rnd(self._adx[j]),
            "is_exit": False,
        }

    def finish(self, exit_idx: int, exit_price: float, exit_reason: str, *,
               peak_r: float, peak_j: int) -> Dict[str, Any]:
        """Close the trade. Returns the per-trade summary (``mae_r``, ``n_path_rows``)."""
        t = self._trade
        if self._pending is not None:
            # The last bar the loop visited IS the exit bar on every exit path
            # (break or timeout). A mismatch means the harness wired the
            # recorder wrongly -- fail loudly rather than emit a short path.
            if self._pending["bar_index"] != exit_idx:
                raise ValueError(f"path recorder: last visited bar {self._pending['bar_index']} "
                                 f"!= exit bar {exit_idx} for {t['key']}")
            self._close_pending(peak_r=peak_r, peak_j=peak_j,
                                exit_price=exit_price, exit_reason=exit_reason)
        else:
            # Exited on the entry bar (entry_override rest-hit) -- no in-trade
            # bar was visited. MAE is what the fill itself realised.
            self._worst = min(self._worst, _r(exit_price, t["entry"], t["risk"], t["is_long"]))
        out = {"mae_r": round(max(0.0, -self._worst), 3),
               "n_path_rows": len(self._trade_rows)}
        if self.keep_rows:
            self.rows.extend(self._trade_rows)
        self._trade = None
        return out

    def write(self, path: str) -> int:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(json.dumps(row, default=str) + "\n")
        return len(self.rows)


def trade_key(strategy: str, symbol: str, entry_time: Any, direction: str) -> str:
    """The join key between a path row and its ``--emit-trades`` row."""
    return f"{strategy}|{symbol}|{entry_time}|{direction}"


class DecisionContext:
    """Decision-time context columns at an entry bar (precomputed once per run)."""

    def __init__(self, df: pd.DataFrame, *, pctl_window: int = 200,
                 ret_lookback: int = 20, vol_window_n: int = 20,
                 adx_period: int = 14) -> None:
        self._ts = df["timestamp"].reset_index(drop=True)
        self._c = df["close"].to_numpy(dtype=float)
        self._adx = _wilder_adx(df, adx_period).to_numpy(dtype=float)
        atr = df["atr"].reset_index(drop=True).astype(float)
        self._atr = atr.to_numpy()
        # Trailing rank of ATR within the previous `pctl_window` bars, the bar
        # itself included -- the same causal construction the harnesses' vol
        # levers use. NaN until the window fills (emitted as null, honestly).
        self._atr_pctl = atr.rolling(pctl_window, min_periods=pctl_window).rank(pct=True).to_numpy()
        self.pctl_window = pctl_window
        self.ret_lookback = ret_lookback
        self.vol_window_n = vol_window_n

    def at(self, i: int) -> Dict[str, Any]:
        from src.runtime.regime.detector import regime_label
        from src.runtime.regime_shadow import rolling_log_return_vol

        adx = _rnd(self._adx[i])
        regime = regime_label(adx)
        pctl = _rnd(self._atr_pctl[i])
        bucket = None
        if pctl is not None:
            bucket = "low" if pctl < 1.0 / 3.0 else ("mid" if pctl < 2.0 / 3.0 else "high")
        c = self._c[i]
        atr = self._atr[i]
        lo = i - self.ret_lookback
        ret = (c / self._c[lo] - 1.0) if lo >= 0 and self._c[lo] > 0 else None
        vol = rolling_log_return_vol(list(self._c[max(0, i - self.vol_window_n): i + 1]),
                                     self.vol_window_n)
        if (i - self.vol_window_n) < 0:
            vol = None   # under a full window: not the live quantity, so not emitted
        ts = pd.Timestamp(self._ts.iloc[i])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return {
            "features_schema": FEATURES_SCHEMA,
            "f_adx_14": adx,
            "f_regime": regime,
            "f_atr_pct": _rnd(atr / c * 100.0 if c > 0 and atr == atr else None, 5),
            "f_atr_pctl": pctl,
            "f_atr_pctl_bucket": bucket,
            "f_regime_cell": None if regime == "unknown" or bucket is None else f"{regime}|{bucket}",
            "f_rlr_vol_20": _rnd(vol, 8),
            "f_ret_20": _rnd(ret, 5),
            "f_hour_utc": int(ts.hour),
            "f_dow_utc": int(ts.dayofweek),
        }
