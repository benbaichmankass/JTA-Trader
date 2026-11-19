"""ict_scalp_sol_5m session lever: the LIVE session filter drops exactly the bars the HARNESS --skip-hours skipped.

Proposal PR for the S_ASIA arm of RQ-20261118-abab-33 (confirmed by RQ-20261119-8260-01): the harness arm is
``--skip-hours=0,1,2,3,4,5,6,7``; the live producer (src/units/strategies/ict_scalp.py) has no skip_hours but has
``session_filter_enabled`` / ``session_start_hour`` / ``session_end_hour`` (signal only if the last bar's UTC hour is in
[start, end)). The declared leg is therefore ``enabled true, start 8, end 24``. These tests prove the two agree on all 24
UTC hours, including the end = 24 edge (hour 23 passes, hour 0 does not), on a tz-aware index, a tz-naive index and a
non-UTC-offset index, and that the real config block of ict_scalp_sol_5m carries exactly those three values and reaches
``order_package`` (the live builder spreads the YAML block into ``cfg``).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

import scripts.backtest_ict_scalp as h
from src.units.strategies.ict_scalp import _passes_session_filter, order_package

from tests.test_ict_scalp_5m import _bullish_scalp_frame

REPO = Path(__file__).resolve().parents[1]
SKIP = h._parse_skip_hours("0,1,2,3,4,5,6,7")          # the S_ASIA arm, exactly as the harness parses it
CFG = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["ict_scalp_sol_5m"]


def _frame_ending_at(hour: int, minute: int = 35, *, tz: str | None = "UTC") -> pd.DataFrame:
    end = pd.Timestamp(2026, 4, 2, hour, minute, tz=tz)
    idx = pd.date_range(end=end, periods=10, freq="5min")
    return pd.DataFrame({"close": range(10)}, index=idx)


def _harness_skips(df: pd.DataFrame) -> bool:
    """The harness predicate: skip the SIGNAL bar when its UTC hour is in the skip set (backtest_ict_scalp.py)."""
    return pd.Timestamp(df.index[-1]).hour in SKIP


def test_the_declared_leg_carries_exactly_the_s_asia_window():
    assert CFG["session_filter_enabled"] is True
    assert (CFG["session_start_hour"], CFG["session_end_hour"]) == (8, 24)


@pytest.mark.parametrize("minute", [0, 5, 35, 55])
@pytest.mark.parametrize("tz", ["UTC", None])
def test_live_filter_matches_the_harness_skip_set_on_all_24_hours(tz, minute):
    for hour in range(24):
        df = _frame_ending_at(hour, minute, tz=tz)
        live_passes = _passes_session_filter(
            df, enabled=CFG["session_filter_enabled"], start_hour=CFG["session_start_hour"], end_hour=CFG["session_end_hour"])
        assert live_passes is (not _harness_skips(df)), (hour, minute, tz)


def test_end_24_edge_hour_23_passes_and_hour_0_is_dropped():
    kw = dict(enabled=True, start_hour=8, end_hour=24)
    assert _passes_session_filter(_frame_ending_at(23, 55), **kw) is True
    assert _passes_session_filter(_frame_ending_at(0, 0), **kw) is False
    assert _passes_session_filter(_frame_ending_at(7, 55), **kw) is False
    assert _passes_session_filter(_frame_ending_at(8, 0), **kw) is True


def test_a_non_utc_index_is_judged_in_utc_like_the_harness():
    # 2026-04-02 09:35 in UTC+3 is 06:35 UTC -> dropped by both; 12:35 in UTC+3 is 09:35 UTC -> kept by both.
    for local_hour, expect_pass in ((9, False), (12, True)):
        df = _frame_ending_at(local_hour, 35, tz="Etc/GMT-3")
        utc_df = df.copy()
        utc_df.index = utc_df.index.tz_convert("UTC")
        live = _passes_session_filter(df, enabled=True, start_hour=8, end_hour=24)
        assert live is expect_pass
        assert live is (not _harness_skips(utc_df))


@pytest.mark.parametrize("shift_hours,expect_signal", [(0, False), (3, True), (17, True), (18, False)])
def test_order_package_with_the_real_config_block_blocks_exactly_the_skipped_bars(shift_hours, expect_signal):
    """_bullish_scalp_frame ends 06:35 UTC. +0h -> 06:35 (dropped), +3h -> 09:35 (kept), +17h -> 23:35 (edge, kept),
    +18h -> 00:35 (dropped)."""
    df = _bullish_scalp_frame()
    df.index = df.index + pd.Timedelta(hours=shift_hours)
    cfg = {"symbol": "SOLUSDT", **CFG}
    if expect_signal:
        assert order_package(cfg, candles_df=df)["direction"] == "long"
    else:
        with pytest.raises(ValueError, match="session window"):
            order_package(cfg, candles_df=df)
