"""The four queue-quality checks added to scripts/research/infra_selftest.py (lane AUTHOR-FLOOR-1024)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research import infra_selftest as ist  # noqa: E402


def _patch(monkeypatch, units):
    monkeypatch.setattr(ist, "_queued_authored", lambda: units)


def test_value_coverage_counts_units_without_a_money_figure(monkeypatch):
    _patch(monkeypatch, [("RQ-A", {"value": {"usd_at_stake_per_month": 10}}), ("RQ-B", {"value": {}}), ("RQ-C", {})])
    v = ist.value_coverage()
    assert v["verdict"] == "fail" and v["measurement"]["sample"] == ["RQ-B", "RQ-C"] and v["n"] == 3


def test_value_coverage_no_units_is_no_data_not_a_pass(monkeypatch):
    _patch(monkeypatch, [])
    v = ist.value_coverage()
    assert v["read_state"] == "no_data" and v["verdict"] == "fail"


def test_command_resolvable_flags_a_missing_script(monkeypatch):
    _patch(monkeypatch, [("RQ-A", {"run": {"command": ["python3", "scripts/research/infra_selftest.py"]}}),
                         ("RQ-B", {"run": {"command": ["python3", "scripts/research/does_not_exist.py"]}}),
                         ("RQ-C", {"run": {"workflow": "x.yml"}})])
    v = ist.command_resolvable()
    assert v["verdict"] == "fail" and v["n"] == 2 and v["measurement"]["missing"][0]["unit"] == "RQ-B"


def test_duplicate_commands_masks_own_id_and_respects_head_to_head(monkeypatch):
    cmd = lambda i: {"run": {"command": ["python3", "s.py", "--unit", i]}}   # noqa: E731
    _patch(monkeypatch, [("RQ-A", cmd("RQ-A")), ("RQ-B", cmd("RQ-B"))])
    assert ist.duplicate_commands()["measurement"]["pairs"] == [["RQ-A", "RQ-B"]]
    _patch(monkeypatch, [("RQ-A", {**cmd("RQ-A"), "head_to_head": {"symbol": "ETH"}}),
                         ("RQ-B", {**cmd("RQ-B"), "head_to_head": {"symbol": "XRP"}})])
    assert ist.duplicate_commands()["verdict"] == "pass"


def test_power_declared_skips_deterministic_and_flags_missing_n(monkeypatch):
    ok = {"power": {"expected_n": 40}, "decision_rule": {"registered_before_run": True}}
    _patch(monkeypatch, [("RQ-A", ok), ("RQ-B", {"decision_rule": {"registered_before_run": True}}),
                         ("RQ-C", {"kind": "deterministic"})])
    v = ist.power_declared()
    assert v["n"] == 2 and v["measurement"]["sample"][0]["unit"] == "RQ-B"


def test_roadmap_ref_valid_flags_string_and_unknown_ids(monkeypatch):
    _patch(monkeypatch, [("RQ-A", {"roadmap": ["L-OPS"]}), ("RQ-B", {"roadmap": "M28"}), ("RQ-C", {"roadmap": ["NOPE"]}),
                         ("RQ-D", {})])
    v = ist.roadmap_ref_valid()
    assert v["verdict"] == "fail" and set(v["measurement"]["sample"]) == {"RQ-B", "RQ-C"}


def test_never_dispatched_age_skips_dispatched_and_gated(monkeypatch):
    _patch(monkeypatch, [("RQ-20200101-001", {}), ("RQ-20200101-002", {"last_dispatched_at": "x"}),
                         ("RQ-20200101-003", {"requires_result": {"unit": "RQ-Z"}})])
    v = ist.never_dispatched_age()
    assert v["measurement"]["over_age"] == 1 and v["verdict"] == "pass"
    monkeypatch.setattr(ist, "NEVER_DISPATCHED_MAX", 0)
    assert ist.never_dispatched_age()["verdict"] == "fail"


def test_related_paths_exist_flags_a_missing_path_only(monkeypatch):
    _patch(monkeypatch, [("RQ-A", {"related": ["scripts/research/infra_selftest.py", "RQ-20260101-001", "docs/nope.md"]})])
    v = ist.related_paths_exist()
    assert v["verdict"] == "fail" and v["measurement"]["missing"] == [{"unit": "RQ-A", "path": "docs/nope.md"}]
