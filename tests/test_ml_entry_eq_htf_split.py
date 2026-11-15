"""ml_entry_eq_htf_split: point-in-time daily attach (previous session only), date-clustered stats, and the rule's thin-n branch."""
import importlib
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
M = importlib.import_module("ml_entry_eq_htf_split")


def test_self_test():
    assert M.self_test() == 0


def test_judge_pass_and_fail_branches():
    ct = {"n": 50, "mean_net_r": -0.4, "t_date_clustered": -2.5}
    assert M.judge({"against_gt40": ct, "with_gt40": {"n": 60, "mean_net_r": 0.1}})["verdict"] == "pass"
    assert M.judge({"against_gt40": {**ct, "t_date_clustered": -1.0}, "with_gt40": {"n": 60, "mean_net_r": 0.1}})["verdict"] == "fail"
    assert M.judge({"against_gt40": ct, "with_gt40": {"n": 60, "mean_net_r": -0.9}})["verdict"] == "fail"
