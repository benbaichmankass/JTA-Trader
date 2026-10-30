#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-18G-EVENT-ENTRIES and by research/queue/blocked/RQ-20261030-e18g-03 (once released); writes comms/strategy_evidence/e4_oi_shock.json; no schedule consumes it.
"""Absolute Stage-0 for the frozen E4 arm (rule RULE-RQ20261030-E18G-03-E4-STAGE0-ABSOLUTE).

PASS iff n >= 30 AND mean net R per trade > 0 AND the 95% ISO-week cluster CI lower bound > 0, on the HELD-OUT window rows of the E4 ledger.
Reads the committed ledger (scripts/research/e4_prop_ledger.py); the cost stack is read from the code and printed. Scored once.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import desk_event_entry_replay as m  # noqa: E402
import desk_gen_replay_driver as gr  # noqa: E402

LEDGER = REPO / "docs/research/e4-prop-sim-2026-10-30/ledgers/e4_full.jsonl"
RULE = "RULE-RQ20261030-E18G-03-E4-STAGE0-ABSOLUTE"


def week(ts: str) -> str:
    return gr.iso_week(int(datetime.fromisoformat(ts).timestamp()))


def stats(rows):
    v = [r["driver_net_r"] for r in rows]
    return m.cluster_mean(v, [week(r["entry_time"]) for r in rows], 0.05)


def main() -> int:
    rows = [json.loads(x) for x in LEDGER.read_text().splitlines()]
    ho = [r for r in rows if r["window"] == "holdout"]
    dev = [r for r in rows if r["window"] == "dev"]
    s = stats(ho)
    fee, slip, fund = gr.dsp.cost_policy("BTCUSDT")
    verdict = "pass" if s["n"] >= m.N_MIN and s["mean"] > 0 and s["ci"][0] > 0 else "fail"
    q = {}
    for r in ho:
        k = f"{datetime.fromisoformat(r['entry_time']).year}Q{(datetime.fromisoformat(r['entry_time']).month - 1) // 3 + 1}"
        q.setdefault(k, []).append(r)
    folds = [{"fold": i + 1, "label": k, "trades": len(v), "net_r": round(sum(x["driver_net_r"] for x in v), 4),
              "expectancy_r": round(float(np.mean([x["driver_net_r"] for x in v])), 4),
              "start": min(x["entry_time"] for x in v), "end": max(x["entry_time"] for x in v)} for i, (k, v) in enumerate(sorted(q.items()))]
    res = {"rule": RULE, "window": "2024-11-01..2025-10-25 (held-out)", "n": s["n"], "weeks": s.get("weeks"), "mean_net_r": s["mean"], "ci95": s["ci"],
           "dev_for_reference": stats(dev), "cost_stack": {"fee_bps_roundtrip": fee, "slippage_bps_roundtrip": slip, "funding_bps_per_window": fund},
           "folds_quarterly": folds, "verdict": verdict}
    print(json.dumps(res, indent=1, default=str))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "comms/research/RQ-20261030-e18g-03"
    out.mkdir(parents=True, exist_ok=True)
    (out / "e4_stage0_result.json").write_text(json.dumps(res, indent=1, default=str))
    net = [r["driver_net_r"] for r in ho]
    cum = np.cumsum(net)
    rec = {"schema_version": 2, "strategy": "e4_oi_shock", "symbol": "ADAUSDT,AVAXUSDT,BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", "timeframe": "1h",
           "config_fingerprint": "not_applicable: research arm, no live config (E4-DEMO-LEG will create one)", "basis": "heldout_window", "coverage_state": "measured",
           "fidelity": "research_harness_not_live_code", "omitted_levers": ["Bybit venue (Binance candles stand in)", "live fills / latency", "bracket and horizon tuning (one fixed bracket)"],
           "net_r_oos": round(float(sum(net)), 4), "expectancy_r_oos": round(float(np.mean(net)), 4), "n_trades_oos": len(net),
           "expectancy_ci95": [round(s["ci"][0], 4), round(s["ci"][1], 4)], "folds": len(folds), "fold_detail": folds,
           "folds_positive": sum(1 for f in folds if f["net_r"] > 0), "window_days": 358, "fee_bps_roundtrip": fee,
           "path_stats": {"series_location": "source_run (the per-trade rows, in order, with driver_net_r)", "n": len(net), "max_drawdown_r": round(float(np.max(np.maximum.accumulate(cum) - cum)), 4),
                          "final_equity_r": round(float(cum[-1]), 4), "worst_trade_r": round(float(min(net)), 4), "best_trade_r": round(float(max(net)), 4),
                          "ordering": "by entry_time ascending", "not_a_verdict": "Descriptive only."},
           "cost_stack": {"fees": fee, "slippage": slip, "funding": fund, "unit": "bps_roundtrip (funding: bps per funding window)", "source": "scripts/research/desk_gen_replay_driver.py cost_policy + execution_costs.roundtrip_cost_r"},
           "decision_rule": {"id": RULE, "rule": "PASS iff n >= 30 AND mean net R per trade > 0 AND the 95% ISO-week cluster CI lower bound > 0 on the held-out window, net of the full cost stack. Registered 2026-10-30 (commit 6326055a0) after the point estimate (+0.022 R) but before the CI was read.",
                             "registered_at": "2026-10-30", "verdict": verdict},
           "param_selection_provenance": "DEV 2025-11-01..2026-09-15 then frozen; held-out is out-of-sample (RQ-20261030-e18g-01/-02)",
           "generated_at": datetime.now(timezone.utc).isoformat(), "generated_by": "scripts/research/e4_stage0.py",
           "source_run": "docs/research/e4-prop-sim-2026-10-30/ledgers/e4_full.jsonl", "error": None, "harness": "event_oi_shock", "venue_bracket_arm": None,
           "rebaseline_history": [], "demo_only_note": "Stage-0 verdict " + verdict + ". This record is NOT a promotion: it names no roster."}
    (REPO / "comms/strategy_evidence/e4_oi_shock.json").write_text(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
