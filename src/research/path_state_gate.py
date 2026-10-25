"""PATHSTATE-TRAIL-GATE: gate an exit lever on the trade's own in-trade path state (Tier-1 research).

Queue units RQ-20261022-b7e1-04..10 ask whether a tight trail / a partial bank / a time-in-chop stop helps
when the path says the move has gone non-directional, rather than on every trade. The harnesses
(``scripts/backtest_pullback.py``, ``scripts/backtest_trend.py``) take three default-off, byte-identical
declarations that share ONE per-trade state tracker:

* ``--trail-state-*`` -- the trail mult drops to ``--trail-state-tight-mult`` on bars where peak R >= arm R
  AND the feature condition held at the previous close. Composes by MINIMUM with every other tightener.
* ``--bank-state-*``  -- the ``--bank-frac`` / ``--bank-at-r`` rung may only fill on bars where the same
  kind of condition held at the previous close.
* ``--chop-stop-*``   -- close at market (at the bar close) once the condition has held for N consecutive
  bars while peak R >= min peak and open R <= max-open-frac x peak.

The features are NOT re-derived here: ``scripts/research/path_state_giveback.py::state_at`` (the function
``trade_states`` calls, so the screen that motivated the units and the gate cannot drift) computes them from
rows ``0..t`` only. The decision is read at the CLOSE of bar t and first binds on bar t+1 (the chop-stop
exits at bar t's own close, like the giveback stop), so a change to any bar after t cannot change the
decision at t.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

FEATURES = ("er", "chop", "atr_ratio", "dist_atr")
_STATE_KEY = {"er": "er_w", "chop": "chop_w", "atr_ratio": "atr_ratio_t", "dist_atr": "dist_atr_t"}
OPS = ("lt", "gt")
# --chop-stop-op default: the direction in which each feature reads "the move has gone sideways".
DEFAULT_OP = {"er": "lt", "chop": "gt", "atr_ratio": "lt", "dist_atr": "gt"}


@dataclass(frozen=True)
class Cond:
    feature: str
    window: int
    op: str
    thr: float

    def holds(self, st: Optional[Dict[str, Any]]) -> bool:
        """False where the feature is undefined: "we could not compute it" never gates an action on."""
        if st is None:
            return False
        v = st[_STATE_KEY[self.feature]]
        return v < self.thr if self.op == "lt" else v > self.thr


def _cond_errors(prefix: str, feature: str, window: int, op: str, thr: float) -> List[str]:
    errs: List[str] = []
    if feature not in FEATURES:
        errs.append(f"--{prefix}-feature must be one of {FEATURES}, got {feature!r}")
    if window < 2:
        errs.append(f"--{prefix}-window must be >= 2 bars, got {window}")
    if op and op not in OPS:
        errs.append(f"--{prefix}-op must be one of {OPS}, got {op!r}")
    if feature == "er" and not 0.0 <= thr <= 1.0:
        errs.append(f"--{prefix}-thr for er is an efficiency ratio in [0, 1], got {thr}")
    return errs


def path_state_flag_errors(trail_feature: str, trail_window: int, trail_op: str, trail_thr: float,
                           trail_arm_r: float, trail_tight_mult: float,
                           bank_feature: str, bank_window: int, bank_op: str, bank_thr: float,
                           bank_arm_r: float, bank_frac: float, bank_at_r: float,
                           chop_feature: str, chop_window: int, chop_op: str, chop_thr: float,
                           chop_bars: int, chop_min_peak_r: float, chop_max_open_frac: float,
                           trail_mult: float, trail_decay_tight_mult: float) -> List[str]:
    """Refusals for a half-declared or inert gate. All-defaults returns []."""
    errs: List[str] = []
    if trail_feature or trail_tight_mult > 0.0:
        if not (trail_feature and trail_tight_mult > 0.0):
            errs.append("--trail-state-feature and --trail-state-tight-mult must be declared together: half a "
                        "declaration is inert")
        else:
            errs += _cond_errors("trail-state", trail_feature, trail_window, trail_op, trail_thr)
            if not trail_tight_mult < trail_mult:
                errs.append(f"--trail-state-tight-mult ({trail_tight_mult}) must be below --trail-mult "
                            f"({trail_mult}): a gate that cannot tighten is inert")
            if trail_arm_r < 0.0:
                errs.append("--trail-state-arm-r must be >= 0")
    if bank_feature:
        errs += _cond_errors("bank-state", bank_feature, bank_window, bank_op, bank_thr)
        if not (bank_frac > 0.0 and bank_at_r > 0.0):
            errs.append("--bank-state-feature needs --bank-frac > 0 and --bank-at-r > 0 (the rung it gates)")
        if bank_arm_r < 0.0:
            errs.append("--bank-state-arm-r must be >= 0")
    if chop_feature or chop_bars > 0:
        if not (chop_feature and chop_bars > 0):
            errs.append("--chop-stop-feature and --chop-stop-bars must be declared together: half a "
                        "declaration is inert")
        else:
            errs += _cond_errors("chop-stop", chop_feature, chop_window, chop_op, chop_thr)
            if chop_min_peak_r < 0.0:
                errs.append("--chop-stop-min-peak-r must be >= 0")
            if not 0.0 < chop_max_open_frac <= 1.0:
                errs.append("--chop-stop-max-open-frac must be in (0, 1]: open R as a share of peak R")
    return errs


def _state_at():
    """The ONE feature function (lazy: a flag-off harness run never imports it)."""
    here = str(Path(__file__).resolve().parents[2] / "scripts" / "research")
    if here not in sys.path:
        sys.path.insert(0, here)
    from path_state_giveback import state_at
    return state_at


class PathStateGate:
    """Per-trade tracker. ``start`` once per trade, ``on_bar_close`` once per leg bar after the ratchet."""

    def __init__(self, trail: Optional[Cond], trail_arm_r: float, trail_tight_mult: float,
                 bank: Optional[Cond], bank_arm_r: float,
                 chop: Optional[Cond], chop_bars: int, chop_min_peak_r: float, chop_max_open_frac: float) -> None:
        self.trail, self.trail_arm_r, self.trail_tight_mult = trail, trail_arm_r, trail_tight_mult
        self.bank, self.bank_arm_r = bank, bank_arm_r
        self.chop, self.chop_bars = chop, chop_bars
        self.chop_min_peak_r, self.chop_max_open_frac = chop_min_peak_r, chop_max_open_frac
        self.on = bool(trail or bank or chop)
        self._state_at = _state_at() if self.on else None
        self.n_trail_bars = self.n_bank_gated = self.n_chop_exits = 0
        self.start()

    def start(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.trail_on = False      # tight mult applies on the NEXT bar
        self.bank_ok = False       # the bank rung may fill on the NEXT bar
        self._streak = 0

    def _state(self, cond: Cond) -> Optional[Dict[str, Any]]:
        return self._state_at(self.rows, len(self.rows) - 1, cond.window)

    def on_bar_close(self, row: Dict[str, Any]) -> bool:
        """Feed bar t's close-state row (c_r, fav_r, adv_r, open_r, peak_r, bars_since_peak, atr_r,
        dist_to_stop_r: the ``PathRecorder`` fields). Returns True when the chop-stop fires at this close."""
        self.rows.append(row)
        peak, open_r = float(row["peak_r"]), float(row["open_r"])
        if self.trail is not None:
            self.trail_on = peak >= self.trail_arm_r and self.trail.holds(self._state(self.trail))
            self.n_trail_bars += int(self.trail_on)
        if self.bank is not None:
            self.bank_ok = peak >= self.bank_arm_r and self.bank.holds(self._state(self.bank))
        if self.chop is not None:
            q = (peak >= self.chop_min_peak_r and peak > 0.0 and open_r <= self.chop_max_open_frac * peak
                 and self.chop.holds(self._state(self.chop)))
            self._streak = self._streak + 1 if q else 0
            if self._streak >= self.chop_bars:
                self.n_chop_exits += 1
                return True
        return False

    def tight(self, mult: float) -> float:
        """The trail mult in force on the current bar, composed by MINIMUM with ``mult``."""
        return min(mult, self.trail_tight_mult) if self.trail_on else mult

    def bank_allowed(self) -> bool:
        return self.bank is None or self.bank_ok

    def summary(self) -> Dict[str, Any]:
        return {"trail_state_bars": self.n_trail_bars if self.trail else None,
                "chop_stop_exits": self.n_chop_exits if self.chop else None}


def build_gate(trail_feature: str, trail_window: int, trail_op: str, trail_thr: float, trail_arm_r: float,
               trail_tight_mult: float, bank_feature: str, bank_window: int, bank_op: str, bank_thr: float,
               bank_arm_r: float, chop_feature: str, chop_window: int, chop_op: str, chop_thr: float,
               chop_bars: int, chop_min_peak_r: float, chop_max_open_frac: float) -> PathStateGate:
    trail = (Cond(trail_feature, trail_window, trail_op or DEFAULT_OP[trail_feature], trail_thr)
             if trail_feature and trail_tight_mult > 0.0 else None)
    bank = Cond(bank_feature, bank_window, bank_op or DEFAULT_OP[bank_feature], bank_thr) if bank_feature else None
    chop = (Cond(chop_feature, chop_window, chop_op or DEFAULT_OP[chop_feature], chop_thr)
            if chop_feature and chop_bars > 0 else None)
    return PathStateGate(trail, trail_arm_r, trail_tight_mult, bank, bank_arm_r,
                         chop, chop_bars, chop_min_peak_r, chop_max_open_frac)


def gate_row(entry: float, risk: float, is_long: bool, close: float, high: float, low: float,
             peak_r: float, bars_since_peak: int, atr: float, stop: float) -> Dict[str, Any]:
    """One bar's close-state row in the ``PathRecorder`` schema, from the harness's own running state."""
    def r(px: float) -> float:
        return (px - entry) / risk if is_long else (entry - px) / risk
    c_r = r(close)
    fav, adv = (r(high), r(low)) if is_long else (r(low), r(high))
    return {"c_r": c_r, "fav_r": fav, "adv_r": adv, "open_r": c_r, "peak_r": float(peak_r),
            "bars_since_peak": int(bars_since_peak), "atr_r": atr / risk, "dist_to_stop_r": c_r - r(stop)}
