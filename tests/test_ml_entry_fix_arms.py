"""ml_entry fix arms (RQ-20261124-f1a0-01..05) and the lever-arms verdict.json harness contract (PI-20261124-RQFAILS-0001)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_fix_arms_self_test():
    import ml_entry_fix_arms as F
    F._self_test()


def test_lever_arms_writes_the_harness_verdict_json():
    """script_run.derive_record reads exactly <out>/verdict.json; lever-arms used to write only verdict_<arm>.json, which landed a
    measured run as producer_failed (RQ-20261124-e1a7-02 run 45455675005)."""
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    body = src[src.index("def lever_arms_cmd"):src.index("def _self_test_lever_arms")]
    assert '(out / "verdict.json").write_text' in body


def test_fix_arms_writes_the_harness_verdict_json():
    src = (REPO / "scripts/research/ml_entry_fix_arms.py").read_text()
    assert '(out / "verdict.json").write_text' in src
