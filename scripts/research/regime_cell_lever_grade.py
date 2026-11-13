#!/usr/bin/env python3
"""Grade a REGIME OFF-CELL as an iteration lever -- row DEMO-FLOOR-ITER-20261113 (AM-ML 2026-11-13 21:12Z).

A regime off-cell (config/regime_policy.yaml, the router's 1-D ADX trend axis: chop <20, transitional 20-25,
trending >=25) drops a leg's intents in one regime. As a lever it must clear the regime-selectivity skill's rules AND
the demo-floor iteration bar, on the record window and on a confirmation window no diagnosis read:

  record window (regime_cell_walkforward --out-json + its workdir, forming replay):
    R1 NO COSMETIC CELL  every gated side is ``*_stable_drag`` in the cell (pooled < 0 AND strict majority-negative
                         under every member of the walk-forward's fixed FOLD_PANEL) -- the cell loses on its own
    R2 STAGE 0           the leg WITHOUT the cell (every trade outside the gated cell / sides) passes Stage 0:
                         net_r > 0, n >= n_floor, >= fold_majority of n_folds equal calendar folds positive
    R3 BEATS BASELINE    that gated book's net_r exceeds the ungated book's
  confirmation window (the same, on the equal-length window before the record window):
    C1  the gated sides' pooled net R in the cell is < 0
    C2  the gated book's net_r is > 0 and above the ungated book's

  PASS iff R1-R3 and C1-C2. FAIL iff all are measured and one fails. INDETERMINATE when a run errored, a gated side is
  under the walk-forward's n floor (its verdict is ``insufficient_n``), or the gated book is under n_floor.

Which sides the cell gates is registered by the unit (``--sides``), never picked from the result.
Writes ``<out>/verdict.json`` (E5). Tier 1: research tooling; reads the walk-forward outputs only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def tag_all(workdir: Path, strategy: str, resample: str) -> List[Dict[str, Any]]:
    """Every trade of the walk-forward's harness run, regime-tagged by regime_tag_emitted (the router's ADX axis)."""
    trades = workdir / f"{strategy}__wf_trades.jsonl"
    data = workdir / f"{strategy}__wf_data.csv"
    out = workdir / f"{strategy}__wf_all_tagged.jsonl"
    subprocess.run([sys.executable, str(REPO / "scripts/research/regime_tag_emitted.py"), "--trades", str(trades),
                    "--data", str(data), "--resample", resample, "--label", strategy, "--emit-tagged", str(out)],
                   check=True, cwd=str(REPO), capture_output=True)
    return [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]


def book(trades: List[Dict[str, Any]], start: str, end: str, n_folds: int) -> Dict[str, Any]:
    lo, hi = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start), \
        pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end)
    edges = [lo + (hi - lo) * i / n_folds for i in range(n_folds + 1)]
    folds = [0.0] * n_folds
    for t in trades:
        ts = pd.Timestamp(t["entry_time"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        for i in range(n_folds):
            if edges[i] <= ts < edges[i + 1] or (i == n_folds - 1 and ts == hi):
                folds[i] += float(t.get("net_r") or 0.0)
                break
    return {"n": len(trades), "net_r": round(sum(float(t.get("net_r") or 0.0) for t in trades), 4),
            "folds": [round(f, 4) for f in folds], "folds_positive": sum(1 for f in folds if f > 0)}


def split(trades: List[Dict[str, Any]], regime: str, sides: List[str]):
    gated = [t for t in trades if t.get("regime") == regime and t.get("direction") in sides]
    kept = [t for t in trades if not (t.get("regime") == regime and t.get("direction") in sides)]
    return gated, kept


def read_window(res_json: Path, workdir: Path, strategy: str) -> Optional[Dict[str, Any]]:
    if not res_json.exists():
        return None
    r = json.loads(res_json.read_text(encoding="utf-8"))
    if r.get("error"):
        return {"error": r["error"]}
    return r


def grade(rec: Optional[Dict[str, Any]], conf: Optional[Dict[str, Any]], rec_trades, conf_trades, *, regime: str,
          sides: List[str], n_floor: int, n_folds: int, fold_majority: int, rec_win, conf_win, leg: str) -> Dict[str, Any]:
    pop = (f"{leg}: regime off-cell {regime} {sides} on the router's 1-D ADX axis, forming replay; record window "
           f"{rec_win[0]}..{rec_win[1]}, confirmation window {conf_win[0]}..{conf_win[1]}; net of the full cost stack")
    base = {"population": pop, "records": []}
    if not rec or rec.get("error") or not conf or conf.get("error") or rec_trades is None or conf_trades is None:
        why = (rec or {}).get("error") or (conf or {}).get("error") or "a walk-forward run wrote no result"
        return {**base, "verdict": "indeterminate", "read_state": "producer_failed", "n": None, "note": why}
    cv = rec.get("cell_verdict") or {}
    r1, notes, under = True, [], False
    for sd in sides:
        v = cv.get(f"{sd}_verdict")
        if v == "insufficient_n":
            under = True
        drag = bool(cv.get(f"{sd}_stable_drag"))
        r1 = r1 and drag
        notes.append(f"{sd}: pooled {cv.get(f'pooled_{sd}_r')} stable_drag={drag} ({v})")
    g_rec, k_rec = split(rec_trades, regime, sides)
    full_rec, kept_rec = book(rec_trades, *rec_win, n_folds), book(k_rec, *rec_win, n_folds)
    r2 = kept_rec["net_r"] > 0 and kept_rec["n"] >= n_floor and kept_rec["folds_positive"] >= fold_majority
    r3 = kept_rec["net_r"] > full_rec["net_r"]
    g_conf, k_conf = split(conf_trades, regime, sides)
    full_conf, kept_conf = book(conf_trades, *conf_win, n_folds), book(k_conf, *conf_win, n_folds)
    cell_conf = round(sum(float(t.get("net_r") or 0.0) for t in g_conf), 4)
    c1 = cell_conf < 0
    c2 = kept_conf["net_r"] > 0 and kept_conf["net_r"] > full_conf["net_r"]
    recs = [
        {"leg": f"{leg}@ungated", "role": "baseline", "verdict": "pass" if full_rec["net_r"] > 0 else "fail",
         "read_state": "measured", "n": full_rec["n"], "net_r": full_rec["net_r"], "folds": full_rec["folds"],
         "population": f"{leg} ungated, record window", "note": f"confirmation-window net_r {full_conf['net_r']}"},
        {"leg": f"{leg}@{regime}_off", "role": "candidate", "verdict": "pass" if (r2 and r3) else "fail",
         "read_state": "measured", "n": kept_rec["n"], "net_r": kept_rec["net_r"], "folds": kept_rec["folds"],
         "folds_positive": kept_rec["folds_positive"], "n_folds": n_folds,
         "population": f"{leg} without the {regime} {sides} cell, record window",
         "note": f"confirmation-window net_r {kept_conf['net_r']} (n {kept_conf['n']})"},
        {"leg": f"{leg}@{regime}_cell", "role": "dropped_cell", "verdict": "pass" if r1 else "fail",
         "read_state": "measured", "n": len(g_rec), "net_r": round(sum(float(t.get('net_r') or 0) for t in g_rec), 4),
         "population": f"{leg} trades in the {regime} {sides} cell, record window",
         "note": "; ".join(notes) + f"; confirmation-window cell net_r {cell_conf} (n {len(g_conf)})"},
    ]
    n_total = full_rec["n"]
    clauses = {"R1_no_cosmetic_cell": r1, "R2_gated_stage0": r2, "R3_beats_ungated": r3,
               "C1_cell_loses_on_confirmation": c1, "C2_gated_book_holds_on_confirmation": c2}
    if under or kept_rec["n"] < n_floor:
        return {**base, "records": recs, "verdict": "indeterminate", "read_state": "measured", "n": n_total,
                "clauses": clauses, "note": "a gated side is under the walk-forward's n floor or the gated book is "
                                            f"under n_floor {n_floor} -- no claim"}
    ok = all(clauses.values())
    failed = [k for k, v in clauses.items() if not v]
    return {**base, "records": recs, "verdict": "pass" if ok else "fail", "read_state": "measured", "n": n_total,
            "clauses": clauses,
            "note": (f"gated book {kept_rec['net_r']}R over n {kept_rec['n']}, {kept_rec['folds_positive']}/{n_folds} folds "
                     f"(ungated {full_rec['net_r']}R); confirmation gated {kept_conf['net_r']}R vs ungated "
                     f"{full_conf['net_r']}R, cell {cell_conf}R; " + ("all clauses hold" if ok else f"fails {failed}"))}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--leg")
    ap.add_argument("--regime", choices=["trending", "transitional", "chop"])
    ap.add_argument("--sides", default="long,short", help="the sides the cell gates, registered by the unit")
    ap.add_argument("--resample", help="the leg's live timeframe (regime_tag_emitted --resample)")
    for flag in ("--record-dir", "--confirm-dir", "--record-start", "--record-end", "--confirm-start", "--confirm-end"):
        ap.add_argument(flag)
    ap.add_argument("--n-floor", type=int, default=30)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--fold-majority", type=int, default=3)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    need = ("out", "leg", "regime", "resample", "record_dir", "confirm_dir", "record_start", "record_end",
            "confirm_start", "confirm_end")
    if any(getattr(a, k) is None for k in need):
        ap.error("missing one of --" + " / --".join(k.replace("_", "-") for k in need))
    sides = [s.strip() for s in a.sides.split(",") if s.strip()]
    rd, cd = Path(a.record_dir), Path(a.confirm_dir)
    rec, conf = read_window(rd / "res.json", rd, a.leg), read_window(cd / "res.json", cd, a.leg)
    rt = ct = None
    try:
        if rec and not rec.get("error"):
            rt = tag_all(rd, a.leg, a.resample)
        if conf and not conf.get("error"):
            ct = tag_all(cd, a.leg, a.resample)
    except (subprocess.CalledProcessError, OSError) as exc:
        rec = {"error": f"regime tag failed: {exc}"}
    v = grade(rec, conf, rt, ct, regime=a.regime, sides=sides, n_floor=a.n_floor, n_folds=a.folds,
              fold_majority=a.fold_majority, rec_win=(a.record_start, a.record_end),
              conf_win=(a.confirm_start, a.confirm_end), leg=a.leg)
    os.makedirs(a.out, exist_ok=True)
    (Path(a.out) / "verdict.json").write_text(json.dumps(v, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "n", "note")}, default=str))
    return 0


def _self_test() -> int:
    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    def t(day, side, r, regime):
        return {"entry_time": f"2026-0{day // 28 + 1}-{day % 28 + 1:02d} 00:00:00+00:00", "direction": side,
                "net_r": r, "regime": regime}
    win = ("2026-01-01", "2026-05-01")
    good = [t(d, "long", 1.0, "trending") for d in range(0, 112, 3)] + [t(d, "short", -2.0, "chop") for d in range(1, 112, 9)]
    drag = {"cell_verdict": {"long_stable_drag": True, "short_stable_drag": True, "long_verdict": "stable_drag",
                             "short_verdict": "stable_drag", "pooled_long_r": -5, "pooled_short_r": -9}}
    kw = dict(regime="chop", sides=["long", "short"], n_floor=10, n_folds=4, fold_majority=3, rec_win=win,
              conf_win=win, leg="L")
    g = grade(drag, drag, good, good, **kw)
    check("losing cell, healthy remainder on both windows -> pass", g["verdict"] == "pass")
    cosmetic = {"cell_verdict": {**drag["cell_verdict"], "short_stable_drag": False, "short_verdict": "fold_sensitive"}}
    g = grade(cosmetic, drag, good, good, **kw)
    check("a gated side without stable drag (cosmetic cell) -> fail", g["verdict"] == "fail"
          and not g["clauses"]["R1_no_cosmetic_cell"])
    bad_conf = [t(d, "long", -1.0, "trending") for d in range(0, 112, 3)] + [t(d, "short", -2.0, "chop") for d in range(1, 112, 9)]
    g = grade(drag, drag, good, bad_conf, **kw)
    check("a record-window pass the confirmation window does not hold -> fail", g["verdict"] == "fail"
          and not g["clauses"]["C2_gated_book_holds_on_confirmation"])
    thin = {"cell_verdict": {**drag["cell_verdict"], "long_verdict": "insufficient_n"}}
    g = grade(thin, drag, good, good, **kw)
    check("a gated side under the walk-forward n floor -> indeterminate", g["verdict"] == "indeterminate")
    g = grade({"error": "fetch failed"}, drag, None, good, **kw)
    check("a run that errored -> indeterminate / producer_failed", g["read_state"] == "producer_failed")
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
