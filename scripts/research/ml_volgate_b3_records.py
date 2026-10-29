#!/usr/bin/env python3
# wiring: manual-only - the record writer for the lane-run B3 driver (ml_volgate_b3.py); it reads that driver's per-leg result files and has no unattended trigger
"""Turn `ml_volgate_b3.py` results into one evidence record per (head, strategy, cell) + a summary.

Every verdict word below is the plan's (docs/plans/ml-live-promotion-plan-2026-10-29.md section 3
P2/P3, registered before the run), applied unchanged:

  CELL_PASS                  `<dir>_stable_drag`, not fold-sensitive, >= MIN_DIRECTION_TRADES in that direction
  FAIL_NOT_STABLE_DRAG       the direction has enough trades and is not a stable drag
  FAIL_FOLD_SENSITIVE        the fold panel disagrees
  INDETERMINATE_*            no trades / fewer than MIN_DIRECTION_TRADES: a verdict over too few trades is no finding
  REFUSED_UNFAITHFUL         the harness fidelity flag is `approximate` (plan section 7): the numbers are
                             recorded as `informational` and can never be a promotion basis
  REFUSED_COST_UNATTESTED    the run's trades do not stamp fee + slippage + funding

A leg x head is `LEG_PASS` only if it is faithful, cost-attested, has >= 1 CELL_PASS, AND the book
rule holds (net >= ungated in >= 3 of 4 yearly folds AND pooled maxDD <= ungated). A passing cell
whose direction the existing 1-D regime table already turns OFF is `REDUNDANT_WITH_1D_CELL`: authoring
it would remove no further order.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGIMES = ("trending", "transitional", "chop")
VOLS = ("calm", "volatile")
DIRS = ("long", "short")


def _policy() -> dict:
    return yaml.safe_load(open(os.path.join(REPO, "config/regime_policy.yaml"), encoding="utf-8"))


def authored_cells(policy: dict) -> dict[tuple, bool]:
    """{(strategy, regime, vol, direction): True} for every authored `trend_vol` OFF side."""
    out = {}
    for reg, vols in (policy.get("trend_vol") or {}).items():
        for vol, strats in (vols or {}).items():
            for strat, sides in (strats or {}).items():
                for d, on in (sides or {}).items():
                    if on is False or str(on).lower() == "off":
                        out[(strat, reg, vol, d)] = True
    return out


def one_d_off(policy: dict, strategy: str, regime: str, direction: str) -> bool:
    side = ((policy.get(regime) or {}).get(strategy) or {}).get(direction)
    return side is False or str(side).lower() == "off"


def cell_dir_verdict(result: dict, cell: dict, direction: str) -> tuple[str, str]:
    """(registered verdict, `would_be` verdict ignoring a refusal)."""
    v = cell.get("verdict") or {}
    n = v.get(f"{direction}_trades")
    if not cell.get("trades") or not n:
        raw = "INDETERMINATE_NO_TRADES"
    elif v.get(f"{direction}_insufficient_n"):
        raw = "INDETERMINATE_INSUFFICIENT_N"
    elif v.get(f"{direction}_stable_drag") and not v.get(f"{direction}_fold_sensitive"):
        raw = "CELL_PASS"
    elif v.get(f"{direction}_fold_sensitive"):
        raw = "FAIL_FOLD_SENSITIVE"
    else:
        raw = "FAIL_NOT_STABLE_DRAG"
    if result.get("fidelity") != "faithful":
        return "REFUSED_UNFAITHFUL", raw
    if not result.get("cost_stack_ok"):
        return "REFUSED_COST_UNATTESTED", raw
    return raw, raw


def leg_verdict(result: dict, cell_verdicts: list[str], redundant_all: bool) -> str:
    if result.get("verdict") == "REFUSED_NO_HARNESS":
        return "REFUSED_NO_HARNESS"
    if result.get("error"):
        return "ERROR"
    if result.get("fidelity") != "faithful":
        return "REFUSED_UNFAITHFUL"
    if not result.get("cost_stack_ok"):
        return "REFUSED_COST_UNATTESTED"
    passing = [v for v in cell_verdicts if v == "CELL_PASS"]
    if not passing:
        return "NO_CANDIDATE_CELL"
    b = result.get("book") or {}
    if b.get("rule_net") is None:
        return "INDETERMINATE_BOOK_FOLDS"
    if not (b.get("rule_net") and b.get("rule_maxdd")):
        return "BOOK_RULE_FAIL"
    if redundant_all:
        return "REDUNDANT_WITH_1D_CELL"
    return "LEG_PASS"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", required=True, help="dir of ml_volgate_b3.py result JSONs")
    ap.add_argument("--heads", required=True, help="JSON file: {head_id: {facts...}} replay + gate-check facts")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    policy = _policy()
    authored = authored_cells(policy)
    heads = json.load(open(a.heads, encoding="utf-8"))
    summary, reverify = [], []
    for path in sorted(glob.glob(os.path.join(a.results, "*.json"))):
        r = json.load(open(path, encoding="utf-8"))
        head, strat = r.get("head"), r.get("strategy")
        base = os.path.join(a.out, head, strat)
        os.makedirs(base, exist_ok=True)
        leg_cells = []
        cell_verdicts_for_leg = []
        passing_dirs = []
        for slug, cell in (r.get("cells") or {}).items():
            reg, vol = slug.split("/")
            per_dir = {}
            for d in DIRS:
                v, raw = cell_dir_verdict(r, cell, d)
                red = one_d_off(policy, strat, reg, d)
                per_dir[d] = {"verdict": v, "would_be_if_not_refused": raw,
                              "informational_only": v.startswith("REFUSED"),
                              "existing_1d_cell_already_off": red,
                              "authored_trend_vol_cell": bool(authored.get((strat, reg, vol, d)))}
                if v == "CELL_PASS":
                    passing_dirs.append((reg, d, red))
                cell_verdicts_for_leg.append(v)
            rec = {"record": "ml-volgate-wf-cell", "lane": "ML-VOLGATE-WF-ETH-BTC", "plan_step": "B3",
                   "head": head, "strategy": strat, "cell": slug, "symbol": r.get("symbol"),
                   "timeframe": r.get("timeframe"), "harness": r.get("harness"),
                   "fidelity": r.get("fidelity"), "omitted_levers": r.get("omitted_levers"),
                   "cost_policy": r.get("cost_policy"), "mean_cost_r_per_trade": r.get("mean_cost_r"),
                   "cost_stack_attested": r.get("cost_stack_ok"),
                   "population": {"trades_in_leg_graded": r.get("n_trades_all"),
                                  "trades_excluded_after_labels_end": r.get("trades_excluded_after_labels_end"),
                                  "labels_end": r.get("labels_end"), "candle_days": r.get("days"),
                                  "trades_in_cell": cell.get("trades")},
                   "rule": "plan section 3 P2/P3: <dir>_stable_drag under every member of FOLD_PANEL (3,4,5), "
                           "not fold-sensitive, >= MIN_DIRECTION_TRADES (10) in that direction, full cost stack",
                   "by_fold_4": cell.get("by_fold_4"), "pooled": cell.get("pooled"),
                   "cell_verdict_detail": cell.get("verdict"), "directions": per_dir,
                   "label_provenance": heads.get(head)}
            with open(os.path.join(base, f"{reg}_{vol}.json"), "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=1, default=str)
            leg_cells.append((slug, per_dir))
        redundant_all = bool(passing_dirs) and all(red for _, _, red in passing_dirs)
        lv = leg_verdict(r, cell_verdicts_for_leg, redundant_all)
        b = r.get("book") or {}
        summary.append({"head": head, "strategy": strat, "fidelity": r.get("fidelity"), "leg_verdict": lv,
                        "passing": [f"{reg}:{d}" + (" (1D already off)" if red else "") for reg, d, red in passing_dirs],
                        "book": {k: b.get(k) for k in ("ungated_fold_net_r", "gated_fold_net_r", "folds_populated",
                                                      "folds_gated_ge_ungated", "ungated_max_dd_r", "gated_max_dd_r",
                                                      "rule_net", "rule_maxdd", "rule1_ungated_all_folds_profitable")},
                        "n": r.get("n_trades_all"), "excluded_after_labels_end": r.get("trades_excluded_after_labels_end"),
                        "error": r.get("error")})
        for (s, reg, vol, d) in authored:
            if s != strat:
                continue
            cell = (r.get("cells") or {}).get(f"{reg}/{vol}") or {}
            v, raw = cell_dir_verdict(r, cell, d)
            vd = cell.get("verdict") or {}
            reverify.append({"head": head, "strategy": s, "cell": f"{reg}/{vol}", "gated_direction": d,
                             "verdict": v, "would_be_if_not_refused": raw,
                             "n_dir": vd.get(f"{d}_trades"), "pooled_dir_r": vd.get(f"pooled_{d}_r"),
                             "removal_candidate": raw in ("FAIL_NOT_STABLE_DRAG", "FAIL_FOLD_SENSITIVE")})
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"legs": summary, "reverify_authored_cells": reverify}, fh, indent=1, default=str)
    print(json.dumps({"legs": len(summary), "reverify": len(reverify)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
