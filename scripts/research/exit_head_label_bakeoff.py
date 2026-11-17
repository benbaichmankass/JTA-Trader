#!/usr/bin/env python3
# wiring: research/queue/RQ-20261117-aadc-04.yaml run.command (one trainer dispatch: rows.jsonl + candles are trainer-resident)
"""LABEL family -> EXIT HEAD: does training exit-head-donchian-1h-v1's recipe on a different TARGET improve its out-of-sample
exits, in that head's own walk-forward replay on one cost stack? (orphan ml-exit-head-donchian-1h, PI-20261117-ZFRREVN5-0003)

WHY: every graded iteration of this head changed FEATURES (volume composition at lookback 500 / 250: flat), UNIVERSE (BTC, SOL,
ETH: sign flips) or POOLING (donchian-4h family: FAIL). The lever map lists `labels` and `recipe` as untested. The shipped target
`holding_pays` = 1[final_r - open_r(t) >= +0.25 R] is read off a path whose tail is shaped by the trailing stop, so it asks
"will the trail leave me >= 0.25 R better off" -- a noisy question for a chandelier exit. Two targets already carried by
rows.jsonl ask it differently:
    holding_pays_0 = 1[future_r_delta >= 0]          (does holding pay AT ALL; the 0.25 R margin removed)
    more_mfe       = 1 - peak_is_in                  (is there still > 0.25 R of NEW favourable excursion ahead; a pure
                                                      truncation observable, independent of how the trail gives it back)

WHAT IT DOES (the volcomp_exit_head_bakeoff driver; every scoring primitive imported UNMODIFIED)
  * baseline trades: live-faithful harness (exit_head_replay._load_harness -> scripts/backtest_trend.py, params from
    config/strategies.yaml, _apply_venue_cost_policy = fee + slippage + funding);
  * sequential trade-count folds (exit_head_walkforward_multifold._fold_boundaries), 7-day embargo;
  * per fold, one head PER TARGET trained by train_exit_head.train_model (unchanged hyper-parameters, the shipped FEATURES)
    on pooled rows.jsonl rows with bar_t <= fold start - embargo;
  * every OOS trade re-resolved by exit_head_replay.replay_trade with the LIVE predicate (shape below_half_r, tau 0.10, close)
    once per arm; paired d = replayed_r(arm) - replayed_r(champion) on identical trades.
An arm whose target column is absent from rows.jsonl is reported `could_not_look`, never silently dropped.

Tier-1 research tooling: writes only --json. No config, model, registry or order path.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts", "ml"), os.path.join(_REPO_ROOT, "scripts", "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

UNIT = "RQ-20261117-aadc-04"
RULE_ID = "RULE-RQ20261117-aadc-04-EXITHEAD-LABEL"
LEGS = [("trend_donchian", "BTCUSDT"), ("trend_donchian_eth", "ETHUSDT"), ("trend_donchian_sol", "SOLUSDT")]
SHAPE = {"policy": "below_half_r", "tau": 0.10, "below_r": 0.5}     # the live artifact's shape
ACTION = "close"
CHAMPION = "holding_pays"
# derived target -> (source column, function of the source value); computed on a COPY of each training row
TARGETS = {
    "holding_pays_0": ("future_r_delta", lambda v: 1 if float(v) >= 0.0 else 0),
    "more_mfe": ("peak_is_in", lambda v: 1 - int(v)),
    # RQ-20261117-aadc-10: the margin lever continued past 0 (holding pays unless the trail will cost > 0.25 R)
    "holding_pays_neg25": ("future_r_delta", lambda v: 1 if float(v) >= -0.25 else 0),
}
DEFAULT_ARMS = ("holding_pays_0", "more_mfe")   # aadc-04's registered arms
N_OOS_MIN = 300
PASS_DR = 0.01
Z_DEFLATED = 2.241   # two-sided Bonferroni over the 2 label arms (alpha 0.05 / 2 -> z 2.241)


def _epoch(v: Any) -> Optional[int]:
    import pandas as pd
    try:
        return int(pd.Timestamp(v).tz_localize("UTC").timestamp()) if pd.Timestamp(v).tzinfo is None \
            else int(pd.Timestamp(v).timestamp())
    except Exception:  # noqa: BLE001  # allow-silent: an unparseable stamp is returned as None and the row is skipped by the caller
        return None


def with_target(rows: List[dict], arm: str) -> Optional[List[dict]]:
    """Copies of `rows` carrying the arm's target under train_exit_head.TARGET's name; None if the source column is absent."""
    if arm == CHAMPION:
        return rows
    src, fn = TARGETS[arm]
    have = [r for r in rows if r.get(src) is not None]
    if not have:
        return None
    return [{**r, CHAMPION: fn(r[src])} for r in have]


def paired(d: List[float], z: float = 1.96) -> Dict[str, Any]:
    n = len(d)
    if n < 2:
        return {"n": n, "mean": (d[0] if n else None), "se": None, "ci": None, "z": z}
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "mean": round(m, 5), "se": round(se, 5), "ci": [round(m - z * se, 5), round(m + z * se, 5)], "z": z}


def judge(arm_d: Dict[str, List[float]]) -> Dict[str, Any]:
    """RULE-RQ20261117-aadc-04 (registered before any run). Per arm: paired d vs champion, CI at Z_DEFLATED.
    PASS iff some arm has n >= N_OOS_MIN, mean >= PASS_DR and CI lower > 0 (chosen = highest mean among those).
    FAIL iff every arm is measured (n >= N_OOS_MIN) and every CI upper < PASS_DR. INDETERMINATE otherwise."""
    stats = {a: paired(d, Z_DEFLATED) for a, d in arm_d.items()}
    measured = {a: s for a, s in stats.items() if s["n"] >= N_OOS_MIN and s["ci"] is not None}
    winners = [a for a, s in measured.items() if s["mean"] >= PASS_DR and s["ci"][0] > 0]
    if winners:
        best = max(winners, key=lambda a: measured[a]["mean"])
        return {"verdict": "pass", "chosen": best, "why": f"{best} - champion {measured[best]['mean']:+.4f} R/trade, "
                f"deflated CI LB {measured[best]['ci'][0]:+.4f} > 0", "arms": stats}
    if measured and len(measured) == len(stats) and all(s["ci"][1] < PASS_DR for s in measured.values()):
        return {"verdict": "fail", "chosen": None, "why": "every label arm's deflated CI upper bound < +0.01 R/trade",
                "arms": stats}
    return {"verdict": "indeterminate", "chosen": None,
            "why": "an arm is below n_oos or between the pass bar and the fail floor", "arms": stats}


def run_leg(strategy: str, symbol: str, rows: List[dict], arms: List[str], a, harness, conf) -> Dict[str, Any]:
    import exit_head_walkforward_multifold as MF
    import train_exit_head as teh
    from exit_head_replay import replay_trade

    cfg = conf.get("strategies", conf).get(strategy)
    if not isinstance(cfg, dict):
        return {"leg": strategy, "read_state": "producer_failed", "why": f"no strategy {strategy!r} in config"}
    path = None
    if a.candles_dir:
        cand = [os.path.join(a.candles_dir, f"{symbol}_{a.timeframe}.csv"), os.path.join(a.candles_dir, f"{symbol}.csv")]
        path = next((c for c in cand if os.path.exists(c)), None)
    if path is None:
        from scripts.ops import backtest_data_source
        res = backtest_data_source.resolve_or_refuse(symbol, a.timeframe, None)
        if not res.ok:
            return {"leg": strategy, "read_state": "producer_failed",
                    "why": backtest_data_source.refusal_message(res, harness="exit_head_label_bakeoff.py", legacy_default=None)}
        path = res.path
    df = harness._load_candles(path)
    trades: List[Any] = []
    harness.run_backtest(
        df.copy(), donchian=int(cfg.get("donchian", 20)), atr_period=int(cfg.get("atr_period", 14)),
        atr_stop_mult=float(cfg.get("atr_stop_mult", 2.5)), trail_mult=float(cfg.get("trail_mult", 3.0)),
        timeout_bars=200, cooldown_bars=1, timeframe=a.timeframe, symbol=symbol,
        min_confidence=float(cfg.get("min_confidence", 0.0)), long_only=bool(cfg.get("long_only")), trades_out=trades)
    ordered = sorted(trades, key=lambda t: t.entry_time)
    fold_defs, block_n = MF._fold_boundaries([_epoch(t.entry_time) for t in ordered], a.num_folds)
    emb = a.embargo_days * 86400
    folds, recs = [], []
    for fd in fold_defs:
        test = ordered[fd["test_start_idx"]:fd["test_end_idx"]]
        cut = fd["test_start_ts"] - emb
        train = [r for r in rows if float(r.get("bar_t", 0)) <= cut]
        f = {"fold_index": fd["index"], "n_test_trades": len(test), "train_rows_n": len(train)}
        if len(test) < MF.MIN_FOLD_TEST_N or len(train) < MF._MIN_FOLD_TRAIN_ROWS:
            f.update({"read_state": "unestablishable", "reason": f"test n {len(test)} / train rows {len(train)} under floor"})
            folds.append(f)
            continue
        per_arm: Dict[str, List[dict]] = {}
        for arm in arms:
            tr = with_target(train, arm)
            if tr is None or len({int(r[CHAMPION]) for r in tr}) < 2:
                continue
            booster = teh.train_model(tr)
            art = {"features": list(teh.FEATURES), "shape": SHAPE}

            def predict(vec, _b=booster):
                # provenance: predict — P(class=1) of the binary booster for this arm's target (holding_pays-shaped)
                return float(_b.predict(vec)[0])
            per_arm[arm] = [replay_trade(df, t, art, predict, ACTION, lookback=a.lookback) for t in test]
        if CHAMPION not in per_arm:
            f.update({"read_state": "unestablishable", "reason": "champion did not train"})
            folds.append(f)
            continue
        for i, t in enumerate(test):
            recs.append({"leg": strategy, "fold": fd["index"], "baseline_r": float(t.r_multiple),
                         **{f"r_{arm}": float(per_arm[arm][i]["replayed_r"]) for arm in per_arm},
                         **{f"fired_{arm}": bool(per_arm[arm][i]["exit_head_fired"]) for arm in per_arm}})
        f.update({"read_state": "measured", "arms_trained": sorted(per_arm),
                  "n_fired": {arm: sum(1 for r in per_arm[arm] if r["exit_head_fired"]) for arm in per_arm}})
        folds.append(f)
        print(json.dumps({"leg": strategy, **{k: f[k] for k in ("fold_index", "n_test_trades", "n_fired")}}), flush=True)
    return {"leg": strategy, "symbol": symbol, "read_state": "measured" if recs else "unestablishable",
            "n_total_trades": len(ordered), "block_n": block_n, "folds": folds, "records": recs}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", default="datasets-out/exit_head/1h/donchian/rows.jsonl")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--legs", default=",".join(f"{s}:{y}" for s, y in LEGS))
    ap.add_argument("--num-folds", type=int, default=5)
    ap.add_argument("--embargo-days", type=float, default=7.0)
    ap.add_argument("--lookback", type=int, default=500)
    ap.add_argument("--candles-dir", default=None, help="local override: <dir>/<SYM>_<tf>.csv instead of the trainer resolver")
    ap.add_argument("--arms", default=",".join(DEFAULT_ARMS), help=f"label arms vs the champion, from {sorted(TARGETS)}")
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--rule-id", default=RULE_ID)
    ap.add_argument("--json", dest="json_out", required=False)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.json_out:
        ap.error("--json is required")
    try:
        from scripts.ml._heavy_queue import take_heavy_queue
        _lock = take_heavy_queue("exit-head-label-bakeoff")   # noqa: F841 — held for the process lifetime
    except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
        print(f"WARN heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked", file=sys.stderr)
    import train_exit_head as teh
    import yaml
    from pathlib import Path
    from exit_head_replay import _apply_venue_cost_policy, _load_harness

    rows_path = Path(a.rows) if os.path.isabs(a.rows) else Path(_REPO_ROOT) / a.rows
    rows = teh.load_rows(rows_path)
    label_arms = [x for x in a.arms.split(",") if x]
    unknown = [x for x in label_arms if x not in TARGETS]
    if unknown:
        ap.error(f"unknown arm(s) {unknown}; known {sorted(TARGETS)}")
    arms = [CHAMPION] + label_arms
    coverage = {arm: (sum(1 for r in rows if r.get(TARGETS[arm][0]) is not None) / len(rows) if rows else 0.0)
                for arm in label_arms}
    conf = yaml.safe_load(open(os.path.join(_REPO_ROOT, "config/strategies.yaml"), encoding="utf-8"))
    legs = [tuple(x.split(":")) for x in a.legs.split(",") if x]
    out_legs, cost = [], {}
    for strategy, symbol in legs:
        harness = _load_harness()
        cost[symbol] = _apply_venue_cost_policy(harness, symbol)
        out_legs.append(run_leg(strategy, symbol, rows, arms, a, harness, conf))
    recs = [r for lg in out_legs for r in lg.get("records", [])]
    arm_d = {arm: [r[f"r_{arm}"] - r[f"r_{CHAMPION}"] for r in recs if f"r_{arm}" in r] for arm in label_arms}
    j = judge(arm_d)
    context = {arm: paired([r[f"r_{arm}"] - r["baseline_r"] for r in recs if f"r_{arm}" in r]) for arm in arms}
    fired = {arm: sum(1 for r in recs if r.get(f"fired_{arm}")) for arm in arms}
    measured = bool(recs)
    n = max((s["n"] for s in j["arms"].values()), default=0)
    row = {"schema_version": 1, "research_unit": a.unit,
           "read_state": "measured" if measured else "producer_failed",
           "verdict": j["verdict"] if measured else "not_applicable", "note": j["why"], "n": n,
           "population": (f"OOS harness trades of {[leg for leg, _ in legs]} ({a.timeframe}), {a.num_folds}-fold sequential "
                          f"walk-forward per leg, one head per target retrained per fold on pooled rows.jsonl (n {len(rows)}) "
                          f"bar_t <= fold start - {a.embargo_days} d; paired per-trade replayed R vs the holding_pays champion"),
           "decision_rule": {"id": a.rule_id, "registered_at": "2026-11-17", "registered_before_run": True},
           "measurement": {"judge": j, "arm_dr_vs_hold_context": context, "fired": fired, "target_coverage": coverage,
                           "cost_basis": cost, "lookback": a.lookback,
                           "legs": [{k: v for k, v in lg.items() if k != "records"} for lg in out_legs]},
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "produced_by": {"tool": "python3 scripts/research/exit_head_label_bakeoff.py"}}
    open(a.json_out, "w", encoding="utf-8").write(json.dumps(row, indent=1, default=str) + "\n")
    print(json.dumps({k: row[k] for k in ("read_state", "verdict", "note", "n")}))
    return 0 if measured else 2


def _self_test() -> int:
    rows = [{"bar_t": i, "holding_pays": i % 2, "future_r_delta": (0.3 if i % 3 else -0.1), "peak_is_in": i % 4 == 0}
            for i in range(12)]
    assert with_target(rows, CHAMPION) is rows
    hn = with_target(rows, "holding_pays_neg25")
    assert all(r["holding_pays"] == 1 for r in hn), "every future_r_delta here is >= -0.25"
    h0 = with_target(rows, "holding_pays_0")
    assert [r["holding_pays"] for r in h0] == [0 if i % 3 == 0 else 1 for i in range(12)]
    assert rows[0]["holding_pays"] == 0 and rows[1]["holding_pays"] == 1, "the source rows must not be mutated"
    mm = with_target(rows, "more_mfe")
    assert [r["holding_pays"] for r in mm] == [0 if i % 4 == 0 else 1 for i in range(12)]
    assert with_target([{"bar_t": 1, "holding_pays": 1}], "more_mfe") is None, "an absent source column is could_not_look"
    assert judge({"holding_pays_0": [0.03] * 400, "more_mfe": [0.0] * 400})["chosen"] == "holding_pays_0"
    assert judge({"holding_pays_0": [-0.01, 0.0] * 200, "more_mfe": [0.0, -0.005] * 200})["verdict"] == "fail"
    assert judge({"holding_pays_0": [0.03] * 100, "more_mfe": [0.03] * 100})["verdict"] == "indeterminate"
    assert judge({"holding_pays_0": [-0.01, 0.0] * 200, "more_mfe": [0.03] * 100})["verdict"] == "indeterminate"
    print("exit_head_label_bakeoff self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
