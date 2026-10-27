#!/usr/bin/env python3
# wiring: research/queue/RQ-20261027-8a01-01.yaml, research/queue/RQ-20261027-8a01-02.yaml (via research-script-run.yml)
"""DESK-8a: confirm run of one ict_scalp 15m leg on a FRESH, DISJOINT window.

The committed Stage-0 records for ict_scalp_eth_15m / ict_scalp_xrp_15m cover the
trailing 365 d and 730 d ending 2026-10-02 (comms/strategy_evidence/). A "fresh
window" has to be disjoint from both, or it re-reads the same trades: the default
window here is 2022-10-01..2024-09-30 (the 730 d immediately BEFORE the 730 d
record's start, 2024-10-02). Composes, does not rewrite: the harness command is
`regime_debt_matrix.build_harness_cmd` (the leg's live config -> the same levers
`build_strategy_evidence.py` measures), costs come from
`execution_costs.resolve_cost_policy`, folds from `build_strategy_evidence.time_folds`.

The rule is registered in the queue unit BEFORE the run and is the SAME bar as
RULE-ICTSCALP-CAUSAL-REBUILD (n >= 88, net R > 0, expectancy > 0, strict majority
of 4 folds positive). Nothing here is tuned; the bootstrap CI is reported beside
the verdict and decides nothing.

    ict_scalp_confirm.py --leg ict_scalp_eth_15m --out DIR [--start 2022-10-01 --end 2024-09-30]
    ict_scalp_confirm.py --self-test

Writes DIR/verdict.json (read by script_run.py). Research tooling: no config write.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

RULE_ID = "RULE-DESK8A-ICTSCALP-FRESH-WINDOW-CONFIRM"
MIN_N = 88          # the floor RULE-ICTSCALP-CAUSAL-REBUILD registered (d=0.3 at alpha .05 / power .8)
FOLDS = 4
BOOT_DRAWS = 10_000
BOOT_SEED = 20261027
LEGS = ("ict_scalp_eth_15m", "ict_scalp_xrp_15m")


def decide(trades: list[dict], fidelity: str | None) -> dict:
    """The registered rule, on a list of trade rows carrying net_r and entry_time."""
    from build_strategy_evidence import time_folds  # noqa: PLC0415
    rs = [float(t.get("net_r") or 0.0) for t in trades]
    n = len(rs)
    fd = time_folds(trades, FOLDS)
    pos = sum(1 for f in fd if f["net_r"] > 0)
    net = round(sum(rs), 4)
    exp = round(net / n, 4) if n else None
    rng = random.Random(BOOT_SEED)
    means = sorted(sum(rng.choice(rs) for _ in range(n)) / n for _ in range(BOOT_DRAWS)) if n else []
    ci = [round(means[int(0.025 * BOOT_DRAWS)], 4), round(means[int(0.975 * BOOT_DRAWS) - 1], 4)] if n else None
    clauses = {
        "n_ge_88": n >= MIN_N,
        "net_r_gt_0": net > 0,
        "expectancy_gt_0": bool(exp is not None and exp > 0),
        "strict_majority_folds_positive": 2 * pos > len(fd) and len(fd) == FOLDS,
        "fidelity_faithful": fidelity == "faithful",
    }
    if n == 0:
        verdict, state = "not_applicable", "no_data"
    elif n < MIN_N:
        verdict, state = "indeterminate", "measured"      # UNDERPOWERED, never FAIL
    elif all(clauses.values()):
        verdict, state = "pass", "measured"
    else:
        verdict, state = "fail", "measured"
    return {"verdict": verdict, "read_state": state, "n": n, "net_r": net, "expectancy_r": exp,
            "expectancy_ci95_bootstrap": ci, "folds": len(fd), "folds_positive": pos,
            "fold_detail": fd, "clauses": clauses, "fidelity": fidelity}


def run_leg(leg: str, start: str, end: str, workdir: str) -> dict:
    import regime_debt_matrix as rdm  # noqa: PLC0415
    from src.runtime.execution_costs import resolve_cost_policy  # noqa: PLC0415
    cfg = rdm.resolve_strategy(leg)
    if not cfg:
        return {"verdict": "not_applicable", "read_state": "no_data", "note": f"{leg} not in strategies.yaml"}
    sym = cfg["symbols"][0]
    feed = rdm.resolve_feed(sym, cfg["timeframe"])
    csv = os.path.join(workdir, f"{leg}__data.csv")
    emit = os.path.join(workdir, f"{leg}__trades.jsonl")
    jout = os.path.join(workdir, f"{leg}__bt.json")
    subprocess.run([sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", feed["ticker"],
                    "--interval", feed["interval"], "--start-date", start, "--end-date", end,
                    "--output", csv, "--source", "binance_vision"], check=True, cwd=REPO)
    argv, faithful, omitted = rdm.build_harness_cmd(leg, cfg, "ict_scalp", csv, feed["resample"], emit, jout)
    slip, fund = resolve_cost_policy(sym)
    argv += ["--slippage-bps-roundtrip", str(slip), "--funding-bps-per-window", str(fund)]
    subprocess.run(argv, check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    trades = [json.loads(x) for x in Path(emit).read_text().splitlines() if x.strip()]
    out = decide(trades, "faithful" if faithful else "approximate")
    out.update({"leg": leg, "symbol": sym, "window": {"start": start, "end": end},
                "cost_stack": {"fee_bps_roundtrip": rdm.roundtrip_fee_bps(sym), "slippage_bps_roundtrip": slip,
                               "funding_bps_per_window": fund, "source": "execution_costs.resolve_cost_policy"},
                "omitted_levers": omitted, "decision_rule_id": RULE_ID})
    return out


def self_test() -> int:
    mk = lambda i, r: {"entry_time": f"2023-01-{1 + i // 4:02d}T{i % 24:02d}:00", "net_r": r}  # noqa: E731
    good = decide([mk(i, 0.3 if i % 2 else -0.1) for i in range(100)], "faithful")
    assert good["verdict"] == "pass", good
    assert decide([mk(i, -0.1) for i in range(100)], "faithful")["verdict"] == "fail"
    assert decide([mk(i, 0.3) for i in range(50)], "faithful")["verdict"] == "indeterminate"
    assert decide([mk(i, 0.3) for i in range(100)], "approximate")["verdict"] == "fail"
    assert decide([], "faithful")["verdict"] == "not_applicable"
    print("ict_scalp_confirm self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", choices=LEGS)
    ap.add_argument("--out")
    ap.add_argument("--start", default="2022-10-01")
    ap.add_argument("--end", default="2024-09-30")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.leg and a.out):
        ap.error("--leg and --out are required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as wd:
        try:
            res = run_leg(a.leg, a.start, a.end, wd)
        except Exception as e:  # allow-silent: not silent -- written to verdict.json as read_state producer_failed with the exception text; noqa: BLE001
            res = {"verdict": "not_applicable", "read_state": "producer_failed",
                   "note": f"{type(e).__name__}: {e}", "leg": a.leg}
    doc = {"verdict": res["verdict"], "read_state": res["read_state"], "n": res.get("n", 0),
           "population": f"{a.leg} {a.start}..{a.end}, trades from the live config on a disjoint fresh window; "
                         "net of fee + slippage + funding from execution_costs.resolve_cost_policy",
           "measurement": res, "note": res.get("note", "")}
    (out / "verdict.json").write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(json.dumps({k: doc[k] for k in ("verdict", "read_state", "n")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
