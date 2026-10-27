#!/usr/bin/env python3
# wiring: manual-only — research harness for the LTR-TRIGGER-TUNE unit; run by a session or by the queue dispatcher via the unit's run.command, no schedule consumes it.
"""Tune the live-trade-review due-event thresholds (config/live_trade_review.yaml) out of sample.

    python3 scripts/research/live_review_trigger_tune.py --out <dir> [--population-only]

WHAT IT MEASURES
----------------
The value of LOOKING at an open package when a due event fires, minus the cost of the look.
There are no graded Claude calls yet, so the reviewer is modelled as the binding pricing step of
.claude/skills/live-trade-review/SKILL.md: at a firing bar it reads the leg's LTR-0 conditional
outcome table (scripts/research/live_review_outcomes.py semantics) and applies the best-EV option
when that option beats HOLD by ``--act-margin-r`` on a measured cell (n >= 20). A thin cell is
``no_recommendation`` (hold); the live reviewer would use judgement there, which this harness
cannot model (stated limitation, counted per firing).

* Corpus: the per-trade rows of each leg's committed Stage-0 evidence record, every ``net_r``
  already net of the full cost stack; the leg's committed candles (widest file).
* Replay: each trade is walked bar by bar (bar closes after the entry bar, through the recorded
  exit bar). The due events are evaluated at each bar close with the SAME rules as
  src/runtime/live_review_due.py::candidate_events / market_events (dedupe on (event, level),
  new_peak against the last REVIEWED peak, one review per bar). daily_floor (24 h) fires in every
  configuration: it is a policy floor and is not tuned here.
* Walk-forward: per leg, trades sorted by entry time and cut into K+1 chronological blocks. Fold k
  (k = 1..K) tests block k and builds the LTR-0 table from blocks 0..k-1 only (expanding window).
* Value of a review at bar j: the chosen action's realised net R minus HOLD's realised net R on the
  test trade, where actions stack (the stop is the tightest of every applied rule, never loosened).
* Cost of a review: ``c_R`` per review session, charged in R. Measured $ per session is an input
  (--usd-per-review); $ per R is NOT measured here, so the objective is reported at the registered
  c_R levels and every $/day figure is firings x $/review.
* Objective per fold = (sum of value_R - c_R x reviews) / trades in the fold   (R per package).

STATED BIASES
* Events are evaluated at bar close; live telemetry evaluates intra-bar (every exit-loop pass), so
  live fires a little earlier and a little more often than this replay.
* A tightened stop fills at the stop (a gap at the open): flatters every tighten.
* The original trail path is not recorded: a stop touched on the recorded exit bar counts as hit.
* The ATR used for tighten levels is the entry ATR proxy (1 R / atr_stop_mult), as LTR-0 uses.
* ``near_target`` needs the leg's tp_r from config/strategies.yaml; a tp_r >= 20 (sentinel) never
  fires.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from scripts.research.live_review_outcomes import (  # noqa: E402
    _paths, find_candles, load_candles, load_trades, trade_costs,
)

LEGS = ("ada_pullback_2h", "xrp_pullback_2h", "trend_donchian_eth_4h", "trend_donchian_xrp_4h",
        "trend_donchian_eth_prop", "trend_donchian_sol_prop")
ACTIONS = ("atr:1.0", "atr:1.5", "atr:2.0", "r:1.0", "r:2.0")
N_FLOOR = 20
TF_HOURS = {"15m": 0.25, "1h": 1.0, "2h": 2.0, "4h": 4.0, "1d": 24.0}

DEFAULTS = {
    "r_milestone.first_r": 1.0, "r_milestone.step_r": 1.0,
    "new_peak.step_r": 0.5,
    "giveback.min_peak_r": 1.0, "giveback.min_giveback_r": 0.5, "giveback.giveback_frac_of_peak": 0.30,
    "near_target.max_r_to_target": 0.5,
    "swing.atr_multiple": 2.0,
    "vol_regime.expand_ratio": 1.5, "vol_regime.contract_ratio": 0.67,
}
# Registered grids (one threshold varied at a time, the rest at default). math.inf = trigger off.
GRIDS = {
    "r_milestone.first_r": [0.5, 1.0, 1.5, 2.0, 3.0, math.inf],
    "r_milestone.step_r": [0.5, 1.0, 1.5, 2.0],
    "new_peak.step_r": [0.25, 0.5, 1.0, 1.5, 2.0, math.inf],
    "giveback.min_peak_r": [0.5, 1.0, 1.5, 2.0, 3.0, math.inf],
    "giveback.min_giveback_r": [0.25, 0.5, 0.75, 1.0, 1.5],
    "giveback.giveback_frac_of_peak": [0.2, 0.3, 0.4, 0.5],
    "near_target.max_r_to_target": [0.25, 0.5, 1.0, -1.0],      # -1 = off
    "swing.atr_multiple": [1.5, 2.0, 2.5, 3.0, math.inf],
    "vol_regime.expand_ratio": [1.25, 1.5, 2.0, 2.5, math.inf],
    "vol_regime.contract_ratio": [0.5, 0.67, 0.8, 0.0],          # 0 = off
}
C_R_LEVELS = (0.02, 0.10)
MARGIN_R = 0.01          # per-package improvement a fold must show
FOLDS_NEEDED = 3


# --------------------------------------------------------------------------- inputs

def leg_params(leg: str) -> Dict[str, float]:
    st = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    st = st.get("strategies", st)
    v = st.get(leg) or {}
    return {"atr_stop_mult": float(v.get("atr_stop_mult", 1.5)), "tp_r": float(v.get("tp_r", 50.0)),
            "timeframe": str(v.get("timeframe", "2h"))}


def wilder_atr(c: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = c["close"].shift(1)
    tr = pd.concat([c["high"] - c["low"], (c["high"] - pc).abs(), (c["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def build_paths(leg: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    trades, src = load_trades(leg)
    rec = json.loads((REPO / "comms" / "strategy_evidence" / f"{leg}.json").read_text())
    tf = rec.get("timeframe")
    cpath = find_candles(trades[0]["symbol"], tf)
    meta = {"leg": leg, "corpus": src, "candles": cpath and str(Path(cpath).relative_to(REPO)),
            "timeframe": tf, "corpus_trades": len(trades), "no_candles": 0, **leg_params(leg)}
    if not cpath:
        meta["no_candles"] = len(trades)
        return [], meta
    c = load_candles(cpath)
    atr = wilder_atr(c)
    out = []
    for t in sorted(trades, key=lambda r: str(r["entry_time"])):
        p = _paths(t, c)
        if p is None:
            meta["no_candles"] += 1
            continue
        et = p["entry_ts"]
        p["atr"] = [float(atr.loc[ts]) for ts in p["idx"]]
        p["atr_entry"] = float(atr.loc[et]) if et in atr.index else None
        pos = c.index.get_indexer(p["idx"])
        p["close_px"] = [float(x) for x in c["close"].iloc[pos]]
        p["close_px_prev"] = [float(x) for x in c["close"].iloc[pos - 1]]
        p["atr_prev"] = [float(x) for x in atr.iloc[pos - 1]]
        p["trade"] = t
        out.append(p)
    return out, meta


# --------------------------------------------------------------------------- the due rules

def _bucket(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def review_bars(p: Dict[str, Any], cfg: Dict[str, float], tp_r: float, tf_h: float) -> List[Tuple[int, List[str]]]:
    """[(bar index, [events])] -- live_review_due semantics evaluated at each bar close."""
    fired: set = set()
    last_peak: Optional[float] = None
    last_rev_h: Optional[float] = None
    peak = -math.inf
    out = []
    for j in range(len(p["idx"])):
        peak = max(peak, p["hi"][j])
        o = p["close"][j]
        gb = peak - o
        ev: List[Tuple[str, Any]] = []
        fr, st = cfg["r_milestone.first_r"], cfg["r_milestone.step_r"]
        if o >= fr:
            ev.append(("r_milestone", round(fr + _bucket(o - fr, st), 6)))
        ns = cfg["new_peak.step_r"]
        if last_peak is not None and peak >= last_peak + ns:
            ev.append(("new_peak", round(_bucket(peak, ns), 6)))
        if peak >= cfg["giveback.min_peak_r"]:
            need = max(cfg["giveback.min_giveback_r"], cfg["giveback.giveback_frac_of_peak"] * peak)
            if gb >= need:
                ev.append(("giveback", round(_bucket(peak, 0.5), 6)))
        if tp_r < 20:
            to_tp = tp_r - o
            if 0 <= to_tp <= cfg["near_target.max_r_to_target"]:
                ev.append(("near_target", 0))
        if p["atr_prev"][j] > 0 and abs(p["close_px"][j] - p["close_px_prev"][j]) >= cfg["swing.atr_multiple"] * p["atr_prev"][j]:
            ev.append(("swing", j))
        if p["atr_entry"]:
            ratio = p["atr"][j] / p["atr_entry"]
            if ratio >= cfg["vol_regime.expand_ratio"]:
                ev.append(("vol_regime", "expand"))
            elif ratio <= cfg["vol_regime.contract_ratio"]:
                ev.append(("vol_regime", "contract"))
        hours = (j + 1) * tf_h
        if last_rev_h is None and hours >= 24 or last_rev_h is not None and hours - last_rev_h >= 24:
            ev.append(("daily_floor", int(hours // 24)))
        new = [(e, lv) for e, lv in ev if (e, lv) not in fired]
        if not new:
            continue
        fired.update(new)
        last_peak = peak if last_peak is None else max(last_peak, peak)
        last_rev_h = hours
        out.append((j, sorted({e for e, _ in new})))
    return out


# --------------------------------------------------------------------------- pricing (LTR-0) and replay

def first_reach(p: Dict[str, Any], level: float) -> Optional[int]:
    ext = -math.inf
    for j, h in enumerate(p["hi"]):
        ext = max(ext, h)
        if ext >= level:
            return j
    return None


def stop_at(rule: Tuple[str, float, int], p: Dict[str, Any], j: int, atr_over_r: float) -> float:
    kind, val, j0 = rule
    if kind == "r":
        return val
    return max(p["hi"][: j]) - val * atr_over_r if j > 0 else -math.inf


def replay(p: Dict[str, Any], rules: List[Tuple[str, float, int]], atr_over_r: float) -> float:
    """Net R with every applied rule active from the bar after it was applied (tightest wins)."""
    t = p["trade"]
    if not rules:
        return float(t["net_r"])
    start = min(r[2] for r in rules) + 1
    for j in range(start, len(p["idx"])):
        live = [r for r in rules if r[2] < j]
        if not live:
            continue
        stop = max(stop_at(r, p, j, atr_over_r) for r in live)
        if p["lo"][j] <= stop:
            fill = p["open"][j] if p["open"][j] <= stop else stop
            fee, slip, fund, _ = trade_costs(t, p["r_dist"])
            span = (p["exit_ts"] - p["entry_ts"]).total_seconds()
            frac = (p["idx"][j] - p["entry_ts"]).total_seconds() / span if span > 0 else 1.0
            return fill - fee - slip - fund * min(1.0, max(0.0, frac))
    return float(t["net_r"])


def ltr0_choice(train: List[Dict[str, Any]], peak: float, open_r: float, atr_over_r: float,
                act_margin: float) -> Tuple[Optional[Tuple[str, float]], str, int]:
    """(action or None=hold, read_state, n) from the train table at live peak ``peak``."""
    rows = []
    for q in train:
        if float(q["trade"]["mfe_r"]) < peak:
            continue
        j0 = first_reach(q, peak)
        if j0 is not None:
            rows.append((q, j0))
    n = len(rows)
    if n < N_FLOOR:
        return None, "insufficient_n", n
    hold = statistics.fmean(float(q["trade"]["net_r"]) for q, _ in rows)
    best, best_ev = None, hold + act_margin
    for spec in ACTIONS:
        kind, val = spec.split(":")[0], float(spec.split(":")[1])
        lvl = val if kind == "r" else peak - val * atr_over_r
        if lvl > open_r - 1.0 * atr_over_r:      # noise floor: min_buffer_atr 1.0 below the mark
            continue
        ev = statistics.fmean(replay(q, [(kind, val, j0)], atr_over_r) for q, j0 in rows)
        if ev > best_ev:
            best, best_ev = (kind, val), ev
    return best, ("act" if best else "hold"), n


def run_config(legs: Dict[str, Dict[str, Any]], cfg: Dict[str, float], k_folds: int,
               act_margin: float) -> Dict[str, Any]:
    """Per (leg, fold): trades, reviews, per-event firings, value_R, open days, thin-cell count."""
    res: Dict[str, Any] = {}
    for leg, L in legs.items():
        paths, meta = L["paths"], L["meta"]
        atr_over_r = 1.0 / meta["atr_stop_mult"]
        tf_h = TF_HOURS.get(meta["timeframe"], 2.0)
        blocks = [paths[i * len(paths) // (k_folds + 1):(i + 1) * len(paths) // (k_folds + 1)]
                  for i in range(k_folds + 1)]
        for k in range(1, k_folds + 1):
            train = [q for b in blocks[:k] for q in b]
            cell = {"trades": 0, "reviews": 0, "events": {}, "value_r": 0.0, "open_days": 0.0,
                    "thin": 0, "acted": 0, "pos_value": 0, "neg_value": 0}
            cache: Dict[Tuple[float, float], Tuple] = {}
            for p in blocks[k]:
                cell["trades"] += 1
                cell["open_days"] += len(p["idx"]) * tf_h / 24.0
                rules: List[Tuple[str, float, int]] = []
                rb = review_bars(p, cfg, meta["tp_r"], tf_h)
                for j, evs in rb:
                    cell["reviews"] += 1
                    for e in evs:
                        cell["events"][e] = cell["events"].get(e, 0) + 1
                    key = (round(max(p["hi"][: j + 1]), 2), round(p["close"][j], 1))
                    if key not in cache:
                        cache[key] = ltr0_choice(train, key[0], key[1], atr_over_r, act_margin)
                    choice, state, _ = cache[key]
                    if state == "insufficient_n":
                        cell["thin"] += 1
                        continue
                    if choice:
                        rules.append((choice[0], choice[1], j))
                        cell["acted"] += 1
                v = replay(p, rules, atr_over_r) - float(p["trade"]["net_r"])
                cell["value_r"] += v
                cell["pos_value"] += v > 1e-9
                cell["neg_value"] += v < -1e-9
            res[f"{leg}|{k}"] = cell
    return res


def objective(res: Dict[str, Any], c_r: float, k_folds: int) -> List[float]:
    """Pooled across legs, per fold: (sum value_R - c_R x reviews) / trades."""
    out = []
    for k in range(1, k_folds + 1):
        cells = [v for key, v in res.items() if key.endswith(f"|{k}")]
        n = sum(c["trades"] for c in cells)
        out.append((sum(c["value_r"] for c in cells) - c_r * sum(c["reviews"] for c in cells)) / n if n else float("nan"))
    return out


def totals(res: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("trades", "reviews", "value_r", "open_days", "thin", "acted", "pos_value", "neg_value")
    t = {k: sum(c[k] for c in res.values()) for k in keys}
    ev: Dict[str, int] = {}
    for c in res.values():
        for e, n in c["events"].items():
            ev[e] = ev.get(e, 0) + n
    t["events"] = ev
    t["reviews_per_pkg_day"] = round(t["reviews"] / t["open_days"], 4) if t["open_days"] else None
    return t


def overlap(legs: Dict[str, Dict[str, Any]], cfg: Dict[str, float]) -> Dict[str, Any]:
    """Event co-firing at the default thresholds over every replayed trade (all blocks)."""
    names = ("r_milestone", "new_peak", "giveback", "near_target", "swing", "vol_regime", "daily_floor")
    solo = {e: 0 for e in names}
    pair: Dict[str, int] = {}
    for L in legs.values():
        tf_h = TF_HOURS.get(L["meta"]["timeframe"], 2.0)
        for p in L["paths"]:
            for _, evs in review_bars(p, cfg, L["meta"]["tp_r"], tf_h):
                if len(evs) == 1:
                    solo[evs[0]] += 1
                for a in evs:
                    for b in evs:
                        if a < b:
                            pair[f"{a}+{b}"] = pair.get(f"{a}+{b}", 0) + 1
    return {"fires_alone": solo, "co_fire_pairs": dict(sorted(pair.items(), key=lambda kv: -kv[1]))}


def decide(base: Dict[float, List[float]], cand: Dict[float, List[float]]) -> Dict[str, Any]:
    """The registered rule, at EVERY c_R level: >= FOLDS_NEEDED folds beat default by MARGIN_R."""
    per = {}
    ok = True
    for c in C_R_LEVELS:
        wins = sum(1 for b, x in zip(base[c], cand[c]) if x - b >= MARGIN_R)
        per[str(c)] = {"folds_beating_default_by_margin": wins, "default": [round(x, 4) for x in base[c]],
                       "candidate": [round(x, 4) for x in cand[c]]}
        ok = ok and wins >= FOLDS_NEEDED
    return {"clears": ok, "per_c_r": per}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--legs", default=",".join(LEGS))
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--act-margin-r", type=float, default=0.05)
    ap.add_argument("--usd-per-review", type=float, default=0.815)
    ap.add_argument("--population-only", action="store_true",
                    help="load and count the population only; compute no objective (pre-registration dry run)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    legs = {}
    for leg in a.legs.split(","):
        paths, meta = build_paths(leg)
        meta["replayed"] = len(paths)
        legs[leg] = {"paths": paths, "meta": meta}
    pop = {leg: L["meta"] for leg, L in legs.items()}
    assert all(m["replayed"] + m["no_candles"] == m["corpus_trades"] for m in pop.values()), "population leak"
    if a.population_only:
        (out / "population.json").write_text(json.dumps(pop, indent=2, default=str))
        print(json.dumps(pop, indent=2, default=str))
        return 0
    base_res = run_config(legs, DEFAULTS, a.folds, a.act_margin_r)
    base_obj = {c: objective(base_res, c, a.folds) for c in C_R_LEVELS}
    base_tot = totals(base_res)
    record: Dict[str, Any] = {
        "unit": "LTR-TRIGGER-TUNE", "harness": "scripts/research/live_review_trigger_tune.py",
        "population": pop, "folds": a.folds, "act_margin_r": a.act_margin_r, "n_floor": N_FLOOR,
        "c_r_levels": list(C_R_LEVELS), "margin_r": MARGIN_R, "folds_needed": FOLDS_NEEDED,
        "usd_per_review": a.usd_per_review,
        "default": {"totals": base_tot, "objective": {str(c): v for c, v in base_obj.items()},
                    "per_leg_fold": base_res},
        "overlap_at_default": overlap(legs, DEFAULTS), "grid": {},
    }
    for name, values in GRIDS.items():
        rows = []
        for v in values:
            cfg = dict(DEFAULTS)
            cfg[name] = v
            r = base_res if v == DEFAULTS[name] else run_config(legs, cfg, a.folds, a.act_margin_r)
            obj = {c: objective(r, c, a.folds) for c in C_R_LEVELS}
            tot = totals(r)
            rows.append({"value": "off" if v in (math.inf, -1.0) or (name.endswith("contract_ratio") and v == 0.0) else v,
                         "objective": {str(c): [round(x, 4) for x in o] for c, o in obj.items()},
                         "objective_sum": {str(c): round(sum(o), 4) for c, o in obj.items()},
                         "reviews": tot["reviews"], "reviews_per_pkg_day": tot["reviews_per_pkg_day"],
                         "value_r": round(tot["value_r"], 4), "acted": tot["acted"], "thin": tot["thin"],
                         "events": tot["events"],
                         "decision": decide(base_obj, obj) if v != DEFAULTS[name] else None})
        best = max(rows, key=lambda r: sum(r["objective_sum"].values()))
        record["grid"][name] = {"default": DEFAULTS[name], "rows": rows,
                                "best_by_pooled_objective": best["value"],
                                "proposed": best["value"] if best["decision"] and best["decision"]["clears"] else DEFAULTS[name]}
    (out / "result.json").write_text(json.dumps(record, indent=2, default=str))
    print(json.dumps({k: {"default": g["default"], "best": g["best_by_pooled_objective"], "proposed": g["proposed"]}
                      for k, g in record["grid"].items()}, indent=2, default=str))
    print(json.dumps(base_tot, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
