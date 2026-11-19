"""`--side-filter` on backtest_ict_scalp.py (PI-20261119-OFUCR5NF-0003).

RQ-20261118-abab-26 (ict_scalp_avax_5m DIRECTION arms) died at argparse: exit_lever_ablation passes `--side-filter long` and this harness had no
such flag (7 queued units blocked). Locked here: (1) the default is BYTE-IDENTICAL to the harness before the change, against a golden generated
from the untouched origin/main script on a COMMITTED candle file (the 15m MGC window of RQ-20261018-ef5d-02), (2) an explicit `both` equals it,
(3) long / short keep only that direction and DO remove trades (a flag that is accepted but ignored would pass a parse-only test), (4) the gate is
the live shared `_side_filter_suppresses`, imported not copied (patching it changes the harness), (5) bad values are refused.
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
    """`h.main()` ASSIGNS the module-level cost globals (venue-aware slippage + funding) and nothing restores them, so any
    test that calls main() earlier in the same pytest process leaks them in (tests/test_backtest_ict_scalp_tp_override.py
    does: net_total_r -14.7793 -> -17.1766 with identical trades and gross R; PR #27149 pytest-run, 2026-11-19). The golden
    is the in-process default run_backtest documents ("run_backtest never touches these"), so pin exactly that."""
    from src.runtime import execution_costs as ec
    monkeypatch.setattr(h, "FEE_BPS_ROUNDTRIP", ec.DEFAULT_FEE_BPS_ROUNDTRIP)
    monkeypatch.setattr(h, "SLIPPAGE_BPS_ROUNDTRIP", 0.0)
    monkeypatch.setattr(h, "FUNDING_BPS_PER_WINDOW", 0.0)
    monkeypatch.setattr(h, "FUNDING_WINDOW_HOURS", ec.FUNDING_WINDOW_HOURS)
    monkeypatch.setattr(h, "CONTRACT_COST", None)


def _run(**extra):
    df = pd.read_csv(REPO / GOLD["source_csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    res = h.run_backtest(df, cfg_overrides=GOLD["cfg_overrides"], _collect_trades=True, return_trades=True, **GOLD["kwargs"], **extra)
    rows = [[str(t.entry_time), t.direction, round(float(t.entry), 6), round(float(t.sl), 6), str(t.exit_time), t.outcome,
             round(float(t.r_multiple), 6)] for t in res["_trades_full"]]
    return res, rows


def test_default_is_byte_identical_to_the_golden():
    res, rows = _run()
    assert rows == GOLD["trades"], "the default output moved: the flag must not change anything when absent"
    for k, v in GOLD["summary"].items():
        assert res[k] == v


def test_explicit_both_equals_the_golden():
    res, rows = _run(side_filter="both")
    assert rows == GOLD["trades"]


def test_long_and_short_keep_only_their_side_and_remove_trades():
    base = len(GOLD["trades"])
    assert {r[1] for r in GOLD["trades"]} == {"long", "short"}, "the golden must hold both sides or the test proves nothing"
    for side in ("long", "short"):
        _, rows = _run(side_filter=side)
        assert rows and {r[1] for r in rows} == {side}
        assert len(rows) < base


def test_the_gate_is_the_live_shared_function(monkeypatch):
    import src.runtime.strategy_signal_builders as sb
    monkeypatch.setattr(sb, "_side_filter_suppresses", lambda direction, side_filter: True)
    res, rows = _run(side_filter="long")
    assert rows == [] and res["total_trades"] == 0
    # and `both` never reaches it (default path has no gate and no import)
    monkeypatch.setattr(sb, "_side_filter_suppresses", lambda direction, side_filter: (_ for _ in ()).throw(AssertionError("called on both")))
    _, rows = _run(side_filter="both")
    assert rows == GOLD["trades"]


def test_live_gate_truth_table_matches_the_flag_semantics():
    from src.runtime.strategy_signal_builders import _side_filter_suppresses as f
    assert [f(d, s) for s in ("long", "short", "both") for d in ("long", "short")] == [False, True, True, False, False, False]


def test_parser_accepts_the_flag_with_a_both_default_and_refuses_junk():
    p = h.build_parser()
    ns = p.parse_args(["--data", "x.csv", "--symbol", "MGC", "--timeframe", "15m"])
    assert ns.side_filter == "both"
    assert p.parse_args(["--data", "x.csv", "--symbol", "MGC", "--timeframe", "15m", "--side-filter", "long"]).side_filter == "long"
    with pytest.raises(SystemExit):
        p.parse_args(["--data", "x.csv", "--symbol", "MGC", "--timeframe", "15m", "--side-filter", "sideways"])


def test_run_backtest_refuses_a_bad_value():
    with pytest.raises(ValueError):
        _run(side_filter="sideways")
