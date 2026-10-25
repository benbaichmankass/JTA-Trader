#!/usr/bin/env python3
# wiring: research/queue/RQ-20261025-3947-27 (PI-20261009-NKGUCEDN-0001) via .github/workflows/research-script-run.yml
"""MOMENTUM-TRAIL ATTRIBUTION: per-cell split of net R by ``trail_adx_tightened``.

WHY (pipeline item PI-20261009-NKGUCEDN-0001, lane EXIT-EVIDENCE-FOLDS 2026-10-09). Five e5-passing
``momentum_trail`` cells settled their FOLDS but could not be passed or failed on the ATTRIBUTION clause: the
sweep records cell aggregates only. ``scripts/backtest_trend.py --emit-trades`` emits ``trail_adx_tightened``
per trade when the lever is armed (``_mom_attribution``). This script runs each cell through
``exit_lever_ablation`` (which builds the harness argv from the committed leg config and passes
``--emit-trades``), reads those trade files, and splits each cell's net R between trades whose stop was last
moved on an ADX-tightened bar and all others.

THE RULE (registered in research/queue/RQ-20261025-3947-27.yaml before any run), per cell:
  n_T = tightened trades, net_T = their summed net R (full cost stack, the harness's own),
  matched = tightened trades whose entry also exists in baseline arm A (key: entry_time + side),
  delta_T = net_T minus the SAME entries' net R under A.
  CELL PASSES iff n_T >= 30 AND net_T >= 0 AND matched >= 80 % of n_T AND delta_T > 0.
  CELL FAILS  iff n_T >= 30 AND (net_T < 0 OR (matched >= 80 % AND delta_T <= 0)).
  Otherwise INDETERMINATE (n_T < 30, or matched < 80 % with net_T >= 0).
UNIT: PASS iff >= 1 cell passes; FAIL iff every cell is evaluable (n_T >= 30) and none passes; else INDETERMINATE.
A PASS is a discovery on one window (follow-up: one disjoint-window confirmation, prop legs in their own PR);
it edits no config and is not a promotion case.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

#: (leg, label, adx_below, falling_bars, tight_mult). The five cells of PI-20261009-NKGUCEDN-0001.
CELLS: list[tuple[str, str, float, int, float]] = [
    ("trend_donchian_eth_4h", "adx20_k0_t2.5", 20.0, 0, 2.5),
    ("trend_donchian_xrp_4h", "adx25_k0_t2.5", 25.0, 0, 2.5),
    ("trend_donchian_xrp_4h", "adx20_k0_t2.5", 20.0, 0, 2.5),
    ("trend_donchian_eth_prop", "adx25_k0_t1.8", 25.0, 0, 1.8),
    ("trend_donchian_eth_prop", "adx25_k3_t1.8", 25.0, 3, 1.8),
]
N_FLOOR = 30
MATCH_FLOOR = 0.80


def cell_tokens(adx: float, k: int, mult: float) -> str:
    toks = [f"--trail-adx-below={adx:g}", f"--trail-adx-tight-mult={mult:g}"]
    if k:
        toks.insert(1, f"--trail-adx-falling-bars={k}")
    return ";".join(toks)


def _key(t: dict[str, Any]) -> tuple[str, str]:
    return (str(t.get("entry_time")), str(t.get("side") or t.get("direction") or ""))


def split_cell(cell_trades: list[dict[str, Any]], base_trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: the attribution split and the per-cell verdict."""
    tight = [t for t in cell_trades if t.get("trail_adx_tightened") is True]
    other = [t for t in cell_trades if t.get("trail_adx_tightened") is not True]
    has_field = any("trail_adx_tightened" in t for t in cell_trades)
    base = {_key(t): float(t.get("net_r") or 0.0) for t in base_trades}
    net_t = round(sum(float(t.get("net_r") or 0.0) for t in tight), 4)
    matched = [t for t in tight if _key(t) in base]
    base_on_matched = round(sum(base[_key(t)] for t in matched), 4)
    net_t_matched = round(sum(float(t.get("net_r") or 0.0) for t in matched), 4)
    frac = round(len(matched) / len(tight), 4) if tight else None
    delta = round(net_t_matched - base_on_matched, 4) if matched else None
    out = {"field_present": has_field, "n_cell": len(cell_trades), "n_tightened": len(tight), "n_other": len(other),
           "net_r_tightened": net_t, "net_r_other": round(sum(float(t.get("net_r") or 0.0) for t in other), 4),
           "n_matched_to_A": len(matched), "matched_fraction": frac,
           "net_r_tightened_matched": net_t_matched, "net_r_A_same_entries": base_on_matched, "delta_T": delta}
    if not has_field or len(tight) < N_FLOOR:
        out.update(verdict="indeterminate", why=("trail_adx_tightened absent from the trade rows (no attribution emitted)" if not has_field
                                                  else f"n_tightened {len(tight)} < {N_FLOOR}"))
    elif net_t < 0:
        out.update(verdict="fail", why=f"tightened exits net NEGATIVE ({net_t} R over {len(tight)} trades)")
    elif frac is not None and frac >= MATCH_FLOOR:
        ok = delta is not None and delta > 0
        out.update(verdict="pass" if ok else "fail",
                   why=(f"tightened exits net {net_t} R and beat the same entries under A by {delta} R" if ok
                        else f"tightened exits net {net_t} R but did not beat the same entries under A (delta {delta} R)"))
    else:
        out.update(verdict="indeterminate", why=f"matched fraction {frac} < {MATCH_FLOOR}: cannot compare with A")
    return out


def unit_verdict(cells: dict[str, dict[str, Any]]) -> tuple[str, str]:
    vs = [c["verdict"] for c in cells.values()]
    if "pass" in vs:
        return "pass", "at least one cell's tightened exits net non-negative and beat A on the same entries"
    if vs and all(v in ("fail",) for v in vs):
        return "fail", "every cell evaluable and none passes: these cells are closed on this window; the momentum_trail family stays open"
    return "indeterminate", "at least one cell not evaluable (n_tightened below floor, missing field, or unmatched)"


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-10-15 23:59")
    ap.add_argument("--days", default="2330")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    import exit_lever_ablation as ela
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    legs: dict[str, list[tuple[str, float, int, float]]] = {}
    for leg, label, adx, k, mult in CELLS:
        legs.setdefault(leg, []).append((label, adx, k, mult))
    result: dict[str, dict[str, Any]] = {}
    for leg, cells in legs.items():
        sub = out / leg
        args = ["--leg", leg, "--arm", "A="]
        for label, adx, k, mult in cells:
            args += ["--arm", f"{label}={cell_tokens(adx, k, mult)}"]
        args += ["--days", a.days, "--start", a.start, "--end", a.end, "--grade", "replace", "--baseline", "A",
                 "--delta-r", "0", "--delta-r-per-trade", "0.02", "--folds", "6", "--fold-majority", "4",
                 "--dd-tol-frac", "0.35", "--n-floor", "39", "--out", str(sub)]
        rc = ela.main(args)
        if rc != 0:
            print(f"ERROR: exit_lever_ablation failed for {leg} (rc {rc})", file=sys.stderr)
            (out / "failure.json").write_text(json.dumps({"stage": "ablation", "leg": leg, "rc": rc}) + "\n", encoding="utf-8")
            return 1
        base = _load(sub / "arms" / "A__trades.jsonl")
        for label, *_ in cells:
            result[f"{leg}:{label}"] = split_cell(_load(sub / "arms" / f"{label}__trades.jsonl"), base)
    verdict, why = unit_verdict(result)
    n_total = sum(c["n_cell"] for c in result.values())
    rec = {"verdict": verdict, "read_state": "measured",
           "population": (f"{len(result)} momentum_trail cells over {len(legs)} legs, window {a.start} .. {a.end}; tightened trades per cell in "
                          "measurement.cells; net of the harness's full cost stack"),
           "n": n_total, "measurement": {"cells": result, "n_floor": N_FLOOR, "match_floor": MATCH_FLOOR, "rule_unit": "RQ-20261025-3947-27"},
           "note": f"{verdict.upper()}: {why}"}
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "why": why}, indent=1))
    return 0


def _self_test() -> int:
    def tr(i, r, tight, side="long"):
        return {"entry_time": f"2024-01-{i:02d}", "side": side, "net_r": r, "trail_adx_tightened": tight}
    base = [tr(i, 1.0, None) for i in range(1, 29)] + [tr(29, -1.0, None), tr(30, -1.0, None), tr(31, -1.0, None)]
    # PASS: 31 tightened, net positive, beat A on same entries
    good = [tr(i, 1.5, True) for i in range(1, 29)] + [tr(29, 0.0, True), tr(30, 0.0, True), tr(31, 0.0, True)]
    r = split_cell(good, base)
    assert r["verdict"] == "pass" and r["n_tightened"] == 31 and r["matched_fraction"] == 1.0, r
    # FAIL: negative tightened net
    bad = [tr(i, -0.5, True) for i in range(1, 32)]
    assert split_cell(bad, base)["verdict"] == "fail"
    # FAIL: net >= 0 but worse than A on the same entries
    worse = [tr(i, 0.5, True) for i in range(1, 29)] + [tr(29, 0.0, True), tr(30, 0.0, True), tr(31, 0.0, True)]
    assert split_cell(worse, base)["verdict"] == "fail"
    # INDETERMINATE: too few tightened; field absent
    assert split_cell([tr(1, 1.0, True)], base)["verdict"] == "indeterminate"
    assert split_cell([{"entry_time": "x", "net_r": 1.0}], base)["verdict"] == "indeterminate"
    # unit roll-up
    assert unit_verdict({"a": {"verdict": "pass"}, "b": {"verdict": "fail"}})[0] == "pass"
    assert unit_verdict({"a": {"verdict": "fail"}, "b": {"verdict": "fail"}})[0] == "fail"
    assert unit_verdict({"a": {"verdict": "fail"}, "b": {"verdict": "indeterminate"}})[0] == "indeterminate"
    assert cell_tokens(25.0, 3, 1.8) == "--trail-adx-below=25;--trail-adx-falling-bars=3;--trail-adx-tight-mult=1.8"
    assert cell_tokens(20.0, 0, 2.5) == "--trail-adx-below=20;--trail-adx-tight-mult=2.5"
    print("self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
