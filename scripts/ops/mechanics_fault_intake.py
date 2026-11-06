#!/usr/bin/env python3
"""MECHANICS-FAULT-INTAKE: a per-trade mechanics fault lands as a pipeline item, so it has an owner
and is not just an alert. Mechanics monitoring (operator 2026-11-06: follow up here, not only a ping).

Reads recently CLOSED journal trades, grades each with ``soak_state.grade_trade`` (the per-trade
mechanics check: signal->package, size/side, real bracket at venue, exit journaled by a real reason,
pnl+fees recorded) and files ONE ``dispatch_lane`` item per faulted trade: a reconciler close, pnl/fee
still missing AFTER the cost-write window, a missing/naked bracket. Not filed: neutral rows, desk/LTR-
touched trades, and closes still inside the cost-write window (could not look yet).
A filing blocks nothing, flips nothing, places no order: it is not a gate.

  python3 scripts/ops/mechanics_fault_intake.py                       # dry run
  python3 scripts/ops/mechanics_fault_intake.py --apply --session-ref <session>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import pipeline  # noqa: E402
import soak_state  # noqa: E402

KEY = "mechanics-fault"


def fault_key(trade_id: Any) -> str:
    return f"{KEY}:{trade_id}"


def _filed(items: Iterable[dict]) -> set:
    return {str((i.get("origin") or {}).get("ref", "")).split(" ")[0] for i in items}


def candidates(trades: List[Dict[str, Any]], items: Iterable[dict], now: datetime,
               packages: Dict[Any, Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """Pure: closed trade rows -> [{trade, grade}] for faulted, untouched, not-yet-filed trades."""
    done, out = _filed(items), []
    for t in trades:
        g = soak_state.grade_trade(t, (packages or {}).get(t.get("order_package_id")), now=now)
        if g["clean"] is False and g["fault"] and not g.get("pending") and not g.get("touched") \
                and fault_key(t["id"]) not in done:
            out.append({"trade": t, "grade": g})
    return out


def build_item(c: Dict[str, Any], item_id: str) -> dict:
    t, g = c["trade"], c["grade"]
    return {
        "id": item_id,
        "what": f"mechanics fault on trade {t['id']} ({t.get('account_id')}/{t.get('strategy_name')} "
                f"{t.get('symbol')}, exit_reason={t.get('exit_reason')!r}): {g['fault']}",
        "origin": {"kind": "audit", "ref": f"{fault_key(t['id'])} (mechanics monitoring)",
                   "rerun": f"python3 scripts/ops/mechanics_fault_intake.py  # grades closed trades; trade {t['id']}"},
        "due_when": {"kind": "observation", "check_every_days": 1,
                     "clears_when": f"trade {t['id']}'s fault is root-caused and fixed (or the grader rule is "
                                    f"corrected); or killed with a stated reason"},
        "next_action": "dispatch_lane",
        "state": "queued",
    }


def _recent(conn: sqlite3.Connection, since_iso: str) -> tuple:
    conn.row_factory = sqlite3.Row
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE status='closed' AND COALESCE(is_backtest,0)=0 "
        "AND datetime(closed_at) >= datetime(?)", (since_iso,))]
    pk: Dict[Any, Dict[str, Any]] = {}
    for t in trades:
        if t.get("order_package_id"):
            r = conn.execute("SELECT * FROM order_packages WHERE order_package_id=?",
                             (t["order_package_id"],)).fetchone()
            if r:
                pk[t["order_package_id"]] = dict(r)
    return trades, pk


def _live_trades(limit: int) -> List[Dict[str, Any]]:
    """Closed trades via the diag read surface (the CI runner has no journal DB). Raises on a failed read:
    could-not-look is an error exit, never an empty list."""
    out = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), f"journal?table=trades&limit={limit}"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"diag_fetch rc={out.returncode}: {out.stderr.strip()[-200:]}")
    rows = json.loads(out.stdout)
    if not isinstance(rows, list):
        raise RuntimeError("diag journal read returned a non-list payload")
    return [r for r in rows if r.get("status") == "closed" and not r.get("is_backtest")]


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--session-ref", default="")
    ap.add_argument("--since-hours", type=float, default=48.0)
    ap.add_argument("--live", action="store_true",
                    help="read closed trades via the diag surface (CI); order packages are not read, so the "
                         "package-side match is skipped (signal_fired / size / bracket / exit / costs still graded)")
    a = ap.parse_args(argv)
    if a.live:
        try:
            now = datetime.now(timezone.utc)
            cut = (now - timedelta(hours=a.since_hours)).isoformat()
            trades = [t for t in _live_trades(300) if str(t.get("closed_at") or "") >= cut]
        except Exception as exc:  # noqa: BLE001 — could not look is loud, not zero
            print(f"mechanics-fault-intake: could not look ({exc})", file=sys.stderr)
            return 3
        return _file(a, trades, {}, now)
    path = soak_state._db_path()
    if not path or not Path(path).exists():
        print("mechanics-fault-intake: journal DB not readable here — could not look (not zero faults)")
        return 3
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        trades, pk = _recent(conn, (now - timedelta(hours=a.since_hours)).strftime("%Y-%m-%d %H:%M:%S"))
    finally:
        conn.close()
    return _file(a, trades, pk, now)


def _file(a, trades, pk, now) -> int:
    todo = candidates(trades, pipeline.read_log(REPO / pipeline.STORE).items.values(), now, pk)
    print(f"mechanics-fault-intake: {len(trades)} closed trade(s) read, {len(todo)} unfiled fault(s)")
    for c in todo:
        print(f"  - {fault_key(c['trade']['id'])}: {c['grade']['fault']}")
        if a.apply:
            if not a.session_ref:
                print("    --session-ref required with --apply", file=sys.stderr)
                return 2
            iid = pipeline.mint_id(a.session_ref)
            pipeline.append(build_item(c, iid), intent="new")
            print(f"    filed {iid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
