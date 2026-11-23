"""exit_lever_ablation covers the squeeze harness (RQ-20261118-abab-45/-46 and RQ-20261101-78fc-54 were producer_failed on the refusal).

``build_arm_argv`` refused ``squeeze_breakout_4h`` ("this ablation covers the trend, pullback, ict_scalp, turtle_soup, fade and fvg_range harnesses") although
``rdm.build_harness_cmd`` has the squeeze branch the evidence builder runs; PR #28213 added ``--side-filter`` / ``--skip-hours`` to ``scripts/backtest_squeeze.py`` but
the whitelist in the ablation was never widened, and the units were not run through the ablation, so abab-45/-46 died on it. Locked here: (1) the squeeze leg builds
an argv for scripts/backtest_squeeze.py, (2) an arm's raw flags reach that argv (the lever the unit tests), (3) a harness outside the list is still refused.
"""
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
sys.path.insert(0, str(REPO))



def _e():
    import exit_lever_ablation
    return exit_lever_ablation


def _cfg():
    legs = yaml.safe_load((REPO / "config/strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    return legs["squeeze_breakout_4h"]


def test_squeeze_leg_builds_an_argv_for_the_squeeze_harness():
    argv, _ = _e().build_arm_argv("squeeze_breakout_4h", _cfg(), "<d>", "4h", "<e>", "<j>", [], None, None)
    assert any(a.endswith("backtest_squeeze.py") for a in argv)


@pytest.mark.parametrize("flag,value", [("--side-filter", "long"), ("--side-filter", "short"), ("--skip-hours", "0,1,2,3,4,5,6,7")])
def test_the_arms_raw_flags_reach_the_squeeze_argv(flag, value):
    argv, _ = _e().build_arm_argv("squeeze_breakout_4h", _cfg(), "<d>", "4h", "<e>", "<j>", [flag, value], None, None)
    assert flag in argv and argv[argv.index(flag) + 1] == value


def test_a_harness_outside_the_list_is_still_refused(monkeypatch):
    import regime_debt_matrix as rdm
    monkeypatch.setattr(rdm, "classify", lambda cfg: "orb")
    with pytest.raises(ValueError, match="fvg_range and squeeze harnesses"):
        _e().build_arm_argv("squeeze_breakout_4h", _cfg(), "<d>", "4h", "<e>", "<j>", [], None, None)
