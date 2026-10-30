"""am_class_regrade.py: the per-class re-grade of the DESK-LIFECYCLE-S0 corpus (RQ-20261029-1f39-02)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import am_class_regrade as cr  # noqa: E402


def test_class_only_keeps_that_class_and_holds_the_rest():
    dec = {("E1", 0): {"action": "tighten_sl", "level_r": 0.0}, ("E1", 1): {"action": "close"},
           ("E1", 2): {"action": "hold"}}
    d = cr.class_only(dec, "E1", "tighten_sl")
    assert d(0, 0, {}) == {"action": "tighten_sl", "level_r": 0.0}
    assert d(1, 0, {}) == {"action": "hold"}
    assert d(2, 0, {}) == {"action": "hold"}
    assert d(3, 0, {}) is None          # a missing answer stays missing: the replay pends, never invents a hold


def test_positive_control_flags_a_mismatch(tmp_path):
    p = tmp_path / "pairs.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in (
        {"pair_id": "A", "C_h": 1.0, "C_m": 0.5, "R_h": 0.1, "R_m": 0.2},
        {"pair_id": "B", "C_h": -1.0, "C_m": None, "R_h": 0.3, "R_m": 0.3})))
    ok = cr.positive_control([("A", 1.0, 0.5)], p, "claude")
    assert ok["ok"] and ok["committed"] == 1
    bad = cr.positive_control([("A", 1.0, 0.6)], p, "claude")
    assert not bad["ok"] and bad["mismatched_or_missing"] == 1
    missing = cr.positive_control([("A", 0.1, 0.2)], p, "random")
    assert not missing["ok"]            # B's random pair was committed but not reproduced


def test_registered_numbers_match_the_unit():
    import yaml
    u = yaml.safe_load((REPO / "research/queue/RQ-20261029-1f39-02.yaml").read_text())
    assert u["decision_rule"]["registered_before_run"] is True
    assert u["intervention_controls"]["matched_random"]["draws"] == cr.DRAWS == 100
    assert (cr.FOLDS, cr.FOLD_MAJORITY) == (4, 3)
    assert "--fetch" in u["run"]["command"]
