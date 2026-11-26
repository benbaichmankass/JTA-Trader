"""`--structure-exit pivot=N` on backtest_ict_scalp.py (row STRUCTURE-ARM-OTHER-HARNESSES; units RQ-20261101-5e01-14/-15 are blocked on it).

Locked here: (1) PARITY: absent and explicit "" are BYTE-IDENTICAL to the golden generated from the untouched script (arm A reproduces the committed
ict_scalp baseline), (2) the arm changes the trade set and the structure risk is the trade's R unit, (3) every trade is accounted: a signal with no confirmed
adverse swing keeps the declared bracket and is COUNTED, never dropped, (4) combining it with another TP mover or a malformed spec is refused,
(5) the stop only ratchets toward price (no exit of a long sits below its initial structure stop).
"""
from __future__ import annotations

import json
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


def test_default_and_explicit_empty_are_byte_identical_to_the_golden():
    for extra in ({}, {"structure_exit": ""}):
        res, rows, _ = _run(**extra)
        assert rows == GOLD["trades"], "the default output moved: the flag must not change anything when absent"
        for k, v in GOLD["summary"].items():
            assert res[k] == v
        assert "structure_exit" not in res


def test_the_arm_changes_the_trade_set_and_accounts_for_every_signal():
    _, base_rows, base = _run()
    res, rows, trades = _run(structure_exit="pivot=3")
    assert rows != base_rows, "an accepted-but-ignored flag would leave the trade set unchanged"
    sx = res["structure_exit"]
    assert sx["pivot"] == 3 and isinstance(sx["no_swing_fallbacks"], int)
    assert 0 <= sx["no_swing_fallbacks"] <= len(base) + 5      # counted, bounded
    structured = [t for t in trades if t.meta.get("tp_basis") == "structure_exit"]
    assert structured, "no trade used a structure bracket"
    for t in structured:
        assert t.risk == pytest.approx(abs(t.entry - t.sl))        # R is in the STRUCTURE risk unit
        assert t.meta["unit_tp"] is not None                         # the declared target is still recorded


def test_the_structure_stop_only_ratchets_toward_price():
    _, _, trades = _run(structure_exit="pivot=3")
    for t in trades:
        if t.meta.get("tp_basis") != "structure_exit" or t.outcome != "sl_hit":
            continue
        if t.direction == "long":
            assert t.exit_price >= t.sl - 1e-9          # a ratcheted stop is at or above the initial stop
        else:
            assert t.exit_price <= t.sl + 1e-9


def test_a_malformed_spec_and_a_second_tp_mover_are_refused():
    with pytest.raises(ValueError):
        _run(structure_exit="pivot=0")
    with pytest.raises(ValueError):
        _run(structure_exit="pivot=3", no_tp=True)
    with pytest.raises(ValueError):
        _run(structure_exit="pivot=3", tp_cap_pct=0.05)


def test_a_signal_with_no_confirmed_swing_keeps_the_declared_bracket_and_is_counted(monkeypatch):
    # force the no-swing path on every signal: the run must equal the declared baseline trade for trade, and every signal must be counted
    monkeypatch.setattr(h._StructureExit, "start", classmethod(lambda cls, *a, **k: None))
    res, rows, trades = _run(structure_exit="pivot=3")
    assert rows == GOLD["trades"]
    assert res["structure_exit"]["no_swing_fallbacks"] == len(trades) > 0
    assert all(t.meta.get("tp_basis") != "structure_exit" for t in trades)
