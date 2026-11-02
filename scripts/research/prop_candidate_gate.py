#!/usr/bin/env python3
"""Prop-replacement candidate gate: Stage 0 at the PROP cost stack, then RULE-P5-GATE-BRK-PER-LEG-V3, for ONE leg.

Lane RESEARCH-PROP-REPLACEMENT-20261031. Nothing here is a new rule: it chains the existing pieces so a candidate leg
is graded by the SAME code the incumbent was (scripts/research/prop_gate.py is the one implementation of V2 + the V3
edge clause; scripts/research/prop_ev_sim.py is the simulator; the ledger comes from exit_lever_ablation.py at the
prop stack, fee 8 / slip 3 / funding 5 bps per 24 h, the arm behind the v1/v2/v3 ledgers).

  python3 scripts/research/prop_candidate_gate.py --leg trend_donchian_xrp_4h --out <dir>
  python3 scripts/research/prop_candidate_gate.py --self-test

Steps: (1) ledger = ``exit_lever_ablation.py --grade stage0`` arm P over --start..--end (skipped with --ledger);
(2) windows: ``3y`` = the whole ledger, ``365d`` = entry_time >= --recent-from; (3) for each of breakout_2 / tradeify_1 /
velotrade_1 x arm cur/ven x seeds 1..N x window one ``prop_ev_sim`` cell; (4) ``prop_gate.aggregate_v2`` + the edge
clause (``edge_ci`` / ``grade_v3``). Output ``<out>/verdict.json`` with ``read_state`` and the per-cell table.

Candidate verdict (the unit's registered rule, stated here only so the output is self-describing):
PASS iff, on the 3y window and arm ``cur``, V3 is PASS on ALL THREE accounts (a swap replaces the incumbent on all three);
CONTESTED if it is PASS but the 365d window has n >= 88 and median EV < 0 on >= 2 accounts; FAIL if any 3y/cur cell is FAIL or
FAIL_EDGE; INDETERMINATE if n < 88 on 3y or the harness failed (read_state producer_failed, never a verdict).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prop_ev_sim as pes  # noqa: E402
import prop_gate as pg  # noqa: E402

ARM_P = "P=--fee-bps-roundtrip=8;--slippage-bps-roundtrip=3;--funding-bps-per-window=5;--funding-window-hours=24"
ACCOUNTS = ("breakout_2", "tradeify_1", "velotrade_1")
ARMS = ("cur", "ven")


def build_ledger(leg: str, out: Path, a: argparse.Namespace) -> Path:
    """Stage 0 at the prop stack through the existing harness; returns the arm-P trade ledger."""
    cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", leg, "--arm", ARM_P,
           "--days", str(a.days), "--start", a.start, "--end", a.end, "--grade", "stage0", "--baseline", "P",
           "--delta-r", "0", "--fold-majority", "3", "--folds", "4", "--n-floor", str(pg.N_FLOOR), "--out", str(out / "ablate")]
    subprocess.run(cmd, check=True, cwd=str(REPO))
    return out / "ablate" / "arms" / "P__trades.jsonl"


def split_windows(rows: list[dict], recent_from: str) -> dict[str, list[dict]]:
    return {"3y": rows, "365d": [r for r in rows if str(r["entry_time"])[:19] >= recent_from[:19]]}


def _cell(job: tuple) -> None:
    leg, win, acct, arm, seed, ledger, cells, lives = job
    c, s, sw = pg.CUR if arm == "cur" else pg.SIM[acct]["ven"]
    sim = pg.SIM[acct]
    outp = cells / f"{leg}__{win}__{acct}__{arm}__s{seed}.json"
    if outp.exists():
        return
    cmd = [sys.executable, str(REPO / "scripts/research/prop_ev_sim.py"), "--trades", f"{leg}={ledger}",
           "--ruleset", str(REPO / f"config/prop_rulesets/{sim['rs']}.yaml"), "--costs", "breakout",
           "--commission-bps-rt", str(c), "--slippage-bps-rt", str(s), "--swap-daily", str(sw), "--swap-model", "prorated",
           "--funded-start", "fresh", "--lev-cap", f"{leg}={pg.lev_cap(acct, leg)}", "--sizing", "start",
           "--risk-pct", str(sim["risk"]), "--dd-switch-frac", "0.8", "--seed", str(seed), "--lives", str(lives),
           "--outer", "2", "--lives-per-outer", str(max(10, lives // 10)), "--modes", "path", "--out", str(outp)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(REPO))


def candidate_verdict(rows: list[dict]) -> tuple[str, str]:
    prim = [r for r in rows if r["window"] == "3y" and r["arm"] == "cur"]
    if len(prim) != len(ACCOUNTS):
        return "INDETERMINATE", f"primary cells {len(prim)} of {len(ACCOUNTS)}"
    vs = [r["v3_verdict"] for r in prim]
    if any(v == "INDETERMINATE" for v in vs):
        return "INDETERMINATE", f"v3 {vs}"
    if any(v in ("FAIL", "FAIL_EDGE") for v in vs):
        return "FAIL", f"v3 {vs}"
    rec = [r for r in rows if r["window"] == "365d" and r["arm"] == "cur" and r["n"] >= pg.N_FLOOR and r["ev_median_usd"] < 0]
    if len(rec) >= 2:
        return "CONTESTED", f"3y PASS on all 3, 365d n>=88 and EV<0 on {len(rec)} accounts"
    return "PASS", f"v3 {vs}"


def _write_verdict(path: Path, v: dict) -> dict:
    """Never write a verdict with no population: the runner would reject it as malformed and hide the real cause
    (PI-20261101-HOPS1447-0001). An empty population becomes read_state producer_failed (the runner accepts only measured|no_data|producer_failed|not_attempted), verdict indeterminate, note could_not_look."""
    if not str(v.get("population") or "").strip():
        v = {**v, "verdict": "indeterminate", "read_state": "producer_failed", "n": v.get("n") or 0,
             "population": "gate produced no population statement: NOT MEASURED",
             "note": "could_not_look: verdict had no population. " + str(v.get("note") or "")}
    path.write_text(json.dumps(v, indent=1) + "\n")
    return v


def run(a: argparse.Namespace) -> dict:
    out = Path(a.out)
    cells = out / "cells"
    cells.mkdir(parents=True, exist_ok=True)
    try:
        ledger = Path(a.ledger) if a.ledger else build_ledger(a.leg, out, a)
        rows = pes.load_rows(ledger)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as read_state producer_failed with the reason, never a verdict
        v = {"verdict": "indeterminate", "read_state": "producer_failed", "n": 0,
             "population": f"{a.leg}: ledger build failed before any measurement (window {a.start}..{a.end}, days={a.days})",
             "note": f"{type(exc).__name__}: {str(exc)[:300]}"}
        return _write_verdict(out / "verdict.json", v)
    wins = split_windows(rows, a.recent_from)
    jobs = []
    for win, wr in wins.items():
        if len(wr) < 2:
            continue
        lp = out / f"{a.leg}_{win}.jsonl"
        lp.write_text("\n".join(json.dumps(r) for r in wr) + "\n")
        jobs += [(a.leg, win, acct, arm, s, lp, cells, a.lives) for acct in ACCOUNTS for arm in ARMS for s in range(1, a.seeds + 1)]
    with ProcessPoolExecutor(a.procs) as ex:
        list(ex.map(_cell, jobs))
    table = pg.aggregate_v2(str(cells.parent) + "/")
    for r in table:
        wr = wins[r["window"]]
        r["edge"] = pg.edge_ci(pg.ledger_net_r(wr, r["account"], r["arm"]))
        r["v3_verdict"] = pg.grade_v3(r["verdict"], r["edge"])
    cv, why = candidate_verdict(table)
    v = {"verdict": {"PASS": "pass", "CONTESTED": "fail", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[cv],
         "candidate_verdict": cv, "read_state": "measured", "leg": a.leg, "n": len(rows), "note": f"{cv}: {why}",
         "population": f"{a.leg} prop-stack ledger n={len(rows)}; 365d n={len(wins['365d'])}; {a.seeds} seeds x {a.lives} lives; "
                       f"{len(table)} graded cells ({len(ACCOUNTS)} accounts x {len(ARMS)} arms x 2 windows)",
         "cells": table}
    return _write_verdict(out / "verdict.json", v)


def _synth_ledger(path: Path, mean_gross: float, n: int = 120) -> None:
    import random
    rnd = random.Random(5)
    rows, t = [], __import__("datetime").datetime(2023, 11, 1, 8)
    for i in range(n):
        g = mean_gross + rnd.gauss(0, 1.0)
        t_in, t_out = t, t + __import__("datetime").timedelta(hours=20)
        rows.append({"strategy": "x", "entry_time": t_in.strftime("%Y-%m-%d %H:%M:%S+00:00"), "symbol": "XRPUSDT",
                     "exit_time": t_out.strftime("%Y-%m-%d %H:%M:%S+00:00"), "entry": 0.5, "sl": 0.49, "direction": "long",
                     "gross_r": round(g, 4), "mfe_r": round(max(g, 0.0) + 0.3, 4), "confidence": 1.0, "regime_weight": 1.0})
        t = t + __import__("datetime").timedelta(days=9)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _self_test() -> int:
    assert candidate_verdict([]) [0] == "INDETERMINATE"
    mk = lambda v, win="3y", n=200, ev=1.0: {"window": win, "arm": "cur", "n": n, "v3_verdict": v, "ev_median_usd": ev}  # noqa: E731
    ok3 = [mk("PASS") for _ in ACCOUNTS]
    assert candidate_verdict(ok3)[0] == "PASS"
    assert candidate_verdict(ok3[:2] + [mk("FAIL_EDGE")])[0] == "FAIL"
    assert candidate_verdict(ok3[:2] + [mk("INDETERMINATE")])[0] == "INDETERMINATE"
    assert candidate_verdict(ok3 + [mk("PASS", "365d", 120, -5.0), mk("PASS", "365d", 120, -5.0)])[0] == "CONTESTED"
    assert candidate_verdict(ok3 + [mk("PASS", "365d", 50, -5.0), mk("PASS", "365d", 50, -5.0)])[0] == "PASS"  # n<88 never contests
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _synth_ledger(td / "neg.jsonl", -0.6)
        ns = argparse.Namespace(leg="synth_neg", out=str(td / "o"), ledger=str(td / "neg.jsonl"), recent_from="2025-10-11 20:00:00",
                                seeds=1, lives=40, procs=3, days=0, start="", end="")
        v = run(ns)
        assert v["read_state"] == "measured" and v["candidate_verdict"] in ("FAIL", "INDETERMINATE"), v["note"]
        assert len(v["cells"]) == len(ACCOUNTS) * len(ARMS) * (2 if len(v["cells"]) > 6 else 1)
        assert all("v3_verdict" in c and "edge" in c for c in v["cells"])
        bad = argparse.Namespace(**{**vars(ns), "out": str(td / "o2"), "ledger": str(td / "missing.jsonl")})
        b = run(bad)
        assert b["read_state"] == "producer_failed" and b["verdict"] == "indeterminate", b
    print("prop_candidate_gate self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leg")
    ap.add_argument("--out")
    ap.add_argument("--ledger", default=None, help="prebuilt arm-P trade ledger (skips the harness)")
    ap.add_argument("--days", type=int, default=1110)
    ap.add_argument("--start", default="2023-10-13")
    ap.add_argument("--end", default="2026-10-11 20:00")
    ap.add_argument("--recent-from", default="2025-10-11 20:00:00")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--lives", type=int, default=1000)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.leg and a.out):
        ap.error("--leg and --out are required")
    v = run(a)
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
