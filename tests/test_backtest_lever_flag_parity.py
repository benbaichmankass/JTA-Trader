"""Lever-flag parity on the per-leg harnesses (PI-20261123-SME5WDGR-0008, units RQ-20261118-abab-05/06/07/10/11/12/14/15).

exit_lever_ablation passes these flags to a harness, and a harness that does not declare one dies at argparse (producer_failed). Contract per
flag and harness, the same shape as tests/test_backtest_squeeze_fvg_side_skip.py: (1) the default run is byte-identical to explicit-off (also
checked against origin/main when each flag landed, see the per-harness numbers below), (2) the flag DOES change the trade set (an accepted-but-
ignored flag would pass a parse-only test), (3) bad values are refused. The ATR-percentile vol gate is ONE shared rule (scripts/lever_gates.py)
whose semantics are locked here on a synthetic series.

Default-vs-origin/main on the golden fixture when the flags landed: fvg_range 23 trades, fade 223, squeeze 72, each with an identical summary and
identical emitted rows. Not built here (stated, not hidden): --be-floor-r / --stale-exit-bars / --trail-adx-below (held on the half-declared TA20 arm) and
turtle_soup (its live unit expresses neither lever and the system engine has no per-leg signal-filter hook).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.backtest_fade as fade
import scripts.backtest_fvg_range as fvg
import scripts.backtest_squeeze as sq
import scripts.lever_gates as lg

REPO = Path(__file__).resolve().parents[1]
GOLD = json.loads((REPO / "tests" / "data" / "ict_scalp_side_filter_golden.json").read_text())
FVG_KW = dict(range_lookback=48, atr_period=14, adx_period=14, adx_max=25.0, min_width_pct=0.002, max_width_pct=0.05,
              touch_tol_pct=0.002, min_touches=2, third_frac=0.33, fvg_search=6, min_fvg_size_bps=1.0, atr_stop_buffer=0.5,
              exit_style="mid", tp_r=2.0, timeout_bars=48, cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")
FADE_KW = dict(donchian=10, atr_period=14, atr_stop_buffer=0.5, pierce_min=0.0, exit_style="far", tp_r=1.0, trail_mult=3.0,
               timeout_bars=48, cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")
SQ_KW = dict(bb_period=20, bb_std=2.0, kc_mult=1.5, atr_period=14, atr_stop_mult=1.5, trail_mult=3.0, timeout_bars=48,
             cooldown_bars=1, timeframe="15m", symbol="BTCUSDT")
HARNESSES = {"fvg_range": (fvg, FVG_KW), "fade": (fade, FADE_KW), "squeeze": (sq, SQ_KW)}
VOL = list(HARNESSES)


@pytest.fixture(autouse=True)
def _pin_costs(monkeypatch):
    # fade reads module-level cost knobs that main() normally sets; pin them so the direct call is deterministic (same as the sibling tests).
    from src.runtime import execution_costs as ec
    for mod in (fade, fvg, sq):
        monkeypatch.setattr(mod, "FEE_BPS_ROUNDTRIP", ec.DEFAULT_FEE_BPS_ROUNDTRIP, raising=False)
        monkeypatch.setattr(mod, "SLIPPAGE_BPS_ROUNDTRIP", 0.0, raising=False)
        monkeypatch.setattr(mod, "FUNDING_BPS_PER_WINDOW", 0.0, raising=False)
        monkeypatch.setattr(mod, "FUNDING_WINDOW_HOURS", ec.FUNDING_WINDOW_HOURS, raising=False)


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


# ---- the shared rule ---------------------------------------------------------------------------------------------------------------------

def test_gate_is_off_by_default_and_never_skips_an_undefined_percentile():
    s = pd.Series([np.nan, 0.05, 0.5, 0.95])
    assert not lg.gate_armed(0.0, 0.0)
    assert lg.skips(None, 0, 0.9, 0.2) is False                       # gate off: no series at all
    assert lg.skips(s, 0, 0.9, 0.2) is False                          # NaN never skips (fail-permissive)
    assert lg.skips(s, 1, 0.9, 0.2) is True                           # dead tail (below)
    assert lg.skips(s, 2, 0.9, 0.2) is False                          # inside the band
    assert lg.skips(s, 3, 0.9, 0.2) is True                           # hot tail (above)
    assert lg.skips(s, 3, 0.0, 0.2) is False and lg.skips(s, 1, 0.9, 0.0) is False   # 0 = that side off


def test_pctl_series_is_the_trailing_rank_and_nan_until_the_window_fills():
    atr = pd.Series(np.arange(1.0, 11.0))
    p = lg.pctl_series(atr, 5)
    assert p.iloc[:4].isna().all() and p.iloc[4:].notna().all()
    assert (p.iloc[4:] == 1.0).all()                                  # strictly rising ATR: the newest bar always ranks top of its window


@pytest.mark.parametrize("above,below,window", [(-0.1, 0.0, 200), (1.5, 0.0, 200), (0.0, 0.0, 1), (0.2, 0.9, 200), (0.5, 0.5, 200)])
def test_bad_flag_sets_are_refused(above, below, window):
    assert lg.flag_errors(above, below, window)


# ---- per harness -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", VOL)
def test_vol_skip_defaults_equal_explicit_off(name, tmp_path):
    a, ra = _run(name, tmp_path, "a")
    b, rb = _run(name, tmp_path, "b", vol_skip_above_pctl=0.0, vol_skip_below_pctl=0.0, vol_pctl_window=200)
    assert a["total_trades"] > 15, "the fixture must produce trades or every other test is vacuous"
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert ra == rb


@pytest.mark.parametrize("name", VOL)
@pytest.mark.parametrize("kw", [dict(vol_skip_above_pctl=0.5), dict(vol_skip_below_pctl=0.5),
                                dict(vol_skip_above_pctl=0.9, vol_skip_below_pctl=0.2)])
def test_vol_skip_changes_the_trade_set(name, kw, tmp_path):
    base, rows0 = _run(name, tmp_path, "base")
    res, rows = _run(name, tmp_path, "vol", **kw)
    assert res["total_trades"] != base["total_trades"], "an accepted-but-ignored flag would leave the trade count unchanged"
    assert res["params"]["vol_skip_above_pctl"] == kw.get("vol_skip_above_pctl", 0.0)     # the arm is recorded in the result


@pytest.mark.parametrize("name", VOL)
def test_vol_skip_default_run_records_no_vol_params(name, tmp_path):
    res, _ = _run(name, tmp_path, "d")
    assert "vol_skip_above_pctl" not in res["params"]


@pytest.mark.parametrize("name", VOL)
@pytest.mark.parametrize("kw", [dict(vol_skip_above_pctl=1.5), dict(vol_skip_below_pctl=-0.2), dict(vol_pctl_window=1),
                                dict(vol_skip_above_pctl=0.2, vol_skip_below_pctl=0.9)])
def test_bad_vol_skip_values_are_refused(name, kw):
    mod, base = HARNESSES[name]
    with pytest.raises(ValueError):
        mod.run_backtest(_df(), **base, **kw)


# ---- ADX ceiling on squeeze (fade / fvg_range already had --adx-max) ----------------------------------------------------------------------

def test_adx_series_is_the_chop_family_definition():
    """lever_gates.adx_series must equal backtest_fade._adx and backtest_fvg_range._adx (backtest_trend's is a different ADX, deliberately not used)."""
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    df = pd.DataFrame({"open": c, "high": c * 1.003, "low": c * 0.997, "close": c})
    mine = lg.adx_series(df, 14).fillna(-1).to_numpy()
    assert np.allclose(mine, fade._adx(df, 14).fillna(-1).to_numpy())
    assert np.allclose(mine, fvg._adx(df, 14).fillna(-1).to_numpy())


def test_adx_blocks_semantics():
    s = pd.Series([np.nan, 10.0, 20.0, 30.0])
    assert lg.adx_blocks(None, 1, 20.0) is False and lg.adx_blocks(s, 1, None) is False     # gate off
    assert lg.adx_blocks(s, 0, 20.0) is True                                                 # undefined ADX is blocked (fail-closed, as fade/fvg)
    assert lg.adx_blocks(s, 1, 20.0) is False and lg.adx_blocks(s, 2, 20.0) is True and lg.adx_blocks(s, 3, 20.0) is True   # >= the cap blocks


def test_squeeze_adx_max_defaults_equal_off_and_changes_the_trade_set(tmp_path):
    a, ra = _run("squeeze", tmp_path, "a")
    b, rb = _run("squeeze", tmp_path, "b", adx_max=None, adx_period=14)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str) and ra == rb
    assert "adx_max" not in a["params"]
    res, _ = _run("squeeze", tmp_path, "adx", adx_max=20.0)
    assert res["total_trades"] < a["total_trades"] and res["params"]["adx_max"] == 20.0


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_squeeze_bad_adx_max_refused(bad):
    with pytest.raises(ValueError):
        sq.run_backtest(_df(), **SQ_KW, adx_max=bad)
