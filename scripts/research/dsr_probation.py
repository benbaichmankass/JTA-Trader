#!/usr/bin/env python3
"""DSR PROBATION: every PRODUCTION leg whose deflated Sharpe is <= 0.95, with its live iteration unit(s).

Report-only standing check for /performance-review and /ml-review (lane SOAK-BACKLOG-REVIEW, 2026-11-06).
DSR is a review and iteration metric, never a promotion or demotion gate: the real-money bar is the holdout
(mandate_resolver R-HOLDOUT). A production leg below the bar is "on probation": it trades live and must have a
live iteration unit whose goal is a DSR-proof version. Decision record: Manager Session 2026-11-06a relay of the
operator's 2026-11-06 ~19:35Z popup (option 3, "Holdout governs; promote").

POPULATION (printed every run): production legs from scripts/ops/strategy_status.py (re-read from config). DSR from
comms/research/trial_ledger.json (``evidence[leg].dsr.dsr``); units from scripts/research/iteration_orphans.py.
A leg the ledger does not carry is listed with ``dsr: —`` and read_state ``not_in_ledger`` (never as 0, never as passing).

Gates this adds or changes: none. Exit 0 on any finding; exit 2 only when the inputs cannot be read at all.
Usage: python3 scripts/research/dsr_probation.py [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/ops"))
sys.path.insert(0, str(REPO / "scripts/research"))

import strategy_status as ss  # noqa: E402

LEDGER_REL = "comms/research/trial_ledger.json"
BAR = 0.95


def rows(root: Path = REPO) -> List[Dict[str, Any]]:
    import iteration_orphans as io  # noqa: PLC0415
    t = ss.table(root)
    try:
        ledger = json.loads((root / LEDGER_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = None
    ev = (ledger or {}).get("evidence") or {}
    units: Dict[str, List[str]] = {}
    for u in (x for x in io.live_units(root) if x.get("live")):  # queued / unblockable units only
        for sid in io._subjects_of(u.get("iteration") or {}):
            units.setdefault(sid, []).append(u["id"])
    res = []
    for leg, row in t.items():
        if row["status"] != ss.PRODUCTION:
            continue
        e = ev.get(leg)
        d = ((e or {}).get("dsr") or {}).get("dsr") if isinstance(e, dict) else None
        measured = isinstance(d, (int, float)) and not isinstance(d, bool)
        res.append({"leg": leg, "books": row["books"], "dsr": d if measured else None,
                    "read_state": "measured" if measured else ("not_computed" if e else "not_in_ledger"),
                    "probation": (d <= BAR) if measured else None,
                    "units": units.get(leg, [])})
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not (REPO / "config/strategies.yaml").is_file():
        print("dsr_probation: COULD NOT READ config", file=sys.stderr)
        return 2
    r = rows()
    if a.json:
        print(json.dumps({"bar": BAR, "ledger": LEDGER_REL, "population": "production legs (strategy_status.py)",
                          "rows": r}, indent=1))
        return 0
    for x in r:
        d = "—" if x["dsr"] is None else f"{x['dsr']:.3f}"
        flag = "PROBATION" if x["probation"] else ("ok" if x["probation"] is False else x["read_state"])
        print(f"{flag:<13} {x['leg']:<28} dsr={d:<7} units={','.join(x['units']) or '— (NO LIVE UNIT)'}")
    n_p = sum(1 for x in r if x["probation"])
    print(f"population: {len(r)} production legs; on probation (DSR <= {BAR}) {n_p}; "
          f"unread {sum(1 for x in r if x['probation'] is None)}; ledger {LEDGER_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
