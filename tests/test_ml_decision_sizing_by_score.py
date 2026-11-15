"""ml_decision_sizing_by_score: weight map, planted PASS / FAIL, thin-n branch."""
import importlib
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
M = importlib.import_module("ml_decision_sizing_by_score")


def test_self_test():
    assert M.self_test() == 0
