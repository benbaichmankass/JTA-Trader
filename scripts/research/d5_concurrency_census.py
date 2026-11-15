#!/usr/bin/env python3
# wiring: research/queue/RQ-20261114-82fd-02.yaml (run.command, via research-script-run.yml); --self-test in CI-free use
"""D5 (position aggregation, "Mastiff") value-of-information census -- Tier-1 research tooling.

docs/plans/ML-ROADMAP-MECE-2026-11.md § 4.7: before any aggregator harness or model, count how often >= 2 packages are
open at once on one real-money (account, symbol). If concurrency is rare, the aggregator's ceiling is small and the slot
stays a rule (slices). This counts it on the Stage-0 trade streams of every leg on each declared pair, on two windows.

Trade streams (each leg ALONE, its own full bracket; the overlap of solo streams is what an aggregator would arbitrate):
  * rule legs   scripts/backtest_system.py::run_system_backtest(roster=[leg]) on Binance-Vision 5m candles, the full
                cost stack (src.research.run_costs) -- the same call same_symbol_head_to_head.py makes for its solo arms;
  * ml_entry    the served-policy trades of scripts/research/ml_entry_tp_revision.py (c692-01 walk-forward folds + the
                served artifact on 2025-10..2026-09), held to its fixed 2 ATR / 3 ATR bracket, filtered to the symbol.

Per (pair, window): per leg n, n_concurrent (its [entry, exit) overlaps another leg's open trade on the pair), the share,
net R of those trades, how many overlaps are OPPOSITE direction (netting), and the pair's hours with >= 2 legs open.
The verdict is the unit's registered materiality rule (decide()). Writes <out>/census.json + <out>/verdict.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

WINDOWS = {"prior_year": ("2024-10-01", "2025-10-01"), "record_year": ("2025-10-01", "2026-10-01")}
MIN_CONCURRENT, MIN_SHARE = 20, 0.15
FETCH_START = "2024-06-01"          # 5m warm-up ahead of the prior window


def overlaps(trades: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """trades: leg -> [{entry_ts, exit_ts, side (+1/-1), net_r}] (pandas Timestamps, UTC). Pure; unit-tested."""
    per_leg, events = {}, []
    for leg, ts in trades.items():
        for t in ts:
            events.append((t["entry_ts"], t["exit_ts"], leg, t["side"]))
    for leg, ts in trades.items():
        n_c = n_opp = 0
        r_c = 0.0
        for t in ts:
            others = [e for e in events if e[2] != leg and e[0] < t["exit_ts"] and t["entry_ts"] < e[1]]
            if others:
                n_c += 1
                r_c += float(t["net_r"])
                n_opp += int(any(e[3] != t["side"] for e in others))
        n = len(ts)
        per_leg[leg] = {"n": n, "n_concurrent": n_c, "share": (n_c / n) if n else None, "net_r_concurrent": r_c,
                        "n_opposite": n_opp, "net_r_all": float(sum(t["net_r"] for t in ts))}
    # hours with >= 2 legs open (sweep over entry/exit edges)
    edges = sorted([(e[0], 1) for e in events] + [(e[1], -1) for e in events], key=lambda x: (x[0], x[1]))
    depth, last, multi_h = 0, None, 0.0
    for t, d in edges:
        if last is not None and depth >= 2:
            multi_h += (t - last).total_seconds() / 3600.0
        depth += d
        last = t
    n_all = sum(v["n"] for v in per_leg.values())
    n_conc = sum(v["n_concurrent"] for v in per_leg.values())
    return {"legs": per_leg, "n_trades": n_all, "n_concurrent": n_conc,
            "share": (n_conc / n_all) if n_all else None, "hours_ge2_open": round(multi_h, 1)}


def decide(cells: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """cells: pair -> {window -> overlaps() result | {"could_not_look": reason}}. The registered materiality rule."""
    material, unmeasured = [], []
    for pair, w in cells.items():
        if any("could_not_look" in v for v in w.values()):
            unmeasured.append(pair)
            continue
        if all(v["n_concurrent"] >= MIN_CONCURRENT and (v["share"] or 0) >= MIN_SHARE for v in w.values()):
            material.append(pair)
    if material:
        return {"verdict": "pass", "reason": f"material concurrency (>= {MIN_CONCURRENT} concurrent trades and share >= "
                f"{MIN_SHARE:.0%} in BOTH windows) on {material}; build AGG-HARNESS + the A0..A4 rule arms"}
    if unmeasured:
        return {"verdict": "indeterminate", "reason": f"no measured pair is material; could not look at {unmeasured}"}
    return {"verdict": "fail", "reason": "concurrency below the materiality bar on every declared pair in at least one "
            "window; D5 stays a rule (slices)"}


def _rule_leg_trades(bs, leg: str, symbol: str, base5m, cost, risk_pct: float) -> List[Dict[str, Any]]:
    import pandas as pd
    s = bs.run_system_backtest(base5m, roster=[leg], start=None, end=None, initial_balance=10_000.0, risk_pct=risk_pct,
                               daily_loss_pct=3.0, signal_ttl_bars=1, overrides={}, refresh=False, clock_tf="15m",
                               attach_full=True, symbol=symbol, costs=cost, require_full_costs=True)
    out = []
    for t in s["closed_trades"]:
        sl = t.sl if t.sl is not None else t.entry
        risk = abs(float(t.qty) * (float(t.entry) - float(sl)))
        if risk <= 0:
            continue
        side = 1 if float(t.entry) > float(sl) else -1
        out.append({"entry_ts": pd.Timestamp(t.entry_ts, tz="UTC") if pd.Timestamp(t.entry_ts).tzinfo is None
                    else pd.Timestamp(t.entry_ts), "exit_ts": pd.Timestamp(t.exit_ts, tz="UTC")
                    if pd.Timestamp(t.exit_ts).tzinfo is None else pd.Timestamp(t.exit_ts),
                    "side": side, "net_r": float(t.pnl) / risk})
    return out


def _ml_entry_trades(cache: Path) -> Dict[str, List[Dict[str, Any]]]:
    import numpy as np
    import pandas as pd
    import ml_decision_entry as E
    import ml_entry_tp_revision as T
    art = json.loads(T.SERVED.read_text())
    syms = E.universe()
    E.fetch(cache, syms)
    tab = E.build_table(cache, syms)
    bars = T.load_bars(cache, syms)
    trades = pd.concat([T.entry_trades_wf(tab, float(art["tau"])), T.served_trades(tab, E.HOLDOUT_START, T.DEV_END, art)],
                       ignore_index=True)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for _k, t in trades.iterrows():
        df = bars[t.symbol]
        Ob, Hh, L, C = (x[0] for x in T.windows(df, np.array([t.i])))
        s = 1 if t.side == "long" else -1
        _px, j, _r, _ = T.walk_static(Ob, Hh, L, C, Ob[0], t.atr, s, T.BASE_TP, None)
        ts = df["ts"].to_numpy()
        out.setdefault(t.symbol, []).append({"entry_ts": pd.Timestamp(ts[int(t.i) + 1]).tz_localize("UTC")
                                             if pd.Timestamp(ts[int(t.i) + 1]).tzinfo is None else pd.Timestamp(ts[int(t.i) + 1]),
                                             "exit_ts": pd.Timestamp(ts[int(t.i) + j]).tz_localize("UTC") + pd.Timedelta(hours=1)
                                             if pd.Timestamp(ts[int(t.i) + j]).tzinfo is None
                                             else pd.Timestamp(ts[int(t.i) + j]) + pd.Timedelta(hours=1),
                                             "side": s, "net_r": float(t.net_r)})
    return out


def run(unit_path: Path, out: Path, cache: Path) -> int:
    import pandas as pd
    import yaml
    out.mkdir(parents=True, exist_ok=True)
    unit = yaml.safe_load(unit_path.read_text())
    pairs: List[Dict[str, Any]] = unit["census"]["pairs"]
    cells: Dict[str, Dict[str, Any]] = {}
    try:
        from same_symbol_head_to_head import _load_bs, fetch_5m
        from src.research import risk_basis
        from src.research.run_costs import resolve_run_costs
        bs = _load_bs()
        live = risk_basis.live_risk(risk_basis.DEFAULT_REFERENCE_ACCOUNT)
        risk_pct = float(live.percent) if live.ok and live.percent is not None else 1.0
        need_ml = any("ml_entry" in p["legs"] for p in pairs)
        ml = _ml_entry_trades(cache) if need_ml else {}
        by_symbol: Dict[str, Any] = {}
        for p in pairs:
            sym, legs = p["symbol"], list(p["legs"])
            key = f"{'+'.join(p['accounts'])}:{sym}"
            streams: Dict[str, List[Dict[str, Any]]] = {}
            missing = []
            for leg in legs:
                if leg == "ml_entry":
                    streams[leg] = ml.get(sym, [])
                    continue
                if leg not in bs.ROSTER:
                    missing.append(leg)
                    continue
                if sym not in by_symbol:
                    path = fetch_5m(sym, out / "candles", FETCH_START)
                    by_symbol[sym] = bs._load_candles(str(path)) if path else None
                if by_symbol[sym] is None:
                    missing.append(f"{leg} (no 5m candles)")
                    continue
                streams[leg] = _rule_leg_trades(bs, leg, sym, by_symbol[sym], resolve_run_costs(sym), risk_pct)
            cells[key] = {}
            for wn, (lo, hi) in WINDOWS.items():
                if missing:
                    cells[key][wn] = {"could_not_look": f"legs not measurable: {missing}"}
                    continue
                a, b = pd.Timestamp(lo, tz="UTC"), pd.Timestamp(hi, tz="UTC")
                cells[key][wn] = overlaps({lg: [t for t in ts if a <= t["entry_ts"] < b] for lg, ts in streams.items()})
            print(key, json.dumps({w: {k: v for k, v in c.items() if k != "legs"} for w, c in cells[key].items()}), flush=True)
        v = decide(cells)
        rec = {"unit": unit["id"], "cells": cells, "windows": WINDOWS, "min_concurrent": MIN_CONCURRENT,
               "min_share": MIN_SHARE, "risk_pct": risk_pct, **v}
        (out / "census.json").write_text(json.dumps(rec, indent=1, default=str))
        n = sum(c.get("n_trades", 0) for w in cells.values() for c in w.values())
        (out / "verdict.json").write_text(json.dumps({"verdict": v["verdict"], "read_state": "measured",
                                                      "population": f"{len(pairs)} declared real-money (account, symbol) pairs x 2 windows",
                                                      "n": n, "measurement": rec, "note": v["reason"]}, default=str))
        print("VERDICT", v, flush=True)
        return 0
    except Exception as exc:  # allow-silent: landed as read_state=producer_failed with the reason in verdict.json
        (out / "verdict.json").write_text(json.dumps({"verdict": "not_applicable", "read_state": "producer_failed",
                                                      "population": "declared pairs", "n": None,
                                                      "note": f"{type(exc).__name__}: {exc}"}))
        raise


def _self_test() -> None:
    import pandas as pd
    T0 = pd.Timestamp("2025-01-01", tz="UTC")
    h = lambda x: T0 + pd.Timedelta(hours=x)  # noqa: E731
    r = overlaps({"a": [{"entry_ts": h(0), "exit_ts": h(10), "side": 1, "net_r": 1.0},
                        {"entry_ts": h(20), "exit_ts": h(22), "side": 1, "net_r": -1.0}],
                  "b": [{"entry_ts": h(5), "exit_ts": h(15), "side": -1, "net_r": 0.5}]})
    assert r["legs"]["a"]["n_concurrent"] == 1 and r["legs"]["a"]["n_opposite"] == 1, r
    assert r["legs"]["b"]["n_concurrent"] == 1 and abs(r["legs"]["a"]["net_r_concurrent"] - 1.0) < 1e-12
    assert r["n_trades"] == 3 and r["n_concurrent"] == 2 and r["hours_ge2_open"] == 5.0, r
    # touching edges (exit == next entry) do not overlap
    r2 = overlaps({"a": [{"entry_ts": h(0), "exit_ts": h(5), "side": 1, "net_r": 0.0}],
                   "b": [{"entry_ts": h(5), "exit_ts": h(9), "side": 1, "net_r": 0.0}]})
    assert r2["n_concurrent"] == 0 and r2["hours_ge2_open"] == 0.0, r2
    big = {"n_concurrent": 25, "share": 0.2, "n_trades": 125}
    small = {"n_concurrent": 5, "share": 0.05, "n_trades": 100}
    assert decide({"p": {"prior_year": big, "record_year": big}})["verdict"] == "pass"
    assert decide({"p": {"prior_year": big, "record_year": small}})["verdict"] == "fail"
    assert decide({"p": {"prior_year": small, "record_year": small},
                   "q": {"prior_year": {"could_not_look": "x"}, "record_year": big}})["verdict"] == "indeterminate"
    print("self-test ok")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", default="RQ-20261114-82fd-02")
    ap.add_argument("--out", default="/tmp/d5_census_out")
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    p = Path(a.unit)
    if not p.exists():
        p = REPO / "research" / "queue" / f"{a.unit}.yaml"
    return run(p, Path(a.out), Path(a.cache))


if __name__ == "__main__":
    sys.exit(main())
