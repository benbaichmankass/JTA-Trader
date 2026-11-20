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
#: SHORT values only. Measured on trade 8034 (2026-11-20, issue #27646): protecting two ~64+ char prose
#: keys on top of the reconciler's ~330-char closed_reason pushed the protected set past 500, and
#: dump_capped fell to the bare {"_truncated": true}, dropping the marker itself. Prose stays trimmable.
PROTECTED = ("pnl_source", "unmeasured_reason", "pre_mark_exit_reason", "closed_at", "closed_by")
#: Default-protected keys that are long PROSE: trimmed here rather than allowed to sink the marker.
UNPROTECT = ("closed_reason",)

VenueRead = Callable[[dict[str, Any], str], bool | None]


def _db_path() -> str:
    from src.utils.paths import trade_journal_db_path  # the ONE sanctioned resolver
    return str(trade_journal_db_path())


def _protected() -> set[str]:
    try:
        from src.utils.json_notes import _DEFAULT_PROTECTED
        base = set(_DEFAULT_PROTECTED)
    except Exception:  # noqa: BLE001 -- outside the repo only
        base = set()
    return (base - set(UNPROTECT)) | set(PROTECTED)


def _dump_notes(notes: dict[str, Any]) -> str:
    try:
        from src.utils.json_notes import dump_capped
        return dump_capped(notes, 500, protected=_protected())
    except ImportError:  # outside the repo only; named, not implicit
        return json.dumps(notes)


def _marker_survives(blob: str, prior: str) -> bool:
    """The written notes must carry the INV-2 marker AND the reversal key, or nothing is written."""
    try:
        n = json.loads(blob)
    except (TypeError, ValueError):
        return False
    return (isinstance(n, dict) and n.get("pnl_source") == UNMEASURED
            and n.get("unmeasured_reason") == EXIT_REASON and n.get("pre_mark_exit_reason") == prior)


def _build_notes(raw: Any, prior: str, oid: str, reason: str) -> str:
    notes = _load_notes(raw)
    notes.update({
        "pnl_source": UNMEASURED,
        "unmeasured_reason": EXIT_REASON,
        "pre_mark_exit_reason": prior,
        "entry_unfilled_marked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry_unfilled_venue": f"order {oid[:12]}: terminal, filled_qty 0",
        "entry_unfilled_reason": reason[:120],
    })
    return _dump_notes(notes)


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
        blob = _build_notes(r["notes"], r["exit_reason"], oid, reason)
        if not _marker_survives(blob, r["exit_reason"]):
            refusals.append(f"{tid}: the notes cap would drop the INV-2 marker or the reversal key")
            continue
        updates.append({"id": tid, "prior": r["exit_reason"], "package": r["order_package_id"],
                        "notes": blob})
    return updates, refusals, skipped


def plan_restore(conn: sqlite3.Connection, bak: sqlite3.Connection, trade_ids: list[int], reason: str
                 ) -> tuple[list[dict[str, Any]], list[str], list[int]]:
    """Repair rows ALREADY relabelled entry_unfilled whose notes lost the marker (trade 8034,
    issue #27646): rebuild the notes from the pre-write backup's original blob. Writes notes only.

    Refuses unless the live row is closed, entry_unfilled, pnl NULL, and missing the marker, and
    the backup row is the same trade (same account, broker order id) still carrying a
    flat-detector label with pnl NULL. A row already carrying the marker is skipped.
    """
    conn.row_factory = sqlite3.Row
    bak.row_factory = sqlite3.Row
    updates: list[dict[str, Any]] = []
    refusals: list[str] = []
    skipped: list[int] = []
    q = ("SELECT id, account_id, status, exit_reason, pnl, notes, broker_order_id "
         "FROM trades WHERE id = ?")
    for tid in trade_ids:
        r = conn.execute(q, (tid,)).fetchone()
        b = bak.execute(q, (tid,)).fetchone()
        if r is None or b is None:
            refusals.append(f"{tid}: missing from the {'journal' if r is None else 'backup'}")
            continue
        if r["exit_reason"] != EXIT_REASON or r["status"] != "closed" or r["pnl"] is not None:
            refusals.append(f"{tid}: live row is not a closed, NULL-pnl {EXIT_REASON} row")
            continue
        if _load_notes(r["notes"]).get("pnl_source") == UNMEASURED:
            skipped.append(tid)
            continue
        if (b["account_id"], b["broker_order_id"]) != (r["account_id"], r["broker_order_id"]):
            refusals.append(f"{tid}: backup row is a different trade (account/order id differ)")
            continue
        if b["exit_reason"] not in RELABELABLE or b["pnl"] is not None:
            refusals.append(f"{tid}: backup row carries {b['exit_reason']!r}/pnl {b['pnl']!r}, "
                            "not the pre-write flat-detector state")
            continue
        oid = str(r["broker_order_id"] or "")
        blob = _build_notes(b["notes"], b["exit_reason"], oid, reason)
        if not _marker_survives(blob, b["exit_reason"]):
            refusals.append(f"{tid}: the notes cap would drop the INV-2 marker or the reversal key")
            continue
        updates.append({"id": tid, "notes": blob})
    return updates, refusals, skipped


def apply_restore(conn: sqlite3.Connection, updates: list[dict[str, Any]]) -> int:
    with conn:
        for u in updates:
            conn.execute("UPDATE trades SET notes = ? WHERE id = ? AND exit_reason = ?",
                         (u["notes"], u["id"], EXIT_REASON))
    return len(updates)


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
    ap.add_argument("--db", default="", help="journal path (default: the canonical resolver)")
    ap.add_argument("--restore-notes-from", default="",
                    help="repair mode: rebuild the named rows' notes from this pre-write backup")
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
    db = a.db.strip() or _db_path()
    try:
        # mode=rw never CREATES a file: a wrong path is an error, not a fresh empty journal.
        conn = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=30)
        conn.execute("SELECT 1 FROM trades LIMIT 1")
    except sqlite3.Error as exc:
        print(f"REFUSE: {db} is not a readable trade journal ({exc}); nothing written.", file=sys.stderr)
        return 1
    try:
        if a.restore_notes_from.strip():
            return _run_restore(conn, db, a.restore_notes_from.strip(), ids, a.reason.strip(), a.apply)
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


def _run_restore(conn: sqlite3.Connection, db: str, bak_path: str, ids: list[int], reason: str,
                 do_apply: bool) -> int:
    try:
        bak = sqlite3.connect(f"file:{bak_path}?mode=ro", uri=True, timeout=30)
        bak.execute("SELECT 1 FROM trades LIMIT 1")
    except sqlite3.Error as exc:
        print(f"REFUSE: backup {bak_path} is not a readable trade journal ({exc}); nothing written.")
        return 1
    try:
        updates, refusals, skipped = plan_restore(conn, bak, ids, reason)
    finally:
        bak.close()
    for t in skipped:
        print(f"skip {t}: notes already carry pnl_source={UNMEASURED}")
    for r in refusals:
        print(f"REFUSE {r}")
    for u in updates:
        print(f"restore {u['id']}: notes rebuilt from backup; pnl_source={UNMEASURED}; {len(u['notes'])} chars")
    if refusals:
        print(f"{len(refusals)} refusal(s): NOTHING written.")
        return 1
    if not do_apply:
        print(f"dry-run: {len(updates)} row(s) would change. Re-run with --apply.")
        return 0
    if not updates:
        print("nothing to do.")
        return 0
    print(f"backup: {backup(db)}")
    print(f"restored: {apply_restore(conn, updates)} row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
