"""`--side-filter` and `--skip-hours` on backtest_fade.py (PI-20261119-FILLW47B-0003).

RQ-20261118-abab-16 / -17 died at argparse (exit_lever_ablation passes these flags; the harness declared neither). Locked here: (1) explicit
`both` / '' equal the default run (the default is also byte-identical to origin/main, checked when the flags landed), (2) long / short keep
only that direction and DO remove trades (an accepted-but-ignored flag would pass a parse-only test), (3) skip-hours removes every trade whose
signal bar sits in the set, (4) bad values are refused.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.backtest_fade as h

REPO = Path(__file__).resolve().parents[1]
GOLD = json.loads((REPO / "tests" / "data" / "ict_scalp_side_filter_golden.json").read_text())
KW = dict(donchian=10, atr_period=14, atr_stop_buffer=0.5, pierce_min=0.0, exit_style="far", tp_r=1.0, trail_mult=3.0,
          timeout_bars=48, cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")


@pytest.fixture(autouse=True)
def _pin_costs(monkeypatch):
    from src.runtime import execution_costs as ec
    monkeypatch.setattr(h, "FEE_BPS_ROUNDTRIP", ec.DEFAULT_FEE_BPS_ROUNDTRIP)
    monkeypatch.setattr(h, "SLIPPAGE_BPS_ROUNDTRIP", 0.0)
    monkeypatch.setattr(h, "FUNDING_BPS_PER_WINDOW", 0.0)
    monkeypatch.setattr(h, "FUNDING_WINDOW_HOURS", ec.FUNDING_WINDOW_HOURS)


def _df():
    df = pd.read_csv(REPO / GOLD["source_csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _trades(tmp_path, name, **extra):
    out = tmp_path / f"{name}.jsonl"
    res = h.run_backtest(_df(), emit_path=str(out), **KW, **extra)
    rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()] if out.exists() else []
    return res, rows


def test_defaults_equal_explicit_off(tmp_path):
    a, ra = _trades(tmp_path, "a")
    b, rb = _trades(tmp_path, "b", side_filter="both", skip_hours="")
    assert a["total_trades"] > 20, "the fixture must produce trades or every other test is vacuous"
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert ra == rb


def test_side_filter_keeps_only_that_side_and_removes_trades(tmp_path):
    base, _ = _trades(tmp_path, "base")
    for side in ("long", "short"):
        res, rows = _trades(tmp_path, side, side_filter=side)
        assert rows and {r["direction"] for r in rows} == {side}
        assert res["total_trades"] < base["total_trades"]


def test_skip_hours_removes_trades_at_those_hours(tmp_path):
    base, rows0 = _trades(tmp_path, "base")
    hours = sorted({pd.Timestamp(r["entry_time"]).hour for r in rows0})[:6]
    res, rows = _trades(tmp_path, "skip", skip_hours=",".join(map(str, hours)))
    assert res["total_trades"] < base["total_trades"]
    assert all(pd.Timestamp(r["entry_time"]).hour not in hours for r in rows)


@pytest.mark.parametrize("bad", ["25", "a", "-1"])
def test_bad_skip_hours_refused(bad):
    with pytest.raises(ValueError):
        h.run_backtest(_df(), **KW, skip_hours=bad)


def test_bad_side_refused():
    with pytest.raises(ValueError):
        h.run_backtest(_df(), **KW, side_filter="up")
