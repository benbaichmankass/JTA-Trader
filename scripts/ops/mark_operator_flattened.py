"""Mark specific closed trades as **operator-flattened**, so exit analyses can
exclude them.

THE PROBLEM. When an operator flattens a live position for an OPERATIONAL
reason — a venue-config change, a migration, clearing a symbol so a Bybit
position-mode switch can proceed — the flatten scripts
(``scripts/ops/flatten_{bybit,ib,alpaca}_position.py``) deliberately do NOT
touch the journal. Their docstrings say so: *"The journal row is left for the
trader's reconciler to close-on-disappear."* The reconciler duly notices the
position is flat and stamps ``exit_reason='reconciler_filled'`` +
``notes.closed_by='monitor_reconciler'``.

That is a correct description of HOW the row closed and a misleading one about
WHY. The resulting row is byte-indistinguishable from an ordinary close the
reconciler happened to book, so:

  * ``/api/bot/performance``'s ``perExitPath`` buckets it under
    ``reconciler_filled`` beside genuine strategy exits;
  * the exit-refinement corpus reads its entry→exit geometry as evidence about
    the strategy's exit quality, when the exit time was chosen by a human for a
    reason unrelated to the market.

The existing operator-flatten convention (``exit_reason=
'operator_flatten_reconciled'`` + ``notes.exit_price_source=
'operator_flatten_fill'``) lives in ``close_stranded_journal_row.py``, which
hard-filters ``WHERE status = 'open'`` — it is the tool for when the reconciler
FAILS to close the row. On the normal path, where the reconciler SUCCEEDS, the
marker is never applied. This script is that missing half.

⚠️ TARGETS ARE NAMED EXPLICITLY, NEVER DERIVED. There is no field that
distinguishes an operational flatten from a strategy exit — that absence is the
whole bug. So the caller passes trade ids and a reason; the script refuses to
guess. A filter-based version of this tool would be inventing the very signal it
exists to record.

⚠️ WHAT IT DOES NOT WRITE, deliberately. No monetary field (``pnl``,
``exit_price``, ``pnl_percent``) and — importantly — NOT ``exit_price_source``.
Trade 4934 carries ``bybit_closed_pnl``, genuine broker truth; stamping
``operator_flatten_fill`` over it would destroy a more specific provenance in
exactly the way
``BL-20260824-RECORDED-EXIT-PRICE-OUTNUMBERS-ALL-BROKER-TRUTH-COMBINED`` records
``order_monitor`` doing. (An id must never be line-wrapped: the ref guard scans
line by line, so a wrapped id reads as a truncated one that resolves to nothing.) The PRICE's provenance and the CLOSE's CAUSE
are different questions; this script answers only the second.

Usage on the VM:
    cd /home/ubuntu/ict-trading-bot
    python3 scripts/ops/mark_operator_flattened.py --trade-ids 4904,4934 \
        --reason "flattened to satisfy the flat-symbol guard for the \
bybit_2 hedge position-mode switch" # dry-run
    python3 scripts/ops/mark_operator_flattened.py --trade-ids 4904,4934 \
        --reason "..." --apply

Safety:
  * Refuses a row that is not ``status='closed'`` (an open row belongs to
    ``close-stranded-journal-row``), a backtest row, or an id that does not
    exist — each is reported, and nothing is written if ANY id is bad.
  * Idempotent: a row already carrying ``notes.closed_by_operator`` is skipped.
  * Records the prior label in ``notes.pre_mark_exit_reason``, so it is
    reversible per row.
  * Single transaction; partial failure rolls back.

``--exit-reason account_reset`` (PI-20261120-XGESYDCD-0002, 2026-11-20). The same
named-ids tool, for rows the PAPER close ladder's rung-3 close-all
(``DELETE /v2/positions?cancel_orders=true``) liquidated as collateral of ANOTHER
leg's close, where ``execute.journal_account_reset`` never ran (the trigger was
not flat within ALPACA_CLOSE_CONFIRM_S), so detectors labelled them. MEASURED
2026-11-16 14:32:33Z (alpaca_order_history, alpaca_paper): one batch of six
market closes. Extra preconditions, ALL rows, or nothing is written:
  * paper only (``account_class='paper'`` or ``is_demo=1``) -- the close-all is
    never automated on real money, so a real-money row cannot be its collateral;
  * one account, one episode: every ``closed_at`` within
    ``RESET_EPISODE_WINDOW_S`` of the others, and every row OPENED before the
    earliest of them;
  * the prior label is a detector / sweep label (``RESET_REPLACEABLE``), never a
    decision such as ``live_review_close``;
  * a row-only JSON backup of the named rows is written before ``--apply``;
  * the written notes must still carry the flag and ``pre_mark_exit_reason``
    after the cap, or nothing is written.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

EXIT_REASON = "operator_flatten_reconciled"
NOTE_FLAG = "closed_by_operator"

ACCOUNT_RESET = "account_reset"
RESET_FLAG = "closed_by_account_reset"
#: Labels a FLAT DETECTOR or a later price sweep writes; only these may be replaced by account_reset.
RESET_REPLACEABLE = frozenset({"stuck_strategy_watchdog", "exchange_flat_reconciled", "reconciler_filled",
                               "sl", "tp", ""})
#: One close-all episode: every named row closed within this many seconds of the others.
RESET_EPISODE_WINDOW_S = 1800


def _db_path() -> str:
    """The ONE sanctioned resolver. Deliberately no inline env-read and no
    CWD-relative fallback — that fallback is what seeded the stray duplicate
    journals, and `canonical-db-resolver` fails CI on it (it caught this exact
    file on its first draft)."""
    from src.utils.paths import trade_journal_db_path
    return str(trade_journal_db_path())


def _dump_notes(notes: Dict[str, Any]) -> str:
    """Serialize through the canonical capped writer when it is importable.

    Falls back to plain JSON only when src is unavailable (a bare invocation
    outside the repo); the fallback is why this is a function rather than an
    inline call — a silent uncapped write is exactly what caused the 5238/5239
    key loss, so the degraded path is named rather than implicit.
    """
    try:
        from src.utils.json_notes import dump_capped
        return dump_capped(notes, 500)
    except Exception:  # noqa: BLE001
        return json.dumps(notes)


def _load_notes(raw: Any) -> Dict[str, Any]:
    try:
        n = json.loads(raw) if raw else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"_original_notes": raw}
    return n if isinstance(n, dict) else {"_original_notes": raw}


def _recover_prior_exit_reason(conn: sqlite3.Connection, trade_id: int):
    """The pre-mark ``exit_reason`` for a row whose notes were shed.

    Reads ``order_packages.close_reason`` on the package linked to this trade.
    That column is written by the close cascade and is never touched by this
    script, so it is independent evidence rather than a restatement of the row
    being repaired. Returns ``None`` when it cannot be established — the caller
    REFUSES on None; it must not fall back to the row's own (already-marked)
    label.
    """
    try:
        cur = conn.execute(
            "SELECT close_reason FROM order_packages WHERE linked_trade_id = ? "
            "AND close_reason IS NOT NULL AND close_reason != '' "
            "ORDER BY updated_at DESC LIMIT 1", (trade_id,))
        got = cur.fetchone()
    except sqlite3.Error:
        return None
    if got is None:
        return None
    val = str(got[0] or "").strip()
    if not val or val == EXIT_REASON:
        return None  # the cascade carries the mark too — no independent prior
    return val


def plan(conn: sqlite3.Connection, trade_ids: List[int], reason: str
         ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (updates, refusals). A non-empty refusal list means write NOTHING."""
    conn.row_factory = sqlite3.Row
    updates: List[Dict[str, Any]] = []
    refusals: List[str] = []
    now = datetime.now(timezone.utc).isoformat()

    for tid in trade_ids:
        cur = conn.execute(
            "SELECT id, status, exit_reason, notes, is_backtest, symbol, account_id "
            "FROM trades WHERE id = ?", (tid,))
        row = cur.fetchone()
        if row is None:
            refusals.append(f"id={tid}: no such trade row")
            continue
        if int(row["is_backtest"] or 0):
            refusals.append(f"id={tid}: is a backtest row")
            continue
        if str(row["status"] or "") != "closed":
            refusals.append(
                f"id={tid}: status={row['status']!r}, not 'closed' — an open row "
                f"belongs to close-stranded-journal-row, not here")
            continue
        notes = _load_notes(row["notes"])
        if notes.get(NOTE_FLAG):
            continue  # idempotent: already marked
        # THREE states, never collapsed — the flag's ABSENCE does not mean
        # unmarked. Trades 5238/5239 carry `exit_reason=EXIT_REASON` with the
        # notes keys gone (shed by `dump_capped(notes, 500)` before those keys
        # were protected). Taking `row["exit_reason"]` as the prior on such a
        # row records THE MARK ITSELF as what preceded it, destroying the one
        # field that makes the marking reversible — laundering a value into the
        # journal, the failure `PROTECTION_REASSERT_MODE` exists to refuse.
        prior_source = "trades.exit_reason"
        prior = row["exit_reason"]
        if str(prior or "") == EXIT_REASON:
            # Marked, notes lost. Recover the prior from an INDEPENDENT
            # source the marking tool never writes: the linked order package's
            # `close_reason`, stamped by the close cascade. Evidence, not memory.
            prior = _recover_prior_exit_reason(conn, tid)
            prior_source = "order_packages.close_reason"
            if prior is None:
                refusals.append(
                    f"id={tid}: already carries exit_reason={EXIT_REASON!r} but no "
                    f"{NOTE_FLAG} in notes (marked, notes shed by the cap), and the "
                    f"prior label is NOT recoverable from order_packages.close_reason "
                    f"— refusing rather than recording the mark as its own prior")
                continue
        notes[NOTE_FLAG] = True
        notes["operator_close_reason"] = reason
        notes["pre_mark_exit_reason"] = prior
        # Which evidence the prior came from. Without it a repaired row is
        # indistinguishable from a first-time mark, and they are not the same
        # claim about what was observed.
        notes["pre_mark_exit_reason_source"] = prior_source
        notes["operator_marked_at"] = now
        updates.append({
            "id": int(row["id"]),
            "symbol": row["symbol"],
            "account_id": row["account_id"],
            "prior_exit_reason": prior,
            # Cap it the way every other trades.notes writer does, at the
            # TIGHTEST budget in use (500 — 15 call sites use it, 7 use 2000).
            # Writing an uncapped blob here is what let the next capped rewrite
            # shed these keys on trades 5238/5239: this tool wrote plain JSON,
            # then order_monitor's broker-pnl close path re-read the notes,
            # added exit_price_source, and wrote back through
            # dump_capped(notes, 500). Capping here does not prevent that
            # rewrite — protecting the keys does — but it stops this tool from
            # being the one that pushes the blob over budget.
            "notes": _dump_notes(notes),
        })
    return updates, refusals


def _ts(v: Any):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _dump_reset_notes(notes: dict[str, Any]) -> str:
    try:
        from src.utils.json_notes import _DEFAULT_PROTECTED, dump_capped
        return dump_capped(notes, 500, protected=set(_DEFAULT_PROTECTED) | {RESET_FLAG, "account_reset_at"})
    except Exception:  # noqa: BLE001 -- outside the repo only; named, not implicit
        return json.dumps(notes)


def plan_account_reset(conn: sqlite3.Connection, trade_ids: list[int], reason: str
                       ) -> tuple[list[dict[str, Any]], list[str]]:
    """``--exit-reason account_reset``: (updates, refusals); any refusal means write NOTHING."""
    conn.row_factory = sqlite3.Row
    rows, refusals = [], []
    for tid in trade_ids:
        r = conn.execute("SELECT id, status, exit_reason, notes, is_backtest, is_demo, account_class, "
                         "symbol, account_id, created_at, closed_at FROM trades WHERE id = ?", (tid,)).fetchone()
        if r is None:
            refusals.append(f"id={tid}: no such trade row")
            continue
        if int(r["is_backtest"] or 0):
            refusals.append(f"id={tid}: is a backtest row")
            continue
        if str(r["status"] or "") != "closed":
            refusals.append(f"id={tid}: status={r['status']!r}, not 'closed'")
            continue
        if not (str(r["account_class"] or "").lower() == "paper" or int(r["is_demo"] or 0)):
            refusals.append(f"id={tid}: not a paper row (account_class={r['account_class']!r}); the close-all "
                            f"is never automated on real money")
            continue
        rows.append(r)
    pending = []
    for r in rows:
        notes = _load_notes(r["notes"])
        if notes.get(RESET_FLAG) or str(r["exit_reason"] or "") == ACCOUNT_RESET:
            continue  # idempotent: already marked
        if str(r["exit_reason"] or "") not in RESET_REPLACEABLE:
            refusals.append(f"id={r['id']}: exit_reason={r['exit_reason']!r} is a decision, not a detector/sweep "
                            f"label; refusing to overwrite it")
            continue
        pending.append((r, notes))
    if rows:
        accts = {r["account_id"] for r in rows}
        if len(accts) != 1:
            refusals.append(f"rows span {len(accts)} accounts {sorted(accts)}; one close-all is one account")
        closes = [_ts(r["closed_at"]) for r in rows]
        opens = [_ts(r["created_at"]) for r in rows]
        if any(t is None for t in closes + opens):
            refusals.append("a named row has an unreadable created_at/closed_at; cannot prove one episode")
        else:
            first, last = min(closes), max(closes)
            if (last - first).total_seconds() > RESET_EPISODE_WINDOW_S:
                refusals.append(f"closes span {(last - first).total_seconds():.0f}s > {RESET_EPISODE_WINDOW_S}s; "
                                f"not one close-all episode")
            late = [r["id"] for r, o in zip(rows, opens) if o >= first]
            if late:
                refusals.append(f"id(s) {late} opened at/after the earliest close {first.isoformat()}; "
                                f"they cannot be collateral of it")
    if refusals:
        return [], refusals
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    for r, notes in pending:
        prior = str(r["exit_reason"] or "")
        notes.update({RESET_FLAG: True, "account_reset_at": now, "operator_close_reason": reason,
                      "pre_mark_exit_reason": prior, "pre_mark_exit_reason_source": "trades.exit_reason"})
        blob = _dump_reset_notes(notes)
        back = _load_notes(blob)
        if not (back.get(RESET_FLAG) is True and back.get("pre_mark_exit_reason") == prior):
            refusals.append(f"id={r['id']}: the marker or pre_mark_exit_reason would not survive the notes cap")
            continue
        updates.append({"id": int(r["id"]), "symbol": r["symbol"], "account_id": r["account_id"],
                        "prior_exit_reason": prior, "notes": blob})
    return ([], refusals) if refusals else (updates, [])


def row_backup(db_path: str, conn: sqlite3.Connection, trade_ids: list[int]) -> str:
    """The named rows' writable fields (exit_reason, notes) to a small JSON file beside the DB, so the
    write is reversible row by row with no ~3 GB full copy on the trader's root filesystem."""
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        f"SELECT id, exit_reason, notes FROM trades WHERE id IN ({','.join('?' * len(trade_ids))})",
        tuple(trade_ids))]
    dest = f"{db_path}.rows-mark-account-reset-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    with open(dest, "w") as fh:
        json.dump({"written_at": datetime.now(timezone.utc).isoformat(), "rows": rows}, fh, indent=1)
    return dest


def apply(conn: sqlite3.Connection, updates: list[dict[str, Any]], exit_reason: str = EXIT_REASON) -> int:
    with conn:
        for u in updates:
            conn.execute(
                "UPDATE trades SET exit_reason = ?, notes = ? WHERE id = ?",
                (exit_reason, u["notes"], u["id"]))
    return len(updates)


def _self_test() -> int:
    # data-wiring: creates NO persistent table. This is an in-memory (":memory:")
    # fixture that exists only for the duration of --self-test. The canonical
    # store is trade_journal.db::trades in src/units/db/database.py; this script
    # only ever UPDATEs two of its columns and never creates it. The columns
    # below are a SUBSET of that DDL, and tests/ops/test_mark_operator_flattened
    # ::test_the_fixture_columns_exist_in_the_real_ddl asserts so — a fixture
    # declaring a schema production does not have is how the pairs tests passed
    # against a fictional order_packages table.
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT,
        exit_reason TEXT, notes TEXT, is_backtest INTEGER, symbol TEXT,
        account_id TEXT, pnl REAL, exit_price REAL)""")
    # data-wiring: creates NO persistent table — an in-memory (":memory:")
    # --self-test fixture only. The canonical store is
    # trade_journal.db::order_packages in src/units/db/database.py; this script
    # never creates it and never WRITES it, it only SELECTs close_reason as the
    # independent evidence for a repaired row's prior label. History is not
    # backfilled here because nothing here persists. The four columns below are
    # a SUBSET of that canonical DDL, asserted by
    # tests/ops/test_mark_operator_flattened::test_the_fixture_columns_exist_in_the_real_ddl
    # — which is what makes this annotation true rather than merely present.
    conn.execute("""CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY,
        linked_trade_id INTEGER, close_reason TEXT, updated_at TEXT)""")
    conn.executemany(
        "INSERT INTO order_packages VALUES (?,?,?,?)",
        [("pkg-5", 5, "reconciler_filled", "2026-08-30T09:33:26+00:00"),
         ("pkg-6", 6, "", "2026-08-30T09:33:26+00:00")])
    conn.executemany(
        "INSERT INTO trades (id,status,exit_reason,notes,is_backtest,symbol,"
        "account_id,pnl,exit_price) VALUES (?,?,?,?,?,?,?,?,?)",
        [(1, "closed", "reconciler_filled",
          json.dumps({"exit_price_source": "bybit_closed_pnl"}), 0, "XRPUSDT",
          "bybit_2", -2.45, 1.38),
         (2, "open", "", "{}", 0, "ETHUSDT", "bybit_2", None, None),
         (3, "closed", "reconciler_filled", "{}", 1, "BTCUSDT", "bt", 0.0, 1.0),
         (4, "closed", EXIT_REASON, json.dumps({NOTE_FLAG: True}), 0, "ADAUSDT",
          "bybit_2", -1.0, 1.0),
         # 5 + 6: marked, notes SHED by the cap (trades 5238/5239 live). 5 has a
         # recoverable prior on its package; 6 does not.
         (5, "closed", EXIT_REASON, json.dumps({"_truncated": True}), 0,
          "BNBUSDT", "bybit_1", -1.0, 1.0),
         (6, "closed", EXIT_REASON, json.dumps({"_truncated": True}), 0,
          "BTCUSDT", "bybit_1", -1.0, 1.0)])
    conn.commit()
    fails = []

    def ck(name, ok):
        print(("  ok   " if ok else "  FAIL ") + name)
        if not ok:
            fails.append(name)

    ups, refs = plan(conn, [1], "test")
    ck("closed row is planned", len(ups) == 1 and ups[0]["id"] == 1)
    ck("prior label is recorded",
       json.loads(ups[0]["notes"])["pre_mark_exit_reason"] == "reconciler_filled")
    ck("broker-truth exit_price_source is left alone",
       json.loads(ups[0]["notes"])["exit_price_source"] == "bybit_closed_pnl")

    _, refs = plan(conn, [2], "test")
    ck("an OPEN row is refused", any("not 'closed'" in r for r in refs))
    _, refs = plan(conn, [3], "test")
    ck("a BACKTEST row is refused", any("backtest" in r for r in refs))
    ups, refs = plan(conn, [5], "test")
    ck("a marked-but-notes-shed row is REPAIRED, not re-marked",
       refs == [] and len(ups) == 1)
    ck("its prior comes from the package, NOT from the mark itself",
       json.loads(ups[0]["notes"])["pre_mark_exit_reason"] == "reconciler_filled")
    ck("and the prior's SOURCE is recorded",
       json.loads(ups[0]["notes"])["pre_mark_exit_reason_source"]
       == "order_packages.close_reason")

    _, refs = plan(conn, [6], "test")
    ck("an unrecoverable prior REFUSES rather than recording the mark as its own",
       any("NOT recoverable" in r for r in refs))

    _, refs = plan(conn, [999], "test")
    ck("a MISSING id is refused", any("no such trade" in r for r in refs))
    ups, refs = plan(conn, [4], "test")
    ck("an already-marked row is a no-op", ups == [] and refs == [])

    apply(conn, plan(conn, [1], "because")[0])
    r = conn.execute("SELECT exit_reason, notes, pnl, exit_price FROM trades "
                     "WHERE id=1").fetchone()
    ck("apply sets the operator exit_reason", r[0] == EXIT_REASON)
    n = json.loads(r[1])
    ck("apply records the reason", n["operator_close_reason"] == "because")
    ck("apply touches NO monetary field", r[2] == -2.45 and r[3] == 1.38)
    ups2, _ = plan(conn, [1], "again")
    ck("re-running is idempotent", ups2 == [])

    # Failure path: the planner must REFUSE rather than silently skip.
    ups3, refs3 = plan(conn, [1, 2], "mixed")
    ck("a bad id in a batch produces a refusal", len(refs3) == 1)

    print(f"self-test: {len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trade-ids", help="comma-separated trade ids")
    ap.add_argument("--reason", help="why the operator flattened these")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--exit-reason", default=EXIT_REASON, choices=(EXIT_REASON, ACCOUNT_RESET),
                    help="account_reset: paper close-all collateral (named ids, one episode; see docstring)")
    ap.add_argument("--from-intent", action="store_true",
                    help="DERIVE the targets from the operator_flatten_intent "
                         "marker the flatten script wrote itself, instead of "
                         "naming ids by hand. This is the durable path: it "
                         "needs nobody to remember which trades were flattened.")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    conn = sqlite3.connect(a.db or _db_path())

    if a.from_intent:
        if a.trade_ids:
            ap.error("--from-intent derives the ids; do not also pass --trade-ids")
        from src.runtime.operator_flatten_intent import find_unmarked_intent_rows
        pending = find_unmarked_intent_rows(conn)
        if not pending:
            print("No closed rows carry an unmarked operator_flatten_intent.")
            return 0
        ids = [r["id"] for r in pending]
        # The reason is the one the FLATTEN recorded, not one invented now.
        reasons = {r["intent"].get("reason") or "operator flatten" for r in pending}
        derived_reason = (reasons.pop() if len(reasons) == 1
                          else "operator flatten (multiple recorded reasons)")
        for r in pending:
            # `detail_state` is printed because a `shed` detail means the reason
            # below is a FALLBACK, not what the flatten recorded — the notes cap
            # dropped the prose (by design; the flag is what survives).
            print(f"  from-intent id={r['id']} {r['account_id']}/{r['symbol']} "
                  f"detail={r.get('detail_state')} "
                  f"intent_at={r['intent'].get('at')} reason={r['intent'].get('reason')!r}")
        a = argparse.Namespace(**{**vars(a), "reason": a.reason or derived_reason})
    else:
        if not a.trade_ids or not a.reason:
            ap.error("--trade-ids and --reason are both required "
                     "(or use --from-intent)")
        ids = [int(x) for x in a.trade_ids.split(",") if x.strip()]
    if a.exit_reason == ACCOUNT_RESET:
        if a.from_intent:
            ap.error("--from-intent is for operator flattens, not account_reset")
        ups, refs = plan_account_reset(conn, ids, a.reason)
        for r in refs:
            print(f"REFUSED {r}")
        if refs:
            print("Nothing written — resolve every refusal first.")
            return 2
        for u in ups:
            print(f"  id={u['id']} {u['account_id']}/{u['symbol']} {u['prior_exit_reason']!r} -> {ACCOUNT_RESET!r}")
        if not ups:
            print("No changes (already marked).")
            return 0
        if not a.apply:
            print(f"DRY-RUN: {len(ups)} row(s) would be marked {ACCOUNT_RESET}. Re-run with --apply.")
            return 0
        print(f"row backup: {row_backup(a.db or _db_path(), conn, [u['id'] for u in ups])}")
        print(f"APPLIED: {apply(conn, ups, ACCOUNT_RESET)} row(s) marked {ACCOUNT_RESET}.")
        return 0
    ups, refs = plan(conn, ids, a.reason)
    for r in refs:
        print(f"REFUSED {r}")
    if refs:
        print("Nothing written — resolve every refusal first.")
        return 2
    for u in ups:
        print(f"  id={u['id']} {u['account_id']}/{u['symbol']} "
              f"{u['prior_exit_reason']!r} -> {EXIT_REASON!r}")
    if not ups:
        print("No changes (already marked).")
        return 0
    if not a.apply:
        print(f"DRY-RUN: {len(ups)} row(s) would be marked. Re-run with --apply.")
        return 0
    n = apply(conn, ups)
    print(f"APPLIED: {n} row(s) marked {EXIT_REASON}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
