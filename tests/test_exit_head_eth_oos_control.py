"""exit_head_eth_oos_control: the 78fc-03 rule branches and the matched random-truncation control's mechanics."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
M = importlib.import_module("exit_head_eth_oos_control")


def test_rule_branches():
    assert M.judge([0.01] * 10)["verdict"] == "indeterminate"
    assert M.judge([0.01, -0.01] * 200)["verdict"] == "pass"            # mean 0, tiny se -> LB > -0.02
    assert M.judge([-0.05, -0.03] * 200)["verdict"] == "fail"


def test_control_is_deterministic_and_matched():
    candles = pd.DataFrame({"close": [100.0 + i for i in range(50)]})
    t = [SimpleNamespace(entry_index=i, exit_index=i + 5, entry=100.0 + i, risk=2.0, direction="long", r_multiple=1.0) for i in range(0, 40, 6)]
    a = M.control_draws(candles, [t], [3], 50, 7)
    b = M.control_draws(candles, [t], [3], 50, 7)
    assert a == b and len(a) == 50
    # every truncation of a rising long closes at (bar - entry)/risk in [0.5, 3.0]; minus baseline 1.0 per trade, 3 trades
    assert all(-1.5 - 1e-9 <= x <= 6.0 + 1e-9 for x in a)
    assert M.control_draws(candles, [t], [0], 5, 7) == [0.0] * 5
