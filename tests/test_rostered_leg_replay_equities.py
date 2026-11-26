"""REGIME-PROGRAM equities universe (rostered_leg_replay --universe equities, RQ-20261126-e9a4-01): the rostered non-crypto legs, disjoint from the
crypto population, Dukascopy candles, SPY anchor, and its own rule ids."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_universes_are_disjoint_and_split_on_the_symbol():
    import rostered_leg_replay as R
    cr, eq = R.rostered_legs(), R.rostered_legs(universe="equities")
    assert cr and eq and not set(cr) & set(eq)
    assert all(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in cr.values())
    assert not any(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in eq.values())
    assert all(v["harness"] in R.FAMILIES for v in eq.values())


def test_equities_rule_ids_and_anchor():
    import rostered_leg_replay as R
    assert R.RULE_FILTER_EQ["id"] != R.RULE_FILTER["id"] and R.RULE_FILTER_EQ["min_delta_r"] == R.RULE_MS["min_delta_r"]
    assert R.EQ_ANCHOR == {"symbols": ["SPY"], "timeframe": "1d"}


def test_equities_universe_refuses_other_modes():
    import rostered_leg_replay as R
    with pytest.raises(SystemExit):
        R.main(["--universe", "equities", "--mode", "book", "--out", "/tmp/_eq_refuse"])
