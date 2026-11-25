#!/usr/bin/env python3
# wiring: research/queue/RQ-20261125-cf48-03.yaml run.command (trainer: reads the synced trade_journal.db)
"""D9 (Whippet) RE-ENTRY COUNT: how many REAL-MONEY fills carry a decision price? (plan MLP-D9-WHIPPET, W48/W49)

docs/plans/ml-dev-plan.yaml MLP-D9-WHIPPET is parked with one re-entry test: it reopens when >= 300 real-money fills carry a
decision price (docs/plans/ML-ROADMAP-MECE-2026-11.md § 8). Nobody has counted. This is that count, nothing more.

A FILL WITH A DECISION PRICE = a row of the join the execution_quality dataset family already uses
(ml/datasets/families/execution_quality.py): trades t INNER JOIN order_packages op ON op.linked_trade_id = t.id, with
t.status = 'closed', t.is_backtest = 0, t.entry_price NOT NULL, op.entry > 0 (op.entry is the decision / intended price,
t.entry_price the fill). Restricted to t.account_class = 'real_money' AND COALESCE(t.is_demo, 0) = 0. Counted per account,
per strategy and in total; also the same join on every class (context, never graded) and the union over order_package_id
(a trade linked from the package side via t.order_package_id, for a package that never set linked_trade_id).

verdict.json: PASS iff total >= --floor (300, the plan's floor): the D9 fill-replay design may be authored. FAIL: below the
floor, the slot stays parked and the count is its re-entry reading. no_data if the tables are absent.
Read-only (sqlite mode=ro). Writes only --out. No config, model, registry or order path. Tier-1 research tooling.

    python3 scripts/research/d9_fill_count.py --db data/trade_journal.db --unit RQ-... --out DIR
    python3 scripts/research/d9_fill_count.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FLOOR = 300
_BASE = ("FROM trades t INNER JOIN order_packages op ON (op.linked_trade_id = t.id OR op.order_package_id = t.order_package_id) "
         "WHERE t.status = 'closed' AND COALESCE(t.is_backtest, 0) = 0 AND t.entry_price IS NOT NULL "
         "AND op.entry IS NOT NULL AND op.entry > 0")


def count(db: Path) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"trades", "order_packages"} <= have:
            return {"read_state": "no_data", "why": f"tables missing: {sorted({'trades', 'order_packages'} - have)}"}
        rm = " AND t.account_class = 'real_money' AND COALESCE(t.is_demo, 0) = 0"
        by_acct = dict(conn.execute(f"SELECT t.account_id, COUNT(DISTINCT t.id) {_BASE}{rm} GROUP BY t.account_id").fetchall())
        by_strat = dict(conn.execute(f"SELECT t.strategy_name, COUNT(DISTINCT t.id) {_BASE}{rm} GROUP BY t.strategy_name").fetchall())
        total = conn.execute(f"SELECT COUNT(DISTINCT t.id) {_BASE}{rm}").fetchone()[0]
        by_class = dict(conn.execute(f"SELECT COALESCE(t.account_class, 'unknown'), COUNT(DISTINCT t.id) {_BASE} "
                                     "GROUP BY 1").fetchall())
        span = conn.execute(f"SELECT MIN(t.timestamp), MAX(t.timestamp) {_BASE}{rm}").fetchone()
        return {"read_state": "measured", "total_real_money": int(total), "by_account": by_acct, "by_strategy": by_strat,
                "by_class_context": by_class, "first_ts": span[0], "last_ts": span[1]}
    finally:
        conn.close()


def run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Path(a.db)
    m = count(db) if db.is_file() else {"read_state": "no_data", "why": f"{db} not found"}
    n = int(m.get("total_real_money") or 0)
    if m["read_state"] != "measured":
        verdict, note = "not_applicable", m.get("why", "")
    else:
        verdict = "pass" if n >= a.floor else "fail"
        note = (f"{n} real-money fills carry a decision price (floor {a.floor}): "
                + ("D9 fill-replay design may be authored" if verdict == "pass" else "D9 stays parked; this is its re-entry reading"))
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": m["read_state"], "verdict": verdict, "n": n,
           "note": note,
           "population": ("closed, non-backtest, non-demo real_money trades joined to an order_package with entry > 0 "
                          f"(execution_quality join), whole synced journal {db}"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": m, "data_inputs": [str(db)],
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(json.dumps({k: row[k] for k in ("read_state", "verdict", "n", "note")}))
    return 0


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "j.db"
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE trades (id INTEGER, status TEXT, is_backtest INT, entry_price REAL, account_class TEXT, "
                  "is_demo INT, account_id TEXT, strategy_name TEXT, timestamp TEXT, order_package_id TEXT)")
        c.execute("CREATE TABLE order_packages (order_package_id TEXT, linked_trade_id INT, entry REAL)")
        rows = [(1, "closed", 0, 10.0, "real_money", 0, "bybit_2", "a", "2026-11-01", "p1"),   # counted (linked)
                (2, "closed", 0, 10.0, "real_money", 0, "bybit_2", "a", "2026-11-02", "p2"),   # counted (package id)
                (3, "rejected", 0, 10.0, "real_money", 0, "alpaca_live", "b", "2026-11-03", "p3"),  # not closed
                (4, "closed", 0, 10.0, "paper", 0, "bybit_1", "a", "2026-11-04", "p4"),        # paper: context only
                (5, "closed", 1, 10.0, "real_money", 0, "bybit_2", "a", "2026-11-05", "p5"),   # backtest
                (6, "closed", 0, 10.0, "real_money", 0, "bybit_2", "a", "2026-11-06", "p6")]   # op.entry 0
        c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT INTO order_packages VALUES (?,?,?)",
                      [("p1", 1, 9.9), ("p2", None, 9.9), ("p3", 3, 9.9), ("p4", 4, 9.9), ("p5", 5, 9.9), ("p6", 6, 0.0)])
        c.commit()
        c.close()
        m = count(db)
        assert m["total_real_money"] == 2 and m["by_account"] == {"bybit_2": 2}, m
        assert m["by_class_context"] == {"real_money": 2, "paper": 1}, m
    print(json.dumps({"self_test": "ok"}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="data/trade_journal.db")
    ap.add_argument("--floor", type=int, default=FLOOR)
    ap.add_argument("--unit", default="")
    ap.add_argument("--rule-id", default="RULE-RQ20261125-cf48-03-D9-REENTRY-COUNT")
    ap.add_argument("--registered-at", default="2026-11-25")
    ap.add_argument("--out", default="out/d9_fill_count")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    return _self_test() if a.self_test else run(a)


if __name__ == "__main__":
    sys.exit(main())
