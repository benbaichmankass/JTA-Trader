#!/usr/bin/env python3
# wiring: manual-only — a session-local two-arm (HTF filter ON vs forced OFF) re-run of one ict_scalp leg; origin.rerun of PI-20261025-1CZRLDTS-0001-A/-B and RQ-20260928-001; no scheduled consumer.
"""RQ-20260928-001 driver: ict_scalp HTF trend filter OFF vs ON on the 7 variant legs.

Invokes ``scripts/backtest_ict_scalp.py`` in-process exactly as
``regime_debt_matrix.build_harness_cmd`` builds the argv for the committed
evidence records (leg's own ``--strategy-name`` + lever flags, venue fee), and
forces ``htf_trend_filter_enabled`` False (OFF) or True (ON) by wrapping the
harness's YAML read. Cost stack is passed EXPLICITLY (non-zero) from
``execution_costs.resolve_cost_policy``. Both arms share one candle CSV per leg.

usage: rq_20260928_001_htf_wire.py <leg> <csv> <outdir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import backtest_ict_scalp as bt  # noqa: E402
import regime_debt_matrix as rdm  # noqa: E402
from src.runtime import execution_costs  # noqa: E402
from src.units.strategies import load_strategy_config  # noqa: E402


def run_arm(leg: str, csv: str, out: Path, arm: str) -> dict:
    cfg = dict(load_strategy_config()[leg])
    symbol = cfg["symbols"][0]
    fee = rdm.roundtrip_fee_bps(symbol)
    slip, fund = execution_costs.resolve_cost_policy(symbol)
    argv, faithful, omitted = rdm.build_harness_cmd(
        leg, cfg, "ict_scalp", csv, str(cfg.get("timeframe")),
        str(out / f"{leg}_{arm}_trades.csv"), str(out / f"{leg}_{arm}.json"))
    argv = argv[1:]  # drop interpreter; keep script path as argv[0]
    argv += ["--slippage-bps-roundtrip", str(slip), "--funding-bps-per-window", str(fund)]
    orig = bt._load_yaml_params
    want = arm == "on"

    def patched(name=bt.DEFAULT_CFG_KEY):
        c = orig(name)
        c["htf_trend_filter_enabled"] = want
        return c

    bt._load_yaml_params = patched
    try:
        rc = bt.main(argv)
    finally:
        bt._load_yaml_params = orig
    res = json.loads((out / f"{leg}_{arm}.json").read_text()) if rc == 0 else {}
    return {"leg": leg, "arm": arm, "rc": rc, "faithful": faithful, "omitted_cfg_keys": omitted,
            "fee_bps_roundtrip": fee, "slippage_bps_roundtrip": slip,
            "funding_bps_per_window": fund, "argv": argv[1:], "summary": res}


if __name__ == "__main__":
    leg, csv, outdir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    rows = [run_arm(leg, csv, outdir, a) for a in ("off", "on")]
    (outdir / f"{leg}_arms.json").write_text(json.dumps(rows, indent=1, default=str))
    print("done", leg)
