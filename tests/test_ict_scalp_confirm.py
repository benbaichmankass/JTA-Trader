"""DESK-8a: the registered rule in scripts/research/ict_scalp_confirm.py, on synthetic trade lists."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "scripts" / "research", REPO / "scripts" / "ops"):
    sys.path.insert(0, str(p))

import ict_scalp_confirm as c  # noqa: E402


def _t(n, f):
    return [{"entry_time": f"2023-{1 + i // 28:02d}-{1 + i % 28:02d}T00:00", "net_r": f(i)} for i in range(n)]


def test_pass_needs_every_clause():
    assert c.decide(_t(100, lambda i: 0.3 if i % 2 else -0.1), "faithful")["verdict"] == "pass"


def test_underpowered_is_indeterminate_not_fail():
    assert c.decide(_t(87, lambda i: -0.5), "faithful")["verdict"] == "indeterminate"


def test_fail_on_negative_net_or_approximate_fidelity():
    assert c.decide(_t(100, lambda i: -0.1), "faithful")["verdict"] == "fail"
    assert c.decide(_t(100, lambda i: 0.3), "approximate")["verdict"] == "fail"


def test_one_fold_carrying_the_sum_is_not_a_majority():
    r = c.decide(_t(100, lambda i: 5.0 if i < 25 else -0.1), "faithful")
    assert r["net_r"] > 0 and r["folds_positive"] == 1 and r["verdict"] == "fail"


def test_no_trades_is_not_applicable():
    assert c.decide([], "faithful")["verdict"] == "not_applicable"
