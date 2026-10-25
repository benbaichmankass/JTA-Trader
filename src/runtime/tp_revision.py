"""The TP-revision contract: how a strategy MOVES its take-profit prediction.

TP doctrine clause 2 (`docs/ARCHITECTURE-CANONICAL.md` § "TP doctrine",
operator 2026-10-06): *the TP is a LIVE prediction, re-estimated through the
trade's life from current market conditions.* The exchange half of the path
already existed and had never been fed (`monitor()` -> `{"tp": x}` ->
`monitor_verdict.interpret_verdict` -> `order_monitor._apply_update` ->
`execute.modify_open_order`); the prop half passed `take_profit=None`. This
module is the ONE place a revision is decided, so every consumer -- the live
`monitor()`, the prop trail step and the backtest harness -- moves the same
TP for the same bars.

THE VERDICT SHAPE (B1)
----------------------
A monitor that revises its target returns, alone or merged into its SL verdict::

    {"tp": <price>, "tp_reason": "<rule>: <why, with the numbers>"}

`tp` is the only key the amend path reads; `tp_reason` rides through
`interpret_verdict` onto `VerdictDecision.tp_reason` and into the
order_monitor log line and the TRADE UPDATED ping, so every TP move on a
venue carries the prediction that produced it. A close verdict
(`{"action": "close", ...}`) always wins: `merge_verdict` never attaches a TP
to a close.

WHAT A REVISION MAY NOT DO (checked here, before any consumer sees it)
----------------------------------------------------------------------
* rest on the wrong side of the current price (an instant fill is a close
  nobody decided -- `through_price`);
* rest beyond the venue cap measured from the CURRENT price (Bybit ErrCode
  10001's reference is the base price, not the entry): the rule's target is
  clamped to the cap and the reason SAYS it was clamped, because a clamped
  level is the venue's limit, not the prediction (`target_expectation`'s
  `clamped` state);
* be non-finite or non-positive.

A rule runs only for a leg that DECLARES it (`tp_revision: <rule>` or
`tp_revision: {rule: <rule>, ...}` in `config/strategies.yaml`, threaded into
the package meta like every other exit lever). Undeclared = no revision: a
rule is strategy logic and declaring it on a leg is Tier-3.

PURE: no I/O, no venue calls, never raises out of `plan_tp_revision`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT

__all__ = [
    "TP_KEY", "TP_REASON_KEY", "DECLARATION_KEY", "TpRevision", "RULES",
    "register_rule", "declared_rule", "rule_params", "tp_revision_rejection",
    "clamp_to_venue_cap", "plan_tp_revision", "as_verdict", "merge_verdict",
    "RULE_DONCHIAN_MEASURED_MOVE", "measured_move_path",
    "RULE_TP_EXTEND", "tp_extend_path",
]

TP_KEY = "tp"
TP_REASON_KEY = "tp_reason"
#: The per-leg declaration key (config/strategies.yaml, threaded into meta).
DECLARATION_KEY = "tp_revision"

REJECT_INVALID = "invalid_tp"
REJECT_THROUGH_PRICE = "through_price"
REJECT_DIRECTION = "unknown_direction"


@dataclass(frozen=True)
class TpRevision:
    """One revised prediction, ready to be placed."""

    tp: float
    rule: str
    reason: str
    clamped: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)


#: rule name -> fn(*, direction, entry, risk, bars, entry_time, params, leg) ->
#: (target, detail) | None. `bars` is a DataFrame of CLOSED bars only; `leg` is
#: the full leg config / package meta (a rule reads its structural params,
#: e.g. `donchian`, from it).
RuleFn = Callable[..., Optional[tuple]]
RULES: Dict[str, RuleFn] = {}


def register_rule(name: str) -> Callable[[RuleFn], RuleFn]:
    def deco(fn: RuleFn) -> RuleFn:
        RULES[name] = fn
        return fn
    return deco


def _f(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def declared_rule(cfg: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The rule a leg/package declares, or None. Accepts the bare string form
    and the mapping form (`{rule: ..., <params>}`)."""
    if not isinstance(cfg, Mapping):
        return None
    raw = cfg.get(DECLARATION_KEY)
    if isinstance(raw, Mapping):
        raw = raw.get("rule")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def rule_params(cfg: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw = (cfg or {}).get(DECLARATION_KEY) if isinstance(cfg, Mapping) else None
    if isinstance(raw, Mapping):
        return {k: v for k, v in raw.items() if k != "rule"}
    return {}


def tp_revision_rejection(direction: str, tp: Any, ref_price: Any) -> Optional[str]:
    """Why this TP may not be placed against ``ref_price``, or None."""
    t, p = _f(tp), _f(ref_price)
    if t is None or t <= 0 or p is None or p <= 0:
        return REJECT_INVALID
    if direction == "long":
        return REJECT_THROUGH_PRICE if t <= p else None
    if direction == "short":
        return REJECT_THROUGH_PRICE if t >= p else None
    return REJECT_DIRECTION


def clamp_to_venue_cap(direction: str, tp: float, ref_price: float,
                       cap_pct: float = TP_VENUE_CAP_PCT) -> tuple:
    """(tp, clamped) -- the level that can actually rest at the venue."""
    if direction == "long":
        cap = ref_price * (1.0 + cap_pct)
        return (cap, True) if tp > cap else (tp, False)
    cap = ref_price * (1.0 - cap_pct)
    return (cap, True) if tp < cap else (tp, False)


def plan_tp_revision(*, leg: Optional[Mapping[str, Any]], direction: str, entry: Any,
                     risk: Any, bars: Any, entry_time: Any, ref_price: Any,
                     cap_pct: float = TP_VENUE_CAP_PCT) -> Optional[TpRevision]:
    """The declared rule's current prediction for one open trade, or None.

    ``leg`` is the leg config or the package meta (both carry the
    declaration). ``bars`` are CLOSED bars (the forming bar excluded) with
    enough history before entry for the rule's lookback. ``ref_price`` is the
    latest price the venue will judge the TP against. None when the leg
    declares no rule, the rule is unknown, it cannot compute, or the result
    fails `tp_revision_rejection` -- a revision that cannot be placed is not
    sent, and the resting TP stays.
    """
    try:
        name = declared_rule(leg)
        if name is None or direction not in ("long", "short"):
            return None
        fn = RULES.get(name)
        e, r, p = _f(entry), _f(risk), _f(ref_price)
        if fn is None or e is None or r is None or r <= 0 or p is None:
            return None
        out = fn(direction=direction, entry=e, risk=r, bars=bars,
                 entry_time=entry_time, params=rule_params(leg), leg=leg)
        if not out:
            return None
        target, detail = out
        target = _f(target)
        if target is None:
            return None
        placed, clamped = clamp_to_venue_cap(direction, target, p, cap_pct)
        if tp_revision_rejection(direction, placed, p) is not None:
            return None
        target_r = (placed - e) / r if direction == "long" else (e - placed) / r
        reason = (f"{name}: target {placed:.8g} ({target_r:+.2f}R from entry)"
                  + (f", CLAMPED to the venue cap from {target:.8g}" if clamped else ""))
        return TpRevision(tp=round(placed, 8), rule=name, reason=reason, clamped=clamped,
                          detail={**(detail or {}), "target_r": round(target_r, 4),
                                  "unclamped": target})
    except Exception:  # noqa: BLE001 -- a revision must never break its caller
        return None


def as_verdict(rev: TpRevision) -> Dict[str, Any]:
    return {TP_KEY: rev.tp, TP_REASON_KEY: rev.reason}


def merge_verdict(base: Optional[Dict[str, Any]],
                  rev: Optional[TpRevision]) -> Optional[Dict[str, Any]]:
    """Attach a TP revision to a monitor verdict. A close verdict wins and is
    returned untouched; ``None`` + a revision is the revision alone."""
    if rev is None:
        return base
    if base is None:
        return as_verdict(rev)
    if base.get("action") == "close":
        return base
    return {**base, **as_verdict(rev)}


# ---------------------------------------------------------------------------
# Rule 1 -- trend_donchian family: the Donchian MEASURED MOVE (2026-10-07)
# ---------------------------------------------------------------------------
RULE_DONCHIAN_MEASURED_MOVE = "donchian_measured_move"


def measured_move_path(highs: Any, lows: Any, *, start: int, end: int, n: int,
                       direction: str, width_mult: float = 1.0) -> Optional[tuple]:
    """The measured-move prediction after bar ``end`` closed. Pure, index-based,
    so the live unit, the prop trail and ``scripts/backtest_trend.py`` call the
    SAME arithmetic on the same bars.

    For every closed bar ``k`` in ``[start, end]`` with a full ``n``-bar
    window, the channel INCLUDING bar k is ``hi_k = max(high[k-n+1..k])``,
    ``lo_k = min(low[k-n+1..k])``; the projection is the classic measured move
    -- the channel height carried past the edge the trade broke:
    ``hi_k + width_mult * (hi_k - lo_k)`` for a long,
    ``lo_k - width_mult * (hi_k - lo_k)`` for a short.

    The prediction is the most favourable projection seen so far (extend-only):
    the target follows the structure out as the trend makes new channel
    extremes, and does not contract on a pullback -- deciding the thesis has
    failed is the trail's job (doctrine clause 3), not the target's.
    Returns ``(target, detail)`` or None when no bar has a full window.
    """
    if n <= 0 or end < start or direction not in ("long", "short"):
        return None
    long_ = direction == "long"
    best = None
    best_k = None
    hi = lo = None
    for k in range(max(start, n - 1), end + 1):
        hk = max(float(x) for x in highs[k - n + 1:k + 1])
        lk = min(float(x) for x in lows[k - n + 1:k + 1])
        w = hk - lk
        if not (w > 0 and math.isfinite(w)):
            continue
        proj = hk + width_mult * w if long_ else lk - width_mult * w
        if best is None or (proj > best if long_ else proj < best):
            best, best_k, hi, lo = proj, k, hk, lk
    if best is None:
        return None
    return best, {"channel_hi": hi, "channel_lo": lo, "width": hi - lo,
                  "at_bar": best_k - start, "bars": end - start + 1, "n": n,
                  "width_mult": width_mult}


def _ts_utc(value: Any):
    import pandas as pd
    if value is None:
        return None
    try:
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value.strip())      # str(df["timestamp"]) of an epoch-ms column
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return pd.Timestamp(int(value), unit="ms", tz="UTC")
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    except (TypeError, ValueError):
        return None


@register_rule(RULE_DONCHIAN_MEASURED_MOVE)
def _donchian_measured_move(*, direction: str, entry: float, risk: float, bars: Any,
                            entry_time: Any, params: Mapping[str, Any],
                            leg: Mapping[str, Any]) -> Optional[tuple]:
    """``bars``: CLOSED bars (timestamp/high/low), history before entry
    included. The managed span starts at the bar holding ``entry_time`` (the
    signal bar: its structure is what the entry broke) and ends at the last
    closed bar. An unreadable entry time is *could not look* -> None."""
    import pandas as pd
    n = int(_f(params.get("donchian")) or _f(leg.get("donchian")) or 0)
    width_mult = _f(params.get("width_mult"))
    width_mult = 1.0 if width_mult is None or width_mult <= 0 else width_mult
    t_entry = _ts_utc(entry_time)
    if n <= 0 or t_entry is None or bars is None or len(bars) == 0:
        return None
    ts = bars["timestamp"]
    ts = (pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts)
          else pd.to_datetime(ts, utc=True))
    at_or_before = (ts <= t_entry).to_numpy().nonzero()[0]
    start = int(at_or_before[-1]) if len(at_or_before) else 0
    return measured_move_path(bars["high"].to_numpy(), bars["low"].to_numpy(), start=start,
                              end=len(bars) - 1, n=n, direction=direction,
                              width_mult=width_mult)


# ---------------------------------------------------------------------------
# Rule 2 -- htf_pullback family: EXTEND while the trend thesis holds (2026-10-22)
# ---------------------------------------------------------------------------
RULE_TP_EXTEND = "tp_extend"


def tp_extend_path(closes: Any, mids: Any, *, start: int, end: int, direction: str,
                   entry: float, risk: float, target_r: float, extend_r: float,
                   approach_frac: float = 0.85, max_extends: int = 3,
                   anchor_cap_pct: float = TP_VENUE_CAP_PCT) -> Optional[tuple]:
    """The tp_extend prediction after bar ``end`` closed. Pure, index-based.

    The live twin of ``scripts/research/tp_geometry.TPTracker`` with
    ``--tp-target-r T --tp-extend-r E --tp-thesis native --tp-cap-pct C`` on
    ``scripts/backtest_pullback.py``: the target starts at
    ``entry +/- target_r * risk``, clamped to ``entry * (1 +/- C)`` (the cap
    the entry-time TP of ``htf_pullback_trend_2h.order_package`` already
    carries; ``anchor_cap_pct`` <= 0 = no cap); on every CLOSED bar ``k`` in
    ``(start, end]`` -- ``start`` is the signal/entry bar, whose close IS the
    entry -- the SAME decision function the harness calls
    (``target_expectation.evaluate_extension``) is asked whether the target
    may move out by ``extend_r`` R, with the pullback family's native thesis:
    the close is still on the trend side of the Donchian ``trend_lookback``
    midline (``mids[k]``; NaN = *could not look* = never extends). At most
    ``max_extends`` extensions; a revised level binds from the next bar.

    Replayed from the bars every call, so it carries no state between monitor
    ticks: the same bars give the same target on a restart. Returns
    ``(target, detail)`` ONLY once at least one extension has fired -- before
    that the entry-time TP (placed by ``order_package``) already IS the
    prediction and nothing is sent. None also when it cannot compute.
    """
    from src.runtime.target_expectation import (
        EXT_EXTEND, evaluate_extension, resolve_expectation)
    if direction not in ("long", "short") or not (risk > 0) or not (target_r > 0) \
            or not (extend_r > 0) or end <= start or start < 0:
        return None
    long_ = direction == "long"
    sl0 = entry - risk if long_ else entry + risk

    def _cap(px: float) -> float:
        if not anchor_cap_pct > 0:
            return px
        cap = entry * (1.0 + anchor_cap_pct) if long_ else entry * (1.0 - anchor_cap_pct)
        return min(cap, px) if long_ else max(cap, px)

    target = _cap(entry + target_r * risk if long_ else entry - target_r * risk)
    n_ext = 0
    last_k = None
    thesis_at = None
    for k in range(start + 1, end + 1):
        c = _f(closes[k])
        if c is None:
            continue
        travelled = (c - entry) if long_ else (entry - c)
        approaching = travelled >= approach_frac * abs(target - entry)
        thesis: Optional[bool] = None
        if approaching:
            m = _f(mids[k])
            thesis = None if m is None else ((c > m) if long_ else (c < m))
        cur_r = ((target - entry) if long_ else (entry - target)) / risk
        expectation = resolve_expectation({"target_r": max(cur_r, 1e-9)}, entry=entry,
                                          sl=sl0, direction=direction)
        verdict = evaluate_extension(expectation, price=c, entry=entry, direction=direction,
                                     thesis_intact=thesis, extends_so_far=n_ext,
                                     approach_frac=approach_frac, extend_r=extend_r,
                                     max_extends=max_extends)
        if verdict["state"] == EXT_EXTEND and verdict["new_target"] is not None:
            new = _cap(float(verdict["new_target"]))
            if new != target:       # an extension the cap swallows is not one
                target = new
                n_ext += 1
                last_k, thesis_at = k, _f(mids[k])
    if n_ext == 0:
        return None
    return target, {"n_extends": n_ext, "max_extends": max_extends,
                    "extend_r": extend_r, "base_target_r": target_r,
                    "last_extend_bar": last_k - start, "midline_at_last_extend": thesis_at,
                    "bars": end - start}


@register_rule(RULE_TP_EXTEND)
def _tp_extend(*, direction: str, entry: float, risk: float, bars: Any,
               entry_time: Any, params: Mapping[str, Any],
               leg: Mapping[str, Any]) -> Optional[tuple]:
    """``bars``: CLOSED bars (timestamp/high/low/close), history before entry
    included (the midline needs ``trend_lookback`` of it). Declared as
    ``tp_revision: {rule: tp_extend, extend_r: <R>, approach_frac: <f>,
    max_extends: <n>[, target_r: <R>][, trend_lookback: <n>][, anchor_cap_pct: <f>]}``; ``target_r``
    falls back to the leg's ``tp_r`` (the entry-time TP), ``trend_lookback``
    to the leg's. ``extend_r`` has NO default: an undeclared step is not a
    revision. A sentinel ``tp_r`` never extends (``evaluate_extension``).
    An unreadable entry time, or an entry bar not in ``bars``, is *could not
    look* -> None."""
    import pandas as pd
    extend_r = _f(params.get("extend_r"))
    target_r = _f(params.get("target_r"))
    if target_r is None:
        target_r = _f(leg.get("tp_r"))
    trend_lb = int(_f(params.get("trend_lookback")) or _f(leg.get("trend_lookback")) or 0)
    cap_pct = _f(params.get("anchor_cap_pct"))
    cap_pct = TP_VENUE_CAP_PCT if cap_pct is None else cap_pct
    approach = _f(params.get("approach_frac"))
    approach = 0.85 if approach is None or not 0.0 < approach <= 1.0 else approach
    max_ext = _f(params.get("max_extends"))
    max_ext = 3 if max_ext is None or max_ext < 0 else int(max_ext)
    t_entry = _ts_utc(entry_time)
    if (extend_r is None or extend_r <= 0 or target_r is None or target_r <= 0
            or trend_lb <= 0 or t_entry is None or bars is None or len(bars) == 0):
        return None
    ts = bars["timestamp"]
    ts = (pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts)
          else pd.to_datetime(ts, utc=True))
    at = (ts == t_entry).to_numpy().nonzero()[0]
    if not len(at):
        return None
    # The ONE midline definition (htf_pullback_trend_2h._trend_midline, which
    # scripts/backtest_pullback.py's df["mid"] matches): prior trend_lb bars,
    # shift(1), no lookahead.
    b = bars.reset_index(drop=True)
    mids = ((b["high"].rolling(trend_lb).max().shift(1)
             + b["low"].rolling(trend_lb).min().shift(1)) / 2.0).to_numpy()
    return tp_extend_path(b["close"].to_numpy(), mids, start=int(at[-1]), end=len(b) - 1,
                          direction=direction, entry=entry, risk=risk, target_r=target_r,
                          extend_r=extend_r, approach_frac=approach, max_extends=max_ext,
                          anchor_cap_pct=cap_pct)
