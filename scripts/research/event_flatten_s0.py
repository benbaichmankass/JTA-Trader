#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-a5b3-01 (lever EVENT-FLATTEN-ARM) via .github/workflows/research-script-run.yml; manual re-run by hand. No timer.
"""Book-level macro-event FLATTEN vs HOLD vs matched random-time flattens, on the committed Stage-0 corpora (offline).

    python3 scripts/research/event_flatten_s0.py --out comms/research/<unit>/<run>
    python3 scripts/research/event_flatten_s0.py --self-test

WHY (lever EVENT-FLATTEN-ARM, unit RQ-20261118-a5b3-01). The operator's Ideas-inbox item (2026-11-18: "we carried 12+
same-direction shorts into FOMC tonight") asks whether the BOOK should shed its majority side before a scheduled US
release. ltr_action_trigger_s0.py prices per-trade actions at per-trade triggers; this action is decided across the
book at a clock time, so it lives here and REUSES that harness's corpus / candle / cost / grading primitives unchanged
(ltr_action_trigger_s0.py itself is not edited).

EVENTS. comms/research/event_span_history/us_releases.jsonl (EVENT-SPAN-HISTORY): graded classes fomc_decision, cpi,
nfp; fomc_minutes is REPORTED only. The graded population is the corpus trades that ENTER inside the history's covered
window [first day of the first graded release's month, last graded release]; trades outside it are excluded with
reason ``outside_event_history`` and the uncovered span is published with read_state could_not_look. Gaps inside the
window (a graded class with no release for longer than its cadence) are listed in ``coverage_gaps``, never filled.

ARMS (every price net of the corpus row's own cost legs: live_review_outcomes.trade_costs, funding pro-rata):
  HOLD          each corpus row's recorded ``net_r`` (the leg's own exit, untouched).
  FLATTEN@T-m   for every graded release at time r, at tau = r - m minutes: the trades open at tau (entry <= tau <
                exit, not already flattened) are counted by side; the side with MORE open trades (each carries 1 R of
                declared risk at entry, so count = declared open risk) is closed at the open of the first bar at or
                after tau (ltr_action_trigger_s0.price_partial with frac 1.0); re-entry none. A tie flattens nothing
                (counted as ``ties``). Graded arm: m = 60. Reported: m = 30, 120, and fomc_minutes at m = 60.
  RANDOM_d      the same majority-side rule at the same NUMBER of clock times, each drawn uniformly on the hourly
                grid of the covered window and rejected when within +-6 h of any graded release (seeded per draw);
                ``--draws`` books (default 200) = the matched random-time control.

GRADE (RULE-RQ-20261118-a5b3-01-BOOK-EVENT-FLATTEN). RULE-AM-RISK-ADJUSTED-V1 (am_risk_adjusted.grade_risk_adjusted)
on the pooled per-trade R book, baseline HOLD, one candidate FLATTEN@T-60m, controls = the random books with
min_control_beat_frac 0.95 (R4), plus L1 (a pass must survive dropping the leg with the largest favourable
contribution, else INDETERMINATE). INDETERMINATE also when fewer than 39 trades are flattened. A SCREEN on per-trade R
books (graduation_eligible false until the BOOK-SIM-REAL-SIZER re-read). REPORTED, never graded: (a) event-spanning vs
non-spanning trades (mean and p10 net R, trade bootstrap CI of each difference, pooled and per leg); the sensitivity
arms; B3 best static over {hold, T-60, T-30, T-120}, each fold's rule chosen on the other folds.

Tier-1 research tooling: reads committed corpora + the committed release history, writes only --out. No live path,
no config write, no apply.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import am_risk_adjusted as ra  # noqa: E402
import live_review_outcomes as lro  # noqa: E402
import ltr_action_trigger_s0 as lat  # noqa: E402

RELEASES = REPO / "comms/research/event_span_history/us_releases.jsonl"
GRADED = ("fomc_decision", "cpi", "nfp")
REPORTED_CLASS = "fomc_minutes"
CADENCE_DAYS = {"fomc_decision": 60, "cpi": 40, "nfp": 40}   # a longer gap between two releases is a coverage gap
GRADED_OFFSET_MIN = 60
SENS_OFFSETS_MIN = (30, 120)
EXCLUSION_H = 6
N_FLAT_FLOOR = 39
SEED = 20261118


def _ts(s: Any) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# ── events ──────────────────────────────────────────────────────────────────────────────────────────────────
def load_releases(path: Path) -> Dict[str, List[datetime]]:
    out: Dict[str, List[datetime]] = defaultdict(list)
    for ln in path.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            out[r["class"]].append(_ts(r["release_utc"]))
    return {k: sorted(v) for k, v in out.items()}


def covered_window(rel: Dict[str, List[datetime]]) -> Tuple[datetime, datetime]:
    g = sorted(t for c in GRADED for t in rel.get(c, []))
    if not g:
        raise SystemExit("no graded releases in the history")
    return g[0].replace(day=1, hour=0, minute=0, second=0, microsecond=0), g[-1]


def coverage_gaps(rel: Dict[str, List[datetime]]) -> List[Dict[str, str]]:
    gaps = []
    for c in GRADED:
        v = rel.get(c, [])
        for a, b in zip(v, v[1:]):
            if (b - a).days > CADENCE_DAYS[c]:
                gaps.append({"class": c, "after": a.isoformat(), "before": b.isoformat(), "days": str((b - a).days)})
    return gaps


def random_times(n: int, lo: datetime, hi: datetime, graded: List[datetime], rng: random.Random) -> List[datetime]:
    """n clock times on the hourly grid of [lo, hi], each > EXCLUSION_H hours from every graded release."""
    hours = int((hi - lo).total_seconds() // 3600)
    ex = timedelta(hours=EXCLUSION_H)
    out: List[datetime] = []
    tries = 0
    while len(out) < n:
        tries += 1
        if tries > 1000 * max(n, 1):
            raise RuntimeError("could not draw random times outside the exclusion band")
        t = lo + timedelta(hours=rng.randrange(hours + 1))
        k = bisect_left(graded, t)
        near = [graded[i] for i in (k - 1, k) if 0 <= i < len(graded)]
        if all(abs(t - g) > ex for g in near):
            out.append(t)
    return sorted(out)


# ── trades ──────────────────────────────────────────────────────────────────────────────────────────────────
def build_records(corpora: List[Tuple[str, dict, List[dict]]], lo: datetime, hi: datetime,
                  candle_loader: Optional[Callable[..., Any]] = None) -> Tuple[List[dict], Counter]:
    excluded: Counter = Counter()
    cache: Dict[Tuple[str, str], Any] = {}
    recs: List[dict] = []
    for leg, man, rows in corpora:
        tf = str((man.get("params") or {}).get("timeframe") or "")
        for i, t in enumerate(rows):
            et, xt = _ts(t["entry_time"]), _ts(t["exit_time"])
            if et < lo or xt > hi:
                excluded["outside_event_history"] += 1
                continue
            df, _p = (candle_loader or lat.resolve_candles)(man, t.get("symbol"), tf, rows, cache)
            if df is None:
                excluded["no_candles"] += 1
                continue
            try:
                path = lro._paths(t, df)
            except (KeyError, ValueError, TypeError):
                path = None
            if path is None or len(path["idx"]) < 1:
                excluded["no_path"] += 1
                continue
            recs.append({"leg": leg, "key": f"{leg}#{i}", "t": t, "path": path, "entry": et, "exit": xt,
                         "side": 1 if t["direction"] == "long" else -1, "entry_time": str(t["entry_time"]),
                         "exit_time": str(t["exit_time"]), "net_r": float(t["net_r"]), "mfe_r": t.get("mfe_r")})
    return recs, excluded


def close_at(rec: dict, tau: datetime) -> Optional[Tuple[float, Any]]:
    """Full close at the open of the first path bar at or after tau; None when no such bar before the exit."""
    idx = rec["path"]["idx"]
    k = next((j for j, ts in enumerate(idx) if ts.to_pydatetime() >= tau), None)
    if k is None:
        return None
    return lat.price_partial(rec["t"], rec["path"], k - 1, frac=1.0)


def flatten_book(recs: List[dict], times: List[datetime]) -> Tuple[Dict[str, Tuple[float, Any]], Dict[str, int]]:
    """Majority-side flatten at each time in ``times``; returns {key: (net_r, exit_ts)} and counters."""
    done: Dict[str, Tuple[float, Any]] = {}
    stats = Counter()
    by_entry = sorted(recs, key=lambda r: r["entry"])
    entries = [r["entry"] for r in by_entry]
    max_hold = max((r["exit"] - r["entry"] for r in recs), default=timedelta(0))
    for tau in sorted(times):
        lo = bisect_left(entries, tau - max_hold)
        hi = bisect_left(entries, tau + timedelta(microseconds=1))
        open_ = [r for r in by_entry[lo:hi] if r["exit"] > tau and r["key"] not in done]
        n_l = sum(1 for r in open_ if r["side"] > 0)
        n_s = len(open_) - n_l
        if not open_:
            stats["events_nothing_open"] += 1
            continue
        if n_l == n_s:
            stats["ties"] += 1
            continue
        side = 1 if n_l > n_s else -1
        stats["events_flattened"] += 1
        for r in open_:
            if r["side"] == side:
                v = close_at(r, tau)
                if v is None:
                    stats["not_expressible"] += 1
                    continue
                done[r["key"]] = v
    stats["trades_flattened"] = len(done)
    return done, dict(stats)


def _book(recs: List[dict], done: Dict[str, Tuple[float, Any]]) -> List[dict]:
    return [lat._trade(r, done.get(r["key"])) for r in recs]


def spanning_report(recs: List[dict], graded: List[datetime], rng: random.Random) -> Dict[str, Any]:
    """(a) REPORTED: event-spanning (a graded release inside [entry, exit)) vs not, pooled and per leg."""
    import numpy as np

    def span(r: dict) -> bool:
        k = bisect_left(graded, r["entry"])
        return k < len(graded) and graded[k] < r["exit"]

    def block(rs: List[dict]) -> Dict[str, Any]:
        a = np.array([r["net_r"] for r in rs if span(r)])
        b = np.array([r["net_r"] for r in rs if not span(r)])
        out: Dict[str, Any] = {"n_spanning": int(a.size), "n_not": int(b.size)}
        if a.size < 2 or b.size < 2:
            return {**out, "read_state": "too_thin"}
        g = np.random.default_rng(rng.randrange(2 ** 32))
        dm, dp = [], []
        for _ in range(lat.BOOT_DRAWS):
            xa, xb = a[g.integers(0, a.size, a.size)], b[g.integers(0, b.size, b.size)]
            dm.append(xa.mean() - xb.mean())
            dp.append(np.percentile(xa, 10) - np.percentile(xb, 10))
        q = lambda xs: [round(float(np.percentile(xs, 2.5)), 4), round(float(np.percentile(xs, 97.5)), 4)]  # noqa: E731
        return {**out, "read_state": "measured", "mean_spanning": round(float(a.mean()), 4),
                "mean_not": round(float(b.mean()), 4), "p10_spanning": round(float(np.percentile(a, 10)), 4),
                "p10_not": round(float(np.percentile(b, 10)), 4), "ci95_mean_diff": q(dm), "ci95_p10_diff": q(dp)}
    legs = defaultdict(list)
    for r in recs:
        legs[r["leg"]].append(r)
    return {"pooled": block(recs), "by_leg": {k: block(v) for k, v in sorted(legs.items())}}


def _l1(books: Dict[str, List[dict]], cl: str, max_cost: float) -> Dict[str, Any]:
    contrib: Dict[str, float] = defaultdict(float)
    for a, c in zip(books["hold"], books[cl]):
        contrib[a["leg"]] += c["net_r"] - a["net_r"]
    best = max(contrib, key=lambda k: contrib[k]) if contrib else None
    a_rest = [a for a in books["hold"] if a["leg"] != best]
    c_rest = [c for c in books[cl] if c["leg"] != best]
    cost = (round((sum(a["net_r"] for a in a_rest) - sum(c["net_r"] for c in c_rest)) / len(a_rest), 6)
            if a_rest else None)
    holds = None if len(contrib) < 2 else (cost is not None and cost <= max_cost)
    return {"best_leg": best, "r_cost_per_trade_without": cost, "holds": holds}


def _sens(books: Dict[str, List[dict]], cl: str) -> Dict[str, Any]:
    A, C = ra.book_metrics(books["hold"]), ra.book_metrics(books[cl])
    n = len(books["hold"])
    return {"r_cost_per_trade": round((sum(a["net_r"] for a in books["hold"]) - sum(c["net_r"] for c in books[cl])) / n, 6),
            "dd_cut_pct": ra._cut_dd(A, C), "cvar5_cut_pct": ra._cut_cvar(A, C)}


def run(args: argparse.Namespace, candle_loader: Optional[Callable[..., Any]] = None,
        corpora: Optional[List[Tuple[str, dict, List[dict]]]] = None,
        releases: Optional[Dict[str, List[datetime]]] = None) -> Dict[str, Any]:
    import numpy as np
    import intervention_controls as ic
    rel = releases if releases is not None else load_releases(Path(args.releases))
    lo, hi = covered_window(rel)
    graded = sorted(t for c in GRADED for t in rel.get(c, []) if lo <= t <= hi)
    corpora = corpora if corpora is not None else lat.load_corpora(Path(args.corpus_dir),
                                                                 args.legs.split(",") if args.legs else None)
    recs, excluded = build_records(corpora, lo, hi, candle_loader)
    n_all = sum(len(r) for _, _, r in corpora)
    first_entry = min((_ts(t["entry_time"]) for _, _, rs in corpora for t in rs), default=None)
    base = {"schema": "event_flatten_s0/v1", "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "population": (f"{len(recs)} trades priced of {n_all} in {len(corpora)} committed Stage-0 corpora "
                           f"({', '.join(lbl for lbl, _, _ in corpora)}), entering inside the release history's covered "
                           f"window {lo.isoformat()}..{hi.isoformat()}; {len(graded)} graded releases ({', '.join(GRADED)})"),
            "covered_window": [lo.isoformat(), hi.isoformat()],
            "uncovered_span": ({"from": first_entry.isoformat(), "to": lo.isoformat(), "read_state": "could_not_look"}
                               if first_entry and first_entry < lo else None),
            "coverage_gaps": coverage_gaps(rel), "excluded": dict(excluded),
            "by_leg_priced": dict(Counter(r["leg"] for r in recs)),
            "cost_stack": "corpus rows' recorded fee + slippage + funding legs (live_review_outcomes.trade_costs)",
            "provenance": "MEASURED", "rule_id": "RULE-RQ-20261118-a5b3-01-BOOK-EVENT-FLATTEN"}
    if not recs:
        return {**base, "verdict": "indeterminate", "read_state": "no_data", "n": None,
                "note": "no trade could be priced (see excluded); nothing measured"}
    off = timedelta(minutes=GRADED_OFFSET_MIN)
    cl = f"flatten@T-{GRADED_OFFSET_MIN}m"
    books: Dict[str, List[dict]] = {"hold": _book(recs, {})}
    done, stats = flatten_book(recs, [g - off for g in graded])
    books[cl] = _book(recs, done)
    sens_stats = {}
    for m in SENS_OFFSETS_MIN:
        d, s = flatten_book(recs, [g - timedelta(minutes=m) for g in graded])
        books[f"flatten@T-{m}m"] = _book(recs, d)
        sens_stats[f"flatten@T-{m}m"] = s
    mins = [t for t in rel.get(REPORTED_CLASS, []) if lo <= t <= hi]
    d, s = flatten_book(recs, [t - off for t in mins])
    books[f"minutes_flatten@T-{GRADED_OFFSET_MIN}m"] = _book(recs, d)
    sens_stats[f"minutes_flatten@T-{GRADED_OFFSET_MIN}m"] = s
    ctl = []
    rand_flat = []
    for k in range(args.draws):
        rng = random.Random(f"{SEED}:{k}")
        times = random_times(len(graded), lo, hi, graded, rng)
        dk, sk = flatten_book(recs, times)
        lab = f"{cl}#rand{k}"
        books[lab] = _book(recs, dk)
        ctl.append(lab)
        rand_flat.append(sk.get("trades_flattened", 0))
    g = ra.grade_risk_adjusted(books, baseline="hold", candidates=[cl], controls={cl: ctl},
                               params={"min_control_beat_frac": args.min_control_beat_frac})
    p = g["rule"]
    if cl not in (g.get("candidates") or {}):       # V1 refused before grading (e.g. baseline n < its floor)
        return {**base, "verdict": "indeterminate", "read_state": "measured", "n": len(recs),
                "note": f"{ra.RULE_ID} did not grade: {g.get('why')}", "measurement": {"rule": p, "flatten_stats": stats}}
    row = g["candidates"][cl]
    row["L1_drop_best_leg"] = _l1(books, cl, float(p["max_r_cost_per_trade"]))
    row["controls"] = {"n": len(row.get("controls") or {}),
                       "beaten": sum(1 for v in (row.get("controls") or {}).values() if v["beats"])}
    verdict, label = row["verdict"], row.get("label")
    if stats.get("trades_flattened", 0) < N_FLAT_FLOOR:
        verdict, label = "indeterminate", f"flattened_below_floor_{N_FLAT_FLOOR}"
    elif verdict == "pass" and row["L1_drop_best_leg"]["holds"] is False:
        verdict, label = "indeterminate", "one_leg_carries_it"
    grid = ["hold", cl] + [f"flatten@T-{m}m" for m in SENS_OFFSETS_MIN]
    mat = np.array([[books[gl][i]["net_r"] - a["net_r"] for gl in grid] for i, a in enumerate(books["hold"])])
    edges = ra.calendar_edges(books["hold"], int(p["folds"]))
    folds = [next((k for k in range(len(edges) - 1) if ra._in_fold(a, edges, k)), -1) for a in books["hold"]]
    bs, chosen = ic.best_static_rule(mat, folds, grid)
    rng = random.Random(SEED)
    cand = {k: row.get(k) for k in ("verdict", "label", "r_cost_per_trade", "dd_cut_pct", "cvar5_cut_pct",
                                    "folds_held", "n_folds", "clauses", "controls", "L1_drop_best_leg")}
    return {**base, "verdict": verdict, "read_state": "measured", "n": len(recs),
            "note": (f"SCREEN under {ra.RULE_ID} + R4 + L1 (per-trade R; graduation_eligible false). {cl}: {verdict} "
                     f"({label}); {stats.get('trades_flattened', 0)} trades flattened at {stats.get('events_flattened', 0)} "
                     f"of {len(graded)} releases"),
            "measurement": {"rule": p, "candidate": cl, "graded": cand, "flatten_stats": stats,
                            "random_trades_flattened": {"mean": round(float(np.mean(rand_flat)), 1),
                                                        "min": int(min(rand_flat)), "max": int(max(rand_flat))},
                            "sensitivity_reported": {k: {**_sens(books, k), **sens_stats[k]} for k in sens_stats},
                            "spanning_reported": spanning_report(recs, graded, rng),
                            "best_static_reported": {"grid": grid, "excludes_test_folds": True,
                                                     "chosen_by_fold": {str(k): v for k, v in chosen.items()},
                                                     "mean_dR_vs_hold": round(float(bs.mean()), 6)},
                            "min_control_beat_frac": args.min_control_beat_frac, "draws": args.draws}}


# ── self-test ───────────────────────────────────────────────────────────────────────────────────────────────
def _synthetic(shock: float, n_events: int = 60):
    """Two legs of 1h trades: around each 'release' at hour H, 3 shorts + 1 long are open from H-5 to H+5; the
    release moves price by ``shock`` (up = against the shorts). Between releases the series is flat."""
    import pandas as pd
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    n_h = n_events * 72 + 48
    px = [100.0] * n_h
    rows = {"a": [], "b": []}
    rels = []
    for e in range(n_events):
        H = 24 + e * 72
        rels.append((t0 + pd.Timedelta(hours=H)).to_pydatetime())
        for h in range(H, n_h):
            px[h] += shock if h < H + 6 else 0.0        # shock lasts through the trades' exit bar, then reverts
        for i, (leg, d) in enumerate((("a", "short"), ("a", "short"), ("b", "short"), ("b", "long"))):
            ent = 100.0
            sl = ent + 1.0 if d == "short" else ent - 1.0
            sign = -1.0 if d == "short" else 1.0
            ex_px = 100.0 + shock
            gross = sign * (ex_px - ent) / 1.0
            rows[leg].append({"symbol": "SYNUSDT", "direction": d, "entry": ent, "sl": sl,
                              "entry_time": str(t0 + pd.Timedelta(hours=H - 5)),
                              "exit_time": str(t0 + pd.Timedelta(hours=H + 5)), "gross_r": gross,
                              "net_r": gross - 0.04, "mfe_r": max(0.0, gross), "exit_reason": "time",
                              "cost_fee_r": 0.02, "cost_slippage_r": 0.01, "cost_funding_r": 0.01})
    bars = [{"timestamp": t0 + pd.Timedelta(hours=h), "open": p, "high": p + 0.05, "low": p - 0.05, "close": p}
            for h, p in enumerate(px)]
    df = pd.DataFrame(bars).set_index("timestamp").sort_index()
    man = {"params": {"timeframe": "1h"}}
    corpora = [("a", man, rows["a"]), ("b", man, rows["b"])]
    releases = {"fomc_decision": rels, "cpi": [], "nfp": [], "fomc_minutes": []}
    return corpora, df, releases


def _self_test() -> int:
    fails = []

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)
    ns = argparse.Namespace(draws=40, min_control_beat_frac=0.95, corpus_dir="", legs="", releases="")
    # planted positive: every release moves 1.5 R against the 3-short majority -> flattening the shorts pays
    corpora, df, rels = _synthetic(shock=1.5)
    loader = lambda m, s, tf, r, c: (df, "synthetic")  # noqa: E731
    lo, hi = covered_window(rels)
    recs, _ = build_records(corpora, lo, hi, loader)
    graded = sorted(rels["fomc_decision"])
    done, st = flatten_book(recs, [g - timedelta(minutes=60) for g in graded])
    check("majority side is the shorts: 3 of 4 open trades flattened per release, the long kept",
          st["trades_flattened"] == 3 * len(recs) // 4 and all(r["side"] < 0 for r in recs if r["key"] in done))
    r0 = next(r for r in recs if r["key"] in done)
    v = done[r0["key"]][0]
    check("flatten closes at the first bar open at/after T-60 net of cost (flat price -> ~ -costs)", -0.05 < v < -0.02)
    out = run(ns, candle_loader=loader, corpora=corpora, releases=rels)
    check(f"planted positive (releases move against the majority) reads pass, got {out['verdict']} / {out['note']}",
          out["verdict"] == "pass")
    sp = out["measurement"]["spanning_reported"]["pooled"]
    check("spanning report is published (every synthetic trade spans a release -> too_thin non-spanning arm)",
          sp["n_spanning"] == len(recs) and sp["read_state"] == "too_thin")
    # planted negative: releases move WITH the shorts -> flattening gives up R (R1 fails)
    corpora_n, df_n, rels_n = _synthetic(shock=-1.5)
    loader_n = lambda m, s, tf, r, c: (df_n, "synthetic")  # noqa: E731
    out_n = run(ns, candle_loader=loader_n, corpora=corpora_n, releases=rels_n)
    check(f"planted negative (releases favour the majority) reads fail, got {out_n['verdict']}", out_n["verdict"] == "fail")
    # random times never land within +-6 h of a graded release
    rt = random_times(200, lo, hi, graded, random.Random(1))
    check("random control times keep the +-6 h exclusion band",
          all(min(abs(t - g) for g in graded) > timedelta(hours=EXCLUSION_H) for t in rt))
    # tie: equal longs and shorts flatten nothing
    tie = [dict(r) for r in recs[:2]]
    tie[0]["side"], tie[1]["side"] = 1, -1
    tie[0]["key"], tie[1]["key"] = "x", "y"
    _d, st_t = flatten_book(tie, [graded[0] - timedelta(minutes=60)])
    check("a tie (1 long, 1 short) flattens nothing", st_t.get("trades_flattened") == 0 and st_t.get("ties") == 1)
    # thin: too few releases -> under the 39-trade floor -> indeterminate
    rels_t = {**rels, "fomc_decision": rels["fomc_decision"][:5]}
    out_t = run(ns, candle_loader=loader, corpora=corpora, releases=rels_t)
    check(f"fewer than 39 flattened trades reads indeterminate, got {out_t['verdict']}", out_t["verdict"] == "indeterminate")
    # coverage: a trade before the history is excluded and the span is published as could_not_look
    gap = {"fomc_decision": [datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 6, 1, tzinfo=timezone.utc)]}
    check("a release gap longer than the class cadence is listed", len(coverage_gaps(gap)) == 1)
    check("trades entering before the covered window are excluded as outside_event_history",
          build_records(corpora, hi, hi + timedelta(days=1), loader)[1]["outside_event_history"]
          == sum(len(r) for _, _, r in corpora))
    check("a trade exiting after the last graded release is outside the covered window (the next release is unknown)",
          len(recs) == sum(len(r) for _, _, r in corpora) - 4)
    print(f"self-test: {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 1 if fails else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus-dir", default=str(REPO / lro.LTR_CORPUS_DIR))
    ap.add_argument("--legs", default="", help="comma list restricting the corpora (default: every committed corpus)")
    ap.add_argument("--releases", default=str(RELEASES))
    ap.add_argument("--draws", type=int, default=200, help="matched random-time control books")
    ap.add_argument("--min-control-beat-frac", type=float, default=0.95)
    ap.add_argument("--out", default=None, help="directory; writes verdict.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required (or --self-test)")
    res = run(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(res["population"])
    print(res["verdict"], res.get("note", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
