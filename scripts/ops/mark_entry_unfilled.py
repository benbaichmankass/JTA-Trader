"""Relabel named CLOSED trades whose entry order never filled: ``entry_unfilled`` + an explicit
``unmeasured`` PnL marker.

WHY THIS EXISTS. PR #27537 (deployed 2026-11-20 01:07Z) makes the position-snapshot reconciler close a
row whose entry order ended at the venue without filling as ``exit_reason='entry_unfilled'``. Rows that
closed BEFORE that deploy still carry the generic ``exchange_flat_reconciled`` (or the watchdog's
``stuck_strategy_watchdog``) with ``pnl`` NULL. The mechanics grader then reads them as close faults, and
db-integrity INV-2 flags a closed row with a NULL PnL and no declaration. The measured case is
alpaca_options_paper SLV trade 8034 (paper): a DAY mleg limit entry that expired unfilled, closed
2026-11-19 21:02Z. This one-shot applies the same label to those rows.

⚠️ TARGETS ARE NAMED, AND THE VENUE MUST AGREE. The caller passes trade ids. For each one the script
asks the venue about the row's own entry order (``clients.account_entry_order_unfilled``, the same
fail-closed read #27537 uses). Only ``True`` passes: terminal (canceled / expired / rejected) with
``filled_qty`` exactly 0. Any fill, an unreadable or unknown order, an unsupported venue, or an ambiguous
status REFUSES that id, and if ANY id is refused nothing is written at all.

What it writes, per row (one transaction, after an online SQLite backup beside the DB):
  * ``trades.exit_reason = 'entry_unfilled'``;
  * notes: ``pnl_source = 'unmeasured'`` (src/runtime/provenance.UNMEASURED_MARKER, the ONE marker INV-2
    accepts) and ``unmeasured_reason = 'entry_unfilled'``; the prior label under
    ``pre_mark_exit_reason``; who, when, why and the venue verdict;
  * the linked package's ``close_reason`` from the prior label to ``entry_unfilled`` (only when it equals
    the prior label).
It touches NO monetary field: pnl stays NULL, honestly unmeasured, because there was no position.

Refuses: a missing id, a backtest row, a row that is not ``status='closed'``, a row with a non-NULL pnl,
and a row whose exit_reason is not one of the flat-detector labels. Idempotent: a row already labelled
``entry_unfilled`` is skipped. Reversible per row from ``pre_mark_exit_reason``.

Usage on the VM:
    python3 scripts/ops/mark_entry_unfilled.py --trade-ids 8034 --reason "..."           # dry-run
    python3 scripts/ops/mark_entry_unfilled.py --trade-ids 8034 --reason "..." --apply
    python3 scripts/ops/mark_entry_unfilled.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

EXIT_REASON = "entry_unfilled"
#: The flat-detector labels a pre-#27537 unfilled-entry close can carry. Anything else is a real exit.
RELABELABLE = ("exchange_flat_reconciled", "stuck_strategy_watchdog")
UNMEASURED = "unmeasured"  # src.runtime.provenance.UNMEASURED_MARKER (pinned by the self-test)
#: Kept through the 500-char notes cap so the record stays reversible and the INV-2 marker survives.
PROTECTED = ("pnl_source", "unmeasured_reason", "pre_mark_exit_reason", "entry_unfilled_marked_at",
             "entry_unfilled_venue", "closed_at", "closed_by")

VenueRead = Callable[[dict[str, Any], str], bool | None]


def _db_path() -> str:
    from src.utils.paths import trade_journal_db_path  # the ONE sanctioned resolver
    return str(trade_journal_db_path())


def _dump_notes(notes: dict[str, Any]) -> str:
    try:
        from src.utils.json_notes import _DEFAULT_PROTECTED, dump_capped
        return dump_capped(notes, 500, protected=set(_DEFAULT_PROTECTED) | set(PROTECTED))
    except Exception:  # noqa: BLE001 -- outside the repo only; named, not implicit
        return json.dumps(notes)


def _load_notes(raw: Any) -> dict[str, Any]:
    try:
        n = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {"_original_notes": raw}
    return n if isinstance(n, dict) else {"_original_notes": raw}


def _venue_read_default(cfg: dict[str, Any], order_id: str) -> bool | None:
    from src.units.accounts.clients import account_entry_order_unfilled
    return account_entry_order_unfilled(cfg, order_id)


def _accounts_default() -> dict[str, dict[str, Any]]:
    from src.config.accounts_loader import load_accounts_dict
    return load_accounts_dict() or {}


def plan(conn: sqlite3.Connection, trade_ids: list[int], reason: str, *,
         accounts: dict[str, dict[str, Any]], venue_read: VenueRead
         ) -> tuple[list[dict[str, Any]], list[str], list[int]]:
    """``(updates, refusals, skipped)``. A non-empty refusal list means write NOTHING."""
    conn.row_factory = sqlite3.Row
    updates: list[dict[str, Any]] = []
    refusals: list[str] = []
    skipped: list[int] = []
    now = datetime.now(timezone.utc).isoformat()
    for tid in trade_ids:
        r = conn.execute(
            "SELECT id, account_id, symbol, status, exit_reason, pnl, notes, broker_order_id, "
            "order_package_id, COALESCE(is_backtest, 0) AS bt FROM trades WHERE id = ?", (tid,)).fetchone()
        if r is None:
            refusals.append(f"{tid}: no such trade")
            continue
        if r["bt"]:
            refusals.append(f"{tid}: backtest row")
            continue
        if r["exit_reason"] == EXIT_REASON:
            skipped.append(tid)
            continue
        if r["status"] != "closed":
            refusals.append(f"{tid}: status {r['status']!r}, not closed")
            continue
        if r["pnl"] is not None:
            refusals.append(f"{tid}: pnl is {r['pnl']!r}; a row with a PnL had a position")
            continue
        if r["exit_reason"] not in RELABELABLE:
            refusals.append(f"{tid}: exit_reason {r['exit_reason']!r} is not a flat-detector label {RELABELABLE}")
            continue
        oid = str(r["broker_order_id"] or "").strip()
        cfg = accounts.get(str(r["account_id"] or ""))
        if not oid or oid.startswith(("rejected-", "dry-")):
            refusals.append(f"{tid}: no real entry order id ({oid!r})")
            continue
        if not isinstance(cfg, dict):
            refusals.append(f"{tid}: account {r['account_id']!r} not in accounts.yaml")
            continue
        try:
            verdict = venue_read(dict(cfg, account_id=r["account_id"]), oid)
        except Exception as exc:  # noqa: BLE001 -- fail closed
            verdict = None
            refusals.append(f"{tid}: venue read raised {type(exc).__name__}: {exc}")
            continue
        if verdict is not True:
            refusals.append(f"{tid}: venue does not confirm an unfilled terminal entry order {oid} "
                            f"(read {verdict!r}: False = it filled, None = could not tell)")
            continue
        notes = _load_notes(r["notes"])
        notes.update({
            "pnl_source": UNMEASURED,
            "unmeasured_reason": EXIT_REASON,
            "pre_mark_exit_reason": r["exit_reason"],
            "entry_unfilled_marked_at": now,
            "entry_unfilled_venue": f"order {oid}: terminal, filled_qty 0",
            "entry_unfilled_reason": reason,
        })
        updates.append({"id": tid, "prior": r["exit_reason"], "package": r["order_package_id"],
                        "notes": _dump_notes(notes)})
    return updates, refusals, skipped


def backup(db_path: str) -> str:
    """Online SQLite backup beside the DB (consistent under WAL, unlike a file copy)."""
    dest = f"{db_path}.bak-mark-entry-unfilled-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    src = sqlite3.connect(db_path)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dest


def apply(conn: sqlite3.Connection, updates: list[dict[str, Any]]) -> int:
    """One transaction; any failure rolls back everything."""
    with conn:
        for u in updates:
            conn.execute("UPDATE trades SET exit_reason = ?, notes = ? WHERE id = ? AND exit_reason = ?",
                         (EXIT_REASON, u["notes"], u["id"], u["prior"]))
            if u["package"]:
                conn.execute("UPDATE order_packages SET close_reason = ? "
                             "WHERE order_package_id = ? AND close_reason = ?",
                             (EXIT_REASON, u["package"], u["prior"]))
    return len(updates)


def _self_test() -> int:
    import tempfile
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok = ok and cond
        print(("  PASS  " if cond else "  FAIL  ") + label)

    from src.runtime.provenance import UNMEASURED_MARKER
    ck("the marker is provenance.UNMEASURED_MARKER", UNMEASURED == UNMEASURED_MARKER)
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "j.db")
        c = sqlite3.connect(db)
        # data-wiring: throwaway self-test fixture mirroring the canonical trade_journal.db columns
        # this script reads; no new table is created in any real store.
        c.executescript(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, status TEXT,"
            " exit_reason TEXT, pnl REAL, notes TEXT, broker_order_id TEXT, order_package_id TEXT,"
            " is_backtest INTEGER);"
            "CREATE TABLE order_packages (order_package_id TEXT, close_reason TEXT);")
        long_note = json.dumps({"closed_at": "x", "closed_by": "position_snapshot_reconciler",
                                "closed_reason": "y" * 600})
        rows = [
            (1, "alpaca_x", "SLV", "closed", "exchange_flat_reconciled", None, long_note, "oid-unfilled", "pkg-1", 0),
            (2, "alpaca_x", "SLV", "closed", "exchange_flat_reconciled", None, "{}", "oid-filled", "pkg-2", 0),
            (3, "alpaca_x", "SLV", "closed", "exchange_flat_reconciled", None, "{}", "oid-unknown", None, 0),
            (4, "alpaca_x", "SLV", "closed", "sl", None, "{}", "oid-unfilled", None, 0),
            (5, "alpaca_x", "SLV", "closed", "exchange_flat_reconciled", 12.5, "{}", "oid-unfilled", None, 0),
            (6, "alpaca_x", "SLV", "open", None, None, "{}", "oid-unfilled", None, 0),
            (7, "alpaca_x", "SLV", "closed", "exchange_flat_reconciled", None, "{}", "rejected-abc", None, 0),
            (8, "alpaca_x", "SLV", "closed", "entry_unfilled", None, "{}", "oid-unfilled", None, 0),
        ]
        c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT INTO order_packages VALUES (?,?)",
                      [("pkg-1", "exchange_flat_reconciled"), ("pkg-2", "exchange_flat_reconciled")])
        c.commit()
        venue = {"oid-unfilled": True, "oid-filled": False, "oid-unknown": None}

        def read(cfg, oid):
            assert cfg.get("account_id") == "alpaca_x"  # the row's own account is what the venue is asked
            return venue.get(oid)
        acc = {"alpaca_x": {"exchange": "alpaca", "mode": "live"}}
        up, ref, _sk = plan(c, [1], "test", accounts=acc, venue_read=read)
        ck("an unfilled terminal entry on a flat-detector close is planned", len(up) == 1 and not ref)
        for tid, why in ((2, "filled"), (3, "could not tell"), (4, "not a flat-detector label"),
                         (5, "had a position"), (6, "not closed"), (7, "no real entry order id"),
                         (99, "no such trade")):
            _u, r, _s = plan(c, [tid], "t", accounts=acc, venue_read=read)
            ck(f"refuses trade {tid} ({why})", bool(r) and why.split()[0] in r[0])
        _u, _r, s = plan(c, [8], "t", accounts=acc, venue_read=read)
        ck("an already-labelled row is skipped, not re-written", s == [8])
        _u, r, _s = plan(c, [1, 2], "t", accounts=acc, venue_read=read)
        ck("one bad id in a batch yields a refusal (the caller writes nothing)", len(r) == 1)
        n = apply(c, up)
        t = c.execute("SELECT exit_reason, pnl, notes FROM trades WHERE id=1").fetchone()
        notes = json.loads(t[2])
        ck("applied: exit_reason entry_unfilled, pnl still NULL", n == 1 and t[0] == EXIT_REASON and t[1] is None)
        ck("the INV-2 marker and the prior label survive the 500-char cap",
           notes.get("pnl_source") == UNMEASURED and notes.get("pre_mark_exit_reason") == "exchange_flat_reconciled"
           and len(t[2]) <= 500)
        ck("the linked package's close_reason follows",
           c.execute("SELECT close_reason FROM order_packages WHERE order_package_id='pkg-1'").fetchone()[0]
           == EXIT_REASON)
        ck("an unrelated package is untouched",
           c.execute("SELECT close_reason FROM order_packages WHERE order_package_id='pkg-2'").fetchone()[0]
           == "exchange_flat_reconciled")
        c.close()
        b = backup(db)
        ck("backup writes a readable copy", sqlite3.connect(b).execute(
            "SELECT exit_reason FROM trades WHERE id=1").fetchone()[0] == EXIT_REASON)
    print("mark-entry-unfilled self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trade-ids", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    try:
        ids = [int(x) for x in a.trade_ids.split(",") if x.strip()]
    except ValueError:
        print("--trade-ids must be digits, comma-separated", file=sys.stderr)
        return 2
    if not ids or not a.reason.strip():
        print("--trade-ids and --reason are both required (targets are named, never derived)", file=sys.stderr)
        return 2
    db = _db_path()
    conn = sqlite3.connect(db, timeout=30)
    try:
        updates, refusals, skipped = plan(conn, ids, a.reason.strip(), accounts=_accounts_default(),
                                          venue_read=_venue_read_default)
        for t in skipped:
            print(f"skip {t}: already {EXIT_REASON}")
        for r in refusals:
            print(f"REFUSE {r}")
        for u in updates:
            print(f"plan {u['id']}: {u['prior']} -> {EXIT_REASON}; notes.pnl_source={UNMEASURED}; "
                  f"package {u['package'] or '-'}")
        if refusals:
            print(f"{len(refusals)} refusal(s): NOTHING written.")
            return 1
        if not a.apply:
            print(f"dry-run: {len(updates)} row(s) would change. Re-run with --apply.")
            return 0
        if not updates:
            print("nothing to do.")
            return 0
        print(f"backup: {backup(db)}")
        print(f"applied: {apply(conn, updates)} row(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
