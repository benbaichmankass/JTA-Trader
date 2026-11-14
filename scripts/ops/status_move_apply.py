#!/usr/bin/env python3
# wiring: deploy_pull_restart.sh runs `--apply` after a sync whose diff touches config/accounts.yaml (a roster move).
"""Close the general-paper copy of a promoted trade (row STATUS-MOVE-AUTO-PAPER-CLOSE).

The rule is OPERATING-PLAN § 2 "Open positions on a book move" (#25251): on a promotion, the leg's general-paper copy
of a trade that is ALSO open on real money or the mirror is the third version and is closed on the paper book; a
paper copy with no money/mirror sibling runs to its own exit. ``status_move.classify`` decides which rows those are;
this script carries them out.

Authority (no new mandate, Manager Session 2026-11-13a, 2026-11-14 11:35Z):
  1. the operator rule quoted in OPERATING-PLAN § 2 (2026-10-29, on ADA trade 6734): "There shouldn't be three versions
     of this trade. There should be at most two."
  2. MD-TRADE-DESK grants ``close`` on every account carrying the package, paper included.
  3. the operator's 2026-11-14 directive ending advice-only: "Just turn on, like, no advice only. All those decisions
     should be implemented."

How each close runs: ONE account- and trade-scoped ``directed_action/v1`` close per row, through the existing
``directed_action._apply_record`` -> ``live_review_apply.run`` path (the account's own RiskManager.approve_action, its
own executor, venue read-back), then the directed path's one trade-update ping, then ``mark_operator_flattened`` so
exit analyses exclude the row. Per ROW, never a whole-symbol flatten: on bybit_1's netted symbols only that leg closes.

Hard limits (asserted here, pinned by tests/test_status_move_apply.py):
  * a target is ONLY a general-paper account (``status_move.GENERAL_PAPER``) whose config/accounts.yaml entry is paper
    and not a Stage-2 mirror; a real-money or mirror account is refused before anything is built;
  * a row acts only on a MEASURED match (an order_package_id on the row): an ESTIMATED leg+symbol+side match never
    closes anything;
  * a trade id acted on is never acted on twice (runtime_logs/status_move_apply_state.json).

    status_move_apply.py              # dry run: print what it would close
    status_move_apply.py --apply      # close (each directed record still re-checks every account bound)
"""
from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import status_move as sm  # noqa: E402
import strategy_status as st  # noqa: E402

OPERATOR_QUOTE = "There shouldn't be three versions of this trade. There should be at most two."
DIRECTED_BY = "status-move (OPERATING-PLAN 2: open positions on a book move)"
CLOSE_VERDICTS = (sm.CLOSE_DUPLICATE, sm.CLOSE_NETTED)
R_NOT_GENERAL_PAPER = "target_not_general_paper"
R_ESTIMATED = "match_not_measured"
R_DONE = "already_acted"


def _state_path() -> Path:
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / "status_move_apply_state.json"


def _log_path() -> Path:
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / "status_move_apply.jsonl"


def general_paper_refusal(account_id: str, accounts: Dict[str, Any]) -> Optional[str]:
    """None when ``account_id`` may be closed by this script; else the reason. Fails CLOSED on an unread config."""
    aid = str(account_id or "")
    if aid not in sm.GENERAL_PAPER:
        return f"{R_NOT_GENERAL_PAPER}:{aid} is not a general-paper book"
    if aid in sm.REAL_MONEY_MIRROR or aid in sm.MIRRORS:
        return f"{R_NOT_GENERAL_PAPER}:{aid} is a real-money or mirror book"
    cfg = accounts.get(aid)
    if not isinstance(cfg, dict):
        return f"{R_NOT_GENERAL_PAPER}:{aid} has no config/accounts.yaml entry (could not confirm paper)"
    cls = str(cfg.get("account_class") or "").lower()
    if cls not in ("paper", "soak"):
        return f"{R_NOT_GENERAL_PAPER}:{aid} account_class={cls or '—'} (not paper)"
    if str(cfg.get("paper_role") or "").lower() == "portfolio":
        return f"{R_NOT_GENERAL_PAPER}:{aid} is a Stage-2 mirror (paper_role portfolio)"
    return None


def open_positions(db_path: str) -> List[Dict[str, Any]]:
    """Open live journal rows, carrying order_package_id (status_move reads them as MEASURED)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, account_id, strategy_name, symbol, direction, order_package_id FROM trades "
            "WHERE status = 'open' AND COALESCE(is_backtest, 0) = 0")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def plan(positions: List[Dict[str, Any]], accounts: Dict[str, Any], strategies: Dict[str, Any],
         done: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(closes, refusals). Pure. Each close is one classify row the rule says to close, cleared by every limit."""
    retired = [leg for leg in strategies if st.retired(strategies, leg)]
    res = sm.classify(positions, st.rosters(accounts), retired)
    closes, refusals = [], []
    by_id = {str(p.get("id")): p for p in positions}
    for v in res["positions"]:
        if v["verdict"] not in CLOSE_VERDICTS:
            continue
        why = general_paper_refusal(v["account"], accounts)
        if why is None and v.get("match") != sm.MEASURED:
            why = f"{R_ESTIMATED}:{v.get('match')}"
        if why is None and str(v["id"]) in done:
            why = f"{R_DONE}:{done[str(v['id'])]}"
        pkg = (by_id.get(str(v["id"])) or {}).get("order_package_id")
        if why is None and not (isinstance(pkg, str) and pkg.startswith("pkg-")):
            why = f"{R_ESTIMATED}:no order_package_id"
        row = {"trade_id": str(v["id"]), "account_id": v["account"], "leg": v["leg"], "symbol": v["symbol"],
               "side": v["side"], "verdict": v["verdict"], "siblings": v.get("siblings"), "order_package_id": pkg}
        (refusals if why else closes).append({**row, **({"refused": why} if why else {})})
    return closes, refusals


def directed_record(close: Dict[str, Any], *, apply: bool, now: Optional[datetime] = None) -> Dict[str, Any]:
    from src.runtime import directed_actions as da
    now = now or datetime.now(timezone.utc)
    return {"schema": da.SCHEMA, "id": da.new_id("close", now, secrets.token_hex(3)), "directed_by": DIRECTED_BY,
            "operator_quote": OPERATOR_QUOTE, "created_at": now.isoformat(), "order_package_id": close["order_package_id"],
            "action": "close", "dry_run": not apply,
            "scope": {"account_id": close["account_id"], "trade_id": close["trade_id"]}}


def _mark(db_path: str, trade_id: str) -> str:
    import mark_operator_flattened as mof
    conn = sqlite3.connect(db_path)
    try:
        updates, refusals = mof.plan(conn, [int(trade_id)], "status-move: promoted leg's general-paper copy closed "
                                                             "(OPERATING-PLAN 2, row STATUS-MOVE-AUTO-PAPER-CLOSE)")
        if refusals:
            return f"not_marked:{'; '.join(refusals)}"
        return f"marked:{mof.apply(conn, updates)}"
    finally:
        conn.close()


def run(*, apply: bool, db_path: Optional[str] = None) -> Dict[str, Any]:
    from scripts.ops import directed_action
    from src.runtime import directed_actions as da
    from src.utils.paths import trade_journal_db_path

    db = db_path or str(trade_journal_db_path())
    accounts, strategies = st.load()
    if not accounts:
        return {"state": "could_not_look", "detail": "config/accounts.yaml unreadable", "closes": [], "refusals": []}
    sp = _state_path()
    try:
        done = json.loads(sp.read_text()).get("done", {}) if sp.exists() else {}
    except (OSError, ValueError):
        done = {}
    closes, refusals = plan(open_positions(db), accounts, strategies, done)
    results = []
    for c in closes:
        assert general_paper_refusal(c["account_id"], accounts) is None   # the hard limit, re-asserted at the act
        rec = directed_record(c, apply=apply)
        probs = da.problems(rec)
        if probs:
            results.append({**c, "result": "refused", "detail": ";".join(probs)})
            continue
        res = directed_action._apply_record(rec)
        executed = any(a.get("executed") for a in res.get("accounts") or [])
        out = {**c, "record": rec["id"], "exit": res.get("exit"), "executed": executed,
               "accounts": res.get("accounts"), "detail": res.get("detail")}
        if apply:
            directed_action._ping(rec, res, "applied" if executed else "not_applied")
            if executed:
                done[c["trade_id"]] = rec["id"]
                out["mark"] = _mark(db, c["trade_id"])
        results.append(out)
    doc = {"at": datetime.now(timezone.utc).isoformat(), "apply": apply, "closes": results, "refusals": refusals}
    if apply:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"done": done}, indent=1))
        with _log_path().open("a") as fh:
            fh.write(json.dumps(doc, default=str) + "\n")
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="close (default: dry run)")
    ap.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    doc = run(apply=a.apply, db_path=a.db)
    for c in doc.get("closes", []):
        print(f">>> status-move close #{c['trade_id']} {c['account_id']} {c['leg']} {c['symbol']} ({c['verdict']}): "
              f"exit={c.get('exit')} executed={c.get('executed')} {c.get('detail') or ''} {c.get('mark') or ''}")
    for r in doc.get("refusals", []):
        print(f">>> status-move refused #{r['trade_id']} {r['account_id']} {r['leg']} {r['symbol']}: {r['refused']}")
    if doc.get("state") == "could_not_look":
        print(f">>> status-move: COULD NOT LOOK — {doc.get('detail')}")
        return 3
    print(f">>> status-move: {len(doc.get('closes', []))} close(s), {len(doc.get('refusals', []))} refusal(s), "
          f"apply={doc.get('apply')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
