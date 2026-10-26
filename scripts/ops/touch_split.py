#!/usr/bin/env python3
# wiring: .github/workflows/soak-book-grade-weekly.yml (after soak_report.py) -> docs/claude/work/SOAK-TOUCH-SPLIT.md;
#         also run ad hoc against a diag pull. Projects over trades.notes.sl_amends (scripts/ops/touch_record.py);
#         adds NO store.
"""The bybit_1 sandbox touched/untouched split (DESK-12-SANDBOX, design § 3.6).

Per (account, leg) and per split (untouched | touched) it reports, over a STATED population:

  * closed trades, the touch records (who amended what, from -> to, verdict);
  * live-vs-backtest: ``scripts/research/live_vs_backtest.check_leg`` on that split's per-trade R
    (``r_multiple_provenanced`` over the order package's declared risk), same bootstrap, same verdicts;
  * cost fidelity: R3's per-cell verdict for the untouched split with the touched split beside it
    (``r3_cost_fidelity.run`` -> ``cells[].touched_split``), when an R3 record is supplied.

The leg's mechanical soak counts untouched trades only (``soak_state.evaluate``); this report is where the
touched ones are SEEN. Desk grading (§ 4.7) reads the same split: touched = the applied effect, untouched =
the control.

A touched count of 0 is "no apply has landed in this population", not "we could not look" — the
``population`` block says how many trade rows and how many carried a parseable notes blob.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "research"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_vs_backtest as lvb  # noqa: E402
import touch_record  # noqa: E402
from src.runtime.r_provenance import r_multiple_provenanced  # noqa: E402

SANDBOX_ACCOUNTS = ("bybit_1",)


def _contract_value(symbol: Any) -> Any:
    from src.runtime.local_pnl import contract_value_usd_for  # noqa: PLC0415
    return contract_value_usd_for(symbol)


def _pkg_meta(pkg: Optional[Dict[str, Any]]) -> Any:
    if not pkg:
        return None
    m = pkg.get("meta")
    if isinstance(m, str):
        try:
            return json.loads(m)
        except ValueError:
            return None
    return m


def _trade_r(t: Dict[str, Any], pkg: Optional[Dict[str, Any]]) -> Optional[float]:
    r, _basis = r_multiple_provenanced(
        {"pnl": t.get("pnl"), "entry_price": t.get("entry_price"), "stop_loss": t.get("stop_loss"),
         "take_profit_1": t.get("take_profit_1"), "direction": t.get("direction"),
         "qty": t.get("position_size"), "package_meta": _pkg_meta(pkg)},
        _contract_value(t.get("symbol")))
    return r


def _row(trades: List[Dict[str, Any]], pkgs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    rs = [r for r in (_trade_r(t, pkgs.get(str(t.get("order_package_id")))) for t in trades) if r is not None]
    return {"trades": len(trades), "rTradeCount": len(rs), "totalR": round(sum(rs), 4) if rs else None}


def cost_cells(rec: Optional[Dict[str, Any]]) -> Dict[tuple, Dict[str, Any]]:
    """``{(account, leg): R3 cell}`` from either an ``r3_cost_fidelity.run()`` record or an R5
    ``soak_book_grade`` record (its ``legs[].cost_fidelity`` IS the R3 cell)."""
    out: Dict[tuple, Dict[str, Any]] = {}
    if not rec:
        return out
    for leg, ent in (rec.get("per_leg") or {}).items():
        for c in ent.get("cells") or []:
            out[(c.get("account_id"), leg)] = c
    for row in rec.get("legs") or []:
        if isinstance(row.get("cost_fidelity"), dict):
            out[(row.get("account_id"), row.get("strategy"))] = row["cost_fidelity"]
    return out


def grading_sets(touched: List[Dict[str, Any]], untouched: List[Dict[str, Any]],
                 pkgs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """DESK grading hook (design § 4.7 "In-trade ... touched and untouched trades split"): the APPLIED
    effect is each touched trade, keyed by its touch's ``decision_id`` (else ``review_id``); the CONTROL is the
    same (account, leg)'s untouched trades. Nothing is graded here -- DESK-9 consumes these sets."""
    ctl = [r for r in (_trade_r(t, pkgs.get(str(t.get("order_package_id")))) for t in untouched) if r is not None]
    return {
        "applied": [{"key": (tc[-1].get("decision_id") or tc[-1].get("review_id")), "trade_id": t.get("id"),
                     "order_package_id": t.get("order_package_id"),
                     "r": _trade_r(t, pkgs.get(str(t.get("order_package_id")))),
                     "touches": tc}
                    for t in touched for tc in [touch_record.touches(t)]],
        "control": {"n": len(ctl), "mean_r": round(sum(ctl) / len(ctl), 4) if ctl else None},
    }


def build(trades: List[Dict[str, Any]], packages: List[Dict[str, Any]], *,
          accounts: tuple = SANDBOX_ACCOUNTS, cost: Optional[Dict[str, Any]] = None,
          draws: int = lvb.DRAWS) -> Dict[str, Any]:
    pkgs = {str(p.get("order_package_id")): p for p in packages}
    cmap = cost_cells(cost)
    closed = [t for t in trades if t.get("status") == "closed" and not t.get("is_backtest")
              and t.get("account_id") in accounts]
    legs: Dict[tuple, List[Dict[str, Any]]] = {}
    for t in closed:
        legs.setdefault((t["account_id"], t.get("strategy_name")), []).append(t)
    out: List[Dict[str, Any]] = []
    all_touches: List[Dict[str, Any]] = []
    for (acct, leg), rows in sorted(legs.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        untouched, touched = touch_record.split(rows)
        cell = cmap.get((acct, leg))
        entry: Dict[str, Any] = {"account": acct, "leg": leg, "split": {}}
        for name, group in (("untouched", untouched), ("touched", touched)):
            row = _row(group, pkgs)
            lv = lvb.check_leg(leg, name, row if group else None, draws=draws)
            entry["split"][name] = {
                "closed": len(group), "r_trades": row["rTradeCount"], "total_r": row["totalR"],
                "live_vs_backtest": {k: lv.get(k) for k in ("verdict", "why", "p5", "p50", "p95",
                                                             "live_percentile", "backtest_n")},
                "cost_fidelity": (None if cell is None else
                                  (cell if name == "untouched" else cell.get("touched_split")))}
        entry["touch_records"] = [x for t in touched for x in touch_record.touches(t)]
        entry["grading"] = grading_sets(touched, untouched, pkgs)
        all_touches += entry["touch_records"]
        out.append(entry)
    n_closed = len(closed)
    return {
        "population": {
            "accounts": list(accounts),
            "trade_rows_in_input": len(trades),
            "closed_non_backtest_on_accounts": n_closed,
            "legs": len(out),
            "touched_trades": sum(e["split"]["touched"]["closed"] for e in out),
            "untouched_trades": sum(e["split"]["untouched"]["closed"] for e in out),
            "packages_in_input": len(packages),
            "closed_with_package_in_input": sum(1 for t in closed if str(t.get("order_package_id")) in pkgs),
            "cost_record_supplied": cost is not None, "cost_cells": len(cmap),
        },
        "touch_records": all_touches,
        "legs": out,
    }


def render(b: Dict[str, Any]) -> str:
    p = b["population"]
    lines = ["# bybit_1 touched / untouched split\n",
             f"Population: {p['closed_non_backtest_on_accounts']} closed non-backtest trades on {p['accounts']} "
             f"(of {p['trade_rows_in_input']} rows read), {p['legs']} legs; "
             f"**{p['touched_trades']} touched / {p['untouched_trades']} untouched**. "
             f"{p['closed_with_package_in_input']} of them match one of {p['packages_in_input']} packages read (R needs the package's declared risk; others fall back to the stored stop). "
             f"R3 cost cells: {p['cost_cells']} ({'record supplied' if p['cost_record_supplied'] else 'NOT supplied, cost_fidelity = null'}).\n",
             "| account | leg | untouched n | touched n | untouched LvB | touched LvB | cost untouched | cost touched |", "|---|---|--:|--:|---|---|---|---|"]
    for e in b["legs"]:
        u, t = e["split"]["untouched"], e["split"]["touched"]
        lines.append(f"| {e['account']} | {e['leg']} | {u['closed']} | {t['closed']} | "
                     f"{u['live_vs_backtest']['verdict']} | {t['live_vs_backtest']['verdict']} | "
                     f"{(u['cost_fidelity'] or {}).get('verdict', '—')} | {(t['cost_fidelity'] or {}).get('verdict', '—')} |")
    if b["touch_records"]:
        lines += ["", "## Touch records", "| package | account | applied_at | before | after | verdict | source | review/decision |",
                  "|---|---|---|--:|--:|---|---|---|"]
        for r in b["touch_records"]:
            lines.append(f"| {r['order_package_id']} | {r['account']} | {r['applied_at']} | {r['level_before']} | "
                         f"{r['level_after']} | {r['verdict']} | {r['source']} | {r['review_id'] or r['decision_id']} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trades", type=Path, required=True, help="diag journal?table=trades JSON")
    ap.add_argument("--packages", type=Path, required=True, help="diag journal?table=order_packages JSON")
    ap.add_argument("--cost", type=Path, default=None,
                    help="an r3_cost_fidelity.run() JSON or an R5 soak_book_grade JSON (adds cost fidelity)")
    ap.add_argument("--out", type=Path, default=None, help="write the rendered markdown here")
    ap.add_argument("--account", action="append", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    b = build(json.loads(a.trades.read_text()), json.loads(a.packages.read_text()),
              accounts=tuple(a.account or SANDBOX_ACCOUNTS),
              cost=json.loads(a.cost.read_text()) if a.cost else None)
    text = json.dumps(b, indent=1, default=str) if a.json else render(b)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
