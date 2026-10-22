"""The ONE definition of the chandelier trail-lever firing rule.

The sibling of `src/runtime/execution_costs.py` ("the ONE shared cost model") for
the *exit-lever* side, and it exists for the same reason that one does: this rule
had already been written **twice**.

MEASURED 2026-08-17, before this module existed:

* `scripts/backtest_trend.py::_effective_trail_mult` — the full rule (trail-decay
  and vol-conditional, composing by minimum), reused by
  `scripts/research/m20_trail_attribution.py` via a dynamic module load;
* `scripts/backtest_pullback.py` — its **own inline** vol-tail test
  (`fired = ((trail_vol_above_pctl > 0.0 and float(vp) > trail_vol_above_pctl) ...)`).

Two derivations of one bound is the defect `tests/test_fold_reachability_is_derived.py`
exists to pin, and the M20 coverage roll-up hit the same class on 2026-08-17 (a
re-derived fold bound beside the one `fold_reachability` computes). A THIRD copy
was about to be added for `scripts/backtest_squeeze.py`, which is what prompted
this move: the squeeze harness had `--trail-mult` but no `--trail-vol-*` at all,
so `vol_trail` was unreachable there and every such matrix cell read
`blocked:no_harness_levers`.

**This is a verbatim MOVE, not a rewrite.** The body is byte-for-byte the
function that produced the recorded corpus, verified against three armed
baselines on `data/backtest_candles.csv` (levers-off, vol-armed, decay-armed —
137 / 153 / 144 trades, three distinct md5s, so the check can actually detect a
change). `backtest_trend.py` keeps a module-level alias so callers that resolve
`_effective_trail_mult` by name — `m20_trail_attribution.py` does exactly that —
keep working.

Do NOT re-inline this rule into a harness. A lever whose firing condition is
stated in two places is free to drift, and a drifted exit lever silently
re-grades every cell measured against it.
"""
from __future__ import annotations

import pandas as pd


def effective_trail_mult(base: float, peak_r: float, bars_since_peak: int,
                         decay_on: bool, decay_arm_r: float,
                         decay_stall_bars: int, decay_tight_mult: float,
                         vol_on: bool, atr_pctl, j: int,
                         vol_above_pctl: float, vol_below_pctl: float,
                         vol_tight_mult: float,
                         adx_on: bool = False, adx=None,
                         adx_below: float = 0.0, adx_falling_bars: int = 0,
                         adx_tight_mult: float = 0.0) -> float:
    """The chandelier trail mult in force on ONE managed bar.

    Two independent tighteners, both **no-ops at their defaults** so the caller's
    arithmetic is byte-identical to the pre-lever engine when neither is declared:

    * **M20 P4.1 trail-decay** — tighten once the move shows exhaustion, either
      R-armed (``peak_r >= decay_arm_r``) or stall-armed (``decay_stall_bars`` or
      more bars since the last new favourable extreme). A new peak re-loosens the
      MULT; the caller's price ratchet never loosens the STOP.
    * **M20-X vol-conditional trail** — tighten on a bar whose trailing ATR
      percentile sits in a gated tail. Conditional, not a ratchet; an undefined
      percentile (window unfilled) leaves it inert.

    * **Momentum trail** (``adx_on``; MOMENTUM-TRAIL-LEVER, memo
      docs/research/cross-signal-exits-2026-10-07.md § 4.1) — tighten on a bar
      whose ADX reads fading momentum (`momentum_trail_fired`). Keyed to
      MOMENTUM, not to price path.

    When more than one fires the TIGHTEST wins, matching the research harness
    this was ported from — the levers compose by minimum, never by sum. The
    momentum arguments default to off, so a caller that does not pass them gets
    the pre-lever arithmetic exactly.
    """
    tm = base
    if decay_on:
        armed = ((decay_arm_r > 0.0 and peak_r >= decay_arm_r)
                 or (decay_stall_bars > 0 and bars_since_peak >= decay_stall_bars))
        if armed:
            tm = decay_tight_mult
    if vol_on and atr_pctl is not None:
        vp = atr_pctl.iloc[j]
        if not pd.isna(vp):
            if ((vol_above_pctl > 0.0 and float(vp) > vol_above_pctl)
                    or (vol_below_pctl > 0.0 and float(vp) < vol_below_pctl)):
                tm = min(tm, vol_tight_mult)
    if adx_on and momentum_trail_fired(adx, j, adx_below, adx_falling_bars):
        tm = min(tm, adx_tight_mult)
    return tm


def vol_trail_armed(trail_vol_tight_mult: float,
                    trail_vol_above_pctl: float,
                    trail_vol_below_pctl: float) -> bool:
    """Is the vol-conditional trail declared at all?

    Hoisted beside the rule it gates because the two harnesses that already had
    this lever ALSO each re-stated this predicate. A tight mult with no tail, or
    a tail with no tight mult, is not a declaration — it is a half-configured
    lever, and reading it as armed would tighten on a bound nobody set.
    """
    return (trail_vol_tight_mult > 0.0
            and (trail_vol_above_pctl > 0.0 or trail_vol_below_pctl > 0.0))


def momentum_trail_armed(adx_below: float, adx_falling_bars: int,
                         adx_tight_mult: float) -> bool:
    """Is the ADX-conditioned trail declared at all?

    A tight mult with no condition, or a condition with no tight mult, is a
    half-configured lever and reads as NOT armed (same contract as
    `vol_trail_armed`) — so a bare ``--trail-adx-tight-mult`` can never tighten
    every bar unannounced.
    """
    return (adx_tight_mult > 0.0
            and (adx_below > 0.0 or adx_falling_bars > 0))


def momentum_trail_fired(adx, j: int, adx_below: float,
                         adx_falling_bars: int) -> bool:
    """Does the momentum-trail condition hold on managed bar ``j``?

    ``adx`` is a per-bar ADX series (positional). Both declared conditions must
    hold: ``ADX_j < adx_below`` (when ``adx_below > 0``) AND
    ``ADX_j < ADX_{j-k}`` (when ``adx_falling_bars = k > 0``) — memo § 4.1, so
    ``adx20_k3`` reads "ADX under 20 *and* lower than 3 bars ago". With only one
    declared, that one alone decides. NaN anywhere it is read (warm-up) is inert
    — fail-permissive, as `vol_trail`.
    """
    if adx is None:
        return False
    a = adx.iloc[j]
    if pd.isna(a):
        return False
    if adx_below > 0.0 and not float(a) < adx_below:
        return False
    if adx_falling_bars > 0:
        if j - adx_falling_bars < 0:
            return False
        ref = adx.iloc[j - adx_falling_bars]
        if pd.isna(ref) or not float(a) < float(ref):
            return False
    return adx_below > 0.0 or adx_falling_bars > 0


def momentum_stale_armed(stale_bars: int, stale_adx_below: float) -> bool:
    """Is the momentum-keyed time stop declared? Needs BOTH knobs (a bar count
    with no ADX bound, or the reverse, is half-configured and reads off)."""
    return stale_bars > 0 and stale_adx_below > 0.0


def momentum_stale_fires(adx, j: int, entry_i: int, stale_bars: int,
                         stale_adx_below: float) -> bool:
    """Should the momentum-keyed time stop close the trade at bar ``j``'s CLOSE?

    ``(j - entry_i) >= N`` AND ``ADX_j < ADX_entry`` AND ``ADX_j < A`` (memo
    § 4.2). Open R is deliberately NOT consulted — that is the whole difference
    from `stale_stop`. NaN at either point is inert.
    """
    if adx is None or (j - entry_i) < stale_bars:
        return False
    a, a0 = adx.iloc[j], adx.iloc[entry_i]
    if pd.isna(a) or pd.isna(a0):
        return False
    return float(a) < float(a0) and float(a) < stale_adx_below


def momentum_flag_errors(trail_mult: float, adx_below: float,
                         adx_falling_bars: int, adx_tight_mult: float,
                         stale_bars: int, stale_adx_below: float) -> list:
    """Refusals for half-configured / inert momentum-lever combinations.

    A lever that is declared but cannot act reports a zero delta that is NOT a
    measurement of it (the `rr_floor` precedent), so the CLIs refuse rather than
    run it. Returns human-readable messages; empty = fine.
    """
    errs = []
    cond = adx_below > 0.0 or adx_falling_bars > 0
    if (adx_tight_mult > 0.0) != cond:
        errs.append("--trail-adx-tight-mult needs --trail-adx-below and/or "
                    "--trail-adx-falling-bars (and vice versa): a half-declared "
                    "momentum_trail is inert")
    if adx_tight_mult > 0.0 and adx_tight_mult >= trail_mult:
        errs.append(f"--trail-adx-tight-mult ({adx_tight_mult}) must be < "
                    f"--trail-mult ({trail_mult}): the lever can only tighten")
    if (stale_bars > 0) != (stale_adx_below > 0.0):
        errs.append("--momentum-stale-bars and --momentum-stale-adx-below must "
                    "be declared together: a half-declared momentum_stale is inert")
    return errs


# ── P1-Q10 level-triggered trail (operator idea, IDEAS.md 2026-10-21) ────────
#: Structural levels the trail can key on. The R-armed variant ("tighten once
#: R >= N") is NOT re-implemented here: it is `effective_trail_mult`'s
#: ``decay_arm_r`` with ``decay_stall_bars = 0`` (``--trail-decay-arm-r N
#: --trail-decay-tight-mult M``), and a second spelling of one rule is the defect
#: this module exists to prevent.
LEVEL_KINDS = ("swing", "fvg", "round")


def level_trail_armed(kind: str, tight_mult: float) -> bool:
    """Is the level-triggered trail declared? Needs a kind AND a tight mult."""
    return bool(kind) and tight_mult > 0.0


def level_flag_errors(kind: str, tight_mult: float, trail_mult: float,
                      lookback: int, pivot_k: int, round_step: float) -> list:
    """Refusals for a half-declared / inert level trail (same contract as
    `momentum_flag_errors`: a lever that cannot act reports a zero delta that is
    NOT a measurement of it)."""
    errs = []
    if kind and kind not in LEVEL_KINDS:
        errs.append(f"--trail-level must be one of {LEVEL_KINDS}, got {kind!r}")
    if bool(kind) != (tight_mult > 0.0):
        errs.append("--trail-level and --trail-level-tight-mult must be declared together: "
                    "a half-declared level trail is inert")
    if tight_mult > 0.0 and tight_mult >= trail_mult:
        errs.append(f"--trail-level-tight-mult ({tight_mult}) must be < --trail-mult "
                    f"({trail_mult}): the lever can only tighten")
    if lookback < 3 or pivot_k < 1:
        errs.append("--trail-level-lookback must be >= 3 and --trail-level-pivot-k >= 1")
    if round_step < 0.0:
        errs.append("--trail-level-round-step must be >= 0 (0 = auto from the entry price)")
    return errs


def auto_round_step(price: float) -> float:
    """One decade below the price's leading digit: ETH 2,500 -> 100, BTC 60,000 ->
    1,000, ADA 0.45 -> 0.01. Fixed rule, not a fit; an explicit step overrides it."""
    import math
    if not price > 0.0:
        raise ValueError(f"round level needs a positive price, got {price!r}")
    return 10.0 ** (math.floor(math.log10(price)) - 1)


def round_level(entry: float, is_long: bool, step: float = 0.0) -> float:
    """The first round multiple of ``step`` strictly BEYOND entry in the trade's
    direction (above for a long, below for a short)."""
    import math
    s = step if step > 0.0 else auto_round_step(entry)
    k = math.floor(entry / s) + 1 if is_long else math.ceil(entry / s) - 1
    return round(k * s, 12)


def swing_level(high, low, entry_i: int, entry: float, is_long: bool,
                lookback: int, pivot_k: int):
    """The most recent CONFIRMED swing extreme beyond entry, or None.

    Long: a pivot high (``high[i]`` >= every high within ``pivot_k`` bars each side)
    strictly above ``entry``; short: a pivot low strictly below. Only pivots whose
    right-hand ``pivot_k`` bars closed BEFORE the entry bar are eligible (``i +
    pivot_k < entry_i``), so nothing is read from the future. Searched over the
    ``lookback`` bars before entry, most recent first. ``high``/``low`` are
    positional sequences (numpy arrays or lists)."""
    lo_i = max(pivot_k, entry_i - lookback)
    for i in range(entry_i - pivot_k - 1, lo_i - 1, -1):
        if is_long:
            v = float(high[i])
            if v > entry and all(v >= float(high[x]) for x in range(i - pivot_k, i + pivot_k + 1)):
                return v
        else:
            v = float(low[i])
            if v < entry and all(v <= float(low[x]) for x in range(i - pivot_k, i + pivot_k + 1)):
                return v
    return None


def fvg_level(high, low, entry_i: int, entry: float, is_long: bool, lookback: int):
    """The NEAREST unfilled OPPOSING fair-value gap beyond entry, or None.

    Long: a bearish FVG above price -- bar ``i`` with ``high[i] < low[i-2]`` (a gap
    down), zone ``(high[i], low[i-2])``; the level is the zone's near edge
    ``high[i]``. Short: a bullish FVG below -- ``low[i] > high[i-2]``, level
    ``low[i]``. Formed within ``lookback`` bars before entry (``i <= entry_i - 1``,
    closed bars only) and UNFILLED up to the entry bar: no bar in ``(i, entry_i)``
    traded back to the near edge. Computed on the harness's own bars -- the node
    names a 1h FVG; on a 4h/2h leg the leg's own timeframe is used, stated in the
    unit, because the harness holds one candle stream."""
    best = None
    for i in range(max(2, entry_i - lookback), entry_i):
        if is_long:
            if float(high[i]) < float(low[i - 2]):
                edge = float(high[i])
                if edge > entry and all(float(high[x]) < edge for x in range(i + 1, entry_i)):
                    best = edge if best is None or edge < best else best
        else:
            if float(low[i]) > float(high[i - 2]):
                edge = float(low[i])
                if edge < entry and all(float(low[x]) > edge for x in range(i + 1, entry_i)):
                    best = edge if best is None or edge > best else best
    return best


def trade_level(kind: str, high, low, entry_i: int, entry: float, is_long: bool,
                lookback: int, pivot_k: int, round_step: float):
    """The one structural level for a trade, fixed AT ENTRY (never re-read later)."""
    if kind == "round":
        return round_level(entry, is_long, round_step)
    if kind == "swing":
        return swing_level(high, low, entry_i, entry, is_long, lookback, pivot_k)
    if kind == "fvg":
        return fvg_level(high, low, entry_i, entry, is_long, lookback)
    raise ValueError(f"unknown level kind {kind!r}")


def level_touched(level, is_long: bool, bar_high: float, bar_low: float) -> bool:
    """Did this bar trade AT or THROUGH the level? None (no level) never touches."""
    if level is None:
        return False
    return bar_high >= level if is_long else bar_low <= level
