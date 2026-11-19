#!/usr/bin/env python3
# wiring: manual-only - run by the per-family queue units RQ-2026111x-* (research-script-run.yml) once the manager releases them; no schedule consumes it.
"""DESK-TRIGGER-REPLAY -- does a desk EVENT TRIGGER (config/desk_triggers.yaml) fire on a situation where entering beats a same-model random entry?

Registered BEFORE any harness or unit existed: work-store event 16945 on row DESK-ENTRY-REVIEW-REDESIGN (lane QUEUE-FILL-STANDING-W47,
manager GO 2026-11-19 00:59Z). This file is that rule made executable; nothing here is tunable.

Reuses, does not rewrite, the certified engine ``desk_gen_replay_driver`` exactly as ``desk_event_entry_replay.py`` does: ``simulate`` /
``transplant`` / ``vol_matched_pool`` / ``eligible_cutoffs`` (market entry at the NEXT bar open, stop before target inside a bar, gap rules,
refusal floor, ``execution_costs.roundtrip_cost_r`` = venue fee + resolve_cost_policy slippage + funding). The engine's bar length is the module
constant ``SEC`` (1h); here it is switched to 300 s INSIDE ``five_minute_engine()`` only and restored on exit, so nothing else in the process changes.

FAMILIES (one queue unit each; the detectors are the live ``src/runtime/desk_event_trigger.py::detect``, re-implemented vectorised and checked
against it bar by bar in ``--self-test``)
  atr_burst          last CLOSED 5m bar range >= 2.0 x ATR14           (ATR14 = mean of the 14 true ranges BEFORE that bar, as live)
  momentum_burst     3-bar net close move >= 2.5 x ATR14
  level_break_break  close beyond the prior-48-bar high/low
  level_break_sweep  wick beyond that level that closes back inside (the live detector's ``liquidity_sweep``)
  near_signal / calendar: NOT scored. Their firings are not reconstructable point-in-time from history (near_signal reads the hourly packet's
  system_book, calendar the packet's economic-calendar block, neither archived per bar); recorded unscored with that reason in the result.
FIRING: the decision is at the bar close, entry at the NEXT bar open; nothing later than the cutoff is read. Symbols: BTC/ETH/SOL/XRP/ADA/AVAX USDT.
DIRECTION RULES, scored separately per family: continuation (side = sign of the trigger: bar colour / net move / break side / sweep wick side)
and fade (opposite). The unit's verdict is on the BETTER pre-declared rule (larger S3 mean) only after the Holm step (below); both are reported.
BRACKET (one, fixed, real TP): SL 1.5 x ATR14, TP 3.0 x ATR14 from the cutoff close (the engine's ATR at the cutoff bar), time stop 12 bars
(= the 1 h short-hold cap), market entry.
BASELINE B3 (decisive): random cutoffs of the SAME symbol in the SAME window, same ATR%-decile (vol_matched_pool), more than 12 bars from any
firing of the family, the firing's OWN side and geometry, 200 draws. STATISTIC S3 = mean over firings of (firing net R - B3 mean net R); a
refused slot is no-trade = 0 R on both sides; weekly-cluster bootstrap, 10,000 draws.
BAR: S3 >= +0.15 R (DESK-18G measured E4 DEV +0.157 R) AND the Holm-adjusted 97.5% lower bound > 0 AND n >= 100 firings. INDETERMINATE if n < 100,
if the cell cannot detect +0.15 R at 80% power (measured sd, stated per unit), or if the planted controls fail.
HOLM: m = the registered number of family x rule cells (4 scorable families x 2 rules = 8, ``--m-cells``). A unit scores ONE family, so the
one-sided level used per cell is 0.025 / (m / 2) = 0.05 / m, i.e. Holm's FIRST step (the most conservative one): a cell that clears it clears Holm.
A cell that does not is reported NOT_CLEARED with its one-sided bootstrap p-value; ``holm`` combines the per-family result files and applies the
full step-down, and is the only thing that may upgrade a NOT_CLEARED cell. (Registered text says "Holm"; this is the same test, split across units.)
WINDOWS: DEV exactly as DESK-18G (gr.WINDOW_START .. gr.WINDOW_END); HOLDOUT (2024-11-01 .. 2025-10-25, time-disjoint, before DEV) is read ONLY
for a family whose DEV result PASSED, through ``holdout_lock.claim_read`` made before any holdout outcome is touched.
CONTROLS (RULE ONE; must hold before any verdict): planted ORACLE side (the realised 12-bar forward sign) must clear the bar; ANTI-ORACLE must read
S3 < 0; random-side must not clear; the detectors must give identical firings on a truncated history (no lookahead).
Overlapping firings (consecutive bars of one burst) are KEPT, not de-duplicated (the registered rule has no cooldown); their count is reported and
the weekly-cluster bootstrap carries the dependence.

pass_action: the family goes forward as a candidate trigger for desk_triggers.yaml. fail_action: stays label-only (data collection kept).
Tier 1 research tooling: reads public Binance Vision candles, writes only under --out. Gates this adds or changes: none.
Provenance: harness, firing counts and sd are MEASURED when a run lands; nothing in this file is a result.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "ci", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_gen_replay_driver as gr  # noqa: E402  (the certified replay engine; reused, not rewritten)

RULE_ID = "RULE-DESK-ENTRY-REVIEW-REDESIGN-EVENT-16945-TRIGGER-REPLAY"

# ----------------------------------------------------------------------------- registered numbers (not tunable)
BAR_SEC = 300
SYMS = gr.REGISTERED_SYMBOLS
RANGE_ATR, MOM_BARS, MOM_ATR, LB = 2.0, 3, 2.5, 48       # frozen from config/desk_triggers.yaml at registration (checked by --self-test)
FAMILIES = ("atr_burst", "momentum_burst", "level_break_break", "level_break_sweep")
UNSCORED = {"near_signal": "firing reads the hourly packet's system_book, not archived per bar: not reconstructable point-in-time",
            "calendar": "firing reads the packet's economic-calendar block, not archived per bar: not reconstructable point-in-time"}
RULES = ("continuation", "fade")
SL_ATR, TP_ATR, HORIZON = 1.5, 3.0, 12
GEOM = {"etype": "market", "offset_atr": 0.0, "sl_atr": SL_ATR, "tp_atr": TP_ATR, "good_till": 0, "horizon": HORIZON}
S3_BAR = 0.15
N_MIN = 100
M_CELLS = len(FAMILIES) * len(RULES)
POWER_Z = NormalDist().inv_cdf(0.80)
EXCL_BARS = HORIZON                                       # baseline cutoffs stay > 12 bars from any firing of the family
B_DRAWS = 200
BOOT = 10_000
SEED = 20261119
DEV = (gr.WINDOW_START, gr.WINDOW_END)
HOLDOUT = (datetime(2024, 11, 1, tzinfo=timezone.utc), datetime(2025, 10, 25, tzinfo=timezone.utc))
FETCH_FROM = {"dev": datetime(2025, 10, 1, tzinfo=timezone.utc), "holdout": datetime(2024, 10, 1, tzinfo=timezone.utc)}
HOLDOUT_TRAIN_END = "2024-10-31"     # the detectors have no fit data (parameters frozen from config); the claim needs a date before the window


@contextlib.contextmanager
def five_minute_engine() -> Iterator[None]:
    """Run the certified 1h engine on 5m bars: its bar length is the module globals SEC / SCAN_TF, restored on exit."""
    old = (gr.SEC, gr.SCAN_TF)
    gr.SEC, gr.SCAN_TF = BAR_SEC, "5m"
    try:
        yield
    finally:
        gr.SEC, gr.SCAN_TF = old


# ----------------------------------------------------------------------------- data
def fetch(root: Path, window: str) -> None:
    from scripts.research import desk_replay_driver as d7   # the one Binance Vision route
    days = int((datetime.now(timezone.utc) - FETCH_FROM[window]).days) + 2
    for s in SYMS:
        d7.fetch_candles(s, "5m", days, root / "candles" / f"{s}_5m.csv")


def load(root: Path) -> Dict[str, gr.Series]:
    with five_minute_engine():
        mkt, missing = gr.load_market(root / "candles", list(SYMS))
    if missing:
        raise SystemExit(f"candles missing for {missing}: refusing to score a partial universe")
    return mkt


# ----------------------------------------------------------------------------- detectors (live detect(), vectorised)
def _atr_before(s: gr.Series) -> np.ndarray:
    """atr_pre[j] = mean of the 14 true ranges of bars j-14..j-1 (live atr14: the judged bar j is NOT in its own ATR). NaN for j < 15."""
    n = len(s.t)
    tr = np.full(n, np.nan)
    if n > 1:
        pc = s.c[:-1]
        tr[1:] = np.maximum(s.h[1:] - s.l[1:], np.maximum(np.abs(s.h[1:] - pc), np.abs(s.l[1:] - pc)))
    out = np.full(n, np.nan)
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(tr))])
    j = np.arange(15, n)
    out[15:] = (cs[j] - cs[j - 14]) / 14.0       # tr[j-14..j-1]
    out[out <= 0] = np.nan
    return out


def detect(s: gr.Series, upto: Optional[int] = None) -> Dict[str, List[dict]]:
    """{family: [{sym, j, cutoff, side}]} -- `side` is the CONTINUATION side (+1/-1). Reads only bars whose close time <= `upto`
    (default all), so the no-lookahead control truncates the history and compares."""
    n = len(s.t)
    if upto is not None:
        n = int(np.searchsorted(s.t + BAR_SEC, upto, side="right"))
    t, o, h, l, c = s.t[:n], s.o[:n], s.h[:n], s.l[:n], s.c[:n]  # noqa: E741
    out: Dict[str, List[dict]] = {f: [] for f in FAMILIES}
    if n < LB + 2:
        return out
    sub = gr.Series(s.symbol, t, o, h, l, c, s.atr[:n], s.fee_bps, s.slip_bps, s.fund_bps)
    a = _atr_before(sub)

    def add(fam: str, j: int, side: int) -> None:
        out[fam].append({"sym": s.symbol, "j": int(j), "cutoff": int(t[j]) + BAR_SEC, "side": int(side)})

    with np.errstate(invalid="ignore", divide="ignore"):
        rng = (h - l) / a
        mv = np.full(n, np.nan)
        mv[MOM_BARS:] = (c[MOM_BARS:] - c[:-MOM_BARS]) / a[MOM_BARS:]
        hi = np.full(n, np.nan)
        lo = np.full(n, np.nan)
        w = np.lib.stride_tricks.sliding_window_view
        hi[LB:] = w(h, LB).max(axis=1)[:-1]      # prior LB bars j-LB..j-1
        lo[LB:] = w(l, LB).min(axis=1)[:-1]
    for j in range(n):
        if not np.isfinite(a[j]):
            continue
        if rng[j] >= RANGE_ATR:
            add("atr_burst", j, 1 if c[j] >= o[j] else -1)
        if np.isfinite(mv[j]) and abs(mv[j]) >= MOM_ATR and j > MOM_BARS:
            add("momentum_burst", j, 1 if mv[j] > 0 else -1)
        if j > LB and np.isfinite(hi[j]):
            if c[j] > hi[j]:
                add("level_break_break", j, 1)
            elif c[j] < lo[j]:
                add("level_break_break", j, -1)
            elif h[j] > hi[j]:
                add("level_break_sweep", j, 1)       # trigger = the wick's side; continuation = with the wick, fade = the classic reversal
            elif l[j] < lo[j]:
                add("level_break_sweep", j, -1)
    return out


# ----------------------------------------------------------------------------- scoring
def slot(ser: gr.Series, i: int, side: float) -> Optional[float]:
    """Net R of one market bracket decided at bar i's close; refused = no-trade = 0.0; unresolved/undefined = None (excluded, counted)."""
    t = gr.transplant(ser, i, dict(GEOM, side=float(side)))
    if t is None or t.state == "unresolved":
        return None
    return t.net_r if t.state == "filled" else 0.0


def week_of(epoch: int) -> str:
    return gr.iso_week(epoch)


def boot_means(vals: List[float], weeks: List[str], draws: int = BOOT, seed: int = SEED) -> Optional[np.ndarray]:
    if not vals:
        return None
    ws = sorted(set(weeks))
    ix = {w: k for k, w in enumerate(ws)}
    sm, cn = np.zeros(len(ws)), np.zeros(len(ws))
    for v, w in zip(vals, weeks):
        sm[ix[w]] += v
        cn[ix[w]] += 1
    b = np.random.default_rng(seed).integers(0, len(ws), size=(draws, len(ws)))
    return sm[b].sum(axis=1) / cn[b].sum(axis=1)


def cell_stats(vals: List[float], weeks: List[str], m: int) -> Dict[str, Any]:
    """Mean, the one-sided level 0.05/m lower bound (Holm step 1 at m cells), the 97.5% bound, the one-sided p, and the cluster MDE."""
    bm = boot_means(vals, weeks)
    if bm is None:
        return {"n": 0, "mean": None}
    alpha = 0.05 / m
    mean = float(np.mean(vals))
    lb = float(np.percentile(bm, 100 * alpha))
    hw = float(np.percentile(bm, 100 * (1 - alpha)) - lb) / 2
    za = NormalDist().inv_cdf(1 - alpha)
    return {"n": len(vals), "weeks": len(set(weeks)), "mean": mean, "alpha_one_sided": alpha, "lb_holm1": lb,
            "lb_97_5": float(np.percentile(bm, 2.5)), "p_one_sided": float((np.sum(bm <= 0) + 1) / (len(bm) + 1)),
            "mde_cluster_r": float((za + POWER_Z) / za * hw),
            "sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else None}


def score_family(mkt: Dict[str, gr.Series], firings: List[dict], window: Tuple[datetime, datetime], side_of=None,
                 draws: int = B_DRAWS, seed: int = SEED, m: int = M_CELLS) -> Dict[str, Any]:
    """S3 of one family under ONE side rule (`side_of(f, ser, i)` -> +1/-1); returns the per-firing rows plus the cell stats."""
    lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
    rng = np.random.default_rng(seed)
    near: Dict[str, np.ndarray] = {}
    pools: Dict[str, np.ndarray] = {}
    inwin = [f for f in sorted(firings, key=lambda f: (f["sym"], f["cutoff"])) if lo <= f["cutoff"] < hi]
    for s_ in SYMS:
        ser = mkt[s_]
        mask = np.zeros(len(ser.t), bool)
        for f in inwin:
            if f["sym"] == s_:
                mask[max(0, f["j"] - EXCL_BARS): f["j"] + EXCL_BARS + 1] = True
        near[s_] = mask
    excl = {"outside_window": len(firings) - len(inwin), "unresolved": 0}
    rows = []
    for f in inwin:
        s_ = f["sym"]
        ser = mkt[s_]
        i = f["j"]
        if s_ not in pools:
            pools[s_] = gr.eligible_cutoffs(ser, *window)
        side = float(f["side"]) if side_of is None else float(side_of(f, ser, i))
        x = slot(ser, i, side)
        if x is None:
            excl["unresolved"] += 1
            continue
        pool = gr.vol_matched_pool(ser, pools[s_], i, window=window)
        pool = pool[~near[s_][pool]]
        bs = [v for v in (slot(ser, int(j), side) for j in (rng.choice(pool, size=draws, replace=True) if len(pool) else [])) if v is not None]
        if not bs:
            excl["unresolved"] += 1
            continue
        rows.append({"sym": s_, "week": week_of(f["cutoff"]), "side": side, "x": x, "b3": float(np.mean(bs)), "d": x - float(np.mean(bs))})
    res = {"firings_in_window": len(inwin), "n": len(rows), "excluded": excl,
           "n_long": sum(1 for r in rows if r["side"] > 0), "n_short": sum(1 for r in rows if r["side"] < 0)}
    if not rows:
        return dict(res, _rows=rows)
    d = [r["d"] for r in rows]
    wk = [r["week"] for r in rows]
    cs = cell_stats(d, wk, m)
    res.update({"mean_net_r": float(np.mean([r["x"] for r in rows])), "mean_b3": float(np.mean([r["b3"] for r in rows])),
                "S3": cs, "per_symbol": {s_: {"n": sum(1 for r in rows if r["sym"] == s_),
                                              "S3": float(np.mean([r["d"] for r in rows if r["sym"] == s_])) if any(r["sym"] == s_ for r in rows) else None}
                                          for s_ in SYMS}})
    res["clears"] = bool(cs["n"] >= N_MIN and cs["mean"] >= S3_BAR and cs["lb_holm1"] > 0)
    return dict(res, _rows=rows)


def fwd_sign(ser: gr.Series, i: int) -> float:
    k = i + 1
    j = min(k + HORIZON - 1, len(ser.c) - 1)
    return 1.0 if ser.c[j] >= ser.o[k] else -1.0


def decluster(fires: List[dict], bars: int) -> List[dict]:
    """Keep the first firing per symbol, then only firings more than `bars` bars after the last KEPT one (same symbol).

    CAUSAL: whether a firing is kept depends only on earlier firings of its own symbol, so the truncated-history
    (no-lookahead) control still holds on the declustered list. bars <= 0 returns the input unchanged (the
    registered d7c3 behaviour, byte-identical). Built for PI-20261119-VEWZICCB-0001: in RQ-20261119-d7c3-01
    15,407 of 30,175 atr_burst firings fell within 12 bars of the previous same-symbol firing."""
    if bars <= 0:
        return fires
    last: Dict[str, int] = {}
    out = []
    for f in sorted(fires, key=lambda x: (x["sym"], x["j"])):
        k = last.get(f["sym"])
        if k is None or f["j"] - k > bars:
            out.append(f)
            last[f["sym"]] = f["j"]
    return out


def rule_fn(rule: str):
    return (lambda f, s, i: float(f["side"])) if rule == "continuation" else (lambda f, s, i: -float(f["side"]))


def run_family(mkt: Dict[str, gr.Series], family: str, window: Tuple[datetime, datetime], m: int = M_CELLS,
               controls: bool = True, decluster_bars: int = 0) -> Dict[str, Any]:
    if family not in FAMILIES:
        raise SystemExit(f"family must be one of {FAMILIES} (near_signal/calendar are recorded unscored: {UNSCORED})")
    with five_minute_engine():
        raw = [f for s_ in SYMS for f in detect(mkt[s_])[family]]
        fires = decluster(raw, decluster_bars)
        lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
        inwin = sorted((f for f in fires if lo <= f["cutoff"] < hi), key=lambda f: (f["sym"], f["cutoff"]))
        overlap = sum(1 for a, b in zip(inwin, inwin[1:]) if a["sym"] == b["sym"] and b["j"] - a["j"] <= HORIZON)
        res: Dict[str, Any] = {"rule": RULE_ID, "family": family, "window": [w.isoformat() for w in window],
                               "firings_detected": len(fires), "firings_in_window": len(inwin),
                               "firings_within_12_bars_of_previous_same_symbol": overlap, "m_cells": m,
                               "unscored_families": UNSCORED}
        if decluster_bars > 0:
            res["decluster_bars"] = decluster_bars
            res["firings_dropped_by_decluster"] = len(raw) - len(fires)
        cells = {}
        for r in RULES:
            x = score_family(mkt, fires, window, side_of=rule_fn(r), m=m)
            x.pop("_rows", None)
            cells[r] = x
        res["cells"] = cells
        best = max((r for r in RULES if cells[r].get("S3")), key=lambda r: cells[r]["S3"]["mean"], default=None)
        res["better_rule"] = best
        if controls and best:
            ctl = {"oracle": score_family(mkt, fires, window, side_of=lambda f, s, i: fwd_sign(s, i), draws=40, m=m),
                   "anti_oracle": score_family(mkt, fires, window, side_of=lambda f, s, i: -fwd_sign(s, i), draws=40, m=m),
                   "random_side": score_family(mkt, fires, window, side_of=lambda f, s, i: 1.0 if (f["cutoff"] // BAR_SEC) % 2 else -1.0, draws=40, m=m)}
            res["controls"] = {k: {"n": v.get("n"), "S3": (v.get("S3") or {}).get("mean"), "clears": v.get("clears")} for k, v in ctl.items()}
            res["controls_ok"] = bool(ctl["oracle"].get("clears")) and ((ctl["anti_oracle"].get("S3") or {}).get("mean") or 0) < 0 \
                and not ctl["random_side"].get("clears")
        cut = int(np.median([f["cutoff"] for f in fires])) if fires else 0
        pre = {s_: decluster(detect(mkt[s_], upto=cut)[family], decluster_bars) for s_ in SYMS}
        res["no_lookahead_prefix_identical"] = all(
            [f for f in fires if f["sym"] == s_ and f["cutoff"] <= cut] == pre[s_] for s_ in SYMS)
    res["verdict"], res["verdict_reason"] = verdict(res)
    return res


def verdict(res: Dict[str, Any]) -> Tuple[str, str]:
    """PASS / NOT_CLEARED / INDETERMINATE for one family unit, on the better rule only."""
    best = res.get("better_rule")
    if not best:
        return "INDETERMINATE", "no scorable firings"
    c = res["cells"][best]
    s3 = c["S3"]
    if not res["no_lookahead_prefix_identical"]:
        return "INDETERMINATE", "detector fails the truncated-history (no-lookahead) control"
    if "controls_ok" in res and not res["controls_ok"]:
        return "INDETERMINATE", "planted controls failed (oracle must clear, anti-oracle < 0, random-side must not clear)"
    if c["n"] < N_MIN:
        return "INDETERMINATE", f"n={c['n']} firings < {N_MIN}"
    if s3["mde_cluster_r"] > S3_BAR:
        return "INDETERMINATE", f"cannot detect +{S3_BAR} R at 80% power (cluster MDE {s3['mde_cluster_r']:.3f} R from measured sd {s3['sd']:.3f})"
    return ("PASS", f"{best}: S3 {s3['mean']:+.3f} R, lb {s3['lb_holm1']:+.3f} at level {s3['alpha_one_sided']:.4f}") if c["clears"] \
        else ("NOT_CLEARED", f"{best}: S3 {s3['mean']:+.3f} R, lb {s3['lb_holm1']:+.3f}, p {s3['p_one_sided']:.4f} (holm may still upgrade)")


def holm(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full Holm step-down over every (family, rule) cell in the given per-family result files (DEV, same window)."""
    cells = [(r["family"], rule, r["cells"][rule]["S3"]["p_one_sided"], r["cells"][rule]["S3"]["mean"], r["cells"][rule]["n"])
             for r in results for rule in RULES if r["cells"].get(rule, {}).get("S3")]
    mm = max(len(cells), 1)
    order = sorted(cells, key=lambda c: c[2])
    out, still = [], True
    for k, (fam, rule, p, mean, n) in enumerate(order):
        rej = still and p <= 0.05 / (mm - k)
        still = rej
        out.append({"family": fam, "rule": rule, "p": p, "holm_threshold": 0.05 / (mm - k), "reject_null": bool(rej),
                    "mean": mean, "n": n, "clears_bar": bool(rej and mean >= S3_BAR and n >= N_MIN)})
    return {"m_scored": mm, "cells": out}


# ----------------------------------------------------------------------------- holdout
def run_holdout(root: Path, family: str, dev_result: Path, unit: str, reader: str, ledger: Optional[Path]) -> Dict[str, Any]:
    dev = json.loads(dev_result.read_text())
    if dev.get("family") != family or dev.get("verdict") != "PASS":
        raise SystemExit(f"holdout is read ONLY for a family whose DEV verdict is PASS; {dev_result} says {dev.get('family')} {dev.get('verdict')}")
    import holdout_lock
    led = ledger or Path(root) / "out" / "holdout_reads.jsonl"
    led.parent.mkdir(parents=True, exist_ok=True)
    claim = holdout_lock.claim_read(f"DESK-TRIGGER-{family}", HOLDOUT[0].date().isoformat(), HOLDOUT[1].date().isoformat(), unit, reader, led,
                                    symbols=list(SYMS), train_end=HOLDOUT_TRAIN_END, family=f"DESK-TRIGGER-{family}")
    mkt = load(root)                                  # candles only after the claim is on disk
    res = run_family(mkt, family, HOLDOUT)
    res["holdout_claim"] = claim
    return res


# ----------------------------------------------------------------------------- self-test
def _synth(sym: str, n: int = 6000, seed: int = 7, t0: int = 1_760_000_000 // 300 * 300) -> gr.Series:
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0015, n)
    for k in rng.integers(60, n - 60, 40):          # planted bursts so every family fires
        r[k] += rng.choice([-1, 1]) * 0.012
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[100.0], c[:-1]])
    hh = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0007, n)))
    ll = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0007, n)))
    bars = [{"time": t0 + 300 * k, "open": float(o[k]), "high": float(hh[k]), "low": float(ll[k]), "close": float(c[k])} for k in range(n)]
    with five_minute_engine():
        return gr.Series.from_bars(sym, bars)


def _live_fires(s: gr.Series, upto_j: int) -> List[tuple]:
    """The LIVE detect() on bars[:j+1], for every j in a sample -- the reference the vectorised detectors are checked against."""
    import yaml
    from src.runtime import desk_event_trigger as det
    cfg = yaml.safe_load((REPO / "config" / "desk_triggers.yaml").read_text())
    bars = s.bars(0, len(s.t) - 1)
    out = []
    for j in range(upto_j):
        for e in det.detect(s.symbol, bars[: j + 1], cfg):
            out.append((j, {"liquidity_sweep": "level_break_sweep", "level_break": "level_break_break"}.get(e["kind"], e["kind"]),
                        e["detail"].get("side", e["detail"].get("direction"))))
    return out


def self_test() -> int:
    import yaml
    cfg = yaml.safe_load((REPO / "config" / "desk_triggers.yaml").read_text())["detectors"]
    assert (cfg["atr_burst"]["range_atr"], cfg["momentum_burst"]["bars"], cfg["momentum_burst"]["move_atr"], cfg["level_break"]["lookback"]) \
        == (RANGE_ATR, MOM_BARS, MOM_ATR, LB), "registered parameters drifted from config/desk_triggers.yaml"
    s = _synth("BTCUSDT")
    assert (gr.SEC, gr.SCAN_TF) == (3600, "1h")
    f = detect(s)
    counts = {k: len(v) for k, v in f.items()}
    assert all(v > 5 for v in counts.values()), f"a family never fired on the planted data (positive control): {counts}"
    # 1. identical to the LIVE detector bar by bar (families and direction), on the first 1500 bars
    live = _live_fires(s, 1500)
    mine = sorted((x["j"], fam, x["side"]) for fam, xs in f.items() for x in xs if x["j"] < 1500)
    norm = []
    for j, fam, d in live:
        side = {"up": 1, "down": -1}.get(d)
        if fam == "momentum_burst":
            side = None
        norm.append((j, fam, side))
    mine_n = [(j, fam, None if fam == "momentum_burst" else side) for j, fam, side in mine]
    assert sorted(norm, key=str) == sorted(mine_n, key=str), (len(norm), len(mine_n), sorted(set(norm) ^ set(mine_n), key=str)[:5])
    # 2. no lookahead: detectors on a truncated history equal the prefix of the full ones
    cut = int(s.t[3000]) + BAR_SEC
    pre = detect(s, upto=cut)
    for fam in FAMILIES:
        assert [x for x in f[fam] if x["cutoff"] <= cut] == pre[fam], fam
    # 3. the engine restore, and the scorer end to end on synthetic data (oracle clears, anti-oracle < 0)
    with five_minute_engine():
        assert gr.SEC == 300
    assert gr.SEC == 3600
    mkt = {x: _synth(x, seed=11 + k) for k, x in enumerate(SYMS)}
    lo = datetime.fromtimestamp(int(mkt["BTCUSDT"].t[400]), tz=timezone.utc)
    hi = datetime.fromtimestamp(int(mkt["BTCUSDT"].t[-30]), tz=timezone.utc)
    with five_minute_engine():
        fires = [x for sy in SYMS for x in detect(mkt[sy])["atr_burst"]]
        orc = score_family(mkt, fires, (lo, hi), side_of=lambda f_, s_, i: fwd_sign(s_, i), draws=30, m=1)
        anti = score_family(mkt, fires, (lo, hi), side_of=lambda f_, s_, i: -fwd_sign(s_, i), draws=30, m=1)
    assert orc["n"] > 20 and orc["S3"]["mean"] > 0 > anti["S3"]["mean"], (orc["S3"]["mean"], anti["S3"]["mean"])
    # 3b. decluster: off is identity; on keeps the first of a planted cluster, is causal, and drops what it says
    assert decluster(f["atr_burst"], 0) is f["atr_burst"]
    planted = [{"sym": "X", "j": j} for j in (10, 12, 20, 23, 40)] + [{"sym": "Y", "j": 11}]
    kept = decluster(planted, 12)
    assert [(x["sym"], x["j"]) for x in kept] == [("X", 10), ("X", 23), ("X", 40), ("Y", 11)], kept
    dc = decluster(f["atr_burst"], 12)
    assert 0 < len(dc) <= len(f["atr_burst"])
    assert [x for x in dc if x["cutoff"] <= cut] == decluster(pre["atr_burst"], 12), "decluster broke the no-lookahead prefix"
    # 4. holm: one tiny p clears, a large one does not
    fake = [{"family": "a", "cells": {"continuation": {"n": 200, "S3": {"p_one_sided": 1e-6, "mean": 0.2}},
                                      "fade": {"n": 200, "S3": {"p_one_sided": 0.4, "mean": 0.0}}}}]
    h = holm(fake)["cells"]
    assert h[0]["clears_bar"] and not h[1]["reject_null"]
    print("self-test OK", counts)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("fetch", "run", "holdout", "holm"))
    ap.add_argument("--root", help="cache dir (candles/<SYMBOL>_5m.csv)")
    ap.add_argument("--out")
    ap.add_argument("--family", choices=FAMILIES)
    ap.add_argument("--window", choices=("dev", "holdout"), default="dev")
    ap.add_argument("--m-cells", type=int, default=M_CELLS)
    ap.add_argument("--dev-result", help="holdout: the family's DEV result json (must read PASS)")
    ap.add_argument("--unit", default="")
    ap.add_argument("--reader", default="desk_trigger_replay")
    ap.add_argument("--results", nargs="*", help="holm: per-family DEV result jsons")
    ap.add_argument("--fetch", action="store_true", help="run/holdout: fetch the 5m candles first (a runner starts with an empty cache)")
    ap.add_argument("--decluster-bars", type=int, default=0,
                    help="run: keep the first firing per symbol, then only firings > N bars after the last kept one (0 = off, the d7c3 behaviour)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode:
        ap.error("mode or --self-test required")
    if a.mode == "holm":
        res = holm([json.loads(Path(p).read_text()) for p in a.results or []])
        print(json.dumps(res, indent=1))
        return 0
    root = Path(a.root)
    out = Path(a.out or root / "out")
    if a.mode == "fetch":
        fetch(root, a.window)
        return 0
    if a.fetch:
        fetch(root, "holdout" if a.mode == "holdout" else "dev")
    if not a.family:
        ap.error("--family required")
    if a.mode == "holdout":
        res = run_holdout(root, a.family, Path(a.dev_result), a.unit, a.reader, None)
        name = f"trigger_replay_{a.family}_holdout.json"
    else:
        res = run_family(load(root), a.family, DEV, m=a.m_cells, decluster_bars=a.decluster_bars)
        name = f"trigger_replay_{a.family}_dev{f'_dc{a.decluster_bars}' if a.decluster_bars > 0 else ''}.json"
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(res, indent=1, default=str))
    best = res.get("better_rule")
    n_best = res["cells"][best]["n"] if best else None
    state = "measured" if best else "no_data"
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "NOT_CLEARED": "fail", "INDETERMINATE": "indeterminate"}[res["verdict"]] if state == "measured" else "not_applicable",
        "read_state": state, "population": f"{a.family} firings of config/desk_triggers.yaml detectors on closed 5m bars, six USDT perps, "
        f"{res['window'][0][:10]}..{res['window'][1][:10]}; n = {n_best} scored firings of the better rule ({best})" if state == "measured"
        else f"{a.family}: no scorable firings", "n": n_best if state == "measured" else None, "measurement": res,
        "note": res["verdict_reason"], "data_inputs": ["binance_vision 5m klines"]}, indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("family", "firings_in_window", "better_rule", "verdict", "verdict_reason",
                                          "no_lookahead_prefix_identical") if k in res}, indent=1))
    for r, c in res["cells"].items():
        print(r, json.dumps({k: c.get(k) for k in ("n", "n_long", "n_short", "mean_net_r", "mean_b3", "S3", "clears")}, default=str))
    print("controls", json.dumps(res.get("controls"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
