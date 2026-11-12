#!/usr/bin/env python3
"""Status-move positions read: which OPEN positions a book move left behind (row STATUS-MOVE-OPEN-POSITIONS).

Rule: docs/plans/OPERATING-PLAN-2026-09-21.md § 2 "Open positions on a book move". Logic: scripts/ops/status_move.py.
This is the runtime half of strategy-status-guard: that guard reads the rosters in CI; this reads the positions.

Read-only. Places nothing, writes nothing. A ``close_duplicate`` row is closed through the existing
``flatten-<venue>-position`` system-action (paper account only); a ``close_netted`` row needs a per-row close, because
those actions flatten the whole symbol on the account.

Usage:
    python3 scripts/ops/status_move_positions.py                 # live: GET /api/bot/positions?include_paper=true
    python3 scripts/ops/status_move_positions.py --file pos.json # a saved positions or journal-trades JSON list
    python3 scripts/ops/status_move_positions.py --json
Exit: 0 clean · 1 a close is due, a version breach, or an unexplained row · 2 could not look.
"""
# wiring: manual-only - run by whoever merges a roster PR, after the merge (OPERATING-PLAN § 2 "Open positions on a book move")
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import status_move as sm
import strategy_status as st

LIVE_URL = "https://ict-bot.duckdns.org/api/bot/positions?include_paper=true"


def _positions(path: str | None):
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(LIVE_URL, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    if isinstance(data, dict):
        data = data.get("positions") or data.get("rows") or data.get("data")
    if not isinstance(data, list):
        raise TypeError("positions payload is not a list")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        positions = _positions(a.file)
    except Exception as exc:  # noqa: BLE001
        print(f"status_move: COULD NOT LOOK — {exc}", file=sys.stderr)
        return 2
    accounts, strategies = st.load()
    if not accounts:
        print("status_move: COULD NOT LOOK — config/accounts.yaml unreadable", file=sys.stderr)
        return 2
    retired = [leg for leg in strategies if st.retired(strategies, leg)]
    res = sm.classify(positions, st.rosters(accounts), retired)
    src = a.file or LIVE_URL
    if a.json:
        print(json.dumps({"source": src, **res}, indent=1))
    else:
        print(f"population: {res['population']} open positions from {src}")
        print("counts: " + ", ".join(f"{k} {v}" for k, v in res["counts"].items()))
        for p in res["positions"]:
            if p["verdict"] not in (sm.ON_BOOK, sm.NOT_JUDGED):
                extra = f" siblings={p.get('siblings')} match={p.get('match')}" if p.get("siblings") else ""
                print(f"  {p['verdict']:<15} #{p['id']} {p['account']} {p['leg']} {p['symbol']} {p['side']} — "
                      f"{p['why']}{extra}")
        for b in res["version_breaches"]:
            print(f"  VERSION BREACH {b['trade']} open {len(b['copies'])}x on {b['copies']} ids={b['ids']} "
                  f"match={b['match']}")
    c = res["counts"]
    due = c[sm.CLOSE_DUPLICATE] + c[sm.CLOSE_NETTED] + c[sm.UNEXPLAINED] + len(res["version_breaches"])
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())
