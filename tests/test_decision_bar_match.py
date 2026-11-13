"""RULE-RQ-20261022-4de5-01 — the decision-bar MATCH grade, on synthetic arms.

Pure-function tests: no candles, no network. The arms come from
forming_bar_pooled_regrade.leg_run and are not re-tested here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
_spec = importlib.util.spec_from_file_location(
    "decision_bar_match", REPO / "scripts" / "research" / "decision_bar_match.py")
dbm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbm)

LO, HI = "2020-01-01 00:00:00+00:00", "2026-01-01 00:00:00+00:00"


def _fold(d, n=10):
    return {"closed": {"n": n, "net_r": 0.0}, "forming": {"n": n, "net_r": 0.0}, "delta_r": d}


def _trades(net_by_year, *, per_year=24):
    import pandas as pd
    out = []
    for y, net in net_by_year.items():
        for k in range(per_year):
            t = pd.Timestamp(f"{y}-01-01", tz="UTC") + pd.Timedelta(days=15 * k + 1)
            out.append({"entry_time": str(t), "exit_time": str(t + pd.Timedelta(hours=6)),
                        "direction": "long", "net_r": net / per_year})
    return out


def test_floor_scales_with_trade_count_and_has_a_minimum():
    fs = dbm.fold_calls([_fold(1.0, n=10), _fold(1.9, n=100), _fold(2.0, n=100), _fold(-0.99, n=5)])
    assert [f["floor_r"] for f in fs] == [1.0, 2.0, 2.0, 1.0]
    assert [f["call"] for f in fs] == ["CLOSED", "TIE", "CLOSED", "TIE"]


def test_better_bar_needs_majority_and_few_opposite_and_sign():
    calls = dbm.fold_calls([_fold(d) for d in (2, 2, 2, 2, -2, 0)])
    assert dbm.better_bar(calls)["better"] == "CLOSED_BETTER"
    calls = dbm.fold_calls([_fold(d) for d in (2, 2, 2, 2, -2, -2)])
    assert dbm.better_bar(calls)["better"] == "NO_MATERIAL_DIFFERENCE"  # two opposite folds
    calls = dbm.fold_calls([_fold(d) for d in (-2, -2, -2, -2, 0.5, 0)])
    assert dbm.better_bar(calls)["better"] == "FORMING_BETTER"
    calls = dbm.fold_calls([_fold(d) for d in (2, 2, 2, 0.5, 0.5, -30)])
    assert dbm.better_bar(calls)["better"] == "NO_MATERIAL_DIFFERENCE"  # 3 of 6 only


def test_match_verdict_table():
    mv = dbm.match_verdict
    assert mv("CLOSED_BETTER", True, False)["verdict"] == "SWITCH_TO_CLOSED"
    assert mv("FORMING_BETTER", True, True)["verdict"] == "KEEP_FORMING_REBASE_RECORD"
    # tie -> closed preferred; closed fails D1, forming passes -> adopt forming
    r = mv("NO_MATERIAL_DIFFERENCE", False, True)
    assert (r["adopted"], r["verdict"]) == ("forming", "KEEP_FORMING_REBASE_RECORD")
    # materially better bar fails D1 -> the worse bar is never adopted
    assert mv("CLOSED_BETTER", False, True)["verdict"] == "DEMOTE_CANDIDATE"
    assert mv("NO_MATERIAL_DIFFERENCE", False, False)["verdict"] == "DEMOTE_CANDIDATE"
    assert mv("CLOSED_BETTER", None, True)["verdict"] == "INDETERMINATE"


def test_grade_leg_end_to_end_on_synthetic_arms():
    years = range(2020, 2026)
    closed = _trades({y: 10.0 for y in years})
    forming = _trades({y: 4.0 for y in years})
    rest = {"window": ["2025-01-01", "2025-12-31"],
            "proxy_closed": {"n": 24, "net_r": 10.0}, "proxy_forming": {"n": 24, "net_r": -1.0}}
    g = dbm.grade_leg(closed, forming, LO, HI, rest)
    assert g["better"] == "CLOSED_BETTER" and g["folds_closed"] == 6
    assert g["verdict"] == "SWITCH_TO_CLOSED"
    g = dbm.grade_leg(closed, forming, LO, HI, rest, incumbent="closed")
    assert g["verdict"] == "MATCHED_KEEP_CLOSED"
    g = dbm.grade_leg(closed, forming, LO, HI, None)
    assert g["verdict"] == "INDETERMINATE"


def test_harness_kwargs_unpacks_yaml_tp_revision_dict():
    """trend_donchian_eth_4h declares tp_revision as {rule, width_mult}; the trend harness
    takes the rule string + tp_revision_width_mult (passing the dict crashed the replay)."""
    import forming_bar_pooled_regrade as fbr
    block = {"timeframe": "4h", "symbols": ["ETHUSDT"], "donchian": 20,
             "tp_revision": {"rule": "donchian_measured_move", "width_mult": 0.5}}
    kw, unmodelled = fbr.harness_kwargs(block, "trend")
    assert kw["tp_revision"] == "donchian_measured_move"
    assert kw["tp_revision_width_mult"] == 0.5
    assert "tp_revision" not in unmodelled


# --- E5 fields (row FORMING-VS-CLOSED-ETH4H-SOL4H): derived from the grades, grading unchanged --------------------

def _res(better, verdict, nc=10, nf=12):
    return {"A_closed": {"n": nc, "net_r": 5.0}, "B_forming": {"n": nf, "net_r": 6.0},
            "grade": {"better": better, "verdict": verdict, "reason": "x", "window": ["a", "b"],
                      "folds_closed": 1, "folds_forming": 2, "folds_tie": 3, "delta_r_full": -1.0,
                      "rule_d1_record_window": {"closed": True, "forming": True, "window": ["c", "d"]}}}


def test_e5_fields_map_the_row_rule():
    import decision_bar_match as dbm
    e = dbm.e5_fields({"L": _res("NO_MATERIAL_DIFFERENCE", "SWITCH_TO_CLOSED"),
                       "M": _res("CLOSED_BETTER", "SWITCH_TO_CLOSED")}, partial=False)
    assert e["verdict"] == "pass" and e["read_state"] == "measured" and e["n"] == 44
    assert [r["verdict"] for r in e["records"]] == ["pass", "pass"]
    # a tie that the tool's own tie-break keeps on forming (closed fails D1) still maps to closed>=forming
    assert dbm.e5_fields({"L": _res("NO_MATERIAL_DIFFERENCE", "KEEP_FORMING_REBASE_RECORD")},
                         partial=False)["records"][0]["verdict"] == "pass"
    f = dbm.e5_fields({"L": _res("FORMING_BETTER", "KEEP_FORMING_REBASE_RECORD"),
                       "M": _res("NO_MATERIAL_DIFFERENCE", "SWITCH_TO_CLOSED")}, partial=False)
    assert f["verdict"] == "fail" and "L" in f["note"]


def test_e5_fields_never_claim_on_an_ungraded_or_partial_run():
    import decision_bar_match as dbm
    i = dbm.e5_fields({"L": _res(None, "INDETERMINATE"), "M": _res("NO_MATERIAL_DIFFERENCE", "SWITCH_TO_CLOSED")},
                      partial=False)
    assert i["verdict"] == "indeterminate" and i["records"][0]["n"] is None
    p = dbm.e5_fields({"M": _res("NO_MATERIAL_DIFFERENCE", "SWITCH_TO_CLOSED")}, partial=True)
    assert p["read_state"] == "producer_failed" and p["verdict"] == "not_applicable"
