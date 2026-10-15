"""NETTED-SLICES: allocation scoring and budget sizing (src/runtime/slice_allocation.py)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.runtime import slice_allocation as sa

REPO = Path(__file__).resolve().parents[1]


def test_pinned_defaults_equal_the_yaml():
    raw = yaml.safe_load((REPO / "config" / "slice_allocation.yaml").read_text())
    assert raw["weights"] == sa._DEFAULT_CONFIG["weights"]
    assert raw["live_window_trades"] == sa._DEFAULT_CONFIG["live_window_trades"]
    assert raw["symbol_budget_trades"] == sa._DEFAULT_CONFIG["symbol_budget_trades"]


def test_account_uses_slices():
    assert sa.account_uses_slices({"position_model": "slices"})
    assert sa.account_uses_slices({"position_model": "SLICES "})
    assert not sa.account_uses_slices({})
    assert not sa.account_uses_slices(None)


def test_weights_follow_score_and_never_the_name():
    w, basis = sa.allocation_weights({"zzz_b": 0.6, "aaa_a": 0.2})
    assert basis == "score"
    assert w["zzz_b"] == pytest.approx(0.75) and w["aaa_a"] == pytest.approx(0.25)
    # Renaming the contenders cannot move a share.
    w2, _ = sa.allocation_weights({"aaa_a": 0.6, "zzz_b": 0.2})
    assert w2["aaa_a"] == pytest.approx(0.75)
    eq, _ = sa.allocation_weights({"x": 0.5, "y": 0.5})
    assert eq == {"x": 0.5, "y": 0.5}


def test_equal_split_is_a_labelled_last_resort():
    w, basis = sa.allocation_weights({"x": 0.0, "y": float("nan")})
    assert basis == "equal_split_last_resort"
    assert w == {"x": 0.5, "y": 0.5}
    assert sa.allocation_weights({}) == ({}, "no_contenders")


def test_slice_qty_never_exceeds_riskmanager_size_and_splits_the_budget():
    # one-trade risk = 2 * 5 = 10; budget 1.0 trade, nothing held
    a = sa.slice_qty(sized_qty=2.0, entry=100, sl=95, weight=0.75, budget_trades=1.0, held_risk=0)
    b = sa.slice_qty(sized_qty=2.0, entry=100, sl=95, weight=0.25, budget_trades=1.0, held_risk=0)
    assert a["qty"] == pytest.approx(1.5) and b["qty"] == pytest.approx(0.5)
    assert a["qty"] + b["qty"] == pytest.approx(2.0)  # == the old single trade
    # a budget of 3 trades still caps each slice at the RiskManager size
    big = sa.slice_qty(sized_qty=2.0, entry=100, sl=95, weight=1.0, budget_trades=3.0, held_risk=0)
    assert big["qty"] == pytest.approx(2.0)


def test_slice_qty_counts_other_strategies_held_risk():
    half = sa.slice_qty(sized_qty=2.0, entry=100, sl=95, weight=1.0, budget_trades=1.0, held_risk=5.0)
    assert half["qty"] == pytest.approx(1.0)
    none = sa.slice_qty(sized_qty=2.0, entry=100, sl=95, weight=1.0, budget_trades=1.0, held_risk=10.0)
    assert none["qty"] == 0.0 and none["reason"] == "budget_exhausted"


def test_backtest_term_reads_only_measured_records(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(
        {"coverage_state": "measured", "expectancy_r_oos": 0.2}))
    (tmp_path / "bad.json").write_text(json.dumps(
        {"coverage_state": "measured", "expectancy_r_oos": -0.9}))
    (tmp_path / "nh.json").write_text(json.dumps(
        {"coverage_state": "no_harness", "expectancy_r_oos": 5}))
    assert sa.backtest_term("good", evidence_dir=tmp_path) == (pytest.approx(0.7), "measured")
    assert sa.backtest_term("bad", evidence_dir=tmp_path)[0] == 0.0
    assert sa.backtest_term("nh", evidence_dir=tmp_path) == (0.5, "coverage_no_harness")
    assert sa.backtest_term("absent", evidence_dir=tmp_path) == (0.5, "no_record")


def test_live_term_is_laplace_smoothed_and_neutral_without_trades():
    assert sa.live_term("x", {}) == (0.5, "no_trades")
    assert sa.live_term("x", {"x": (3, 4)})[0] == pytest.approx(4 / 6)


def test_regime_term_rewards_only_an_explicit_on_cell():
    pol = {"trending": {"s": {"long": True, "short": False}}}
    on = SimpleNamespace(strategy="s", side="long", regime="trending")
    unlisted = SimpleNamespace(strategy="t", side="long", regime="trending")
    assert sa.regime_term(on, pol) == (1.0, "explicit_on")
    assert sa.regime_term(unlisted, pol)[0] == 0.5


def test_score_candidate_combines_weighted_terms(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps(
        {"coverage_state": "measured", "expectancy_r_oos": 0.5}))
    cand = SimpleNamespace(strategy="s", side="long", regime="trending", confidence=1.0)
    out = sa.score_candidate(
        cand, config=sa._DEFAULT_CONFIG, live_counts={"s": (1, 0 + 1)},
        regime_policy={"trending": {"s": {"long": True}}}, evidence_dir=tmp_path,
    )
    # 0.4*1 + 0.3*1 + 0.2*(2/3) + 0.1*1 = 0.9333
    assert out["score"] == pytest.approx(0.4 + 0.3 + 0.2 * (2 / 3) + 0.1, abs=1e-6)
    assert set(out["terms"]) == {"confidence", "backtest", "live", "regime"}
