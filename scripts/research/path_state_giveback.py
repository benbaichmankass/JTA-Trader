#!/usr/bin/env python3
# wiring: manual-only - run by research queue unit RQ-20261022-b7e1-01 (research-script-run.yml) or by hand; Tier-1 research tooling, writes only under --out.
"""P1-Q11 rung 1e: PER-BAR path STATE -> "will this open profit be handed back from here?"

``path_metric_giveback.py`` (007) reads each trade ONCE, at bar k=6, and labels peak-to-exit giveback. An
exit lever acts at the bar where the trade is *already in profit and deteriorating*, so the question a lever
needs answered is per-state: at bar t of a trade that has reached ``--min-peak`` R, does a trailing-window
path measure predict ``exit_r <= open_r_t - X`` (the trade gives back >= X R **from here**, to the harness's
own exit), beyond what (open_r, peak_r, bars_since_peak, bars_in_trade) already say?

Features (bars <= t only; trailing window ``--window`` w):
  er_w         Kaufman efficiency ratio of the last w closes (signed-R space)
  chop_w       choppiness index over the last w bars, log10(sum TR / range)/log10(w)
  vol_ratio_t  realised bar-to-bar R-move std over the last w bars / the same over bars 1..w after entry
  atr_ratio_t  atr_r at t / atr_r at entry bar (volatility expansion vs entry)
  dist_atr_t   (peak_r - open_r) / atr_r : distance below the peak in ATRs
  dd_frac_t    (peak_r - open_r) / peak_r : share of the peak already given back
  bsp_t        bars since peak (also in the baseline -- listed so its OOS AUC is reported)

Grading is out-of-sample by CALENDAR fold of the trade's entry (``--folds``); thresholds and ridge/logistic
fits come from the other folds only. Population: harness trades, states with peak_r_t >= ``--min-peak`` and
not the exit bar. n is reported as STATES and as TRADES (states within a trade are autocorrelated: the
fold-majority bar carries the clustering, the trade count carries the power).

Screening table (NOT a lever grade): per feature, the first state where the (training-fold-median-split)
condition holds is a hypothetical full exit at that bar's close; reported = mean(open_r_flag - exit_r) over
flagged trades against the unconditional "exit at first peak>=min_peak state". Levers get graded properly in
their own queue units.

    python3 scripts/research/path_state_giveback.py --leg ada_pullback_2h --window 6 --min-peak 1.0 \\
        --x 1.0 --folds 6 --fold-majority 4 --days 2330 --start 2020-07-01 --end "2026-10-15 23:59" --out /tmp/o
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "scripts" / "research", REPO / "scripts" / "ops", REPO / "scripts", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import path_metric_giveback as pmg  # noqa: E402

BASE = ("open_r", "peak_r", "bsp_t", "bars_in")
FEATS = ("er_w", "chop_w", "vol_ratio_t", "atr_ratio_t", "dist_atr_t", "dd_frac_t")
# direction in which a feature is hypothesised to flag giveback risk (screening only; AUC sign is reported)
HYP = {"er_w": -1, "chop_w": +1, "vol_ratio_t": +1, "atr_ratio_t": +1, "dist_atr_t": +1, "dd_frac_t": +1}


def state_at(rows: list[dict[str, Any]], t: int, w: int, entry_sd: float | None = None) -> dict[str, Any] | None:
    """The feature dict of ONE trade at bar index ``t`` of its ordered rows, from ``rows[0..t]`` ONLY.

    The single home of the per-bar features: ``trade_states`` (the screen) and the harness path-state gates
    (``src/research/path_state_gate.py``, PATHSTATE-TRAIL-GATE) both call it, so a gate cannot drift from the
    measurement that motivated it. ``None`` where a feature is undefined (t < w-1, no ATR, a flat entry window).
    ``entry_sd`` (std of the first w bar moves) may be passed to skip recomputing it per bar."""
    if t < w - 1 or t >= len(rows):
        return None
    atr0 = rows[0].get("atr_r")

    def bar_moves(a: int, b: int) -> list[float]:
        return [float(rows[i]["c_r"]) - (float(rows[i - 1]["c_r"]) if i > 0 else 0.0) for i in range(a, b)]

    if entry_sd is None:
        entry_sd = _sd(bar_moves(0, w))
    r = rows[t]
    peak, openr = float(r["peak_r"]), float(r["open_r"])
    win = rows[t - w + 1:t + 1]
    prev_c = float(rows[t - w]["c_r"]) if t - w >= 0 else 0.0
    tr_sum, moves, hi, lo = 0.0, 0.0, -math.inf, math.inf
    for x in win:
        fav, adv, c = float(x["fav_r"]), float(x["adv_r"]), float(x["c_r"])
        tr_sum += max(fav, prev_c) - min(adv, prev_c)
        moves += abs(c - prev_c)
        hi, lo = max(hi, fav), min(lo, adv)
        prev_c = c
    rng = hi - lo
    chop = math.log10(tr_sum / rng) / math.log10(w) if rng > 0 and tr_sum > 0 and w > 1 else 0.0
    net = float(win[-1]["c_r"]) - (float(rows[t - w]["c_r"]) if t - w >= 0 else 0.0)
    er = abs(net) / moves if moves > 0 else 0.0
    sd_t = _sd(bar_moves(t - w + 1, t + 1))
    atr_t = r.get("atr_r")
    dist_atr = (peak - openr) / atr_t if atr_t else None
    atr_ratio = (atr_t / atr0) if (atr_t and atr0) else None
    if dist_atr is None or atr_ratio is None or entry_sd <= 0:
        return None
    return {"open_r": openr, "peak_r": peak, "bsp_t": float(r["bars_since_peak"]), "bars_in": float(t + 1),
            "er_w": er, "chop_w": chop, "vol_ratio_t": sd_t / entry_sd, "atr_ratio_t": atr_ratio,
            "dist_atr_t": dist_atr, "dd_frac_t": (peak - openr) / peak if peak > 0 else 0.0,
            "stop_room_r": float(r.get("dist_to_stop_r") or 0.0), "t": t}


def trade_states(rows: list[dict[str, Any]], w: int, min_peak: float) -> list[dict[str, Any]]:
    """One dict per qualifying (trade, bar) state of ONE trade's ordered rows. Features use rows <= t only."""
    exit_r = float(rows[-1]["open_r"])
    n = len(rows)
    out: list[dict[str, Any]] = []
    entry_sd = _sd([float(rows[i]["c_r"]) - (float(rows[i - 1]["c_r"]) if i > 0 else 0.0)
                    for i in range(0, min(w, n))])
    for t in range(w - 1, n - 1):               # never the exit bar (n-1)
        r = rows[t]
        if r.get("is_exit"):
            break
        if float(r["peak_r"]) < min_peak:
            continue
        st = state_at(rows, t, w, entry_sd)
        if st is None:
            continue
        st["exit_r"] = exit_r
        st["bars_to_exit"] = float(n - 1 - t)
        out.append(st)
    return out


def _sd(v: list[float]) -> float:
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def build_states(path_rows: list[dict[str, Any]], w: int, min_peak: float) -> tuple[list[dict[str, Any]], int, int]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in path_rows:
        by.setdefault(r["trade_key"], []).append(r)
    states, n_with = [], 0
    for key, rows in by.items():
        rows.sort(key=lambda r: int(r["bar_offset"]))
        st = trade_states(rows, w, min_peak)
        if st:
            n_with += 1
        ts = key.split("|")[2]
        for s in st:
            s["trade_key"], s["entry_ts"] = key, ts
        states += st
    return states, n_with, len(by)


def auc(score, y) -> float:
    import numpy as np
    y = np.asarray(y)
    pos, neg = score[y == 1], score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    allv = np.concatenate([pos, neg])
    # average ranks over ties
    uniq, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / cnt)[inv]
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def grade(states: list[dict[str, Any]], *, x: float, control: bool = False, folds: int, fold_majority: int, n_floor: int,
          min_ll_gain: float, min_auc: float) -> dict[str, Any]:
    import numpy as np
    n = len(states)
    n_tr = len({s["trade_key"] for s in states})
    out: dict[str, Any] = {"n_states": n, "n_trades": n_tr, "x": x, "folds": folds, "n_floor": n_floor,
                           "stop_room_control": control}
    if n_tr < n_floor:
        return {**out, "verdict": "indeterminate", "why": f"{n_tr} trades with a qualifying state < n_floor {n_floor}"}
    y = np.array([1.0 if s["exit_r"] <= s["open_r"] - x else 0.0 for s in states])
    fid = np.array(pmg.fold_of([s["entry_ts"] for s in states], folds))
    base = BASE + (("stop_room_r",) if control else ())   # control: room to the stop in force, a mechanical confound
    xb = np.array([[s[f] for f in base] for s in states])
    xf = np.array([[s[f] for f in base + FEATS] for s in states])
    qb, qf = np.full(n, np.nan), np.full(n, np.nan)
    per_fold = []
    for f in range(folds):
        te, tr = fid == f, fid != f
        if te.sum() < 5 or tr.sum() < 30 or len(set(y[tr].tolist())) < 2:
            per_fold.append({"fold": f, "n_states": int(te.sum()), "usable": False})
            continue
        a, b = pmg._std(xb[tr], xb[te])
        c, d = pmg._std(xf[tr], xf[te])
        qb[te] = pmg._logit(a, y[tr], b)
        qf[te] = pmg._logit(c, y[tr], d)
        per_fold.append({"fold": f, "n_states": int(te.sum()), "n_trades": len({states[i]["trade_key"] for i in np.where(te)[0]}),
                         "usable": True, "base_rate": round(float(y[te].mean()), 4),
                         "ll_base": round(pmg._ll(y[te], qb[te]), 4), "ll_full": round(pmg._ll(y[te], qf[te]), 4),
                         "auc_base": round(auc(qb[te], y[te]), 4), "auc_full": round(auc(qf[te], y[te]), 4)})
    ok = ~np.isnan(qb)
    ll_gain = pmg._ll(y[ok], qb[ok]) - pmg._ll(y[ok], qf[ok])
    usable = [p for p in per_fold if p["usable"]]
    wins = sum(1 for p in usable if p["ll_base"] - p["ll_full"] > 0)
    auc_b, auc_f = auc(qb[ok], y[ok]), auc(qf[ok], y[ok])
    # per-feature univariate pooled AUC + sign consistency by fold (raw feature, no fitting -> no leakage)
    uni = {}
    for f in base + FEATS:
        v = np.array([s[f] for s in states])
        per = [auc(v[fid == k], y[fid == k]) for k in range(folds) if (fid == k).sum() >= 5]
        per = [p for p in per if p == p]
        a_all = auc(v, y)
        uni[f] = {"auc": round(a_all, 4), "folds_same_side": sum(1 for p in per if (p > 0.5) == (a_all > 0.5)),
                  "folds": len(per), "per_fold_auc": [round(p, 3) for p in per]}
    passes = ll_gain >= min_ll_gain and wins >= fold_majority and (auc_f - auc_b) >= 0.0
    return {**out, "verdict": "pass" if passes else "fail", "base_rate": round(float(y.mean()), 4),
            "ll_gain": round(ll_gain, 4), "ll_fold_wins": wins, "usable_folds": len(usable),
            "auc_base": round(auc_b, 4), "auc_full": round(auc_f, 4), "min_ll_gain": min_ll_gain,
            "min_auc": min_auc, "univariate": uni, "per_fold": per_fold,
            "median_bars_to_exit_positive": round(float(np.median([s["bars_to_exit"] for s, yy in zip(states, y) if yy == 1])), 1)
            if y.sum() else None,
            "why": f"OOS log-loss gain {ll_gain:+.4f} ({wins}/{len(usable)} folds), AUC base {auc_b:.3f} -> full {auc_f:.3f}"}


def screening(states: list[dict[str, Any]], *, folds: int) -> dict[str, Any]:
    """Per feature: first state per trade satisfying the hypothesised-side median split (median from TRAINING
    folds), hypothetical full exit at that bar's close; mean (open_r_flag - exit_r) vs the unconditional first
    state. A screen for which levers are worth pre-registering, NOT a lever result."""
    import numpy as np
    fid = np.array(pmg.fold_of([s["entry_ts"] for s in states], folds))
    by_trade: dict[str, list[int]] = {}
    for i, s in enumerate(states):
        by_trade.setdefault(s["trade_key"], []).append(i)
    res = {}
    for f in FEATS:
        sign, deltas, uncond, flagged, total = HYP[f], [], [], 0, 0
        for k in range(folds):
            tr = fid != k
            if tr.sum() < 30:
                continue
            thr = float(np.median([states[i][f] for i in np.where(tr)[0]]))
            for key, idx in by_trade.items():
                if fid[idx[0]] != k:
                    continue
                total += 1
                first = states[idx[0]]
                uncond.append(first["open_r"] - first["exit_r"])
                hit = next((states[i] for i in idx if (states[i][f] - thr) * sign > 0), None)
                if hit is not None:
                    flagged += 1
                    deltas.append(hit["open_r"] - hit["exit_r"])
        res[f] = {"trades": total, "flagged": flagged,
                  "mean_flag_minus_exit_r": round(float(np.mean(deltas)), 4) if deltas else None,
                  "mean_firststate_minus_exit_r": round(float(np.mean(uncond)), 4) if uncond else None}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--window", type=int, required=True)
    ap.add_argument("--min-peak", type=float, required=True)
    ap.add_argument("--x", type=float, action="append", required=True, help="giveback-from-here size in R (repeatable)")
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--data-csv", default=None)
    ap.add_argument("--non-crypto-source", choices=("auto", "dukascopy"), default="auto")
    ap.add_argument("--folds", type=int, required=True)
    ap.add_argument("--fold-majority", type=int, required=True)
    ap.add_argument("--n-floor", type=int, default=100)
    ap.add_argument("--min-ll-gain", type=float, default=0.01)
    ap.add_argument("--min-auc", type=float, default=0.55)
    ap.add_argument("--stop-room-control", action="store_true",
                    help="add dist_to_stop_r (room to the stop in force) to the BASELINE")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import yaml
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    cfg = cfg.get("strategies", cfg)
    wd = Path(tempfile.mkdtemp(prefix="path_state_giveback_"))
    per_leg: dict[str, Any] = {}
    pooled: list[dict[str, Any]] = []
    for leg in a.leg:
        base = cfg.get(leg)
        if not isinstance(base, dict):
            print(f"ERROR: leg {leg!r} not in config/strategies.yaml", file=sys.stderr)
            return 2
        try:
            rows, meta = pmg.run_leg_paths(leg, base, days=a.days, start=a.start, end=a.end, wd=wd,
                                           data_csv=a.data_csv, non_crypto_source=a.non_crypto_source)
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- printed, written to failure.json, exit 1
            print(f"ERROR: {exc}", file=sys.stderr)
            (out / "failure.json").write_text(json.dumps({"stage": "harness", "leg": leg, "error": str(exc)}) + "\n")
            return 1
        states, n_with, total = build_states(rows, a.window, a.min_peak)
        for s in states:
            s["leg"] = leg
        pooled += states
        kw = dict(folds=a.folds, fold_majority=a.fold_majority, n_floor=a.n_floor, min_ll_gain=a.min_ll_gain,
                  min_auc=a.min_auc)
        per_leg[leg] = {"n_trades_total": total, "n_trades_reaching_peak": n_with,
                        "cost_policy": {f: meta["bt"].get(f) for f in ("fee_bps_roundtrip", "slippage_bps_roundtrip",
                                                                       "funding_bps_per_window")},
                        "by_x": {str(x): grade(states, x=x, control=a.stop_room_control, **kw) for x in a.x},
                        "screen": screening(states, folds=a.folds) if states else {}}
    kw = dict(folds=a.folds, fold_majority=a.fold_majority, n_floor=a.n_floor, min_ll_gain=a.min_ll_gain,
              min_auc=a.min_auc)
    pooled_by_x = {str(x): grade(pooled, x=x, control=a.stop_room_control, **kw) for x in a.x}
    verdicts = [g["verdict"] for g in pooled_by_x.values()]
    verdict = "pass" if "pass" in verdicts else ("indeterminate" if all(v == "indeterminate" for v in verdicts) else "fail")
    pop = (f"{len(pooled)} (trade,bar) states with peak_r>={a.min_peak} from {len({s['trade_key'] for s in pooled})} "
           f"harness trades across {a.leg}, window {a.start}..{a.end}, window w={a.window}, net of the harness's "
           "venue-aware cost stack; label exit_r <= open_r - X on the trade's own harness exit")
    rec = {"verdict": verdict, "read_state": "measured", "population": pop, "n": len(pooled),
           "measurement": {"pooled_by_x": pooled_by_x, "per_leg": per_leg, "window": a.window, "min_peak": a.min_peak},
           "note": f"{verdict.upper()}: " + "; ".join(f"X={k}: {g.get('why')}" for k, g in pooled_by_x.items())}
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "pooled": {k: (g["verdict"], g.get("why"), g.get("base_rate")) for k, g in pooled_by_x.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
