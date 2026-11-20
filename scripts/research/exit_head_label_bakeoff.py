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
# FEATURE family (lane ML-PRIMARY-17, 2026-11-20; research/levers/ml-exit-head-donchian-1h.yaml `features: untested` after the
# neg25 label lever closed): same champion TARGET and hyper-parameters, a different FEATURE LIST. Each arm is a pure function of
# train_exit_head.FEATURES / FEATURES_EXH, resolved at run time. Every listed column is emitted by the live
# src.runtime.exit_head_shadow._feature_row, so the replay scores each arm on the same rows the monitor would build.
FEATURE_ARMS = {
    "feat_exh": lambda base, exh: list(base) + list(exh),                                    # + M20 P4.3 exhaustion block
    "feat_no_calendar": lambda base, exh: [f for f in base if f not in ("hour_of_day", "dayofweek")],
    "feat_no_volume": lambda base, exh: [f for f in base if f != "vol_ratio_vs_entry"],
    "feat_path_only": lambda base, exh: [f for f in base if f in ("age_bars", "open_r", "mfe_r", "mae_r", "giveback_r",
                                                                   "dist_to_stop_r", "is_long")],
}
FEATURE_COVERAGE_MIN = 0.90   # an arm whose ADDED columns are non-null on fewer rows is could_not_look (not trained)


def arm_features(teh, arm: str) -> List[str]:
    """The feature list an arm trains and replays on: the shipped FEATURES for the champion and every label arm."""
    if arm in FEATURE_ARMS:
        return FEATURE_ARMS[arm](teh.FEATURES, getattr(teh, "FEATURES_EXH", []))
    return list(teh.FEATURES)


def feature_coverage(rows: List[dict], feats: List[str], base: List[str]) -> float:
    """Share of rows on which every column the arm ADDS over the shipped list is non-null (1.0 for a pure ablation)."""
    added = [f for f in feats if f not in base]
    if not added or not rows:
        return 1.0 if rows else 0.0
    return sum(1 for r in rows if all(r.get(f) is not None for f in added)) / len(rows)


def train_with_features(teh, rows: List[dict], feats: List[str]):
    """train_exit_head.train_model on `feats` (its matrix() reads the module global FEATURES); the global is restored."""
    saved = teh.FEATURES
    teh.FEATURES = list(feats)
    try:
        return teh.train_model(rows)
    finally:
        teh.FEATURES = saved
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


PEAK_EPS_R = 0.25   # scripts/ml/build_exit_head_dataset.py HOLDING_PAYS_R, the eps its peak_is_in pass uses


def derive_peak_is_in(rows: List[dict]) -> Dict[str, Any]:
    """D8 more_mfe (RQ-20261119-a10d-06): stamp peak_is_in on rows built before the builder's second pass existed, IN PLACE,
    with the builder's own definition (build_exit_head_dataset.py, "M20 P4.2 label"): per trade, final MFE = the running
    mfe_r at the trade's last bar (the builder emits one row per bar of the hold and mfe_r is a running max, so it is the
    trade's max mfe_r); peak_is_in = 1 iff final MFE - mfe_r(t) <= 0.25 R. A truncation observable from the row's own trade,
    no barrier re-simulation. Rows that already carry peak_is_in are left untouched; rows without trade_key or mfe_r are
    left without it (could_not_look, never imputed). Returns the counts so the result can say where the label came from."""
    final: Dict[str, float] = {}
    for r in rows:
        k, m = r.get("trade_key"), r.get("mfe_r")
        if k is None or m is None:
            continue
        final[k] = max(final.get(k, float("-inf")), float(m))
    had = derived = missing = 0
    for r in rows:
        if r.get("peak_is_in") is not None:
            had += 1
            continue
        k, m = r.get("trade_key"), r.get("mfe_r")
        if k is None or m is None or k not in final:
            missing += 1
            continue
        fmd = final[k] - float(m)
        r["future_mfe_delta"] = round(fmd, 4)
        r["peak_is_in"] = 1 if fmd <= PEAK_EPS_R else 0
        derived += 1
    return {"rows": len(rows), "already_labelled": had, "derived": derived, "not_derivable": missing, "trades": len(final)}


PEAK_MIN_DERIVABLE = 0.90   # a10d-06: below this share of rows labelled, more_mfe is could_not_look (INDETERMINATE)


def peak_derivable_share(src: Dict[str, Any]) -> float:
    return (src["already_labelled"] + src["derived"]) / src["rows"] if src.get("rows") else 0.0


def with_target(rows: List[dict], arm: str) -> Optional[List[dict]]:
    """Copies of `rows` carrying the arm's target under train_exit_head.TARGET's name; None if the source column is absent."""
    if arm == CHAMPION or arm in FEATURE_ARMS:
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


def judge(arm_d: Dict[str, List[float]], z: float = None, pass_dr: float = None) -> Dict[str, Any]:
    """RULE-RQ20261117-aadc-04 (registered before any run). Per arm: paired d vs champion, CI at Z_DEFLATED.
    PASS iff some arm has n >= N_OOS_MIN, mean >= PASS_DR and CI lower > 0 (chosen = highest mean among those).
    FAIL iff every arm is measured (n >= N_OOS_MIN) and every CI upper < PASS_DR. INDETERMINATE otherwise."""
    z = Z_DEFLATED if z is None else z
    pass_dr = PASS_DR if pass_dr is None else pass_dr
    stats = {a: paired(d, z) for a, d in arm_d.items()}
    measured = {a: s for a, s in stats.items() if s["n"] >= N_OOS_MIN and s["ci"] is not None}
    winners = [a for a, s in measured.items() if s["mean"] >= pass_dr and s["ci"][0] > 0]
    if winners:
        best = max(winners, key=lambda a: measured[a]["mean"])
        return {"verdict": "pass", "chosen": best, "why": f"{best} - champion {measured[best]['mean']:+.4f} R/trade, "
                f"deflated CI LB {measured[best]['ci'][0]:+.4f} > 0", "arms": stats}
    if measured and len(measured) == len(stats) and all(s["ci"][1] < pass_dr for s in measured.values()):
        return {"verdict": "fail", "chosen": None, "why": "every arm's deflated CI upper bound < +0.01 R/trade",
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
    path, resample = None, None
    if a.candles_dir:
        cand = [os.path.join(a.candles_dir, f"{symbol}_{a.timeframe}.csv"), os.path.join(a.candles_dir, f"{symbol}.csv")]
        path = next((c for c in cand if os.path.exists(c)), None)
    if path is None:
        from scripts.ops import backtest_data_source
        res = backtest_data_source.resolve_or_refuse(symbol, a.timeframe, None)
        if not res.ok:
            return {"leg": strategy, "read_state": "producer_failed",
                    "why": backtest_data_source.refusal_message(res, harness="exit_head_label_bakeoff.py", legacy_default=None)}
        path, resample = res.path, res.resample
    from scripts.ops.backtest_data_source import load_resolved_frame
    df = load_resolved_frame(harness, path, resample)   # honour the resolver's grain (5m/15m file -> the leg's tf)
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
            feats = arm_features(teh, arm)
            if feature_coverage(tr, feats, teh.FEATURES) < FEATURE_COVERAGE_MIN:
                continue   # could_not_look: the added columns are absent from these rows; never trained on NaN
            booster = train_with_features(teh, tr, feats)
            art = {"features": feats, "shape": SHAPE}

            def predict(vec, _b=booster):
                # provenance: predict_proba — P(class=1) (was .predict = the class label, fixed 2026-11-18) of the binary booster for this arm's target (holding_pays-shaped)
                return float(_b.predict_proba(vec)[0][1])  # P(class=1); .predict would be the 0/1 class label
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
    return {"leg": strategy, "symbol": symbol, "candle_source": {"path": str(path), "resampled_to": resample, "bars": len(df)}, "read_state": "measured" if recs else "unestablishable",
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
    ap.add_argument("--arms", default=",".join(DEFAULT_ARMS), help=f"label arms vs the champion, from {sorted(TARGETS)}; 'none' = feature arms only")
    ap.add_argument("--feature-arms", default="", help=f"feature arms vs the champion (champion target), from {sorted(FEATURE_ARMS)}")
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--exclude-train-symbol", action="append", default=[],
                    help="drop rows.jsonl rows of this symbol from every fold's training (a held-out-symbol read); repeatable")
    ap.add_argument("--z", type=float, default=Z_DEFLATED, help="CI z for the judge (default the aadc-04 deflated 2.241)")
    ap.add_argument("--pass-dr", type=float, default=PASS_DR, help="pass bar in R/trade (default +0.01)")
    ap.add_argument("--derive-peak-is-in", action="store_true",
                    help="RQ-20261119-a10d-06: stamp peak_is_in from trade_key + mfe_r on rows that predate the builder's pass")
    ap.add_argument("--rule-id", default=RULE_ID)
    ap.add_argument("--registered-at", default="2026-11-17", help="the unit's decision_rule.registered_at (default aadc-04/-11's)")
    ap.add_argument("--json", dest="json_out", required=False)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.json_out:
        ap.error("--json is required")
    label_arms = [] if a.arms.strip().lower() == "none" else [x for x in a.arms.split(",") if x]
    unknown = [x for x in label_arms if x not in TARGETS]
    if unknown:
        ap.error(f"unknown arm(s) {unknown}; known {sorted(TARGETS)}")
    feat_arms = [x for x in a.feature_arms.split(",") if x]
    unknown_f = [x for x in feat_arms if x not in FEATURE_ARMS]
    if unknown_f:
        ap.error(f"unknown feature arm(s) {unknown_f}; known {sorted(FEATURE_ARMS)}")
    if not label_arms and not feat_arms:
        ap.error("no arm to judge: pass --arms and/or --feature-arms")
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
    peak_source = derive_peak_is_in(rows) if a.derive_peak_is_in else None
    from collections import Counter
    rows_by_symbol = dict(Counter(str(r.get("symbol") or "unknown") for r in rows))
    excl = set(a.exclude_train_symbol)
    if excl:
        rows = [r for r in rows if str(r.get("symbol") or "unknown") not in excl]
    arms = [CHAMPION] + label_arms + feat_arms
    coverage = {arm: (sum(1 for r in rows if r.get(TARGETS[arm][0]) is not None) / len(rows) if rows else 0.0)
                for arm in label_arms}
    coverage.update({arm: round(feature_coverage(rows, arm_features(teh, arm), teh.FEATURES), 4) for arm in feat_arms})
    arm_feature_lists = {arm: arm_features(teh, arm) for arm in arms}
    conf = yaml.safe_load(open(os.path.join(_REPO_ROOT, "config/strategies.yaml"), encoding="utf-8"))
    legs = [tuple(x.split(":")) for x in a.legs.split(",") if x]
    out_legs, cost = [], {}
    for strategy, symbol in legs:
        harness = _load_harness()
        cost[symbol] = _apply_venue_cost_policy(harness, symbol)
        out_legs.append(run_leg(strategy, symbol, rows, arms, a, harness, conf))
    recs = [r for lg in out_legs for r in lg.get("records", [])]
    arm_d = {arm: [r[f"r_{arm}"] - r[f"r_{CHAMPION}"] for r in recs if f"r_{arm}" in r] for arm in label_arms + feat_arms}
    j = judge(arm_d, a.z, a.pass_dr)
    context = {arm: paired([r[f"r_{arm}"] - r["baseline_r"] for r in recs if f"r_{arm}" in r]) for arm in arms}
    fired = {arm: sum(1 for r in recs if r.get(f"fired_{arm}")) for arm in arms}
    measured = bool(recs)
    n = max((s["n"] for s in j["arms"].values()), default=0)
    if peak_source is not None and peak_derivable_share(peak_source) < PEAK_MIN_DERIVABLE:   # a10d-06 rule: could_not_look
        j = {**j, "verdict": "indeterminate",
             "why": f"peak_is_in derivable on {peak_derivable_share(peak_source):.3f} of rows < {PEAK_MIN_DERIVABLE} (could_not_look); judge: {j['why']}"}
    row = {"schema_version": 1, "research_unit": a.unit,
           "read_state": "measured" if measured else "producer_failed",
           "verdict": j["verdict"] if measured else "not_applicable", "note": j["why"], "n": n,
           "population": (f"OOS harness trades of {[leg for leg, _ in legs]} ({a.timeframe}), {a.num_folds}-fold sequential "
                          f"walk-forward per leg, one head per target retrained per fold on pooled rows.jsonl (n {len(rows)}) "
                          f"bar_t <= fold start - {a.embargo_days} d; paired per-trade replayed R vs the holding_pays champion"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {"judge": j, "arm_dr_vs_hold_context": context, "fired": fired, "target_coverage": coverage,
                           "arm_features": arm_feature_lists,
                           "peak_is_in_source": peak_source,
                           "cost_basis": cost, "lookback": a.lookback,
                           "rows_by_symbol": rows_by_symbol, "excluded_train_symbols": sorted(excl),
                           "train_rows_after_exclusion": len(rows), "z": a.z, "pass_dr": a.pass_dr,
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
    # a10d-06: peak_is_in derived from trade_key + running mfe_r equals the builder's definition (final MFE - MFE(t) <= 0.25)
    tr = [{"trade_key": "A", "mfe_r": m} for m in (0.0, 0.4, 0.9, 1.0, 1.0)] + [{"trade_key": "B", "mfe_r": 0.2},
          {"trade_key": None, "mfe_r": 0.1}, {"trade_key": "C", "mfe_r": 0.5, "peak_is_in": 0}]
    st = derive_peak_is_in(tr)
    assert [r.get("peak_is_in") for r in tr] == [0, 0, 1, 1, 1, 1, None, 0], [r.get("peak_is_in") for r in tr]
    assert st == {"rows": 8, "already_labelled": 1, "derived": 6, "not_derivable": 1, "trades": 3}, st
    assert tr[1]["future_mfe_delta"] == 0.6 and with_target(tr, "more_mfe") is not None
    assert abs(peak_derivable_share(st) - 7 / 8) < 1e-12 and peak_derivable_share(st) < PEAK_MIN_DERIVABLE
    assert judge({"holding_pays_0": [0.03] * 400, "more_mfe": [0.0] * 400})["chosen"] == "holding_pays_0"
    assert judge({"holding_pays_0": [-0.01, 0.0] * 200, "more_mfe": [0.0, -0.005] * 200})["verdict"] == "fail"
    assert judge({"holding_pays_0": [0.03] * 100, "more_mfe": [0.03] * 100})["verdict"] == "indeterminate"
    assert judge({"holding_pays_neg25": [0.006, 0.004] * 200}, 1.96, 0.005)["verdict"] == "pass"
    assert judge({"holding_pays_neg25": [0.006, 0.004] * 200})["verdict"] == "fail"   # default bar +0.01
    assert judge({"holding_pays_0": [-0.01, 0.0] * 200, "more_mfe": [0.03] * 100})["verdict"] == "indeterminate"
    # feature arms: champion target unchanged, feature lists derived from the shipped lists, coverage gates added columns only
    class _T:
        FEATURES = ["age_bars", "open_r", "mfe_r", "mae_r", "giveback_r", "dist_to_stop_r", "vol_ratio_vs_entry",
                    "hour_of_day", "dayofweek", "is_long"]
        FEATURES_EXH = ["bars_since_peak", "mom_8"]
    assert with_target(rows, "feat_exh") is rows
    assert arm_features(_T, CHAMPION) == _T.FEATURES and arm_features(_T, "more_mfe") == _T.FEATURES
    assert arm_features(_T, "feat_exh") == _T.FEATURES + _T.FEATURES_EXH
    assert "hour_of_day" not in arm_features(_T, "feat_no_calendar") and len(arm_features(_T, "feat_no_calendar")) == 8
    assert arm_features(_T, "feat_no_volume") == [f for f in _T.FEATURES if f != "vol_ratio_vs_entry"]
    assert arm_features(_T, "feat_path_only") == ["age_bars", "open_r", "mfe_r", "mae_r", "giveback_r", "dist_to_stop_r", "is_long"]
    cov_rows = [{"bars_since_peak": 1, "mom_8": 0.1}, {"bars_since_peak": 2, "mom_8": None}, {}, {"bars_since_peak": 0, "mom_8": 0.0}]
    assert feature_coverage(cov_rows, arm_features(_T, "feat_exh"), _T.FEATURES) == 0.5
    assert feature_coverage(cov_rows, arm_features(_T, "feat_no_volume"), _T.FEATURES) == 1.0
    seen = {}
    class _TT(_T):
        @staticmethod
        def train_model(train_rows):
            seen["f"], seen["n"] = list(_TT.FEATURES), len(train_rows)
            return "booster"
    assert train_with_features(_TT, [{}, {}], ["open_r"]) == "booster" and seen == {"f": ["open_r"], "n": 2}
    assert _TT.FEATURES == _T.FEATURES
    assert judge({"feat_exh": [0.03] * 400})["chosen"] == "feat_exh"
    print("exit_head_label_bakeoff self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
