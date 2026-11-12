#!/usr/bin/env python3
"""Journal ONE prop ticket as an OPEN position (filled), through the sanctioned ingest path.

Run by the ``prop-report-open`` system-action (Tier 2) on the live VM.
DRY-RUN by default: prints the ticket, its fill rows, and the ``open`` report as
it would be sent. ``--apply`` additionally needs ``--confirm <ticket_id>``. It
takes an SQLite backup of the journal, then calls
``src.prop.prop_report.ingest_report`` (the chokepoint ``POST /api/bot/prop/report``
uses) with ``{kind: fill, status: open}`` and the ticket's own id, symbol,
direction, qty, SL and TP. ingest_report journals the open fill and moves the
ticket to ``filled``, so the prop trail / stop / target management treats it as
a live position again.

Why it exists (2026-11-11, PHONE-LIVE-ACCOUNT-FEED): breakout_2 ETH long
``prop-manual-c54b2229aa1c`` was swept to ``skipped`` by the stale-entry cancel,
which found no resting order -- because the order had FILLED. The phone could not
read the Positions tab (no_table), so the fill was never reported. The operator
confirmed it in chat ~21:20Z: "There is an open ETH long trade." Neither
``prop-report-close`` (a close) nor ``prop-report-skip`` (never filled) is the
honest transition; this is.

Refused (exit 3, nothing written), fail-closed:
  * ``reason`` is empty (the record must say who confirmed the position and how);
  * ``account`` is not configured in ``config/prop_platforms.yaml``;
  * the ticket is missing or belongs to another account;
  * the ticket is already ``filled`` or ``closed`` (nothing to record);
  * the ticket already has an ``open``/``filled``/``closed`` fill row;
  * another OPEN fill already holds this account + symbol + direction (a second
    one would double-count open risk -- report it on that row instead);
  * ``--entry-price`` given but not a positive number;
  * ``--apply`` without ``--confirm`` equal to the ticket id.

The record says only what was reported: the venue is not read here. Without
``--entry-price`` the fill carries the TICKET's planned entry and says so in
``entry_price_source`` (the real fill price was not read). No notification is
suppressed: ingest_report fires its usual prop_fill message.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ALREADY_POSITION_TICKET_STATUSES = ("filled", "closed")
POSITION_FILL_STATUSES = ("open", "filled", "closed")
OPEN_FILL_STATUSES = ("open", "filled")
SOURCE = "prop_report_open_action"


def configured_accounts(platforms_path: Optional[Path] = None) -> Set[str]:
    """Every prop account in ``prop_platforms.yaml`` (``accounts`` + ``phone_accounts``).
    Unreadable file -> empty set, so every account is refused rather than guessed."""
    import yaml

    from src.prop.platform import PLATFORMS_PATH

    p = Path(platforms_path) if platforms_path else PLATFORMS_PATH
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 — refuse everything rather than guess
        return set()
    out: Set[str] = set()
    for section in ("accounts", "phone_accounts"):
        out |= {str(a) for a in (data.get(section) or {})}
    return out


def _dict(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(r) if r is not None else None


def _ticket(conn: sqlite3.Connection, ticket_id: str) -> Optional[Dict[str, Any]]:
    return _dict(conn.execute(
        "SELECT ticket_id, account_id, symbol, direction, status, entry, sl, tp, qty, order_package_id "
        "FROM prop_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone())


def _pos(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def plan(conn: sqlite3.Connection, *, account_id: str, ticket_id: str, reason: str,
         accounts: Set[str], entry_price: Optional[str] = None,
         opened_at: Optional[str] = None) -> Dict[str, Any]:
    """The decision, without writing: ``{"ok", "why", "ticket", "fills", "report"}``."""
    out: Dict[str, Any] = {"ok": False, "account_id": account_id, "ticket_id": ticket_id,
                           "ticket": None, "fills": [], "report": None}
    reason = (reason or "").strip()
    if not reason:
        out["why"] = "reason is required (who confirmed the position is open, and how)"
        return out
    if account_id not in accounts:
        out["why"] = f"{account_id} is not a configured prop account (config/prop_platforms.yaml)"
        return out
    ep = None
    if entry_price not in (None, ""):
        ep = _pos(entry_price)
        if ep is None:
            out["why"] = f"entry_price {entry_price!r} is not a positive number"
            return out
    tk = _ticket(conn, ticket_id)
    out["ticket"] = tk
    if tk is None:
        out["why"] = "ticket not found"
        return out
    if tk["account_id"] != account_id:
        out["why"] = f"ticket belongs to {tk['account_id']}, not {account_id}"
        return out
    status = str(tk.get("status") or "").lower()
    if status in ALREADY_POSITION_TICKET_STATUSES:
        out["why"] = f"ticket is already {status!r}: nothing to record"
        return out
    fills = [dict(r) for r in conn.execute(
        "SELECT id, status, qty, entry_price, reason, reported_at FROM prop_fills "
        "WHERE account_id = ? AND ticket_id = ? ORDER BY id", (account_id, ticket_id))]
    out["fills"] = fills
    pos = [f["id"] for f in fills if str(f.get("status") or "").lower() in POSITION_FILL_STATUSES]
    if pos:
        out["why"] = f"fill row(s) {pos} on this ticket are already open/filled/closed"
        return out
    # the journal's own open-position rule: the NEWEST fill per (account, symbol, direction) decides
    newest = _dict(conn.execute(
        "SELECT id, ticket_id, status FROM prop_fills WHERE account_id = ? AND UPPER(symbol) = UPPER(?) "
        "AND LOWER(direction) = LOWER(?) ORDER BY id DESC LIMIT 1",
        (account_id, tk["symbol"], tk["direction"])).fetchone())
    if newest and str(newest.get("status") or "").lower() in OPEN_FILL_STATUSES \
            and newest.get("ticket_id") != ticket_id:
        out["why"] = (f"fill {newest['id']} (ticket {newest.get('ticket_id')}) already holds {account_id} "
                      f"{tk['symbol']} {tk['direction']} open -- a second would double-count open risk")
        return out
    report = {
        "kind": "fill", "status": "open", "account_id": account_id, "ticket_id": ticket_id,
        "symbol": tk.get("symbol"), "direction": tk.get("direction"),
        "qty": tk.get("qty"), "sl": tk.get("sl"), "tp": tk.get("tp"),
        "entry_price": ep if ep is not None else tk.get("entry"),
        "entry_price_source": "reported" if ep is not None else "ticket_planned_entry (fill price not read)",
        "reason": reason, "source": SOURCE, "provenance": "UNVERIFIED",
    }
    if opened_at:
        report["opened_at"] = opened_at
    out["report"] = report
    out["ok"] = True
    out["why"] = f"ticket {status} -> filled (open fill journaled; {len(fills)} non-position fill row(s))"
    return out


def _backup(db_path: str) -> str:
    dest = f"{db_path}.bak-prop-report-open-{int(time.time())}"
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def apply(decision: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    """Send the ``open`` report through ``ingest_report``; return the response and the ticket after."""
    os.environ["TRADE_JOURNAL_DB"] = db_path  # prop_journal resolves its DB from this
    from src.prop.prop_report import ingest_report

    res = ingest_report(dict(decision["report"]))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "ingest": res,
            "open_fill": _dict(conn.execute("SELECT * FROM prop_fills WHERE id = ?", (res.get("id"),)).fetchone()),
            "ticket": _ticket(conn, decision["ticket_id"]),
        }
    finally:
        conn.close()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--ticket-id", required=True)
    ap.add_argument("--reason", default="")
    ap.add_argument("--entry-price", default="")
    ap.add_argument("--opened-at", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="", help="must equal --ticket-id for --apply")
    ap.add_argument("--platforms", default=None, help="prop_platforms.yaml (tests)")
    a = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        decision = plan(conn, account_id=a.account, ticket_id=a.ticket_id, reason=a.reason,
                        accounts=configured_accounts(Path(a.platforms) if a.platforms else None),
                        entry_price=a.entry_price or None, opened_at=a.opened_at or None)
    finally:
        conn.close()
    decision["mode"] = "apply" if a.apply else "dry_run"
    decision["before"] = decision.get("ticket")
    if decision["ok"] and a.apply and a.confirm != a.ticket_id:
        decision["ok"] = False
        decision["why"] = f"apply needs confirm: {a.ticket_id} (got {a.confirm!r})"
    if not decision["ok"]:
        print(json.dumps(decision, indent=2, default=str))
        return 3
    if not a.apply:
        decision["after"] = {"would_ingest": decision["report"], "ticket_status": "filled"}
        print(json.dumps(decision, indent=2, default=str))
        return 0
    decision["backup"] = _backup(a.db)
    decision["after"] = apply(decision, a.db)
    print(json.dumps(decision, indent=2, default=str))
    return 0 if (decision["after"].get("ticket") or {}).get("status") == "filled" else 4


if __name__ == "__main__":
    sys.exit(main())
