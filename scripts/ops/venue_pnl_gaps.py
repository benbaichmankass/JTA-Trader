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

Two modes (manager decision 2026-11-12 on #25270):

* ``--mode real``: REAL-MONEY accounts (``account_class='real_money'``). Every gap and every
  unmatched row is its OWN diagnosis item (id ``VPG-<trade_id>``), because they are few and
  each needs a reason.
* ``--mode demo``: paper books. Items are GROUPED per (account, kind), feeding one standing
  checklist row per group (``VENUE-PNL-GAPS-<ACCOUNT>-<KIND>``).

``--check`` makes the run a machine-checkable condition: exit 0 when the selection (after
``--account`` / ``--kind`` / ``--max-age-days``) has NO items, else exit 1. The standing rows'
``clears_when`` is such a command.

Usage:
  scripts/ops/venue_pnl_gaps.py --journal-json FILE   # a saved /api/diag/journal?table=trades read
  scripts/ops/venue_pnl_gaps.py                       # fetch one via scripts/ops/diag_fetch.sh
  scripts/ops/venue_pnl_gaps.py --mode real --json    # one item per real-money gap
  scripts/ops/venue_pnl_gaps.py --mode demo --account bybit_1 --kind gap --max-age-days 7 --check
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


def _is_real(row: Dict[str, Any]) -> bool:
    return str(row.get("account_class") or "").lower() == "real_money"


def select(rows: List[Dict[str, Any]], *, mode: str, account: str | None = None,
           kind: str | None = None, max_age_days: float | None = None) -> Dict[str, Any]:
    """Filter to one mode (``real`` / ``demo`` / ``all``) and optional account / kind / age."""
    from datetime import datetime, timedelta, timezone

    if mode == "real":
        rows = [r for r in rows if _is_real(r)]
    elif mode == "demo":
        rows = [r for r in rows if not _is_real(r)]
    res = find_items(rows)
    items = res["items"]
    if account:
        items = [i for i in items if i["account_id"] == account]
    if kind:
        items = [i for i in items if i["kind"] == kind]
    if max_age_days is not None:
        cut = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        def _recent(i):
            try:
                return datetime.fromisoformat(str(i.get("closed_at")).replace("Z", "+00:00")) >= cut
            except ValueError:
                return True  # an unreadable time is kept: never hidden by the filter
        items = [i for i in items if _recent(i)]
    if mode == "real":
        for i in items:
            i["item_id"] = f"VPG-{i['id']}"
    groups: Dict[str, List[Any]] = collections.defaultdict(list)
    for i in items:
        groups[f"{i['account_id']}|{i['kind']}"].append(i["id"])
    res.update(mode=mode, items=items, groups={k: sorted(v) for k, v in sorted(groups.items())},
               n_gap=sum(1 for i in items if i["kind"] == "gap"),
               n_unmatched=sum(1 for i in items if i["kind"] == "unmatched"),
               filter={"account": account, "kind": kind, "max_age_days": max_age_days})
    return res


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--journal-json")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--mode", choices=("all", "real", "demo"), default="all")
    ap.add_argument("--account")
    ap.add_argument("--kind", choices=("gap", "unmatched"))
    ap.add_argument("--max-age-days", type=float)
    ap.add_argument("--check", action="store_true",
                    help="exit 0 when the selection has no items, else 1")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = select(_load(a.journal_json, a.limit), mode=a.mode, account=a.account,
                 kind=a.kind, max_age_days=a.max_age_days)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    if a.check:
        n = len(res["items"])
        if not a.json:
            print(f"check: {n} item(s) in selection {res['filter']} (mode={a.mode})")
        return 0 if n == 0 else 1
    if a.json:
        return 0
    print(res["population"])
    print(f"mode={res['mode']} diagnosis items: {res['n_gap']} gap(s), {res['n_unmatched']} unmatched")
    for k, ids in res["groups"].items():
        print(f"  {k}: {len(ids)} -> trades {ids}")
    for i in res["items"]:
        print("  ", json.dumps(i, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
