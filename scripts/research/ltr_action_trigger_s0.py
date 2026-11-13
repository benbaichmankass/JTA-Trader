#!/usr/bin/env python3
# wiring: research/queue/RQ-20261113-ed2b-01 / -03 / -05 via .github/workflows/research-script-run.yml (one run per class); manual re-run by hand. No timer.
"""Does a live-review ACTION taken at the first trigger beat holding, and beat the same action at a random time? (offline)

    python3 scripts/research/ltr_action_trigger_s0.py --action partial_close --triggers r_milestone,near_target,stall \\
        --out comms/research/<unit>/<run>
    python3 scripts/research/ltr_action_trigger_s0.py --self-test

WHY (lane ORPHANS-LTR, 2026-11-13). Five live-review action classes had no graded result and no iteration unit
(scripts/research/iteration_orphans.py): the live record holds 0-1 calls for each (comms/research/ltr_class_grade/
VERDICT.md), and LTR-TRIGGER-CLOSE-S0 (comms/research/ltr_trigger_close_s0/) graded only `close`. This harness is the
close-trigger S0 design generalised to three more actions that the committed replay primitives can express:

  * ``partial_close``   bank ``--partial-frac`` of the position at the open of the bar after the trigger bar; the
                        rest keeps the recorded exit, brackets unchanged (the live class: skill § 3b).
  * ``tp_pull_in``      replace the declared TP (``params.tp_r`` of the corpus) with a limit that keeps
                        ``--tp-keep`` of the remaining distance from the next open; filled if a later bar reaches it
                        before the recorded exit (SL-first on the recorded exit bar when that exit was a stop).
                        A corpus with no TP or a fictional one (``tp_r`` >= ``--max-real-tp-r``, TP doctrine) is
                        excluded, named.
  * ``sl_to_structure`` move the stop to the swing extreme against the position over the last ``--pivot-bars``
                        closed bars, less ``--pivot-buffer-atr`` x ATR; taken only when that level is TIGHTER than
                        the initial stop and below the next open (a structure level behind the stop is a widen, which
                        needs a past-the-recorded-exit replay this tool does not have).

  Not expressible here, so not offered: ``widen_sl`` and ``tp_extend``. Both need the path AFTER the recorded exit
  (the widened stop survives the recorded stop-out; the extended TP outlives the recorded TP fill) replayed under the
  leg's own trail/stale exits. That is a separate build (see the blocked units RQ-20261113-ed2b-02 / -04).

ARMS (per trade, per pre-registered trigger T, first CLOSED bar on which T fires; thresholds from
config/live_trade_review.yaml ``due.events`` via ltr_trigger_close_s0.first_fires, evaluated on bar closes in R):
  HOLD      the recorded ``net_r`` of the committed corpus row (full cost stack: fee + slippage + funding).
  ACTION@T  the action at the open of the bar after T's bar, priced net of the same cost legs
            (live_review_outcomes.trade_costs; funding pro-rata to the held fraction).
  RANDOM_d  the SAME action at a bar drawn uniformly from the trade's eligible bars (seeded per trade and draw), on the
            same set of trades where T fired. ``--draws`` books = the matched random-time control.
  A trade where T did not fire in time (or the action is not expressible at that bar) keeps HOLD in that arm.

GRADE. RULE-AM-RISK-ADJUSTED-V1 (am_risk_adjusted.grade_risk_adjusted) over the pooled BOOK, baseline HOLD, one
candidate per trigger, controls = the ``--draws`` random books, ``min_control_beat_frac`` from the flag (the unit's
multiple-comparison correction). Plus L1: a V1 pass must still have r_cost <= max_r_cost_per_trade after dropping the
leg with the largest favourable contribution; otherwise the candidate reads INDETERMINATE (one leg carries it).
The books are per-trade R, so the grade is a SCREEN (``graduation_eligible: false`` until BOOK-SIM-REAL-SIZER).
Reported, never graded: per trigger mean dT (action - hold), mean edge vs random, bootstrap CIs, per leg.

INPUTS. Every ``<leg>__trades.jsonl`` + ``<leg>__corpus.json`` in ``--corpus-dir`` (default the committed
comms/strategy_evidence/ltr_corpus). Candles: the manifest's ``candles`` path when it exists, else
live_review_outcomes.find_candles(symbol, tf, widest_span=True), else venue_candles (cached outside the repo).
A trade with no candles is excluded with reason ``no_candles``, never priced as 0.

Tier-1 research tooling: reads committed corpora, writes only --out. No live path, no config write, no apply.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import yaml  # noqa: E402

import am_risk_adjusted as ra  # noqa: E402
import live_review_outcomes as lro  # noqa: E402
import ltr_trigger_close_s0 as s0  # noqa: E402

ACTIONS = ("partial_close", "tp_pull_in", "sl_to_structure")
SEED = 20261113
BOOT_DRAWS = 2000


# ── action pricing (pure; ``path`` is live_review_outcomes._paths output, R units, favourable = up) ─────────────
def _cost_at(t: Dict[str, Any], path: Dict[str, Any], j: int) -> float:
    fee, slip, fund, _ = lro.trade_costs(t, path["r_dist"])
    return fee + slip + fund * lro._frac(path, path["idx"][j])


def price_partial(t: Dict[str, Any], path: Dict[str, Any], j0: int, frac: float,
                  **_: Any) -> Optional[Tuple[float, Any]]:
    """Bank ``frac`` at bar j0+1's open; the rest keeps the recorded exit. Returns (net_r, exit_ts)."""
    j = j0 + 1
    banked = path["open"][j] - _cost_at(t, path, j)
    return frac * banked + (1.0 - frac) * float(t["net_r"]), path["exit_ts"]


def price_tp_pull_in(t: Dict[str, Any], path: Dict[str, Any], j0: int, keep: float, tp_r: Optional[float],
                     **_: Any) -> Optional[Tuple[float, Any]]:
    """TP replaced at bar j0+1 by a limit keeping ``keep`` of the distance from that bar's open to ``tp_r``.
    None when not expressible (no TP, or the open is already at/through the TP)."""
    if tp_r is None:
        return None
    o = path["open"][j0 + 1]
    if o >= tp_r:
        return None
    x = o + keep * (tp_r - o)
    last = len(path["idx"]) - 1
    for j in range(j0 + 1, last + 1):
        if path["hi"][j] >= x:
            if j == last and str(t.get("exit_reason")) in ("stop", "trail_stop", "stop_loss", "sl"):
                break                       # SL-first on the recorded exit bar
            return x - _cost_at(t, path, j), path["idx"][j]
    return float(t["net_r"]), path["exit_ts"]


def structure_level(path: Dict[str, Any], j0: int, pivot_bars: int, buffer_r: float) -> float:
    """Swing extreme against the position over the last ``pivot_bars`` closed bars up to j0, less the buffer (R)."""
    lo = min(path["lo"][max(0, j0 - pivot_bars + 1): j0 + 1])
    return lo - buffer_r


def price_sl_to_structure(t: Dict[str, Any], path: Dict[str, Any], j0: int, pivot_bars: int, buffer_atr: float,
                          atr_r: List[Optional[float]], **_: Any) -> Optional[Tuple[float, Any]]:
    """Stop moved to structure from bar j0+1. None when not a tighten (level <= initial stop -1R) or not below the
    next open, or ATR unread."""
    a = atr_r[j0]
    if a is None:
        return None
    level = structure_level(path, j0, pivot_bars, buffer_atr * a)
    if level <= -1.0 or level >= path["open"][j0 + 1]:
        return None
    hit = lro.replay_tighten(path, j0, "r", level, 0.0)
    net, _src = lro.tightened_net_r(t, path, hit, 0.0)
    return net, (hit[1] if hit else path["exit_ts"])


PRICERS: Dict[str, Callable[..., Optional[Tuple[float, Any]]]] = {
    "partial_close": price_partial, "tp_pull_in": price_tp_pull_in, "sl_to_structure": price_sl_to_structure}


# ── corpus + candles ────────────────────────────────────────────────────────────────────────────────────────
def load_corpora(corpus_dir: Path, legs: Optional[List[str]]) -> List[Tuple[str, dict, List[dict]]]:
    out = []
    for mf in sorted(glob.glob(str(corpus_dir / "*__corpus.json"))):
        leg = Path(mf).name[: -len("__corpus.json")]
        tf = corpus_dir / f"{leg}__trades.jsonl"
        if legs and leg not in legs or not tf.is_file():
            continue
        man = json.loads(Path(mf).read_text())
        rows = [json.loads(ln) for ln in tf.read_text().splitlines() if ln.strip()]
        out.append((leg, man, rows))
    return out


def resolve_candles(man: dict, symbol: str, tf: str, rows: List[dict], cache: Dict[Tuple[str, str], Any]) -> Any:
    key = (symbol, tf)
    if key in cache:
        return cache[key]
    path = None
    c = man.get("candles")
    if isinstance(c, str) and (REPO / c).is_file() and symbol in Path(c).name:
        path = str(REPO / c)
    if path is None:
        path = lro.find_candles(symbol, tf, REPO, widest_span=True)
    if path is None:
        path = lro.venue_candles(symbol, tf, rows)
    df = lro.load_candles(path) if path else None
    cache[key] = (df, path)
    return cache[key]


def atr_r_series(df: Any, path: Dict[str, Any], n: int = 14) -> List[Optional[float]]:
    """Wilder ATR (price units, on the whole frame) at each path bar, divided by the trade's R distance."""
    if "_atr" not in df.attrs:
        bars = [{"high": float(h), "low": float(lw), "close": float(c)}
                for h, lw, c in zip(df["high"], df["low"], df["close"])]
        df.attrs["_atr"] = dict(zip(df.index, s0.wilder_atr(bars, n)))
    m = df.attrs["_atr"]
    return [(m.get(ts) / path["r_dist"]) if m.get(ts) else None for ts in path["idx"]]


# ── core ────────────────────────────────────────────────────────────────────────────────────────────────────
def build_trades(corpora: List[Tuple[str, dict, List[dict]]], *, action: str, triggers: List[str], cfg: dict,
                 opts: Dict[str, Any], candle_loader: Optional[Callable[..., Any]] = None) -> Tuple[List[dict], Counter]:
    """Per-trade records: hold, action value at each trigger's first fire, and a lazy random-bar pricer."""
    excluded: Counter = Counter()
    cache: Dict[Tuple[str, str], Any] = {}
    recs: List[dict] = []
    for leg, man, rows in corpora:
        params = man.get("params") or {}
        tf = str(params.get("timeframe") or "")
        tp_r = params.get("tp_r")
        tp_r = float(tp_r) if tp_r is not None else None
        if action == "tp_pull_in" and (tp_r is None or tp_r >= opts["max_real_tp_r"]):
            excluded[f"no_real_tp:{leg}"] += len(rows)
            continue
        for i, t in enumerate(rows):
            sym = t.get("symbol")
            df, _p = (candle_loader or resolve_candles)(man, sym, tf, rows, cache)
            if df is None:
                excluded["no_candles"] += 1
                continue
            try:
                path = lro._paths(t, df)
            except (KeyError, ValueError, TypeError):
                path = None
            if path is None or len(path["idx"]) < 2:
                excluded["no_path_or_single_bar"] += 1
                continue
            last = len(path["idx"]) - 1
            atr_r = atr_r_series(df, path)
            bars = [{"close": c} for c in path["close"][:last]]
            fires = s0.first_fires(bars, atr_r[:last], side=1.0, entry=0.0, r_dist=1.0,
                                   tp=tp_r, tf=tf, cfg=cfg)
            kw = dict(frac=opts["partial_frac"], keep=opts["tp_keep"], tp_r=tp_r, pivot_bars=opts["pivot_bars"],
                      buffer_atr=opts["pivot_buffer_atr"], atr_r=atr_r)
            pricer = PRICERS[action]
            memo: Dict[int, Optional[Tuple[float, Any]]] = {}

            def at(j: int, _t=t, _path=path, _kw=kw, _memo=memo, _pr=pricer) -> Optional[Tuple[float, Any]]:
                if j not in _memo:
                    _memo[j] = _pr(_t, _path, j, **_kw)
                return _memo[j]
            act = {}
            for T in triggers:
                if T in fires:
                    v = at(fires[T])
                    if v is not None:
                        act[T] = v
            recs.append({"leg": leg, "key": f"{leg}#{i}", "entry_time": str(t["entry_time"]),
                         "exit_time": str(t["exit_time"]), "net_r": float(t["net_r"]), "mfe_r": t.get("mfe_r"),
                         "n_bars": last, "act": act, "at": at})
    return recs, excluded


def _trade(rec: dict, v: Optional[Tuple[float, Any]]) -> Dict[str, Any]:
    if v is None:
        return {"entry_time": rec["entry_time"], "exit_time": rec["exit_time"], "net_r": rec["net_r"],
                "mfe_r": rec["mfe_r"], "leg": rec["leg"]}
    return {"entry_time": rec["entry_time"], "exit_time": str(v[1]), "net_r": float(v[0]), "mfe_r": rec["mfe_r"],
            "leg": rec["leg"]}


def _boot_ci(xs: List[float], alpha: float, rng: random.Random) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    import numpy as np
    a = np.asarray(xs)
    g = np.random.default_rng(rng.randrange(2 ** 32))
    ms = np.sort(a[g.integers(0, len(a), size=(BOOT_DRAWS, len(a)))].mean(axis=1))
    return [round(float(ms[int(alpha / 2 * BOOT_DRAWS)]), 4),
            round(float(ms[min(BOOT_DRAWS - 1, int((1 - alpha / 2) * BOOT_DRAWS))]), 4)]


def grade(recs: List[dict], *, action: str, triggers: List[str], draws: int, beat_frac: float,
          n_cmp: int) -> Dict[str, Any]:
    hold = [_trade(r, None) for r in recs]
    books: Dict[str, List[dict]] = {"hold": hold}
    controls: Dict[str, List[str]] = {}
    report: Dict[str, Any] = {}
    rng = random.Random(SEED)
    for T in triggers:
        cl = f"{action}@{T}"
        books[cl] = [_trade(r, r["act"].get(T)) for r in recs]
        fired = [r for r in recs if T in r["act"]]
        ctl = []
        rand_mean: Dict[str, float] = defaultdict(float)
        for d in range(draws):
            lab = f"{cl}#rand{d}"
            bk = []
            for r in recs:
                if T in r["act"]:
                    j = random.Random(f"{SEED}:{r['key']}:{d}").randrange(r["n_bars"])
                    v = r["at"](j)
                    bk.append(_trade(r, v))
                    rand_mean[r["key"]] += (v[0] if v else r["net_r"]) / draws
                else:
                    bk.append(_trade(r, None))
            books[lab] = bk
            ctl.append(lab)
        controls[cl] = ctl
        dT = [r["act"][T][0] - r["net_r"] for r in fired]
        edge = [r["act"][T][0] - rand_mean[r["key"]] for r in fired]
        by_leg: Dict[str, List[float]] = defaultdict(list)
        for r, x in zip(fired, dT):
            by_leg[r["leg"]].append(x)
        report[cl] = {"n_fired": len(fired),
                      "mean_dT_vs_hold": round(sum(dT) / len(dT), 4) if dT else None,
                      "mean_edge_vs_random": round(sum(edge) / len(edge), 4) if edge else None,
                      "ci95_dT": _boot_ci(dT, 0.05, rng), "ci95_edge": _boot_ci(edge, 0.05, rng),
                      "ci_bonf_edge": _boot_ci(edge, 0.05 / n_cmp, rng),
                      "by_leg": {k: {"n": len(v), "sum_dT": round(sum(v), 3)} for k, v in sorted(by_leg.items())}}
    g = ra.grade_risk_adjusted(books, baseline="hold", candidates=[f"{action}@{T}" for T in triggers],
                               controls=controls, params={"min_control_beat_frac": beat_frac})
    # L1: drop the leg with the largest favourable contribution; a pass must survive it.
    p = g["rule"]
    for cl, row in g["candidates"].items():
        contrib: Dict[str, float] = defaultdict(float)
        for a, c in zip(books["hold"], books[cl]):
            contrib[a["leg"]] += c["net_r"] - a["net_r"]
        best_leg = max(contrib, key=lambda k: contrib[k]) if contrib else None
        a_rest = [a for a in books["hold"] if a["leg"] != best_leg]
        c_rest = [c for c in books[cl] if c["leg"] != best_leg]
        r_cost_rest = (round((sum(a["net_r"] for a in a_rest) - sum(c["net_r"] for c in c_rest)) / len(a_rest), 6)
                       if a_rest else None)
        # not readable with a single leg (None): it then never demotes; with >= 2 legs it must hold
        l1 = (None if len(contrib) < 2 else
              (r_cost_rest is not None and r_cost_rest <= float(p["max_r_cost_per_trade"])))
        row["L1_drop_best_leg"] = {"best_leg": best_leg, "r_cost_per_trade_without": r_cost_rest, "holds": l1}
        row["controls"] = {"n": len(row.get("controls") or {}),
                           "beaten": sum(1 for v in (row.get("controls") or {}).values() if v["beats"])}
        if row["verdict"] == "pass" and l1 is False:
            row["verdict"], row["label"] = "indeterminate", "one_leg_carries_it"
        row["s0_report"] = report[cl]
    order = {"pass": 0, "indeterminate": 1, "fail": 2}
    vs = [r["verdict"] for r in g["candidates"].values()]
    g["verdict"] = min(vs, key=lambda v: order[v]) if vs else "indeterminate"
    g["passing"] = [c for c, r in g["candidates"].items() if r["verdict"] == "pass"]
    return g


def run(args: argparse.Namespace, candle_loader: Optional[Callable[..., Any]] = None,
        corpora: Optional[List[Tuple[str, dict, List[dict]]]] = None) -> Dict[str, Any]:
    cfg = yaml.safe_load((REPO / "config/live_trade_review.yaml").read_text())["due"]
    triggers = [x for x in args.triggers.split(",") if x]
    bad = [x for x in triggers if x not in s0.TRIGGERS]
    if bad:
        raise SystemExit(f"unknown trigger(s) {bad}; known: {s0.TRIGGERS}")
    corpora = corpora if corpora is not None else load_corpora(Path(args.corpus_dir), args.legs.split(",") if args.legs else None)
    opts = {"partial_frac": args.partial_frac, "tp_keep": args.tp_keep, "pivot_bars": args.pivot_bars,
            "pivot_buffer_atr": args.pivot_buffer_atr, "max_real_tp_r": args.max_real_tp_r}
    recs, excluded = build_trades(corpora, action=args.action, triggers=triggers, cfg=cfg, opts=opts,
                                  candle_loader=candle_loader)
    pop = (f"{len(recs)} trades priced of {sum(len(r) for _, _, r in corpora)} in {len(corpora)} committed "
           f"Stage-0 corpora ({', '.join(l for l, _, _ in corpora)}); action {args.action}; triggers {triggers}")
    base = {"schema": "ltr_action_trigger_s0/v1", "action": args.action, "triggers": triggers, "options": opts,
            "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "population": pop,
            "excluded": dict(excluded), "by_leg_priced": dict(Counter(r["leg"] for r in recs)),
            "cost_stack": "corpus rows' recorded fee + slippage + funding legs (live_review_outcomes.trade_costs)",
            "provenance": "MEASURED"}
    if not recs:
        return {**base, "verdict": "indeterminate", "read_state": "no_data", "n": None,
                "note": "no trade could be priced (see excluded); nothing measured"}
    g = grade(recs, action=args.action, triggers=triggers, draws=args.draws, beat_frac=args.min_control_beat_frac,
              n_cmp=args.n_comparisons)
    cand = {c: {k: r[k] for k in ("verdict", "label", "r_cost_per_trade", "dd_cut_pct", "cvar5_cut_pct",
                                  "folds_held", "n_folds", "clauses", "controls", "L1_drop_best_leg", "s0_report")}
            for c, r in g["candidates"].items()}
    note = "; ".join(f"{c}: {r['verdict']} ({r['label']})" for c, r in cand.items())
    return {**base, "verdict": g["verdict"], "read_state": "measured", "n": len(recs),
            "note": f"SCREEN under {ra.RULE_ID} (per-trade R; graduation_eligible false). {note}",
            "measurement": {"rule": g["rule"], "baseline_book": g["baseline_book"], "candidates": cand,
                            "passing": g["passing"], "min_control_beat_frac": args.min_control_beat_frac,
                            "n_comparisons": args.n_comparisons}}


# ── self-test ───────────────────────────────────────────────────────────────────────────────────────────────
def _synthetic(n_trades: int, *, revert: bool):
    """n trades on one synthetic 1h series. Each: entry, a rise to +1.3R by bar 4, then (revert) a slide to the -1R
    stop, or (not revert) a run to +3R. R distance 1.0, entry 100."""
    import pandas as pd
    rows, bars = [], []
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    k = 0
    for i in range(n_trades):
        prof = [0.2, 0.5, 0.8, 1.1, 1.3, 1.0, 0.6, 0.2, -0.3, -0.7, -1.05] if revert else \
               [0.2, 0.5, 0.8, 1.1, 1.3, 1.6, 2.0, 2.4, 2.7, 3.05]
        prof = [0.0] * 14 + [0.0] + prof     # 14 warm-up bars (ATR) + entry bar
        ent_k = k + 14
        for j, r in enumerate(prof):
            p = 100.0 + r
            bars.append({"timestamp": t0 + pd.Timedelta(hours=k), "open": p - 0.05, "high": p + 0.1,
                         "low": p - 0.1, "close": p})
            k += 1
        ex_r = -1.0 if revert else 3.0
        rows.append({"symbol": "SYNUSDT", "direction": "long", "entry": 100.0, "sl": 99.0,
                     "entry_time": str(t0 + pd.Timedelta(hours=ent_k)), "exit_time": str(t0 + pd.Timedelta(hours=k - 1)),
                     "net_r": ex_r - 0.04, "gross_r": ex_r, "mfe_r": 1.4 if revert else 3.1,
                     "exit_reason": "stop" if revert else "take_profit",
                     "cost_fee_r": 0.02, "cost_slippage_r": 0.01, "cost_funding_r": 0.01})
        k += 3 * 24  # gap between trades so calendar folds have content
    df = pd.DataFrame(bars).set_index("timestamp").sort_index()
    return rows, df


def _self_test() -> int:
    fails = []

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)
    rows, df = _synthetic(60, revert=True)
    path = lro._paths(rows[0], df)
    # partial: 0.5 banked at bar j0+1 open, rest keeps recorded
    v, _ = price_partial(rows[0], path, 3, frac=0.5)
    held = (path["idx"][4] - path["entry_ts"]).total_seconds() / (path["exit_ts"] - path["entry_ts"]).total_seconds()
    exp = 0.5 * (path["open"][4] - (0.02 + 0.01 + 0.01 * held)) + 0.5 * rows[0]["net_r"]   # funding pro-rata
    check("partial_close prices f*banked + (1-f)*recorded", abs(v - exp) < 1e-6)
    # tp pull-in with no TP is not expressible; with TP 3 keeps half the distance and fills on the way up
    check("tp_pull_in without a TP is not expressible", price_tp_pull_in(rows[0], path, 0, keep=0.5, tp_r=None) is None)
    v2 = price_tp_pull_in(rows[0], path, 0, keep=0.3, tp_r=3.0)
    x = path["open"][1] + 0.3 * (3.0 - path["open"][1])
    check("tp_pull_in fills at the pulled-in level on a reverting trade (recorded exit was the -1R stop)",
          v2 is not None and x - 0.04 <= v2[0] <= x - 0.03 + 1e-9)
    # structure: at bar 5 (after the peak) the 5-bar swing low is above -1R -> a tighten that stops out above -1R
    atr = atr_r_series(df, path)
    v3 = price_sl_to_structure(rows[0], path, 5, pivot_bars=5, buffer_atr=0.1, atr_r=atr)
    check("sl_to_structure on a reverting trade exits above the recorded -1R stop", v3 is not None and v3[0] > rows[0]["net_r"])
    check("sl_to_structure is refused when the buffered level sits below the initial stop (a widen)",
          price_sl_to_structure(rows[0], path, 0, pivot_bars=5, buffer_atr=50.0, atr_r=atr) is None)
    # end-to-end planted positive: partial at +1R on trades that all revert to the stop must pass the screen
    man = {"leg": "syn", "params": {"timeframe": "1h", "tp_r": 3.0}}
    loader = lambda m, s, tf, r, c: (df, "synthetic")  # noqa: E731
    ns = argparse.Namespace(action="partial_close", triggers="r_milestone", corpus_dir="", legs="", partial_frac=0.5,
                            tp_keep=0.5, pivot_bars=5, pivot_buffer_atr=0.1, max_real_tp_r=10.0, draws=40,
                            min_control_beat_frac=0.95, n_comparisons=1)
    out = run(ns, candle_loader=loader, corpora=[("syn", man, rows)])
    check(f"planted positive (partial@+1R on reverting trades) reads pass, got {out['verdict']}", out["verdict"] == "pass")
    # planted negative: on trades that run to +3R, a partial at +1R gives up R and fails R1
    rows_n, df_n = _synthetic(60, revert=False)
    loader_n = lambda m, s, tf, r, c: (df_n, "synthetic")  # noqa: E731
    out_n = run(ns, candle_loader=loader_n, corpora=[("syn", man, rows_n)])
    check(f"planted negative (partial@+1R on runners) reads fail, got {out_n['verdict']}", out_n["verdict"] == "fail")
    # a trigger that never fires leaves the book untouched -> indeterminate (lever_never_fired)
    ns_nf = argparse.Namespace(**{**vars(ns), "triggers": "adverse_r_0.75"})
    out_nf = run(ns_nf, candle_loader=loader_n, corpora=[("syn", man, rows_n)])
    check(f"a trigger that never fires reads indeterminate, got {out_nf['verdict']}", out_nf["verdict"] == "indeterminate")
    # fictional TP excluded from tp_pull_in, named
    ns_tp = argparse.Namespace(**{**vars(ns), "action": "tp_pull_in"})
    out_tp = run(ns_tp, candle_loader=loader, corpora=[("syn", {"params": {"timeframe": "1h", "tp_r": 50.0}}, rows)])
    check("tp_pull_in excludes a fictional TP (tp_r 50) and reads no_data",
          out_tp["read_state"] == "no_data" and any(k.startswith("no_real_tp") for k in out_tp["excluded"]))
    print(f"self-test: {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 1 if fails else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--action", choices=ACTIONS)
    ap.add_argument("--triggers", default="", help="comma list of ltr_trigger_close_s0.TRIGGERS (pre-registered by the unit)")
    ap.add_argument("--corpus-dir", default=str(REPO / lro.LTR_CORPUS_DIR))
    ap.add_argument("--legs", default="", help="comma list restricting the corpora (default: every committed corpus)")
    ap.add_argument("--partial-frac", type=float, default=0.5)
    ap.add_argument("--tp-keep", type=float, default=0.5, help="tp_pull_in: share of the open->TP distance kept")
    ap.add_argument("--max-real-tp-r", type=float, default=10.0, help="tp_pull_in: tp_r at/above this is fictional")
    ap.add_argument("--pivot-bars", type=int, default=5)
    ap.add_argument("--pivot-buffer-atr", type=float, default=0.1)
    ap.add_argument("--draws", type=int, default=200, help="matched random-time control books")
    ap.add_argument("--min-control-beat-frac", type=float, default=0.95)
    ap.add_argument("--n-comparisons", type=int, default=1, help="family size for the reported Bonferroni CI")
    ap.add_argument("--out", default=None, help="directory; writes verdict.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.action or not a.triggers or not a.out:
        ap.error("--action, --triggers and --out are required (or --self-test)")
    res = run(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(res["population"])
    print(res["verdict"], res.get("note", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
