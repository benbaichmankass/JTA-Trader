"""MOMENTUM-LEVERS-PARITY guard: the live exit path reproduces the harness, bar by bar.

Runs ``scripts/research/momentum_levers_parity.py`` over a seeded synthetic 4h series
with the one leg that declares a momentum lever (``trend_donchian_xrp_adx25``, ADX
trail 25/2.5) and with the momentum-stale cell (8 bars / ADX 20) set in-script. Both
sides see identical bars; the lever decisions, the exits and the stop path must agree.

The negative controls re-introduce the two live-path defects the parity check found
(the stale stop counting the forming bar; the trail ratcheting on the forming bar and
on the entry bar's pre-fill range) and assert the check SEES them -- a parity probe that
cannot report a divergence proves nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "research"))

import momentum_levers_parity as parity  # noqa: E402

LEG = "trend_donchian_xrp_adx25"


@pytest.fixture(scope="module")
def candles(tmp_path_factory) -> str:
    rng = np.random.default_rng(20261024)
    n = 4000
    # Regime-switching drift so breakouts, trends and chop (ADX both sides of 25) all
    # occur; down-weighted to give the short-only leg its entries, with occasional
    # shock bars so breakouts clear the leg's 0.80 depth floor.
    drift = np.repeat(rng.choice([-0.006, -0.003, 0.0, 0.003], size=n // 60 + 1), 60)[:n]
    shock = rng.choice([0.0, -0.05, 0.04], size=n, p=[0.96, 0.025, 0.015])
    ret = drift + shock + rng.normal(0.0, 0.012, n)
    close = 1.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])  # 24/7: open == previous close
    span = np.abs(rng.normal(0.0, 0.008, n)) * close
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span
    ts = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    p = tmp_path_factory.mktemp("parity") / "SYN_4h.csv"
    pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low,
                  "close": close, "volume": 1.0}).to_csv(p, index=False)
    return str(p)


def _run(candles, tmp_path, **kw):
    return parity.run(candles, LEG, "XRPUSDT", kw.pop("overrides", {}), tmp_dir=tmp_path, **kw)


def _assert_population(res):
    pop = res["population"]
    assert pop["n_trades"] >= 10, pop
    assert pop["n_managed_bars"] >= 100, pop
    assert pop["n_entries_reproduced_by_live_builder"] == pop["n_trades"]


def test_momentum_trail_leg_is_at_parity(candles, tmp_path):
    res = _run(candles, tmp_path, intrabar=True)
    _assert_population(res)
    # The lever must actually have fired, or a 1.0 match rate measures nothing.
    assert res["momentum_trail_fired_bars_harness"] > 0
    assert res["match_rate"]["momentum_trail_decision"] == 1.0
    assert res["match_rate"]["exit"] == 1.0
    assert res["verdict"] == "PARITY", res["divergences"][:3]


def test_momentum_stale_cell_is_at_parity(candles, tmp_path):
    res = _run(candles, tmp_path, intrabar=True,
               overrides={"momentum_stale_bars": 8, "momentum_stale_adx_below": 20})
    _assert_population(res)
    reasons = [t["harness_exit"]["reason"] for t in res["trades"]]
    assert "momentum_stale" in reasons, "the stale cell never fired: the check saw nothing"
    assert res["match_rate"]["momentum_stale_decision"] == 1.0
    assert res["match_rate"]["exit"] == 1.0
    assert res["verdict"] == "PARITY", res["divergences"][:3]


def test_probe_sees_a_stale_stop_counting_the_forming_bar(candles, tmp_path, monkeypatch):
    """NEGATIVE CONTROL: the pre-fix stale_stop (forming bar counted, intrabar price)."""
    from src.runtime import exit_levers

    monkeypatch.setattr(exit_levers, "closed_frame", lambda df, meta, cfg: df)
    res = _run(candles, tmp_path)
    assert res["verdict"].startswith("DIVERGES"), res["verdict"]
    assert res["match_rate"]["exit"] < 1.0


def test_trail_extreme_starts_at_the_fill_when_the_entry_bar_had_closed():
    """The entry bar's pre-fill range is not part of the since-entry extreme (harness
    ``ext = entry``); a package without the flag keeps the legacy window."""
    from src.units.strategies import trend_donchian

    ts = pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts.astype(str), "open": [10.0, 10.0, 10.5, 10.6],
                       "high": [10.2, 12.0, 10.8, 10.9], "low": [9.8, 9.0, 10.4, 10.5],
                       "close": [10.0, 10.5, 10.6, 10.7]})
    meta = {"entry_time": str(ts[1]), "timeframe": "4h", "entry_bar_closed": True}
    pkg = {"entry": 10.5, "meta": meta}
    w = trend_donchian._trail_window(meta, {}, df, pkg)
    assert float(w["high"].iloc[0]) == 10.5 and float(w["low"].iloc[0]) == 10.5
    assert float(w["high"].max()) == 10.9
    legacy = dict(meta, entry_bar_closed=False)
    w0 = trend_donchian._trail_window(legacy, {}, df, dict(pkg, meta=legacy))
    assert float(w0["high"].max()) == 12.0
