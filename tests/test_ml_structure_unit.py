"""ml_structure_unit: the structure arm re-scores the declared arm's decisions (entries fixed) and applies RULE-STRUCTURE-EXITS-V1.

Synthetic klines only (no network, no LightGBM): fake predictions pick the decisions, ``E.policy`` blocks positions, and the unit
re-scores the SAME (symbol, ts, side) with the structure bracket.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import ml_decision_entry as E  # noqa: E402
import ml_entry_levers as L  # noqa: E402
import ml_structure_unit as U  # noqa: E402


def _klines(seed: int, n: int = 2600) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n)),
                         "low": np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n)), "close": c, "volume": 1.0})


@pytest.fixture()
def world(tmp_path):
    cache = tmp_path / "klines"
    cache.mkdir()
    parts = []
    for k, sym in enumerate(("AAAUSDT", "BBBUSDT")):
        df = _klines(k + 1)
        df.to_pickle(cache / f"{sym}.pkl")
        g = E.regrid_hourly(df)
        lab = L.label_cell(g, E.SL_ATR, E.TP_ATR)
        lab["symbol"] = sym
        lab["ts"] = g["ts"].to_numpy()[lab["i"].to_numpy()]
        parts.append(lab)
    tab = pd.concat(parts, ignore_index=True).sort_values(["ts", "symbol"]).reset_index(drop=True)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    rng = np.random.default_rng(7)
    pl, ps = rng.uniform(0, 0.4, len(tab)), rng.uniform(0, 0.4, len(tab))
    return tab, cache, E.policy(tab, pl, ps, 0.10)


def test_the_structure_arm_rescoring_keeps_the_declared_decisions(world):
    tab, cache, trades = world
    assert len(trades) > 200
    lab = U.structure_labels(tab, cache, 5)
    out = U.rescore(trades, tab, lab)
    assert (out[["symbol", "ts", "side"]].to_numpy() == trades[["symbol", "ts", "side"]].to_numpy()).all()   # entries fixed
    r = out.iloc[0]
    row = tab[(tab.symbol == r.symbol) & (tab.ts == r.ts)].index[0]
    assert r.net_r == pytest.approx(lab[f"net_{r.side}"].to_numpy()[row])
    assert not np.allclose(out["net_r"].to_numpy(), trades["net_r"].to_numpy())      # and the exits really differ from the declared bracket


def test_random_exit_controls_are_seeded_and_have_one_mean_per_draw(world):
    tab, cache, trades = world
    c1 = U.random_exit_controls(trades, tab, cache, draws=20)
    c2 = U.random_exit_controls(trades, tab, cache, draws=20)
    assert c1.shape == (20,) and np.isfinite(c1).all() and np.array_equal(c1, c2)
    assert not np.array_equal(c1, U.random_exit_controls(trades, tab, cache, draws=20, seed=1))


def test_score_structure_runs_end_to_end_and_names_the_population(world):
    tab, cache, trades = world
    r = U.score_structure(trades, tab, cache, draws=30)
    assert r["verdict"] in ("PASS_BETTER", "PASS_NONINFERIOR", "FAIL", "INDETERMINATE")
    assert r["n"] == len(trades) and set(r["fallback_share"]) == set(U.PIVOTS)


def _frame(net, n=240):
    ts = pd.date_range("2024-01-01", periods=n, freq="6h", tz="UTC")
    return pd.DataFrame({"ts": ts, "symbol": "X", "net_r": net, "fallback": 0})


def test_the_rule_passes_a_clear_improvement_and_fails_a_worse_exit():
    rng = np.random.default_rng(0)
    base = rng.normal(0.0, 1.0, 240)
    a = _frame(base)
    ctrl = np.full(100, -0.05)
    better = {p: _frame(base + 0.5 + rng.normal(0, 0.05, 240)) for p in U.PIVOTS}
    assert U.judge_structure(a, better, ctrl)["verdict"] == "PASS_BETTER"
    worse = {p: _frame(base - 0.5) for p in U.PIVOTS}
    assert U.judge_structure(a, worse, ctrl)["verdict"] == "FAIL"


def test_indeterminate_when_s_never_differs_n_is_small_or_controls_missing():
    base = np.random.default_rng(1).normal(0, 1, 240)
    a = _frame(base)
    same = {p: _frame(base) for p in U.PIVOTS}
    assert U.judge_structure(a, same, np.full(100, -0.05))["verdict"] == "INDETERMINATE"
    assert U.judge_structure(_frame(base[:20], 20), {p: _frame(base[:20], 20) for p in U.PIVOTS}, np.full(5, 0.0))["verdict"] == "INDETERMINATE"
    assert U.judge_structure(a, {p: _frame(base + 1) for p in U.PIVOTS}, np.array([]))["verdict"] == "INDETERMINATE"


def test_a_win_that_does_not_beat_the_random_exit_controls_is_not_a_pass():
    # negative control for R4: the improvement is real but the controls are better still
    rng = np.random.default_rng(2)
    base = rng.normal(0.0, 1.0, 240)
    r = U.judge_structure(_frame(base), {p: _frame(base + 0.5) for p in U.PIVOTS}, np.full(100, 5.0))
    assert r["R4"] is False and r["verdict"] == "FAIL"
