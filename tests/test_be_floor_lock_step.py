"""`be_floor_lock_r` — the profit-lock STEP on the pullback harness's break-even floor.

ADA-LIVE-EXIT-REVIEW-1024 (docs/research/ada-live-exit-review-2026-10-24.md):
ada_pullback_2h trails 5.0 x ATR against a 1.5 x ATR initial stop, i.e. 3.33 R
behind the extreme, so before its 4 R target the trail can lock at most 0.67 R.
The question "lock k R once the trade has seen m R" needs a floor ABOVE entry;
`--be-floor-r` alone only offers k = 0. This flag moves the armed floor to
entry + k R. Pinned here:
  * byte-identical when 0.0 (and when the floor itself is off);
  * echoed in params only when it does something;
  * it changes outcomes when armed, and never books a fired floor below k R.
"""
import importlib.util
import os
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


PULLBACK = _load("_belock_pullback", "scripts/backtest_pullback.py")
BASE = dict(trend_lookback=40, pullback_lookback=10, pullback_frac=0.5,
            atr_period=14, atr_stop_mult=1.5, trail_mult=5.0,
            timeout_bars=200, cooldown_bars=1, timeframe="5min", symbol="BTCUSDT")


def _candles(rule="5min"):
    df = pd.read_csv(os.path.join(_REPO, "data/backtest_candles.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return (df.set_index("timestamp").resample(rule, label="right", closed="right")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna().reset_index())


def test_lock_is_a_noop_at_default():
    df = _candles()
    plain = PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0)
    explicit = PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0, be_floor_lock_r=0.0)
    assert plain == explicit


def test_lock_is_inert_without_the_floor():
    df = _candles()
    assert PULLBACK.run_backtest(df.copy(), **BASE) == \
        PULLBACK.run_backtest(df.copy(), **BASE, be_floor_lock_r=0.5)


def test_lock_echoed_only_when_active():
    df = _candles()
    assert "be_floor_lock_r" not in PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0)["params"]
    s = PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0, be_floor_lock_r=0.5)
    assert s["params"]["be_floor_lock_r"] == 0.5


def test_lock_changes_outcomes_and_books_at_least_k_when_it_fires(tmp_path):
    import json
    df = _candles()
    pa, pb = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a = PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0, emit_path=str(pa))
    b = PULLBACK.run_backtest(df.copy(), **BASE, be_floor_r=1.0, be_floor_lock_r=0.5,
                              emit_path=str(pb))
    assert a != b, "the lock never fired on the fixture, so this proves nothing"
    rows = [json.loads(line) for line in pb.read_text().splitlines() if line.strip()]
    assert rows, "fixture must trade"
    # A trade that SAW >= 1.0 R and left on a stop must book >= +0.5 R gross
    # (this harness fills a stop at the stop price).
    fired = [r for r in rows if r["mfe_r"] >= 1.0 and r["exit_reason"] in ("stop", "trail_stop")]
    assert fired, "no trade armed the floor"
    for r in fired:
        assert r["gross_r"] >= 0.5 - 1e-3, r
