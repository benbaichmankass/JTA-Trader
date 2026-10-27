"""DESK-SHORT-HOLD-LANE: the 5-min block of the short-hold envelope (scripts/ops/short_hold_packet.py)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import short_hold_packet as shp  # noqa: E402

NOW = datetime(2026, 10, 27, 9, 6, 0, tzinfo=timezone.utc)


def bars(n=20, start=datetime(2026, 10, 27, 7, 30, tzinfo=timezone.utc)):
    return [{"time": int((start + timedelta(minutes=5 * i)).timestamp()),
             "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i} for i in range(n)]


def test_block_reads_the_last_closed_bar_and_open_r_from_the_initial_risk():
    pk = {"state": {"sl": 95.0}, "context": {"direction": "long"}}
    b = shp.five_min_block(pk, bars(), NOW, opened_at="2026-10-27T08:30:00Z", entry=110.0, risk_per_unit=5.0)
    assert b["read_state"] == "read" and b["bar"] == "2026-10-27T09:00:00Z" and b["bar_close"] == "2026-10-27T09:05:00Z"
    assert b["mark"] == 118.5 and b["open_r_at_mark"] == 1.7 and b["r_unit"] == "risk_per_unit"
    assert b["minutes_held"] == 36.0 and len(b["recent_bars"]) == shp.RECENT_BARS and b["atr"] is not None


def test_unread_candles_are_null_never_zero():
    b = shp.five_min_block({"state": {}, "context": {"direction": "short"}}, None, NOW, entry=110.0)
    assert b["read_state"] == "could_not_look" and b["mark"] is None and b["open_r_at_mark"] is None
