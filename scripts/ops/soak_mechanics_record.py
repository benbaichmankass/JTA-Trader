#!/usr/bin/env python3
# wiring: manual-only - a session runs it over read-only diag pulls to write the committed soak evidence record (comms/research/soak_mechanics/); the live state is soak_state.soak_states() on the VM
"""Grade every soak contract MECHANICALLY from a pulled journal, and write a committed evidence record.

Why this exists: soak state is computed live on the VM by
``soak_state.soak_states()``; a session cannot open that DB. It CAN pull the
same rows read-only through the diag relays. This script loads those pulled rows
into a scratch SQLite DB with the journal's table names and runs the SAME grader
(``soak_state.graded_for`` + ``soak_state.evaluate``) over it, so the committed
record and the live state come from one definition.

Inputs (all READ-ONLY pulls; see ``--help``):
  trades.json        GET /api/diag/journal?table=trades (every page)
  packages.json      GET /api/diag/journal?table=order_packages (every page)
  prop_tickets.json  GET /api/bot/prop/tickets?limit=500   (optional)
  prop_fills.json    GET /api/bot/prop/fills?limit=500     (optional)

Output: ``comms/research/soak_mechanics/<date>.json``: one entry per contract
with the state, the clean trade/package ids the state rests on, the fault (id and
reason) when there is one, and every graded event's checklist items. It carries
NO P&L, balances or sizes: ids, timestamps, exit reasons and checklist verdicts
only (public repo).

``--apply`` also writes the PASS dispositions into ``docs/claude/work/SOAKS.json``
(the migration). Without it the store is not touched.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import soak_state as ss  # noqa: E402

OUT_DIR = REPO / "comms/research/soak_mechanics"
#: Fields copied into the record per graded event. Deliberately no pnl / size.
_EVENT_KEYS = ("id", "clean", "fault", "items", "accounts")


def _load(path: str) -> List[Dict[str, Any]]:
    d = json.loads(Path(path).read_text())
    if isinstance(d, dict):
        for k in ("rows", "fills", "tickets"):
            if isinstance(d.get(k), list):
                return d[k]
    return d if isinstance(d, list) else []


def _table(conn: sqlite3.Connection, name: str, rows: List[Dict[str, Any]]) -> None:
    cols = sorted({k for r in rows for k in r}) or ["_empty"]
    conn.execute(f"CREATE TABLE {name} ({', '.join(f'[{c}]' for c in cols)})")
    for r in rows:
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in (r.get(c) for c in cols)]
        conn.execute(f"INSERT INTO {name} VALUES ({','.join('?' * len(cols))})", vals)


def build_db(trades, packages, tickets, fills) -> str:
    path = str(Path(tempfile.mkdtemp()) / "journal.db")
    conn = sqlite3.connect(path)
    _table(conn, "trades", trades)
    _table(conn, "order_packages", packages)
    if tickets is not None:
        # /api/bot/prop/tickets projects prop_tickets as `strategy`; keep that name.
        _table(conn, "prop_tickets", tickets)
        _table(conn, "prop_fills", fills or [])
    conn.commit()
    conn.close()
    return path


def grade_all(db: str, contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db)
    out = []
    for c in contracts:
        entry: Dict[str, Any] = {"id": c["id"], "leg": c["leg"], "account": c["account"],
                                 "kind": c["kind"], "started": c["started"],
                                 "n_needed": c.get("n_needed")}
        d = c.get("disposition") or {}
        if c.get("design") == "not_soaking":
            entry.update(state="not_soaking", reason=c.get("recommended_fix"))
        elif d.get("verdict") in ("KILLED", "REFUSE", "FAIL"):
            entry.update(state=f"disposition:{d['verdict']}", reason=str(d.get("reason"))[:160])
        else:
            graded = ss.graded_for(conn, c)
            ev = ss.evaluate(graded, int(c.get("n_needed") or ss.N_DEFAULT))
            entry.update(state=ev["state"], progress=ev["progress"], reason=ev["reason"],
                         clean=ev["clean"], fault=ev.get("fault"), fault_id=ev.get("fault_id"),
                         graded=[{k: g.get(k) for k in _EVENT_KEYS if k in g} for g in graded
                                 if g.get("clean") is not None])
            if d.get("verdict") == "NEEDS_DATA":
                entry["disposition_in_force"] = {"verdict": "NEEDS_DATA", "until": d.get("until")}
        out.append(entry)
    conn.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trades", required=True)
    ap.add_argument("--packages", required=True)
    ap.add_argument("--prop-tickets")
    ap.add_argument("--prop-fills")
    ap.add_argument("--pulled-at", required=True, help="ISO time the pulls were taken")
    ap.add_argument("--out", default=None)
    ap.add_argument("--apply", action="store_true", help="write PASS dispositions into SOAKS.json")
    a = ap.parse_args(argv)
    trades, packages = _load(a.trades), _load(a.packages)
    tickets = _load(a.prop_tickets) if a.prop_tickets else None
    fills = _load(a.prop_fills) if a.prop_fills else None
    contracts = ss.load_contracts()
    for c in contracts:
        for p in ss.contract_problems(c):
            raise SystemExit(f"contract {c['id']} not admissible ({p}) — migrate the schema first")
    entries = grade_all(build_db(trades, packages, tickets, fills), contracts)
    day = a.pulled_at[:10]
    counts: Dict[str, int] = {}
    for e in entries:
        counts[e["state"]] = counts.get(e["state"], 0) + 1
    rec = {
        "question": "Stage-1 / shadow soak, MECHANICAL definition (operator 2026-10-15): has each "
                    "leg cleared its checklist on n_needed (<=2) clean trades since its last fault?",
        "rule": "scripts/ops/soak_state.py (grade_trade / grade_shadow_package / grade_prop_signal / "
                "evaluate) — the same code soak_states() runs live",
        "population": {
            "contracts": len(entries),
            "journal_trades_rows": len(trades), "order_packages_rows": len(packages),
            "prop_tickets_rows": None if tickets is None else len(tickets),
            "prop_fills_rows": None if fills is None else len(fills),
        },
        "sources": ["GET /api/diag/journal?table=trades (all pages)",
                    "GET /api/diag/journal?table=order_packages (all pages)"]
                   + (["GET /api/bot/prop/tickets?limit=500", "GET /api/bot/prop/fills?limit=500"]
                      if tickets is not None else []),
        "pulled_at": a.pulled_at,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": dict(sorted(counts.items())),
        "note": "No P&L, balances or sizes are recorded here (public repo). Provenance of fees on "
                "the graded closes is carried per trade as cost_source.",
        "soaks": entries,
    }
    out = Path(a.out) if a.out else OUT_DIR / f"{day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}: {rec['counts']}")
    if a.apply:
        rel = str(out.relative_to(REPO))
        by = {e["id"]: e for e in entries}
        doc = json.loads(ss.CONTRACTS.read_text())
        n = 0
        for c in doc["soaks"]:
            e = by.get(c["id"])
            if not e or e["state"] != "passed" or (c.get("disposition") or {}).get("verdict") == "PASS":
                continue
            c["disposition"] = {
                "verdict": "PASS", "decided_at": date.fromisoformat(day).isoformat(),
                "trades": e["clean"], "evidence": [rel],
                "reason": f"mechanical soak passed: {e['reason']}",
            }
            n += 1
        ss.CONTRACTS.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"applied {n} PASS disposition(s) to {ss.CONTRACTS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
