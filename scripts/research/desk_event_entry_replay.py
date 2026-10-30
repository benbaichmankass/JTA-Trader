#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-18G-EVENT-ENTRIES and by research/queue/blocked/RQ-20261030-e18g-01 (research-script-run.yml, once the manager releases it); no schedule consumes it.
"""DESK-18G-EVENT-ENTRIES -- do entries triggered by a point-in-time-known CATALYST beat a same-model random entry?

Question (operator 2026-10-30 ~21:40Z, popup answer "Event-driven entries"): the desk (judged-1) equals a random short
(S3 +0.007 R, DESK-18F). A lever must add INFORMATION the 1h price packet cannot see. This arm enters ONLY when an event
fires, with a stated direction rule, and is scored against random entries net of the full cost stack.

Reuses, does not rewrite, the certified instrument: ``desk_gen_replay_driver.simulate`` / ``transplant`` / ``Series`` /
``vol_matched_pool`` / ``eligible_cutoffs`` (market entry at the NEXT bar's open, stop before target in a bar, gap rules,
refusal floor, ``execution_costs.roundtrip_cost_r`` with the venue fee + resolve_cost_policy slippage + funding), and the
event detectors of ``desk_event_calendar_study.build_events`` (C3 funding shock, C4 open-interest shock), re-implemented here
only to key them to the 1h engine. Tier 1 research tooling: reads public Binance Vision files, writes only under --out.

THE ARM (registered in research/queue/blocked/RQ-20261030-e18g-01.yaml before the first score)
  E3  funding-shock fade   a Binance USD-M funding settlement with |z| >= 2 vs the symbol's previous 90 settlements;
                           known_at = fundingTime; side = AGAINST the funding sign (crowded side pays).
  E4  OI-shock continuation 1h change of sumOpenInterest with z >= 3 vs the previous 7 days of 1h changes (5-minute grid,
                           contiguous), at most one per symbol per 6 h; known_at = metrics row time + 5 min; side = the sign
                           of the last CLOSED 1h bar's return at the decision cutoff.
  decision cutoff  = the first 1h boundary at or after known_at (the engine decides at a bar close and enters the NEXT open),
                     so the entry is at least one bar after the event is known. Nothing later than the cutoff is read.
  bracket (one, fixed)  SL 1.5 ATR14, TP 3.0 ATR14 from the cutoff close, time stop 24 bars. The TP is a real distance (R:R 2).

BASELINES (cost-matched by construction: same engine, same costs)
  B3 (decisive)  random cutoffs of the SAME symbol in the SAME window, same ATR%-decile (vol_matched_pool), outside 24 bars of
                 any event of the class, the event row's OWN side and geometry (so short-side drift cancels), 200 draws.
  B1 (diagnostic) the SAME event time with the side averaged over long and short (what the direction rule adds at that time).
  S3 = mean over events of (event net R - B3 mean net R). A refused slot is no-trade = 0 R on both sides.

CONTROLS (RULE ONE: the probe must find a positive)  oracle side (realised forward sign) must clear; anti-oracle must be
negative; random-side must not clear; the event detectors must give identical events on a truncated history (no lookahead).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "ci", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_gen_replay_driver as gr  # noqa: E402  (the certified replay engine; reused, not rewritten)
import desk_event_calendar_study as ecs  # noqa: E402  (fetch helpers: _get, _months, _dir_rows)

UNIT_ID = "RQ-20261030-e18g-01"
RULE_ID = "RULE-RQ20261030-E18G-01-DESK-EVENT-ENTRIES"

# ----------------------------------------------------------------------------- registered numbers (not tunable)
SYMS = gr.REGISTERED_SYMBOLS
S3_BAR = 0.25
N_ARMS = 2                                  # E3, E4 decisive -> Bonferroni: the decisive CI is the 97.5% one
N_MIN = 30                                  # DESK-13 floor on events
SL_ATR, TP_ATR, HORIZON = 1.5, 3.0, 24
GEOM = {"etype": "market", "offset_atr": 0.0, "sl_atr": SL_ATR, "tp_atr": TP_ATR, "good_till": 0, "horizon": HORIZON}
FR_Z, FR_LOOK = 2.0, 90
OI_Z, OI_W, OI_LAG_BARS, OI_COOL_S = 3.0, 2016, 12, 6 * 3600
EXCL_BARS = 24                              # baseline cutoffs stay this far from any event of the class
B_DRAWS = 200
BOOT = 10_000
SEED = 20261030
DEV = (gr.WINDOW_START, gr.WINDOW_END)                                   # 2025-11-01 .. 2026-09-15
HOLDOUT = (datetime(2024, 11, 1, tzinfo=timezone.utc), datetime(2025, 10, 25, tzinfo=timezone.utc))   # run ONLY if DEV clears
BASE = ecs.BASE
FETCH_FROM = {"dev": datetime(2025, 4, 1, tzinfo=timezone.utc), "holdout": datetime(2024, 4, 1, tzinfo=timezone.utc)}
SEC = gr.SEC


# ----------------------------------------------------------------------------- data
def fetch(root: Path, window: str) -> None:
    """Funding (monthly) and open interest (daily metrics, 5-minute) for the six symbols from FETCH_FROM[window]; 1h candles via the driver."""
    import io
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    lo = FETCH_FROM[window]
    end = (DEV if window == "dev" else HOLDOUT)[1] + dt.timedelta(days=3)
    jobs = []
    for s in SYMS:
        for y, m in ecs._months((lo.year, lo.month), (end.year, end.month)):
            jobs.append((f"{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{y}-{m:02d}.zip", root / "fr" / s / f"{y}-{m:02d}.csv"))
        d = (lo + dt.timedelta(days=0)).date() if window == "holdout" else (DEV[0] - dt.timedelta(days=14)).date()
        if window == "holdout":
            d = (HOLDOUT[0] - dt.timedelta(days=14)).date()
        while d <= end.date():
            jobs.append((f"{BASE}/daily/metrics/{s}/{s}-metrics-{d}.zip", root / "oi" / s / f"{d}.csv"))
            d += dt.timedelta(days=1)

    def one(j):
        url, out = j
        if out.exists():
            return 1
        b = ecs._get(url)
        if b is None:
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        z = zipfile.ZipFile(io.BytesIO(b))
        out.write_bytes(z.read(z.namelist()[0]))
        return 1
    with ThreadPoolExecutor(32) as ex:
        ok = sum(ex.map(one, jobs))
    print(f"fetched {ok}/{len(jobs)} event files")
    from scripts.research import desk_replay_driver as d7   # the driver's one Binance Vision route, with days reaching back to FETCH_FROM
    days = int((datetime.now(timezone.utc) - lo).days) + 2
    for s in SYMS:
        d7.fetch_candles(s, gr.SCAN_TF, days, root / "candles" / f"{s}_{gr.SCAN_TF}.csv")


def ceil_hour(k: int) -> int:
    return int(math.ceil(k / SEC) * SEC)


def detect(root: Path, mkt: Dict[str, gr.Series], upto: Optional[int] = None) -> Dict[str, List[dict]]:
    """{'E3': [...], 'E4': [...]} events, each {sym, known, cutoff, side(+1/-1)}. Reads only data stamped <= `upto`
    (default: everything), so the no-lookahead control can truncate the history and compare."""
    out: Dict[str, List[dict]] = {"E3": [], "E4": []}
    for s in SYMS:
        ser = mkt[s]
        fr = sorted((int(r[0]) // 1000, float(r[2])) for r in ecs._dir_rows(root / "fr" / s))
        fr = [x for x in fr if upto is None or x[0] <= upto]
        ft = np.array([x[0] for x in fr])
        fv = np.array([x[1] for x in fr])
        for i in range(FR_LOOK, len(fv)):
            w = fv[i - FR_LOOK:i]
            sd = w.std()
            if sd > 0 and abs(fv[i] - w.mean()) / sd >= FR_Z:
                out["E3"].append({"sym": s, "known": int(ft[i]), "cutoff": ceil_hour(int(ft[i])), "side": -1 if fv[i] > 0 else 1})
        rows = []
        for r in ecs._dir_rows(root / "oi" / s):
            t = dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
            if upto is None or t + 300 <= upto:
                rows.append((t, float(r[2])))
        if not rows:
            continue
        rows.sort()
        t = np.array([r[0] for r in rows])
        oi = np.array([r[1] for r in rows])
        ch = np.zeros(len(oi))
        good = (oi[OI_LAG_BARS:] > 0) & (oi[:-OI_LAG_BARS] > 0)
        ch[OI_LAG_BARS:][good] = oi[OI_LAG_BARS:][good] / oi[:-OI_LAG_BARS][good] - 1
        ok = np.zeros(len(oi), bool)
        ok[OI_LAG_BARS:] = good & ((t[OI_LAG_BARS:] - t[:-OI_LAG_BARS]) == 3600)
        cs, cs2 = np.cumsum(ch), np.cumsum(ch ** 2)
        last = -1e18
        for i in range(OI_W + OI_LAG_BARS, len(oi)):
            if not ok[i] or t[i] - t[i - OI_W] > 7.5 * 86400:
                continue
            m = (cs[i - 1] - cs[i - OI_W - 1]) / OI_W
            v = (cs2[i - 1] - cs2[i - OI_W - 1]) / OI_W - m * m
            if v <= 0:
                continue
            known = t[i] + 300
            if (ch[i] - m) / math.sqrt(v) >= OI_Z and known - last >= OI_COOL_S:
                cut = ceil_hour(int(known))
                j = ser.last_closed(cut)                       # the last CLOSED 1h bar at the decision cutoff
                if j >= 1:
                    pr = ser.c[j] / ser.c[j - 1] - 1
                    if pr != 0:
                        out["E4"].append({"sym": s, "known": int(known), "cutoff": cut, "side": 1 if pr > 0 else -1})
                        last = known
    return out


# ----------------------------------------------------------------------------- scoring
def slot(ser: gr.Series, i: int, side: float) -> Optional[float]:
    """Net R of one market bracket decided at bar i's close; refused = no-trade = 0.0; unresolved/undefined = None (excluded, counted)."""
    t = gr.transplant(ser, i, dict(GEOM, side=float(side)))
    if t is None or t.state == "unresolved":
        return None
    return t.net_r if t.state == "filled" else 0.0


def cluster_mean(vals: List[float], weeks: List[str], alpha: float, seed: int = SEED, draws: int = BOOT) -> Dict[str, Any]:
    """Mean and weekly-cluster bootstrap interval (ISO week is the resampling unit); alpha=0.05 -> 95%, 0.025 -> 97.5%."""
    if not vals:
        return {"n": 0, "mean": None, "ci": [None, None]}
    ws = sorted(set(weeks))
    ix = {w: k for k, w in enumerate(ws)}
    sm, cn = np.zeros(len(ws)), np.zeros(len(ws))
    for v, w in zip(vals, weeks):
        sm[ix[w]] += v
        cn[ix[w]] += 1
    rng = np.random.default_rng(seed)
    b = rng.integers(0, len(ws), size=(draws, len(ws)))
    means = sm[b].sum(axis=1) / cn[b].sum(axis=1)
    return {"n": len(vals), "weeks": len(ws), "mean": float(np.mean(vals)),
            "ci": [float(np.percentile(means, 100 * alpha / 2)), float(np.percentile(means, 100 * (1 - alpha / 2)))]}


def score_class(mkt: Dict[str, gr.Series], events: List[dict], window: Tuple[datetime, datetime], side_of=None,
                seed: int = SEED, draws: int = B_DRAWS) -> Dict[str, Any]:
    """S3 of one event class: event net R minus the B3 mean, plus the B1 diagnostic. `side_of(ev, ser, i)` overrides the side (controls)."""
    lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
    rng = np.random.default_rng(seed)
    pools: Dict[str, np.ndarray] = {}
    ev_idx: Dict[str, List[int]] = {s: [] for s in SYMS}
    rows, excl = [], {"outside_window": 0, "no_bar": 0, "unresolved": 0}
    for ev in sorted(events, key=lambda e: (e["sym"], e["cutoff"])):
        ser = mkt[ev["sym"]]
        if not (lo <= ev["cutoff"] < hi):
            excl["outside_window"] += 1
            continue
        i = ser.last_closed(ev["cutoff"])
        if i < 0 or ser.t[i] + SEC != ev["cutoff"]:
            excl["no_bar"] += 1
            continue
        ev_idx[ev["sym"]].append(i)
        rows.append((ev, ser, i))
    out_rows = []
    for ev, ser, i in rows:
        s_ = ev["sym"]
        if s_ not in pools:
            pools[s_] = gr.eligible_cutoffs(ser, *window)
        side = float(ev["side"]) if side_of is None else float(side_of(ev, ser, i))
        x = slot(ser, i, side)
        if x is None:
            excl["unresolved"] += 1
            continue
        near = np.zeros(len(ser.t), bool)
        for j in ev_idx[s_]:
            near[max(0, j - EXCL_BARS): j + EXCL_BARS + 1] = True
        pool = gr.vol_matched_pool(ser, pools[s_], i, window=window)
        pool = pool[~near[pool]]
        bs = []
        for j in (rng.choice(pool, size=draws, replace=True) if len(pool) else []):
            v = slot(ser, int(j), side)
            if v is not None:
                bs.append(v)
        if not bs:
            excl["unresolved"] += 1
            continue
        both = [slot(ser, i, 1.0), slot(ser, i, -1.0)]
        b1 = float(np.mean([v for v in both if v is not None])) if any(v is not None for v in both) else None
        out_rows.append({"sym": s_, "week": gr.iso_week(ev["cutoff"]), "side": side, "x": x, "b3": float(np.mean(bs)),
                         "b1": b1, "d": x - float(np.mean(bs)), "d_dir": None if b1 is None else x - b1, "cutoff": ev["cutoff"]})
    wk = [r["week"] for r in out_rows]
    d = [r["d"] for r in out_rows]
    res: Dict[str, Any] = {"events_in": len(rows), "n": len(out_rows), "excluded": excl,
                           "n_long": sum(1 for r in out_rows if r["side"] > 0), "n_short": sum(1 for r in out_rows if r["side"] < 0)}
    if not out_rows:
        return res
    res.update({
        "mean_net_r": float(np.mean([r["x"] for r in out_rows])), "mean_b3": float(np.mean([r["b3"] for r in out_rows])),
        "sd_d": float(np.std(d, ddof=1)) if len(d) > 1 else None,
        "S3": cluster_mean(d, wk, 0.025), "S3_ci95": cluster_mean(d, wk, 0.05),
        "S1_net_r": cluster_mean([r["x"] for r in out_rows], wk, 0.05),
        "S3_dir_vs_B1": cluster_mean([r["d_dir"] for r in out_rows if r["d_dir"] is not None],
                                     [r["week"] for r in out_rows if r["d_dir"] is not None], 0.05),
        "per_symbol": {s: {"n": sum(1 for r in out_rows if r["sym"] == s),
                           "S3": float(np.mean([r["d"] for r in out_rows if r["sym"] == s])) if any(r["sym"] == s for r in out_rows) else None}
                       for s in SYMS},
    })
    ci = res["S3"]["ci"]
    res["mde_iid_r"] = None if not res["sd_d"] else float(2.8 * res["sd_d"] / math.sqrt(len(d)))
    res["mde_cluster_r"] = float(2.8 / 2.24 * (ci[1] - ci[0]) / 2)          # 97.5% half-width x (z_.8 + z_.9875)/z_.9875
    res["clears"] = bool(res["n"] >= N_MIN and res["S3"]["mean"] >= S3_BAR and ci[0] > 0)
    res["_rows"] = out_rows
    return res


def run_all(root: Path, window_name: str, out: Path) -> Dict[str, Any]:
    window = DEV if window_name == "dev" else HOLDOUT
    mkt, missing = gr.load_market(root / "candles", list(SYMS))
    if missing:
        raise SystemExit(f"candles missing for {missing}: refusing to score a partial universe")
    ev = detect(root, mkt)
    res: Dict[str, Any] = {"unit": UNIT_ID, "rule": RULE_ID, "window": [w.isoformat() for w in window], "events_detected": {k: len(v) for k, v in ev.items()},
                           "events_in_window": {k: sum(1 for e in v if gr._epoch(window[0]) <= e["cutoff"] < gr._epoch(window[1])) for k, v in ev.items()}}
    arms: Dict[str, Any] = {}
    for cls, evs in ev.items():
        r = score_class(mkt, evs, window)
        arms[cls] = {k: v for k, v in r.items() if k != "_rows"}
        if cls == "E4":
            fwd = lambda e, s, i: _fwd_sign(s, i)                     # noqa: E731  oracle: the realised forward sign (uses the future ON PURPOSE)
            ctl = {"oracle": score_class(mkt, evs, window, side_of=fwd, draws=40),
                   "anti_oracle": score_class(mkt, evs, window, side_of=lambda e, s, i: -_fwd_sign(s, i), draws=40),
                   "random_side": score_class(mkt, evs, window, side_of=lambda e, s, i: 1.0 if (e["known"] // 7) % 2 else -1.0, draws=40)}
            res["controls"] = {k: {"n": v.get("n"), "S3": (v.get("S3") or {}).get("mean"), "ci97.5": (v.get("S3") or {}).get("ci"), "clears": v.get("clears")}
                               for k, v in ctl.items()}
    res["arms"] = arms
    cut = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp())
    full = ecs  # noqa: F841
    pre = detect(root, mkt, upto=cut)
    same = {k: [e for e in ev[k] if e["known"] <= cut] == pre[k] for k in ev}
    res["no_lookahead_prefix_identical"] = same
    verdict = "S3_CLEARED" if any(a.get("clears") for a in arms.values()) else "S3_NOT_CLEARED"
    if not all(same.values()) or (res.get("controls") and not _controls_ok(res["controls"])):
        verdict = "INDETERMINATE_INSTRUMENT"
    res["verdict"] = verdict
    out.mkdir(parents=True, exist_ok=True)
    (out / f"event_entry_result_{window_name}.json").write_text(json.dumps(res, indent=1, default=str))
    return res


CONFIRM_UNIT = "RQ-20261030-e18g-02"
CONFIRM_RULE = "RULE-RQ20261030-E18G-02-DESK-E4-HELDOUT-CONFIRM"


def run_confirm(root: Path, out: Path) -> Dict[str, Any]:
    """The frozen E4 arm on the HOLDOUT window, scored ONCE. detect() and score_class() are the DEV code, unchanged.
    PASS iff n >= N_MIN AND the paired S3 mean vs B3 > 0 AND the 95% weekly-cluster CI lower bound > 0 (the operator's DESK-13 gate:
    out-of-sample edge vs the random-entry baseline, net of the full cost stack). The S3 +0.25 R bar does NOT apply here."""
    window = HOLDOUT
    mkt, missing = gr.load_market(root / "candles", list(SYMS))
    if missing:
        raise SystemExit(f"candles missing for {missing}: refusing to score a partial universe")
    ev = detect(root, mkt)["E4"]
    lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
    r = score_class(mkt, ev, window)
    r.pop("_rows", None)
    s3 = r.get("S3_ci95") or {}
    ci = s3.get("ci") or [None, None]
    n = r.get("n", 0)
    verdict = "NO_DATA" if not n else ("PASS" if n >= N_MIN and s3["mean"] > 0 and ci[0] > 0 else "FAIL")
    res = {"unit": CONFIRM_UNIT, "rule": CONFIRM_RULE, "window": [w.isoformat() for w in window], "events_in_window": sum(1 for e in ev if lo <= e["cutoff"] < hi),
           "arm": "E4 frozen", "result": r, "verdict": verdict, "first_event": min((e["cutoff"] for e in ev if lo <= e["cutoff"] < hi), default=None)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "event_entry_confirm_holdout.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def _fwd_sign(ser: gr.Series, i: int) -> float:
    k = i + 1
    j = min(k + HORIZON - 1, len(ser.c) - 1)
    return 1.0 if ser.c[j] >= ser.o[k] else -1.0


def _controls_ok(c: Dict[str, Any]) -> bool:
    return bool(c["oracle"]["clears"]) and (c["anti_oracle"]["S3"] or 0) < 0 and not c["random_side"]["clears"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("fetch", "run", "confirm"))
    ap.add_argument("--root", required=True, help="cache dir for fetched event files and candles")
    ap.add_argument("--out", default=None)
    ap.add_argument("--window", choices=("dev", "holdout"), default="dev")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.mode == "fetch":
        fetch(root, a.window)
        return 0
    if a.mode == "confirm":
        res = run_confirm(root, Path(a.out or root / "out"))
        print(json.dumps({k: res[k] for k in ("window", "events_in_window", "verdict")}, indent=1))
        print(json.dumps({x: res["result"].get(x) for x in ("n", "n_long", "n_short", "mean_net_r", "mean_b3", "S3_ci95", "S3", "S3_dir_vs_B1", "mde_iid_r", "mde_cluster_r", "excluded")}, default=str))
        return 0
    res = run_all(root, a.window, Path(a.out or root / "out"))
    print(json.dumps({k: res[k] for k in ("window", "events_detected", "events_in_window", "verdict", "no_lookahead_prefix_identical")}, indent=1))
    for k, v in res["arms"].items():
        print(k, json.dumps({x: v.get(x) for x in ("n", "n_long", "n_short", "mean_net_r", "mean_b3", "S3", "S3_ci95", "S3_dir_vs_B1", "mde_iid_r", "mde_cluster_r", "clears")}, default=str))
    print("controls", json.dumps(res.get("controls"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
