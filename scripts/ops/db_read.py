#!/usr/bin/env python3
# wiring: called - the system-action wrappers (scripts/ops/*_action.sh, inspect/kick_insights.sh) call it for their
# read-only BEFORE/AFTER and count reads.
"""Read-only SQL for the VM shell wrappers, in place of the ``sqlite3`` CLI (which is NOT installed on the live VM).

AUD-20261104-FLATTEN-LABEL side finding (2026-11-11): system-action #23604 printed ``sqlite3: command not found`` for
its BEFORE/AFTER read-back, so the action's own verification showed nothing. Eleven wrappers used the CLI; the count
ones fell back to ``?``, which (a) disabled their "nothing to do" exit and (b) wrote ``"pre_count": ?`` -- invalid
JSON -- into ``record_audit``.

    db_read.py <db> "<SELECT ...>"            # one scalar (first column of the first row; empty if no row)
    db_read.py --table <db> "<SELECT ...>"    # header + rows, column-aligned (the CLI's -header -column)

The database is opened read-only (``file:...?mode=ro``) and only a single SELECT / WITH statement is accepted.
Exit 0 on success, 2 on a refused statement or a read error (stderr says which).
"""
from __future__ import annotations

import re
import sqlite3
import sys
from typing import List, Optional, Sequence

_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def run(db: str, sql: str, table: bool = False) -> str:
    stmt = sql.strip().rstrip(";").strip()
    if not _READ_ONLY.match(stmt) or ";" in stmt:
        raise ValueError("only one SELECT / WITH statement is accepted")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        cur = conn.execute(stmt)
        rows = cur.fetchall()
        cols = [d[0] for d in (cur.description or [])]
    finally:
        conn.close()
    if not table:
        return "" if not rows else ("" if rows[0][0] is None else str(rows[0][0]))
    cells: List[List[str]] = [cols] + [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    table = False
    if args and args[0] == "--table":
        table, args = True, args[1:]
    if len(args) != 2:
        print("usage: db_read.py [--table] <db> '<SELECT ...>'", file=sys.stderr)
        return 2
    try:
        print(run(args[0], args[1], table=table))
    except (ValueError, sqlite3.Error) as exc:
        print(f"db_read: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
