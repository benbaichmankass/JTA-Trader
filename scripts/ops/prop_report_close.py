#!/usr/bin/env python3
"""Journal the CLOSE of ONE open prop position through the sanctioned ingest path.

Run by the ``prop-report-close`` system-action (Tier 2) on the live VM.
DRY-RUN by default: prints the ticket / open-fill rows as they are and the close
row as it would be written. ``--apply`` takes an SQLite backup of the journal
first, then calls ``src.prop.prop_report.ingest_report`` (the same chokepoint
``POST /api/bot/prop/report`` uses) with a ``status=closed`` fill report.

Why it exists (2026-10-12): breakout_2 SOLUSDT long (prop_fills row 107, ticket
prop-manual-903de9527c23) was closed on the Breakout terminal but the journal still
listed it open. The Streamlit report form is retired, the SPA has no form, and no
system-action journaled a prop close.

Exit price is OPTIONAL. Absent -> the close row carries ``exit_price`` NULL,
``pnl`` NULL and ``provenance: UNVERIFIED`` (the overview counts it under
``closed_unpriced``); nothing is guessed. Present -> ``pnl`` is the GROSS
(entry/exit/qty, before fees) figure, ``provenance: ESTIMATED``.

``--from-placed`` (opt-in, LIVE-SILENCE-DIAG 2026-10-13): also accept a ``placed``
fill row as the row being closed, when the ticket itself is ``placed``. The case:
breakout_2 ETHUSDT short ``prop-manual-762f959676fd`` was journaled ``placed``
(UNVERIFIED, go-token redeemed, phone never confirmed), filled and stopped out on
the terminal, and the phone's clean Positions read then showed the account flat.
``fill_inference`` treats a flat clean read as "not filled", so the row stays
``placed`` for ever, and ``placed`` blocks every later same-key ticket with no
time window (``breakout_executor`` reticket guard); supersede needs a resting
order, which no longer exists. Without the flag a ``placed`` row is refused as
before: closing the record of an order that is still resting would hide its fill.

Refused (exit 3, nothing written), fail-closed:
  * ``account`` is not configured in ``config/prop_platforms.yaml``;
  * the ticket is missing or belongs to another account;
  * the ticket has no ``open``/``filled`` fill row (nor, with ``--from-placed``, a
    ``placed`` row on a ``placed`` ticket), or already has a ``closed`` one;
  * a NEWER fill row exists for the same position key (the open row is stale);
  * ``exit_price`` is not a positive number, ``closed_at`` is not ISO-8601.

The close notification (push + Telegram) is suppressed: this is journal repair
after the fact, not a live trade event. The row stays visible in the audit.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

OPEN_STATUSES = ("open", "filled")
PLACED_STATUS = "placed"
SOURCE = "prop_report_close_action"


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


def _parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dict(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(r) if r is not None else None


def _canon_dir(d: Any) -> str:
    from src.prop.prop_position_identity import canonical_direction

    return canonical_direction(d)


def plan(conn: sqlite3.Connection, *, account_id: str, ticket_id: str,
         exit_price: Optional[str], closed_at: Optional[str], reason: str,
         accounts: Set[str], now: datetime, from_placed: bool = False) -> Dict[str, Any]:
    """The decision, without writing: ``{"ok", "why", "ticket", "open_fill", "report"}``."""
    out: Dict[str, Any] = {"ok": False, "account_id": account_id, "ticket_id": ticket_id,
                           "ticket": None, "open_fill": None, "report": None}
    if account_id not in accounts:
        out["why"] = f"{account_id} is not a configured prop account (config/prop_platforms.yaml)"
        return out
    px: Optional[float] = None
    if exit_price not in (None, ""):
        try:
            px = float(exit_price)
        except (TypeError, ValueError):
            px = None
        if px is None or not px > 0 or px != px or px == float("inf"):
            out["why"] = f"exit_price {exit_price!r} must be a positive number"
            return out
    closed_dt = now
    if closed_at not in (None, ""):
        closed_dt = _parse_ts(closed_at)
        if closed_dt is None:
            out["why"] = f"closed_at {closed_at!r} is not ISO-8601"
            return out
    tk = _dict(conn.execute(
        "SELECT ticket_id, account_id, symbol, direction, status FROM prop_tickets WHERE ticket_id = ?",
        (ticket_id,)).fetchone())
    out["ticket"] = tk
    if tk is None:
        out["why"] = "ticket not found"
        return out
    if tk["account_id"] != account_id:
        out["why"] = f"ticket belongs to {tk['account_id']}, not {account_id}"
        return out
    fills = [dict(r) for r in conn.execute(
        "SELECT * FROM prop_fills WHERE account_id = ? AND ticket_id = ? ORDER BY id", (account_id, ticket_id))]
    if any(str(f.get("status") or "").lower() == "closed" for f in fills):
        out["why"] = "ticket already has a closed prop_fills row -- already closed"
        return out
    opens = [f for f in fills if str(f.get("status") or "").lower() in OPEN_STATUSES]
    if not opens and from_placed and str(tk.get("status") or "").lower() == PLACED_STATUS:
        opens = [f for f in fills if str(f.get("status") or "").lower() == PLACED_STATUS]
    if not opens:
        out["why"] = ("no open/filled prop_fills row references this ticket "
                      f"(ticket status {tk['status']!r}, {len(fills)} fill row(s)) -- nothing to close")
        return out
    of = opens[-1]
    out["open_fill"] = of
    key_dir = _canon_dir(of.get("direction"))
    newer = [dict(r) for r in conn.execute(
        "SELECT id, ticket_id, status, direction FROM prop_fills WHERE account_id = ? AND symbol = ? AND id > ?",
        (account_id, of.get("symbol"), of["id"])) if _canon_dir(r["direction"]) == key_dir]
    if newer:
        out["why"] = (f"newer fill row(s) {[n['id'] for n in newer]} exist for the same position key; "
                      f"fill {of['id']} is not the position's latest state -- refused")
        return out
    qty, entry = of.get("qty"), of.get("entry_price")
    report: Dict[str, Any] = {
        "kind": "fill", "status": "closed", "account_id": account_id, "ticket_id": ticket_id,
        "symbol": of.get("symbol"), "direction": of.get("direction"), "qty": qty,
        "entry_price": entry, "exit_price": px, "pnl": None, "opened_at": of.get("opened_at"),
        "closed_at": closed_dt.isoformat(), "source": SOURCE,
        "provenance": "UNVERIFIED", "reason": reason or "closed on the terminal; journaled by prop-report-close",
    }
    if px is not None and isinstance(qty, (int, float)) and isinstance(entry, (int, float)):
        sign = -1.0 if _canon_dir(of.get("direction")) == "short" else 1.0
        report["pnl"] = round((px - entry) * qty * sign, 4)
        report["provenance"] = "ESTIMATED"
        report["pnl_basis"] = "gross: (exit-entry)*qty, before fees/funding"
    out["report"] = report
    out["ok"] = True
    out["why"] = f"fill {of['id']} ({of.get('status')}) -> closed" + (" (exit unknown)" if px is None else "")
    return out


def _backup(db_path: str) -> str:
    dest = f"{db_path}.bak-prop-report-close-{int(time.time())}"
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
    """Journal the close via ``ingest_report`` (notification suppressed); return the rows after."""
    os.environ["TRADE_JOURNAL_DB"] = db_path  # prop_journal resolves its DB from this
    from src.prop.prop_report import ingest_report

    with mock.patch("src.prop.breakout_notify.emit_prop_fill",
                    return_value={"push": False, "telegram": False}):
        res = ingest_report(dict(decision["report"]))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        after = {
            "ingest": res,
            "close_fill": _dict(conn.execute("SELECT * FROM prop_fills WHERE id = ?", (res.get("id"),)).fetchone()),
            "ticket": _dict(conn.execute(
                "SELECT ticket_id, account_id, status FROM prop_tickets WHERE ticket_id = ?",
                (decision["ticket_id"],)).fetchone()),
        }
    finally:
        conn.close()
    from src.prop.prop_monitor_pulse import find_open_prop_positions

    still = [p for p in find_open_prop_positions(account_id=decision["account_id"])
             if p.get("ticket_id") == decision["ticket_id"]]
    after["still_listed_open"] = bool(still)
    return after


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--ticket-id", required=True)
    ap.add_argument("--exit-price", default=None)
    ap.add_argument("--closed-at", default=None)
    ap.add_argument("--reason", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from-placed", action="store_true",
                    help="also close a `placed` fill row on a `placed` ticket (filled + closed off-journal)")
    ap.add_argument("--platforms", default=None, help="prop_platforms.yaml (tests)")
    ap.add_argument("--now", default=None, help="ISO time (tests)")
    a = ap.parse_args(argv)

    now = _parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        decision = plan(conn, account_id=a.account, ticket_id=a.ticket_id,
                        exit_price=a.exit_price, closed_at=a.closed_at, reason=a.reason,
                        accounts=configured_accounts(Path(a.platforms) if a.platforms else None), now=now,
                        from_placed=a.from_placed)
    finally:
        conn.close()
    decision["mode"] = "apply" if a.apply else "dry_run"
    if not decision["ok"]:
        print(json.dumps(decision, indent=2, default=str))
        return 3
    if not a.apply:
        decision["after"] = {"would_insert_close_fill": decision["report"],
                             "ticket_status": "closed", "position_listed_open": False}
        print(json.dumps(decision, indent=2, default=str))
        return 0
    decision["backup"] = _backup(a.db)
    decision["after"] = apply(decision, a.db)
    print(json.dumps(decision, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
