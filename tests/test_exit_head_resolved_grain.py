"""The exit-head research drivers must replay at the LEG's timeframe, not the resolved file's grain.

WHY (ML-PRIMARY-13, 2026-11-19): ``backtest_data_source.resolve_or_refuse`` returns the finest grain <= the
requested timeframe plus a resample instruction. Four drivers dropped it, so on the trainer (no <SYM>_1h.csv;
ETH/SOL 5m, BTC 15m) RQ-20261119-a10d-07 replayed a 1h config on 5m bars (9,418 ETH harness trades where the
1h harness gives ~118 a year). ``load_resolved_frame`` is the one loader; these tests pin both halves.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]

DRIVERS = (
    "scripts/research/exit_head_label_bakeoff.py",
    "scripts/research/volcomp_exit_head_bakeoff.py",
    "scripts/research/exit_head_walkforward_multifold.py",
    "scripts/research/exit_head_eth_oos_control.py",
)


def _harness():
    """The drivers' own loader (scripts/ml/exit_head_replay._load_harness), so the test reads what they read."""
    import sys
    for p in (str(REPO), str(REPO / "scripts" / "ml")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from exit_head_replay import _load_harness
    return _load_harness()


def _write_5m(path: Path, hours: int = 48) -> None:
    ts = pd.date_range("2026-01-01", periods=hours * 12, freq="5min", tz="UTC")
    px = pd.Series(range(len(ts)), dtype=float) + 100.0
    pd.DataFrame({"timestamp": ts, "open": px, "high": px + 1, "low": px - 1, "close": px + 0.5,
                  "volume": 1.0}).to_csv(path, index=False)


def test_a_5m_file_resolved_for_1h_reaches_the_harness_as_hourly_bars(tmp_path):
    from scripts.ops import backtest_data_source as ds
    _write_5m(tmp_path / "ZZZUSDT_5m.csv")
    res = ds.resolve_or_refuse("ZZZUSDT", "1h", None, data_dir=tmp_path, env={})
    assert res.ok and res.path.endswith("ZZZUSDT_5m.csv")
    assert res.resample == "1h", "the resolver must say the 5m file needs resampling to the leg's 1h"
    h = _harness()
    raw = h._load_candles(res.path)
    df = ds.load_resolved_frame(h, res.path, res.resample)
    # POSITIVE CONTROL: the raw read is the 5m grain (the defect), the resolved frame is hourly.
    assert len(raw) == 48 * 12
    assert 47 <= len(df) <= 49, len(df)
    step = pd.to_datetime(df["timestamp"]).diff().dropna().unique()
    assert len(step) == 1 and pd.Timedelta(step[0]) == pd.Timedelta(hours=1)


def test_a_native_grain_file_is_returned_unchanged(tmp_path):
    from scripts.ops import backtest_data_source as ds
    h = _harness()
    _write_5m(tmp_path / "ZZZUSDT_5m.csv")
    p = str(tmp_path / "ZZZUSDT_5m.csv")
    assert ds.load_resolved_frame(h, p, None).equals(h._load_candles(p))


def test_every_exit_head_driver_loads_through_the_resolved_grain():
    for rel in DRIVERS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "load_resolved_frame(" in text, f"{rel} must load candles via backtest_data_source.load_resolved_frame"
        assert "harness._load_candles(res.path)" not in text and "harness._load_candles(path)" not in text, \
            f"{rel} still reads the resolved file at its native grain"
    assert os.path.exists(REPO / "scripts" / "ops" / "backtest_data_source.py")


def _bt_kwargs():
    return dict(donchian=20, atr_period=14, atr_stop_mult=2.5, trail_mult=5.0, timeout_bars=200, cooldown_bars=1,
                timeframe="1h", symbol="ZZZUSDT")


def test_run_backtest_refuses_a_frame_finer_than_its_timeframe(tmp_path):
    """Manager 2026-11-19: run_backtest called DIRECTLY on a finer file must refuse (it never resamples itself)."""
    import pytest
    h = _harness()
    _write_5m(tmp_path / "ZZZUSDT_5m.csv", hours=24 * 10)
    raw = h._load_candles(str(tmp_path / "ZZZUSDT_5m.csv"))
    with pytest.raises(ValueError, match="finer bars"):
        h.run_backtest(raw.copy(), **_bt_kwargs())
    # the same data at the declared grain runs
    from scripts.ops import backtest_data_source as ds
    ok = ds.load_resolved_frame(h, str(tmp_path / "ZZZUSDT_5m.csv"), "1h")
    h.run_backtest(ok.copy(), **_bt_kwargs())
    # the CLI path keeps its label semantics (opt-out), filed as PI-20261119-RIMARY13-0002
    h.run_backtest(raw.copy(), grain_check=False, **_bt_kwargs())
