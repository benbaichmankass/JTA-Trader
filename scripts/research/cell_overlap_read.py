#!/usr/bin/env python3
# wiring: manual-only - run by queue unit RQ-20261119-e6b2-01 (research-script-run.yml, once the manager merges it); no schedule consumes it.
"""P1-ATM-sol4h-b-overlap: are the PASSING basket-B cells of sol_4h (RQ-20261026-1b57-08) the same bet as a live crypto leg?

Registered BEFORE any run: unit RQ-20261119-e6b2-01 decision_rule RULE-RQ20261119E6B2-01-SOL4H-B-OVERLAP (lane QUEUE-FILL-STANDING-W47b, manager
approval 2026-11-19 04:42Z: 'Author the overlap read plus one disjoint-window confirmation, both registered before any run').

WHAT IT READS (committed data only, no network): the per-trade rows of the three passing cells of 1b57-08 (AVAXUSDT, NEARUSDT, ETCUSDT; run 40544537821,
comms/research/RQ-20261026-1b57-08/40544537821/cells/trend_<SYM>_4h_B__trades.jsonl) against the committed per-trade corpora of the live crypto legs
(comms/strategy_evidence/ltr_corpus/): ada_pullback_2h, xrp_pullback_2h, trend_donchian_eth_4h, trend_donchian_xrp_4h, trend_donchian_eth_prop,
trend_donchian_sol_prop. ml_entry (a pooled multi-symbol model leg) and the non-crypto legs are not read.
STATISTIC per (cell, live leg): the Pearson correlation of the DAILY realised net R (a trade's net R booked on its exit date, 0 on days with no exit)
over the calendar window both series cover; reported with the number of days. Also reported, NOT graded: the share of the cell's trades whose
[entry, exit] window overlaps an open same-direction trade of that leg.
BAR: a cell is REDUNDANT with a leg iff |corr| > 0.30 on >= 250 common days. The unit PASSES iff no passing cell is redundant with any live leg
(the cells are a different bet from the live book); FAILS iff at least one cell is redundant with at least one leg (named); INDETERMINATE iff fewer
than 2 of the 3 cells have >= 250 common days with at least 4 of the 6 legs. pass_action: the prop EV/survival gate and a re-entry case for the
non-redundant cells (never a roster act). fail_action: the redundant cells are dropped from the candidate list; the rest go on. No gate is added.
Tier-1 research tooling: reads committed files, writes under --out. Provenance: every number is MEASURED when a run lands; none is in this file.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
RULE_ID = "RULE-RQ20261119E6B2-01-SOL4H-B-OVERLAP"
CELL_DIR = REPO / "comms" / "research" / "RQ-20261026-1b57-08" / "40544537821" / "cells"
CELLS = ("AVAXUSDT", "NEARUSDT", "ETCUSDT")
LEG_DIR = REPO / "comms" / "strategy_evidence" / "ltr_corpus"
LEGS = ("ada_pullback_2h", "xrp_pullback_2h", "trend_donchian_eth_4h", "trend_donchian_xrp_4h", "trend_donchian_eth_prop", "trend_donchian_sol_prop")
CORR_BAR = 0.30
MIN_DAYS = 250
MIN_LEGS_PER_CELL = 4
MIN_CELLS = 2


def _t(s: Any) -> datetime:
    return datetime.fromisoformat(str(s))


def load(path: Path) -> List[dict]:
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    out = []
    for r in rows:
        if not r.get("entry_time") or not r.get("exit_time") or r.get("net_r") is None:
            continue
        out.append({"entry": _t(r["entry_time"]), "exit": _t(r["exit_time"]), "net_r": float(r["net_r"]),
                    "dir": str(r.get("direction") or r.get("side") or "")})
    out.sort(key=lambda t: t["entry"])
    return out


def daily(trades: Sequence[dict]) -> Dict[str, float]:
    d: Dict[str, float] = {}
    for t in trades:
        k = t["exit"].strftime("%Y-%m-%d")
        d[k] = d.get(k, 0.0) + t["net_r"]
    return d


def corr_pair(a: Sequence[dict], b: Sequence[dict]) -> Dict[str, Any]:
    """Pearson correlation of the two daily realised-R series over the calendar window BOTH cover (0 on a day without an exit)."""
    if not a or not b:
        return {"corr": None, "days": 0}
    lo = max(min(t["entry"] for t in a), min(t["entry"] for t in b)).date()
    hi = min(max(t["exit"] for t in a), max(t["exit"] for t in b)).date()
    if hi <= lo:
        return {"corr": None, "days": 0}
    da, db = daily(a), daily(b)
    xs, ys, d = [], [], lo
    while d <= hi:
        k = d.strftime("%Y-%m-%d")
        xs.append(da.get(k, 0.0))
        ys.append(db.get(k, 0.0))
        d += timedelta(days=1)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return {"corr": None, "days": n}
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return {"corr": sxy / math.sqrt(sxx * syy), "days": n}


def concurrent_share(a: Sequence[dict], b: Sequence[dict]) -> Optional[float]:
    """Share of a's trades whose [entry, exit] overlaps an open SAME-direction trade of b (reported, not graded)."""
    if not a:
        return None
    hit = 0
    for t in a:
        if any(u["dir"] == t["dir"] and u["entry"] < t["exit"] and t["entry"] < u["exit"] for u in b):
            hit += 1
    return hit / len(a)


def evaluate(cells: Dict[str, List[dict]], legs: Dict[str, List[dict]]) -> Dict[str, Any]:
    table: Dict[str, Dict[str, Any]] = {}
    redundant, enough = [], 0
    for c, ct in cells.items():
        table[c] = {}
        legs_ok = 0
        for leg, lt in legs.items():
            r = corr_pair(ct, lt)
            r["concurrent_same_dir_share"] = concurrent_share(ct, lt)
            table[c][leg] = r
            if r["corr"] is not None and r["days"] >= MIN_DAYS:
                legs_ok += 1
                if abs(r["corr"]) > CORR_BAR:
                    redundant.append({"cell": c, "leg": leg, "corr": r["corr"], "days": r["days"]})
        if legs_ok >= MIN_LEGS_PER_CELL:
            enough += 1
    res: Dict[str, Any] = {"rule": RULE_ID, "n_cells": len(cells), "n_legs": len(legs), "table": table, "redundant": redundant,
                           "cells_with_enough_coverage": enough}
    if enough < MIN_CELLS:
        res["verdict"], res["verdict_reason"] = "INDETERMINATE", f"only {enough} cells have >= {MIN_DAYS} common days with >= {MIN_LEGS_PER_CELL} legs"
    elif redundant:
        res["verdict"], res["verdict_reason"] = "FAIL", "redundant with a live leg (|corr| > %.2f): %s" % (
            CORR_BAR, "; ".join(f"{x['cell']}~{x['leg']} {x['corr']:+.2f} over {x['days']} d" for x in redundant))
    else:
        res["verdict"], res["verdict_reason"] = "PASS", f"no passing cell has |corr| > {CORR_BAR} with any live leg on >= {MIN_DAYS} common days"
    return res


def self_test() -> int:
    base = datetime(2024, 1, 1)

    def mk(offsets, rs, dirs="long", hold=1):
        return [{"entry": base + timedelta(days=o), "exit": base + timedelta(days=o + hold), "net_r": r, "dir": dirs} for o, r in zip(offsets, rs)]

    days = list(range(0, 400, 2))
    a = mk(days, [(1 if i % 3 else -2) for i in range(len(days))])
    same = mk(days, [(1 if i % 3 else -2) for i in range(len(days))])              # identical R stream -> corr exactly 1
    anti = mk(days, [-(1 if i % 3 else -2) for i in range(len(days))])             # mirrored -> corr exactly -1
    r1 = corr_pair(a, same)
    assert abs(r1["corr"] - 1.0) < 1e-12 and r1["days"] >= 399, r1
    assert abs(corr_pair(a, anti)["corr"] + 1.0) < 1e-12
    # independent streams on disjoint days: corr small, share 0
    other = mk([d + 1 for d in days], [(1 if i % 5 else -3) for i in range(len(days))])
    r2 = corr_pair(a, other)
    assert r2["corr"] is not None and abs(r2["corr"]) < 0.3
    # concurrency: same direction overlapping vs opposite direction
    assert concurrent_share(mk([0], [1], hold=5), mk([2], [1], hold=5)) == 1.0
    assert concurrent_share(mk([0], [1], hold=5), mk([2], [1], dirs="short", hold=5)) == 0.0
    # a series with no variance has no correlation (not 0)
    flat = mk(days, [0.0] * len(days))
    assert corr_pair(a, flat)["corr"] is None
    legs = {f"L{i}": other for i in range(4)}
    ok = evaluate({"c1": a, "c2": a}, legs)
    assert ok["verdict"] == "PASS", ok["verdict_reason"]
    bad = evaluate({"c1": a, "c2": a}, dict(legs, L9=same))
    assert bad["verdict"] == "FAIL" and bad["redundant"], bad
    short = evaluate({"c1": mk([0, 1, 2], [1, 1, 1])}, legs)
    assert short["verdict"] == "INDETERMINATE"
    # the registered inputs exist and parse
    for c in CELLS:
        assert load(CELL_DIR / f"trend_{c}_4h_B__trades.jsonl"), c
    for leg in LEGS:
        assert load(LEG_DIR / f"{leg}__trades.jsonl"), leg
    print("self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("run",))
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode:
        ap.error("mode or --self-test required")
    cells = {c: load(CELL_DIR / f"trend_{c}_4h_B__trades.jsonl") for c in CELLS}
    legs = {leg: load(LEG_DIR / f"{leg}__trades.jsonl") for leg in LEGS}
    res = evaluate(cells, legs)
    out = Path(a.out or ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "cell_overlap_read.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[res["verdict"]], "read_state": "measured",
        "population": f"{res['n_cells']} passing basket-B cells of sol_4h vs {res['n_legs']} live crypto legs, daily realised-R correlation",
        "n": res["cells_with_enough_coverage"], "measurement": res, "note": res["verdict_reason"],
        "data_inputs": ["comms/research/RQ-20261026-1b57-08/40544537821/cells", "comms/strategy_evidence/ltr_corpus"]}, indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("verdict", "verdict_reason", "cells_with_enough_coverage")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
