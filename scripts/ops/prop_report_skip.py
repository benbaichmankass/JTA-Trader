#!/usr/bin/env python3
"""Journal ONE prop ticket that never became a position as ``skipped``, through the sanctioned ingest path.

Run by the ``prop-report-skip`` system-action (Tier 2) on the live VM.
DRY-RUN by default: prints the ticket and its fill rows as they are, and the
``skipped`` report as it would be sent. ``--apply`` additionally needs
``--confirm <ticket_id>`` echoing the ticket. It takes an SQLite backup of the
journal, then calls ``src.prop.prop_report.ingest_report``, the same chokepoint
``POST /api/bot/prop/report`` uses, with ``{kind: fill, status: skipped}``.
ingest_report moves the ticket to ``skipped``.

Why it exists (2026-11-05, BREAKOUT-UNRECORDED-1101, operator decision
"Approve, via a system action"): breakout_2 ETH long ``prop-manual-8468ab1f682f``
had a live phone submit on 2026-11-04 15:02Z (go-token redeemed) that the phone
never confirmed. The LIMIT at 2379.36 rested unfilled for about 18 h, and the
operator cancelled it at the venue. The journal still read ``placed``, and the
trail kept planning LIVE amends against a position that never existed.
``prop_report_close.py`` writes a CLOSE, which would be wrong because there was
no position. ``prop_ticket_expire.py`` refuses phone accounts. This is the one
honest transition: the ticket was never filled.

Refused (exit 3, nothing written), fail-closed:
  * ``reason`` is empty (the record must say why);
  * ``account`` is not configured in ``config/prop_platforms.yaml``;
  * the ticket is missing or belongs to another account;
  * the ticket status is not ``placed`` or ``emitted`` (a filled, closed,
    skipped or expired ticket is not skippable);
  * any fill row on the ticket is ``open``, ``filled`` or ``closed``. That
    would be a position, and it is the job of ``prop-report-close``;
  * ``--apply`` without ``--confirm`` equal to the ticket id.

The record says only what was reported. Whether the venue was really flat is
the reporter's statement, carried verbatim in ``reason``; this tool reads no
venue. No notification fires: ingest_report sends none for ``skipped``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SKIPPABLE_TICKET_STATUSES = ("placed", "emitted")
POSITION_FILL_STATUSES = ("open", "filled", "closed")
SOURCE = "prop_report_skip_action"


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
        "SELECT ticket_id, account_id, symbol, direction, status FROM prop_tickets WHERE ticket_id = ?",
        (ticket_id,)).fetchone())


def plan(conn: sqlite3.Connection, *, account_id: str, ticket_id: str, reason: str,
         accounts: Set[str]) -> Dict[str, Any]:
    """The decision, without writing: ``{"ok", "why", "ticket", "fills", "report"}``."""
    out: Dict[str, Any] = {"ok": False, "account_id": account_id, "ticket_id": ticket_id,
                           "ticket": None, "fills": [], "report": None}
    reason = (reason or "").strip()
    if not reason:
        out["why"] = "reason is required (the record must say why the ticket never filled)"
        return out
    if account_id not in accounts:
        out["why"] = f"{account_id} is not a configured prop account (config/prop_platforms.yaml)"
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
    if status not in SKIPPABLE_TICKET_STATUSES:
        out["why"] = (f"ticket status {status!r} is not skippable "
                      f"(only {list(SKIPPABLE_TICKET_STATUSES)}); a filled/closed ticket is a position")
        return out
    fills = [dict(r) for r in conn.execute(
        "SELECT id, status, qty, entry_price, reason, reported_at FROM prop_fills "
        "WHERE account_id = ? AND ticket_id = ? ORDER BY id", (account_id, ticket_id))]
    out["fills"] = fills
    pos = [f["id"] for f in fills if str(f.get("status") or "").lower() in POSITION_FILL_STATUSES]
    if pos:
        out["why"] = (f"fill row(s) {pos} are open/filled/closed -- that is a position; "
                      "use prop-report-close, not skip")
        return out
    out["report"] = {
        "kind": "fill", "status": "skipped", "account_id": account_id, "ticket_id": ticket_id,
        "symbol": tk.get("symbol"), "direction": tk.get("direction"),
        "reason": reason, "source": SOURCE, "provenance": "UNVERIFIED",
    }
    out["ok"] = True
    out["why"] = f"ticket {status} -> skipped ({len(fills)} non-position fill row(s))"
    return out

def _take_backup():
    """The shared pre-APPLY backup with per-tag retention (scripts/ops/journal_backup.py)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.ops.journal_backup import take_backup
    return take_backup


def _backup(db_path: str) -> str:
    """Pre-APPLY copy to <db>.bak-prop-report-skip-<stamp>; keeps only the newest per tag (journal_backup.py)."""
    return _take_backup()(db_path, "prop-report-skip", method="online", stamp_style="epoch")


def apply(decision: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    """Send the ``skipped`` report through ``ingest_report``; return the response and the ticket after."""
    os.environ["TRADE_JOURNAL_DB"] = db_path  # prop_journal resolves its DB from this
    from src.prop.prop_report import ingest_report

    res = ingest_report(dict(decision["report"]))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "ingest": res,
            "skip_fill": _dict(conn.execute("SELECT * FROM prop_fills WHERE id = ?", (res.get("id"),)).fetchone()),
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
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="", help="must equal --ticket-id for --apply")
    ap.add_argument("--platforms", default=None, help="prop_platforms.yaml (tests)")
    a = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        decision = plan(conn, account_id=a.account, ticket_id=a.ticket_id, reason=a.reason,
                        accounts=configured_accounts(Path(a.platforms) if a.platforms else None))
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
        decision["after"] = {"would_ingest": decision["report"], "ticket_status": "skipped"}
        print(json.dumps(decision, indent=2, default=str))
        return 0
    decision["backup"] = _backup(a.db)
    decision["after"] = apply(decision, a.db)
    print(json.dumps(decision, indent=2, default=str))
    return 0 if (decision["after"].get("ticket") or {}).get("status") == "skipped" else 4


if __name__ == "__main__":
    sys.exit(main())
