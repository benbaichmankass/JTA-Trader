"""trend_donchian_eth_4h measured-move TP revision (width 0.5) Tier-3 packet pins.

The declaration must reach the rule's resolved parameters (an unknown key passes
through silently) and the live/mirror pair must still carry the leg.
Evidence: research/results/RQ-20261018-007/.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from src.runtime import tp_revision as tr
from src.units.strategies import trend_donchian as td

ROOT = Path(__file__).resolve().parents[1]
LEG = "trend_donchian_eth_4h"


def _accounts():
    accts = yaml.safe_load((ROOT / "config" / "accounts.yaml").read_text())
    return accts.get("accounts", accts)


def test_declared_rule_and_width_resolve_exactly_as_tested():
    leg = yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text())["strategies"][LEG]
    assert tr.declared_rule(leg) == tr.RULE_DONCHIAN_MEASURED_MOVE
    assert tr.rule_params(leg) == {"width_mult": 0.5}
    assert tr.RULE_DONCHIAN_MEASURED_MOVE in tr.RULES
    assert '"tp_revision"' in inspect.getsource(td.order_package)
    # Tested arm A geometry is unchanged by this packet.
    assert leg["atr_stop_mult"] == 1.5 and leg["trail_mult"] == 6.0 and leg["donchian"] == 20


def test_leg_on_all_three_accounts_and_pair_stays_equal():
    a = _accounts()
    for acct in ("bybit_2", "bybit_portfolio", "bybit_1"):
        assert LEG in a[acct]["strategies"]
    assert a["bybit_2"]["strategies"] == a["bybit_portfolio"]["strategies"]
