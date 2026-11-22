"""`--side-filter` and `--skip-hours` on backtest_squeeze.py and backtest_fvg_range.py (PI-20261119-FILLW47B-0003).

RQ-20261118-abab-45 / -46 (squeeze) and -18 / -19 (fvg_range) died at argparse: exit_lever_ablation passes these flags and neither harness
declared them. Same contract as tests/test_backtest_fade_side_skip.py, per harness: (1) explicit `both` / '' equal the default run (the default is
also byte-identical to origin/main, checked when the flags landed: 72 squeeze and 23 fvg_range trades on this fixture), (2) long / short keep only
that direction and DO remove trades (an accepted-but-ignored flag would pass a parse-only test), (3) skip-hours removes every trade whose signal bar
sits in the set, (4) bad values are refused.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.backtest_fvg_range as fvg
import scripts.backtest_squeeze as sq

REPO = Path(__file__).resolve().parents[1]
GOLD = json.loads((REPO / "tests" / "data" / "ict_scalp_side_filter_golden.json").read_text())
SQ_KW = dict(bb_period=20, bb_std=2.0, kc_mult=1.5, atr_period=14, atr_stop_mult=1.5, trail_mult=3.0, timeout_bars=48,
             cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")
FVG_KW = dict(range_lookback=48, atr_period=14, adx_period=14, adx_max=25.0, min_width_pct=0.002, max_width_pct=0.05,
              touch_tol_pct=0.002, min_touches=2, third_frac=0.33, fvg_search=6, min_fvg_size_bps=1.0, atr_stop_buffer=0.5,
              exit_style="mid", tp_r=2.0, timeout_bars=48, cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")
HARNESSES = {"squeeze": (sq, SQ_KW), "fvg_range": (fvg, FVG_KW)}


def _df():
    df = pd.read_csv(REPO / GOLD["source_csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _run(name, tmp_path, tag, **extra):
    mod, kw = HARNESSES[name]
    out = tmp_path / f"{name}_{tag}.jsonl"
    res = mod.run_backtest(_df(), emit_path=str(out), **kw, **extra)
    rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()] if out.exists() else []
    return res, rows


@pytest.mark.parametrize("name", list(HARNESSES))
def test_defaults_equal_explicit_off(name, tmp_path):
    a, ra = _run(name, tmp_path, "a")
    b, rb = _run(name, tmp_path, "b", side_filter="both", skip_hours="")
    assert a["total_trades"] > 15, "the fixture must produce trades or every other test is vacuous"
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert ra == rb


@pytest.mark.parametrize("name", list(HARNESSES))
def test_side_filter_keeps_only_that_side_and_removes_trades(name, tmp_path):
    base, _ = _run(name, tmp_path, "base")
    for side in ("long", "short"):
        res, rows = _run(name, tmp_path, side, side_filter=side)
        assert rows and {r["direction"] for r in rows} == {side}
        assert res["total_trades"] < base["total_trades"]


@pytest.mark.parametrize("name", list(HARNESSES))
def test_skip_hours_removes_trades_at_those_hours(name, tmp_path):
    base, rows0 = _run(name, tmp_path, "base")
    hours = sorted({pd.Timestamp(r["entry_time"]).hour for r in rows0})[:6]
    res, rows = _run(name, tmp_path, "skip", skip_hours=",".join(map(str, hours)))
    assert res["total_trades"] < base["total_trades"]
    assert all(pd.Timestamp(r["entry_time"]).hour not in hours for r in rows)


@pytest.mark.parametrize("name", list(HARNESSES))
@pytest.mark.parametrize("bad", ["25", "a", "-1"])
def test_bad_skip_hours_refused(name, bad):
    mod, kw = HARNESSES[name]
    with pytest.raises(ValueError):
        mod.run_backtest(_df(), **kw, skip_hours=bad)


@pytest.mark.parametrize("name", list(HARNESSES))
def test_bad_side_refused(name):
    mod, kw = HARNESSES[name]
    with pytest.raises(ValueError):
        mod.run_backtest(_df(), **kw, side_filter="up")
