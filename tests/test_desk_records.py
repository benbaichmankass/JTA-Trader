"""DESK-0-SCHEMA: the desk packet v3 / decision / touch validator."""
import copy
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cdr", REPO / "scripts/ci/check_desk_records.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
PS = json.loads(m.PACKET_SCHEMA.read_text())
DS = json.loads(m.DECISION_SCHEMA.read_text())


def test_self_test_passes():
    assert m._self_test() == 0


def test_committed_files_are_valid():
    assert m.findings() == []


def test_live_review_guard_still_green_on_main_rows():
    spec = importlib.util.spec_from_file_location("clrr", REPO / "scripts/ci/check_live_review_records.py")
    lr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lr)
    assert lr.findings() == []


def test_every_role_action_is_closed_and_has_no_size_or_halt():
    banned = {"size_up", "size_down", "resize", "widen_sl", "enter", "open", "halt", "set_mode", "set_execution"}
    for role, acts in DS["role_actions"].items():
        assert not banned & set(acts), role
    assert set(DS["role_actions"]) == set(DS["enums"]["role"]) == set(DS["role_packet_kinds"])


def test_kind_matrix_matches_the_design_table():
    assert set(m.BLOCKS_BY_KIND) == set(PS["enums"]["packet_kind"])
    assert "outcome" in m.BLOCKS_BY_KIND["exit"]
    assert all("outcome" not in b for k, b in m.BLOCKS_BY_KIND.items() if k != "exit")
    assert "state" not in m.BLOCKS_BY_KIND["entry"]
    assert "history" not in m.BLOCKS_BY_KIND["exit"]


def test_projection_nulls_unreadable_never_zero():
    p = copy.deepcopy(m.GOOD_PACKET)
    p["state"]["open_r"] = None
    f = m.project_features(p)
    assert f["open_r"] is None and f["atr_now_over_entry"] == 1.0
    e = m.project_features({"market": {"atr_now": None, "atr_entry": 2.0}})
    assert e["atr_now_over_entry"] is None and e["peak_r"] is None


def test_exit_packet_valid_and_outcome_is_t1():
    assert m.packet_problems(m.GOOD_EXIT_PACKET, PS) == []
    bad = copy.deepcopy(m.GOOD_EXIT_PACKET)
    bad["outcome"]["t1"] = False
    assert m.packet_problems(bad, PS)


def test_sandbox_account_is_bybit_1_and_touch_flag_is_checked():
    assert DS["sandbox_account"] == "bybit_1"
    t = copy.deepcopy(m.GOOD_TOUCH)
    t["sandbox"] = False
    assert m.touch_problems(t, DS, {m.GOOD_DECISION["decision_id"]: m.GOOD_DECISION})


def test_short_touch_must_fall():
    t = copy.deepcopy(m.GOOD_TOUCH)
    t.update(side="short", level_before=95.0, level_after=98.0)
    assert any("tighten-only" in x for x in m.touch_problems(t, DS, {m.GOOD_DECISION["decision_id"]: m.GOOD_DECISION}))
