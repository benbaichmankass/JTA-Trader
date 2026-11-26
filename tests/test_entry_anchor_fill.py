"""LTR-FUNCTION-CORRECTNESS-AUDIT check 1 (2026-11-26): trails and the max-hold time stop anchor on the FILL.

Every candle strategy stamps meta.entry_time = the SIGNAL bar's OPEN; the fill (package created_at) comes after that bar
closes. The backtest (scripts/backtest_trend.py) starts the trail extreme at the entry price and walks only the bars
after the signal bar, so the live window must drop the signal bar too.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.runtime import exit_levers
from src.units.strategies.claude_desk import max_hold_verdict


def _frame():
    ts = pd.date_range(end="2026-11-26T16:00:00Z", periods=10, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.0, "volume": 1.0})


def _pkg(entry_time, created_at=None, **meta):
    m = {"entry_time": entry_time, "timeframe": "1h", **meta}
    return {"meta": m, **({"created_at": created_at} if created_at else {})}


def test_signal_bar_is_dropped_when_the_fill_comes_after_it():
    w = exit_levers.since_entry(_frame(), _pkg("2026-11-26T15:00:00+00:00", "2026-11-26T16:04:09+00:00"))
    assert [str(t) for t in w["timestamp"]] == ["2026-11-26 16:00:00+00:00"]   # the fill bar only; 15:00 signal bar gone


def test_without_created_at_the_old_anchor_is_unchanged():
    w = exit_levers.since_entry(_frame(), _pkg("2026-11-26T15:00:00+00:00"))
    assert len(w) == 2                                                          # 15:00 + 16:00, as before


def test_desk_anchor_is_unchanged_when_entry_time_is_the_fill():
    w = exit_levers.since_entry(_frame(), _pkg("2026-11-26T16:04:09+00:00", "2026-11-26T16:04:10+00:00"))
    assert len(w) == 1


def test_entry_anchor_picks_the_later_time():
    assert exit_levers.entry_anchor({"entry_time": "2026-11-26T15:00:00Z"}, {"created_at": "2026-11-26T16:04:09Z"}) \
        == "2026-11-26T16:04:09Z"
    assert exit_levers.entry_anchor({"entry_time": "2026-11-26T15:00:00Z"}, {}) == "2026-11-26T15:00:00Z"
    assert exit_levers.entry_anchor({}, {}) is None


def test_max_hold_counts_from_the_fill_not_the_decision_bar_open():
    pkg = _pkg("2026-11-26T15:00:00+00:00", "2026-11-26T16:04:09+00:00", max_hold_min=1440)
    fill = datetime(2026, 11, 26, 16, 4, 9, tzinfo=timezone.utc)
    assert max_hold_verdict(pkg, fill + timedelta(hours=23, minutes=30)) is None          # used to fire at 15:00 next day
    assert max_hold_verdict(pkg, fill + timedelta(hours=24, minutes=1))["reason"]
    assert max_hold_verdict(_pkg("2026-11-26T15:00:00+00:00", max_hold_min=1440),
                            datetime(2026, 11, 27, 15, 1, tzinfo=timezone.utc))["reason"]  # no created_at: unchanged
