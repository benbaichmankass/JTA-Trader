#!/usr/bin/env python3
# wiring: system-action `set-bybit-collateral-switch` (scripts/ops/bybit_set_collateral_switch_action.sh).
"""Read — and with ``--apply``, SET — a coin's collateral switch on a Bybit DEMO account.

Lane BYBIT1-AVAILABLE-USD-ZERO (2026-10-28). Measured on bybit_1: the demo wallet
holds BTC and ETH with ``collateralSwitch=false``, so they count in
``totalEquity`` but NOT in ``totalMarginBalance``, and available margin is a
fraction of what the equity suggests. Turning the switch ON is the operator's
decision (2026-10-28 popup, "Turn collateral ON for BTC+ETH"); nothing in the
repo could perform it until this script.

Calls Bybit v5 ``POST /v5/account/set-collateral-switch`` (pybit
``set_collateral_switch(coin=, collateralSwitch="ON"|"OFF")``).

REFUSALS BEFORE ANY MUTATION:
  * the account must exist, be ``exchange: bybit``, ``demo: true`` AND
    ``account_class: paper``. A real-money account (bybit_2, bybit_portfolio...)
    is refused by name; this action cannot touch real money, and "the account
    looks like a demo" is not inferred from its id.
  * ``--coin`` must be on a small allowlist; ``--switch`` must be ON or OFF.
  * ``--confirm-account`` must echo ``--account`` for ``--apply``.

THE RE-READ IS THE VERIFICATION. ``--apply`` re-reads the coin's
``collateralSwitch`` afterwards and exits 5 (``switch_unverified``) unless it now
equals the request, so a silent venue no-op cannot report success.

⚠️ NO DOLLAR FIGURES ARE PRINTED. system-actions posts this script's whole
output as an issue comment, and this repository is public. The before/after
balances are the point of the exercise, so they are read where they are private:
``scripts/ops/diag_fetch.sh 'broker_account_status?account_id=<id>'``
(``margin_fields.totalMarginBalance`` / ``totalAvailableBalance``) before and
after. This script reports only the switch state and whether each figure went
up, down or stayed (``increased``/``decreased``/``unchanged``/``unreadable``).

Revert: rerun with ``--switch OFF`` (same account/coin).

Usage:
    python3 scripts/ops/bybit_set_collateral_switch.py --account bybit_1 --coin BTC --switch ON
    python3 scripts/ops/bybit_set_collateral_switch.py --account bybit_1 --coin BTC --switch ON \
        --confirm-account bybit_1 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

ALLOWED_COINS = ("BTC", "ETH")
SWITCHES = ("ON", "OFF")


def _fnum(v: Any) -> Optional[float]:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _account_cfg(account_id: str) -> Optional[Dict[str, Any]]:
    from src.units.ui.data_loaders import list_accounts
    for acc in list_accounts() or []:
        if str(acc.get("id") or acc.get("account_id")) == account_id:
            return acc
    return None


def demo_refusal(cfg: Dict[str, Any]) -> Optional[str]:
    """Reason this account may NOT be mutated, or None if it is a demo account."""
    if str(cfg.get("exchange", "")).lower() != "bybit":
        return f"exchange is {cfg.get('exchange')!r}, not bybit"
    if str(cfg.get("demo", "false")).strip().lower() not in ("true", "1", "yes"):
        return "account is not demo: true (real-money accounts are refused)"
    if str(cfg.get("account_class", "")).strip().lower() != "paper":
        return f"account_class is {cfg.get('account_class')!r}, not 'paper'"
    return None


def read_wallet(client, coin: str) -> Dict[str, Any]:
    """Coin switch state + the two margin figures (kept internal, never printed)."""
    try:
        resp = client.get_wallet_balance(accountType="UNIFIED") or {}
    except Exception as exc:  # noqa: BLE001 — a failed read is a STATE
        return {"read_state": "error", "error": f"{type(exc).__name__}: {exc}"}
    lst = (resp.get("result") or {}).get("list") or []
    if not lst:
        return {"read_state": "error", "error": "wallet read carried no account object"}
    acct = lst[0] or {}
    entry = next((c for c in acct.get("coin") or [] if c.get("coin") == coin), None)
    if entry is None:
        return {"read_state": "coin_absent", "error": None}
    raw = entry.get("collateralSwitch")
    return {
        "read_state": "read",
        "error": None,
        "collateral_switch": bool(raw) if isinstance(raw, bool) else str(raw).strip().lower() == "true",
        "margin_balance": _fnum(acct.get("totalMarginBalance")),
        "available": _fnum(acct.get("totalAvailableBalance")),
    }


def _direction(before: Optional[float], after: Optional[float]) -> str:
    if before is None or after is None:
        return "unreadable"
    if after > before:
        return "increased"
    if after < before:
        return "decreased"
    return "unchanged"


def run(a: argparse.Namespace, cfg: Optional[Dict[str, Any]], client) -> "tuple[int, Dict[str, Any]]":
    out: Dict[str, Any] = {"status": "collateral_switch", "account": a.account, "coin": a.coin,
                           "requested_switch": a.switch, "applied": False, "switch_verified": None}
    if cfg is None:
        out.update(action="abort_unknown_account", detail=f"no account {a.account!r} in accounts.yaml")
        return 2, out
    why = demo_refusal(cfg)
    if why:
        out.update(action="abort_not_demo", detail=why)
        return 2, out
    if a.coin not in ALLOWED_COINS or a.switch not in SWITCHES:
        out.update(action="abort_bad_args",
                   detail=f"coin must be one of {ALLOWED_COINS} and switch one of {SWITCHES}")
        return 2, out
    if client is None:
        out.update(action="abort_no_client", detail="bybit_client_for returned None (missing creds?)")
        return 2, out

    want = a.switch == "ON"
    before = read_wallet(client, a.coin)
    out["before"] = {"read_state": before["read_state"], "collateral_switch": before.get("collateral_switch"),
                     "error": before.get("error")}
    if not a.apply:
        out.update(action="report_only",
                   detail="dry-run. Re-run with --confirm-account and --apply to set the switch.")
        return 0, out
    if a.confirm_account != a.account:
        out.update(action="abort_unconfirmed", detail="--confirm-account must equal --account for --apply")
        return 2, out
    if before["read_state"] != "read":
        out.update(action="abort_unreadable",
                   detail=f"read_state={before['read_state']!r} — refusing to change a switch we could not read")
        return 3, out
    if before["collateral_switch"] is want:
        out.update(action="noop_already_set", switch_verified=True, detail=f"already {a.switch}")
        return 0, out

    try:
        resp = client.set_collateral_switch(coin=a.coin, collateralSwitch=a.switch)
        out["response"] = {"retCode": (resp or {}).get("retCode"), "retMsg": (resp or {}).get("retMsg")}
    except Exception as exc:  # noqa: BLE001
        out.update(action="switch_failed", detail=f"{type(exc).__name__}: {exc}")
        return 4, out

    out["applied"] = True
    after = read_wallet(client, a.coin)
    out["after"] = {"read_state": after["read_state"], "collateral_switch": after.get("collateral_switch"),
                    "error": after.get("error")}
    out["margin_balance"] = _direction(before.get("margin_balance"), after.get("margin_balance"))
    out["available"] = _direction(before.get("available"), after.get("available"))
    out["switch_verified"] = after["read_state"] == "read" and after["collateral_switch"] is want
    out["action"] = "switched" if out["switch_verified"] else "switch_unverified"
    if not out["switch_verified"]:
        out["detail"] = "the venue accepted the call but the re-read does NOT show the requested switch — treat as NOT set"
    return (0 if out["switch_verified"] else 5), out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", required=True)
    ap.add_argument("--coin", required=True)
    ap.add_argument("--switch", required=True)
    ap.add_argument("--confirm-account", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    cfg = _account_cfg(a.account)
    client = None
    if cfg is not None and demo_refusal(cfg) is None:
        from src.units.accounts.clients import bybit_client_for
        client = bybit_client_for(cfg)
    code, out = run(a, cfg, client)
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
