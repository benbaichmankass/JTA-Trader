#!/usr/bin/env python3
# wiring: manual-only - run once per leg when the operator decides a leg keeps the
# FORMING decision bar and its standing record must describe that bar (operator
# 2026-10-22, "match the bar"; checklist DECISION-BAR-MATCH). A decision, not a cadence.
"""Re-base a leg's committed Stage-0 evidence record onto the decision bar it TRADES.

WHY. Operator 2026-10-22 (checklist DECISION-BAR-MATCH, verbatim): a closed-bar backtest
does not count as evidence for a forming-bar leg -- "No — match the bar". Then, same day:
"Split: 3 to closed, 2 stay" -- trend_donchian_eth_4h and trend_donchian_sol_prop keep
the forming bar "and re-record their evidence on the forming bar (it passes the rule
there)". `build_strategy_evidence.py` runs the closed-bar Stage-0 harness only, so it
cannot produce that record.

WHAT IT DOES (nothing re-measured here, nothing re-implemented):
  * trades   the FORMING arm of scripts/research/decision_bar_match.py (RQ-20261022-4de5-01;
             forming_bar_pooled_regrade.leg_run: the Stage-0 harness config-exact, entry
             decided at the live 2-min tick cadence on the forming bar, full cost stack),
             restricted to the EXISTING record's own window [data_start, data_end] -- the
             same window and predicate forming_bar_pooled_regrade.restate graded, so the
             record's verdict is the number the operator decided on.
  * record   every field of the existing record is kept; the measured fields are
             recomputed with build_strategy_evidence's OWN time_folds / path_stats and
             RULE-D1 (DECISION_RULE_ID / TEXT / REGISTERED_AT), the fold count kept.
             Adds `decision_bar` and `supersedes`; the old record stays in git.
  * run      writes runs/<date>-forming/<leg>__trades.jsonl + __bt.json beside it, so every
             consumer that resolves cost_stack.source -> __trades.jsonl (prop_ev_grid,
             prop_ev_sim --book) reads the forming set.

Refuses (exit 1) if the leg's config is not `decision_bar: forming` (absent = forming), if
the config fingerprint moved since the record, or if the window holds no trades.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "ops"), str(ROOT / "scripts" / "research"), str(ROOT)]

import build_strategy_evidence as bse  # noqa: E402

EVIDENCE = ROOT / "comms" / "strategy_evidence"
GENERATOR = "scripts/ops/rebase_evidence_decision_bar.py"


def _ts(s: Any):
    import pandas as pd
    t = pd.Timestamp(str(s))
    return t.tz_localize("UTC") if t.tzinfo is None else t


def in_window(trades: List[Dict[str, Any]], lo: Any, hi: Any) -> List[Dict[str, Any]]:
    """Trades entered in [lo, hi] -- forming_bar_pooled_regrade._window's predicate."""
    a, b = _ts(lo), _ts(hi)
    return [t for t in trades if a <= _ts(t["entry_time"]) <= b]


def rebase(record: Dict[str, Any], bt: Dict[str, Any], trades: List[Dict[str, Any]], *,
           decision_bar: str, cfg: Dict[str, Any], run_dir_rel: str, unit: str,
           old_path_rel: str, now: str) -> Dict[str, Any]:
    """New record dict (pure). `trades` = the arm's rows already restricted to the window."""
    if not trades:
        raise ValueError("no trades in the record window -- zero trades is not an edge of zero")
    folds = int(record.get("folds") or bse.DEFAULT_FOLDS)
    fd = bse.time_folds(trades, folds)
    rs = [float(t.get("net_r") or 0.0) for t in trades]
    fee_only = [t.get("net_r_fee_only") for t in trades]
    leg = record["strategy"]
    rec = dict(record)
    for k in ("fold_basis", "fold_detail_equal_count", "folds_positive_equal_count",
              "positive_control", "research_grading"):
        rec.pop(k, None)  # described the superseded closed-bar measurement
    rec.update({
        "config_fingerprint": bse.config_fingerprint(cfg),
        "basis": "decision_bar_replay_timefolds",
        "decision_bar": decision_bar,
        "decision_bar_note": (
            f"Evidence measured on the bar the leg TRADES ({decision_bar}), per the operator's "
            "2026-10-22 'match the bar' decision (checklist DECISION-BAR-MATCH). Trades are the "
            f"{decision_bar} arm of {unit} (forming_bar_pooled_regrade.leg_run, Binance USD-M 1m "
            "proxy, full cost stack) restricted to the superseded record's own window."),
        "coverage_state": "measured",
        "n_trades_oos": len(trades),
        "net_r_oos": round(sum(rs), 4),
        "expectancy_r_oos": round(statistics.fmean(rs), 4),
        "folds": len(fd),
        "fold_detail": fd,
        "folds_positive": sum(1 for f in fd if f["net_r"] > 0),
        "fold_basis": "equal_count (build_strategy_evidence.time_folds)",
        "data_start": bt["data_start"],
        "data_end": bt["data_end"],
        "path_stats": bse.path_stats(trades),
        "cost_stack": {"fees": bt["fee_bps_roundtrip"], "slippage": bt["slippage_bps_roundtrip"],
                       "funding": bt["funding_bps_per_window"],
                       "unit": "bps_roundtrip (funding: bps per funding window)",
                       "source": f"{run_dir_rel}/{leg}__bt.json"},
        "net_r_oos_fee_only": (round(sum(fee_only), 4)
                               if fee_only and all(isinstance(v, (int, float)) for v in fee_only)
                               else None),
        "research_unit": unit,
        "supersedes": old_path_rel,
        "generated_at": now,
        "generated_by": GENERATOR,
        "source_run": f"{run_dir_rel}/{leg}__trades.jsonl",
        "error": None,
    })
    rec["decision_rule"] = {
        "id": bse.DECISION_RULE_ID, "rule": bse.DECISION_RULE_TEXT,
        "registered_at": bse.DECISION_RULE_REGISTERED_AT,
        "verdict": "pass" if rec["net_r_oos"] > 0 else "fail",
    }
    return rec


def main(argv: List[str] | None = None) -> int:
    import yaml
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", required=True)
    ap.add_argument("--arm-trades", required=True, help="the arm's full-window trades JSONL")
    ap.add_argument("--arm-ref", default=None,
                    help="repo path the arm is committed at (recorded in __bt.json); default --arm-trades")
    ap.add_argument("--decision-bar", choices=("forming",), default="forming")
    ap.add_argument("--unit", required=True, help="research unit that produced --arm-trades")
    ap.add_argument("--cost-from", required=True,
                    help="verdict.json of that run (legs.<leg>.costs = the stack the arm used)")
    ap.add_argument("--run-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args(argv)

    cfg = (yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"]).get(args.leg)
    if not isinstance(cfg, dict):
        print(f"ERROR: {args.leg} has no config block", file=sys.stderr)
        return 1
    live_bar = str(cfg.get("decision_bar") or "forming").lower()
    if live_bar != args.decision_bar:
        print(f"ERROR: {args.leg} trades decision_bar={live_bar}, not {args.decision_bar}", file=sys.stderr)
        return 1
    old_path = EVIDENCE / f"{args.leg}.json"
    record = json.loads(old_path.read_text())
    if record.get("config_fingerprint") != bse.config_fingerprint(cfg):
        print(f"ERROR: {args.leg} config moved since its record; rebuild, do not re-base", file=sys.stderr)
        return 1
    old_bt = json.loads((ROOT / record["cost_stack"]["source"]).read_text())
    costs = json.loads(Path(args.cost_from).read_text())["legs"][args.leg]["costs"]
    rows = [json.loads(x) for x in Path(args.arm_trades).read_text().splitlines() if x.strip()]
    trades = in_window(rows, old_bt["data_start"], old_bt["data_end"])

    run_dir = EVIDENCE / "runs" / f"{args.run_date}-{args.decision_bar}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_rel = run_dir.relative_to(ROOT).as_posix()
    rs = [float(t["net_r"]) for t in trades]
    bt = {"strategy": args.leg, "symbol": record.get("symbol"), "timeframe": cfg.get("timeframe"),
          "decision_bar": args.decision_bar, "research_unit": args.unit,
          "arm_trades": args.arm_ref or Path(args.arm_trades).as_posix(),
          "data_start": old_bt["data_start"], "data_end": old_bt["data_end"],
          "window_from": record["cost_stack"]["source"],
          "fee_bps_roundtrip": costs["fee_bps_roundtrip"],
          "slippage_bps_roundtrip": costs["slippage_bps_roundtrip"],
          "funding_bps_per_window": costs["funding_bps_per_window"],
          "total_trades": len(trades), "net_total_r": round(sum(rs), 4),
          "run_date": args.run_date, "generated_by": GENERATOR}
    now = datetime.now(timezone.utc).isoformat()
    new = rebase(record, bt, trades, decision_bar=args.decision_bar, cfg=cfg, run_dir_rel=run_rel,
                 unit=args.unit, old_path_rel=f"git:{old_path.relative_to(ROOT).as_posix()}@"
                 f"{record.get('generated_at')}", now=now)
    (run_dir / f"{args.leg}__trades.jsonl").write_text(
        "".join(json.dumps(t, default=str) + "\n" for t in trades), encoding="utf-8")
    (run_dir / f"{args.leg}__bt.json").write_text(json.dumps(bt, indent=1) + "\n", encoding="utf-8")
    old_path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    print(f"{args.leg}: {record.get('n_trades_oos')} trades {record.get('net_r_oos'):+.2f}R (closed record) -> "
          f"{new['n_trades_oos']} trades {new['net_r_oos']:+.2f}R ({args.decision_bar}), "
          f"folds +{new['folds_positive']}/{new['folds']}, RULE-D1 {new['decision_rule']['verdict']}")
    return 0 if new["decision_rule"]["verdict"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
