#!/usr/bin/env python3
"""List every venue-vs-computed P&L gap the journal records (PNL-GROSS-VS-VENUE-6817).

Operator decision w11 (2026-11-12): "Store the venue's always, it is the single source of
truth and if we have a gap we need to understand why". ``order_monitor._sweep_venue_net_pnl``
writes ``pnl`` = the venue's net figure, ``pnl_computed`` = ours, and ``pnl_gap_usd``. This
script reads the journal and prints each DIAGNOSIS ITEM:

* ``gap``: ``|pnl_gap_usd|`` above ``venue_pnl.gap_tolerance_usd`` (max of 0.25 USD and
  1% of the venue figure);
* ``unmatched``: ``pnl_basis='venue_unmatched'`` (a Bybit close whose venue record was
  never matched).

It prints the population and both counts, grouped by account. Gaps are listed, never
reconciled. Read-only.

Usage:
  scripts/ops/venue_pnl_gaps.py --journal-json FILE   # a saved /api/diag/journal?table=trades read
  scripts/ops/venue_pnl_gaps.py                       # fetch one via scripts/ops/diag_fetch.sh
  scripts/ops/venue_pnl_gaps.py --json                # machine-readable
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.runtime import venue_pnl as vp  # noqa: E402


def _load(path: str | None, limit: int) -> List[Dict[str, Any]]:
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        out = subprocess.run([str(ROOT / "scripts/ops/diag_fetch.sh"),
                              f"journal?table=trades&limit={int(limit)}"],
                             capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
    rows = data if isinstance(data, list) else (data.get("rows") or [])
    return [r for r in rows if isinstance(r, dict)]


def find_items(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pop = [r for r in rows if r.get("status") == "closed" and not r.get("is_backtest")]
    classified = [r for r in pop if r.get("pnl_basis")]
    items = []
    for r in classified:
        basis = str(r.get("pnl_basis"))
        if basis == vp.BASIS_VENUE_UNMATCHED:
            items.append({"kind": "unmatched", "id": r.get("id"), "account_id": r.get("account_id"),
                          "symbol": r.get("symbol"), "closed_at": r.get("closed_at"), "pnl": r.get("pnl")})
        elif basis in vp.NET_BASES and vp.is_gap(r.get("pnl"), r.get("pnl_computed")):
            items.append({"kind": "gap", "id": r.get("id"), "account_id": r.get("account_id"),
                          "symbol": r.get("symbol"), "closed_at": r.get("closed_at"),
                          "pnl_venue": r.get("pnl"), "pnl_computed": r.get("pnl_computed"),
                          "gap_usd": r.get("pnl_gap_usd"),
                          "tolerance_usd": round(vp.gap_tolerance_usd(r.get("pnl")), 4)})
    by_acct = collections.Counter((i["account_id"], i["kind"]) for i in items)
    return {
        "population": (f"{len(pop)} closed non-backtest rows read; {len(classified)} carry a pnl_basis "
                       f"(the rest are not classified yet, or predate the column)"),
        "n_closed": len(pop), "n_classified": len(classified),
        "n_gap": sum(1 for i in items if i["kind"] == "gap"),
        "n_unmatched": sum(1 for i in items if i["kind"] == "unmatched"),
        "by_account": {f"{a}|{k}": n for (a, k), n in sorted(by_acct.items())},
        "items": items,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--journal-json")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = find_items(_load(a.journal_json, a.limit))
    if a.json:
        print(json.dumps(res, indent=1, default=str))
        return 0
    print(res["population"])
    print(f"diagnosis items: {res['n_gap']} gap(s), {res['n_unmatched']} unmatched")
    for k, n in res["by_account"].items():
        print(f"  {k}: {n}")
    for i in res["items"]:
        print("  ", json.dumps(i, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
