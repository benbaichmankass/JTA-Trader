"""ml_decision_vol_decomp: exact decomposition, planted CONFOUND and planted DIRECTION branches, thin-n branch."""
import importlib
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
M = importlib.import_module("ml_decision_vol_decomp")


def test_self_test():
    assert M.self_test() == 0


def test_thin_n_is_indeterminate():
    assert M.judge({"n": 5})["verdict"] == "indeterminate"
