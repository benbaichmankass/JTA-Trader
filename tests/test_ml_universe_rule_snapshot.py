"""ML-UNIVERSE-RULE (2026-11-26): removing the per-account ``account_symbols`` maps must not change what any account trades,
except the decisions listed in the fixture's ``_changed``. The fixture is the pre-change ``leg_symbols`` for every account x
rostered leg (main 150e68ea2e). A roster or symbols edit after that changes the live config, not this rule: such a pair is
skipped only when its leg or account no longer exists, and a NEW pair is checked against the rule itself below."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import symbol_sets as SS
from src.config import venue_capability as VC
from src.config.accounts_loader import load_accounts_dict

FIX = json.loads((Path(__file__).parent / "fixtures" / "ml_universe_rule_snapshot.json").read_text())


def _pairs():
    for acct, legs in sorted(FIX["snapshot"].items()):
        for leg, syms in sorted(legs.items()):
            yield acct, leg, syms


@pytest.mark.parametrize("acct,leg,before", list(_pairs()))
def test_every_account_trades_what_it_traded_before_the_maps_were_removed(acct, leg, before):
    accts = load_accounts_dict()
    cfg = SS.load_strategies_cfg()
    if acct not in accts or leg not in (accts[acct].get("strategies") or []) or leg not in cfg:
        pytest.skip(f"{acct}/{leg} no longer rostered (a later config change, not this rule)")
    expected = FIX["_changed"].get(f"{acct}/{leg}", {}).get("now", before)
    got = SS.leg_symbols(cfg[leg], acct, leg=leg)
    assert sorted(got) == sorted(expected), (acct, leg, got, expected)


def test_no_leg_carries_a_per_account_symbol_map():
    cfg = SS.load_strategies_cfg()
    offenders = [n for n, c in cfg.items() if isinstance(c, dict) and SS.ACCOUNT_SYMBOLS_KEY in c]
    assert offenders == [], f"per-account symbol maps are retired (canonical rule 2026-11-04): {offenders}"


def test_venue_capability_is_by_asset_class():
    assert VC.venue_can_trade("BTCUSDT", "bybit") and VC.venue_can_trade("BTCUSDT", "breakout")
    assert not VC.venue_can_trade("SPY", "bybit") and VC.venue_can_trade("SPY", "alpaca")
    assert VC.venue_can_trade("SPY", "interactive_brokers") and VC.venue_can_trade("MES", "interactive_brokers")
    assert not VC.venue_can_trade("MES", "alpaca") and not VC.venue_can_trade("BTCUSDT", "alpaca")
    assert not VC.venue_can_trade("SPY", "nonexistent_venue")
    assert not VC.venue_can_trade("AAXJ", "interactive_brokers") and VC.venue_can_trade("AAXJ", "alpaca")   # IB: STK-resolved only


def test_prop_account_takes_only_the_prop_gate_population(tmp_path, monkeypatch):
    (tmp_path / "legx.json").write_text(json.dumps({"symbols": ["ETHUSDT"]}))
    monkeypatch.setattr(SS, "PROP_SURVIVAL_DIR", tmp_path)
    monkeypatch.setattr(SS, "_account", lambda a: {"exchange": "breakout", "account_class": "prop"} if a == "p" else
                        {"exchange": "bybit", "account_class": "paper"})
    cfg = {"symbols": ["BTCUSDT", "ETHUSDT", "SPY"]}
    assert SS.leg_symbols(cfg, "p", leg="legx") == ["ETHUSDT"]
    assert SS.leg_symbols(cfg, "q", leg="legx") == ["BTCUSDT", "ETHUSDT"]
    assert SS.leg_symbols(cfg, "p", leg="no_record") == ["BTCUSDT", "ETHUSDT"]   # no structured record: not narrowed


def test_an_unreadable_account_never_narrows(monkeypatch):
    monkeypatch.setattr(SS, "_account", lambda a: None)
    assert SS.leg_symbols({"symbols": ["BTCUSDT", "SPY"]}, "gone") == ["BTCUSDT", "SPY"]
