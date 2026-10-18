"""trend_donchian_eth_mm05 (soak alias of trend_donchian_eth_4h) Tier-3 packet pins.

The alias carries the measured-move TP revision (width 0.5) and is rostered on
bybit_1 ONLY; the real-money leg and its mirror stay on the undeclared
incumbent together. Evidence: research/results/RQ-20261018-007/.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from src.runtime import tp_revision as tr
from src.units.strategies import trend_donchian as td

ROOT = Path(__file__).resolve().parents[1]
ALIAS, INCUMBENT = "trend_donchian_eth_mm05", "trend_donchian_eth_4h"


def _strategies():
    return yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text())["strategies"]


def _accounts():
    accts = yaml.safe_load((ROOT / "config" / "accounts.yaml").read_text())
    return accts.get("accounts", accts)


def test_alias_declares_the_rule_and_width_exactly_as_tested():
    leg = _strategies()[ALIAS]
    assert tr.declared_rule(leg) == tr.RULE_DONCHIAN_MEASURED_MOVE
    assert tr.rule_params(leg) == {"width_mult": 0.5}
    assert tr.RULE_DONCHIAN_MEASURED_MOVE in tr.RULES
    assert '"tp_revision"' in inspect.getsource(td.order_package)


def test_alias_differs_from_the_incumbent_only_by_the_declaration_and_prefix():
    s = _strategies()
    inc, alias = s[INCUMBENT], s[ALIAS]
    assert "tp_revision" not in inc
    keys = set(inc) | set(alias)
    assert {k for k in keys if inc.get(k) != alias.get(k)} == {"tp_revision", "signal_prefixes"}
    # Attribution is by substring: no alias prefix may contain or be contained by an incumbent one.
    for a in alias["signal_prefixes"]:
        for i in inc["signal_prefixes"]:
            assert a not in i and i not in a


def test_staging_alias_on_bybit_1_only_and_pair_stays_on_the_incumbent():
    a = _accounts()
    assert ALIAS in a["bybit_1"]["strategies"] and INCUMBENT not in a["bybit_1"]["strategies"]
    for acct in ("bybit_2", "bybit_portfolio"):
        assert INCUMBENT in a[acct]["strategies"] and ALIAS not in a[acct]["strategies"]
    assert a["bybit_2"]["strategies"] == a["bybit_portfolio"]["strategies"]
