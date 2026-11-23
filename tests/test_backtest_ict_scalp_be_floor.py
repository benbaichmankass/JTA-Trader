"""`--be-floor-r` on backtest_ict_scalp.py (PI-20261123-SME5WDGR-0008; units RQ-20261118-abab-06 / -07 carry a BE1 arm that died at argparse).

The MI-165 break-even floor already existed on backtest_trend.py / backtest_squeeze.py / backtest_pullback.py; ict_scalp had only the --sim-breakeven ratchet
(arms on a bar CLOSE >= 1R, stop to entry +/- be_offset_bps). Locked here: (1) default and explicit 0 are BYTE-IDENTICAL to the golden generated from the
untouched script (the same golden the --side-filter / --skip-hours builds use), (2) a floor changes the trade set and does so as a floor: a trade that was
stopped out for a full loss after seeing >= the floor is now a scratch at entry (outcome be_stop, R exactly 0 before costs) and no exit sits below the entry
once the floor armed, (3) it is independent of --sim-breakeven (that ratchet still arms on its own rule), (4) a negative value is refused.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

import scripts.backtest_ict_scalp as h

REPO = Path(__file__).resolve().parents[1]
GOLD = json.loads((REPO / "tests" / "data" / "ict_scalp_side_filter_golden.json").read_text())


@pytest.fixture(autouse=True)
def _pin_module_cost_globals(monkeypatch):
    from src.runtime import execution_costs as ec
    monkeypatch.setattr(h, "FEE_BPS_ROUNDTRIP", ec.DEFAULT_FEE_BPS_ROUNDTRIP)
    monkeypatch.setattr(h, "SLIPPAGE_BPS_ROUNDTRIP", 0.0)
    monkeypatch.setattr(h, "FUNDING_BPS_PER_WINDOW", 0.0)
    monkeypatch.setattr(h, "FUNDING_WINDOW_HOURS", ec.FUNDING_WINDOW_HOURS)
    monkeypatch.setattr(h, "CONTRACT_COST", None)


def _df():
    df = pd.read_csv(REPO / GOLD["source_csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _run(**extra):
    res = h.run_backtest(_df(), cfg_overrides=GOLD["cfg_overrides"], _collect_trades=True, return_trades=True, **GOLD["kwargs"], **extra)
    trades = res["_trades_full"]
    rows = [[str(t.entry_time), t.direction, round(float(t.entry), 6), round(float(t.sl), 6), str(t.exit_time), t.outcome,
             round(float(t.r_multiple), 6)] for t in trades]
    return res, rows, trades


def test_default_and_explicit_zero_are_byte_identical_to_the_golden():
    for extra in ({}, {"be_floor_r": 0.0}):
        res, rows, _ = _run(**extra)
        assert rows == GOLD["trades"], "the default output moved: the flag must not change anything when absent"
        for k, v in GOLD["summary"].items():
            assert res[k] == v


def test_a_floor_turns_full_losses_into_scratches_at_entry():
    _, base_rows, base = _run()
    _, rows, trades = _run(be_floor_r=0.5)
    assert rows != base_rows, "an accepted-but-ignored flag would leave the trade set unchanged"
    kinds = Counter(t.outcome for t in trades)
    assert kinds["be_stop"] > 0 and kinds["sl_hit"] < Counter(t.outcome for t in base)["sl_hit"]
    scratches = [t for t in trades if t.outcome == "be_stop"]
    # without --sim-breakeven every be_stop is a floor stop-out, which exits AT the entry: gross R is exactly 0, never a loss
    assert all(abs(float(t.exit_price) - float(t.entry)) < 1e-9 and abs(float(t.r_multiple)) < 1e-9 for t in scratches)


def test_a_higher_floor_arms_less_often():
    _, _, t5 = _run(be_floor_r=0.5)
    _, _, t10 = _run(be_floor_r=1.0)
    assert Counter(t.outcome for t in t10)["be_stop"] < Counter(t.outcome for t in t5)["be_stop"]


def test_the_floor_is_a_different_lever_from_the_sim_breakeven_ratchet():
    """The ratchet arms on a bar CLOSE >= 1R; the floor on the intrabar extreme. Run alone they must not produce the same trades, and the floor must
    still act when the ratchet is on (it is not subsumed)."""
    _, rows_floor, _ = _run(be_floor_r=1.0)
    _, rows_ratchet, _ = _run(sim_breakeven=True)
    _, rows_both, _ = _run(be_floor_r=1.0, sim_breakeven=True)
    assert rows_floor != rows_ratchet
    assert rows_both != rows_ratchet


def test_negative_floor_is_refused():
    with pytest.raises(ValueError):
        _run(be_floor_r=-0.5)
