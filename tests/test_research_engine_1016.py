"""RESEARCH-ENGINE-1016: the floor gap reaches brief §0, coverage + disposition checks self-test."""
import json
from pathlib import Path

from scripts.research import programme_coverage, queue_throughput as qt, result_disposition_check


def _rec(d: Path, name: str, floor: int, runnable_after: int) -> None:
    (d / f"{name}.json").write_text(json.dumps({"floor": floor, "throughput": {"runnable_after": runnable_after}}))


def test_floor_is_computed_in_one_place():
    assert qt.computed_floor(32) == 26 and qt.computed_floor(63) == 50 and qt.computed_floor(None) == 25
    from scripts.ci import check_research_queue_health as h
    assert h.computed_floor is qt.computed_floor


def test_floor_gap_counts_consecutive_below_floor_passes(tmp_path):
    d = tmp_path / qt.OPS_DIR
    d.mkdir(parents=True)
    _rec(d, "20301001T0300Z", 25, 30)       # met -> ends the streak
    _rec(d, "20301001T0900Z", 46, 23)
    _rec(d, "20301001T1500Z", 41, 18)
    _rec(d, "20301001T2100Z", 50, 9)
    g = qt.floor_gap({"fired_24h": 63, "runnable": 2}, tmp_path)
    assert g == {"floor": 50, "runnable": 2, "gap": 48, "below_floor_passes": 3, "ops_records_read": 4,
                 "since": "20301001T0900Z"}, g
    lines = qt.floor_gap_lines({"fired_24h": 63, "runnable": 2}, tmp_path)
    assert lines[0].startswith("### 🚨 RESEARCH FLOOR GAP — runnable 2 < floor 50 (gap 48); below floor") and "3 research-ops" in lines[0]


def test_no_gap_renders_nothing_and_unread_throughput_is_a_hole(tmp_path):
    assert qt.floor_gap_lines({"fired_24h": 10, "runnable": 30}, tmp_path) == []
    assert "COULD NOT BE READ" in qt.floor_gap_lines(None, tmp_path)[0]


def test_brief_section0_carries_the_floor_gap():
    from scripts.ops import render_daily_brief as r
    b = {"pipeline": {"section0Lines": ["## §0 — what came due"]}, "researchFloorLines": ["### 🚨 RESEARCH FLOOR GAP — x", ""]}
    assert "### 🚨 RESEARCH FLOOR GAP — x" in r._section0(b)


def test_self_tests():
    assert programme_coverage._self_test() == 0
    assert result_disposition_check._self_test() == 0
