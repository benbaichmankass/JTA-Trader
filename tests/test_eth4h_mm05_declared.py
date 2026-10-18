"""trend_donchian_eth_4h measured-move TP revision (width 0.5) Tier-3 packet pins.

The declaration must reach the live package meta and the rule's resolved
parameters (an unknown key passes through silently), and the mirror pair must
still carry the leg. Evidence: research/results/RQ-20261018-007/.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.runtime import tp_revision as tr

ROOT = Path(__file__).resolve().parents[1]


def _leg():
    cfg = yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text())
    return cfg["strategies"]["trend_donchian_eth_4h"]


def test_declared_rule_and_width_resolve_exactly_as_tested():
    leg = _leg()
    assert tr.declared_rule(leg) == tr.RULE_DONCHIAN_MEASURED_MOVE
    assert tr.rule_params(leg) == {"width_mult": 0.5}
    assert tr.RULE_DONCHIAN_MEASURED_MOVE in tr.RULES
    # Tested arm A geometry: unchanged by this packet.
    assert leg["atr_stop_mult"] == 1.5 and leg["trail_mult"] == 6.0 and leg["donchian"] == 20


def test_declaration_threads_into_package_meta():
    import inspect

    from src.units.strategies import trend_donchian as td
    assert '"tp_revision"' in inspect.getsource(td.order_package)


def test_leg_still_on_both_halves_of_the_stage_2_pair():
    accts = yaml.safe_load((ROOT / "config" / "accounts.yaml").read_text())
    accts = accts.get("accounts", accts)
    assert "trend_donchian_eth_4h" in accts["bybit_2"]["strategies"]
    assert "trend_donchian_eth_4h" in accts["bybit_portfolio"]["strategies"]
