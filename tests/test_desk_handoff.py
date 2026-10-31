"""DESK-HANDOFF-PROTOCOL: the hand-off chain for desk-opened positions (src/runtime/desk_handoff.py and its users)."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.runtime import desk_handoff as dh
from src.runtime import live_review_due as lrd

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DESK_ROW = {"decision_id": "DD-20261031T0400Z-scan-1h-1", "judged_at": "2026-10-31T04:02:00Z",
            "proposal": {"symbol": "BTCUSDT", "side": "long", "timeframe": "1h", "entry": {"level": 100.0},
                         "stop": {"level": 97.0}, "tp": {"level": 106.0, "p_hit": 0.4}, "thesis": "t",
                         "forecast": {"thesis": "t", "direction": "with_trade", "target_px": 106.0, "p_target": 0.4,
                                      "invalidation_px": 97.5, "horizon_bars": 12, "timeframe": "1h"},
                         "exit_plan": "brackets; exit on a 1h close below 98"}}
META = {"decision_id": DESK_ROW["decision_id"]}


def test_first_wake_links_to_the_opening_desk_decision():
    b = dh.handoff_block("pkg-1", META, [DESK_ROW], [])
    assert b["read_state"] == "read" and b["prior_decision_id"] == DESK_ROW["decision_id"]
    assert b["opening"]["forecast"]["invalidation_px"] == 97.5 and b["opening"]["exit_plan"]
    assert b["chain_length"] == 0


def test_later_wakes_link_to_the_newest_review_one_chain_per_position():
    rv = [{"order_package_id": "pkg-1", "review_id": "LR-20261031T0800Z-pkg-1", "reviewed_at": "2026-10-31T08:03:00Z",
           "recommendation": {"action": "hold"}, "handoff": {"verdict": "confirm"}},
          {"order_package_id": "pkg-1", "review_id": "LR-20261031T0500Z-pkg-1", "reviewed_at": "2026-10-31T05:03:00Z",
           "recommendation": {"action": "hold"}},
          {"order_package_id": "pkg-OTHER", "review_id": "LR-20261031T0900Z-pkg-OTHER", "reviewed_at": "2026-10-31T09:00:00Z"}]
    b = dh.handoff_block("pkg-1", META, [DESK_ROW], rv)
    assert b["prior_decision_id"] == "LR-20261031T0800Z-pkg-1" and b["chain_length"] == 2
    assert b["chain_tail"][-1]["verdict"] == "confirm"


def test_an_unreadable_read_is_could_not_look_never_an_empty_chain():
    assert dh.handoff_block("pkg-1", META, None, [])["read_state"] == "could_not_look"
    b = dh.handoff_block("pkg-1", META, [DESK_ROW], None)
    assert b["read_state"] == "could_not_look" and b["chain_length"] is None and b["prior_decision_id"] is None
    assert dh.handoff_block("pkg-1", {}, [DESK_ROW], [])["read_state"] == "could_not_look"


def test_claude_desk_packages_are_on_the_judgement_cadence():
    """(c): no desk position goes longer than one cadence without an owner."""
    cfg = lrd.load_config(str(ROOT / "config/live_trade_review.yaml"))
    tf = lrd.timeframe_seconds(dh.DESK_LEG, str(cfg.get("default_timeframe", "2h")))
    hours = cfg["events"]["judgement_cadence"]["hours_by_timeframe"][lrd._TF_LABEL[tf]]
    assert hours == dh.CADENCE_HOURS
    floor = set(cfg["events"]["daily_floor"]["accounts"])
    accounts = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"][dh.DESK_LEG]["account_symbols"]
    assert set(accounts) <= floor
    ev = lrd.judgement_cadence_event({"last": None}, cfg, NOW, tf)
    assert ev and ev[0] == "judgement_cadence"


def test_orphans_flag_a_desk_position_with_no_decision_inside_cadence_plus_slack():
    pkgs = [{"order_package_id": "a", "strategy_name": "claude_desk", "symbol": "BTCUSDT", "created_at": "2026-10-31T03:00:00Z"},
            {"order_package_id": "b", "strategy_name": "claude_desk", "symbol": "ETHUSDT", "created_at": "2026-10-31T03:00:00Z"},
            {"order_package_id": "c", "strategy_name": "claude_desk", "symbol": "SOLUSDT", "created_at": "2026-10-31T06:00:00Z"},
            {"order_package_id": "d", "strategy_name": "other_leg", "symbol": "XRPUSDT", "created_at": "2026-10-01T00:00:00Z"},
            {"order_package_id": "e", "strategy_name": "claude_desk", "symbol": "ADAUSDT", "created_at": None}]
    rv = [{"order_package_id": "b", "reviewed_at": "2026-10-31T07:00:00Z"}]
    got = {o["order_package_id"]: o for o in dh.orphans(pkgs, rv, NOW)}
    assert set(got) == {"a", "e"}           # a: 6h; b: reviewed 2h ago; c: opened 3h ago; d: not a desk leg
    assert got["e"]["last_decision_at"] is None  # could not look is never read as owned


# --------------------------------------------------------------------------- the validator rule (b)

def _row_and_packet(**handoff):
    row = json.loads(json.dumps(_load("rb", "tests/test_live_review_reviewer_brief.py")._json_block("### Worked example")))
    packet = {"review_id": row["review_id"], "desk_handoff": {"read_state": "read", "prior_decision_id": DESK_ROW["decision_id"]}}
    row["handoff"] = {"prior_decision_id": DESK_ROW["decision_id"], "verdict": "revise", "reason": "stop to structure",
                      "read_state": "read", **handoff}
    return row, packet


def test_validator_accepts_a_linked_handoff_and_refuses_a_broken_one():
    v = _load("clr_h", "scripts/ci/check_live_review_records.py")
    row, packet = _row_and_packet()
    assert v.handoff_problems(row, packet) == []
    assert v.handoff_problems(_row_and_packet(prior_decision_id="DD-20261030T0000Z-scan-1h-1")[0], packet)
    assert v.handoff_problems(_row_and_packet(reason="")[0], packet)
    assert v.handoff_problems(_row_and_packet(verdict="exit")[0], packet)  # exit <=> close
    no = copy.deepcopy(row)
    no.pop("handoff")
    assert v.handoff_problems(no, packet)
    assert v.handoff_problems(no, {"review_id": row["review_id"]}) == []  # not a desk package: no handoff needed
    cnl = {"read_state": "could_not_look", "prior_decision_id": None}
    assert v.handoff_problems(_row_and_packet(read_state="could_not_look", prior_decision_id=None)[0],
                              {"desk_handoff": cnl}) == []
    assert v.handoff_problems(row, {"desk_handoff": cnl})  # must say could_not_look


def test_validator_runs_the_rule_through_the_committed_packet(tmp_path, monkeypatch):
    v = _load("clr_h2", "scripts/ci/check_live_review_records.py")
    row, packet = _row_and_packet()
    blob = json.dumps(packet).encode()
    row["packet_sha"] = hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert v.packet_blob_problems(row, blob) == []
    row["handoff"]["prior_decision_id"] = "LR-20261031T0000Z-pkg-x"
    assert any("one chain per position" in p for p in v.packet_blob_problems(row, blob))


def test_the_schema_admits_the_handoff_object():
    v = _load("clr_h3", "scripts/ci/check_live_review_records.py")
    schema = json.loads((ROOT / "comms/schema/live_review.schema.json").read_text())
    row, _ = _row_and_packet()
    row["reviewed_at"] = "2026-10-26T13:03:00Z"
    assert v.row_problems(row, "reviews", schema) == []
    row["handoff"]["verdict"] = "maybe"
    assert v.row_problems(row, "reviews", schema)
