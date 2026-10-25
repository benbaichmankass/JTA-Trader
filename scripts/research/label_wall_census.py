#!/usr/bin/env python3
# wiring: research/queue units declaring run.command ["python3","scripts/research/label_wall_census.py",...]
#         via the research-queue dispatcher (compute: needs_vm_data -> research-script-run-trainer.yml); the journal never leaves the VM
"""Per (strategy, symbol) cell: where does the label count stand against the M23 P2 gate? (ML-LABEL-WALL, plan item ML-D2)

WHY (lane ML-HEALTH-BUILDS-1027, 2026-10-25). Every trade-outcome / meta-label / conviction head is label-bound, and
nothing MEASURED where each cell stood against its gate, so "wait for accrual" was unverified (backtest rows are not
schedule-bounded). RQ-20261011-17f4-02 asked for the census and was blocked on this script.

PER CELL (strategy_name, symbol)
  n_measured                  closed, non-backtest journal rows whose pnl provenance is MEASURED
                              (`src.runtime.provenance.classify_pnl` over trades.notes; ESTIMATED / FABRICATED / UNVERIFIED
                              are counted beside it, never folded in)
  n_backtest                  rows of the NEWEST committed test-result ledger per leg that carry this cell
                              (`comms/strategy_evidence/runs/*/<leg>__trades.jsonl`, resample sub-ledgers excluded)
  n_backtest_parity_held      n_backtest ONLY where `--parity` says the cell's backtest-vs-live feature parity HELD; with no
                              parity file it is 0 and the rows sit in `n_backtest_parity_unverified`
  n_pooled                    n_measured + n_backtest_parity_held
GLOBAL: cells with n_pooled >= --pooled-gate (300, M23 P2); total MEASURED n against --conviction-gate (1000, ML-PRODUCERS M5).
Verdict by RULE-RQ1011-17F4-02-LABEL-GATE-CENSUS: GO (a cell qualifies with parity held) / PARK (none does; the record
carries each cell's observed accrual rate and the days to the gate at that rate, not a guessed date) / NEEDS-BACKFILL
(evaluated only where a `--coverage` file says market_raw coverage is the short side). Thresholds are CLI flags for a test;
the unit never overrides them.

HONEST LIMITS, STATED IN THE RECORD
  * The journal calls a family `strategy_name`; ledgers carry `strategy` and the leg name. Cells are joined on the literal
    (strategy, symbol) pair; `cells_in_both_sources` says how many matched, so a naming mismatch shows as a low overlap, not
    as a silent zero.
  * Parity is not measured here. It is the product of POOLING-PARITY-INSTRUMENT / ML-PARITY-FC-SHADOWLOG; until a parity file
    exists no cell can read GO, and the record says how many cells WOULD qualify if parity held.
  * The conviction clause also needs an offline stacker beating the majority baseline; this script reports only the n
    clause (`conviction_n_met`) and says the stacker is unevaluated.

Read-only (sqlite opened `mode=ro`); trains nothing, edits no threshold. Tier-1 research code. Writes `<out>/verdict.json`
in the shape script_run.py --derive-record consumes.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime import provenance as P  # noqa: E402

DEFAULT_LEDGERS = "comms/strategy_evidence/runs/*/*__trades.jsonl"
RESAMPLE_RE = re.compile(r"__B\d+$|__M$")
POOLED_GATE = 300
CONVICTION_GATE = 1000

Cell = Tuple[str, str]


def key(c: Cell) -> str:
    return f"{c[0]}|{c[1]}"


# ── sources ───────────────────────────────────────────────────────────────────
def read_journal(db: str) -> Tuple[Dict[Cell, Dict[str, Any]], Optional[str]]:
    """{cell: {measured, estimated, fabricated, unverified, first, last}} over closed non-backtest rows, or ({}, why)."""
    if not db or not os.path.isfile(db):
        return {}, f"journal not found at {db or '(unresolved)'}"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT strategy_name, symbol, notes, pnl, timestamp, closed_at FROM trades "
            "WHERE status = 'closed' AND COALESCE(is_backtest, 0) = 0").fetchall()
    except sqlite3.Error as exc:
        return {}, f"journal unreadable: {type(exc).__name__}: {exc}"
    out: Dict[Cell, Dict[str, Any]] = {}
    for r in rows:
        c = (str(r["strategy_name"] or "?"), str(r["symbol"] or "?"))
        bucket, _why = P.classify_pnl({"notes": r["notes"], "pnl": r["pnl"]})
        d = out.setdefault(c, {P.MEASURED: 0, P.ESTIMATED: 0, P.FABRICATED: 0, P.UNVERIFIED: 0, "first": None, "last": None})
        d[bucket] = d.get(bucket, 0) + 1
        t = str(r["closed_at"] or r["timestamp"] or "")
        if t:
            d["first"] = t if d["first"] is None or t < d["first"] else d["first"]
            d["last"] = t if d["last"] is None or t > d["last"] else d["last"]
    con.close()
    return out, None


def read_ledgers(glob_pat: str) -> Tuple[Dict[Cell, int], int]:
    """{cell: n rows} over the newest ledger per leg, and the number of legs read."""
    newest: Dict[str, str] = {}
    pat = glob_pat if os.path.isabs(glob_pat) else str(REPO / glob_pat)
    for f in sorted(glob.glob(pat)):
        leg = os.path.basename(f)[: -len("__trades.jsonl")]
        if RESAMPLE_RE.search(leg):
            continue
        newest[leg] = f
    cells: Dict[Cell, int] = {}
    for f in newest.values():
        for ln in Path(f).read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            c = (str(r.get("strategy") or "?"), str(r.get("symbol") or "?"))
            cells[c] = cells.get(c, 0) + 1
    return cells, len(newest)


def _days(first: Optional[str], last: Optional[str]) -> Optional[float]:
    try:
        a = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max((b - a).total_seconds() / 86400.0, 0.0)


# ── census ────────────────────────────────────────────────────────────────────
def census(journal: Dict[Cell, Dict[str, Any]], ledgers: Dict[Cell, int], parity: Dict[str, bool],
           coverage_short: Dict[str, bool], *, pooled_gate: int, conviction_gate: int) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for c in sorted(set(journal) | set(ledgers)):
        j = journal.get(c, {})
        n_meas = int(j.get(P.MEASURED, 0))
        n_bt = int(ledgers.get(c, 0))
        held = bool(parity.get(key(c)))
        n_held = n_bt if held else 0
        n_pooled = n_meas + n_held
        span = _days(j.get("first"), j.get("last"))
        rate = (n_meas / span) if span and span > 0 else None
        days_to_gate = None
        if n_pooled < pooled_gate and rate:
            days_to_gate = round((pooled_gate - n_pooled) / rate, 1)
        rows.append({
            "strategy": c[0], "symbol": c[1], "n_measured": n_meas,
            "n_estimated": int(j.get(P.ESTIMATED, 0)), "n_fabricated": int(j.get(P.FABRICATED, 0)),
            "n_unverified": int(j.get(P.UNVERIFIED, 0)),
            "n_backtest": n_bt, "n_backtest_parity_held": n_held,
            "n_backtest_parity_unverified": 0 if held else n_bt,
            "parity_state": "held" if held else ("failed" if key(c) in parity else "unmeasured"),
            "n_pooled": n_pooled, "in_journal": c in journal, "in_ledgers": c in ledgers,
            "measured_per_day": None if rate is None else round(rate, 4), "days_to_gate_at_observed_rate": days_to_gate,
            "meets_gate": n_pooled >= pooled_gate and held,
            "would_meet_gate_if_parity_held": (n_meas + n_bt) >= pooled_gate,
            "short_only_on_coverage": bool(coverage_short.get(key(c))) and n_pooled < pooled_gate,
        })
    n_meas_total = sum(r["n_measured"] for r in rows)
    go = [r for r in rows if r["meets_gate"]]
    backfill = [r for r in rows if r["short_only_on_coverage"]]
    if go:
        rule = "GO"
    elif backfill:
        rule = "NEEDS-BACKFILL"
    else:
        rule = "PARK"
    return {
        "rule_verdict": rule, "cells": rows, "n_cells": len(rows),
        "cells_in_both_sources": sum(1 for r in rows if r["in_journal"] and r["in_ledgers"]),
        "n_cells_meeting_gate": len(go), "n_cells_that_would_meet_gate_if_parity_held": sum(1 for r in rows if r["would_meet_gate_if_parity_held"]),
        "n_measured_total": n_meas_total, "conviction_n_met": n_meas_total >= conviction_gate,
        "conviction_stacker": "unevaluated (needs an offline stacker beating the majority baseline under purged CV)",
        "thresholds": {"pooled_gate": pooled_gate, "conviction_gate": conviction_gate},
    }


def to_record(c: Dict[str, Any], *, journal_why: Optional[str], n_legs: int) -> Dict[str, Any]:
    if journal_why is not None:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0,
                "population": f"no journal read ({journal_why}): NOTHING COUNTED", "measurement": {"journal": journal_why},
                "note": "an unreadable journal is 'we could not look', not 'zero labels'"}
    verdict = {"GO": "pass", "PARK": "fail", "NEEDS-BACKFILL": "indeterminate"}[c["rule_verdict"]]
    return {
        "verdict": verdict, "read_state": "measured", "n": c["n_measured_total"],
        "population": (f"{c['n_cells']} (strategy, symbol) cells: closed non-backtest journal rows (MEASURED n={c['n_measured_total']}) "
                       f"+ newest committed ledger of {n_legs} legs"),
        "measurement": {**c, "rule_verdict": c["rule_verdict"]},
        "note": (f"rule verdict {c['rule_verdict']}: {c['n_cells_meeting_gate']} cell(s) meet n_pooled>={c['thresholds']['pooled_gate']} "
                 f"with parity held; {c['n_cells_that_would_meet_gate_if_parity_held']} would if parity held (parity unmeasured here); "
                 f"{c['cells_in_both_sources']} cell(s) appear in both sources. Trains nothing; no threshold edited."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--journal")
    ap.add_argument("--ledgers", default=DEFAULT_LEDGERS)
    ap.add_argument("--parity", help='JSON {"<strategy>|<symbol>": true|false} of backtest-vs-live parity verdicts')
    ap.add_argument("--coverage", help='JSON {"<strategy>|<symbol>": true} where market_raw coverage is the short side')
    ap.add_argument("--pooled-gate", type=int, default=POOLED_GATE)
    ap.add_argument("--conviction-gate", type=int, default=CONVICTION_GATE)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    from src.utils.paths import trade_journal_db_path
    journal, why = read_journal(a.journal or trade_journal_db_path())
    ledgers, n_legs = read_ledgers(a.ledgers)
    parity = json.loads(Path(a.parity).read_text()) if a.parity else {}
    coverage = json.loads(Path(a.coverage).read_text()) if a.coverage else {}
    if why is not None:
        rec = to_record({}, journal_why=why, n_legs=n_legs)
    else:
        rec = to_record(census(journal, ledgers, parity, coverage, pooled_gate=a.pooled_gate,
                               conviction_gate=a.conviction_gate), journal_why=None, n_legs=n_legs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"label_wall_census: verdict={rec['verdict']} read_state={rec['read_state']} n={rec['n']}")
    return 0


def _self_test() -> int:
    ok = True
    j = {("trend", "BTCUSDT"): {P.MEASURED: 120, P.ESTIMATED: 5, P.FABRICATED: 0, P.UNVERIFIED: 2,
                                 "first": "2026-09-01T00:00:00+00:00", "last": "2026-10-01T00:00:00+00:00"}}
    led = {("trend", "BTCUSDT"): 400, ("pullback", "SOLUSDT"): 50}
    c0 = census(j, led, {}, {}, pooled_gate=300, conviction_gate=1000)
    c1 = census(j, led, {"trend|BTCUSDT": True}, {}, pooled_gate=300, conviction_gate=1000)
    if c0["rule_verdict"] == "PARK" and c0["n_cells_that_would_meet_gate_if_parity_held"] == 1:
        print("  PASS  no parity evidence -> PARK, and the would-qualify count is reported")
    else:
        print(f"  FAIL  no-parity read {c0['rule_verdict']}")
        ok = False
    if c1["rule_verdict"] == "GO" and {r["strategy"]: r for r in c1["cells"]}["trend"]["n_pooled"] == 520:
        print("  PASS  parity held -> pooled 120+400 reaches the gate -> GO")
    else:
        print(f"  FAIL  parity-held read {c1['rule_verdict']}")
        ok = False
    r = to_record({}, journal_why="journal not found", n_legs=0)
    if r["read_state"] == "no_data" and r["verdict"] == "not_applicable":
        print("  PASS  unreadable journal is no_data, never zero labels")
    else:
        ok = False
    print("label_wall_census self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
