#!/usr/bin/env python3
# wiring: manual-only - run by the DESK-EDGE-PROGRAM lane and research/queue unit RQ-20261027-fe57-02; no schedule consumes it.
"""DESK-EDGE-PROGRAM, RQ-20261027-fe57-02 -- the SHORT-HOLD information ceiling on 1-minute perp bars (token-free).

Rule and constants: research/queue/blocked/RQ-20261027-fe57-02.yaml and docs/research/desk-edge-program-2026-10-27.md
section 6 (registered before this file existed). Question: at holds of 5-60 minutes (the live claude_desk cap) and under
the hold rule "enter now, may run to H" for H = 120 / 240 / 480 minutes, can any fitted learner pick entries with
S3 >= +0.25 R AND S1 > 0, under the MEASURED taker cost and under a maker-entry / taker-exit cost?

REUSE, NOT RE-IMPLEMENTATION. The driver (desk_gen_replay_driver) supplies the engine (transplant -> simulate, stop
before target inside a bar, gap fills, time stop), the random-entry baseline (random_baseline), the folds (fold_of),
weeks and cluster_stats; desk_edge_ceiling supplies the learners, the walk-forward with embargo, the desk-like policy,
the corrected CI and the verdict machinery. The ONE adaptation: the driver's bar length constant `d.SEC` is set to 60
for this process (every driver function reads it at call time), so a d.Series of 1-minute bars replays exactly as an
hourly one does. Nothing in the driver is edited.

COSTS. Every action is simulated once with the MEASURED Bybit taker stack (11.0 bps fee + 1.3 bps slippage round
trip; comms/research/desk_edge/levers/bybit-fee-measured-2026-10-27.json and R3) and re-costed with
execution_costs.roundtrip_cost_r under the maker-entry scenario (2 + 5.5 bps fee, 1.5 bps slippage: Bybit's published
maker fee, INFERRED; we have no maker fill). The maker re-costing assumes the limit FILLS at the same price: an upper
bound on the maker lever (no fill-probability or adverse-selection haircut), stated in every verdict.

  build  --klines DIR --out DIR [--workers 4]   cutoffs x actions x labels (both cost scenarios), features
  run    --out DIR --evidence DIR               walk-forward learners, controls, per-hold verdicts, hold-rule comparison
  mechanism --out DIR --evidence DIR            the model-free volatility selector (is S3 earnable from cost alone?)
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_edge_ceiling as ce  # noqa: E402
from src.runtime import execution_costs as xc  # noqa: E402
import desk_scan_packet as dsp  # noqa: E402

# ----------------------------------------------------------------------------- registered design (fe57-02)
BAR_SEC = 60
CUTOFF_STEP_MIN = 60                                 # amended from 15 BEFORE the full run (compute: 2.6M -> 650k actions)
HOLDS_MIN = (5, 15, 30, 60, 120, 240, 480)          # 5-60 hard cap; 120/240/480 = the hold rule's H
HARD_CAP_MIN = 60
STOP_SQRT_ATR = 1.0                                  # stop = sqrt(hold) x ATR14 of 1m bars (about 1.3 sd of the hold's move)
TP_R = 1.5
TAKER = (11.0, 1.3)                                  # (fee, slippage) bps round trip, MEASURED
MAKER = (7.5, 1.5)                                   # maker entry 2 + taker exit 5.5, slippage on the exit only (INFERRED)
FUND_BPS = 1.0
TARGET_S3 = 0.25
HOLD_RULE_MIN_GAIN = 0.10
N_FAMILY = len(HOLDS_MIN) * 3 * 2                    # holds x learners x cost scenarios = 42
LEARNERS = ("ridge", "logit", "gbdt")
FEATURE_LOOKBACK = 1440
SEED = 20261027
EMBARGO_BARS = 600                                   # > the longest hold (480 min); desk_edge_ceiling's EMBARGO_H counts BARS


def _only_member(z: zipfile.ZipFile) -> str:
    """A Binance Vision monthly zip holds exactly one CSV; refuse anything else rather than pick one."""
    (name,) = z.namelist()
    return name


def geometry(hold: int) -> dict:
    return {"etype": "market", "offset_atr": 0.0, "sl_atr": STOP_SQRT_ATR * math.sqrt(hold),
            "tp_atr": STOP_SQRT_ATR * math.sqrt(hold) * TP_R, "good_till": 1, "horizon": hold}


# ----------------------------------------------------------------------------- data
def load_1m(klines: Path, symbols) -> Tuple[Dict[str, d.Series], Dict[str, Dict[str, np.ndarray]]]:
    """{symbol: d.Series of 1m bars (MEASURED taker costs)}, {symbol: {v, tb}} from Binance Vision USD-M 1m zips."""
    mkt, flow = {}, {}
    for s in symbols:
        rows = []
        files = sorted(glob.glob(str(klines / f"{s}-1m-*.zip")))     # every month is read; none is chosen over another
        print(f"load_1m: {s}: reading all {len(files)} files {[Path(f).name for f in files]}", file=sys.stderr)
        for f in files:
            z = zipfile.ZipFile(f)
            for ln in z.read(_only_member(z)).decode().splitlines():
                if ln and not ln.startswith("open_time"):
                    p = ln.split(",")
                    rows.append((int(p[0]) // 1000, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[9])))
        if not rows:
            continue
        rows.sort()
        a = np.array(rows)
        bars = [{"time": int(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in rows]
        atr = np.array([np.nan if x is None else x for x in dsp.atr_series(bars)])
        mkt[s] = d.Series(s, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], atr, TAKER[0], TAKER[1], FUND_BPS)
        flow[s] = {"v": a[:, 5], "tb": a[:, 6]}
    return mkt, flow


def cutoffs(start: datetime = d.WINDOW_START, end: datetime = d.WINDOW_END) -> List[int]:
    return list(range(d._epoch(start), d._epoch(end), CUTOFF_STEP_MIN * 60))


# ----------------------------------------------------------------------------- features (all at or before the cutoff bar)
def sym_features(s: d.Series, fl: Dict[str, np.ndarray], i: int) -> Dict[str, float]:
    a = float(s.atr[i]) if np.isfinite(s.atr[i]) and s.atr[i] > 0 else float("nan")
    o: Dict[str, float] = {}
    for k in (1, 5, 15, 60, 240):
        o[f"ret{k}"] = float((s.c[i] - s.c[i - k]) / (a * math.sqrt(k))) if i >= k else float("nan")
    for n in (60, 240, 1440):
        lo, hi = float(s.l[max(0, i - n + 1): i + 1].min()), float(s.h[max(0, i - n + 1): i + 1].max())
        o[f"rpos{n}"] = (float(s.c[i]) - lo) / (hi - lo) - 0.5 if hi > lo else float("nan")
    base = s.atr[max(0, i - FEATURE_LOOKBACK): i + 1]
    o["atr_rel1440"] = float(a / np.nanmean(base)) if np.isfinite(base).any() else float("nan")
    o["atr_pct"] = float(a / s.c[i] * 1e4)
    v, tb = fl["v"], fl["tb"]
    for n in (1, 5, 15, 60):
        vv = v[i - n + 1: i + 1].sum()
        o[f"taker_buy{n}"] = float(tb[i - n + 1: i + 1].sum() / vv - 0.5) if vv > 0 else float("nan")
    v60, v1440 = v[max(0, i - 59): i + 1].sum(), v[max(0, i - FEATURE_LOOKBACK): i + 1].sum() / 24.0
    o["vol60_z"] = float(math.log(v60 / v1440)) if v60 > 0 and v1440 > 0 else float("nan")
    return o


SIGNED = ("ret1", "ret5", "ret15", "ret60", "ret240", "rpos60", "rpos240", "rpos1440", "taker_buy1", "taker_buy5", "taker_buy15", "taker_buy60")


def action_features(ex: Dict[str, Dict[str, float]], sym: str, side: str, cutoff: int, hold: int) -> Dict[str, float]:
    sg = 1.0 if side == "long" else -1.0
    o = {k: (sg * v if k in SIGNED else v) for k, v in ex[sym].items()}
    for k in ("ret5", "ret60"):
        o[f"btc_{k}"] = sg * ex["BTCUSDT"].get(k, float("nan")) if "BTCUSDT" in ex else float("nan")
        xs = np.array([sg * ex[s].get(k, float("nan")) for s in ex])
        own = sg * ex[sym].get(k, float("nan"))
        o[f"xs_{k}_rank"] = float((xs < own).sum()) / max(1, len(xs) - 1) if np.isfinite(own) else float("nan")
    dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
    m = dt.hour * 60 + dt.minute
    o.update(side_long=1.0 if side == "long" else 0.0, hold=float(hold), log_hold=math.log(hold),
             tod_sin=math.sin(2 * math.pi * m / 1440), tod_cos=math.cos(2 * math.pi * m / 1440), dow=float(dt.weekday()))
    for s in d.REGISTERED_SYMBOLS:
        o[f"sym_{s}"] = 1.0 if s == sym else 0.0
    return o


# ----------------------------------------------------------------------------- labels
def maker_net(t: d.Trade, s: d.Series) -> float:
    """The same fill and exit re-costed under MAKER (fill price unchanged: the upper bound stated in the docstring)."""
    t_in, t_out = int(s.t[t.fill_i]), int(s.t[t.exit_i]) + BAR_SEC
    c = xc.roundtrip_cost_r(entry=t.fill_px, exit_price=t.exit_px, risk=t.risk,
                            entry_time=datetime.fromtimestamp(t_in, tz=timezone.utc).isoformat(),
                            exit_time=datetime.fromtimestamp(t_out, tz=timezone.utc).isoformat(),
                            fee_bps_roundtrip=MAKER[0], slippage_bps_roundtrip=MAKER[1], funding_bps_per_window=FUND_BPS)
    return t.gross_r - c["total_cost_r"]


def baseline(s: d.Series, g: dict, pool: np.ndarray, rng: np.random.Generator) -> Tuple[Optional[float], Optional[float]]:
    """(taker mean net, maker mean net) of random entries with geometry g: the driver's random_baseline for the taker
    stack, and the same draws re-costed for maker."""
    br = d.random_baseline(s, g, pool, rng, ce.BASELINE_DRAWS)
    if br["mean"] is None:
        return None, None
    rng2 = np.random.default_rng(int(rng.integers(1 << 31)))
    mk = []
    for j in rng2.choice(pool, size=ce.BASELINE_DRAWS, replace=True):
        t = d.transplant(s, int(j), g)
        if t is not None and t.state == "filled":
            mk.append(maker_net(t, s))
    return br["mean"], (float(np.mean(mk)) if mk else None)


_G: Dict[str, Any] = {}


def _build_symbol(sym: str) -> List[dict]:
    d.SEC = BAR_SEC
    mkt, cuts = _G["mkt"], _G["cuts"]
    s = mkt[sym]
    rng = np.random.default_rng(SEED + d.REGISTERED_SYMBOLS.index(sym))
    base: Dict[Tuple, Tuple] = {}
    rows = []
    for c in cuts:
        i = s.last_closed(c)
        if i < FEATURE_LOOKBACK or not np.isfinite(s.atr[i]):
            continue
        fold = d.fold_of(c)
        for side, sg in ce.SIDES:
            for h in _G.get("holds", HOLDS_MIN):
                g = dict(geometry(h), side=sg)
                t = d.transplant(s, i + _G.get("delay", 0), g)     # features stay at bar i; the entry decision is delayed
                if t is None or t.state != "filled":
                    continue
                bk = (fold, side, h)
                if bk not in base:
                    base[bk] = baseline(s, g, d.eligible_cutoffs(s, d.WINDOW_START, d.WINDOW_END, fold), rng)
                bt, bm = base[bk]
                if bt is None or bm is None:
                    continue
                mn = maker_net(t, s)
                rows.append({"cutoff": c, "fold": fold, "week": d.iso_week(c), "symbol": sym, "side": side, "hold": h,
                             "net_r": t.net_r, "y": t.net_r - bt, "net_r_maker": mn, "y_maker": mn - bm,
                             "days": t.days, "cost_r": t.cost_r})
    return rows


def cmd_build(a: argparse.Namespace) -> int:
    import multiprocessing as mp
    import pickle
    d.SEC = BAR_SEC
    syms = list(d.REGISTERED_SYMBOLS)
    mkt, flow = load_1m(Path(a.klines), syms)
    missing = sorted(set(syms) - set(mkt))
    if missing:
        raise SystemExit(f"1m klines missing for {missing}")
    cuts = cutoffs()
    if a.limit:
        cuts = cuts[:: max(1, len(cuts) // a.limit)]
    _G.update(mkt=mkt, flow=flow, cuts=cuts, delay=a.delay, holds=tuple(int(x) for x in a.holds.split(",")) if a.holds else HOLDS_MIN)
    with mp.get_context("fork").Pool(a.workers) as pool:
        parts = pool.map(_build_symbol, syms)
    acts = [r for p in parts for r in p]
    ex = {}
    for c in cuts:
        ex[c] = {s: sym_features(mkt[s], flow[s], mkt[s].last_closed(c)) for s in syms if mkt[s].last_closed(c) >= FEATURE_LOOKBACK}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "actions.pkl").write_bytes(pickle.dumps(acts))
    (out / "features.pkl").write_bytes(pickle.dumps(ex))
    (out / "meta.json").write_text(json.dumps({"delay_bars": a.delay, "holds": list(_G["holds"])}) + "\n")
    print(json.dumps({"cutoffs": len(cuts), "actions": len(acts), "by_hold": {h: sum(1 for r in acts if r["hold"] == h) for h in HOLDS_MIN}}))
    return 0


# ----------------------------------------------------------------------------- run
def matrix(ex, acts) -> np.ndarray:
    """Features per (cutoff, symbol, side) computed once and shared by its holds; hold columns appended."""
    keys, idx, vecs, names = {}, [], [], None
    for r in acts:
        k = (r["cutoff"], r["symbol"], r["side"])
        if k not in keys:
            f = action_features(ex[r["cutoff"]], r["symbol"], r["side"], r["cutoff"], HOLDS_MIN[0])
            f.pop("hold"), f.pop("log_hold")
            if names is None:
                names = sorted(f)
            keys[k] = len(vecs)
            vecs.append([f.get(n, float("nan")) for n in names])
        idx.append(keys[k])
    base = np.array(vecs, dtype=float)[np.array(idx)]
    h = np.array([r["hold"] for r in acts], dtype=float)
    return np.column_stack([base, h, np.log(h)])


def scored(rows: List[dict], idx, cost: str) -> List[dict]:
    yk, nk = ("y", "net_r") if cost == "taker" else ("y_maker", "net_r_maker")
    return [{"week": rows[j]["week"], "net_r": rows[j][nk], "days": rows[j]["days"], "diff": rows[j][yk]} for j in idx]


def per_hold(rows: List[dict], preds: Dict[str, np.ndarray], alpha: float) -> Dict[str, Any]:
    out = {}
    hold = np.array([r["hold"] for r in rows])
    for h in HOLDS_MIN:
        m = np.nonzero(hold == h)[0]
        if not len(m):
            continue
        hr = [rows[j] for j in m]
        ent: Dict[str, Any] = {"actions": len(hr), "mean_cost_r_taker": float(np.mean([r["cost_r"] for r in hr])) if hr else None,
                               "unselected_gross_R": float(np.mean([r["net_r"] + r["cost_r"] for r in hr])) if hr else None,
                               "unselected_S1_taker": float(np.mean([r["net_r"] for r in hr])) if hr else None,
                               "unselected_S1_maker": float(np.mean([r["net_r_maker"] for r in hr])) if hr else None}
        cands, best_hi = [], -9.0
        for lr, p in preds.items():
            picks = ce.policy_picks(hr, p[m])
            for cost in ("taker", "maker"):
                sr = scored(hr, picks, cost)
                st = d.cluster_stats(sr, draws=3000)
                lo, hi = ce.cluster_ci(sr, "diff", alpha, draws=3000)
                key = f"{lr}/{cost}"
                gross = [hr[j]["net_r"] + hr[j]["cost_r"] for j in picks]
                ent[key] = {"n": st["n"], "S1": st["mean_net_r"], "S3": st.get("paired_diff_vs_random"), "S3_ci95": st.get("paired_diff_ci95"),
                            "S3_ci_corrected": [lo, hi], "weekly_S1": _weekly(sr, "net_r"),
                            # the timing check (doc 4.6): GROSS R of the picks (no cost) vs the unselected gross; S3 can also come
                            # from picking low-cost-in-R moments (high volatility), which is not timing
                            "gross_R_picks": float(np.mean(gross)) if gross else None,
                            "taker_cost_R_picks": float(np.mean([hr[j]["cost_r"] for j in picks])) if picks else None}
                best_hi = max(best_hi, hi)
                if st.get("paired_diff_vs_random", -9) >= TARGET_S3 and lo > 0 and st["mean_net_r"] > 0:
                    cands.append(key)
        ent["verdict"] = "candidate" if cands else ("no_edge" if best_hi < TARGET_S3 else "inconclusive")
        ent["candidates"] = cands
        out[str(h)] = ent
    return out


def _weekly(sr: List[dict], f: str) -> Dict[str, float]:
    wk: Dict[str, List[float]] = {}
    for r in sr:
        wk.setdefault(r["week"], []).append(r[f])
    return {w: float(np.mean(v)) for w, v in wk.items()}


def hold_rule(ph: Dict[str, Any], alpha: float) -> Dict[str, Any]:
    """S1 of each H in 120/240/480 minus the hard 60-min cap, same learner and cost, paired by week; corrected CI."""
    out = {}
    for h in (120, 240, 480):
        for key in [k for k in ph[str(HARD_CAP_MIN)] if "/" in k]:
            a_, b_ = ph[str(h)][key]["weekly_S1"], ph[str(HARD_CAP_MIN)][key]["weekly_S1"]
            wk = sorted(set(a_) & set(b_))
            if len(wk) < 5:
                continue
            dlt = np.array([a_[w] - b_[w] for w in wk])
            bt = np.random.default_rng(SEED).choice(dlt, size=(10_000, len(dlt)), replace=True).mean(axis=1)
            lo, hi = float(np.percentile(bt, 100 * alpha / 2)), float(np.percentile(bt, 100 * (1 - alpha / 2)))
            out[f"H{h} vs cap60 {key}"] = {"weeks": len(wk), "S1_gain": float(dlt.mean()), "ci_corrected": [lo, hi],
                                           "wins": bool(dlt.mean() >= HOLD_RULE_MIN_GAIN and lo > 0)}
    return out


def cmd_run(a: argparse.Namespace) -> int:
    import pickle
    d.SEC = BAR_SEC
    src = Path(a.out)
    acts = pickle.loads((src / "actions.pkl").read_bytes())
    ex = pickle.loads((src / "features.pkl").read_bytes())
    X = matrix(ex, acts)
    ce.EMBARGO_H = EMBARGO_BARS            # walk_forward multiplies it by d.SEC (60 here): 600 minutes > the 480-min hold
    alpha = ce.ALPHA / N_FAMILY
    te = np.array([r["fold"] in ce.TEST_FOLDS for r in acts])
    rows = [acts[j] for j in np.nonzero(te)[0]]
    preds = {}
    for lr in LEARNERS:
        preds[lr] = ce.walk_forward(acts, X, lr)[te]
        print(json.dumps({"learner": lr, "done": True}), flush=True)
    ph = per_hold(rows, preds, alpha)
    hr = hold_rule(ph, alpha) if str(HARD_CAP_MIN) in ph and all(str(h) in ph for h in (120, 240, 480)) else {}
    # controls on GBDT and ridge (taker): a planted signal must reach `candidate` somewhere; shuffled labels must not
    y = np.array([r["y"] for r in acts])
    planted = y + np.random.default_rng(SEED + 1).normal(0, 2.0 * y.std(), len(y))
    ctl = {}
    for name, kw in (("planted_signal", {"extra_col": planted}), ("shuffled_labels", {"label_noise": "shuffle"})):
        pp = {lr: ce.walk_forward(acts, X, lr, **kw)[te] for lr in ("ridge", "gbdt")}
        c = per_hold(rows, pp, alpha)
        ctl[name] = {h: {"verdict": v["verdict"], "S3": {k: v[k]["S3"] for k in v if "/" in k}} for h, v in c.items()}
    valid = any(v["verdict"] == "candidate" for v in ctl["planted_signal"].values()) and \
        not any(v["verdict"] == "candidate" for v in ctl["shuffled_labels"].values())
    verdict = "instrument_invalid" if not valid else ("candidate" if any(v["verdict"] == "candidate" for v in ph.values()) else
                                                      "no_edge" if all(v["verdict"] == "no_edge" for v in ph.values()) else "inconclusive")
    for v in ph.values():
        for k in [k for k in v if "/" in k]:
            v[k].pop("weekly_S1", None)
    res = {"verdict": verdict, "read_state": "measured", "instrument_valid": valid, "per_hold": ph, "hold_rule": hr, "controls": ctl,
           "design": {"holds_min": HOLDS_MIN, "cutoff_step_min": CUTOFF_STEP_MIN, "stop": f"{STOP_SQRT_ATR} x sqrt(hold) x ATR14(1m)",
                      "tp_r": TP_R, "taker_bps": TAKER, "maker_bps": MAKER, "family": N_FAMILY, "alpha_corrected": alpha,
                      "target_s3": TARGET_S3, "test_folds": ce.TEST_FOLDS,
                      "maker_limit": "maker re-costs the same fill: an UPPER bound (no fill probability, no adverse selection)"},
           "population": {"actions": len(acts), "test_actions": len(rows), "window": [d.WINDOW_START.isoformat(), d.WINDOW_END.isoformat()],
                          "source": "Binance Vision USD-M perp 1m klines, six symbols"}}
    d._write_verdict(Path(a.evidence), res, f"1m-bar short-hold ceiling, {len(rows)} test actions", len(rows),
                     f"verdict {verdict}", None, None)
    print(json.dumps({"verdict": verdict, "valid": valid, "per_hold": {h: v["verdict"] for h, v in ph.items()}}))
    return 0


def cmd_mechanism(a: argparse.Namespace) -> int:
    """Doc section 4.6: a MODEL-FREE selector (highest ATR% first, the same policy) - its S3 and the GROSS R / cost of its
    picks. If it earns S3 with ~0 gross R, S3 at that hold can be earned from cost selection alone."""
    import pickle
    d.SEC = BAR_SEC
    acts = pickle.loads((Path(a.out) / "actions.pkl").read_bytes())
    ex = pickle.loads((Path(a.out) / "features.pkl").read_bytes())
    res = {}
    for h in sorted({r["hold"] for r in acts}):
        rows = [r for r in acts if r["hold"] == h and r["fold"] in ce.TEST_FOLDS]
        picks = ce.policy_picks(rows, np.array([ex[r["cutoff"]][r["symbol"]]["atr_pct"] for r in rows]))
        st = d.cluster_stats(ce.s_rows(rows, picks), draws=2000)
        res[str(h)] = {"vol_rule_S3": st["paired_diff_vs_random"], "S3_ci95": st["paired_diff_ci95"], "S1": st["mean_net_r"],
                       "cost_all": float(np.mean([r["cost_r"] for r in rows])), "cost_picks": float(np.mean([rows[j]["cost_r"] for j in picks])),
                       "gross_picks": float(np.mean([rows[j]["net_r"] + rows[j]["cost_r"] for j in picks])),
                       "gross_all": float(np.mean([r["net_r"] + r["cost_r"] for r in rows]))}
    Path(a.evidence).mkdir(parents=True, exist_ok=True)
    (Path(a.evidence) / "vol-rule-mechanism.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({h: round(v["vol_rule_S3"], 3) for h, v in res.items()}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build")
    b.add_argument("--klines", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--limit", type=int, default=0, help="thin the cutoff grid to about this many (smoke tests)")
    b.add_argument("--delay", type=int, default=0, help="enter this many 1m bars AFTER the feature bar (robustness, doc section 4.5)")
    b.add_argument("--holds", default="", help="comma list of holds to build (default: all registered)")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--evidence", required=True)
    r.set_defaults(fn=cmd_run)
    mc = sub.add_parser("mechanism", help="doc 4.6: model-free volatility selector, its S3 and the gross R of its picks")
    mc.add_argument("--out", required=True)
    mc.add_argument("--evidence", required=True)
    mc.set_defaults(fn=cmd_mechanism)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
