"""scripts/ops/rebase_evidence_decision_bar.py — the pure re-base of a Stage-0 record onto
the decision bar a leg trades (DECISION-BAR-MATCH, operator 2026-10-22). Synthetic rows."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "ops"), str(REPO / "scripts" / "research"), str(REPO)]
_spec = importlib.util.spec_from_file_location(
    "rebase_evidence_decision_bar", REPO / "scripts" / "ops" / "rebase_evidence_decision_bar.py")
reb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reb)

OLD = {"strategy": "leg_x", "folds": 4, "net_r_oos": 5.0, "n_trades_oos": 8, "fidelity": "faithful",
       "fold_basis": "calendar", "fold_detail_equal_count": [], "generated_at": "2026-10-01T00:00:00Z"}
BT = {"data_start": "2025-01-01 00:00:00+00:00", "data_end": "2025-12-31 23:00:00+00:00",
      "fee_bps_roundtrip": 7.5, "slippage_bps_roundtrip": 3.0, "funding_bps_per_window": 1.0}


def _rows(rs):
    return [{"entry_time": f"2025-{m:02d}-01 00:00:00+00:00", "exit_time": f"2025-{m:02d}-01 06:00:00+00:00",
             "net_r": r, "net_r_fee_only": r + 0.1} for m, r in enumerate(rs, start=1)]


def test_window_filter_is_inclusive_and_drops_outside_rows():
    rows = _rows([1.0, -1.0]) + [{"entry_time": "2026-02-01 00:00:00+00:00", "net_r": 9.0}]
    assert len(reb.in_window(rows, BT["data_start"], BT["data_end"])) == 2


def test_rebase_recomputes_measured_fields_and_names_the_bar():
    t = _rows([1.0, -0.5, 2.0, -1.0, 0.5, 1.5, -0.2, 0.7])
    rec = reb.rebase(OLD, BT, t, decision_bar="forming", cfg={"timeframe": "1h"}, run_dir_rel="runs/x",
                     unit="RQ-1", old_path_rel="git:old", now="2026-10-22T00:00:00Z")
    assert rec["decision_bar"] == "forming" and rec["supersedes"] == "git:old"
    assert rec["n_trades_oos"] == 8 and rec["net_r_oos"] == pytest.approx(4.0)
    assert rec["folds"] == 4 and rec["decision_rule"]["verdict"] == "pass"
    assert rec["net_r_oos_fee_only"] == pytest.approx(4.8)
    assert rec["cost_stack"]["source"] == "runs/x/leg_x__bt.json"
    assert "fold_detail_equal_count" not in rec and rec["fidelity"] == "faithful"


def test_rebase_fails_rule_d1_on_negative_and_refuses_empty():
    rec = reb.rebase(OLD, BT, _rows([-1.0, -0.5]), decision_bar="forming", cfg={}, run_dir_rel="r",
                     unit="u", old_path_rel="o", now="n")
    assert rec["decision_rule"]["verdict"] == "fail"
    with pytest.raises(ValueError):
        reb.rebase(OLD, BT, [], decision_bar="forming", cfg={}, run_dir_rel="r", unit="u",
                   old_path_rel="o", now="n")
