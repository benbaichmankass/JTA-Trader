#!/usr/bin/env python3
# wiring: research-script-run-trainer.yml via research/queue/RQ-20261119-c8e2-02.yaml; --self-test in run_guards research-tooling-selftests.
"""Fresh-data walk-forward of the LIVE trend_vol OFF-cells (the vol-keyed regime-router cells).

WHY. The evidence behind the live ``config/regime_policy.yaml`` ``trend_vol`` cells is the 2026-06-27 vol-gating
A/B (``docs/research/A-vol-gating-AB-evidence-2026-06-27.md``, ``scripts/ml/walkforward_vol_gating.sh``): four
consecutive BTC year-folds ending 2026-06-01, fed by ``data/backtest_BTCUSDT_5m.csv`` -- a file that stayed frozen at
2026-05-21 until #27299 refreshed it on 2026-11-19. Nothing has re-read those cells on post-freeze data.

WHAT. For each fold, three arms of the SAME harness (``scripts/backtest_system.py --json``) over the SAME roster:
  ungated  ``--regime-router off``                              (the no-cell baseline; regime-selectivity Rule 1)
  frozen   ``--regime-router on --vol-verdict frozen``          (the cells keyed by the frozen vol detector)
  ml       ``--regime-router on --vol-verdict ml --ml-model-id``  (the cells keyed by the ML vol head, as live)
and grades the registered rule (``grade()``; the unit carries the same rule text, registered before the run).

Report only: it edits no config, flips no cell, places no order. Python + scripts/research only (the
research-script-run-trainer allowlist), so it shells the harness rather than a bash wrapper.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROSTER = "trend_donchian,squeeze_breakout_4h,htf_pullback_trend_2h"  # the 2026-06-27 A/B's roster, unchanged
DEFAULT_FOLDS = ("2022-07-01:2023-07-01", "2023-07-01:2024-07-01", "2024-07-01:2025-07-01",
                 "2025-07-01:2026-06-01", "2026-06-01:2026-11-19")
FRESH_FOLD = "2026-06-01:2026-11-19"   # the post-freeze fold the verdict is graded on
MIN_TRADES = 30                        # ungated trades on the fresh fold below this -> indeterminate


def grade(folds: list[dict], fresh: str = FRESH_FOLD, min_trades: int = MIN_TRADES) -> dict:
    """The registered rule. ``folds`` = [{fold, ungated:{net,maxdd_pct,trades}, frozen:{...}, ml:{...}}].

    On the FRESH fold the live (ml-keyed) cells HOLD iff ml.net >= ungated.net AND ml.maxdd_pct <= ungated.maxdd_pct
    (the cells still remove a money-losing slice without worsening drawdown: not cosmetic). They DO NOT HOLD iff
    ml.net < ungated.net AND ml.maxdd_pct >= ungated.maxdd_pct (they cost money and buy no drawdown). Anything
    else (one better, one worse) is MIXED. Fewer than ``min_trades`` ungated trades on the fresh fold, or any arm
    unreadable, is INDETERMINATE. ml vs frozen is reported, never graded here."""
    by = {f["fold"]: f for f in folds}
    f = by.get(fresh)
    if not f or any(not isinstance(f.get(a), dict) or f[a].get("net") is None for a in ("ungated", "ml")):
        return {"verdict": "indeterminate", "why": f"fresh fold {fresh} missing or an arm unreadable"}
    u, m = f["ungated"], f["ml"]
    if (u.get("trades") or 0) < min_trades:
        return {"verdict": "indeterminate", "why": f"ungated trades {u.get('trades')} < {min_trades} on {fresh}"}
    better_net = m["net"] >= u["net"]
    better_dd = m["maxdd_pct"] <= u["maxdd_pct"]
    verdict = "holds" if (better_net and better_dd) else (
        "does_not_hold" if (not better_net and not better_dd) else "mixed")
    return {"verdict": verdict, "fresh_fold": fresh, "d_net_ml_vs_ungated": round(m["net"] - u["net"], 2),
            "d_maxdd_pct_ml_vs_ungated": round(m["maxdd_pct"] - u["maxdd_pct"], 3),
            "ml_vs_frozen_net": (round(m["net"] - f["frozen"]["net"], 2)
                                 if isinstance(f.get("frozen"), dict) and f["frozen"].get("net") is not None else None)}


def _arm(py: str, data: str, policy: str, s: str, e: str, flags: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "s.json"
        cmd = [py, "scripts/backtest_system.py", "--data", data, "--roster", ROSTER, "--regime-policy", policy,
               "--start", s, "--end", e, "--json", str(out), *flags]
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False)
        if p.returncode != 0 or not out.exists():
            return {"net": None, "error": (p.stderr or p.stdout)[-400:]}
        d = json.loads(out.read_text())
        return {"net": d.get("net_pnl"), "maxdd_pct": d.get("max_drawdown_pct"), "trades": d.get("total_trades"),
                "data_start": d.get("data_start"), "data_end": d.get("data_end")}


def run(data: str, policy: str, mid: str, folds: list[str]) -> dict:
    py = sys.executable
    rows = []
    for f in folds:
        s, e = f.split(":")
        rows.append({"fold": f,
                     "ungated": _arm(py, data, policy, s, e, ["--regime-router", "off"]),
                     "frozen": _arm(py, data, policy, s, e, ["--regime-router", "on", "--vol-verdict", "frozen"]),
                     "ml": _arm(py, data, policy, s, e, ["--regime-router", "on", "--vol-verdict", "ml",
                                                        "--ml-model-id", mid])})
        print(json.dumps(rows[-1]), flush=True)
    return contract_result(grade(rows), rows, f"BTC system backtest, roster {ROSTER}, live {policy}, data {data}")


#: The rule's outcome -> script_run.py's verdict.json contract (VERDICTS / READ_STATES). The rule's own word is kept
#: in grade.rule_outcome. MIXED has no registered action, so it lands as indeterminate, never as a pass. Before this
#: map, run 44598184518 wrote verdict 'mixed' / read_state 'complete' / no n and landed as producer_failed.
CONTRACT_VERDICT = {"holds": "pass", "does_not_hold": "fail", "mixed": "indeterminate", "indeterminate": "indeterminate"}


def contract_result(g: dict, rows: list, description: str) -> dict:
    fresh = next((f for f in rows if f.get("fold") == FRESH_FOLD), None)
    readable = bool(fresh) and all(isinstance(fresh.get(a), dict) and fresh[a].get("net") is not None
                                   for a in ("ungated", "ml"))
    g = {**g, "rule_outcome": g["verdict"]}
    return {"read_state": "measured" if readable else "no_data",
            "verdict": CONTRACT_VERDICT[g["verdict"]],
            "n": fresh["ungated"].get("trades") if readable else None,
            "population": f"{description}; graded on the fresh fold {FRESH_FOLD} (n = ungated trades there)",
            "grade": g, "folds": rows}


def _self_test() -> int:
    def fold(un, ud, mn, md, t=50):
        return [{"fold": FRESH_FOLD, "ungated": {"net": un, "maxdd_pct": ud, "trades": t},
                 "frozen": {"net": mn, "maxdd_pct": md, "trades": t}, "ml": {"net": mn, "maxdd_pct": md, "trades": t}}]
    checks = [
        (grade(fold(100, 10, 120, 9))["verdict"] == "holds", "better net + better DD -> holds"),
        (grade(fold(100, 10, 80, 11))["verdict"] == "does_not_hold", "worse net + worse DD -> does_not_hold"),
        (grade(fold(100, 10, 80, 9))["verdict"] == "mixed", "worse net + better DD -> mixed"),
        (grade(fold(100, 10, 120, 9, t=5))["verdict"] == "indeterminate", "thin fold -> indeterminate"),
        (grade([])["verdict"] == "indeterminate", "missing fold -> indeterminate"),
        (grade([{"fold": FRESH_FOLD, "ungated": {"net": None}, "ml": {"net": 1}}])["verdict"] == "indeterminate",
         "unreadable arm -> indeterminate (never a pass)"),
    ]
    mixed = contract_result(grade(fold(100, 10, 80, 9)), fold(100, 10, 80, 9), "t")
    gone = contract_result(grade([]), [], "t")
    checks += [
        (mixed["verdict"] == "indeterminate" and mixed["grade"]["rule_outcome"] == "mixed"
         and mixed["read_state"] == "measured" and mixed["n"] == 50, "contract: mixed -> indeterminate, measured, n"),
        (contract_result(grade(fold(100, 10, 120, 9)), fold(100, 10, 120, 9), "t")["verdict"] == "pass",
         "contract: holds -> pass"),
        (contract_result(grade(fold(100, 10, 80, 11)), fold(100, 10, 80, 11), "t")["verdict"] == "fail",
         "contract: does_not_hold -> fail"),
        (gone["read_state"] == "no_data" and gone["n"] is None and "n" in gone, "contract: no fold -> no_data, n null"),
        (isinstance(mixed["population"], str) and mixed["population"].strip() != "", "contract: population is a string"),
    ]
    ok = all(c for c, _ in checks)
    for c, label in checks:
        print(("PASS " if c else "FAIL ") + label)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--data", default="data/backtest_BTCUSDT_5m.csv")
    ap.add_argument("--policy", default="config/regime_policy.yaml")
    ap.add_argument("--ml-model-id", default="btc-regime-15m-lgbm-v2")
    ap.add_argument("--folds", default=",".join(DEFAULT_FOLDS))
    ap.add_argument("--unit", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    os.environ.setdefault("PYTHONPATH", str(REPO))
    res = run(a.data, a.policy, a.ml_model_id, a.folds.split(","))
    res["unit"] = a.unit
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(res, indent=2, default=str) + "\n")
    print(json.dumps({"verdict": res["verdict"], "grade": res["grade"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
