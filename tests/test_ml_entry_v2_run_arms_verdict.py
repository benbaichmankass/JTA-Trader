"""ml_entry_v2_run.write_verdict reads the per-ARM verdict shape (b604 / b607) as well as the per-CELL one.

Before 2026-11-15 an ``arms`` result wrote no verdict.json, so the run landed producer_failed and the unit stayed queued
(b604 ran 3x, b607 4x with real results on main)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
sys.path.insert(0, str(ROOT))

import ml_entry_v2_run as M  # noqa: E402


def _run(tmp_path: Path, payload: dict) -> dict | None:
    (tmp_path / "x_result.json").write_text(json.dumps(payload))
    ok = M.write_verdict("RQ-TEST", tmp_path)
    return json.loads((tmp_path / "verdict.json").read_text()) if ok else None


def test_arms_with_a_win_is_pass(tmp_path):
    v = _run(tmp_path, {"unit": "RQ-TEST", "arms": {"A": {"verdict": "no_win", "n": [5000]},
                                                    "B": {"verdict": "win", "n": [6000]}}})
    assert v["verdict"] == "pass" and v["read_state"] == "measured" and v["n"] == 6000   # n = the largest cell's n


def test_arms_indeterminate_and_no_win_is_indeterminate(tmp_path):
    v = _run(tmp_path, {"arms": {"R1": {"verdict": "indeterminate", "n": [70000]}, "R2": {"verdict": "no_win", "n": [70000]}}})
    assert v["verdict"] == "indeterminate"


def test_arms_all_no_win_is_fail(tmp_path):
    v = _run(tmp_path, {"arms": {"R1": {"verdict": "no_win", "n": [100]}}})
    assert v["verdict"] == "fail"


def test_cells_shape_unchanged(tmp_path):
    v = _run(tmp_path, {"cells": {"base": {"verdict": "base"}, "c1": {"verdict": "win", "n": [10]}}})
    assert v["verdict"] == "pass"


def test_unknown_word_writes_nothing(tmp_path):
    assert _run(tmp_path, {"arms": {"R1": {"verdict": "descriptive", "n": [1]}}}) is None
