"""D9 fill model (MLP-D9-WHIPPET): the self-test pins kappa=inf to desk_maker_fills strict, monotonicity in the queue, and the hand cases."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

import fill_model as FM


def test_self_test():
    FM._self_test()


def test_breakeven_states():
    def cv(means, los):
        return [{"kappa": k, "mean_delta_F_bps": m, "ci95": [lo, 9.0]} for k, m, lo in zip((0, 1, "inf"), means, los)]
    assert FM.breakeven_kappa(cv([3, 3, 3], [1, 1, 1]), 2.0)["state"] == "robust"
    assert FM.breakeven_kappa(cv([1, 1, 1], [1, 1, 1]), 2.0)["state"] == "fails_everywhere"
    assert FM.breakeven_kappa(cv([3, 1, 1], [1, 1, 1]), 2.0) == {"state": "queue_dependent", "kappa_star": 0, "holds_at_0": True, "holds_at_inf": False}
    assert FM.breakeven_kappa([], 2.0)["state"] == "no_data"
