"""AMEND-PARITY-ALL-ACCOUNTS — every account that can place orders can also
UPDATE the SL/TP of an open position (operator directive 2026-10-25:
"building a broker integration is not only placing the trade, it is also being
able to update the trade in real time").

Two rules, both over the REAL config (``config/accounts.yaml`` and
``config/prop_platforms.yaml``), so a new broker or a new account fails CI
here until it declares a modify-open-position path:

1. Every account with ``mode: live`` resolves to a modify path:
   * a prop account → its platform adapter OVERRIDES ``modify_bracket`` (VM
     executor, ``prop_trail``), or it is a phone account served by the
     ``phone_trail`` amend channel;
   * anything else → its integration declares ``modify`` in
     ``clients.EXCHANGE_MANAGEMENT_CAPS`` AND ``execute.modify_open_order`` has
     a branch for it.
2. Every integration (``integrator.EXCHANGE_MAP`` plus every ``exchange:`` in
   accounts.yaml) either declares ``modify`` or is listed in
   :data:`KNOWN_AMEND_GAPS` with the checklist row that closes it — and no
   ``mode: live`` non-prop account may sit on a listed gap.

A gap entry is a visible line in this file, in the PR diff, naming a row. It
may only shrink.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from src.prop.prop_identity import is_prop_account
from src.units.accounts import execute
from src.units.accounts.clients import exchange_management_caps
from src.units.accounts.integrator import EXCHANGE_MAP

REPO = Path(__file__).resolve().parents[1]

#: integration -> why it has no modify path, and the row that closes it.
KNOWN_AMEND_GAPS = {
    # oanda_practice is dry_run; OandaClient has no SL/TP modify. Flipping it
    # live without one fails rule 1 below.
    "oanda": "AMEND-PARITY-OANDA",
    # The EXCHANGE_MAP stub for prop accounts places nothing itself: prop
    # accounts trade and amend through src/prop (rule 1's prop branch).
    "breakout": "n/a: prop accounts amend via src/prop platform adapters / phone_trail",
}


def _accounts():
    d = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    acc = d.get("accounts", d)
    return {k: v for k, v in acc.items() if isinstance(v, dict) and v.get("exchange")}


def _platforms():
    return yaml.safe_load((REPO / "config" / "prop_platforms.yaml").read_text()) or {}


def amend_path_for(account_id, cfg, platforms):
    """``(kind, where)`` for the account's modify-open-position path, or
    ``None`` when it has none."""
    if is_prop_account(cfg):
        if account_id in (platforms.get("phone_accounts") or {}):
            from src.prop import phone_trail
            if all(hasattr(phone_trail, f) for f in ("plan_amends", "claim_amend", "record_amend_result")):
                return ("phone_amend_channel", "src/prop/phone_trail.py::plan_amends/claim_amend")
            return None
        entry = (platforms.get("accounts") or {}).get(account_id)
        if not isinstance(entry, dict):
            return None
        from src.prop.platform import adapter_for_platform
        from src.prop.platform.base import PropPlatformAdapter
        cls = type(adapter_for_platform(str(entry.get("platform"))))
        if cls.modify_bracket is PropPlatformAdapter.modify_bracket:
            return None
        return ("prop_vm_modify_bracket", f"{cls.__module__}.{cls.__name__}.modify_bracket")
    ex = str(cfg.get("exchange") or "").lower()
    if "modify" not in exchange_management_caps(ex):
        return None
    src = inspect.getsource(execute.modify_open_order)
    aliases = {"interactive_brokers": ("interactive_brokers", '"ib"'), "ib": ('"ib"',)}.get(ex, (f'"{ex}"',))
    if not any(a.strip('"') in src for a in aliases):
        return None
    return ("modify_open_order", f"src/units/accounts/execute.py::modify_open_order[{ex}]")


def test_every_live_account_has_a_modify_open_position_path():
    platforms = _platforms()
    missing = [aid for aid, cfg in _accounts().items()
               if str(cfg.get("mode") or "live").lower() == "live"
               and amend_path_for(aid, cfg, platforms) is None]
    assert not missing, (
        f"live account(s) {missing} can place orders but have NO path to modify an open "
        "position's SL/TP. Wire one (see .claude/skills/new-broker/SKILL.md step 4b) before "
        "the account goes live.")


def test_every_integration_declares_modify_or_a_tracked_gap():
    exchanges = {e.lower() for e in EXCHANGE_MAP} | {
        str(c["exchange"]).lower() for c in _accounts().values()}
    undeclared = sorted(e for e in exchanges
                        if "modify" not in exchange_management_caps(e) and e not in KNOWN_AMEND_GAPS)
    assert not undeclared, (
        f"integration(s) {undeclared} declare no `modify` cap and no KNOWN_AMEND_GAPS entry. "
        "A broker integration is not done until an open trade can be amended.")


def test_known_gaps_are_real_and_not_live():
    for ex in KNOWN_AMEND_GAPS:
        assert "modify" not in exchange_management_caps(ex), (
            f"{ex} now declares modify: delete its KNOWN_AMEND_GAPS entry (the list only shrinks)")
    live_on_gap = [aid for aid, c in _accounts().items()
                   if str(c.get("exchange")).lower() in KNOWN_AMEND_GAPS
                   and not is_prop_account(c)
                   and str(c.get("mode") or "live").lower() == "live"]
    assert not live_on_gap, f"live account(s) {live_on_gap} sit on a known amend gap"


def test_guard_can_find_a_positive():
    """The probe is not vacuous: a live account on a gap integration, and a
    prop account whose adapter does not override modify_bracket, both FAIL."""
    platforms = _platforms()
    assert amend_path_for("x", {"exchange": "oanda", "mode": "live"}, platforms) is None
    assert amend_path_for("x", {"exchange": "newbroker", "mode": "live"}, platforms) is None
    assert amend_path_for("nope", {"exchange": "breakout", "account_class": "prop"}, platforms) is None
    assert amend_path_for("bybit_2", {"exchange": "bybit"}, platforms)[0] == "modify_open_order"
    assert amend_path_for("alpaca_live", {"exchange": "alpaca"}, platforms)[0] == "modify_open_order"
