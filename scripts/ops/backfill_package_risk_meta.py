#!/usr/bin/env python3
"""Backfill ``meta.risk_per_unit`` / ``meta.entry_time`` on OPEN ml_entry + claude_desk packages. **Tier-2 DB write.**

WHY (ML-ENTRY-RISK-META, 2026-11-02): both builders omitted the two keys ``position_telemetry.build_record`` reads, so
open_r is None and peak_state is ``no_risk``. The builders are fixed for NEW packages; this fixes the packages already open.

APPROVAL: operator popup 2026-11-02 ~18:42Z, "Yes, fix now (Rec.)" -- store risk_per_unit (|entry-sl|) and entry_time,
backfill the open packages, order placement unchanged.

RULES: only ``status='open'`` packages of :data:`STRATEGIES`; only a MISSING key is written (an existing value is never
overwritten); risk_per_unit = |entry - sl| of the package row (must be > 0); entry_time = earliest linked trade
``created_at`` (trades.order_package_id = package, or package.linked_trade_id), else the package ``created_at``.
Touches only ``order_packages.meta``; no trade row, money field, order or venue. Idempotent. DRY-RUN unless ``--apply``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

STRATEGIES = ("ml_entry", "claude_desk")


def plan(conn):
    out = []
    rows = conn.execute(
        "SELECT order_package_id, strategy_name, entry, sl, created_at, linked_trade_id, meta FROM order_packages "
        f"WHERE status='open' AND strategy_name IN ({','.join('?' * len(STRATEGIES))}) ORDER BY created_at",
        STRATEGIES).fetchall()
    for r in rows:
        pid = r["order_package_id"]
        try:
            meta = json.loads(r["meta"]) if r["meta"] else {}
            if not isinstance(meta, dict):
                raise ValueError("not an object")
        except Exception as exc:  # noqa: BLE001
            out.append((pid, "refused", f"meta unparseable ({type(exc).__name__})", None, None, None))
            continue
        add = {}
        if meta.get("risk_per_unit") in (None, ""):
            risk = abs(float(r["entry"]) - float(r["sl"]))
            if not risk > 0:
                out.append((pid, "refused", "entry == sl, no risk", None, None, None))
                continue
            add["risk_per_unit"] = risk
        if not meta.get("entry_time"):
            t = conn.execute(
                "SELECT MIN(created_at) AS c FROM trades WHERE order_package_id = ? OR id = ?",
                (pid, r["linked_trade_id"])).fetchone()["c"]
            add["entry_time"] = t or r["created_at"]
        out.append((pid, "plan" if add else "noop", r["strategy_name"], add, meta, r["meta"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db if a.apply else f"file:{a.db}?mode=ro", uri=not a.apply)
    conn.row_factory = sqlite3.Row
    try:
        rows = plan(conn)
        written = lost = 0
        for pid, st, info, add, meta, raw in rows:
            if st == "plan":
                print(f"PLAN    {pid} ({info}): add {json.dumps(add)}")
                if a.apply:
                    new = dict(meta, **add)
                    cur = conn.execute(
                        "UPDATE order_packages SET meta = ? WHERE order_package_id = ? AND status='open' AND meta IS ?",
                        (json.dumps(new), pid, raw))
                    written += cur.rowcount
                    lost += 0 if cur.rowcount else 1
            else:
                print(f"{st.upper():8}{pid}: {info}")
        if a.apply:
            conn.commit()
            for pid, st, *_ in rows:
                if st == "plan":
                    m = json.loads(conn.execute("SELECT meta FROM order_packages WHERE order_package_id=?",
                                                (pid,)).fetchone()[0])
                    print(f"READBACK {pid} risk_per_unit={m.get('risk_per_unit')} entry_time={m.get('entry_time')}")
        n = lambda k: sum(1 for x in rows if x[1] == k)  # noqa: E731
        print(f"SUMMARY apply={a.apply} open_pkgs={len(rows)} planned={n('plan')} noop={n('noop')} "
              f"refused={n('refused')} written={written} lost_race={lost}")
        return 1 if a.apply and lost else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
