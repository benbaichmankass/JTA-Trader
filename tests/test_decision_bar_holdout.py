"""RULE-RQ-20261018-2a10-01 — the closed-vs-forming decision-bar holdout grade, on synthetic arms.

Pure-function tests: no candles, no network. The arms themselves come from the Stage-0
harnesses (forming_bar_pooled_regrade.leg_run) and are not re-tested here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
_spec = importlib.util.spec_from_file_location(
    "decision_bar_holdout", REPO / "scripts" / "research" / "decision_bar_holdout.py")
dbh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbh)

LO, HI = "2020-01-01 00:00:00+00:00", "2024-01-01 00:00:00+00:00"


def _monthly(net_r, *, start_year=2020, years=4, per_month=3, exit_hours=6):
    """per_month trades per month (3 -> 144 over 4 years, so the 25% holdout holds >= 25), each worth net_r, each worth net_r (callable or float)."""
    import pandas as pd
    out = []
    for i, m in enumerate(pd.period_range(f"{start_year}-01", f"{start_year + years - 1}-12", freq="M")):
        for k in range(per_month):
            t = m.to_timestamp(how="start").tz_localize("UTC") + pd.Timedelta(days=2 * k + 1)
            r = net_r(i) if callable(net_r) else net_r
            out.append({"entry_time": str(t), "exit_time": str(t + pd.Timedelta(hours=exit_hours)),
                        "direction": "long", "net_r": r})
    return out


def test_calendar_edges_are_equal_and_cover_the_span():
    e = dbh.calendar_edges(LO, HI, 4)
    assert len(e) == 5 and str(e[0]).startswith("2020-01-01") and str(e[-1]).startswith("2024-01-01")
    assert e[1] - e[0] == e[2] - e[1] == e[3] - e[2]
    with pytest.raises(ValueError):
        dbh.calendar_edges(HI, LO, 4)


def test_closed_wins_when_selected_on_discovery_and_ahead_on_holdout():
    a = _monthly(0.6)        # closed: +0.6R every month
    b = _monthly(-0.2)       # forming: -0.2R every month
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["discovery"]["closed_selected"] is True
    assert g["discovery"]["folds_closed_ahead"] == 4
    assert g["holdout"]["delta_r"] > 0
    assert g["verdict"] == "CLOSED_WINS" and g["proposal"].startswith("decision_bar: closed")
    # the held-back span is the latest 25% grown until 25 closed entries: monthly trades -> >= 25 months
    assert g["boundary"]["closed_entries_in_holdout"] >= 25 and g["boundary"]["short_at_cap"] is False
    assert g["holdout"]["closed"]["n"] >= 25


def test_closed_not_replicated_when_holdout_reverses():
    # closed ahead in discovery (first 3 years) but behind in the last year
    a = _monthly(lambda i: 0.6 if i < 30 else -1.0)
    b = _monthly(lambda i: -0.2 if i < 30 else 0.5)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["discovery"]["closed_selected"] is True
    assert g["holdout"]["delta_r"] < 0
    assert g["verdict"] == "CLOSED_NOT_REPLICATED" and g["proposal"] is None


def test_forming_stands_and_is_flagged_when_ahead_on_both_spans():
    a = _monthly(-0.3)
    b = _monthly(0.4)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["discovery"]["closed_selected"] is False
    assert g["verdict"] == "FORMING_STANDS" and g["reason"] == "forming_ahead"
    assert g["forming_better_both_spans"] is True and g["proposal"] is None


def test_selection_needs_the_delta_floor_and_the_fold_majority():
    # closed ahead by 0.05R per trade: ~100 discovery trades -> dR ~5R is NOT reached at 0.04
    a = _monthly(0.09)
    b = _monthly(0.05)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["discovery"]["delta_r"] < 5.0 and g["discovery"]["closed_selected"] is False
    assert g["verdict"] == "FORMING_STANDS" and g["reason"] == "closed_not_robust"
    # ahead overall but concentrated in one fold -> fold majority fails
    a2 = _monthly(lambda i: 1.5 if i < 9 else -0.1)
    b2 = _monthly(0.0)
    g2 = dbh.grade_leg(a2, b2, LO, HI, incumbent="forming")
    assert g2["discovery"]["delta_r"] >= 5.0
    assert g2["discovery"]["folds_closed_ahead"] < 3 and g2["discovery"]["closed_selected"] is False


def test_indeterminate_when_discovery_is_thin():
    a = _monthly(0.6)[:10]
    b = _monthly(-0.2)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["verdict"] == "INDETERMINATE" and g["reason"] == "insufficient_discovery"
    assert g["proposal"] is None


def test_indeterminate_when_the_boundary_caps_short_of_the_holdout_floor():
    # dense closed trades in the first 2.4 years, then 1 every 6 months: at the 40% cap the
    # held-back span holds only a handful of closed entries -> underpowered, no change
    dense = [t for t in _monthly(0.6) if t["entry_time"] < "2022-06"]
    sparse = [t for i, t in enumerate(_monthly(0.6, per_month=1)) if t["entry_time"] >= "2022-06" and i % 6 == 0]
    a = dense + sparse
    b = _monthly(-0.2)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    assert g["boundary"]["short_at_cap"] is True
    assert g["verdict"] == "INDETERMINATE" and g["reason"] == "underpowered_holdout"


def test_closed_incumbent_never_proposes_a_revert():
    a, b = _monthly(-0.3), _monthly(0.4)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="closed")
    assert g["verdict"] == "RESEARCH_FLAG_FORMING_AHEAD" and g["proposal"] is None
    g2 = dbh.grade_leg(_monthly(0.6), _monthly(-0.2), LO, HI, incumbent="closed")
    assert g2["verdict"] == "KEEP_CLOSED" and g2["proposal"] is None
    # closed ahead on discovery but not across the fold majority: not a flag against closed
    g3 = dbh.grade_leg(_monthly(lambda i: 1.5 if i < 9 else -0.1), _monthly(0.0), LO, HI, incumbent="closed")
    assert g3["reason"] == "closed_not_robust" and g3["verdict"] == "KEEP_CLOSED_NOT_SELECTED"
    with pytest.raises(ValueError):
        dbh.grade_leg(a, b, LO, HI, incumbent="sideways")


def test_discovery_never_sees_the_held_back_span():
    import pandas as pd
    a, b = _monthly(0.6), _monthly(-0.2)
    g = dbh.grade_leg(a, b, LO, HI, incumbent="forming")
    boundary = pd.Timestamp(g["boundary"]["at"])
    disc_n = g["discovery"]["closed"]["n"] + g["discovery"]["forming"]["n"]
    hold_n = g["holdout"]["closed"]["n"] + g["holdout"]["forming"]["n"]
    assert disc_n + hold_n <= len(a) + len(b)
    assert all(pd.Timestamp(f["end"]) <= boundary for f in g["discovery"]["folds"])


def test_harness_kwargs_never_forward_the_live_decision_bar_keys():
    """trend_donchian_xrp_4h declares decision_bar: closed; the arms set decision_bar
    themselves, so the block's key must not reach run_backtest (it crashed the forming arm)."""
    import forming_bar_pooled_regrade as fbr
    block = {"enabled": True, "symbols": ["XRPUSDT"], "timeframe": "4h", "donchian": 20,
             "decision_bar": "closed", "decision_bar_fresh_seconds": 600, "atr_stop_mult": 2}
    kw, unmodelled = fbr.harness_kwargs(block, "trend")
    assert not any(k.startswith("decision_bar") for k in kw)
    assert not any(k.startswith("decision_bar") for k in unmodelled)
    assert kw["donchian"] == 20 and kw["atr_stop_mult"] == 2
