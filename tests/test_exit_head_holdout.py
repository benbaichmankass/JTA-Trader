"""Tests for scripts/research/exit_head_holdout.py (RQ-20261104-e4a1-01): exit predicates and cost pricing."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ml"))

pytest.importorskip("pandas")
h = pytest.importorskip("exit_head_holdout")

STACK = {"fee_bps_roundtrip": 11.0, "slippage_bps_roundtrip": 3.0, "funding_bps_per_window": 1.0}


def _bars(marks, t0=1_600_000_000, mfe=None):
    out = []
    peak = 0.0
    for i, m in enumerate(marks):
        peak = max(peak, m)
        out.append({"bar_t": t0 + i * 14400, "age_bars": i, "open_r": m,
                    "mfe_r": peak if mfe is None else mfe[i], "giveback_r": peak - m})
    return out


def _emit(net_r=-1.08, gross_r=-1.0):
    return {"strategy": "trend_donchian", "symbol": "ETHUSDT", "entry_time": "2020-09-13 12:00:00+00:00",
            "exit_time": "2020-09-15 12:00:00+00:00", "entry": 100.0, "sl": 98.0, "direction": "long",
            "gross_r": gross_r, "net_r": net_r, "mfe_r": 0.6}


def test_arm_names_fixed_count():
    names = h.arm_names()
    assert len(names) == 19 and len(set(names)) == 19


def test_exit_index_tau_and_last_bar_rides():
    bars = _bars([0.1, 0.2, 0.3])
    assert h.exit_index("tau_0.2", bars, np.array([0.9, 0.1, 0.9])) == 1
    # firing only on the final bar is the declared exit, not a truncation
    assert h.exit_index("tau_0.2", bars, np.array([0.9, 0.9, 0.1])) is None
    assert h.exit_index("tau_0.2", bars, np.array([0.9, 0.9, 0.9])) is None


def test_exit_index_conditional_shape_and_hard_levers():
    bars = _bars([0.6] * 9 + [0.1] + [0.2])
    p = np.full(len(bars), 0.05)
    # age8_below_half_r needs age >= 8 AND open_r < 0.5 -> bar 9
    assert h.exit_index("age8_below_half_r_tau_0.1", bars, p) == 9
    stale = _bars([0.1] * 8 + [-0.1, -0.2, 0.0])
    assert h.exit_index("stale_8_0", stale, None) == 8
    gb = _bars([0.5, 1.2, 0.1, 0.3])
    assert h.exit_index("giveback_1_1", gb, None) == 2


def test_pricer_keeps_baseline_when_not_truncated_and_charges_cost_when_truncated():
    e = _emit()
    tk = "k"
    pr = h.Pricer({tk: e}, STACK, 14400)
    bars = _bars([0.5, 0.2, -0.9])
    keep = pr.net(tk, bars, None)
    assert keep["r"] == pytest.approx(-1.08) and keep["cut"] == 0
    cut = pr.net(tk, bars, 0)
    assert cut["cut"] == 1 and cut["bars"] == 1
    # truncated net = mark minus a positive cost (round trip + one slippage side)
    assert 0.5 - 0.2 < cut["r"] < 0.5
    assert pr.net(tk, None, None)["r"] == pytest.approx(-1.08)


def test_baseline_gap_matches_emitted_cost():
    e = _emit()
    pr = h.Pricer({}, STACK, 14400)
    xp = 100.0 + e["gross_r"] * 2.0
    c = h.ec.roundtrip_cost_r(entry=100.0, exit_price=xp, risk=2.0, entry_time=e["entry_time"],
                              exit_time=e["exit_time"], **STACK)
    e.update(cost_fee_r=c["fee_r"], cost_slippage_r=c["slippage_r"], cost_funding_r=c["funding_r"])
    assert pr.baseline_gap(e) < 1e-9


def test_summarize_drawdown_and_counts():
    s = h.summarize([{"r": 1.0, "mfe": 1.5, "bars": 2, "cut": 0}, {"r": -2.0, "mfe": 0.0, "bars": 2, "cut": 1},
                     {"r": 0.5, "mfe": 1.0, "bars": 2, "cut": 0}], 14400)
    assert s["n"] == 3 and s["net_r"] == pytest.approx(-0.5) and s["max_dd_r"] == pytest.approx(2.0)
    assert s["n_truncated"] == 1
