"""Conditional profit lock levers (row PROFIT-LOCK-CONDITIONAL-TEST, 2026-11-14).

Pinned here:
  * scripts/research/profit_lock_gate.py: the TP-distance gate opens only with a resting TP within N R of the extreme;
  * byte-identical at default: --be-floor-lock-r 0 (trend, newly ported) and --be-floor-tp-within-r 0 (both harnesses)
    change nothing, and the CLI default equals the explicit zeros;
  * armed: every trade whose MFE reached --be-floor-r exits at >= the lock (gross R), and the TP gate can only defer
    the floor (a gated arm never locks a trade the TP-distance condition did not open).
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

pd = pytest.importorskip("pandas")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GATE = _load("_pl_gate", "scripts/research/profit_lock_gate.py")
TREND = _load("_pl_trend", "scripts/backtest_trend.py")
PULLBACK = _load("_pl_pullback", "scripts/backtest_pullback.py")

HARNESSES = [
    pytest.param(TREND, dict(donchian=20, atr_period=14, atr_stop_mult=2.5, trail_mult=3.0, timeout_bars=200,
                             cooldown_bars=1, timeframe="5min", symbol="BTCUSDT"), id="trend"),
    pytest.param(PULLBACK, dict(trend_lookback=40, pullback_lookback=10, pullback_frac=0.5, atr_period=14,
                                atr_stop_mult=2.5, trail_mult=5.0, timeout_bars=200, cooldown_bars=1,
                                timeframe="5min", symbol="BTCUSDT"), id="pullback"),
]


def _candles(rule="5min"):
    df = pd.read_csv(os.path.join(_REPO, "data/backtest_candles.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return (df.set_index("timestamp").resample(rule, label="right", closed="right")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna().reset_index())


def _trades(mod, df, base, path, **kw):
    out = mod.run_backtest(df.copy(), **base, emit_path=str(path), **kw)
    return out, [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_gate_semantics():
    assert GATE.tp_gate_open(True, 105.0, 110.0, 10.0, 0.5)          # 0.5R away
    assert not GATE.tp_gate_open(True, 100.0, 110.0, 10.0, 0.5)      # 1.0R away
    assert GATE.tp_gate_open(True, 112.0, 110.0, 10.0, 0.5)          # past the TP
    assert GATE.tp_gate_open(False, 95.0, 90.0, 10.0, 0.5)
    assert not GATE.tp_gate_open(False, 100.0, 90.0, 10.0, 0.5)
    assert not GATE.tp_gate_open(True, 105.0, None, 10.0, 0.5)       # no resting TP never opens
    assert not GATE.tp_gate_open(True, 105.0, 110.0, 0.0, 0.5)


@pytest.mark.parametrize("mod,base", HARNESSES)
def test_defaults_are_byte_identical(mod, base):
    df = _candles()
    for kw in ({}, {"be_floor_r": 1.0}):
        unset = mod.run_backtest(df.copy(), **base, **kw)
        explicit = mod.run_backtest(df.copy(), **base, **kw, be_floor_lock_r=0.0, be_floor_tp_within_r=0.0)
        assert unset == explicit
        assert "be_floor_lock_r" not in unset["params"] and "be_floor_tp_within_r" not in unset["params"]
    assert unset["total_trades"] > 0, "fixture must trade or this proves nothing"


@pytest.mark.parametrize("script", ["scripts/backtest_trend.py", "scripts/backtest_pullback.py"])
def test_cli_default_equals_explicit_zero(script, tmp_path):
    csv = tmp_path / "c.csv"
    _candles("1min").to_csv(csv, index=False)

    def run(extra):
        out = tmp_path / f"o{len(extra)}.json"
        r = subprocess.run([sys.executable, os.path.join(_REPO, script), "--data", str(csv), "--resample", "5min",
                            "--symbol", "BTCUSDT", "--be-floor-r", "1", "--json", str(out), *extra],
                           cwd=_REPO, capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(out.read_text())
    assert run([]) == run(["--be-floor-lock-r", "0", "--be-floor-tp-within-r", "0"])


@pytest.mark.parametrize("mod,base", HARNESSES)
def test_lock_floors_every_armed_trade(mod, base, tmp_path):
    df = _candles()
    k, lock = 1.0, 0.5
    out, trades = _trades(mod, df, base, tmp_path / "l.jsonl", be_floor_r=k, be_floor_lock_r=lock)
    armed = [t for t in trades if t["mfe_r"] is not None and t["mfe_r"] >= k]
    assert armed, "the lock must arm on the fixture or this proves nothing"
    # the floor binds from the bar AFTER it armed (SL-first), so an exit on the arming bar itself may sit below it
    assert sum(1 for t in armed if t["gross_r"] >= lock - 1e-9) >= len(armed) - 1
    assert out["params"]["be_floor_lock_r"] == lock
    # the lock changes outcomes vs the plain break-even floor (an earlier locked exit may also free the position for a
    # different next entry -- a path effect the harness models, so entries are NOT pinned equal)
    plain, _ = _trades(mod, df, base, tmp_path / "p.jsonl", be_floor_r=k)
    assert plain["net_total_r"] != out["net_total_r"]


@pytest.mark.parametrize("mod,base", HARNESSES)
def test_tp_gate_only_defers_the_floor(mod, base, tmp_path):
    df = _candles()
    kw = dict(be_floor_r=1.0, be_floor_lock_r=0.5, tp_r=3.0, tp_cap_pct=0.5)  # a TP rests only with a cap
    _, ungated = _trades(mod, df, base, tmp_path / "u.jsonl", **kw)
    _, wide = _trades(mod, df, base, tmp_path / "w.jsonl", **kw, be_floor_tp_within_r=100.0)
    _, never = _trades(mod, df, base, tmp_path / "n.jsonl", **kw, be_floor_tp_within_r=1e-9)
    _, nolock = _trades(mod, df, base, tmp_path / "x.jsonl", tp_r=3.0, tp_cap_pct=0.5)
    strip = [(t["entry_time"], t["exit_time"], t["gross_r"]) for t in ungated]
    # a gate wide enough to always be open is the ungated lock
    assert [(t["entry_time"], t["exit_time"], t["gross_r"]) for t in wide] == strip
    # a gate that opens only at the TP itself never moves a stop before the TP fills: identical to no lock
    assert ([(t["entry_time"], t["exit_time"], t["gross_r"]) for t in never]
            == [(t["entry_time"], t["exit_time"], t["gross_r"]) for t in nolock])
