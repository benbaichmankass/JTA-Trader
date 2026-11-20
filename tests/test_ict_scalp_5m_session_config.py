"""ict_scalp_5m (BTCUSDT) session lever S_ASIA: the declared leg carries exactly the allowed window [8, 24) and it reaches order_package.

The filter itself, its frame shapes and its parity with the harness's --skip-hours are covered once, on the real live frame, in
tests/test_ict_scalp_sol_5m_session_parity.py; this file pins the BTC leg's own config block to the same window the registered
evidence (RQ-20261118-abab-25 and RQ-20261119-8260-02, arm S_ASIA = --skip-hours=0..7) measured.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

import scripts.backtest_ict_scalp as h
from src.units.strategies.ict_scalp import order_package

from tests.test_ict_scalp_5m import _bullish_scalp_frame

REPO = Path(__file__).resolve().parents[1]
SKIP = h._parse_skip_hours("0,1,2,3,4,5,6,7")
CFG = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["ict_scalp_5m"]


def _live_shape(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index.name = "timestamp"
    return out.reset_index()


def test_the_declared_btc_leg_carries_exactly_the_s_asia_window():
    assert CFG["session_filter_enabled"] is True
    assert (CFG["session_start_hour"], CFG["session_end_hour"]) == (8, 24)
    assert set(range(24)) - set(SKIP) == set(range(CFG["session_start_hour"], CFG["session_end_hour"]))


@pytest.mark.parametrize("shape", ["index", "column"])
@pytest.mark.parametrize("shift_hours,expect_signal", [(0, False), (3, True), (17, True), (18, False)])
def test_order_package_with_the_btc_config_block_blocks_exactly_the_skipped_bars(shift_hours, expect_signal, shape):
    """_bullish_scalp_frame ends 06:35 UTC. +0h -> 06:35 (dropped), +3h -> 09:35 (kept), +17h -> 23:35 (edge, kept), +18h -> 00:35 (dropped)."""
    df = _bullish_scalp_frame()
    df.index = df.index + pd.Timedelta(hours=shift_hours)
    if shape == "column":
        df = _live_shape(df)
    cfg = {"symbol": "BTCUSDT", **CFG}
    if expect_signal:
        assert order_package(cfg, candles_df=df)["direction"] == "long"
    else:
        with pytest.raises(ValueError, match="session window"):
            order_package(cfg, candles_df=df)
