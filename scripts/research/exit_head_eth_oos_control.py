#!/usr/bin/env python3
"""RQ-20261101-78fc-03: does exit-head-donchian-1h-v1's recipe add value OUT OF SAMPLE on trend_donchian_eth?

WHY THIS EXISTS (row ETH-EXITHEAD-CONTROL-TEST, operator 2026-11-11 Thursday-planning b6, verbatim "Confirm: run the control test";
row ML-VOLGATE-EXITHEAD-REPLAY = the replay command 78fc-03's blocked_on names). The head closes trend_donchian_eth trades live on bybit_1
on an ETH read that was IN-SAMPLE only (+0.0215 R/trade, n=583); the multi-fold OOS walk-forward (RQ-20260927-002) ran on BTC only.

WHAT IT DOES. The RQ-20260927-002 method, unchanged, on ETHUSDT 1h trend_donchian_eth trades: sequential trade-count folds
(``exit_head_walkforward_multifold._fold_boundaries``, imported), a LightGBM head retrained per fold on the pooled rows.jsonl rows
with bar_t <= fold start - embargo (``train_exit_head.train_model``, unmodified), and each test trade re-resolved by
``exit_head_replay.replay_trade`` (the live predicate ``exit_head_shadow.would_exit_for``). Added, and only added:
  1. the 78fc-03 statistic: per-trade dR = replayed_r - baseline_r over every OOS trade; mean and a trade-clustered (one trade = one
     cluster, so the plain per-trade SE) 95% CI lower bound;
  2. a matched RANDOM-TRUNCATION control (practice principle T1; operator "run the control test"): per fold, draw as many test trades as
     the head fired on and close each at a uniformly random in-trade bar's close; 1000 draws; the head's pooled dR is compared with the
     control's p50 / p95. REPORTED, not gating: 78fc-03's registered rule does not include it, and this driver does not change the rule.

RULE (RULE-RQ-20261101-78fc-03, registered 2026-11-01, restated not re-decided): INDETERMINATE if n_oos < 300. KEEP iff OOS dR/trade >= 0
AND trade-clustered 95% CI LB > -0.02 R. Else FAIL (a data-backed Tier-3 de-risk proposal: exit_head_action -> annotate on
trend_donchian_eth; held for the manager).

FIDELITY (stated, as RQ-20260927-002): the baseline harness run passes donchian / atr_period / atr_stop_mult / trail_mult / min_confidence /
long_only from config/strategies.yaml; other declared exit levers of the leg are not modelled. Both arms are charged the same per-trade
cost, so the paired delta is net of cost by construction; the head's discretionary close is NOT charged an extra slippage side.

Runs on the trainer (rows.jsonl is trainer-resident), dispatched once via the trainer-vm-diag relay. Writes only --json.
"""
# wiring: manual-only - one trainer-vm-diag dispatch for research/queue/RQ-20261101-78fc-03.yaml (run.note); not called from CI.
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts", "ml"), os.path.join(_REPO_ROOT, "scripts", "research")):
    if p not in sys.path:
        sys.path.insert(0, p)

RULE_ID = "RULE-RQ-20261101-78fc-03"
N_OOS_MIN = 300
LB_BAR = -0.02
CONTROL_DRAWS = 1000
CONTROL_SEED = 20261112
SHAPE = {"policy": "below_half_r", "tau": 0.10, "below_r": 0.5}     # the live artifact's shape (multifold.SHAPE)
ACTION = "close"


def bar_r(candles, trade, i: int) -> float:
    close = float(candles["close"].iloc[i])
    return ((close - trade.entry) if trade.direction == "long" else (trade.entry - close)) / trade.risk


def control_draws(candles, fold_trades: list, k_per_fold: list[int], draws: int, seed: int) -> list[float]:
    """Pooled random-truncation dR per draw: per fold, k random trades each closed at a uniform in-trade bar."""
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        tot = 0.0
        for trades, k in zip(fold_trades, k_per_fold):
            if k <= 0 or not trades:
                continue
            for t in rng.sample(trades, min(k, len(trades))):
                lo, hi = t.entry_index + 1, t.exit_index
                if hi < lo:
                    continue
                tot += bar_r(candles, t, rng.randint(lo, hi)) - float(t.r_multiple)
        out.append(tot)
    return out


def judge(deltas: list[float]) -> dict:
    n = len(deltas)
    if n < N_OOS_MIN:
        return {"verdict": "indeterminate", "n_oos": n, "why": f"n_oos {n} < {N_OOS_MIN}"}
    m = sum(deltas) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in deltas) / (n - 1)) if n > 1 else 0.0
    lb = m - 1.96 * sd / math.sqrt(n)
    keep = m >= 0 and lb > LB_BAR
    return {"verdict": "pass" if keep else "fail", "n_oos": n, "dr_per_trade": round(m, 5), "se": round(sd / math.sqrt(n), 5),
            "ci95_lb": round(lb, 5),
            "why": (f"KEEP: OOS dR/trade {m:+.4f} >= 0 and CI LB {lb:+.4f} > {LB_BAR}" if keep else
                    f"FAIL: OOS dR/trade {m:+.4f}, CI LB {lb:+.4f} (needs >= 0 and > {LB_BAR}) -> Tier-3 proposal: annotate on "
                    "trend_donchian_eth (held for the manager)")}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strategy", default="trend_donchian_eth")
    ap.add_argument("--symbol", default="ETHUSDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--rows", default="datasets-out/exit_head/1h/donchian/rows.jsonl")
    ap.add_argument("--num-folds", type=int, default=5)
    ap.add_argument("--embargo-days", type=float, default=7.0)
    ap.add_argument("--lookback", type=int, default=500)
    ap.add_argument("--json", dest="json_out", required=True)
    a = ap.parse_args(argv[1:])

    from pathlib import Path

    import exit_head_walkforward_multifold as MF
    import train_exit_head as teh
    import yaml
    from exit_head_replay import _apply_venue_cost_policy, _load_harness, replay_trade

    from scripts.ops import backtest_data_source

    conf = yaml.safe_load(open(os.path.join(_REPO_ROOT, "config/strategies.yaml"), encoding="utf-8"))
    cfg = conf.get("strategies", conf).get(a.strategy)
    if not isinstance(cfg, dict):
        print(f"ERROR: no strategy {a.strategy!r}", file=sys.stderr)
        return 2
    res = backtest_data_source.resolve_or_refuse(a.symbol, a.timeframe, None)
    if not res.ok:
        print(backtest_data_source.refusal_message(res, harness="exit_head_eth_oos_control.py", legacy_default=None), file=sys.stderr)
        return 2
    harness = _load_harness()
    cost_basis = _apply_venue_cost_policy(harness, a.symbol)
    df = harness._load_candles(res.path)
    trades: list[Any] = []
    baseline = harness.run_backtest(
        df.copy(), donchian=int(cfg.get("donchian", 20)), atr_period=int(cfg.get("atr_period", 14)),
        atr_stop_mult=float(cfg.get("atr_stop_mult", 2.5)), trail_mult=float(cfg.get("trail_mult", 3.0)),
        timeout_bars=200, cooldown_bars=1, timeframe=a.timeframe, symbol=a.symbol,
        min_confidence=float(cfg.get("min_confidence", 0.0)), long_only=bool(cfg.get("long_only")), trades_out=trades)
    ordered = sorted(trades, key=lambda t: t.entry_time)
    epochs = [datetime.fromisoformat(str(t.entry_time).replace("Z", "+00:00")).timestamp()
              if not isinstance(t.entry_time, (int, float)) else float(t.entry_time) for t in ordered]
    fold_defs, block_n = MF._fold_boundaries(epochs, a.num_folds)
    rows_path = Path(a.rows) if os.path.isabs(a.rows) else Path(_REPO_ROOT) / a.rows
    rows = teh.load_rows(rows_path)
    emb = a.embargo_days * 86400

    folds, deltas, fold_trades, k_fired = [], [], [], []
    for fd in fold_defs:
        test = ordered[fd["test_start_idx"]:fd["test_end_idx"]]
        cut = fd["test_start_ts"] - emb
        train = [r for r in rows if float(r.get("bar_t", 0)) <= cut]
        f = {"fold_index": fd["index"], "n_test_trades": len(test), "train_rows_n": len(train),
             "test_start": datetime.fromtimestamp(fd["test_start_ts"], tz=timezone.utc).isoformat(),
             "train_cutoff": datetime.fromtimestamp(cut, tz=timezone.utc).isoformat()}
        if len(test) < MF.MIN_FOLD_TEST_N or len(train) < MF._MIN_FOLD_TRAIN_ROWS:
            f.update({"read_state": "unestablishable", "reason": f"test n {len(test)} / train rows {len(train)} under floor"})
            folds.append(f)
            continue
        booster = teh.train_model(train)
        art = {"features": teh.FEATURES, "shape": SHAPE}

        def predict(vec, _b=booster):
            # provenance: predict — P(class=1) of the binary holding_pays booster (exit_head_walkforward_multifold.py's closure)
            return float(_b.predict(vec)[0])

        recs = [replay_trade(df, t, art, predict, ACTION, lookback=a.lookback) for t in test]
        d = [float(r["replayed_r"]) - float(r["baseline_r"]) for r in recs]
        deltas += d
        fold_trades.append(test)
        k_fired.append(sum(1 for r in recs if r["exit_head_fired"]))
        f.update({"read_state": "measured", "recovered_r_oos": round(sum(d), 4), "dr_per_trade": round(sum(d) / len(d), 5),
                  "n_fired_oos": k_fired[-1]})
        folds.append(f)
        print(json.dumps({k: f[k] for k in ("fold_index", "n_test_trades", "recovered_r_oos", "n_fired_oos")}), flush=True)

    j = judge(deltas)
    ctl = sorted(control_draws(df, fold_trades, k_fired, CONTROL_DRAWS, CONTROL_SEED)) if deltas else []
    head_sum = round(sum(deltas), 4)
    control = None
    if ctl:
        control = {"draws": CONTROL_DRAWS, "seed": CONTROL_SEED, "k_fired_per_fold": k_fired, "p50": round(ctl[len(ctl) // 2], 4),
                   "p95": round(ctl[int(0.95 * len(ctl)) - 1], 4), "head_recovered_r": head_sum,
                   "head_beats_control_p95": head_sum > ctl[int(0.95 * len(ctl)) - 1],
                   "head_pct_rank": round(sum(1 for c in ctl if c < head_sum) / len(ctl), 4), "gating": False}
    row = {"schema_version": 1, "research_unit": "RQ-20261101-78fc-03", "read_state": "measured" if deltas else "producer_failed",
           "verdict": j["verdict"] if deltas else "not_applicable", "note": j["why"], "n": j.get("n_oos"),
           "population": {"n": j.get("n_oos"), "description": (
               f"{a.strategy} {a.symbol} {a.timeframe} harness trades, {a.num_folds}-fold sequential walk-forward (block_n {block_n}), "
               f"head retrained per fold on pooled rows.jsonl bar_t <= fold start - {a.embargo_days} d; paired dR per OOS trade")},
           "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-01", "registered_before_run": True},
           "measurement": {"judge": j, "folds": folds, "control_random_truncation": control, "cost_basis": cost_basis,
                           "baseline_net_total_r": baseline.get("net_total_r"), "n_total_trades": len(ordered),
                           "data_start": str(df["timestamp"].iloc[0]) if len(df) else None,
                           "data_end": str(df["timestamp"].iloc[-1]) if len(df) else None, "lookback": a.lookback},
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "produced_by": {"tool": "python3 scripts/research/exit_head_eth_oos_control.py", "where": "trainer (trainer-vm-diag relay)"}}
    out = json.dumps(row, indent=1, default=str)
    open(a.json_out, "w", encoding="utf-8").write(out + "\n")
    print("RESULT_JSON_BEGIN")
    print(out)
    print("RESULT_JSON_END")
    return 0 if deltas else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
