"""HTF long gate (`--htf-long-sma-days`) in the pullback and trend harnesses (scripts/htf_daily_gate.py).

Row DEMO-FLOOR-ITER-20261113, manager GO 2026-11-14 07:15Z, after RQ-20261114-db1a-03's post-hoc PASS. Pinned here:
  * the gate reads the last COMPLETED UTC daily close (strictly before the bar's date) against the N-day SMA ending at it,
    and never gates without a full N-day history;
  * byte-identical at default: `htf_long_gate=None` == not passing it, and the CLI default (0) builds no gate;
  * when armed it removes longs only where the prior daily close is below the SMA, every surviving long sits at or
    above it, and it actually fires on the fixture;
  * the params echo carries the lever only when declared.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

pd = pytest.importorskip("pandas")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GATE = _load("_htf_gate", "scripts/htf_daily_gate.py")
TREND = _load("_htf_trend", "scripts/backtest_trend.py")
PULLBACK = _load("_htf_pullback", "scripts/backtest_pullback.py")

HARNESSES = [
    pytest.param(TREND, dict(donchian=20, atr_period=14, atr_stop_mult=2.5, trail_mult=3.0, timeout_bars=200,
                             cooldown_bars=1, timeframe="5min", symbol="BTCUSDT"), id="trend"),
    pytest.param(PULLBACK, dict(trend_lookback=40, pullback_lookback=10, pullback_frac=0.5, atr_period=14,
                                atr_stop_mult=2.5, trail_mult=5.0, timeout_bars=200, cooldown_bars=1,
                                timeframe="5min", symbol="BTCUSDT"), id="pullback"),
]
DAYS = 2  # the fixture spans ~3.5 UTC days of 1m bars, so a 2-day SMA has history from the third day


def _candles(rule="5min"):
    df = pd.read_csv(os.path.join(_REPO, "data/backtest_candles.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return (df.set_index("timestamp").resample(rule, label="right", closed="right")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna().reset_index())


def _hourly(closes_by_day):
    rows = []
    for d, c in closes_by_day:
        for h in range(24):
            ts = pd.Timestamp(f"{d} {h:02d}:00:00", tz="UTC")
            rows.append({"timestamp": ts, "open": c, "high": c, "low": c, "close": c})
    return pd.DataFrame(rows)


# --- the gate itself ------------------------------------------------------ #

def test_gate_off_when_days_not_positive():
    df = _hourly([("2024-01-01", 1.0)])
    assert GATE.build_gate(df, 0) is None and GATE.build_gate(df, -3) is None


def test_gate_reads_the_last_completed_day_against_its_sma():
    df = _hourly([("2024-01-01", 10.0), ("2024-01-02", 12.0), ("2024-01-03", 8.0), ("2024-01-04", 20.0)])
    g = GATE.build_gate(df, 2)
    # no full 2-day history before 2024-01-02's close -> unknown, never gated
    assert g.state("2024-01-01 05:00:00+00:00") == "unknown"
    assert g.state("2024-01-02 05:00:00+00:00") == "unknown"
    # on 01-03 the last completed day is 01-02: close 12 vs SMA(10,12)=11 -> above
    assert g.state("2024-01-03 23:00:00+00:00") == "above" and not g.skip("2024-01-03 23:00:00+00:00")
    # on 01-04 the last completed day is 01-03: close 8 vs SMA(12,8)=10 -> below (the 01-04 bar itself is not used)
    assert g.state("2024-01-04 00:00:00+00:00") == "below" and g.skip("2024-01-04 00:00:00+00:00")
    # a naive timestamp is read as UTC
    assert g.state(pd.Timestamp("2024-01-04 12:00:00")) == "below"


# --- byte-identical at default ------------------------------------------- #

@pytest.mark.parametrize("mod,base", HARNESSES)
def test_gate_none_is_a_noop(mod, base):
    df = _candles()
    unset = mod.run_backtest(df.copy(), **base)
    explicit = mod.run_backtest(df.copy(), **base, htf_long_gate=None)
    assert unset == explicit
    assert unset["total_trades"] > 0, "fixture must trade or this proves nothing"
    assert "htf_long_sma_days" not in unset["params"]


@pytest.mark.parametrize("script", ["scripts/backtest_trend.py", "scripts/backtest_pullback.py"])
def test_cli_default_equals_explicit_zero(script, tmp_path):
    csv = tmp_path / "c.csv"
    _candles("1min").to_csv(csv, index=False)

    def run(extra):
        out = tmp_path / f"o{len(extra)}.json"
        r = subprocess.run([sys.executable, os.path.join(_REPO, script), "--data", str(csv), "--resample", "5min",
                            "--symbol", "BTCUSDT", "--json", str(out), *extra],
                           cwd=_REPO, capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(out.read_text())
    assert run([]) == run(["--htf-long-sma-days", "0"])


# --- armed ---------------------------------------------------------------- #

@pytest.mark.parametrize("mod,base", HARNESSES)
def test_armed_gate_removes_only_below_sma_longs(mod, base, tmp_path):
    df = _candles()
    gate = GATE.build_gate(df, DAYS)
    p0, p1 = tmp_path / "off.jsonl", tmp_path / "on.jsonl"
    off = mod.run_backtest(df.copy(), **base, emit_path=str(p0))
    on = mod.run_backtest(df.copy(), **base, emit_path=str(p1), htf_long_gate=gate)
    t_off = [json.loads(x) for x in p0.read_text().splitlines() if x.strip()]
    t_on = [json.loads(x) for x in p1.read_text().splitlines() if x.strip()]
    longs_on = [t for t in t_on if t["direction"] == "long"]
    gated_off = [t for t in t_off if t["direction"] == "long" and gate.skip(t["entry_time"])]
    assert gated_off, "the gate must fire on the fixture or this proves nothing"
    assert all(not gate.skip(t["entry_time"]) for t in longs_on), "a surviving long sits below the SMA"
    assert len(longs_on) < len([t for t in t_off if t["direction"] == "long"])
    assert on["params"]["htf_long_sma_days"] == DAYS and "htf_long_sma_days" not in off["params"]
