"""Row TREND-ALIGNMENT-FEATURE step 3: the live TREND-ALIGN-V1 copy is pinned EQUAL to the research labeller, the entry
meta helper labels on closed bars only, and a missing input stays null (observe-only, never a gate, never raises)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import trend_alignment as research  # noqa: E402
from src.runtime import trend_alignment as live  # noqa: E402


def _bars(n, drift, tf="1h", start="2024-01-01"):
    from datetime import timedelta
    d = {"1h": timedelta(hours=1), "1d": timedelta(days=1)}[tf]
    t0 = pd.Timestamp(start, tz="UTC")
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + drift + rng.normal(0, 0.002, n))
    df = pd.DataFrame({"open_time": [t0 + i * d for i in range(n)], "open": c, "high": c * 1.003, "low": c * 0.997, "close": c})
    df["close_time"] = df["open_time"] + d
    return df


def test_constants_match_research_and_detector():
    from src.runtime.regime import detector as det
    assert (live.TREND_MIN_ADX, live.MIN_BARS, live.ADX_PERIOD) == (research.TREND_MIN_ADX, research.MIN_BARS, research.ADX_PERIOD)
    assert live.TREND_MIN_ADX == det.TREND_MIN_ADX and live.MIN_BARS == det._MIN_BARS
    assert live.DEFINITION_ID == research.DEFINITION_ID == "TREND-ALIGN-V1"


def test_dmi_bit_for_bit_equal_to_research():
    up = _bars(200, 0.004)
    a, b = live.dmi(up), research.dmi(up)
    for col in ("adx", "pdi", "mdi"):
        assert np.allclose(a[col].values, b[col].values, equal_nan=True), col


def test_label_tf_equals_research_on_every_side():
    up = _bars(200, 0.004)
    for entry_i in (60, 120, 199):
        entry = up["close_time"].iloc[entry_i]
        for side in (1, -1):
            assert live.label_tf(up, entry, side) == research.label_tf(up, entry, side)


def test_meta_for_entry_labels_on_closed_bars_only():
    up = _bars(200, 0.004, tf="1h", start="2024-01-01")   # 200 1h bars end ~2024-01-09
    # a 1d frame that ENDS around the same time (as in production both frames end at "now"), so >= 30 daily
    # bars are closed before the 1h entry; strong up-trend.
    d1 = _bars(120, 0.02, tf="1d", start="2023-10-01")
    m = live.meta_for_entry(up[["open_time", "open", "high", "low", "close"]].rename(columns={"open_time": "timestamp"}),
                            d1[["open_time", "open", "high", "low", "close"]].rename(columns={"open_time": "timestamp"}),
                            "long", "1h")
    assert m["definition"] == "TREND-ALIGN-V1" and m["side"] == "long"
    assert m["LEG"]["label"] == "with_trend"
    assert m["D1"]["label"] in live.LABELS
    # the LEG label equals the research labeller on the same bars at the frame's last close
    lb = up.copy()
    entry = lb["close_time"].iloc[-1]
    assert m["LEG"] == research.label_tf(lb, entry, 1)


def test_missing_inputs_stay_null_never_raise():
    # no candles at all
    m = live.meta_for_entry(None, None, "long", "1h")
    assert m["LEG"]["label"] is None and m["D1"]["label"] is None and m["agreement"] == "other"
    # a 1d leg with no separate d1 frame reuses the leg frame
    d1 = _bars(120, 0.02, tf="1d")[["open_time", "open", "high", "low", "close"]].rename(columns={"open_time": "timestamp"})
    m = live.meta_for_entry(d1, None, "long", "1d")
    assert m["LEG"]["label"] in live.LABELS
    # an unknown direction -> no side, null labels, no raise
    m = live.meta_for_entry(_bars(60, 0.004).rename(columns={"open_time": "timestamp"}), None, "sideways", "1h")
    assert m["side"] is None and m["LEG"]["missing_reason"] == "no_side"
