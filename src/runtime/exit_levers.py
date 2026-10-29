"""The M20 R-based exit levers, owned in ONE place.

`stale_stop` and `giveback_stop` lived only inside
`src/units/strategies/trend_donchian.py`, so the pullback family could not run
them however its YAML was written — while `scripts/backtest_pullback.py` HAS
modelled both since M20. That asymmetry is the defect: **the harness simulated a
book the live module could not execute**, which is the usual live-vs-train
complaint running backwards, and it makes any sweep result recommending
`stale_exit_bars` for a pullback leg unactionable — declaring it would produce
an ORPHANED DECLARE, a YAML key nothing reads.

Measured 2026-08-18 (`scripts/ops/exit_path_coverage.py`): 22 of 34 open trades
had no decision-driven exit path at all, and 11 of those are the pullback
family, whose unit implements exactly one of the four M20 mechanisms.

This module is the same shape `src/runtime/trail_decay.py` and
`src/runtime/trail_vol.py` already established — a lever both units import
rather than each owning a copy. The bodies here are `trend_donchian`'s,
moved VERBATIM: the only edits are the two donchian-specific pieces, and both
are now parameters rather than literals (`default_label` for the annotate row,
`since_entry` resolved here instead of per-module). trend_donchian's behaviour
must be, and is asserted to be, unchanged — it trades real money.

**This also collapses a duplicate.** `_since_entry` existed in BOTH unit
modules, byte-identical apart from its docstring. Two copies of a window
definition that every R measurement depends on is exactly what
`_regime_score_semantics.py` had to be written to stop.

THE DECLARE IS STILL THE GATE, unchanged from donchian's contract. A leg whose
YAML declares the lever gets a REAL close; an undeclared leg evaluates the
reference cell and writes one observe-only row to
`runtime_logs/exit_lever_soak.jsonl`, returning None. So importing this module
changes NO behaviour on its own — shipping it is inert until an operator
declares a key, which is the Tier-3 decision.

⚠️ **PRECEDENCE IS THE CALLER'S, AND THE TWO FAMILIES DISAGREE TODAY.** Both
harnesses evaluate giveback BEFORE stale (`backtest_trend.py` lines ~566/582 in
one per-bar loop; `backtest_pullback._levers` giveback → trend_flip → stale),
while live `trend_donchian.monitor` runs stale BEFORE giveback under a comment
claiming it "matches the harness's exit precedence" — it does not. Field beats
comment. This is LATENT, not active: no live leg declares both keys (checked
2026-08-18 against `config/strategies.yaml` — stale-only on 3 legs,
giveback-only on 1, both on none), and when only one is declared the order
cannot matter. It is filed as
BL-20260818-LIVE-DONCHIAN-INVERTS-THE-HARNESS-LEVER-PRECEDENCE rather than
fixed here, because flipping a live-money family's exit order is Tier-3 and
must not ride along inside a refactor. New callers should follow their OWN
harness.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pandas as pd

# Reference cells for the observe-only annotate soak — used ONLY when a leg has
# NOT declared its own params. A declared leg uses exactly what its YAML says.
# Values are trend_donchian's, moved unchanged so the soak corpus stays one
# series rather than splitting at this commit.
STALE_REF_BARS = 8
STALE_REF_BELOW_R = 0.0
GIVEBACK_REF_MIN_MFE_R = 1.0
GIVEBACK_REF_GIVEBACK_R = 1.0

_STALE_REF_BARS = STALE_REF_BARS
_STALE_REF_BELOW_R = STALE_REF_BELOW_R
_GIVEBACK_REF_MIN_MFE_R = GIVEBACK_REF_MIN_MFE_R
_GIVEBACK_REF_GIVEBACK_R = GIVEBACK_REF_GIVEBACK_R


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def closed_frame(candles_df: Any, meta: Dict[str, Any], cfg_dict: Dict[str, Any]) -> Any:
    """``candles_df`` without its still-forming last bar, keyed on the leg's
    ``timeframe`` (meta first, then cfg). Unchanged when the timeframe is unknown
    or the last bar has closed. Never raises."""
    try:
        from src.runtime.closed_bars import drop_forming_bar

        tf = str((meta or {}).get("timeframe") or (cfg_dict or {}).get("timeframe") or "")
        return drop_forming_bar(candles_df, tf) if tf else candles_df
    except Exception:  # noqa: BLE001 — trimming must never break a lever
        return candles_df


#: ``DataFrame.attrs`` key ``since_entry`` stamps on what it returns: ``True``
#: when the frame really is restricted to the trade (entry time and timestamps
#: both readable), ``False`` on the full-frame fallback. Telemetry reads it so
#: a fallback frame reports ``unanchored`` instead of a measured pre-entry peak.
SINCE_ENTRY_ANCHORED_ATTR = "since_entry_anchored"


def _bar_seconds(candles_df: Any, ts: Any, meta: Dict[str, Any]) -> Optional[float]:
    """Bar length in seconds: the leg's declared ``timeframe`` first, else the
    median spacing of the frame's timestamps. ``None`` when neither is readable."""
    try:
        from src.runtime.closed_bars import TF_SECONDS

        tf = str((meta or {}).get("timeframe") or "")
        if tf in TF_SECONDS:
            return float(TF_SECONDS[tf])
    except Exception:  # noqa: BLE001
        pass
    try:
        diffs = ts.dropna().diff().dropna().dt.total_seconds()
        diffs = diffs[diffs > 0]
        if len(diffs) == 0:
            return None
        return float(diffs.median())
    except Exception:  # noqa: BLE001
        return None


def _stamp(frame: Any, anchored: bool) -> Any:
    """Return ``frame`` carrying the anchored flag in ``attrs`` — on a shallow
    copy with its own attrs dict, so the caller's frame is never mutated."""
    try:
        out = frame.copy(deep=False)
        out.attrs = {**dict(getattr(frame, "attrs", {}) or {}),
                     SINCE_ENTRY_ANCHORED_ATTR: bool(anchored)}
        return out
    except Exception:  # noqa: BLE001
        return frame


def since_entry_is_anchored(window: Any) -> bool:
    """False only when ``window`` is a ``since_entry`` full-frame fallback.
    A frame ``since_entry`` never touched reads True (the caller's own claim
    stands)."""
    try:
        return getattr(window, "attrs", {}).get(SINCE_ENTRY_ANCHORED_ATTR, True) is not False
    except Exception:  # noqa: BLE001
        return True


def since_entry(candles_df: pd.DataFrame, open_pkg: Dict[str, Any]) -> pd.DataFrame:
    """Restrict the candle window to the bars of the trade: the bar that
    CONTAINS the entry (``bar_open <= entry_time < bar_open + tf``) and every
    bar after it.

    The Chandelier trail tracks the extreme SINCE ENTRY; the fetched
    window (limit=200) includes pre-entry bars whose extreme would
    move the trail too far.

    SINCE-ENTRY-WINDOW-FIX (2026-10-29): when the entry time and the
    timestamps are readable the result is ALWAYS the filtered frame — possibly
    0 or 1 rows in the first bar of a trade. It used to fall back to the FULL
    frame whenever the filter came back empty, which is exactly the first bar
    after every entry (no CLOSED bar yet opens at/after the entry): every
    caller then measured ~200 PRE-ENTRY bars as the trade (SLV pkg-3df9800b:
    bars_held 199, a pre-entry peak_r, and a false STALL wake two minutes
    after the fill). Callers degrade a 0/1-row window to "no trail move /
    thin_window".

    The full-frame fallback remains ONLY when the entry time or the timestamp
    column is genuinely unavailable; that frame carries
    ``attrs[SINCE_ENTRY_ANCHORED_ATTR] = False`` so telemetry reports it
    ``unanchored`` (``since_entry_is_anchored``). The caller's
    correct-side-of-price guard still prevents an instant stop-out there.
    """
    meta = open_pkg.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta) if meta else {}
        except Exception:  # noqa: BLE001
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    entry_ts = meta.get("entry_time") or open_pkg.get("created_at")
    if entry_ts is None or "timestamp" not in getattr(candles_df, "columns", []):
        return _stamp(candles_df, False)
    try:
        ts = pd.to_datetime(candles_df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.to_datetime(entry_ts, utc=True, errors="coerce")
        if pd.isna(cutoff) or ts.isna().all():
            return _stamp(candles_df, False)
        bar_s = _bar_seconds(candles_df, ts, meta)
        if bar_s and bar_s > 0:
            mask = ts > cutoff - pd.Timedelta(seconds=bar_s)
        else:
            mask = ts >= cutoff
        return _stamp(candles_df[mask], True)
    except Exception:  # noqa: BLE001
        return _stamp(candles_df, False)


def stale_stop_verdict(
    meta: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    open_pkg: Dict[str, Any],
    candles_df: pd.DataFrame,
    current_price: float,
    direction: str,
    default_label: str = "",
) -> Optional[Dict[str, Any]]:
    """M20 conditional stale-stop — close a position that is ≥ N native bars
    old and still below the declared open-R threshold at bar close.

    Declared (``stale_exit_bars`` in meta/cfg) ⇒ may return a real
    ``{"action": "close", "reason": "stale_stop"}`` verdict. Undeclared ⇒
    evaluates the reference cell (8 bars, < 0R) and writes one observe-only
    annotate row when it would fire, returning ``None`` (behaviour unchanged).
    Fail-safe: any missing input (entry_time, frozen risk, entry) skips both
    paths — never a spurious close. **Never raises.**
    """
    try:
        declared_bars = _coerce_int(
            meta.get("stale_exit_bars") if meta.get("stale_exit_bars") is not None
            else cfg_dict.get("stale_exit_bars")
        )
        below_r_raw = (
            meta.get("stale_exit_below_r")
            if meta.get("stale_exit_below_r") is not None
            else cfg_dict.get("stale_exit_below_r")
        )
        below_r = _coerce_float(below_r_raw)
        n_bars = declared_bars if declared_bars is not None else _STALE_REF_BARS
        threshold = below_r if (declared_bars is not None and below_r is not None) \
            else (_STALE_REF_BELOW_R if declared_bars is None else 0.0)

        entry = _coerce_float(open_pkg.get("entry"))
        risk = _coerce_float(meta.get("risk_per_unit"))
        if entry is None or risk is None or risk <= 0:
            return None
        if not meta.get("entry_time"):
            return None  # age unknowable — fail-safe skip
        # MOMENTUM-LEVERS-PARITY (2026-10-24): decide on CLOSED bars, as the
        # harnesses do (close at bar CLOSE once j - entry_i >= N). Counting the
        # still-forming bar made the live age one bar older than the harness's and
        # tested an intrabar price, so the stop fired up to one bar early
        # (measured: scripts/research/momentum_levers_parity.py). A frame with no
        # declared timeframe passes through unchanged (the pre-fix behaviour).
        closed = closed_frame(candles_df, meta, cfg_dict)
        window = since_entry(closed, open_pkg)
        # since_entry falls back to the FULL frame only when the entry time or
        # timestamps are unreadable (since SINCE-ENTRY-WINDOW-FIX it returns a
        # 0/1-row frame in a trade's first bar, which reads age 0 below); a
        # full frame would fake a huge age, so require a real restriction.
        if len(window) >= len(closed) and len(closed) > 0:
            # Ambiguous: either fallback or a trade older than the fetch
            # window (limit≈200 bars ≫ any sane stale_exit_bars). Treat a
            # full-window match as "at least window-length old" ONLY when the
            # first window bar is at/after the entry time; _since_entry
            # guarantees that when it actually filtered, so equality here
            # means fallback — skip (fail-safe).
            return None
        age_bars = max(0, len(window) - 1)  # CLOSED bars strictly after the entry bar
        if age_bars < n_bars:
            return None
        bar_close = _coerce_float(closed["close"].iloc[-1])
        if bar_close is None:
            return None
        open_r = ((bar_close - entry) if direction == "long"
                  else (entry - bar_close)) / risk
        if open_r >= threshold:
            return None
        if declared_bars is not None:
            return {"action": "close", "reason": "stale_stop",
                    "exit_price": current_price}
        # Annotate-only path (undeclared): observe, never act.
        try:
            from src.runtime.exit_lever_soak import record_exit_lever_annotation

            record_exit_lever_annotation(
                lever="stale_stop",
                strategy=str(meta.get("strategy_label")
                             or open_pkg.get("strategy_name") or default_label),
                symbol=str(open_pkg.get("symbol") or ""),
                direction=direction,
                order_package_id=open_pkg.get("order_package_id"),
                params={"stale_exit_bars": n_bars,
                        "stale_exit_below_r": threshold},
                state={"age_bars": age_bars, "open_r": round(open_r, 4),
                       "price": current_price, "entry": entry},
            )
        except Exception:  # noqa: BLE001 — annotate must never affect the path
            pass
        return None
    except Exception:  # noqa: BLE001 — monitor must never crash on this lever
        return None


def giveback_verdict(
    meta: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    open_pkg: Dict[str, Any],
    candles_df: pd.DataFrame,
    current_price: float,
    direction: str,
    default_label: str = "",
) -> Optional[Dict[str, Any]]:
    """M20 giveback-stop — close a position that has seen at least
    ``giveback_min_mfe_r`` R of open profit (peak basis, since entry) and
    has given back at least ``giveback_r`` R from that peak at bar close.
    An R-based profit lock, distinct from the price/ATR chandelier trail —
    the harness reference is ``scripts/backtest_trend.py``'s giveback lever
    (identical peak_r/r_close math; the research copy was retired 2026-08-09).

    Declared (BOTH ``giveback_min_mfe_r`` AND ``giveback_r`` positive in
    meta/cfg) ⇒ may return a real ``{"action": "close", "reason":
    "giveback_stop"}`` verdict. Undeclared ⇒ evaluates the reference cell
    (1R giveback after 1R MFE) and writes one observe-only annotate row
    when it would fire, returning ``None`` (behaviour unchanged).
    Fail-safe: any missing input (entry, frozen risk, entry_time, an
    unrestrictable candle window whose pre-entry bars would fake the
    peak) skips both paths — never a spurious close. **Never raises.**
    """
    try:
        declared_min_mfe = _coerce_float(
            meta.get("giveback_min_mfe_r")
            if meta.get("giveback_min_mfe_r") is not None
            else cfg_dict.get("giveback_min_mfe_r")
        )
        declared_gb = _coerce_float(
            meta.get("giveback_r") if meta.get("giveback_r") is not None
            else cfg_dict.get("giveback_r")
        )
        declared = (declared_min_mfe is not None and declared_min_mfe > 0
                    and declared_gb is not None and declared_gb > 0)
        min_mfe_r = declared_min_mfe if declared else _GIVEBACK_REF_MIN_MFE_R
        giveback_r = declared_gb if declared else _GIVEBACK_REF_GIVEBACK_R

        entry = _coerce_float(open_pkg.get("entry"))
        risk = _coerce_float(meta.get("risk_per_unit"))
        if entry is None or risk is None or risk <= 0:
            return None
        if not meta.get("entry_time"):
            return None  # peak window unanchorable — fail-safe skip
        window = since_entry(candles_df, open_pkg)
        # Same ambiguity guard as _stale_stop_verdict: a full-frame
        # "restriction" means _since_entry fell back, and a pre-entry
        # extreme would fake a peak the trade never actually saw.
        if len(window) >= len(candles_df) and len(candles_df) > 0:
            return None
        if len(window) < 2:
            # First bar of the trade (SINCE-ENTRY-WINDOW-FIX): 0 rows, or only
            # the bar CONTAINING the entry, whose extreme can predate the fill.
            # No measurable peak — the `thin_window` rule of
            # `trail_decay.since_entry_peak`, never a close.
            return None
        if direction == "long":
            peak = _coerce_float(window["high"].max())
            if peak is None:
                return None
            peak_r = (peak - entry) / risk
            r_close = (current_price - entry) / risk
        else:
            peak = _coerce_float(window["low"].min())
            if peak is None:
                return None
            peak_r = (entry - peak) / risk
            r_close = (entry - current_price) / risk
        if not (peak_r >= min_mfe_r and (peak_r - r_close) >= giveback_r):
            return None
        if declared:
            return {"action": "close", "reason": "giveback_stop",
                    "exit_price": current_price}
        # Annotate-only path (undeclared): observe, never act.
        try:
            from src.runtime.exit_lever_soak import record_exit_lever_annotation

            record_exit_lever_annotation(
                lever="giveback_stop",
                strategy=str(meta.get("strategy_label")
                             or open_pkg.get("strategy_name") or default_label),
                symbol=str(open_pkg.get("symbol") or ""),
                direction=direction,
                order_package_id=open_pkg.get("order_package_id"),
                params={"giveback_min_mfe_r": min_mfe_r,
                        "giveback_r": giveback_r},
                state={"peak_r": round(peak_r, 4), "open_r": round(r_close, 4),
                       "price": current_price, "entry": entry},
            )
        except Exception:  # noqa: BLE001 — annotate must never affect the path
            pass
        return None
    except Exception:  # noqa: BLE001 — monitor must never crash on this lever
        return None
