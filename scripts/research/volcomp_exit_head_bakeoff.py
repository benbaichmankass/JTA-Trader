#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-0bc8-02.yaml run.command ["python3","scripts/research/volcomp_exit_head_bakeoff.py",...]
#         one trainer dispatch (rows.jsonl + candles are trainer-resident), or a local session run with --rows/--candles-dir
"""VOLUME COMPOSITION -> EXIT HEAD: does adding the size/count surprise (ss, sn) to exit-head-donchian-1h-v1's recipe improve
its out-of-sample exits, beyond plain volume, in that head's own walk-forward replay on one cost stack?

WHY (operator 2026-11-12 07:46Z, planning page p3, "Also test it in the exit head now"; row VOLUME-COMPOSITION-RESEARCH)
-----------------------------------------------------------------------------------------------------------------------
RQ-20261111-f5c8-02 found that a SIZE-led volume surprise precedes a calmer next 4h bar (held-out partial rank IC -0.069).
A calmer next bar is exit-relevant (less room to run, less giveback). One passing univariate unit is not a feature: this
bake-off decides, using the exit head's OWN judge (RQ-20260927-002 / RQ-20261101-78fc-03 method).

WHAT IT DOES (the 78fc-03 driver, three arms instead of one; every scoring primitive imported UNMODIFIED)
--------------------------------------------------------------------------------------------------------
For each leg (trend_donchian BTCUSDT, trend_donchian_eth ETHUSDT, trend_donchian_sol SOLUSDT; 1h):
  * baseline trades from the live-faithful harness (``exit_head_replay._load_harness`` -> ``scripts/backtest_trend.py``,
    params from config/strategies.yaml, ``_apply_venue_cost_policy`` = net of the full fee + slippage + funding stack);
  * sequential trade-count folds (``exit_head_walkforward_multifold._fold_boundaries``), 7-day embargo;
  * per fold, THREE heads trained by ``train_exit_head.train_model`` (unchanged hyper-parameters) on the SAME pooled
    rows.jsonl rows with bar_t <= fold start - embargo, differing ONLY in feature columns:
        champion = train_exit_head.FEATURES (the shipped base recipe)
        vol      = champion + sv1h, sv4h               (plain volume surprise)
        comp     = champion + sv1h, ss1h, sn1h, sv4h, ss4h, sn4h   (the composition split; sv = ss + sn exactly)
  * every OOS trade re-resolved by ``exit_head_replay.replay_trade`` (the live predicate ``exit_head_shadow.would_exit_for``,
    shape below_half_r tau 0.10, action close) once per arm. The composition columns reach the live feature row through a
    wrapper around ``exit_head_shadow._feature_row`` that adds them for the scored bar (the ONLY new logic, with the join).
  * statistic: paired per-trade d = replayed_r(arm) - replayed_r(champion) on identical trades; pooled over legs and folds.
Composition features: Binance USD-M 1h klines (the trade count field; Bybit klines carry none, so Binance PROXIES the
venue), surprise vs the same hour-of-day mean over the previous 20 days (strictly before the bar), at the 1h grain and
over trailing 4-bar sums. A rows.jsonl symbol whose klines cannot be fetched gets NaN columns (LightGBM routes NaN); the
coverage share is reported.

Tier-1 research tooling: writes only --json. No config, model, registry or order path.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts", "ml"), os.path.join(_REPO_ROOT, "scripts", "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RULE_ID = "RULE-VOLCOMP-EXITHEAD-01"
LEGS = [("trend_donchian", "BTCUSDT"), ("trend_donchian_eth", "ETHUSDT"), ("trend_donchian_sol", "SOLUSDT")]
SHAPE = {"policy": "below_half_r", "tau": 0.10, "below_r": 0.5}     # the live artifact's shape (multifold.SHAPE)
ACTION = "close"
VOL_COLS = ["sv1h", "sv4h"]
COMP_COLS = ["sv1h", "ss1h", "sn1h", "sv4h", "ss4h", "sn4h"]
# registered bars (research/queue/RQ-20261112-0bc8-02.yaml decision_rule) — restated, never re-decided here
N_OOS_MIN = 300
PASS_DR = 0.01


def _warn(msg: str) -> None:
    print(f"volcomp_exit_head_bakeoff: {msg}", file=sys.stderr)


# ---- composition features -------------------------------------------------------------------------------------------
def composition_1h(k, season_days: int = 20):
    """1h kline frame (ts, volume, trades) -> frame[t_epoch, sv1h, sn1h, ss1h, sv4h, sn4h, ss4h]. Past-only at bar t."""
    import numpy as np
    import pandas as pd
    d = k[["ts", "volume", "trades"]].copy().sort_values("ts").reset_index(drop=True)
    d["slot"] = d["ts"].dt.hour
    vol, trd = d["volume"].where(d["volume"] > 0), d["trades"].where(d["trades"] > 0)
    v4 = d["volume"].rolling(4, min_periods=4).sum().where(lambda s: s > 0)
    n4 = d["trades"].rolling(4, min_periods=4).sum().where(lambda s: s > 0)
    for g, (lv, ln) in {"1h": (np.log(vol), np.log(trd)), "4h": (np.log(v4), np.log(n4))}.items():
        for name, series in (("sv", lv), ("sn", ln), ("ss", lv - ln)):
            norm = series.groupby(d["slot"]).transform(
                lambda s: s.shift(1).rolling(season_days, min_periods=season_days // 2).mean())
            d[f"{name}{g}"] = series - norm
    # unit-independent: Binance-vision frames arrive as datetime64[ms], so a // 10**9 on the raw int would be wrong
    d["t_epoch"] = ((d["ts"] - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).astype(int)
    return d[["t_epoch", *COMP_COLS]]


def build_lookup(symbols: List[str], start: str, end: str) -> Tuple[Dict[Tuple[str, int], Dict[str, float]], Dict[str, Any]]:
    from volume_composition_ic import fetch_symbol
    look: Dict[Tuple[str, int], Dict[str, float]] = {}
    cov: Dict[str, Any] = {}
    for s in symbols:
        try:
            k, c = fetch_symbol(s, start, end)
        except Exception as e:  # allow-silent: a symbol that cannot be fetched is recorded in coverage and gets NaN columns
            k, c = None, {"error": f"{type(e).__name__}: {e}"}
        if k is None or len(k) == 0:
            cov[s] = {"state": "unfetched", **(c or {})}
            continue
        f = composition_1h(k).dropna()
        for r in f.itertuples(index=False):
            look[(s, int(r.t_epoch))] = {c2: float(getattr(r, c2)) for c2 in COMP_COLS}
        cov[s] = {"state": "fetched", "bars": int(len(f)), "months_missing": c.get("months_missing")}
    return look, cov


def _epoch(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return int(x / 1000) if x > 1e11 else int(x)
    try:
        import pandas as pd
        return int(pd.Timestamp(v).tz_localize("UTC").timestamp()) if pd.Timestamp(v).tzinfo is None \
            else int(pd.Timestamp(v).timestamp())
    except Exception:  # allow-silent: an unparseable timestamp yields no composition join (NaN), counted in coverage
        return None


def augment_rows(rows: List[dict], look) -> float:
    """Add COMP_COLS to each rows.jsonl row from (symbol, bar_t); returns the joined share."""
    hit = 0
    for r in rows:
        v = look.get((str(r.get("symbol")), _epoch(r.get("bar_t")) or -1))
        if v:
            hit += 1
            r.update(v)
    return hit / len(rows) if rows else 0.0


# ---- statistics -----------------------------------------------------------------------------------------------------
def paired(d: List[float]) -> Dict[str, Any]:
    n = len(d)
    if n < 2:
        return {"n": n, "mean": (d[0] if n else None), "se": None, "ci95": None}
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "mean": round(m, 5), "se": round(se, 5), "ci95": [round(m - 1.96 * se, 5), round(m + 1.96 * se, 5)]}


def judge(comp_vs_champ: List[float], comp_vs_vol: List[float]) -> Dict[str, Any]:
    """RULE-VOLCOMP-EXITHEAD-01 (registered 2026-11-12, before any run; restated, not re-decided)."""
    a, b = paired(comp_vs_champ), paired(comp_vs_vol)
    n = a["n"]
    if n < N_OOS_MIN or a["ci95"] is None:
        return {"verdict": "indeterminate", "why": f"n_oos {n} < {N_OOS_MIN}", "comp_vs_champion": a, "comp_vs_vol": b}
    if a["mean"] >= PASS_DR and a["ci95"][0] > 0 and b["mean"] is not None and b["mean"] >= 0:
        v, why = "pass", (f"comp - champion {a['mean']:+.4f} R/trade >= +{PASS_DR}, CI LB {a['ci95'][0]:+.4f} > 0, "
                          f"comp - vol {b['mean']:+.4f} >= 0")
    elif a["ci95"][1] < PASS_DR:
        v, why = "fail", f"comp - champion CI UB {a['ci95'][1]:+.4f} < +{PASS_DR}: cannot reach the bar"
    else:
        v, why = "indeterminate", "between the pass bar and the fail floor"
    return {"verdict": v, "why": why, "comp_vs_champion": a, "comp_vs_vol": b}


# ---- driver ---------------------------------------------------------------------------------------------------------
def run_leg(strategy: str, symbol: str, rows: List[dict], look, a, harness, conf) -> Dict[str, Any]:
    import exit_head_walkforward_multifold as MF
    import train_exit_head as teh
    import src.runtime.exit_head_shadow as ehs
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
                    "why": backtest_data_source.refusal_message(res, harness="volcomp_exit_head_bakeoff.py", legacy_default=None)}
        path = res.path
    df = harness._load_candles(path)
    trades: List[Any] = []
    baseline = harness.run_backtest(
        df.copy(), donchian=int(cfg.get("donchian", 20)), atr_period=int(cfg.get("atr_period", 14)),
        atr_stop_mult=float(cfg.get("atr_stop_mult", 2.5)), trail_mult=float(cfg.get("trail_mult", 3.0)),
        timeout_bars=200, cooldown_bars=1, timeframe=a.timeframe, symbol=symbol,
        min_confidence=float(cfg.get("min_confidence", 0.0)), long_only=bool(cfg.get("long_only")), trades_out=trades)
    ordered = sorted(trades, key=lambda t: t.entry_time)
    epochs = [_epoch(t.entry_time) for t in ordered]
    fold_defs, block_n = MF._fold_boundaries(epochs, a.num_folds)
    emb = a.embargo_days * 86400
    base_feats = list(teh.FEATURES)
    arms = {"champion": base_feats, "vol": base_feats + VOL_COLS, "comp": base_feats + COMP_COLS}
    orig_row = ehs._feature_row

    def row_with_comp(candles_df, *args, **kw):
        row = orig_row(candles_df, *args, **kw)
        if row is not None:
            v = look.get((symbol, _epoch(candles_df["timestamp"].iloc[-1]) or -1))
            row = dict(row)
            row.update(v or {c: None for c in COMP_COLS})
        return row

    folds, recs_all = [], []
    try:
        ehs._feature_row = row_with_comp
        for fd in fold_defs:
            test = ordered[fd["test_start_idx"]:fd["test_end_idx"]]
            cut = fd["test_start_ts"] - emb
            train = [r for r in rows if float(r.get("bar_t", 0)) <= cut]
            f = {"fold_index": fd["index"], "n_test_trades": len(test), "train_rows_n": len(train),
                 "test_start": datetime.fromtimestamp(fd["test_start_ts"], tz=timezone.utc).isoformat()}
            if len(test) < MF.MIN_FOLD_TEST_N or len(train) < MF._MIN_FOLD_TRAIN_ROWS:
                f.update({"read_state": "unestablishable", "reason": f"test n {len(test)} / train rows {len(train)} under floor"})
                folds.append(f)
                continue
            per_arm: Dict[str, List[dict]] = {}
            for arm, feats in arms.items():
                teh.FEATURES = feats
                try:
                    booster = teh.train_model(train)
                finally:
                    teh.FEATURES = base_feats
                art = {"features": feats, "shape": SHAPE}

                def predict(vec, _b=booster):
                    # provenance: predict — P(class=1) of the binary holding_pays booster (as exit_head_eth_oos_control.py)
                    return float(_b.predict(vec)[0])
                per_arm[arm] = [replay_trade(df, t, art, predict, ACTION, lookback=a.lookback) for t in test]
            for i, t in enumerate(test):
                recs_all.append({"leg": strategy, "fold": fd["index"], "baseline_r": float(t.r_multiple),
                                 **{f"r_{arm}": float(per_arm[arm][i]["replayed_r"]) for arm in arms},
                                 **{f"fired_{arm}": bool(per_arm[arm][i]["exit_head_fired"]) for arm in arms}})
            f.update({"read_state": "measured", "n_fired": {arm: sum(1 for r in per_arm[arm] if r["exit_head_fired"]) for arm in arms}})
            folds.append(f)
            print(json.dumps({"leg": strategy, **{k: f[k] for k in ("fold_index", "n_test_trades", "n_fired")}}), flush=True)
    finally:
        ehs._feature_row = orig_row
    return {"leg": strategy, "symbol": symbol, "read_state": "measured" if recs_all else "unestablishable",
            "n_total_trades": len(ordered), "block_n": block_n, "folds": folds, "records": recs_all,
            "baseline_net_total_r": baseline.get("net_total_r") if isinstance(baseline, dict) else None,
            "data_start": str(df["timestamp"].iloc[0]) if len(df) else None,
            "data_end": str(df["timestamp"].iloc[-1]) if len(df) else None}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", default="datasets-out/exit_head/1h/donchian/rows.jsonl")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--legs", default=",".join(f"{s}:{y}" for s, y in LEGS))
    ap.add_argument("--num-folds", type=int, default=5)
    ap.add_argument("--embargo-days", type=float, default=7.0)
    ap.add_argument("--lookback", type=int, default=500)
    ap.add_argument("--kline-start", default="2019-09")
    ap.add_argument("--kline-end", default="2026-10")
    ap.add_argument("--candles-dir", default=None, help="local override: <dir>/<SYM>_<tf>.csv instead of the trainer resolver")
    ap.add_argument("--json", dest="json_out", required=False)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.json_out:
        ap.error("--json is required")
    try:
        sys.path.insert(0, _REPO_ROOT)
        from scripts.ml._heavy_queue import take_heavy_queue
        _lock = take_heavy_queue("volcomp-exit-head-bakeoff")   # noqa: F841 — held for the process lifetime
    except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
        _warn(f"heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked")
    import train_exit_head as teh
    import yaml
    from pathlib import Path
    from exit_head_replay import _apply_venue_cost_policy, _load_harness

    rows_path = Path(a.rows) if os.path.isabs(a.rows) else Path(_REPO_ROOT) / a.rows
    rows = teh.load_rows(rows_path)
    syms = sorted({str(r.get("symbol")) for r in rows if r.get("symbol")})
    look, cov = build_lookup(syms, a.kline_start, a.kline_end)
    joined = augment_rows(rows, look)
    conf = yaml.safe_load(open(os.path.join(_REPO_ROOT, "config/strategies.yaml"), encoding="utf-8"))
    legs = [tuple(x.split(":")) for x in a.legs.split(",") if x]
    out_legs, cost = [], {}
    for strategy, symbol in legs:
        harness = _load_harness()
        cost[symbol] = _apply_venue_cost_policy(harness, symbol)
        out_legs.append(run_leg(strategy, symbol, rows, look, a, harness, conf))
    recs = [r for lg in out_legs for r in lg.get("records", [])]
    j = judge([r["r_comp"] - r["r_champion"] for r in recs], [r["r_comp"] - r["r_vol"] for r in recs])
    context = {arm: paired([r[f"r_{arm}"] - r["baseline_r"] for r in recs]) for arm in ("champion", "vol", "comp")}
    per_leg = {lg["leg"]: paired([r["r_comp"] - r["r_champion"] for r in lg.get("records", [])]) for lg in out_legs}
    measured = bool(recs) and joined > 0
    row = {"schema_version": 1, "research_unit": "RQ-20261112-0bc8-02",
           "read_state": "measured" if measured else "producer_failed",
           "verdict": j["verdict"] if measured else "not_applicable", "note": j["why"], "n": j["comp_vs_champion"]["n"],
           "population": {"n": j["comp_vs_champion"]["n"], "description": (
               f"OOS harness trades of {[l for l, _ in legs]} ({a.timeframe}), {a.num_folds}-fold sequential walk-forward per leg, "
               f"3 heads retrained per fold on pooled rows.jsonl (n {len(rows)}) bar_t <= fold start - {a.embargo_days} d; paired "
               "per-trade replayed R, comp vs champion and comp vs vol")},
           "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-12", "registered_before_run": True},
           "measurement": {"judge": j, "per_leg_comp_vs_champion": per_leg, "arm_dr_vs_hold_context": context,
                           "rows_joined_share": round(joined, 4), "kline_coverage": cov, "cost_basis": cost,
                           "legs": [{k: v for k, v in lg.items() if k != "records"} for lg in out_legs],
                           "lookback": a.lookback},
           "caveats": ["Binance USD-M 1h klines PROXY the venue's trade count (Bybit klines carry none); composition columns are "
                       "NaN for rows.jsonl symbols Binance does not list (rows_joined_share).",
                       "Walk-forward spans overlap the window f5c8-02 read (2021-01..2026-09) when it selected the feature."],
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "produced_by": {"tool": "python3 scripts/research/volcomp_exit_head_bakeoff.py"}}
    out = json.dumps(row, indent=1, default=str)
    open(a.json_out, "w", encoding="utf-8").write(out + "\n")
    print("RESULT_JSON_BEGIN")
    print(json.dumps({k: row[k] for k in ("read_state", "verdict", "note", "n")}))
    print("RESULT_JSON_END")
    return 0 if measured else 2


def _self_test() -> int:
    import numpy as np
    import pandas as pd
    n = 24 * 40
    rng = np.random.default_rng(5)
    k = pd.DataFrame({"ts": pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC"),
                      "volume": np.exp(rng.normal(5, 0.5, n)), "trades": np.exp(rng.normal(3, 0.5, n))})
    f = composition_1h(k).dropna()
    km = k.copy()
    km["ts"] = km["ts"].astype("datetime64[ms, UTC]")
    assert composition_1h(km)["t_epoch"].iloc[0] == 1577836800, "epoch wrong for a ms-resolution frame"
    assert len(f) > 0 and np.allclose(f["sv1h"], f["sn1h"] + f["ss1h"]) and np.allclose(f["sv4h"], f["sn4h"] + f["ss4h"])
    k2 = k.copy()
    k2.loc[n - 1, "volume"] *= 50
    g, g2 = composition_1h(k), composition_1h(k2)
    assert g.iloc[:-1].fillna(0).equals(g2.iloc[:-1].fillna(0)), "a future bar leaked into an earlier row"
    look = {("X", int(f["t_epoch"].iloc[0])): {c: 1.0 for c in COMP_COLS}}
    rows = [{"symbol": "X", "bar_t": int(f["t_epoch"].iloc[0])}, {"symbol": "Y", "bar_t": 1}]
    assert augment_rows(rows, look) == 0.5 and rows[0]["ss1h"] == 1.0 and "ss1h" not in rows[1]
    j = judge([0.02] * 400, [0.01] * 400)
    assert j["verdict"] == "pass", j
    assert judge([-0.01] * 200 + [0.0] * 200, [0.0] * 400)["verdict"] == "fail"
    assert judge([0.02] * 100, [0.0] * 100)["verdict"] == "indeterminate"
    print("volcomp_exit_head_bakeoff self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
