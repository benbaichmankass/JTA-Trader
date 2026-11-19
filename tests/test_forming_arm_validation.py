"""scripts/research/forming_arm_validation.py (unit RQ-20261119-f1a7-01): the verdict logic on planted data only; the run itself needs a runner."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

import forming_arm_validation as v  # noqa: E402


def test_self_test_passes():
    assert v.self_test() == 0


def test_the_record_it_reproduces_is_the_committed_one():
    import json
    repo = Path(__file__).resolve().parents[1]
    bt = json.loads((repo / v.RECORD_BT).read_text())
    ev = json.loads((repo / "comms" / "strategy_evidence" / "ict_scalp_eth_15m.json").read_text())
    assert ev["source_run"].startswith(v.RECORD_BT.rsplit("/", 1)[0]), "the control must be the run the committed record was built from"
    assert int(bt["total_trades"]) == int(ev["n_trades_oos"]) == 76 and abs(float(bt["net_total_r"]) - float(ev["net_r_oos"])) < 0.01
    assert str(bt["data_start"]).startswith(v.START) and str(bt["data_end"]).startswith("2026-10-27")


def test_the_unit_runs_this_script_with_the_same_window():
    import yaml
    repo = Path(__file__).resolve().parents[1]
    path = next(q for q in (repo / "research" / "queue" / "RQ-20261119-f1a7-01.yaml",
                            repo / "research" / "queue" / "blocked" / "RQ-20261119-f1a7-01.yaml") if q.exists())
    u = yaml.safe_load(path.read_text())
    assert u["run"]["command"][:3] == ["python3", "scripts/research/forming_arm_validation.py", "run"]
    assert u["kind"] == "deterministic" and u["decision_rule"]["registered_before_run"] is True
    text = u["decision_rule"]["statistic"]
    assert v.START in text and "2026-10-27 23:59" in text and str(v.DAYS) in text
