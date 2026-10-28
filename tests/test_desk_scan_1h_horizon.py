"""DESK-1H-HORIZON-MISMATCH: the 1h scan must carry a row that prices a hold at the desk's 60-minute cap."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))

import desk_scan_packet as dsp  # noqa: E402

LIVE_HOLD_CAP_MIN = 60  # desk_write.SHORT_HOLD_MAX_MIN


def test_default_horizons_include_a_row_that_fits_the_live_hold_cap():
    fits = [
        h
        for h in dsp.DEFAULT_HORIZONS
        if h * dsp.TF_SECONDS["1h"] // 60 <= LIVE_HOLD_CAP_MIN
    ]
    assert fits == [1]


def test_a_built_1h_packet_carries_the_1_bar_rows_per_side():
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    bars = [
        {
            "time": t0 + 3600 * i,
            "open": 100 + i % 7,
            "high": 102 + i % 7,
            "low": 98 + i % 7,
            "close": 100 + (i * 3) % 11,
        }
        for i in range(400)
    ]
    cutoff = datetime.fromtimestamp(t0 + 3600 * 400, tz=timezone.utc)
    rows = dsp.base_rates("ETHUSDT", "1h", bars, dsp.DEFAULT_HORIZONS, 300)
    one = {r["side"] for r in rows if r["horizon_bars"] == 1}
    assert one == {"long", "short"} and cutoff
