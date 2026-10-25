"""HARNESS-METRIC-TRIGGER: act on a trade only if an out-of-fold metric flagged it (Tier-1 research).

Programme 01 Q11 rung 2 asks whether a metric-TRIGGERED action (bank / tight trail) beats the declared
exit AND the same action applied to every trade. The harnesses (``scripts/backtest_pullback.py``,
``scripts/backtest_trend.py``) therefore take one of two mutually exclusive trigger sources, both
default-off and byte-identical when absent:

* ``--trigger-file FILE`` -- JSONL, one row per trade the producer scored:
  ``{"trade_key": <harness_emit.trade_key>, "k": <bar offset>, "trigger": bool, "p": float|null}``.
  Written by ``scripts/research/path_metric_giveback.py --emit-triggers`` from a model fit on the OTHER
  calendar folds only. A trade with no row, or ``trigger: false``, is not acted on. An EMPTY file is
  valid (nothing flagged => every arm byte-identical to the declared leg); a MISSING file is an error
  ("we did not look" is not "nothing flagged").
* ``--trigger-all K`` -- the unconditional control: act on every trade still open at bar offset K.

``--trigger-action bank|tight`` says what the action is, using the harness's own existing levers:
``bank`` = the ``--bank-frac`` / ``--bank-at-r`` rung, live only on triggered trades and only from the bar
AFTER the trigger bar; ``tight`` = the trail mult drops to ``--trail-decay-tight-mult`` from the bar
after the trigger bar (the stop still never loosens).

The decision is made at the CLOSE of bar offset ``k`` (features read bars 1..k only), so the action can
first bind on bar k+1. A trade that exits on or before bar k is outside the population on both arms.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

ACTIONS = ("bank", "tight")


def load_triggers(path: str) -> Dict[str, int]:
    """trade_key -> trigger bar offset, for the rows flagged ``trigger: true``.

    Raises FileNotFoundError on a missing file and ValueError on a malformed row: a typo must
    never read as "nothing was flagged"."""
    out: Dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        for n, ln in enumerate(fh, 1):
            if not ln.strip():
                continue
            row = json.loads(ln)
            if "trade_key" not in row or "trigger" not in row or "k" not in row:
                raise ValueError(f"{path}:{n}: trigger row needs trade_key, k and trigger, got {sorted(row)}")
            k = int(row["k"])
            if k < 1:
                raise ValueError(f"{path}:{n}: trigger bar offset k must be >= 1, got {k}")
            if row["trigger"]:
                out[str(row["trade_key"])] = k
    return out


def trigger_flag_errors(action: str, trigger_file: str, trigger_all: int, bank_frac: float,
                        bank_at_r: float, trail_mult: float, trail_decay_tight_mult: float,
                        trail_decay_arm_r: float, trail_decay_stall_bars: int) -> List[str]:
    """Refusals for an inert / ambiguous trigger declaration."""
    errs: List[str] = []
    src = bool(trigger_file) + (trigger_all > 0)
    if not action and not src:
        return errs
    if action and action not in ACTIONS:
        errs.append(f"--trigger-action must be one of {ACTIONS}, got {action!r}")
    if bool(action) != bool(src):
        errs.append("--trigger-action and exactly one of --trigger-file / --trigger-all must be "
                    "declared together: half a declaration is inert")
    if src > 1:
        errs.append("--trigger-file and --trigger-all are mutually exclusive")
    if trigger_all < 0:
        errs.append("--trigger-all must be >= 1 (a bar offset after entry)")
    if trigger_file and not Path(trigger_file).is_file():
        errs.append(f"--trigger-file {trigger_file!r} does not exist (an empty file is valid, a missing one is not)")
    if action == "bank" and not (bank_frac > 0.0 and bank_at_r > 0.0):
        errs.append("--trigger-action bank needs --bank-frac > 0 and --bank-at-r > 0 (the rung it applies)")
    if action == "tight":
        if not 0.0 < trail_decay_tight_mult < trail_mult:
            errs.append(f"--trigger-action tight needs 0 < --trail-decay-tight-mult < --trail-mult "
                        f"({trail_mult}), got {trail_decay_tight_mult}")
        if trail_decay_arm_r > 0.0 or trail_decay_stall_bars > 0:
            errs.append("--trigger-action tight reuses --trail-decay-tight-mult as the triggered mult, so "
                        "--trail-decay-arm-r / --trail-decay-stall-bars must be 0: otherwise decay would "
                        "tighten untriggered trades too and the contrast is not a trigger effect")
    return errs


class TriggerPlan:
    """Per-run lookup: at which bar offset (if any) does this trade's action start?"""

    def __init__(self, action: str, trigger_file: str, trigger_all: int) -> None:
        self.action = action
        self.on = bool(action)
        self.trigger_all = trigger_all
        self.file_k: Dict[str, int] = load_triggers(trigger_file) if trigger_file else {}
        self.n_flagged_in_file = len(self.file_k)
        self.n_acted = 0

    def k_for(self, trade_key: str) -> Optional[int]:
        if not self.on:
            return None
        if self.trigger_all > 0:
            return self.trigger_all
        return self.file_k.get(trade_key)

    def summary(self) -> dict:
        return {"action": self.action, "trigger_all": self.trigger_all or None,
                "n_flagged_in_file": self.n_flagged_in_file if not self.trigger_all else None,
                "n_acted": self.n_acted}
