#!/usr/bin/env python3
"""Conditional outcome table for an OPEN trade: HOLD vs each TIGHTEN, from the leg's own history.

    python3 scripts/research/live_review_outcomes.py --leg ada_pullback_2h --side short \\
        --open-r 3.44 --peak-r 3.51 --bars-held 17 --atr-stop-mult 1.5 \\
        --candles comms/research/RQ-20261014-d6e7-01/38663653665/candles/ADAUSDT_2h_378d.csv --json

LTR-0 of docs/plans/live-trade-review-DESIGN.md (sections 3 and 8): the live-trade review's
pricing tool. The ADA live exit review (ADA-LIVE-EXIT-REVIEW-1024, PR #19891) did this by hand:
"on trades that reached MFE >= 3.4 R, holding gave +3.19 R and tightening gave +2.96 R". This
makes it a command. A live review is a PRICING exercise (what did this leg's own history do from
this exact state?), and the tighten it prices is a risk PREFERENCE, so EV and tail are reported
separately and every tighten carries its expected-R cost.

METHOD
------
* Corpus: the per-trade rows of the leg's COMMITTED Stage-0 evidence record
  (``comms/strategy_evidence/<leg>.json`` -> ``source_run``), every ``net_r`` already net of the
  full cost stack (fee + slippage + funding).
* Comparable state: a trade is comparable when its path reached ``peak_r`` (the live peak R) and
  was still open there. The first closed bar whose running extreme >= ``peak_r`` is the REVIEW BAR.
  Optional ``--bars-slack``: the review bar must fall within ``bars_held * (1 + slack)``.
* HOLD: the trade's recorded ``net_r`` (the leg's own exit, untouched).
* TIGHTEN ``atr:k``: from the bar AFTER the review bar, a stop ratchets at ``k`` entry-ATR behind
  the running extreme (never loosens). ``r:x``: a fixed stop at +x R. Replayed on the committed
  candles, SL-first, a gap fills at the open. If the stop is not hit before the recorded exit, the
  recorded exit stands.
* COST STACK: a tightened exit keeps the trade's recorded fee and slippage legs, and its funding
  leg is rescaled by holding time. A record that carries no cost columns is priced from
  ``execution_costs.resolve_cost_policy()`` + ``DEFAULT_FEE_BPS_ROUNDTRIP`` and says so.
* A cell below ``--n-floor`` (default 20, the design's floor) is ``insufficient_n``: its numbers are
  ``null`` and ``n`` is still reported. ``null`` means "could not look", never 0.

STATED BIASES (the tool prints them; they are not hidden)
* A stop fills AT the stop price (a gap fills at the open), which flatters every tighten; the real
  cost of tightening is, if anything, larger. ``--stop-fill-slip-r`` charges extra R per tightened
  stop-out to bound it.
* The original trail path is not in the record, so on the recorded exit bar a tightened stop that
  was touched is taken as hit (SL-first).
* ``peak_r`` in live telemetry is a lower bound on true MFE; the table is conditioned on it as given.
* i.i.d. trades from one leg and one window; parameter selection on that window is not undone.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from src.runtime.execution_costs import (  # noqa: E402
    DEFAULT_FEE_BPS_ROUNDTRIP,
    resolve_cost_policy,
)

N_FLOOR = 20
AUTO_BOUND_R = 0.25      # design Q1 auto-apply bound (proposed)
SHADOW_BOUND_R = 0.5     # design shadow bound (proposed)
MFE_TOL_R = 0.05         # replayed-vs-recorded MFE agreement used by the fidelity check
DEFAULT_TIGHTEN = ("atr:1.0", "atr:1.5", "atr:2.0", "r:1.0", "r:2.0")
BIASES = (
    "stop fills at the stop price (a gap fills at the open): flatters every tighten, so the real "
    "cost of tightening is, if anything, larger",
    "the original trail path is not recorded: on the recorded exit bar a touched tightened stop "
    "is taken as hit (SL-first)",
    "live peak_r is a lower bound on true MFE",
    "one leg, one window, i.i.d. trades; parameter selection on the window is not undone",
)


# --------------------------------------------------------------------------- loading

def load_trades(leg: str, repo: Path = REPO) -> Tuple[List[Dict[str, Any]], str]:
    """The leg's committed Stage-0 per-trade rows. Raises FileNotFoundError when there are none."""
    rec_path = repo / "comms" / "strategy_evidence" / f"{leg}.json"
    rec = json.loads(rec_path.read_text())
    src = rec.get("source_run")
    if not src:
        raise FileNotFoundError(f"{rec_path}: no source_run")
    rows = [json.loads(ln) for ln in (repo / src).read_text().splitlines() if ln.strip()]
    return rows, src


def load_candles(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp").sort_index()


def find_candles(symbol: str, timeframe: str, repo: Path = REPO) -> Optional[str]:
    """The widest committed candle file for this symbol+timeframe, or None."""
    hits = glob.glob(str(repo / "comms" / "research" / "*" / "*" / "candles" / f"{symbol}_{timeframe}_*d.csv"))

    def days(p: str) -> int:
        try:
            return int(Path(p).stem.rsplit("_", 1)[1].rstrip("d"))
        except ValueError:
            return 0
    return max(hits, key=lambda p: (days(p), p)) if hits else None


def parse_tighten(spec: str) -> Tuple[str, float]:
    kind, _, val = spec.partition(":")
    if kind not in ("atr", "r") or not val:
        raise ValueError(f"bad --tighten {spec!r}: want atr:<k> or r:<x>")
    return kind, float(val)


# --------------------------------------------------------------------------- costs

def trade_costs(t: Dict[str, Any], r_dist: float) -> Tuple[float, float, float, str]:
    """(fee_r, slippage_r, funding_r, source) for the trade AS RECORDED."""
    if all(k in t for k in ("cost_fee_r", "cost_slippage_r", "cost_funding_r")):
        return float(t["cost_fee_r"]), float(t["cost_slippage_r"]), float(t["cost_funding_r"]), "recorded"
    slip_bps, fund_bps = resolve_cost_policy(t.get("symbol"))
    per_unit = float(t["entry"]) / r_dist / 1e4
    hours = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600.0
    return (DEFAULT_FEE_BPS_ROUNDTRIP * per_unit, slip_bps * per_unit,
            fund_bps * (hours / 8.0) * per_unit, "policy")


# --------------------------------------------------------------------------- replay

def _paths(t: Dict[str, Any], candles: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Per-bar favourable/adverse R from the bar after entry through the recorded exit bar."""
    et, xt = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
    if et.tzinfo is None:
        et, xt = et.tz_localize("UTC"), xt.tz_localize("UTC")
    if et < candles.index[0] or xt > candles.index[-1]:
        return None
    r_dist = abs(float(t["entry"]) - float(t["sl"]))
    if r_dist <= 0:
        return None
    sign = 1.0 if t["direction"] == "long" else -1.0
    w = candles.loc[et:xt].iloc[1:]          # entry price is the entry bar's close
    if w.empty:
        return None
    ent = float(t["entry"])
    f = lambda p: sign * (p - ent) / r_dist  # noqa: E731
    best = w["high"] if sign > 0 else w["low"]
    worst = w["low"] if sign > 0 else w["high"]
    return {
        "idx": list(w.index), "open": [f(float(x)) for x in w["open"]],
        "hi": [f(float(x)) for x in best], "lo": [f(float(x)) for x in worst],
        "close": [f(float(x)) for x in w["close"]], "r_dist": r_dist, "entry_ts": et, "exit_ts": xt,
    }


def review_bar(path: Dict[str, Any], peak_r: float) -> Optional[int]:
    """Index of the first bar whose running favourable extreme >= peak_r, else None."""
    ext = -math.inf
    for j, h in enumerate(path["hi"]):
        ext = max(ext, h)
        if ext >= peak_r:
            return j
    return None


def replay_tighten(path: Dict[str, Any], j0: int, kind: str, val: float,
                   atr_over_r: float) -> Optional[Tuple[float, pd.Timestamp]]:
    """Gross R and time of a tightened stop-out after review bar ``j0``; None = recorded exit stands."""
    ext = max(path["hi"][: j0 + 1])
    for j in range(j0 + 1, len(path["idx"])):
        stop = val if kind == "r" else ext - val * atr_over_r
        if path["lo"][j] <= stop:
            fill = min(stop, path["open"][j]) if path["open"][j] <= stop else stop   # gap -> open
            return fill, path["idx"][j]
        ext = max(ext, path["hi"][j])
    return None


def tightened_net_r(t: Dict[str, Any], path: Dict[str, Any], hit: Optional[Tuple[float, pd.Timestamp]],
                    stop_fill_slip_r: float) -> Tuple[float, str]:
    """Net R of the tightened path, full cost stack. ``hit`` None -> the recorded net_r stands."""
    if hit is None:
        return float(t["net_r"]), "recorded_exit"
    gross, ts = hit
    fee, slip, fund, src = trade_costs(t, path["r_dist"])
    span = (path["exit_ts"] - path["entry_ts"]).total_seconds()
    frac = ((ts - path["entry_ts"]).total_seconds() / span) if span > 0 else 1.0
    return gross - fee - slip - fund * min(1.0, max(0.0, frac)) - stop_fill_slip_r, f"tightened_stop[{src}]"


# --------------------------------------------------------------------------- statistics

def _pct(sorted_vals: List[float], q: float) -> float:
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def cell_stats(rs: List[float], peak_r: float, n_floor: int) -> Dict[str, Any]:
    n = len(rs)
    if n < n_floor:
        return {"n": n, "state": "insufficient_n", "n_floor": n_floor, "mean_r": None, "sd_r": None,
                "worst_r": None, "p05_r": None, "p_giveback_gt_half": None}
    s = sorted(rs)
    return {
        "n": n, "state": "measured", "n_floor": n_floor,
        "mean_r": round(statistics.fmean(rs), 4),
        "sd_r": round(statistics.stdev(rs), 4) if n > 1 else None,
        "worst_r": round(s[0], 4), "p05_r": round(_pct(s, 0.05), 4),
        "p_giveback_gt_half": round(sum(1 for r in rs if r < 0.5 * peak_r) / n, 4),
    }


def tighten_vs_hold(hold: List[float], tight: List[float], hold_cell: Dict[str, Any],
                    cell: Dict[str, Any], auto_bound: float, shadow_bound: float) -> Dict[str, Any]:
    if cell["state"] != "measured":
        return {"ev_cost_r": None, "ev_cost_se_r": None, "worst_case_gain_r": None,
                "within_auto_bound": None, "within_shadow_bound": None}
    diffs = [h - t for h, t in zip(hold, tight)]
    cost = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else None
    return {
        "ev_cost_r": round(cost, 4), "ev_cost_se_r": None if se is None else round(se, 4),
        "worst_case_gain_r": round(cell["worst_r"] - hold_cell["worst_r"], 4),
        "within_auto_bound": cost <= auto_bound, "within_shadow_bound": cost <= shadow_bound,
    }


# --------------------------------------------------------------------------- the table

def build_table(trades: List[Dict[str, Any]], candles: Optional[pd.DataFrame], *, side: Optional[str],
                open_r: float, peak_r: float, bars_held: Optional[int], atr_stop_mult: float,
                tighten: List[str], n_floor: int = N_FLOOR, bars_slack: Optional[float] = None,
                stop_fill_slip_r: float = 0.0, auto_bound: float = AUTO_BOUND_R,
                shadow_bound: float = SHADOW_BOUND_R, dist_stop_atr: Optional[float] = None,
                dist_target_atr: Optional[float] = None) -> Dict[str, Any]:
    atr_over_r = 1.0 / atr_stop_mult
    pop = {"corpus_trades": len(trades), "side_filter": side, "side_excluded": 0, "no_candles": 0,
           "never_reached_peak": 0, "beyond_bars_slack": 0, "comparable": 0,
           "mfe_replay_mismatch": 0}
    rows: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[int]]] = []
    for t in trades:
        if side and t["direction"] != side:
            pop["side_excluded"] += 1
            continue
        if float(t["mfe_r"]) < peak_r:
            pop["never_reached_peak"] += 1
            continue
        if candles is None:
            rows.append((t, None, None))
            continue
        path = _paths(t, candles)
        if path is None:
            pop["no_candles"] += 1
            continue
        j0 = review_bar(path, peak_r)
        if j0 is None:      # recorded MFE says it got there; the candles do not (fidelity miss)
            pop["mfe_replay_mismatch"] += 1
            continue
        if bars_held is not None and bars_slack is not None and (j0 + 1) > bars_held * (1 + bars_slack):
            pop["beyond_bars_slack"] += 1
            continue
        rows.append((t, path, j0))
    pop["comparable"] = len(rows)
    hold = [float(t["net_r"]) for t, _, _ in rows]
    hold_cell = cell_stats(hold, peak_r, n_floor)
    out: Dict[str, Any] = {
        "state": {"side": side, "open_r": open_r, "peak_r": peak_r, "bars_held": bars_held,
                  "atr_stop_mult": atr_stop_mult, "dist_to_stop_atr": dist_stop_atr,
                  "dist_to_target_atr": dist_target_atr},
        "population": pop, "n_floor": n_floor,
        "bounds_r": {"auto_apply": auto_bound, "shadow": shadow_bound},
        "options": [{"action": "hold", **hold_cell}], "biases": list(BIASES),
        "read_state": hold_cell["state"],
    }
    for spec in tighten:
        kind, val = parse_tighten(spec)
        lvl_r = val if kind == "r" else peak_r - val * atr_over_r
        base = {"action": "tighten", "spec": spec, "stop_at_r_now": round(lvl_r, 4)}
        if lvl_r >= open_r:
            out["options"].append({**base, "n": len(rows), "state": "invalid_level",
                                   "mean_r": None, "sd_r": None, "worst_r": None, "p05_r": None,
                                   "p_giveback_gt_half": None, "ev_cost_r": None,
                                   "ev_cost_se_r": None, "worst_case_gain_r": None,
                                   "within_auto_bound": None, "within_shadow_bound": None})
            continue
        if candles is None:
            out["options"].append({**base, **cell_stats([], peak_r, n_floor), "state": "could_not_look",
                                   "reason": "no_candles", "ev_cost_r": None, "ev_cost_se_r": None,
                                   "worst_case_gain_r": None, "within_auto_bound": None,
                                   "within_shadow_bound": None})
            continue
        tight = [tightened_net_r(t, p, replay_tighten(p, j0, kind, val, atr_over_r), stop_fill_slip_r)[0]
                 for t, p, j0 in rows]
        cell = cell_stats(tight, peak_r, n_floor)
        out["options"].append({**base, **cell, **tighten_vs_hold(hold, tight, hold_cell, cell,
                                                                  auto_bound, shadow_bound)})
    return out


def render_text(res: Dict[str, Any]) -> str:
    f = lambda v: "  —  " if v is None else f"{v:+.2f}"   # noqa: E731
    p, s = res["population"], res["state"]
    lines = [
        f"state: side={s['side']} open_r={s['open_r']} peak_r={s['peak_r']} bars_held={s['bars_held']}",
        f"population: corpus {p['corpus_trades']} -> comparable {p['comparable']} "
        f"(never_reached_peak {p['never_reached_peak']}, no_candles {p['no_candles']}, "
        f"side_excluded {p['side_excluded']}, mfe_replay_mismatch {p['mfe_replay_mismatch']})",
        f"{'action':<12}{'n':>4} {'state':<15}{'mean':>6}{'sd':>6}{'worst':>7}{'p05':>6}"
        f"{'gvbk>½':>7}{'EVcost':>7}{'worst+':>7}  <=0.25 <=0.5",
    ]
    for o in res["options"]:
        name = "hold" if o["action"] == "hold" else o["spec"]
        a, b = o.get("within_auto_bound"), o.get("within_shadow_bound")
        gb = "  —  " if o["p_giveback_gt_half"] is None else f"{o['p_giveback_gt_half']:.2f}"
        mark = lambda v: "  —  " if v is None else ("  yes" if v else "   no")   # noqa: E731
        lines.append(f"{name:<12}{o['n']:>4} {o['state']:<15}{f(o['mean_r']):>6}{f(o['sd_r']):>6}"
                     f"{f(o['worst_r']):>7}{f(o['p05_r']):>6}"
                     f"{gb:>7}"
                     f"{f(o.get('ev_cost_r')):>7}{f(o.get('worst_case_gain_r')):>7} {mark(a)} {mark(b)}")
    lines.append("biases: " + "; ".join(res["biases"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leg", required=True)
    ap.add_argument("--side", choices=("long", "short"))
    ap.add_argument("--open-r", type=float, required=True)
    ap.add_argument("--peak-r", type=float, required=True)
    ap.add_argument("--bars-held", type=int)
    ap.add_argument("--bars-slack", type=float, help="review bar must be <= bars_held*(1+slack)")
    ap.add_argument("--atr-stop-mult", type=float, required=True, help="1R = this x entry ATR (the leg's atr_stop_mult)")
    ap.add_argument("--dist-stop-atr", type=float)
    ap.add_argument("--dist-target-atr", type=float)
    ap.add_argument("--candles", help="candle CSV; default = widest committed file for the symbol/timeframe")
    ap.add_argument("--tighten", action="append", help="atr:<k> or r:<x>; repeatable")
    ap.add_argument("--n-floor", type=int, default=N_FLOOR)
    ap.add_argument("--stop-fill-slip-r", type=float, default=0.0)
    ap.add_argument("--auto-bound-r", type=float, default=AUTO_BOUND_R)
    ap.add_argument("--shadow-bound-r", type=float, default=SHADOW_BOUND_R)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    trades, src = load_trades(a.leg)
    cpath = a.candles
    if cpath is None and trades:
        sym = trades[0].get("symbol")
        tf = json.loads((REPO / "comms" / "strategy_evidence" / f"{a.leg}.json").read_text()).get("timeframe")
        cpath = find_candles(sym, tf) if sym and tf else None
    candles = load_candles(cpath) if cpath else None
    res = build_table(trades, candles, side=a.side, open_r=a.open_r, peak_r=a.peak_r,
                      bars_held=a.bars_held, atr_stop_mult=a.atr_stop_mult,
                      tighten=a.tighten or list(DEFAULT_TIGHTEN), n_floor=a.n_floor,
                      bars_slack=a.bars_slack, stop_fill_slip_r=a.stop_fill_slip_r,
                      auto_bound=a.auto_bound_r, shadow_bound=a.shadow_bound_r,
                      dist_stop_atr=a.dist_stop_atr, dist_target_atr=a.dist_target_atr)
    res["leg"], res["corpus"], res["candles"] = a.leg, src, cpath
    print(json.dumps(res, indent=2) if a.json else render_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
