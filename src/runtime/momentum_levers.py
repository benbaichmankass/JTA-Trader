"""MOMENTUM-LEVERS-LIVE -- the live producers for the harness's two momentum exit levers.

WHY THIS EXISTS (checklist row MOMENTUM-LEVERS-LIVE, Programme 01, 2026-10-18)
--------------------------------------------------------------------------------
On 2026-10-18 three Programme-01 confirmations PASSED their pre-registered rules on
real-money legs and none could be declared, because the lever existed only in the
research harnesses:

* ``RQ-20261016-005`` trend_donchian_eth_4h (bybit_2): ADX-tightened trail
  ``trail_adx_below 20 / trail_adx_tight_mult 2.5`` -- 111.37 vs 88.27 R over
  270 / 262 trades, 5 of 6 folds, maxDD 16.12 vs 18.06 (2020-07..2026-10).
* ``RQ-20261016-015`` trend_donchian_xrp_4h (bybit_2): ``trail_adx_below 25 /
  tight 2.5`` -- 17.07 vs 14.30 R over 68 trades, 4 of 4 folds.
* ``RQ-20261016-016`` slv_pullback_1d (alpaca_live): momentum-keyed time stop
  ``momentum_stale_bars 8 / momentum_stale_adx_below 20`` -- 20.73 vs 12.82 R over
  89 / 69 trades, 3 of 4 folds.

The firing rules already have ONE definition, ``src/research/trail_levers.py``
(``momentum_trail_armed`` / ``momentum_trail_fired`` / ``momentum_stale_armed`` /
``momentum_stale_fires``), imported by ``scripts/backtest_trend.py`` and
``scripts/backtest_pullback.py``. This module imports the SAME functions, so the
live monitor and the harness cannot drift on the rule itself (the reason that
module exists -- see its docstring). What this module adds is the live plumbing:
reading the keys from the package meta / live YAML, computing the ADX series on
CLOSED bars, locating the entry bar, and the observe-only soak row.

CONTRACT (identical to the stale / giveback / trail-decay / vol-trail levers)
---------------------------------------------------------------------------
* **Declared** -- the keys are present in the package meta (threaded from the
  strategy YAML by ``order_package`` at entry) or in the live cfg
  (``order_monitor._load_live_strategy_cfgs``, which covers already-open
  packages). Half-declared reads as OFF, exactly as the harness's
  ``momentum_trail_armed`` / ``momentum_stale_armed`` say.
* **Undeclared** -- byte-identical monitor behaviour: the base trail mult is
  returned unchanged and the stale verdict is ``None``. No reference-cell
  annotate row: the offline confirmations above are the evidence, and a
  reference cell would be a second, un-registered parameter choice.
* **Closed bars only** -- the forming bar is dropped
  (``src.runtime.closed_bars.drop_forming_bar``) before the ADX is computed, as
  the vol-trail lever does; the harness only ever sees closed bars.
* **ADX** -- ``src.runtime.regime.detector.wilder_adx`` (Wilder EWM, alpha =
  1/period); the harness's ``_adx`` is the same recursion with ``min_periods``
  NaN warm-up, so the two agree bit-for-bit after warm-up
  (``tests/test_momentum_levers_live.py::test_live_adx_matches_the_harness_adx``).
  The live series is computed over the monitor's fetched window (>= 200 closed
  bars) rather than the harness's whole history; the EWM memory of bars older
  than the window decays as (1 - 1/period)^n, below 1e-6 of the value at 200
  bars for period 14, so this is a stated, bounded approximation, never a
  different rule.
* **Fail-safe** -- any missing input (no entry_time, no risk, too few bars,
  NaN ADX at either point) returns the base mult / ``None``. **Never raises.**

TWO LEVERS
----------
``resolve_momentum_trail_mult`` -- the ADX-conditioned TRAIL. On a closed bar
where ``momentum_trail_fired`` holds (ADX below the bound and/or lower than k
bars ago), the effective chandelier mult becomes ``min(base, tight)``. It
composes with trail-decay and vol-trail by minimum, exactly as
``trail_levers.effective_trail_mult`` does in the harness. A tighter TRAIL is
something every execution path already carries (it is a stop amend), so no
platform gap opens.

``momentum_stale_verdict`` -- the momentum-keyed TIME STOP. Closes at bar
close once ``(bars since entry) >= N`` AND ``ADX_now < ADX_entry`` AND
``ADX_now < A``. Open R is deliberately not consulted (that is the whole
difference from ``stale_stop``). This is a CLOSE verb: a leg whose execution
path cannot close on a verdict (the prop paths, see
PI-20261006-KX6ZKFNA-0001 / lane EXIT-LEVER-STRIP) must not declare it;
``tests/test_momentum_levers_live.py`` pins that no prop leg does.
"""
from __future__ import annotations

import logging
import math
from contextlib import suppress
from typing import Any

import pandas as pd

from src.research.trail_levers import (
    momentum_stale_armed,
    momentum_stale_fires,
    momentum_trail_armed,
    momentum_trail_fired,
)

logger = logging.getLogger(__name__)

_DEFAULT_ADX_PERIOD = 14
#: Bars of ADX warm-up the harness leaves NaN (``min_periods=period``); the live
#: series is read only past this point so a warm-up value can never fire.
_WARMUP_MULT = 2


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _pick(meta: dict[str, Any], cfg: dict[str, Any], key: str) -> Any:
    mv = (meta or {}).get(key)
    return mv if mv is not None else (cfg or {}).get(key)


def momentum_trail_keys(meta: dict[str, Any], cfg: dict[str, Any]) -> dict[str, float]:
    return {
        "trail_adx_below": _f(_pick(meta, cfg, "trail_adx_below")) or 0.0,
        "trail_adx_falling_bars": _i(_pick(meta, cfg, "trail_adx_falling_bars")),
        "trail_adx_tight_mult": _f(_pick(meta, cfg, "trail_adx_tight_mult")) or 0.0,
    }


def momentum_stale_keys(meta: dict[str, Any], cfg: dict[str, Any]) -> dict[str, float]:
    return {
        "momentum_stale_bars": _i(_pick(meta, cfg, "momentum_stale_bars")),
        "momentum_stale_adx_below": _f(_pick(meta, cfg, "momentum_stale_adx_below")) or 0.0,
    }


def momentum_trail_declared(cfg: dict[str, Any]) -> bool:
    k = momentum_trail_keys({}, cfg)
    return momentum_trail_armed(k["trail_adx_below"], k["trail_adx_falling_bars"],
                                k["trail_adx_tight_mult"])


def momentum_stale_declared(cfg: dict[str, Any]) -> bool:
    k = momentum_stale_keys({}, cfg)
    return momentum_stale_armed(k["momentum_stale_bars"], k["momentum_stale_adx_below"])


def _closed(candles_df: Any, meta: dict[str, Any], cfg: dict[str, Any]) -> Any:
    """The frame without its still-forming last bar (train/live parity)."""
    with suppress(Exception):  # trimming must never break the lever
        from src.runtime.closed_bars import drop_forming_bar
        timeframe = str(_pick(meta, cfg, "timeframe") or "")
        if timeframe:
            return drop_forming_bar(candles_df, timeframe)
    return candles_df


def live_adx(candles_df: Any, period: int) -> pd.Series | None:
    """Wilder ADX over the frame, or None when the frame is too short to be
    past warm-up (the harness reads NaN there and never fires)."""
    if candles_df is None or len(candles_df) < _WARMUP_MULT * period + 1:
        return None
    try:
        from src.runtime.regime.detector import wilder_adx
        adx = wilder_adx(candles_df, period)
    except Exception:  # noqa: BLE001
        return None
    # Mask the warm-up the harness leaves NaN, so both read the same bars.
    adx = adx.copy()
    adx.iloc[: period] = float("nan")
    return adx


def _entry_index(closed_df: Any, open_pkg: dict[str, Any]) -> int | None:
    """Positional index of the entry bar inside ``closed_df`` (the first bar at or
    after ``entry_time``), or None when it cannot be placed (fail-safe)."""
    try:
        from src.runtime.exit_levers import since_entry
        window = since_entry(closed_df, open_pkg)
        if window is None or len(window) == 0:
            return None
        if len(window) >= len(closed_df):
            # since_entry falls back to the FULL frame when the entry time cannot
            # be matched; a full-window match is indistinguishable from that
            # fallback, so it is a fail-safe skip (as the stale lever does).
            return None
        return len(closed_df) - len(window)
    except Exception:  # noqa: BLE001
        return None


def resolve_momentum_trail_mult(
    meta: dict[str, Any],
    cfg_dict: dict[str, Any],
    candles_df: Any,
    base_mult: float,
    direction: str,
    open_pkg: dict[str, Any] | None = None,
) -> float:
    """The EFFECTIVE trail mult after the ADX-conditioned tightener (base when
    undeclared, unfired, or unreadable). Composes by minimum with whatever the
    caller passes as ``base_mult`` (trail-decay / vol-trail already applied)."""
    try:
        meta = meta or {}
        cfg_dict = cfg_dict or {}
        k = momentum_trail_keys(meta, cfg_dict)
        if not momentum_trail_armed(k["trail_adx_below"], k["trail_adx_falling_bars"],
                                    k["trail_adx_tight_mult"]):
            return base_mult
        closed = _closed(candles_df, meta, cfg_dict)
        period = _i(_pick(meta, cfg_dict, "adx_period")) or _DEFAULT_ADX_PERIOD
        adx = live_adx(closed, period)
        if adx is None:
            return base_mult
        j = len(adx) - 1
        if not momentum_trail_fired(adx, j, k["trail_adx_below"], k["trail_adx_falling_bars"]):
            return base_mult
        eff = min(float(base_mult), float(k["trail_adx_tight_mult"]))
        pkg = open_pkg or {}
        with suppress(Exception):  # soak logging must never affect the path
            from src.runtime.exit_lever_soak import record_exit_lever_annotation
            record_exit_lever_annotation(
                lever="momentum_trail",
                strategy=str(meta.get("strategy_label") or pkg.get("strategy_name") or "unknown"),
                symbol=str(pkg.get("symbol") or ""),
                direction=direction,
                order_package_id=pkg.get("order_package_id"),
                params={**k, "adx_period": period, "base_trail_mult": float(base_mult)},
                state={"adx": round(float(adx.iloc[j]), 4), "eff_mult": round(eff, 4),
                       "applied": True},
            )
        return eff
    except Exception:  # the monitor must never feel this
        logger.debug("momentum_levers: trail resolve failed", exc_info=True)
        return base_mult


def momentum_stale_verdict(
    meta: dict[str, Any],
    cfg_dict: dict[str, Any],
    open_pkg: dict[str, Any],
    candles_df: Any,
    current_price: float,
    direction: str,
    default_label: str = "",
) -> dict[str, Any] | None:
    """``{"action": "close", "reason": "momentum_stale", ...}`` when the declared
    momentum-keyed time stop fires on the last CLOSED bar; ``None`` otherwise
    (undeclared, young, momentum intact, or any unreadable input)."""
    try:
        meta = meta or {}
        cfg_dict = cfg_dict or {}
        k = momentum_stale_keys(meta, cfg_dict)
        if not momentum_stale_armed(k["momentum_stale_bars"], k["momentum_stale_adx_below"]):
            return None
        if not meta.get("entry_time"):
            return None  # age unknowable -- fail-safe skip
        closed = _closed(candles_df, meta, cfg_dict)
        period = _i(_pick(meta, cfg_dict, "adx_period")) or _DEFAULT_ADX_PERIOD
        adx = live_adx(closed, period)
        if adx is None:
            return None
        entry_i = _entry_index(closed, open_pkg)
        if entry_i is None:
            return None
        j = len(adx) - 1
        if not momentum_stale_fires(adx, j, entry_i, k["momentum_stale_bars"],
                                    k["momentum_stale_adx_below"]):
            return None
        with suppress(Exception):  # annotate must never affect the path
            from src.runtime.exit_lever_soak import record_exit_lever_annotation
            record_exit_lever_annotation(
                lever="momentum_stale",
                strategy=str(meta.get("strategy_label") or open_pkg.get("strategy_name")
                             or default_label),
                symbol=str(open_pkg.get("symbol") or ""),
                direction=direction,
                order_package_id=open_pkg.get("order_package_id"),
                params={**k, "adx_period": period},
                state={"age_bars": j - entry_i, "adx": round(float(adx.iloc[j]), 4),
                       "adx_entry": round(float(adx.iloc[entry_i]), 4),
                       "price": current_price, "applied": True},
            )
        return {"action": "close", "reason": "momentum_stale", "exit_price": current_price}
    except Exception:  # the monitor must never feel this
        logger.debug("momentum_levers: stale verdict failed", exc_info=True)
        return None
