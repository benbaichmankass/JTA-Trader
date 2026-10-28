#!/usr/bin/env python3
# wiring: manual-only - run by the DESK-EDGE-PROGRAM lane (and its re-run); no schedule consumes it.
"""DESK-EDGE-PROGRAM part 1 -- the INFORMATION CEILING: can ANY fitted model pick desk entries that beat the
random-geometry baseline (S3 > 0) from what a scan packet contains? Token-free (no LLM, no API).

Design and the PRE-REGISTERED verdict rule: docs/research/desk-edge-program-2026-10-27.md section 3. The rule
constants below are that section, verbatim in code; they were committed before the first run.

WHAT IT REUSES (never re-implements): scripts/research/desk_gen_replay_driver.py -- the masked packet builder
(build_masked_packet, the one the judge saw), the replay engine (transplant -> simulate, full cost stack), the
random-entry baseline (random_baseline over the same symbol, same fold, the action's own geometry), the folds
(fold_of), the ISO week, and the weekly-cluster statistics (cluster_stats: S1 mean net R, S2 per capital-day,
S3 paired difference vs random). A row handed to cluster_stats is {week, net_r, days, diff}, exactly as the
driver's score() builds it, so S3 here IS the e535 S3.

THE ACTION SET. At every cutoff of a dense 2-hour grid over the driver's window (2025-11-01 .. 2026-09-15, the
judged-1 window; every judged-1 cutoff is added so the judge and the models are compared on the same packets),
each of the six symbols x {long, short} x GEOMETRIES (market entries; the driver's six registered reference
geometries plus GJ, judged-1's median bracket) is one action. Its label is the driver's S3 term for that action:
y = net_r(transplant) - mean net_r of the same geometry at random cutoffs of the same symbol and fold.

TWO FEATURE TIERS
  P   PACKET ONLY: fields of the masked packet the judge saw (per-symbol atr %, htf_trend, swing distances,
      session; the 36 base-rate rows; cross-sectional summaries of those), plus the action's side and geometry.
  P+  P plus information the packet does NOT carry, every value at or before the cutoff: multi-horizon returns,
      range position, volatility state, volume and taker-buy flow (Binance Vision USD-M perp klines), cross-asset (BTC and
      the six-symbol cross-section), calendar, symbol identity, and point-in-time perp funding (Binance Vision
      USD-M fundingRate). Feature groups are ablated one at a time, so a P+ win names WHICH information.

  build  --out DIR --candles DIR [--funding DIR] [--workers N] [--era]   packets -> features + labels (cached)
  run    --out DIR --evidence DIR                                 walk-forward learners, controls, verdict
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402

# ----------------------------------------------------------------------------- registered design (doc section 3)
GRID_STEP_H = 2                                     # dense cutoff grid inside the driver's window
GEOMETRIES = tuple((name, sl, tp_r, h) for name, sl, tp_r, h in d.REFERENCE_GEOMETRIES) + (("GJ", 1.25, 2.0, 48),)
BASELINE_DRAWS = 2000                               # random entries per (symbol, fold, side, geometry) cell
SEED = 20261027
TEST_FOLDS = (2, 3, 4)                              # walk-forward: train on folds < k, test fold k
EMBARGO_H = 96                                      # longest horizon: no training label may overlap the test fold
TAKE_FRAC = 0.34                                    # desk-like policy: act on the top 34% of cutoffs (judged-1: 506/1498)
MAX_PER_CUTOFF = 2                                  # judged-1's cap, distinct symbols
USEFUL_S3 = 0.10                                    # an S3 below +0.10 R is not a useful edge (doc section 3)
N_CONFIGS = 6                                       # 3 learners x 2 tiers: the Bonferroni family
ALPHA = 0.05
FOLDS_POSITIVE_NEEDED = 2                           # of the 3 test folds
SIDES = (("long", 1.0), ("short", -1.0))
HORIZONS = (4, 12, 48)
SESSIONS = ("asia", "europe", "us", "late_us")
TRENDS = ("chop", "transitional", "trending")
RET_K = (1, 4, 12, 24, 72, 168, 336)

# ----------------------------------------------------------------------------- the EXTENDED-ERA run (doc section 4.2)
# Registered after the DEV-window run showed its resolution limit (about 33 out-of-sample weeks) and BEFORE this run.
# Six half-year folds before the program's FULL-RUN window (which starts 2023-11-01; desk_edge_devloop.FULL_RUN) plus
# the driver's four DEV folds; the HOLDOUT and FULL-RUN windows are never read as cutoffs.
ERA_BOUNDS = (datetime(2021, 1, 15, tzinfo=timezone.utc), datetime(2021, 7, 1, tzinfo=timezone.utc),
              datetime(2022, 1, 1, tzinfo=timezone.utc), datetime(2022, 7, 1, tzinfo=timezone.utc),
              datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2023, 7, 1, tzinfo=timezone.utc),
              datetime(2023, 10, 25, tzinfo=timezone.utc))
ERA_GRID_STEP_H = 4
ERA_DEV_FOLD_OFFSET = 6                              # DEV fold k is era fold k + 6
ERA_TEST_FOLDS = (3, 4, 5, 6, 7, 8, 9, 10)
ERA_N_CONFIGS = 12                                   # both ceiling runs' configurations: the family for this run
ERA_FOLDS_POSITIVE_NEEDED = 5                        # of the 8 test folds (the DEV run's 2 of 3, scaled)
# Holding period is a lever (operator popup 2026-10-27 ~16:10Z): the live claude_desk leg holds <= 60 minutes, so the era
# run adds 1h-bar holds of ONE bar (<= 60 min on the 1h grid) and a 4-bar hold beside the 12..96-bar ones.
SHORT_GEOMETRIES = (("H1a", 0.5, 1.0, 1), ("H1b", 1.0, 1.0, 1), ("H4", 0.75, 1.5, 4))
ERA_GEOMETRIES = GEOMETRIES + SHORT_GEOMETRIES


def era_fold(cutoff: int) -> int:
    for k in range(len(ERA_BOUNDS) - 1):
        if d._epoch(ERA_BOUNDS[k]) <= cutoff < d._epoch(ERA_BOUNDS[k + 1]):
            return k + 1
    if d._epoch(d.WINDOW_START) <= cutoff < d._epoch(d.WINDOW_END):
        return d.fold_of(cutoff) + ERA_DEV_FOLD_OFFSET
    raise ValueError(f"cutoff {cutoff} is outside the era folds (the holdout and full-run windows are never read)")


def era_fold_window(fold: int) -> Tuple[datetime, datetime]:
    """The window a fold's random-entry pool is drawn from (the fold itself)."""
    if fold <= len(ERA_BOUNDS) - 1:
        return ERA_BOUNDS[fold - 1], ERA_BOUNDS[fold]
    s0, e0 = d._epoch(d.WINDOW_START), d._epoch(d.WINDOW_END)
    k = fold - ERA_DEV_FOLD_OFFSET
    lo = s0 + (e0 - s0) * (k - 1) / d.N_FOLDS
    hi = s0 + (e0 - s0) * k / d.N_FOLDS
    return datetime.fromtimestamp(math.ceil(lo), tz=timezone.utc), datetime.fromtimestamp(math.ceil(hi), tz=timezone.utc)


def era_cutoffs() -> List[int]:
    out = list(range(d._epoch(ERA_BOUNDS[0]), d._epoch(ERA_BOUNDS[-1]), ERA_GRID_STEP_H * d.SEC))
    return out + list(range(d._epoch(d.WINDOW_START), d._epoch(d.WINDOW_END), ERA_GRID_STEP_H * d.SEC))


# ----------------------------------------------------------------------------- cutoffs
def grid_cutoffs(start: datetime = d.WINDOW_START, end: datetime = d.WINDOW_END, step_h: int = GRID_STEP_H) -> List[int]:
    return list(range(d._epoch(start), d._epoch(end), step_h * d.SEC))


def judged1_cutoffs(mask_key: Path) -> Dict[int, str]:
    """{cutoff_epoch: packet_id} of the judged-1 packets."""
    return {int(k["cutoff_epoch"]): k["packet_id"] for k in json.loads(mask_key.read_text())["keys"]}


# ----------------------------------------------------------------------------- packet features (tier P)
def packet_features(m: dict, key: dict) -> Dict[str, Dict[str, Any]]:
    """{real_symbol: raw packet fields} from one masked packet and its key. Only what the judge saw."""
    hist = {(h["symbol"], h["side"], h["horizon_bars"]): h for h in m["history"]["rows"]}
    out: Dict[str, Dict[str, Any]] = {}
    for u in m["universe"]:
        a = u["symbol"]
        sw = u.get("swing") or {}
        f: Dict[str, Any] = {"atr_pct": u.get("atr"), "htf_trend": u.get("htf_trend"), "session": u.get("session"),
                             "dist_high_atr": sw.get("dist_high_atr"), "dist_low_atr": sw.get("dist_low_atr")}
        for side, _ in SIDES:
            for h in HORIZONS:
                r = hist.get((a, side, h)) or {}
                for st in ("mean_r", "sd_r", "p10_r", "p50_r", "p90_r", "mean_cost_r"):
                    f[f"br_{side}_h{h}_{st}"] = r.get(st)
        out[key["alias"][a]] = f
    return out


def _num(x: Any) -> float:
    return float(x) if x is not None and np.isfinite(float(x)) else float("nan")


def p_action_features(pf: Dict[str, Dict[str, Any]], sym: str, side: str) -> Dict[str, float]:
    """Tier-P features of one (symbol, side) action, side-signed where the field has a direction."""
    f = pf[sym]
    sg = 1.0 if side == "long" else -1.0
    opp = "short" if side == "long" else "long"
    o: Dict[str, float] = {"side_long": 1.0 if side == "long" else 0.0, "atr_pct": _num(f["atr_pct"])}
    for t in TRENDS:
        o[f"htf_{t}"] = 1.0 if f["htf_trend"] == t else 0.0
    for s in SESSIONS:
        o[f"sess_{s}"] = 1.0 if f["session"] == s else 0.0
    dh, dl = _num(f["dist_high_atr"]), _num(f["dist_low_atr"])
    o["room_atr"] = dh if sg > 0 else dl                 # distance to the swing in the trade's direction
    o["behind_atr"] = dl if sg > 0 else dh
    for h in HORIZONS:
        for st in ("mean_r", "sd_r", "p10_r", "p50_r", "p90_r"):
            o[f"br_h{h}_{st}"] = _num(f[f"br_{side}_h{h}_{st}"])
        o[f"br_opp_h{h}_mean_r"] = _num(f[f"br_{opp}_h{h}_mean_r"])
    o["br_h48_cost"] = _num(f[f"br_{side}_h48_mean_cost_r"])
    xs = np.array([_num(pf[s][f"br_{side}_h48_mean_r"]) for s in pf])
    own = o["br_h48_mean_r"]
    o["xs_br_h48_mean"] = float(np.nanmean(xs)) if np.isfinite(xs).any() else float("nan")
    o["xs_br_h48_rel"] = own - o["xs_br_h48_mean"]
    o["xs_br_h48_rank"] = float((xs < own).sum()) / max(1, len(xs) - 1) if np.isfinite(own) else float("nan")
    o["xs_n_trending"] = float(sum(1 for s in pf if pf[s]["htf_trend"] == "trending"))
    atrs = np.array([_num(pf[s]["atr_pct"]) for s in pf])
    o["xs_atr_rel"] = o["atr_pct"] / float(np.nanmean(atrs)) if np.isfinite(atrs).any() else float("nan")
    return o


# ----------------------------------------------------------------------------- extra information (tier P+)
class Extra:
    """Candle-, volume-, flow- and funding-derived values at a cutoff bar, point in time (index <= i)."""

    def __init__(self, mkt: Dict[str, d.Series], raw: Dict[str, Dict[str, np.ndarray]], funding: Dict[str, Tuple[np.ndarray, np.ndarray]]):
        self.mkt, self.raw, self.funding = mkt, raw, funding

    def sym(self, sym: str, i: int) -> Dict[str, float]:
        s = self.mkt[sym]
        a = float(s.atr[i]) if np.isfinite(s.atr[i]) and s.atr[i] > 0 else float("nan")
        o: Dict[str, float] = {}
        for k in RET_K:
            o[f"ret{k}"] = float((s.c[i] - s.c[i - k]) / a) if i >= k else float("nan")
        for n in (24, 168, 720):
            lo, hi = float(s.l[max(0, i - n + 1): i + 1].min()), float(s.h[max(0, i - n + 1): i + 1].max())
            o[f"rpos{n}"] = (float(s.c[i]) - lo) / (hi - lo) if hi > lo else float("nan")
        r = s.atr[max(0, i - 720): i + 1] / s.c[max(0, i - 720): i + 1]
        r = r[np.isfinite(r)]
        o["vol_pct720"] = float((r < r[-1]).mean()) if len(r) > 100 else float("nan")
        o["atr_ratio168"] = float(s.atr[i] / s.atr[i - 168]) if i >= 168 and s.atr[i - 168] > 0 else float("nan")
        rw = self.raw.get(sym)
        if rw is not None:
            j = int(np.searchsorted(rw["t"], int(s.t[i]), side="right")) - 1
            if j >= 720 and rw["t"][j] == s.t[i]:
                v, tb = rw["v"], rw["tb"]
                v24 = v[j - 23: j + 1].sum()
                base = np.array([v[q - 23: q + 1].sum() for q in range(j - 720, j + 1, 24)])
                o["vol24_z"] = float(math.log(v24 / base.mean())) if v24 > 0 and base.mean() > 0 else float("nan")
                for n in (1, 4, 24):
                    vv = v[j - n + 1: j + 1].sum()
                    o[f"taker_buy{n}"] = float(tb[j - n + 1: j + 1].sum() / vv - 0.5) if vv > 0 else float("nan")
        fu = self.funding.get(sym)
        if fu is not None:
            ft, fr = fu
            close = int(s.t[i]) + d.SEC
            j = int(np.searchsorted(ft, close, side="right")) - 1   # last settlement at or before the cutoff
            o["funding_last"] = float(fr[j]) * 1e4 if j >= 0 else float("nan")
            o["funding_3d"] = float(fr[max(0, j - 8): j + 1].mean()) * 1e4 if j >= 8 else float("nan")
        return o


SIGNED_EXTRA = tuple(f"ret{k}" for k in RET_K) + ("taker_buy1", "taker_buy4", "taker_buy24", "funding_last", "funding_3d")
EXTRA_GROUPS = {
    "returns": tuple(f"ret{k}" for k in RET_K) + ("xs_ret24_rank", "xs_ret168_rank", "mkt_ret24"),
    "range": ("rpos24", "rpos168", "rpos720", "rpos24_s", "rpos168_s", "rpos720_s"),
    "volatility": ("vol_pct720", "atr_ratio168"),
    "volume_flow": ("vol24_z", "taker_buy1", "taker_buy4", "taker_buy24"),
    "cross_asset_btc": ("btc_ret4", "btc_ret24", "btc_ret168"),
    "calendar": ("hour_sin", "hour_cos", "dow"),
    "symbol": tuple(f"sym_{s}" for s in d.REGISTERED_SYMBOLS),
    "funding": ("funding_last", "funding_3d"),
}


def pplus_action_features(ex: Dict[str, Dict[str, float]], sym: str, side: str, cutoff: int) -> Dict[str, float]:
    sg = 1.0 if side == "long" else -1.0
    e = ex[sym]
    o: Dict[str, float] = {}
    for k, v in e.items():
        o[k] = sg * v if k in SIGNED_EXTRA else v
    for n in (24, 168, 720):
        o[f"rpos{n}_s"] = sg * (e.get(f"rpos{n}", float("nan")) - 0.5)
    for k in ("ret4", "ret24", "ret168"):
        o[f"btc_{k}"] = sg * ex["BTCUSDT"].get(k, float("nan")) if "BTCUSDT" in ex else float("nan")
    for k in ("ret24", "ret168"):
        xs = np.array([sg * ex[s].get(k, float("nan")) for s in ex])
        own = sg * e.get(k, float("nan"))
        o[f"xs_{k}_rank"] = float((xs < own).sum()) / max(1, len(xs) - 1) if np.isfinite(own) else float("nan")
    o["mkt_ret24"] = float(np.nanmean([sg * ex[s].get("ret24", float("nan")) for s in ex]))
    dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
    o["hour_sin"], o["hour_cos"], o["dow"] = math.sin(2 * math.pi * dt.hour / 24), math.cos(2 * math.pi * dt.hour / 24), float(dt.weekday())
    for s in d.REGISTERED_SYMBOLS:
        o[f"sym_{s}"] = 1.0 if s == sym else 0.0
    for k in ("vol24_z", "taker_buy1", "taker_buy4", "taker_buy24", "funding_last", "funding_3d"):
        o.setdefault(k, float("nan"))
    return o


# ----------------------------------------------------------------------------- data loading
def load_raw_volume(candles: Path, symbols: Sequence[str]) -> Dict[str, Dict[str, np.ndarray]]:
    """Volume and taker-buy base volume from the Binance Vision raw CSV the driver's fetch writes beside the candles."""
    import pandas as pd
    out = {}
    for s in symbols:
        p = candles / f"{s}_1h.raw.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if not {"volume", "taker_buy_base"} <= set(df.columns):
            continue
        ts = pd.to_datetime(df["timestamp"], utc=True)
        t = np.array([int(x.timestamp()) for x in ts], dtype=np.int64)     # unit-safe across pandas versions
        out[s] = {"t": t, "v": df["volume"].to_numpy(float), "tb": df["taker_buy_base"].to_numpy(float)}
    return out


FUNDING_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{ym}.zip"


def fetch_funding(dest: Path, symbols: Sequence[str], since: datetime, until: datetime) -> None:
    """Binance Vision USD-M monthly funding-rate files -> one CSV per symbol (calc_time ms, rate)."""
    dest.mkdir(parents=True, exist_ok=True)
    for s in symbols:
        rows: List[str] = []
        y, mth = since.year, since.month
        while (y, mth) <= (until.year, until.month):
            ym = f"{y}-{mth:02d}"
            try:
                with urllib.request.urlopen(FUNDING_URL.format(s=s, ym=ym), timeout=60) as r:
                    z = zipfile.ZipFile(io.BytesIO(r.read()))
                txt = z.read(z.namelist()[0]).decode()
                rows += [ln for ln in txt.splitlines()[1:] if ln.strip()] if txt.startswith("calc_time") else [ln for ln in txt.splitlines() if ln.strip()]
            except Exception as e:  # allow-silent: a missing month is reported by the coverage line below
                print(f"  funding {s} {ym}: {e}")
            y, mth = (y + 1, 1) if mth == 12 else (y, mth + 1)
        (dest / f"{s}_funding.csv").write_text("calc_time,interval,rate\n" + "\n".join(rows) + "\n")
        print(f"  funding {s}: {len(rows)} settlements")


def load_funding(src: Optional[Path], symbols: Sequence[str]) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    out = {}
    if src is None:
        return out
    for s in symbols:
        p = src / f"{s}_funding.csv"
        if not p.exists():
            continue
        t, r = [], []
        for ln in p.read_text().splitlines()[1:]:
            parts = ln.split(",")
            if len(parts) >= 3:
                t.append(int(parts[0]) // 1000)
                r.append(float(parts[2]))
        o = np.argsort(t)
        out[s] = (np.array(t)[o], np.array(r)[o])
    return out


# ----------------------------------------------------------------------------- build (packets -> actions)
_G: Dict[str, Any] = {}


def _one_cutoff(args: Tuple[int, int, int]) -> Optional[dict]:
    ce, k, seed = args
    mkt, classes = _G["mkt"], _G["classes"]
    try:
        m, key = d.build_masked_packet(mkt, classes, ce, k, seed)
    except AssertionError as e:
        return {"cutoff": ce, "error": str(e)[:200]}
    pf = packet_features(m, key)
    ex = {s: _G["extra"].sym(s, mkt[s].last_closed(ce)) for s in mkt}
    return {"cutoff": ce, "fold": _G.get("fold_fn", d.fold_of)(ce), "packet_id": m["meta"]["packet_id"], "pf": pf, "ex": ex}


def label_actions(mkt: Dict[str, d.Series], cutoffs: List[dict], rng_seed: int = SEED, fold_window=None,
                  geometries: Sequence[tuple] = GEOMETRIES) -> List[dict]:
    """One row per (cutoff, symbol, side, geometry) that FILLS, with the driver's S3 term as `y`. The random-entry pool
    is the driver's fold (default) or, with `fold_window`, every eligible cutoff of that fold's window."""
    rng = np.random.default_rng(rng_seed)
    base: Dict[Tuple, Optional[float]] = {}
    rows: List[dict] = []
    for c in cutoffs:
        ce, fold = c["cutoff"], c["fold"]
        for sym, s in mkt.items():
            i = s.last_closed(ce)
            for side, sg in SIDES:
                for gname, sl, tp_r, h in geometries:
                    g = {"side": sg, "etype": "market", "offset_atr": 0.0, "sl_atr": sl, "tp_atr": sl * tp_r, "good_till": 1, "horizon": h}
                    t = d.transplant(s, i, g)
                    if t is None or t.state != "filled":
                        continue
                    bk = (sym, fold, side, gname)
                    if bk not in base:
                        pool = (d.eligible_cutoffs(s, d.WINDOW_START, d.WINDOW_END, fold) if fold_window is None
                                else d.eligible_cutoffs(s, *fold_window(fold)))
                        br = d.random_baseline(s, g, pool, rng, BASELINE_DRAWS)
                        base[bk] = br["mean"]
                    if base[bk] is None:
                        continue
                    rows.append({"cutoff": ce, "fold": fold, "week": d.iso_week(ce), "symbol": sym, "side": side, "geom": gname,
                                 "g_sl": sl, "g_tp_r": tp_r, "g_h": float(h), "net_r": t.net_r, "days": t.days,
                                 "y": t.net_r - base[bk], "b_r": base[bk], "cost_r": t.cost_r,
                                 "atr_pct": float(s.atr[i] / s.c[i])})
    return rows


def cmd_build(a: argparse.Namespace) -> int:
    import multiprocessing as mp
    import pickle
    uni, _ = d.parse_universe()
    syms = [u["symbol"] for u in uni]
    mkt, missing = d.load_market(Path(a.candles), syms)
    if missing:
        raise SystemExit(f"candles missing {missing}")
    fdir = Path(a.funding) if a.funding else None
    if fdir is not None and a.fetch_funding:
        fetch_funding(fdir, syms, datetime(2025, 4, 1, tzinfo=timezone.utc), d.WINDOW_END)
    _G.update(mkt=mkt, classes={u["symbol"]: u["classes"] for u in uni},
              extra=Extra(mkt, load_raw_volume(Path(a.candles), syms), load_funding(fdir, syms)))
    j1 = judged1_cutoffs(Path(a.mask_key))
    j1_keys = {int(k["cutoff_epoch"]): k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    grid = set(era_cutoffs() if a.era else grid_cutoffs())
    if a.era:
        from scripts.research.desk_edge_devloop import assert_not_locked
        assert_not_locked(sorted(grid))            # the holdout and full-run windows are never read
        _G["fold_fn"] = era_fold
    # judged-1 cutoffs are rebuilt with THEIR index and seed so the packet is byte-identical (packet_sha asserted)
    jobs = [(ce, int(j1_keys[ce]["index"]), d.SEED) for ce in sorted(j1)]
    jobs += [(ce, 100000 + n, SEED) for n, ce in enumerate(sorted(grid - set(j1)))]
    if a.limit:
        jobs = jobs[: a.limit]
    with mp.get_context("fork").Pool(a.workers) as pool:
        res = [r for r in pool.imap_unordered(_one_cutoff, jobs, chunksize=8) if r is not None]
    errs = [r for r in res if "error" in r]
    res = sorted([r for r in res if "error" not in r], key=lambda r: r["cutoff"])
    for r in res:
        if r["cutoff"] in j1 and r["packet_id"] != j1[r["cutoff"]]:
            raise SystemExit(f"judged-1 packet drift at {r['cutoff']}: {r['packet_id']} != {j1[r['cutoff']]}")
        r["judged1"] = r["cutoff"] in j1
    acts = label_actions(mkt, res, fold_window=era_fold_window if a.era else None,
                         geometries=ERA_GEOMETRIES if a.era else GEOMETRIES)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"mode": "era" if a.era else "dev", "test_folds": list(ERA_TEST_FOLDS if a.era else TEST_FOLDS),
            "n_configs": ERA_N_CONFIGS if a.era else N_CONFIGS}
    (out / "meta.json").write_text(json.dumps(meta) + "\n")
    (out / "cutoffs.pkl").write_bytes(pickle.dumps(res))
    (out / "actions.pkl").write_bytes(pickle.dumps(acts))
    print(json.dumps({"cutoffs": len(res), "judged1_cutoffs": sum(r["judged1"] for r in res), "packet_errors": len(errs),
                      "actions_filled": len(acts), "funding_symbols": sorted(_G["extra"].funding), "volume_symbols": sorted(_G["extra"].raw)}))
    return 0


# ----------------------------------------------------------------------------- matrices
def feature_rows(cutoffs: List[dict], acts: List[dict], tier: str) -> Tuple[np.ndarray, List[str]]:
    by = {c["cutoff"]: c for c in cutoffs}
    cache: Dict[Tuple, Dict[str, float]] = {}
    feats: List[Dict[str, float]] = []
    for r in acts:
        ck = (r["cutoff"], r["symbol"], r["side"])
        if ck not in cache:
            c = by[r["cutoff"]]
            f = p_action_features(c["pf"], r["symbol"], r["side"])
            if tier == "P+":
                f.update(pplus_action_features(c["ex"], r["symbol"], r["side"], r["cutoff"]))
            cache[ck] = f
        feats.append(dict(cache[ck], g_sl=r["g_sl"], g_tp_r=r["g_tp_r"], g_h=r["g_h"]))
    names = sorted({k for f in feats for k in f})
    X = np.array([[f.get(k, float("nan")) for k in names] for f in feats], dtype=float)
    return X, names


def _impute(Xtr: np.ndarray, Xte: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    a, b = Xtr.copy(), Xte.copy()
    for X in (a, b):
        ii = np.where(~np.isfinite(X))
        X[ii] = med[ii[1]]
    mu, sd = a.mean(axis=0), a.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    return (a - mu) / sd, (b - mu) / sd


# ----------------------------------------------------------------------------- learners
def fit_predict(learner: str, Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, seed: int = SEED) -> np.ndarray:
    if learner == "ridge":
        from sklearn.linear_model import Ridge
        A, B = _impute(Xtr, Xte)
        return Ridge(alpha=100.0).fit(A, ytr).predict(B)
    if learner == "logit":
        from sklearn.linear_model import LogisticRegression
        A, B = _impute(Xtr, Xte)
        return LogisticRegression(C=0.05, max_iter=2000).fit(A, (ytr > 0).astype(int)).predict_proba(B)[:, 1]
    if learner == "gbdt":
        import lightgbm as lgb
        m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=400, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, random_state=seed, verbose=-1)
        return m.fit(Xtr, ytr).predict(Xte)
    raise ValueError(learner)


# ----------------------------------------------------------------------------- selection and scoring
def policy_picks(rows: List[dict], pred: np.ndarray, take_frac: float = TAKE_FRAC, cap: int = MAX_PER_CUTOFF) -> List[int]:
    """The desk-like policy on one test population: per cutoff, the best action per symbol, the top `cap` symbols;
    act on the `take_frac` of cutoffs whose best predicted value is highest. Ranks predictions only (no label)."""
    best: Dict[int, List[Tuple[float, int]]] = {}
    for j, r in enumerate(rows):
        best.setdefault(r["cutoff"], []).append((float(pred[j]), j))
    chosen_by_cut: Dict[int, List[int]] = {}
    top_val: Dict[int, float] = {}
    for ce, lst in best.items():
        lst.sort(reverse=True)
        seen, pick = set(), []
        for v, j in lst:
            if rows[j]["symbol"] in seen:
                continue
            seen.add(rows[j]["symbol"])
            pick.append(j)
            if len(pick) >= cap:
                break
        chosen_by_cut[ce] = pick
        top_val[ce] = lst[0][0]
    order = sorted(top_val, key=lambda c: -top_val[c])
    keep = order[: max(1, int(round(take_frac * len(order))))]
    return [j for ce in keep for j in chosen_by_cut[ce]]


def s_rows(rows: List[dict], idx: Sequence[int]) -> List[dict]:
    """Rows in the shape the driver's cluster_stats takes: {week, net_r, days, diff}."""
    return [{"week": rows[j]["week"], "net_r": rows[j]["net_r"], "days": rows[j]["days"], "diff": rows[j]["y"]} for j in idx]


def cluster_ci(rows: List[dict], field: str, alpha: float, seed: int = SEED, draws: int = 10_000) -> Tuple[float, float]:
    """The driver's weekly-cluster resampling (d._week_arrays) at a family-corrected level. Same estimator as
    cluster_stats' S3, only the percentile moves (two-sided alpha)."""
    if not rows:
        return (float("nan"), float("nan"))
    a = d._week_arrays(rows, (field,))
    w = len(a["_n"])
    idx = np.random.default_rng(seed).integers(0, w, size=(draws, w))
    b = a[field][idx].sum(axis=1) / a["_n"][idx].sum(axis=1)
    return float(np.percentile(b, 100 * alpha / 2)), float(np.percentile(b, 100 * (1 - alpha / 2)))


def weekly_ic(rows: List[dict], pred: np.ndarray) -> List[dict]:
    """Per-week Spearman rank correlation of prediction vs y over all test actions of that week."""
    from scipy.stats import spearmanr
    wk: Dict[str, List[int]] = {}
    for j, r in enumerate(rows):
        wk.setdefault(r["week"], []).append(j)
    out = []
    for w, ix in sorted(wk.items()):
        if len(ix) < 50:
            continue
        ys = np.array([rows[j]["y"] for j in ix])
        rho = spearmanr(pred[ix], ys).statistic
        if np.isfinite(rho):
            out.append({"week": w, "ic": float(rho)})
    return out


def ic_summary(ics: List[dict], alpha: float, seed: int = SEED) -> Dict[str, Any]:
    if not ics:
        return {"weeks": 0}
    v = np.array([x["ic"] for x in ics])
    b = np.random.default_rng(seed).choice(v, size=(10_000, len(v)), replace=True).mean(axis=1)
    return {"weeks": len(v), "mean_ic": float(v.mean()), "ci_corrected": [float(np.percentile(b, 100 * alpha / 2)),
                                                                            float(np.percentile(b, 100 * (1 - alpha / 2)))]}


def evaluate(rows: List[dict], pred: np.ndarray, alpha: float) -> Dict[str, Any]:
    picks = policy_picks(rows, pred)
    sr = s_rows(rows, picks)
    st = d.cluster_stats(sr) if sr else {"n": 0}
    out = {k: st.get(k) for k in ("n", "weeks", "mean_net_r", "mean_ci95", "net_r_per_capital_day", "paired_diff_vs_random", "paired_diff_ci95")}
    out["S3_ci_corrected"] = list(cluster_ci(sr, "diff", alpha)) if sr else None
    if picks and all("atr_pct" in r for r in rows):
        # DESK-S3-VOL-MATCHED-BASELINE companions (never read by a rule): gross_excess, S3_matched; see desk_vm_baseline
        from scripts.research import desk_vm_baseline as vm
        out["companions"] = vm.companions(vm.annotate(rows, lambda r: r["atr_pct"]), picks, d.cluster_stats)
    out["long_share"] = float(np.mean([rows[j]["side"] == "long" for j in picks])) if picks else None
    out["geoms"] = {g: sum(1 for j in picks if rows[j]["geom"] == g) for g in sorted({rows[j]["geom"] for j in picks})}
    return out


# ----------------------------------------------------------------------------- the walk-forward ceiling
def walk_forward(acts: List[dict], X: np.ndarray, learner: str, label_noise: Optional[str] = None,
                 extra_col: Optional[np.ndarray] = None, seed: int = SEED) -> np.ndarray:
    """Out-of-sample predictions for every action in TEST_FOLDS (NaN elsewhere). Train on folds < k, minus an
    EMBARGO_H embargo before fold k's first cutoff. `label_noise='shuffle'` permutes training labels within each
    week (the null control); `extra_col` is appended (the planted positive control)."""
    if extra_col is not None:
        X = np.column_stack([X, extra_col])
    y = np.array([r["y"] for r in acts])
    fold = np.array([r["fold"] for r in acts])
    cut = np.array([r["cutoff"] for r in acts])
    pred = np.full(len(acts), np.nan)
    rng = np.random.default_rng(seed)
    for k in TEST_FOLDS:
        te = fold == k
        if not te.any():
            continue
        start_k = cut[te].min()
        tr = (fold < k) & (cut + EMBARGO_H * d.SEC < start_k)
        ytr = y[tr].copy()
        if label_noise == "shuffle":
            wk = np.array([acts[j]["week"] for j in np.nonzero(tr)[0]])
            for w in np.unique(wk):
                ii = np.nonzero(wk == w)[0]
                ytr[ii] = ytr[rng.permutation(ii)]
        pred[te] = fit_predict(learner, X[tr], ytr, X[te], seed)
    return pred


def verdict_for(evals: Dict[str, Dict[str, Any]], ics: Dict[str, Dict[str, Any]], folds: Dict[str, Dict[str, float]]) -> Tuple[str, List[str]]:
    """The registered tier verdict (doc section 3), over that tier's learners."""
    present = [lr for lr, e in evals.items()
               if e.get("paired_diff_vs_random") is not None and e["paired_diff_vs_random"] > 0
               and e["S3_ci_corrected"] and e["S3_ci_corrected"][0] > 0
               and ics[lr].get("ci_corrected") and ics[lr]["ci_corrected"][0] > 0
               and sum(1 for v in folds[lr].values() if v is not None and v > 0) >= FOLDS_POSITIVE_NEEDED]
    if present:
        return "present", [f"{lr}: S3 {evals[lr]['paired_diff_vs_random']:+.3f}, corrected CI {evals[lr]['S3_ci_corrected']}" for lr in present]
    if all(e["S3_ci_corrected"] and e["S3_ci_corrected"][1] < USEFUL_S3 for e in evals.values()):
        return "absent", [f"every learner's corrected S3 upper bound < +{USEFUL_S3} R"]
    return "inconclusive", ["no learner meets 'present', and at least one corrected S3 upper bound reaches +%.2f R" % USEFUL_S3]


def run_tier(cutoffs: List[dict], acts: List[dict], tier: str, alpha: float, learners=("ridge", "logit", "gbdt")) -> Dict[str, Any]:
    X, names = feature_rows(cutoffs, acts, tier)
    te = np.array([r["fold"] in TEST_FOLDS for r in acts])
    evals, ics, folds, preds = {}, {}, {}, {}
    for lr in learners:
        p = walk_forward(acts, X, lr)
        preds[lr] = p
        rows = [acts[j] for j in np.nonzero(te)[0]]
        pt = p[te]
        evals[lr] = evaluate(rows, pt, alpha)
        ics[lr] = ic_summary(weekly_ic(rows, pt), alpha)
        folds[lr] = {}
        for k in TEST_FOLDS:
            mk = np.array([r["fold"] == k for r in rows])
            rk = [rows[j] for j in np.nonzero(mk)[0]]
            e = evaluate(rk, pt[mk], alpha) if rk else {}
            folds[lr][str(k)] = e.get("paired_diff_vs_random")
    v, why = verdict_for(evals, ics, folds)
    return {"tier": tier, "n_features": len(names), "features": names, "evals": evals, "ic": ics, "fold_S3": folds,
            "verdict": v, "why": why, "_preds": preds, "_X": X, "_names": names}


def cmd_run(a: argparse.Namespace) -> int:
    import pickle
    src = Path(a.out)
    cutoffs = pickle.loads((src / "cutoffs.pkl").read_bytes())
    acts = pickle.loads((src / "actions.pkl").read_bytes())
    global TEST_FOLDS, N_CONFIGS, FOLDS_POSITIVE_NEEDED
    meta = json.loads((src / "meta.json").read_text()) if (src / "meta.json").exists() else {"mode": "dev"}
    if meta["mode"] == "era":
        TEST_FOLDS, N_CONFIGS, FOLDS_POSITIVE_NEEDED = tuple(meta["test_folds"]), int(meta["n_configs"]), ERA_FOLDS_POSITIVE_NEEDED
    alpha = ALPHA / N_CONFIGS
    res: Dict[str, Any] = {"design": {"geometries": GEOMETRIES, "test_folds": TEST_FOLDS, "embargo_h": EMBARGO_H, "take_frac": TAKE_FRAC,
                                      "max_per_cutoff": MAX_PER_CUTOFF, "useful_s3": USEFUL_S3, "family": N_CONFIGS, "alpha_corrected": alpha,
                                      "grid_step_h": GRID_STEP_H, "baseline_draws": BASELINE_DRAWS,
                                      "folds_positive_needed": FOLDS_POSITIVE_NEEDED, "mode": meta["mode"]},
                           "population": {"cutoffs": len(cutoffs), "judged1_cutoffs": sum(c["judged1"] for c in cutoffs),
                                          "actions_filled": len(acts),
                                          "test_actions": sum(1 for r in acts if r["fold"] in TEST_FOLDS),
                                          "mode": meta["mode"],
                                          "window": ([ERA_BOUNDS[0].isoformat(), ERA_BOUNDS[-1].isoformat(), d.WINDOW_START.isoformat(), d.WINDOW_END.isoformat()]
                                                     if meta["mode"] == "era" else [d.WINDOW_START.isoformat(), d.WINDOW_END.isoformat()])}}
    te = np.array([r["fold"] in TEST_FOLDS for r in acts])
    test_rows = [acts[j] for j in np.nonzero(te)[0]]
    # what NO selection earns: every test action (S3 should be ~0 by construction; a check of the labels)
    allst = d.cluster_stats(s_rows(test_rows, range(len(test_rows))), draws=2000)
    res["unselected_test_actions"] = {k: allst.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")}
    tiers = {}
    for tier in ("P", "P+"):
        t = run_tier(cutoffs, acts, tier, alpha)
        tiers[tier] = t
        res[f"tier_{tier}"] = {k: v for k, v in t.items() if not k.startswith("_")}
        print(json.dumps({"tier": tier, "verdict": t["verdict"], "S3": {lr: e["paired_diff_vs_random"] for lr, e in t["evals"].items()},
                          "IC": {lr: i.get("mean_ic") for lr, i in t["ic"].items()}}), flush=True)
    # controls on the strongest tier's GBDT and ridge: planted signal must read present, shuffled labels must not
    Xp = tiers["P+"]["_X"]
    y = np.array([r["y"] for r in acts])
    rng = np.random.default_rng(SEED + 1)
    planted = y + rng.normal(0, 2.0 * y.std(), len(y))
    ctl = {}
    for name, kw in (("planted_signal", {"extra_col": planted}), ("shuffled_labels", {"label_noise": "shuffle"})):
        ev, ic, fo = {}, {}, {}
        for lr in ("ridge", "gbdt"):
            p = walk_forward(acts, Xp, lr, **kw)[te]
            ev[lr] = evaluate(test_rows, p, alpha)
            ic[lr] = ic_summary(weekly_ic(test_rows, p), alpha)
            fo[lr] = {str(k): evaluate([r for r in test_rows if r["fold"] == k], p[np.array([r["fold"] == k for r in test_rows])], alpha).get("paired_diff_vs_random") for k in TEST_FOLDS}
        v, why = verdict_for(ev, ic, fo)
        ctl[name] = {"verdict": v, "S3": {lr: e["paired_diff_vs_random"] for lr, e in ev.items()},
                     "S3_ci_corrected": {lr: e["S3_ci_corrected"] for lr, e in ev.items()}, "IC": {lr: i.get("mean_ic") for lr, i in ic.items()}}
        print(json.dumps({"control": name, **ctl[name]}), flush=True)
    res["controls"] = ctl
    res["instrument_valid"] = ctl["planted_signal"]["verdict"] == "present" and ctl["shuffled_labels"]["verdict"] != "present"
    # ablation: each P+ extra group added to P alone (which information carries it), on the GBDT and ridge
    Xpp, names = tiers["P+"]["_X"], tiers["P+"]["_names"]
    pnames = set(tiers["P"]["_names"])
    abl = {}
    for grp, cols in EXTRA_GROUPS.items():
        keep = [j for j, n in enumerate(names) if n in pnames or n in cols]
        ev = {}
        for lr in ("ridge", "gbdt"):
            p = walk_forward(acts, Xpp[:, keep], lr)[te]
            e = evaluate(test_rows, p, alpha)
            ev[lr] = {"S3": e["paired_diff_vs_random"], "S3_ci95": e["paired_diff_ci95"], "IC": ic_summary(weekly_ic(test_rows, p), alpha).get("mean_ic")}
        abl[f"P+{grp}"] = ev
        print(json.dumps({"ablation": grp, **{lr: v["S3"] for lr, v in ev.items()}}), flush=True)
    res["ablation_P_plus_one_group"] = abl
    # the judge vs the models ON THE SAME PACKETS (judged-1 cutoffs in the test folds)
    jrecs = [json.loads(ln) for ln in Path(a.judged1_records).read_text().splitlines() if ln.strip()] if a.judged1_records else []
    j1cut = {c["cutoff"] for c in cutoffs if c["judged1"]}
    jt = [j for j, r in enumerate(test_rows) if r["cutoff"] in j1cut]
    jrows = [test_rows[j] for j in jt]
    same = {}
    for tier in ("P", "P+"):
        for lr in ("ridge", "logit", "gbdt"):
            p = tiers[tier]["_preds"][lr][te][jt]
            e = evaluate(jrows, p, alpha)
            same[f"{tier}/{lr}"] = {k: e[k] for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95", "long_share")}
    if jrecs:
        keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
        ffn = era_fold if meta["mode"] == "era" else d.fold_of
        jsel = [r for r in jrecs if ffn(int(keys[r["packet_id"]]["cutoff_epoch"])) in TEST_FOLDS]
        st = d.cluster_stats([{"week": r["week"], "net_r": r["net_r"], "days": r["days"], "diff": r["diff"]} for r in jsel])
        same["judge_judged1"] = {"n": st["n"], "mean_net_r": st["mean_net_r"], "paired_diff_vs_random": st.get("paired_diff_vs_random"),
                                 "paired_diff_ci95": st.get("paired_diff_ci95"),
                                 "long_share": float(np.mean([r["side"] == "long" for r in jsel])) if jsel else None,
                                 "source": "judged-1 per-proposal records (DESK-18C decomposition, the driver's own score loop)"}
    res["same_packets_judge_vs_models"] = same
    # GBDT gain importances on P+, last test fold's training set (what the model leaned on)
    try:
        import lightgbm as lgb
        fold = np.array([r["fold"] for r in acts])
        tr = fold < max(TEST_FOLDS)
        mdl = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=400, subsample=0.8, subsample_freq=1,
                                colsample_bytree=0.8, reg_lambda=10.0, random_state=SEED, verbose=-1, importance_type="gain").fit(Xpp[tr], y[tr])
        imp = sorted(zip(names, mdl.feature_importances_), key=lambda x: -x[1])[:20]
        res["gbdt_P+_top_gain"] = [[n, float(v)] for n, v in imp]
    except Exception as e:  # allow-silent: importance is descriptive; its absence is recorded
        res["gbdt_P+_top_gain"] = f"not computed: {e}"
    # holding period as an axis: per horizon, each learner's policy restricted to that horizon's actions, plus the cost
    hz = {}
    gh = np.array([r["g_h"] for r in test_rows])
    for h in sorted(set(gh.tolist())):
        m = np.nonzero(gh == h)[0]
        hrows = [test_rows[j] for j in m]
        ent = {"actions": len(hrows), "unselected_mean_net_r": float(np.mean([r["net_r"] for r in hrows])),
               "mean_cost_r": float(np.mean([r["cost_r"] for r in hrows])) if all("cost_r" in r for r in hrows) else None}
        for tier in ("P", "P+"):
            for lr in ("ridge", "logit", "gbdt"):
                e = evaluate(hrows, tiers[tier]["_preds"][lr][te][m], alpha)
                ent[f"{tier}/{lr}"] = {k: e[k] for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95", "S3_ci_corrected")}
        best_hi = max((ent[k]["S3_ci_corrected"][1] for k in ent if "/" in k and ent[k]["S3_ci_corrected"]), default=float("nan"))
        best_pt = max((ent[k]["paired_diff_vs_random"] for k in ent if "/" in k and ent[k]["paired_diff_vs_random"] is not None), default=float("nan"))
        ent["horizon_verdict"] = ("no_extractable_s3" if best_hi < USEFUL_S3 else
                                  "candidate" if best_pt > 0 else "not_excluded")
        hz[str(int(h))] = ent
        print(json.dumps({"horizon": int(h), "verdict": ent["horizon_verdict"], "cost_r": ent["mean_cost_r"], "best_S3": best_pt}), flush=True)
    res["by_horizon"] = hz
    # the pre-registered decision tree
    vp, vpp, valid = res["tier_P"]["verdict"], res["tier_P+"]["verdict"], res["instrument_valid"]
    jj = same.get("judge_judged1", {})
    judge_found = bool(jj.get("paired_diff_ci95") and jj["paired_diff_ci95"][0] > 0)
    if not valid:
        branch = "instrument_invalid"
    elif vp == "present" and not judge_found:
        branch = "bottleneck_judge"
    elif vp != "present" and vpp == "present":
        branch = "bottleneck_packet_information"
    elif vp == "present":
        branch = "information_and_judge_both_find_edge"
    elif vp == "absent" and vpp == "absent":
        branch = "no_edge_in_reachable_information"
    else:
        branch = "inconclusive"
    res["decision_branch"] = branch
    ev = Path(a.evidence)
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "ceiling.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=float) + "\n")
    print(json.dumps({"branch": branch, "P": vp, "P+": vpp, "instrument_valid": valid}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--candles", required=True)
    b.add_argument("--mask-key", default=str(REPO / "comms/research/desk_gen_replay/judged-1/mask-key.json"))
    b.add_argument("--funding", default=None)
    b.add_argument("--fetch-funding", action="store_true")
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--era", action="store_true", help="the extended-era run (doc section 4.2)")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--evidence", required=True)
    r.add_argument("--mask-key", default=str(REPO / "comms/research/desk_gen_replay/judged-1/mask-key.json"))
    r.add_argument("--judged1-records", default=None)
    r.set_defaults(fn=cmd_run)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
