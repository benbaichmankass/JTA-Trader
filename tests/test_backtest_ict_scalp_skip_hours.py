"""`--skip-hours` on backtest_ict_scalp.py (PI-20261119-FILLW47B-0002).

The 7 ict_scalp SESSION units (RQ-20261118-abab-25/27/29/31/33/35/37) pass `--skip-hours` to a harness that had no such flag; abab-27 and abab-33
died at argparse (producer_failed). Locked here: (1) default / empty is BYTE-IDENTICAL to the harness before the change (the same golden the
--side-filter build uses, generated from the untouched script), (2) the gate acts on the SIGNAL bar's UTC hour (spy on order_package: it is never
called for a bar in the set, and is called for the others), (3) skipping all 24 hours leaves no trade, (4) malformed values are refused, at parse
time on the CLI and in run_backtest. Cost globals are pinned (main() used to leak them across tests; PR #27149 / #27175)."""
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
    rows = [[str(t.entry_time), t.direction, round(float(t.entry), 6), round(float(t.sl), 6), str(t.exit_time), t.outcome,
             round(float(t.r_multiple), 6)] for t in res["_trades_full"]]
    return res, rows


def test_default_and_empty_are_byte_identical_to_the_golden():
    for extra in ({}, {"skip_hours": ""}):
        res, rows = _run(**extra)
        assert rows == GOLD["trades"], "the default output moved: the flag must not change anything when absent"
        for k, v in GOLD["summary"].items():
            assert res[k] == v


def test_the_gate_acts_on_the_signal_bar_utc_hour(monkeypatch):
    seen = []
    real = h.order_package

    def spy(cfg, candles_df=None):
        seen.append(pd.Timestamp(candles_df["timestamp"].iloc[-1]).hour)
        return real(cfg, candles_df=candles_df)

    monkeypatch.setattr(h, "order_package", spy)
    _run()
    base_hours = set(seen)
    assert len(base_hours) > 12, "the golden window must span many hours or the test proves nothing"
    skip = {20, 21, 22, 23}
    seen.clear()
    _run(skip_hours="20,21,22,23")
    assert seen and not (set(seen) & skip), "order_package was called for a signal bar in the skip set"
    assert skip & base_hours, "the baseline must reach the skipped hours, or the gate was never exercised"
    assert set(seen) <= base_hours


def test_skipping_every_hour_leaves_no_trade():
    res, rows = _run(skip_hours=",".join(str(x) for x in range(24)))
    assert rows == [] and res["total_trades"] == 0


def test_a_partial_skip_changes_the_run():
    _, rows = _run(skip_hours="0,1,2,3,4,5,6,7")
    assert rows != GOLD["trades"]


@pytest.mark.parametrize("bad", ["24", "-1", "a", "1,x", "1.5"])
def test_malformed_values_are_refused(bad):
    with pytest.raises(ValueError):
        h._parse_skip_hours(bad)
    with pytest.raises(ValueError):
        _run(skip_hours=bad)


def test_parser_default_and_cli_refusal(capsys):
    p = h.build_parser()
    assert p.parse_args([]).skip_hours == ""
    assert p.parse_args(["--skip-hours", "20,21"]).skip_hours == "20,21"
    with pytest.raises(SystemExit) as e:
        p.parse_args(["--skip-hours", "25"])
    assert e.value.code == 2
    assert h._parse_skip_hours("") == set() and h._parse_skip_hours(" 3, 4 ,") == {3, 4}
