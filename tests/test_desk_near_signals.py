"""DESK-16B-NEAR-SIGNALS: the near-signal producer (scripts/ops/desk_near_signals.py)."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dns", REPO / "scripts/ops/desk_near_signals.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_self_test_passes():
    assert m._self_test() == 0


def test_rostered_legs_skips_disabled_and_opted_out_and_dedupes():
    acc = {"a": {"strategies": ["x_trend_1d", "off_trend_1d"]}, "b": {"strategies": ["x_trend_1d"]},
           "c": {"configured": False, "strategies": ["y_trend_1d"]}, "d": {"strategies": []}}
    strat = {"x_trend_1d": {"symbols": ["AAA", "BBB"], "timeframe": "1d"}, "off_trend_1d": {"enabled": False, "symbols": ["CCC"]},
             "y_trend_1d": {"symbols": ["DDD"]}}
    rows = m.rostered_legs(acc, strat)
    assert [(r["leg"], r["symbol"]) for r in rows] == [("x_trend_1d", "AAA"), ("x_trend_1d", "BBB")]


def test_every_current_rostered_leg_resolves_to_a_unit():
    """The mapping is by name family; a new family must not silently become 'unlooked' for want of a rule."""
    dsp = m.dsp
    acc, strat = dsp._load_cfg()
    unresolved = [r["leg"] for r in m.rostered_legs(acc, strat) if m.unit_for(r["leg"]) is None]
    assert unresolved == []


def test_read_only_no_order_path():
    src = (REPO / "scripts/ops/desk_near_signals.py").read_text()
    for banned in ("place_order", "multi_account_execute", "log_signal", "signal_builder(", ".write_text", "open("):
        assert banned not in src


def test_unit_failure_is_unlooked_not_quiet():
    sec = m.dsp.TF_SECONDS["1d"]
    t0 = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    bars = [{"time": t0 + i * sec, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0} for i in range(200)]
    cut = datetime.fromtimestamp(t0 + 200 * sec, tz=timezone.utc)

    def boom(_unit):
        def op(cfg, candles_df=None):
            raise KeyError("x")
        return op

    row = {"leg": "z_trend_1d", "symbol": "Z", "timeframe": "1d", "cfg": {"enabled": True}}
    res = m.look_at_leg(row, bars, cut, resolve_unit=boom, side_filter=lambda c: "both")
    assert res["unlooked"] and "KeyError" in res["unlooked"] and res["items"] == []
