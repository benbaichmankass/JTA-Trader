"""The TP-distance gate on the --be-floor-r profit lock (row PROFIT-LOCK-CONDITIONAL-TEST, 2026-11-14).

Operator 2026-11-14 ~08:53Z, on a real-money short sitting at +2.6R open with its TP close by and its stop barely past
entry: "there's no way that we can leave this much R on the table". The 2026-10-28 advice-only verdict on tightens
pooled every tighten in every state; this gate expresses the CONDITIONAL lock -- arm the floor only once the trade's
extreme sits within ``within_r`` R of a resting take-profit. Both harnesses (scripts/backtest_trend.py,
scripts/backtest_pullback.py) call this one rule, loaded by file and only when the flag is armed.
"""
from __future__ import annotations

from typing import Optional


def tp_gate_open(is_long: bool, ext: float, tp_price: Optional[float], risk: float, within_r: float) -> bool:
    """True when a resting TP exists and the extreme ``ext`` is within ``within_r`` R of it (at or past it counts)."""
    if tp_price is None or risk <= 0.0:
        return False
    dist_r = ((tp_price - ext) if is_long else (ext - tp_price)) / risk
    return dist_r <= within_r
