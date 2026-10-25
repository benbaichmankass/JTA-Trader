#!/usr/bin/env python3
"""Every prop / phone ticket still OPEN while its order package is CLOSED (PHONE-AMEND-REFUSED-1025).

Why. On 2026-10-25 breakout_2's ETH short (prop-manual-2e786ef17c05) was still on the terminal ~20h after its
order package pkg-2c3f338d9477499b closed ``sl_cross``: the strategy had exited, the account had not, and no
read said so in those words. This is that read, over EVERY prop account, from the canonical ticket view
(``GET /api/bot/prop/tickets``, which projects ``order_packages`` enriched by the ``prop_tickets`` sidecar).

Population: the newest ``--limit`` tickets per account, for every ``type: prop`` account in config/accounts.yaml.
An account whose read fails is reported as UNREAD, never as clean. Read-only.

    python3 scripts/ops/check_ticket_package_divergence.py            # exit 1 when any ticket diverges or any read fails
    python3 scripts/ops/check_ticket_package_divergence.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ict-bot.duckdns.org/api/bot/prop/tickets"
OPEN_TICKET = ("placed", "filled")      # the phone/executor reported the order on the venue
CLOSED_PACKAGE = ("closed",)


def prop_accounts(path: Path = ROOT / "config" / "accounts.yaml") -> list[str]:
    accts = (yaml.safe_load(path.read_text()) or {}).get("accounts") or {}
    return sorted(a for a, v in accts.items() if isinstance(v, dict) and str(v.get("type") or "") == "prop")


def divergent(tickets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tickets the venue should still hold while their package says the strategy is out. Pure."""
    out = []
    for t in tickets:
        if str(t.get("status") or "") in OPEN_TICKET and str(t.get("op_status") or "") in CLOSED_PACKAGE:
            tr = t.get("phone_trail") or {}
            out.append({k: t.get(k) for k in ("account_id", "ticket_id", "order_package_id", "strategy", "symbol",
                                              "direction", "status", "op_status", "close_reason", "created_at")}
                       | {"last_amend": tr.get("amend_id"), "amend_status": tr.get("amend_status"),
                          "fails": tr.get("fails")})
    return out


def _fetch(account: str, limit: int) -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"{BASE}?account_id={account}&limit={limit}", timeout=40) as r:
        d = json.load(r)
    return list(d.get("tickets") or [])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows: list[dict[str, Any]] = []
    unread: dict[str, str] = {}
    counted: dict[str, int] = {}
    for acct in prop_accounts():
        try:
            tks = _fetch(acct, a.limit)
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as UNREAD below, never as clean
            unread[acct] = f"{type(exc).__name__}: {str(exc)[:120]}"
            continue
        counted[acct] = len(tks)
        rows.extend(divergent(tks))
    if a.json:
        print(json.dumps({"divergent": rows, "tickets_read": counted, "unread": unread}, indent=1))
    else:
        print(f"tickets read per account: {counted}")
        for acct, why in unread.items():
            print(f"UNREAD {acct}: {why}")
        for r in rows:
            print(f"DIVERGED {r['account_id']} {r['ticket_id']} ({r['order_package_id']}, {r['symbol']} "
                  f"{r['direction']}): ticket {r['status']}, package {r['op_status']} {r['close_reason']}; "
                  f"last amend {r['last_amend']} {r['amend_status']} fails={r['fails']}")
        if not rows and not unread:
            print("no ticket is open while its package is closed")
    return 1 if (rows or unread) else 0


if __name__ == "__main__":
    sys.exit(main())
