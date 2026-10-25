"""Observe-only BRACKET ADVISOR, phase 0 — the stop/target a confirmed but
UNDECLARED rule lever WOULD set on this bar, logged beside the live bracket.

WHY THIS EXISTS (checklist row BRACKET-ADVISOR-SHADOW)
------------------------------------------------------
``position_path_history`` records the live bracket (``sl_r``/``tp_r``) per bar.
Nothing recorded what a candidate lever WOULD set on the same bar, so the
harness-vs-live parity of a lever (exit-refinement P5) could only be read after
its Tier-3 declare. This module computes that value on the same monitor pass
and the history row stores it as ``advisor_sl_r`` / ``advisor_tp_r`` /
``advisor_source`` / ``advisor_state``. Operator approval for building it,
2026-10-25 ~06:02Z, verbatim popup choice: "Build it (Recommended)".

THE REGISTRY IS THE COVERAGE MATRIX
-----------------------------------
``docs/research/exit-refinement-coverage.json`` (the exit-refinement skill's
contract) grades every (leg, lever). A cell with status ``passed_unshipped``
MAY carry a structured ``advisor`` spec::

    "advisor": {"lever": "momentum_trail", "version": "RQ-20261016-005/M1",
                "harness": "scripts/backtest_trend.py",
                "params": {"trail_adx_below": 20, "trail_adx_tight_mult": 2.5},
                "evidence": "research/results/RQ-20261016-005/39103745017.jsonl"}

That spec is the ONLY input that names a leg and its parameters: this module
holds no leg list. A cell without a spec is not advised.

THE SAME FUNCTIONS AS THE HARNESS
---------------------------------
* ``momentum_trail`` (SL side): ``scripts/backtest_trend.py``'s chandelier,
  replayed over the CLOSED bars after the entry bar from the initial stop —
  ``ext`` starts at entry, ``trail = max(trail, ext - m x atr)`` with the
  frozen entry ATR and ``m = trail_levers.effective_trail_mult(...)`` (the ONE
  rule, composing the leg's declared trail-decay with the candidate ADX
  tightener by minimum). ADX is ``momentum_levers.live_adx`` on the closed
  frame — the series the live lever reads once declared. The value logged is
  the stop the harness would test the NEXT bar against.
* ``tp_revision`` (TP side): ``tp_revision.plan_tp_revision`` with the spec's
  rule overlaid on the package meta, on the closed bars.

The live producers in ``momentum_levers`` are deliberately NOT called: they
write exit-lever soak rows reading ``applied: True``, and an advisor that
wrote those would fabricate evidence of a lever that never acted.

HARD CONSTRAINTS
----------------
1. **Never read by the exit or order path.** Nothing in ``src/`` outside the
   history writer imports this module (pinned by
   ``tests/test_bracket_advisor.py``).
2. **Never raises.** Every failure becomes ``advisor_state='error'`` for that
   row, logged at WARNING once per process.
3. **Bounded per bar.** One computation per (package, last closed bar): the
   ~30 s passes inside a bar reuse the cached result. A frame longer than
   ``MAX_MANAGED_BARS`` managed bars is refused (``over_budget``), and a
   computation slower than ``SLOW_MS`` is logged.

``advisor_state`` — never collapsed (``ADVISOR_STATES``):
``computed`` a value was produced · ``declared`` the leg already declares the
lever, so the live bracket IS the lever · ``no_lever`` no advisor spec is
registered for this leg · ``unmodelled`` the leg declares an SL lever this
replay does not model, so a value would differ from the evidence ·
``insufficient_data`` a required input (entry time, ATR, risk, closed bars) is
missing · ``over_budget`` refused on the cost bound · ``registry_unreadable``
the matrix could not be read (we did not look) · ``error`` the computation
failed.
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bump when the replay arithmetic changes, so a stored value says which
#: advisor produced it (it rides in ``advisor_source``).
ADVISOR_VERSION = 1

REGISTRY_PATH = (Path(__file__).resolve().parents[2]
                 / "docs" / "research" / "exit-refinement-coverage.json")

ADVISOR_STATES = ("computed", "declared", "no_lever", "unmodelled",
                  "insufficient_data", "over_budget", "registry_unreadable",
                  "error")

#: Levers this module can advise, and which side of the bracket each sets.
SL_LEVERS = ("momentum_trail",)
TP_LEVERS = ("tp_revision",)
SUPPORTED_LEVERS = SL_LEVERS + TP_LEVERS

#: The harness whose chandelier the SL replay reproduces. A spec naming any
#: other harness is ``unmodelled`` — its trail is not this one.
TRAIL_HARNESS = "scripts/backtest_trend.py"

#: SL-shaping levers the replay does not model (the prop trail's list plus the
#: harness's level trail). A leg declaring one is ``unmodelled``.
_UNMODELLED_SL_KEYS = ("trail_vol_tight_mult", "be_floor_r", "trail_level_tight_mult")

MAX_MANAGED_BARS = 2000
SLOW_MS = 50.0
_CACHE_MAX = 512
_DEFAULT_ADX_PERIOD = 14

_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
_registry: dict[str, Any] = {"mtime": None, "specs": None}
_warned: set = set()


def _warn_once(key: str, msg: str) -> None:
    if key in _warned:
        logger.debug(msg, exc_info=True)
        return
    _warned.add(key)
    logger.warning(msg, exc_info=True)


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _empty(state: str, source: str | None = None) -> dict[str, Any]:
    return {"advisor_sl_r": None, "advisor_tp_r": None,
            "advisor_source": source, "advisor_state": state}


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def specs_from_matrix(matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """strategy -> advisor specs, from every ``passed_unshipped`` cell that
    carries one. Pure."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in (matrix or {}).get("rows") or []:
        if not isinstance(row, dict) or not row.get("strategy"):
            continue
        for column, cell in row.items():
            if not isinstance(cell, dict):
                continue
            spec = cell.get("advisor")
            if not isinstance(spec, dict) or not str(cell.get("status", "")).startswith(
                    "passed_unshipped"):
                continue
            out.setdefault(str(row["strategy"]), []).append(
                {**spec, "column": column})
    return out


def load_specs(path: Path | None = None) -> dict[str, list[dict[str, Any]]] | None:
    """The registry's advisor specs, cached on the file's mtime. ``None`` when
    the file cannot be read — which is NOT the same fact as no specs."""
    p = path or REGISTRY_PATH
    try:
        mtime = p.stat().st_mtime
        if path is None and _registry["mtime"] == mtime and _registry["specs"] is not None:
            return _registry["specs"]
        specs = specs_from_matrix(json.loads(p.read_text()))
        if path is None:
            _registry.update(mtime=mtime, specs=specs)
        return specs
    except Exception:  # noqa: BLE001 — an unreadable registry is a state, not a crash
        _warn_once("registry", f"bracket_advisor: registry unreadable at {p}")
        return None


# ---------------------------------------------------------------------------
# The two computations
# ---------------------------------------------------------------------------

def _declared(meta: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Does the package already carry this lever? Then the live bracket IS the
    lever and there is nothing to advise."""
    if spec.get("lever") == "tp_revision":
        from src.runtime.tp_revision import declared_rule
        rule = (spec.get("params") or {}).get("rule")
        return rule is not None and declared_rule(meta) == rule
    params = spec.get("params") or {}
    return bool(params) and all(
        _f(meta.get(k)) is not None and _f(meta.get(k)) == _f(v) for k, v in params.items())


def _managed_bars(closed, entry_time: Any):
    """(managed frame, offset of its first row in ``closed``): the CLOSED bars
    strictly after the entry bar — the harness's ``range(entry_i + 1, ...)``.
    ``entry_time`` is the decision bar's timestamp on a forming- and a
    closed-bar leg alike (``order_package`` stamps the frame's last row)."""
    import pandas as pd
    ts = pd.to_datetime(closed["timestamp"], utc=True, errors="coerce")
    cut = pd.to_datetime(entry_time, utc=True, errors="coerce")
    if pd.isna(cut) or not (ts <= cut).any():
        return None, None   # the entry bar is not in the frame: cannot anchor
    mask = (ts > cut).to_numpy()
    offset = int(mask.argmax()) if mask.any() else len(closed)
    return closed.iloc[offset:], offset


def replay_momentum_trail(*, meta: dict[str, Any], params: dict[str, Any],
                          closed, direction: str, entry: float, risk: float,
                          atr: float) -> float | None:
    """The harness's chandelier stop after the last closed bar with the
    candidate ADX tightener added to the leg's declared levers. Pure."""
    from src.research.trail_levers import effective_trail_mult, momentum_trail_armed
    from src.runtime.momentum_levers import live_adx

    base = _f(meta.get("trail_mult"))
    if base is None or base <= 0:
        return None
    adx_below = _f(params.get("trail_adx_below")) or 0.0
    adx_falling = int(_f(params.get("trail_adx_falling_bars")) or 0)
    adx_tight = _f(params.get("trail_adx_tight_mult")) or 0.0
    if not momentum_trail_armed(adx_below, adx_falling, adx_tight):
        return None
    period = int(_f(meta.get("adx_period")) or _DEFAULT_ADX_PERIOD)
    adx = live_adx(closed, period)
    managed, offset = _managed_bars(closed, meta.get("entry_time"))
    if managed is None:
        return None
    decay_tight = _f(meta.get("trail_decay_tight_mult")) or 0.0
    decay_arm = _f(meta.get("trail_decay_arm_r")) or 0.0
    decay_stall = int(_f(meta.get("trail_decay_stall_bars")) or 0)
    long_ = direction == "long"
    ext = entry
    trail = entry - risk if long_ else entry + risk
    peak_j = offset - 1          # the harness's peak_j = entry_i
    highs = managed["high"].astype(float).to_numpy()
    lows = managed["low"].astype(float).to_numpy()
    for k in range(len(managed)):
        j = offset + k
        if long_:
            if highs[k] > ext:
                peak_j = j
            ext = max(ext, highs[k])
            peak_r = (ext - entry) / risk
        else:
            if lows[k] < ext:
                peak_j = j
            ext = min(ext, lows[k])
            peak_r = (entry - ext) / risk
        tm = effective_trail_mult(base, peak_r, j - peak_j, decay_tight > 0.0,
                                  decay_arm, decay_stall, decay_tight,
                                  False, None, j, 0.0, 0.0, 0.0,
                                  adx is not None, adx, adx_below, adx_falling, adx_tight)
        trail = max(trail, ext - tm * atr) if long_ else min(trail, ext + tm * atr)
    return trail


def _level_r(level: float | None, entry: float, risk: float, long_: bool) -> float | None:
    if level is None:
        return None
    v = ((level - entry) if long_ else (entry - level)) / risk
    return round(v, 4) if math.isfinite(v) else None


def _compute(specs: list[dict[str, Any]], *, meta: dict[str, Any], open_pkg: dict[str, Any],
             candles_df, direction: str, current_price: float | None) -> dict[str, Any]:
    from src.runtime.exit_levers import closed_frame

    pending = [s for s in specs if not _declared(meta, s)]
    if not pending:
        return _empty("declared", "+".join(f"{s.get('lever')}@{s.get('version')}" for s in specs))
    entry = _f(open_pkg.get("entry"))
    risk = _f(meta.get("risk_per_unit"))
    if (entry is None or risk is None or risk <= 0 or direction not in ("long", "short")
            or not meta.get("entry_time") or candles_df is None or len(candles_df) == 0):
        return _empty("insufficient_data")
    closed = closed_frame(candles_df, meta, {})
    if len(closed) > MAX_MANAGED_BARS:
        return _empty("over_budget")
    long_ = direction == "long"
    out = _empty("computed")
    sources, states = [], []
    for spec in pending:
        lever = spec.get("lever")
        params = spec.get("params") or {}
        if lever in SL_LEVERS:
            if spec.get("harness") != TRAIL_HARNESS or any(
                    (_f(meta.get(k)) or 0.0) > 0 for k in _UNMODELLED_SL_KEYS):
                states.append("unmodelled")
                continue
            atr = _f(meta.get("atr"))
            if atr is None or atr <= 0:
                states.append("insufficient_data")
                continue
            sl = replay_momentum_trail(meta=meta, params=params, closed=closed,
                                       direction=direction, entry=entry, risk=risk, atr=atr)
            if sl is None:
                states.append("insufficient_data")
                continue
            out["advisor_sl_r"] = _level_r(sl, entry, risk, long_)
        elif lever in TP_LEVERS:
            from src.runtime.tp_revision import plan_tp_revision
            rev = plan_tp_revision(leg={**meta, "tp_revision": params}, direction=direction,
                                   entry=entry, risk=risk, bars=closed,
                                   entry_time=meta.get("entry_time"),
                                   ref_price=current_price)
            if rev is None:
                states.append("insufficient_data")
                continue
            out["advisor_tp_r"] = _level_r(rev.tp, entry, risk, long_)
        else:
            states.append("unmodelled")
            continue
        sources.append(f"{lever}@{spec.get('version')}")
        states.append("computed")
    out["advisor_source"] = ("+".join(sources) + f";advisor_v{ADVISOR_VERSION}") if sources else \
        "+".join(f"{s.get('lever')}@{s.get('version')}" for s in pending)
    # One state per row: computed when anything was, else the first reason none was.
    out["advisor_state"] = "computed" if "computed" in states else (states[0] if states else "error")
    return out


def _bar_key(candles_df) -> Any:
    try:
        return (len(candles_df), str(candles_df["timestamp"].iloc[-1]))
    except Exception:  # noqa: BLE001
        return None


def advise(*, open_pkg: dict[str, Any] | None, meta: dict[str, Any] | None, candles_df,
           direction: str, current_price: float | None = None,
           registry_path: Path | None = None) -> dict[str, Any]:
    """The four ``advisor_*`` fields for one monitor pass. Never raises."""
    try:
        open_pkg = open_pkg or {}
        meta = meta if isinstance(meta, dict) else {}
        strategy = str(meta.get("strategy_label") or open_pkg.get("strategy_name") or "")
        specs = load_specs(registry_path)
        if specs is None:
            return _empty("registry_unreadable")
        mine = specs.get(strategy) or []
        if not mine:
            return _empty("no_lever")
        pkg = str(open_pkg.get("order_package_id") or "")
        # The value depends only on the closed bars, so it is constant inside
        # a bar: the many passes of one bar reuse one computation.
        key = (_bar_key(candles_df), len(mine))
        hit = _cache.get(pkg) if pkg else None
        if hit is not None and hit[0] == key:
            return dict(hit[1])
        t0 = time.perf_counter()
        out = _compute(mine, meta=meta, open_pkg=open_pkg, candles_df=candles_df,
                       direction=str(direction or "").lower(), current_price=_f(current_price))
        ms = (time.perf_counter() - t0) * 1000.0
        if ms > SLOW_MS:
            logger.warning("bracket_advisor: %s took %.1f ms (bound %.0f ms)", pkg, ms, SLOW_MS)
        if pkg:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[pkg] = (key, dict(out))
        return out
    except Exception:  # noqa: BLE001 — never raise into the monitor
        _warn_once("advise", "bracket_advisor: computation failed (contained; row keeps "
                             "advisor_state='error'; trading unaffected)")
        return _empty("error")
