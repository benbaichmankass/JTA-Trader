"""Per-leg placement backoff after repeated exchange rejections (IB-MGC-INACTIVE-1125).

WHY: a leg whose signal persists re-dispatches every tick. When the venue
refuses the order for a reason that will not clear in a minute (MEASURED
2026-11-25: ``ib_paper``/``mgc_trend_1h`` hit IBKR Error 201 -- the front
month was inside its physical-delivery window -- on every 1-min tick, 30
failures 14:46-15:15Z and 60+ by evening), the coordinator journaled a
rejection row, fired an execution-failure ping and re-raised the critical
"consecutive rejections" alert EVERY minute.

WHAT: failures are contained PER ITEM -- key ``(account, strategy, symbol,
direction)`` -- and retried with exponential backoff. The first
``GRACE_FAILURES`` attempts run at tick cadence (a transient refusal clears
itself); after that the next attempt waits ``BASE_DELAY_S * 2**k``, capped at
``MAX_DELAY_S``. It NEVER stops retrying (Prime Directive rule 7: no halting)
and never touches ``mode:`` / ``execution:``. ``should_flag`` is True exactly
once per streak, so the operator gets ONE red flag, not one per minute.
A success (or any non-failure outcome for the key) clears the streak.

In-process state: a restart clears it, which only means the next signal is
tried at once -- the safe direction.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

GRACE_FAILURES = 3
BASE_DELAY_S = 120.0
MAX_DELAY_S = 3600.0

Key = Tuple[str, str, str, str]


@dataclass
class _Streak:
    failures: int = 0
    next_attempt_at: float = 0.0
    flagged: bool = False
    last_reason: str = ""
    first_failure_at: float = field(default=0.0)


_LOCK = threading.Lock()
_STREAKS: Dict[Key, _Streak] = {}
_clock: Callable[[], float] = time.time


def key_for(account: str, strategy: Optional[str], symbol: Optional[str], direction: Optional[str]) -> Key:
    return (str(account or "?"), str(strategy or "?"), str(symbol or "?").upper(), str(direction or "?").lower())


def delay_after(failures: int) -> float:
    """Seconds to wait before the next attempt after *failures* consecutive failures."""
    if failures < GRACE_FAILURES:
        return 0.0
    return min(MAX_DELAY_S, BASE_DELAY_S * (2 ** (failures - GRACE_FAILURES)))


def remaining_s(key: Key) -> Optional[float]:
    """Seconds left in this key's backoff, or None when an attempt may go now."""
    with _LOCK:
        st = _STREAKS.get(key)
        if st is None:
            return None
        left = st.next_attempt_at - _clock()
        return left if left > 0 else None


def record_failure(key: Key, reason: str) -> Tuple[int, float, bool]:
    """Record one failed placement. Returns ``(failures, delay_s, flag_now)``.

    ``flag_now`` is True only the first time the streak reaches
    ``GRACE_FAILURES`` -- the single red flag for this streak.
    """
    now = _clock()
    with _LOCK:
        st = _STREAKS.setdefault(key, _Streak(first_failure_at=now))
        st.failures += 1
        st.last_reason = str(reason)[:300]
        delay = delay_after(st.failures)
        st.next_attempt_at = now + delay
        flag_now = st.failures >= GRACE_FAILURES and not st.flagged
        if flag_now:
            st.flagged = True
        return st.failures, delay, flag_now


def failures(key: Key) -> int:
    with _LOCK:
        st = _STREAKS.get(key)
        return st.failures if st else 0


def clear(key: Key) -> None:
    with _LOCK:
        _STREAKS.pop(key, None)


def reset_all() -> None:
    """Tests only."""
    with _LOCK:
        _STREAKS.clear()


def snapshot() -> Dict[str, dict]:
    """Read-only view for diagnostics."""
    now = _clock()
    with _LOCK:
        return {
            "|".join(k): {
                "failures": st.failures,
                "retry_in_s": max(0.0, round(st.next_attempt_at - now, 1)),
                "flagged": st.flagged,
                "last_reason": st.last_reason,
            }
            for k, st in _STREAKS.items()
        }
