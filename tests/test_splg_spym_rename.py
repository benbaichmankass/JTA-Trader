"""SPLG was renamed SPYM by the issuer; the leg id is kept, the traded symbol moved.

Guards the 2026-10-28 rename: the leg must trade a symbol that is declared in
config/instruments.yaml, listed on the accounts that carry the leg, and the dead
ticker must not reappear in live config.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEG = "splg_trend_long_1d"


def _load(name):
    return yaml.safe_load((ROOT / "config" / name).read_text())


def test_leg_id_kept_and_symbol_is_spym():
    leg = _load("strategies.yaml")["strategies"][LEG]
    assert leg["symbols"] == ["SPYM"]


def test_spym_declared_and_spplg_gone_from_instruments():
    inst = _load("instruments.yaml")
    table = inst.get("instruments", inst)
    assert "SPYM" in table and "SPLG" not in table
    assert table["SPYM"]["base_asset"] == "SPYM"


def test_every_account_carrying_the_leg_lists_spym():
    accts = _load("accounts.yaml")["accounts"]
    for name, acct in accts.items():
        if LEG in (acct.get("strategies") or []):
            assert "SPYM" in (acct.get("symbols") or []), name
        assert "SPLG" not in (acct.get("symbols") or []), name
