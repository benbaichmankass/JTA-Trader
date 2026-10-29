#!/usr/bin/env python3
# wiring: manual-only — the live-trade-review pricing tool; a reviewer session RUNS it per open trade (LTR-3 skill will call it), no schedule or workflow consumes it.
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

* ``--condition pullback`` (ADA-AM-CASE, 2026-10-29): the comparable state is "reached ``peak_r`` AND
  then retraced to ``open_r``" (the review bar is the first bar at/after the peak bar whose close is at or
  below ``open_r``), which is the state an operator is actually looking at when the question is "bank it
  now". ``--partial f`` banks fraction f at ``open_r`` on the review bar (the rest keeps the recorded
  exit; the banked part pays fee + slippage + funding to that bar). ``--move-tp X`` replaces the TP with a
  limit at +X R on the profit side of the market (X must be above ``open_r``); filled at X if a later bar
  reaches it before the recorded exit (SL-first on the recorded exit bar when that exit was a stop).
* ``--corpus`` overrides the Stage-0 evidence record's ``source_run`` (e.g. the full-history harness
  run behind a research unit), so a leg whose committed record is a 12-month run can be priced on its
  full history.

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
#: Committed FULL-HISTORY per-trade corpora (ADA-AM-CASE, 2026-10-29). The Stage-0 evidence record is a
#: 12-month OOS run (build_strategy_evidence.DEFAULT_DAYS = 365), so a leg's conditional cell (a side, a
#: peak, a retrace) is usually under the n floor. ``<leg>__trades.jsonl`` + ``<leg>__corpus.json`` here are
#: a longer run of the SAME harness and cost stack; ``--corpus auto`` prefers them.
LTR_CORPUS_DIR = "comms/strategy_evidence/ltr_corpus"
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

def load_trades(leg: str, repo: Path = REPO,
                corpus: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
    """The leg's committed Stage-0 per-trade rows (or ``corpus``, a repo-relative or absolute JSONL path).

    Raises FileNotFoundError when there are none."""
    if corpus == "auto":
        hit = resolve_corpus(leg, repo)
        if hit:
            return [json.loads(ln) for ln in (repo / hit).read_text().splitlines() if ln.strip()], hit
        corpus = None
    if corpus:
        cp = Path(corpus) if Path(corpus).is_absolute() else repo / corpus
        return [json.loads(ln) for ln in cp.read_text().splitlines() if ln.strip()], str(corpus)
    rec_path = repo / "comms" / "strategy_evidence" / f"{leg}.json"
    rec = json.loads(rec_path.read_text())
    src = rec.get("source_run")
    if not src:
        raise FileNotFoundError(f"{rec_path}: no source_run")
    rows = [json.loads(ln) for ln in (repo / src).read_text().splitlines() if ln.strip()]
    return rows, src


def resolve_corpus(leg: str, repo: Path = REPO) -> Optional[str]:
    """Repo-relative path of the leg's committed full-history corpus, or None when it has none.

    Needs both the trades file and its manifest, so an orphaned half is never picked up silently."""
    d = repo / LTR_CORPUS_DIR
    if (d / f"{leg}__trades.jsonl").is_file() and (d / f"{leg}__corpus.json").is_file():
        return f"{LTR_CORPUS_DIR}/{leg}__trades.jsonl"
    return None


def load_candles(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp").sort_index()


def _span_days(path: str) -> int:
    """Calendar days a candle CSV actually covers (first to last data row), 0 if unreadable."""
    try:
        with open(path) as fh:
            fh.readline()
            first = fh.readline().split(",", 1)[0]
            last = first
            for ln in fh:
                last = ln
            return (pd.Timestamp(last.split(",", 1)[0]) - pd.Timestamp(first)).days
    except (OSError, ValueError):
        return 0


def find_candles(symbol: str, timeframe: str, repo: Path = REPO, widest_span: bool = False) -> Optional[str]:
    """The widest committed candle file for this symbol+timeframe, or None.

    ``widest_span`` also reads the ``data/<SYM>_<tf>.csv`` files (full-history pulls the filename-days
    pattern does not match) and ranks every candidate by the days it actually covers."""
    hits = glob.glob(str(repo / "comms" / "research" / "*" / "*" / "candles" / f"{symbol}_{timeframe}_*d.csv"))
    if widest_span:
        hits += glob.glob(str(repo / "comms" / "research" / "*" / "*" / "data" / f"{symbol}_{timeframe}.csv"))
        return max(hits, key=lambda p: (_span_days(p), p)) if hits else None

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


def pullback_bar(path: Dict[str, Any], j_peak: int, open_r: float) -> Optional[int]:
    """First bar at/after the peak bar whose close is at or below ``open_r`` AND that is not the last
    (recorded exit) bar, so there is a later bar for an intervention to act on; else None."""
    last = len(path["idx"]) - 1
    for j in range(j_peak, last):
        if path["close"][j] <= open_r:
            return j
    return None


def _frac(path: Dict[str, Any], ts: pd.Timestamp) -> float:
    span = (path["exit_ts"] - path["entry_ts"]).total_seconds()
    return min(1.0, max(0.0, (ts - path["entry_ts"]).total_seconds() / span)) if span > 0 else 1.0


def partial_net_r(t: Dict[str, Any], path: Dict[str, Any], j0: int, frac_closed: float,
                  open_r: float) -> float:
    """Net R of banking ``frac_closed`` at ``open_r`` on review bar ``j0``; the rest keeps the recorded exit."""
    fee, slip, fund, _ = trade_costs(t, path["r_dist"])
    banked = open_r - fee - slip - fund * _frac(path, path["idx"][j0])
    return frac_closed * banked + (1.0 - frac_closed) * float(t["net_r"])


def move_tp_net_r(t: Dict[str, Any], path: Dict[str, Any], j0: int, tp_r: float) -> float:
    """Net R with the TP replaced by a limit at +``tp_r`` R from review bar ``j0``'s next bar on."""
    fee, slip, fund, _ = trade_costs(t, path["r_dist"])
    last = len(path["idx"]) - 1
    for j in range(j0 + 1, last + 1):
        if path["hi"][j] >= tp_r:
            if j == last and t.get("exit_reason") in ("stop", "trail_stop", "stop_loss"):
                break           # SL-first on the recorded exit bar
            return tp_r - fee - slip - fund * _frac(path, path["idx"][j])
    return float(t["net_r"])


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
                dist_target_atr: Optional[float] = None, condition: str = "peak",
                partial: Optional[List[float]] = None,
                move_tp: Optional[List[float]] = None) -> Dict[str, Any]:
    atr_over_r = 1.0 / atr_stop_mult
    pop = {"corpus_trades": len(trades), "side_filter": side, "side_excluded": 0, "no_candles": 0,
           "never_reached_peak": 0, "beyond_bars_slack": 0, "comparable": 0,
           "mfe_replay_mismatch": 0, "no_pullback_after_peak": 0}
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
        if condition == "pullback":
            j0 = pullback_bar(path, j0, open_r)
            if j0 is None:     # never retraced to open_r with a bar left to act on
                pop["no_pullback_after_peak"] += 1
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
                  "atr_stop_mult": atr_stop_mult, "condition": condition, "dist_to_stop_atr": dist_stop_atr,
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
    for kind, specs, fn in (("partial_close", partial or [], lambda t, p, j0, v: partial_net_r(t, p, j0, v, open_r)),
                            ("move_tp", move_tp or [], lambda t, p, j0, v: move_tp_net_r(t, p, j0, v))):
        for v in specs:
            base = {"action": kind, "spec": f"{kind}:{v}"}
            if kind == "move_tp" and v <= open_r:
                out["options"].append({**base, **cell_stats([], peak_r, n_floor), "n": len(rows),
                                       "state": "invalid_level", "ev_cost_r": None, "ev_cost_se_r": None,
                                       "worst_case_gain_r": None, "within_auto_bound": None,
                                       "within_shadow_bound": None})
                continue
            if candles is None:
                out["options"].append({**base, **cell_stats([], peak_r, n_floor), "state": "could_not_look",
                                       "reason": "no_candles", "ev_cost_r": None, "ev_cost_se_r": None,
                                       "worst_case_gain_r": None, "within_auto_bound": None,
                                       "within_shadow_bound": None})
                continue
            vals = [fn(t, p, j0, v) for t, p, j0 in rows]
            cell = cell_stats(vals, peak_r, n_floor)
            out["options"].append({**base, **cell, **tighten_vs_hold(hold, vals, hold_cell, cell,
                                                                      auto_bound, shadow_bound)})
    return out


def render_text(res: Dict[str, Any]) -> str:
    f = lambda v: "  —  " if v is None else f"{v:+.2f}"   # noqa: E731
    p, s = res["population"], res["state"]
    lines = [
        f"state: side={s['side']} open_r={s['open_r']} peak_r={s['peak_r']} bars_held={s['bars_held']}",
        f"population: corpus {p['corpus_trades']} -> comparable {p['comparable']} "
        f"(never_reached_peak {p['never_reached_peak']}, no_pullback {p.get('no_pullback_after_peak', 0)}, no_candles {p['no_candles']}, "
        f"side_excluded {p['side_excluded']}, mfe_replay_mismatch {p['mfe_replay_mismatch']})",
        f"{'action':<12}{'n':>4} {'state':<15}{'mean':>6}{'sd':>6}{'worst':>7}{'p05':>6}"
        f"{'gvbk>½':>7}{'EVcost':>7}{'worst+':>7}  <=0.25 <=0.5",
    ]
    for o in res["options"]:
        name = "hold" if o["action"] == "hold" else o["spec"].replace("partial_close", "partial").replace("move_tp", "mvtp")
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
    ap.add_argument("--corpus", help="per-trade JSONL (repo-relative or absolute), or 'auto' = the leg's committed full-history "
                    "corpus (comms/strategy_evidence/ltr_corpus/) else the evidence record's source_run; "
                    "default = the evidence record's source_run")
    ap.add_argument("--condition", choices=("peak", "pullback"), default="peak")
    ap.add_argument("--partial", type=float, action="append", help="fraction in (0,1) banked at --open-r; repeatable")
    ap.add_argument("--move-tp", type=float, action="append", help="new TP in R (> --open-r); repeatable")
    ap.add_argument("--n-floor", type=int, default=N_FLOOR)
    ap.add_argument("--stop-fill-slip-r", type=float, default=0.0)
    ap.add_argument("--auto-bound-r", type=float, default=AUTO_BOUND_R)
    ap.add_argument("--shadow-bound-r", type=float, default=SHADOW_BOUND_R)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    trades, src = load_trades(a.leg, corpus=a.corpus)
    cpath = a.candles
    if cpath is None and trades:
        sym = trades[0].get("symbol")
        tf = json.loads((REPO / "comms" / "strategy_evidence" / f"{a.leg}.json").read_text()).get("timeframe")
        cpath = find_candles(sym, tf, widest_span=a.corpus == "auto") if sym and tf else None
    candles = load_candles(cpath) if cpath else None
    res = build_table(trades, candles, side=a.side, open_r=a.open_r, peak_r=a.peak_r,
                      bars_held=a.bars_held, atr_stop_mult=a.atr_stop_mult,
                      tighten=a.tighten or list(DEFAULT_TIGHTEN), n_floor=a.n_floor,
                      bars_slack=a.bars_slack, stop_fill_slip_r=a.stop_fill_slip_r,
                      auto_bound=a.auto_bound_r, shadow_bound=a.shadow_bound_r,
                      dist_stop_atr=a.dist_stop_atr, dist_target_atr=a.dist_target_atr, condition=a.condition,
                      partial=a.partial, move_tp=a.move_tp)
    res["leg"], res["corpus"], res["candles"] = a.leg, src, cpath
    print(json.dumps(res, indent=2) if a.json else render_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
