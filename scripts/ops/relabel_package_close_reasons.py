#!/usr/bin/env python3
"""Relabel 13 closed order packages to their linked trades' sl/tp label. **Tier-2 DB writeback.**

WHAT IS WRONG (CLOSE-REASON-XRP-1220, 2026-11-01)
-------------------------------------------------
The close paths stamp a package with the label of the path that NOTICED the close
(``reconciler_filled``, ``exchange_flat_reconciled``, ``stuck_cascade_recovered``,
``stuck_strategy_watchdog``, ``netting_attributed``). The trade rows were later refined to
``sl``/``tp`` from venue fills, and ``order_monitor._sweep_package_close_reason_from_trade``
carries that onto the package, but only for packages updated in the last 14 days. These 13
closed 2026-10-02..2026-10-12, so the sweep never reached them.

APPROVAL: the manager's 2026-11-01 decision (data-backed Tier-2: the linked trades already
read sl/tp from venue fills). The id list is FIXED here; the 14-day sweep window is
deliberately NOT widened, which would touch every matching package.

RULES (each one a refusal, never a guess)
* only the ids in :data:`TARGET_IDS`;
* only while ``close_reason`` is still one of :data:`BOOKKEEPING` (the UPDATE re-checks it);
* every linked trade (``trades.order_package_id`` = the package, or the package's
  ``linked_trade_id``) must be closed and read ``sl`` or ``tp``, all the SAME label;
  a mixed or missing set is refused;
* the prior value is kept in ``meta.pre_label_close_reason``;
* idempotent: a package already carrying the target label is a no-op.
Touches no trade row, no money field, no venue. DRY-RUN unless ``--apply``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

TARGET_IDS = (
    "pkg-d29c9c617aa14b40", "pkg-116e8fa3a99a4b93", "pkg-a9cce5360e6e4723",
    "pkg-3eac656c32ba43e4", "pkg-e602cc504093432b", "pkg-86e5480eccf04319",
    "pkg-9caabc69c3034359", "pkg-c3d86ac38d3644d3", "pkg-1c2147657eb3401f",
    "pkg-9f34c06abd924b6a", "pkg-c98cbaea89dd4fde", "pkg-3fef5dfdca6645a1",
    "pkg-596743908c2a401b",
)
BOOKKEEPING = (
    "reconciler_filled", "exchange_flat_reconciled", "stuck_cascade_recovered",
    "stuck_strategy_watchdog", "netting_attributed",
)
TRUE_LABELS = ("sl", "tp")


def plan_one(conn, pid):
    """Return (status, detail). status: plan | noop | refused."""
    row = conn.execute(
        "SELECT order_package_id, status, close_reason, linked_trade_id, meta "
        "FROM order_packages WHERE order_package_id = ?", (pid,)).fetchone()
    if row is None:
        return "refused", {"why": "package not found"}
    cur = row["close_reason"]
    trades = conn.execute(
        "SELECT id, status, exit_reason FROM trades "
        "WHERE order_package_id = ? OR id = ?", (pid, row["linked_trade_id"])).fetchall()
    labels = {t["exit_reason"] for t in trades}
    if row["status"] != "closed":
        return "refused", {"why": f"package status is {row['status']!r}, not closed"}
    if not trades:
        return "refused", {"why": "no linked trades found"}
    if any(t["status"] != "closed" for t in trades):
        return "refused", {"why": "a linked trade is not closed"}
    if len(labels) != 1 or next(iter(labels)) not in TRUE_LABELS:
        return "refused", {"why": f"linked trade labels are {sorted(map(str, labels))}, "
                                  "need one unanimous sl/tp"}
    target = next(iter(labels))
    if cur == target:
        return "noop", {"close_reason": cur, "why": "already carries the label"}
    if cur not in BOOKKEEPING:
        return "refused", {"why": f"close_reason {cur!r} is not a bookkeeping label"}
    return "plan", {"from": cur, "to": target, "n_trades": len(trades), "meta": row["meta"]}


def counts(conn):
    out = {}
    for pid in TARGET_IDS:
        r = conn.execute("SELECT close_reason FROM order_packages WHERE order_package_id=?",
                         (pid,)).fetchone()
        out[pid] = None if r is None else r["close_reason"]
    return out


def summarise(c):
    book = sum(1 for v in c.values() if v in BOOKKEEPING)
    tru = sum(1 for v in c.values() if v in TRUE_LABELS)
    return {"n": len(c), "bookkeeping": book, "sl_tp": tru,
            "other": len(c) - book - tru}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    a = ap.parse_args(argv)

    conn = sqlite3.connect(a.db if a.apply else f"file:{a.db}?mode=ro",
                           uri=not a.apply)
    conn.row_factory = sqlite3.Row
    try:
        before = counts(conn)
        print(f"BEFORE {json.dumps(summarise(before))}")
        planned, refused, noop = [], [], []
        for pid in TARGET_IDS:
            st, d = plan_one(conn, pid)
            {"plan": planned, "noop": noop, "refused": refused}[st].append((pid, d))
        for pid, d in planned:
            print(f"PLAN    {pid}: {d['from']} -> {d['to']} ({d['n_trades']} trades)")
        for pid, d in noop:
            print(f"NOOP    {pid}: {d['why']} ({d['close_reason']})")
        for pid, d in refused:
            print(f"REFUSED {pid}: {d['why']}")
        written = lost = 0
        if a.apply:
            for pid, d in planned:
                try:
                    meta = json.loads(d["meta"]) if d["meta"] else {}
                    if not isinstance(meta, dict):
                        raise ValueError("meta is not an object")
                except Exception as exc:  # noqa: BLE001
                    print(f"REFUSED {pid}: meta unparseable ({type(exc).__name__})")
                    continue
                meta.setdefault("pre_label_close_reason", d["from"])
                cur = conn.execute(
                    "UPDATE order_packages SET close_reason = ?, meta = ? "
                    "WHERE order_package_id = ? AND close_reason = ? AND status = 'closed'",
                    (d["to"], json.dumps(meta), pid, d["from"]))
                if cur.rowcount:
                    written += 1
                else:
                    lost += 1
                    print(f"LOST-RACE {pid}: close_reason changed under us; not written")
            conn.commit()
        after = counts(conn)
        print(f"AFTER  {json.dumps(summarise(after))}")
        for pid in TARGET_IDS:
            print(f"READBACK {pid} {before[pid]} -> {after[pid]}")
        print(f"SUMMARY apply={a.apply} planned={len(planned)} noop={len(noop)} "
              f"refused={len(refused)} written={written} lost_race={lost}")
        if a.apply and (lost or any(after[p] != d["to"] for p, d in planned)):
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
