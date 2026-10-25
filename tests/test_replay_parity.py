"""Tests for scripts/ml/replay_parity.py (ML plan P0).

Positive control: a funding column the train builder fills but the live builder
never emits MUST come back ABSENT_LIVE; its un-planted twins (columns both sides
build) must come back OK — so a harness that flags everything cannot pass.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pandas")

import scripts.ml.replay_parity as R  # noqa: E402

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
N = 420


def _write_raw(d, n=N):
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    px = 100.0
    for i in range(n):
        px *= 1 + 0.004 * math.sin(i / 5.0) + 0.002 * math.cos(i / 2.3)
        o, c = px, px * (1 + 0.001 * math.sin(i))
        rows.append({"ts": (START + timedelta(hours=i)).isoformat(), "open": o,
                     "high": max(o, c) * 1.002, "low": min(o, c) * 0.998,
                     "close": c, "volume": 10.0, "source": "t"})
    (d / "data.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def _write_funding(d, n=N):
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"ts": (START + timedelta(hours=8 * k)).isoformat(), "symbol": "BTCUSDT",
             "funding_rate": 0.0001 * math.sin(k / 3.0) + 0.00005 * (k % 4)}
            for k in range(n // 8 + 2)]
    (d / "data.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


FEATS = ["vol_bucket", "rolling_log_return_vol", "log_return", "log_return_lag_1",
         "hour_of_day", "dayofweek", "funding_rate", "funding_rate_zscore",
         "funding_rate_abs_z"]


@pytest.fixture()
def report(tmp_path):
    _write_raw(tmp_path / "raw")
    _write_funding(tmp_path / "fund")
    return R.run_parity(
        market_raw=tmp_path / "raw", funding_oi=tmp_path / "fund", features=FEATS,
        categorical=["vol_bucket", "hour_of_day", "dayofweek"], symbol="BTCUSDT",
        timeframe="1h", vol_threshold=0.003, bars=250)


def test_planted_funding_gap_is_flagged(report):
    for f in ("funding_rate", "funding_rate_zscore", "funding_rate_abs_z"):
        r = report["features"][f]
        assert r["verdict"] in ("ABSENT_LIVE", "DEFAULT_LIVE"), (f, r)
        assert r["train_nondefault_pct"] > 90.0
        assert r["live_nondefault_pct"] == 0.0
    assert report["head_verdict"] in ("ABSENT_LIVE", "DEFAULT_LIVE")
    assert set(report["drifting_features"]) >= {"funding_rate", "funding_rate_zscore"}


def test_unplanted_twins_are_clean(report):
    assert report["paired_bars"] >= 200
    for f in ("rolling_log_return_vol", "log_return", "log_return_lag_1",
              "hour_of_day", "dayofweek", "vol_bucket"):
        r = report["features"][f]
        assert r["verdict"] == "OK", (f, r)
        assert r["live_present_pct"] == 100.0


def test_compare_detects_value_drift_and_absence():
    t = {str(i): {"a": 1.0, "b": 2.0, "c": "x"} for i in range(5)}
    live = {str(i): {"a": 1.0, "b": 2.5, "c": "y"} for i in range(5)}
    rep = R.compare_features(t, live, ["a", "b", "c", "d"], categorical=["c"])
    assert rep["features"]["a"]["verdict"] == "OK"
    assert rep["features"]["b"]["verdict"] == "DRIFT"
    assert rep["features"]["b"]["max_abs_diff"] == pytest.approx(0.5)
    assert rep["features"]["c"]["verdict"] == "DRIFT"
    assert rep["features"]["d"]["verdict"] == "NO_SIGNAL"  # default both sides
    assert rep["head_verdict"] == "DRIFT"


def test_no_pairs_is_not_ok():
    rep = R.compare_features({"1": {"a": 1.0}}, {"2": {"a": 1.0}}, ["a"])
    assert rep["features"]["a"]["verdict"] == "NO_PAIRS"
