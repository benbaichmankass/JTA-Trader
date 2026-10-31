"""TRAIL-RATCHET-AUDIT: a trail candidate through the price closes; it never loosens or amends past price."""
import pandas as pd
import pytest

from src.runtime.trail_cross import trail_cross_verdict


def test_long_cross_closes():
    assert trail_cross_verdict("long", 105.0, 100.0, 104.0) == {
        "action": "close", "reason": "strategy_close", "exit_price": 104.0}


def test_long_candidate_at_price_closes():
    assert trail_cross_verdict("long", 104.0, 100.0, 104.0)["action"] == "close"


def test_short_cross_closes():
    assert trail_cross_verdict("short", 95.0, 100.0, 96.0)["action"] == "close"


@pytest.mark.parametrize("d,cand,sl,px", [
    ("long", 99.0, 100.0, 98.0),    # candidate does not tighten (looser than sl): never act
    ("short", 101.0, 100.0, 102.0),
    ("long", 103.0, 100.0, 110.0),  # tightens and is below price: ordinary amend, not a close
    ("short", 97.0, 100.0, 90.0),
    ("flat", 105.0, 100.0, 104.0),
])
def test_no_close_when_not_a_tightening_cross(d, cand, sl, px):
    assert trail_cross_verdict(d, cand, sl, px) is None


def test_bad_input_is_none():
    assert trail_cross_verdict("long", None, 100.0, 104.0) is None


def _frame(highs, lows, closes):
    n = len(closes)
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-02", periods=n, freq="4h", tz="UTC"),
                         "open": closes, "high": highs, "low": lows, "close": closes, "volume": [1.0] * n})


@pytest.mark.parametrize("mod", ["fade_breakout_4h", "squeeze_breakout_4h", "htf_pullback_trend_2h"])
def test_other_chandelier_monitors_close_on_cross(mod):
    import importlib
    m = importlib.import_module(f"src.units.strategies.{mod}")
    pkg = {"order_package_id": "p", "direction": "long", "entry": 110.0, "sl": 83.75, "tp": 1500.0,
           "meta": {"atr": 10.5, "trail_mult": 3.0, "atr_period": 14}}
    verdict = m.monitor({}, _frame([200, 130], [150, 118], [180, 120.0]), pkg)
    assert verdict and verdict.get("action") == "close" and verdict.get("reason") == "strategy_close", verdict
