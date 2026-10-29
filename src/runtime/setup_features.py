"""Decision-time ``setup_candidates`` features on the live path (B2, 2026-10-29).

The setup meta-label heads (``setup-candidates-metalabel-*``, P1 of
``docs/plans/ml-live-promotion-plan-2026-10-29.md``) train on the
``setup_candidates`` decision-time row: the candle features of the bar the
setup fired on (``rolling_log_return_vol``, ``log_return`` + 2 lags,
``momentum``, the four range-vol estimators, ``hour_of_day``, ``dayofweek``)
plus ``direction`` (±1), ``symbol`` and ``vol_bucket``. The signal-time row the
live path scored them on carried six trade-context fields and none of those, so
every candle feature served as missing.

This module closes that gap without a second implementation of any feature:

- ``stash_decision_features`` runs at signal time on the leg's CLOSED candles
  and stores ``ml.datasets.families.setup_candidates.decision_time_features``
  (the build's own ``_feature_fields``) on the signal meta as
  ``meta["setup_features"]``. The meta rides signal → intent → OrderPackage, so
  the execution-time advisory path reads the same numbers the shadow path saw.
- ``row_for_predictor`` merges that block into the base row for a head that
  exposes a frozen ``serve_spec`` (``ml.experiments.runner._attach_serve_spec``):
  ``vol_bucket`` is bucketed with the build's ``_bucket_for`` against the head's
  own per-symbol edges, ``direction`` becomes the build's ±1. A head without a
  ``serve_spec`` gets the base row unchanged, so no existing model's input moves.

Every refusal is a named ``read_state`` (never a silent default): the merged row
is either the training row or absent, and the caller records which. Pure and
never-raises; nothing here can change an order by itself.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

META_KEY = "setup_features"

# Build defaults (SetupCandidatesBuilder.iter_rows). A head whose spec declares
# other windows is refused rather than served on these.
VOL_WINDOW_N = 20
MOMENTUM_WINDOW = 10
# Bars kept for the computation: the vol window plus the two lags, with margin.
_BARS = 64


def _iso_utc(ts_value: Any) -> str | None:
    """A candle ``timestamp`` cell as the ISO-8601 UTC string ``market_raw``
    writes (``...Z``, ``ml.datasets.adapters.bybit_offvm._ms_to_iso``) from
    epoch ms / s, a datetime / pandas Timestamp, or ISO text."""
    dt = _utc_datetime(ts_value)
    return None if dt is None else dt.isoformat().replace("+00:00", "Z")


def _utc_datetime(ts_value: Any) -> datetime | None:
    if ts_value is None:
        return None
    if hasattr(ts_value, "hour") and hasattr(ts_value, "weekday"):
        dt = ts_value
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    try:
        epoch = float(ts_value)
    except (TypeError, ValueError):
        epoch = None
    if epoch is not None and math.isfinite(epoch):
        if epoch > 1e11:  # milliseconds
            epoch /= 1000.0
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    s = str(ts_value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _column(candles_df: Any, name: str) -> list[Any] | None:
    try:
        col = candles_df[name]
    except Exception:  # noqa: BLE001 — missing column / not a frame
        return None
    try:
        return list(col.tolist())
    except AttributeError:
        try:
            return list(col)
        except TypeError:
            return None


def bars_from_candles(
    candles_df: Any, symbol: str, timeframe: str,
) -> list[dict[str, Any]] | None:
    """The last ``_BARS`` candles as ``market_raw``-shaped rows, oldest first.

    ``None`` when a column is missing or any kept bar has a non-finite or
    non-positive price: the window must be the bars the build would read, or
    nothing.
    """
    if candles_df is None:
        return None
    cols = {c: _column(candles_df, c)
            for c in ("timestamp", "open", "high", "low", "close")}
    if any(v is None for v in cols.values()):
        return None
    n = len(cols["close"])
    if n == 0 or any(len(v) != n for v in cols.values()):
        return None
    out: list[dict[str, Any]] = []
    for i in range(max(0, n - _BARS), n):
        ts = _iso_utc(cols["timestamp"][i])
        if ts is None:
            return None
        try:
            o, h, lo, c = (float(cols[k][i]) for k in ("open", "high", "low", "close"))
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(x) and x > 0 for x in (o, h, lo, c)):
            return None
        out.append({"ts": ts, "open": o, "high": h, "low": lo, "close": c,
                    "symbol": symbol, "timeframe": timeframe, "source": "live"})
    return out


def decision_features_block(
    candles_df: Any, symbol: str, timeframe: str,
) -> dict[str, Any]:
    """The ``meta["setup_features"]`` block for the last closed bar.

    ``candles_df`` must already end on a CLOSED bar (the caller drops the
    forming one, ``src.runtime.closed_bars.drop_forming_bar``): training rows
    are closed bars.
    """
    block: dict[str, Any] = {
        "timeframe": str(timeframe or ""),
        "vol_window_n": VOL_WINDOW_N,
        "momentum_window": MOMENTUM_WINDOW,
    }
    try:
        from ml.datasets.families.setup_candidates import decision_time_features

        bars = bars_from_candles(candles_df, str(symbol or ""), str(timeframe or ""))
        if not bars:
            block["read_state"] = "no_bars"
            return block
        feats = decision_time_features(
            bars, vol_window_n=VOL_WINDOW_N, momentum_window=MOMENTUM_WINDOW,
        )
        if feats is None:
            block["read_state"] = "incomplete_window"
            return block
        block["read_state"] = "ok"
        block["features"] = feats
        return block
    except Exception as exc:  # noqa: BLE001 — never strand a signal
        block["read_state"] = "error"
        block["error"] = str(exc)[:200]
        return block


def stash_decision_features(
    meta: dict, candles_df: Any, symbol: str, timeframe: str,
) -> None:
    """Store the block on a signal's meta (in place). Never raises."""
    try:
        if isinstance(meta, dict):
            meta[META_KEY] = decision_features_block(candles_df, symbol, timeframe)
    except Exception:  # noqa: BLE001
        pass


def serve_spec_of(predictor: Any) -> Mapping[str, Any] | None:
    """A predictor's frozen ``serve_spec`` (through a ShadowPredictor wrap)."""
    for obj in (getattr(predictor, "wrapped", None), predictor):
        spec = getattr(obj, "serve_spec", None) if obj is not None else None
        if isinstance(spec, Mapping):
            return spec
    return None


def _direction_int(direction: Any) -> int | None:
    d = str(direction or "").strip().lower()
    if d in ("long", "buy", "1", "+1"):
        return 1
    if d in ("short", "sell", "-1"):
        return -1
    return None


def setup_row(
    base_row: Mapping[str, Any],
    block: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """``(row, read_state)``: the training-shaped row for a spec'd head, or
    ``(None, reason)`` when it cannot be built faithfully."""
    if not isinstance(block, Mapping):
        return None, "no_setup_features"
    if block.get("read_state") != "ok":
        return None, f"setup_features_{block.get('read_state') or 'unknown'}"
    feats = block.get("features")
    if not isinstance(feats, Mapping):
        return None, "no_setup_features"
    if (int(spec.get("vol_window_n") or VOL_WINDOW_N) != int(block.get("vol_window_n") or 0)
            or int(spec.get("momentum_window") or MOMENTUM_WINDOW)
            != int(block.get("momentum_window") or 0)):
        return None, "window_mismatch"
    edges_by = spec.get("vol_bucket_edges_by_symbol") or {}
    labels_by = spec.get("vol_bucket_labels_by_symbol") or {}
    want = str(base_row.get("symbol") or feats.get("symbol") or "").strip().upper()
    sym = next((s for s in edges_by if str(s).strip().upper() == want), None)
    if sym is None:
        return None, "symbol_not_in_spec"
    tfs = list((spec.get("timeframe_by_symbol") or {}).get(sym) or [])
    if len(tfs) != 1 or str(tfs[0]) != str(block.get("timeframe") or ""):
        return None, "timeframe_mismatch"
    direction = _direction_int(base_row.get("direction"))
    if direction is None:
        return None, "no_direction"
    vol = feats.get("rolling_log_return_vol")
    labels = [str(b) for b in (labels_by.get(sym) or [])]
    edges = [float(e) for e in (edges_by.get(sym) or [])]
    if not isinstance(vol, (int, float)) or len(labels) != len(edges) + 1:
        return None, "bad_spec"
    from ml.datasets.families.setup_candidates import bucket_vol

    row = {**base_row, **feats}
    row["symbol"] = sym
    row["direction"] = direction
    row["vol_bucket"] = bucket_vol(float(vol), edges, labels)
    return row, "ok"


def row_for_predictor(
    predictor: Any,
    base_row: Mapping[str, Any],
    block: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], str | None]:
    """``(row, read_state)`` a predictor is scored on.

    A head without a ``serve_spec`` gets ``base_row`` unchanged and
    ``read_state None``. A spec'd head gets the merged row and ``"ok"``, or the
    base row and the refusal reason, so a dead feature is visible in the log
    instead of being served as a default.
    """
    spec = serve_spec_of(predictor)
    if spec is None:
        return base_row, None
    try:
        row, state = setup_row(base_row, block, spec)
    except Exception as exc:  # noqa: BLE001
        return base_row, f"error:{str(exc)[:80]}"
    return (row if row is not None else base_row), state
