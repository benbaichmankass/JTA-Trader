"""DESK-0-SCHEMA + DESK-0B-SCHEMA-V2: the desk packet v3 (schema v2) / decision / touch / outcome / consumed validator."""
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


def test_v2_entry_generation_replaces_the_veto_role():
    assert DS["schema_version"] == 2 and PS["schema_version"] == 2
    assert DS["role_actions"]["entry_generation"] == ["no_trade", "propose_entry", "watch_note"]
    assert "market_watch" not in DS["role_actions"]
    every = {a for acts in DS["role_actions"].values() for a in acts}
    assert not {"veto_candidate", "delay_candidate"} & every
    assert DS["role_packet_kinds"]["entry_generation"] == ["scan"]


def test_scan_kind_has_no_package_and_carries_the_books():
    assert {"universe", "system_book", "desk_book", "history"} <= m.BLOCKS_BY_KIND["scan"]
    assert not {"package", "market", "state", "outcome"} & m.BLOCKS_BY_KIND["scan"]
    assert m.packet_problems(m.GOOD_SCAN, PS) == []


def test_proposal_has_no_size_field_and_a_predictive_tp():
    props = DS["decisions"]["properties"]["proposal"]["properties"]
    assert not m.SIZE_KEYS & set(props)
    # every field required except max_hold_min (optional on old rows; required <= 60 on a live row by the guard)
    assert set(DS["decisions"]["properties"]["proposal"]["required"]) == set(props) - {"max_hold_min"}
    assert {"level", "basis", "p_hit"} == set(props["tp"]["required"])
    assert "trail" not in DS["enums"]["tp_basis"]


def test_stable_id_chain_fields_exist():
    d = DS["decisions"]["properties"]
    assert {"decision_id", "packet_id", "intent_id", "order_package_id"} <= set(d)
    assert "trade_id" in d["disposition"]["properties"]["per_account"]["items"]["properties"]
    assert {"outcome_id", "decision_id", "order_package_id", "trade_id"} <= set(DS["outcomes"]["properties"])


def test_training_marker_derivation():
    r = copy.deepcopy(m.GOOD_ENTRY_DECISION)
    assert m.expected_training(r) == (True, True, set())
    r["label_source"] = "synthetic"
    assert m.expected_training(r) == (False, False, {"synthetic"})
    r["label_source"], r["pre_cutoff"] = "historical_masked", True
    assert m.expected_training(r) == (True, False, {"historical_masked", "pre_cutoff"})


def test_committed_desk_files_include_outcomes_and_consumed():
    assert (REPO / "comms/desk/outcomes.jsonl").exists() and (REPO / "comms/desk/consumed.jsonl").exists()
