#!/usr/bin/env python3
# wiring: research/queue/RQ-20261105-fd68-01.yaml (Tradeify-only ML leg) and its Breakout/Velotrade sibling (checklist TRADEIFY-OWN-LEG-DRIVER, lane TRADEIFY-OWN-LEG)
# ruff: noqa: E402, E701, E702, E731
"""Prop ML entry leg: pooled ML entry model -> net-of-cost ledger -> V3 prop gate -> distinctness D1-D4. Tier-1 research tooling.

The pre-registered design lives in the queue unit, not here; this file only implements it:
  research/queue/RQ-20261105-fd68-01.yaml  (profile ``tradeify``)   and   its ``bv`` sibling (profile ``bv``).
Nothing in this file edits config, a roster or an order path. Data: Binance Vision public klines / funding / metrics and FRED
public CSV (keyless); no Anthropic API.

    python3 scripts/research/prop_ml_leg.py run --profile tradeify --out DIR [--cache DIR] [--ref-ledger PATH ...]
    python3 scripts/research/prop_ml_leg.py distinct --ledger LEDGER.jsonl --span-start 2025-10-01 --span-end 2026-09-30 [--refs ...]
    python3 scripts/research/prop_ml_leg.py --self-test          # reproduces the ml_entry reference (+0.01704 R, n 381) and unit-tests D1-D4
    python3 scripts/research/prop_ml_leg.py run --profile tradeify --smoke --out DIR   # mechanics only: dev window <= 2022-12-31, never reads the held-out

Design constants are the registered ones (unit ``label_and_horizon``, ``arms``, ``split``, ``decision_rule``). Thresholds are NOT changed after a result.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import itertools
import json
import math
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import book_depth_pit as BD  # point-in-time book-depth table (unit RQ-20261109-98e3-36, PASS): the F0+BOOK arm reads its as-of tables
import ml_decision_entry as E  # klines fetch, features_symbol, bracket_outcome (reused, unchanged)
import prop_gate as G  # V3 edge clause + ACCT/SIM

SCHEMA = "prop_ml_leg/1"
H = 48                                 # max hold, bars (registered at 1h bars; --bar-hours N sets H = 48 // N so the real horizon stays 48 h)
BAR_H = 1                              # decision bar length in hours (--bar-hours; units RQ-20261105-fd68-01/-02 are 1; the 4h units set 4)
SL_ATR = 1.5                           # registered stop
REF_TP_R = 3.0                         # label bracket's reference TP, in R (driver detail fixed BEFORE any run; see unit ``amendments``)
Y_MIN_NET_R = 0.5                      # registered label threshold
TP_Q, TP_LO, TP_HI = 0.60, 1.5, 4.0    # registered TP head: q60 of MFE-in-R, clipped
HOLDOUT_START, HOLDOUT_END = "2025-10-01", "2026-09-30"
DEV_START_FOLDS = "2022-01-01"
DISC_END = None                        # discovery folds end here; None = HOLDOUT_START (forward design). --heldout-span with a span BEFORE --discovery-start sets it (backward design)
DISC_FLOOR_TS = None                   # --discovery-start: rows before it never enter discovery training or folds (keeps a backward held-out span sealed)
TAUS = (0.55, 0.60, 0.65)
N_HELD_FLOOR, N_DISC_FLOOR = 150, 100
SEED = 20261105
BOOT_DRAWS, RANDOM_DRAWS = 2000, 2000
LGB = {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 300, "subsample": 0.8, "subsample_freq": 1,
       "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": SEED, "verbose": -1, "n_jobs": 4}

PROFILES = {
    # unit RQ-20261105-fd68-01 baselines.cost_stack: commission 4 bps/side, slippage 3 bps/side, swap 3.3 bps/night
    "tradeify": {"symbols": ["ETHUSDT", "SOLUSDT", "XRPUSDT"], "accounts": ["tradeify_1"], "comm_bps_side": 4.0, "slip_bps_side": 3.0,
                 "swap_bps_night": 3.3, "leg_key": "tradeify_own_sol_cap2", "grade_distinct": True, "pass_rule": "all"},
    # ETH+SOL slice of the tradeify profile (2026-11-09): config/accounts.yaml tradeify_1 trades ETHUSDT and SOLUSDT; same account, cost stack and leg key
    "tradeify_es": {"symbols": ["ETHUSDT", "SOLUSDT"], "accounts": ["tradeify_1"], "comm_bps_side": 4.0, "slip_bps_side": 3.0,
                    "swap_bps_night": 3.3, "leg_key": "tradeify_own_sol_cap2", "grade_distinct": True, "pass_rule": "all"},
    # shared Breakout/Velotrade model: the stricter of the two firms' declared stacks on each term
    "bv": {"symbols": ["ETHUSDT", "SOLUSDT"], "accounts": ["breakout_2", "velotrade_1"], "comm_bps_side": 4.0, "slip_bps_side": 3.0,
           "swap_bps_night": 5.0, "leg_key": "bv_shared_ml", "grade_distinct": False, "pass_rule": "any"},
}
CONTEXT_SYMBOLS = ["BTCUSDT"]          # cross-sectional / market context only, never traded or trained on
MACRO = {"VIXCLS": "vix", "DGS10": "y10", "DTWEXBGS": "usd", "SP500": "spx"}   # F2: market series, lagged one day (point-in-time safe)
FEATURE_SETS = {"F0": [], "F0+F1": ["F1"], "F0+F1+F2": ["F1", "F2"], "F0+F1+F2+F3": ["F1", "F2", "F3"]}
# OPT-IN arms (2026-11-09, PROP-ML-NEW-DATA step 2): selectable ONLY by name via --arms, never part of the default arm list, so no existing unit
# that runs without --arms changes. F1o = the open-interest / long-short / taker-flow part of F1 WITHOUT the funding columns (the census family oi_flow).
EXTRA_ARMS = {"F0+OI": ["F1o"], "F0+BASIS": ["F1b"], "F0+BOOK": ["F1d"]}
F1_OI_COLS = ("oi_chg24", "oi_z", "ls_top_cnt", "ls_top_pos", "ls_all", "taker_ratio", "taker_ratio_ma24")
# F1b (2026-11-09, PROP-ML-NEW-DATA step 2b, census RQ-20261109-98e3-30): the basis (premium index) part of the census family funding_basis. It is
# the stream the census graded USABLE for BOTH ETH and SOL (SOL fundingRate was not), and the only family that spans the sealed backward span.
# It is loaded and added to the table ONLY when the F0+BASIS arm is requested (NEED_BASIS), so no existing unit changes: no new download, no new column.
BASIS_COLS = ("basis", "basis_ma24", "basis_z", "basis_chg24")
BASIS_STALE_H = 6                      # a premium reading older than this at a bar close is NaN: a hole in the archive never carries a stale value forward
NEED_BASIS = False
# F1d (2026-11-09, PROP-ML-NEW-DATA step 3, builder unit RQ-20261109-98e3-36 PASS): the Binance USD-M perp bookDepth family (resting liquidity within +-1/2/5 % of
# mid, from the public archive, 30 s snapshots, 2023-01 onward). Features are book_depth_pit.FEATURES, each AS OF the bar close (snapshots <= the close only; a
# snapshot older than book_depth_pit.TOL_S at the close is NaN). Loaded and added ONLY when the F0+BOOK arm is requested (NEED_BOOK): no other unit changes.
BOOK_COLS = tuple(BD.FEATURES)
NEED_BOOK = False


# ----------------------------------------------------------------------------------------------- data
def _get(url: str):
    import requests
    for wait in (0, 2, 4):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final miss returns None and is counted in coverage
            continue
    return None


def fetch_funding(cache: Path, syms: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for s in syms:
        p = cache / f"{s}.funding.pkl"
        if p.exists():
            out[s] = pd.read_pickle(p); continue
        frames = []
        for m in E._months(E.START, E.END):
            b = _get(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip")
            if b:
                raw = zipfile.ZipFile(io.BytesIO(b)).read(zipfile.ZipFile(io.BytesIO(b)).namelist()[0]).decode()
                frames.append(pd.read_csv(io.StringIO(raw)))
        df = pd.concat(frames) if frames else pd.DataFrame(columns=["calc_time", "last_funding_rate"])
        df["ts"] = pd.to_datetime(pd.to_numeric(df["calc_time"]), unit="ms", utc=True)
        df = df[["ts", "last_funding_rate"]].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        df.to_pickle(p); out[s] = df
    return out


def fetch_metrics(cache: Path, syms: list[str]) -> dict[str, pd.DataFrame]:
    """Daily 5-minute metrics files (OI, long/short ratios, taker flow). Missing days stay missing (coverage reports them)."""
    out = {}
    days = pd.date_range(max(pd.Timestamp(E.START), pd.Timestamp("2021-12-01")), pd.Timestamp(E.END), freq="D")
    for s in syms:
        p = cache / f"{s}.metrics.pkl"
        if p.exists():
            out[s] = pd.read_pickle(p); continue

        def one(d, s=s):
            b = _get(f"https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d:%Y-%m-%d}.zip")
            if not b:
                return None
            z = zipfile.ZipFile(io.BytesIO(b))
            return pd.read_csv(io.StringIO(z.read(z.namelist()[0]).decode()))
        with cf.ThreadPoolExecutor(16) as ex:
            frames = [f for f in ex.map(one, days) if f is not None]
        df = pd.concat(frames) if frames else pd.DataFrame()
        if len(df):
            df["ts"] = pd.to_datetime(df["create_time"], utc=True)
            df = df.drop(columns=["create_time", "symbol"]).sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
        df.to_pickle(p); out[s] = df
    return out


def fetch_macro(cache: Path) -> pd.DataFrame:
    p = cache / "macro.pkl"
    if p.exists():
        return pd.read_pickle(p)
    cols = {}
    for sid, name in MACRO.items():
        b = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
        if not b:
            continue
        df = pd.read_csv(io.BytesIO(b))
        df.columns = ["d", name]
        df["d"] = pd.to_datetime(df["d"], utc=True)
        df[name] = pd.to_numeric(df[name], errors="coerce")
        cols[name] = df.set_index("d")[name].dropna()
    m = pd.DataFrame(cols).sort_index()
    m.to_pickle(p)
    return m


# ----------------------------------------------------------------------------------------------- bars
def hourly_premium(m1: pd.DataFrame) -> pd.DataFrame:
    """1m premium-index closes -> ONE row per UTC hour h: the close of the last 1m bar inside [h, h+1h), stamped h+1h, the moment the hour has closed.
    A stamp is never earlier than the data it carries, so every downstream as-of join is point-in-time. Holes stay holes (no fill)."""
    if not len(m1):
        return pd.DataFrame({"ts": pd.DatetimeIndex([], tz="UTC"), "premium": np.array([], dtype=float)})
    d = m1.drop_duplicates("ts").sort_values("ts").set_index("ts")["close"].astype(float)
    h = d.groupby(d.index.floor("1h")).last()
    return pd.DataFrame({"ts": h.index + pd.Timedelta(hours=1), "premium": h.to_numpy()})


def fetch_premium(cache: Path, syms: list[str]) -> dict[str, pd.DataFrame]:
    """Monthly 1m premiumIndexKlines from the public Binance Vision archive (no credential), reduced to hourly (see hourly_premium) and cached."""
    from scripts.data_lake.binance_vision_lake import parse_kline_csv    # the lake's own parser: header rows and ms/us epochs handled once
    out = {}
    months = E._months(E.START, E.END)
    for s in syms:
        p = cache / f"{s}.premium.pkl"
        if p.exists():
            out[s] = pd.read_pickle(p); continue

        def one(m, s=s):
            b = _get(f"https://data.binance.vision/data/futures/um/monthly/premiumIndexKlines/{s}/1m/{s}-1m-{m}.zip")
            if not b:
                return None
            z = zipfile.ZipFile(io.BytesIO(b))
            return parse_kline_csv(z.read(z.namelist()[0]))[["ts", "close"]]
        with cf.ThreadPoolExecutor(8) as ex:
            frames = [f for f in ex.map(one, months) if f is not None and len(f)]
        df = hourly_premium(pd.concat(frames) if frames else pd.DataFrame(columns=["ts", "close"]))
        df.to_pickle(p); out[s] = df
    return out


def basis_features(kl: pd.DataFrame, prem: pd.DataFrame | None) -> pd.DataFrame:
    """Basis (premium index) features as-of the bar CLOSE (bar t covers [t, t+BAR_H); only hourly readings stamped <= t+BAR_H are used).
    The hourly series is put on a COMPLETE grid first, so a hole is NaN and shift(24) / the 24 h and 168 h windows are exactly that long.
    A reading older than BASIS_STALE_H at the bar close is NaN. NaN where the source has no history."""
    out = pd.DataFrame({"ts": kl["ts"]})
    for c in BASIS_COLS:
        out[c] = np.nan
    if prem is None or not len(prem):
        return out
    ns = "datetime64[ns, UTC]"
    h = prem.set_index("ts")["premium"].astype(float)
    grid = pd.date_range(h.index.min(), h.index.max(), freq="1h")
    h = h.reindex(grid)
    z = (h - h.rolling(168, min_periods=48).mean()) / h.rolling(168, min_periods=48).std()
    feat = pd.DataFrame({"avail": grid.astype(ns), "basis": h.to_numpy(), "basis_ma24": h.rolling(24, min_periods=12).mean().to_numpy(),
                         "basis_z": z.to_numpy(), "basis_chg24": (h - h.shift(24)).to_numpy()}).dropna(subset=["basis"])
    q = pd.DataFrame({"ts": kl["ts"].astype(ns).to_numpy(), "close_ts": (kl["ts"] + pd.Timedelta(hours=BAR_H)).astype(ns).to_numpy()}).sort_values("close_ts")
    m = pd.merge_asof(q, feat, left_on="close_ts", right_on="avail", direction="backward", tolerance=pd.Timedelta(hours=BASIS_STALE_H))
    res = m.set_index("ts")[list(BASIS_COLS)].reindex(kl["ts"].astype(ns))
    for c in BASIS_COLS:
        out[c] = res[c].to_numpy()
    return out


def fetch_book(cache: Path, syms: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Per trade symbol: the as-of table of book-depth features at every BAR_H-hour bar close (book_depth_pit.asof_table), plus the file census.
    Day-files are cached under <cache>/book_depth; an unreachable day is never cached as an answer."""
    tables, census = {}, {}
    days = BD.days_in(BD.SPAN)
    with cf.ThreadPoolExecutor(8) as ex:
        for s in syms:
            parts = list(ex.map(lambda d, s=s: BD.load_day(cache / "book_depth", s, d), days))
            snaps, cen = BD.census_symbol(s, parts)
            feat = BD.snap_features(snaps) if not snaps.empty else pd.DataFrame()
            tables[s], census[s] = BD.asof_table(feat, BD.SPAN, BAR_H), cen
    return tables, census


def book_features(kl: pd.DataFrame, bt: pd.DataFrame | None) -> pd.DataFrame:
    """Book-depth features for the bars of `kl`, as of each bar's CLOSE (bar t covers [t, t+BAR_H); the table row stamped t+BAR_H is used, and every
    value in that row was computed from snapshots at or before that instant). NaN where the table has no row or the snapshot was stale."""
    out = pd.DataFrame({"ts": kl["ts"]})
    for c in BOOK_COLS:
        out[c] = np.nan
    if bt is None or not len(bt):
        return out
    ns = "datetime64[ns, UTC]"
    b = bt.assign(_k=bt["T"].astype(ns)).drop_duplicates("_k").set_index("_k")[list(BOOK_COLS)]
    res = b.reindex((kl["ts"] + pd.Timedelta(hours=BAR_H)).astype(ns))
    for c in BOOK_COLS:
        out[c] = res[c].to_numpy()
    return out


def load_kl(cache: Path, sym: str) -> pd.DataFrame:
    """The cached 1h klines, resampled to BAR_H-hour bars (open time = bar start; empty bars dropped) when BAR_H > 1."""
    d = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
    if BAR_H == 1:
        return d
    r = d.set_index("ts").resample(f"{BAR_H}h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return r.reset_index()


# ----------------------------------------------------------------------------------------------- features
def f1_features(kl: pd.DataFrame, fund: pd.DataFrame, met: pd.DataFrame) -> pd.DataFrame:
    """Derivatives positioning, as-of the bar CLOSE (bar t covers [t, t+1h); inputs stamped <= t+1h). NaN where the source has no history."""
    close_ts = kl["ts"] + pd.Timedelta(hours=BAR_H)
    out = pd.DataFrame({"ts": kl["ts"]})
    if len(fund):
        f = fund.set_index("ts")["last_funding_rate"].astype(float)
        fr = f.reindex(f.index.union(close_ts)).ffill().reindex(close_ts)
        out["fund"] = fr.to_numpy()
        roll = f.rolling(9).mean(); z = (f - f.rolling(90).mean()) / f.rolling(90).std()
        out["fund_ma3d"] = roll.reindex(f.index.union(close_ts)).ffill().reindex(close_ts).to_numpy()
        out["fund_z"] = z.reindex(f.index.union(close_ts)).ffill().reindex(close_ts).to_numpy()
    if len(met):
        m = met.set_index("ts").astype(float)
        asof = lambda col: m[col].reindex(m.index.union(close_ts)).ffill().reindex(close_ts)
        oi = asof("sum_open_interest_value")
        out["oi_chg24"] = (np.log(oi) - np.log(oi.shift(24))).to_numpy()
        out["oi_z"] = ((oi - oi.rolling(168).mean()) / oi.rolling(168).std()).to_numpy()
        for col, nm in (("count_toptrader_long_short_ratio", "ls_top_cnt"), ("sum_toptrader_long_short_ratio", "ls_top_pos"),
                        ("count_long_short_ratio", "ls_all"), ("sum_taker_long_short_vol_ratio", "taker_ratio")):
            out[nm] = np.log(asof(col).replace(0, np.nan)).to_numpy()
        out["taker_ratio_ma24"] = pd.Series(out["taker_ratio"]).rolling(24, min_periods=6).mean().to_numpy()
    return out


def f2_features(ts: pd.Series, macro: pd.DataFrame) -> pd.DataFrame:
    """Daily market series; the value dated d is usable from d+1 00:00 UTC (one-day lag => point-in-time safe)."""
    avail = macro.copy(); avail.index = avail.index + pd.Timedelta(days=1)
    close_ts = ts + pd.Timedelta(hours=BAR_H)
    out = pd.DataFrame({"ts": ts})
    for c in avail.columns:
        s = avail[c].reindex(avail.index.union(close_ts)).ffill().reindex(close_ts).to_numpy()
        ser = pd.Series(s)
        out[f"m_{c}"] = s
        out[f"m_{c}_chg5d"] = (np.log(ser.replace(0, np.nan)) - np.log(ser.shift(120).replace(0, np.nan))).to_numpy()
    return out


def label_symbol(df: pd.DataFrame, cost) -> pd.DataFrame:
    """Every closed 1h bar with a full 48-bar contiguous forward window. Entry = next bar open; stop 1.5 ATR14; reference TP 3R for the label."""
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(E.ATR_N, min_periods=E.ATR_N).mean().to_numpy()
    ts = df["ts"]; N = len(df)
    t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
    cand = np.where(~np.isnan(atr))[0]; cand = cand[cand + H < N]
    cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * BAR_H * 3_600_000_000_000]
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
    entry = Ob[:, 0]; a = atr[cand]; risk = SL_ATR * a
    out = {"i": cand, "ts": ts.to_numpy()[cand], "atr": a, "entry": entry}
    for name, side in (("long", 1), ("short", -1)):
        px, j, _ = E.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=SL_ATR, tp_atr=REF_TP_R * SL_ATR)
        gross = side * (px - entry) / risk
        out[f"net_{name}"] = gross - cost(entry, px, risk, j * BAR_H)
        out[f"y_{name}"] = (out[f"net_{name}"] >= Y_MIN_NET_R).astype(int)
        fav = (Hh.max(1) - entry) if side > 0 else (entry - Lb.min(1))
        out[f"mfe_{name}"] = np.maximum(fav / risk, 0.0)
    return pd.DataFrame(out)


def make_cost(p: dict):
    """cost in R of a trade: (2 x (commission + slippage) bps + swap bps per night x nights held) x avg price / risk."""
    def cost(entry, px, risk, hold_bars):
        avg = (np.abs(entry) + np.abs(px)) / 2.0
        return (2 * (p["comm_bps_side"] + p["slip_bps_side"]) / 1e4 * avg + p["swap_bps_night"] / 1e4 * (np.asarray(hold_bars) / 24.0) * avg) / risk
    return cost


def build_table(cache: Path, profile: dict, smoke: bool, rehearsal: bool = False) -> tuple[pd.DataFrame, dict, dict]:
    trade_syms, ctx = profile["symbols"], CONTEXT_SYMBOLS
    allsyms = trade_syms + ctx
    E.fetch(cache, allsyms)
    fund, met = fetch_funding(cache, allsyms), fetch_metrics(cache, allsyms)
    prem = fetch_premium(cache, trade_syms) if NEED_BASIS else {}      # trade symbols only; context symbols never reach the table
    book, book_census = fetch_book(cache, trade_syms) if NEED_BOOK else ({}, {})
    macro = fetch_macro(cache)
    cost = make_cost(profile)
    feats, rows, cov = {}, [], {}
    for s in allsyms:
        kl = load_kl(cache, s)
        f0 = E.features_symbol(kl)
        f1 = f1_features(kl, fund.get(s, pd.DataFrame()), met.get(s, pd.DataFrame()))
        f2 = f2_features(kl["ts"], macro) if len(macro) else pd.DataFrame({"ts": kl["ts"]})
        feats[s] = f0
        if s in ctx:
            continue
        lab = label_symbol(kl, cost)
        parts = (f0, f1, f2) + ((basis_features(kl, prem.get(s)),) if NEED_BASIS else ()) + ((book_features(kl, book.get(s)),) if NEED_BOOK else ())
        for part in parts:
            lab = lab.join(part.drop(columns=["ts"]), on="i")
        lab["symbol"] = s; rows.append(lab)
    tab = pd.concat(rows, ignore_index=True)
    r24 = pd.DataFrame({s: feats[s].set_index("ts")["ret24_raw"] for s in allsyms})
    v24 = pd.DataFrame({s: feats[s].set_index("ts")["vol24"] for s in allsyms})
    rank = r24[trade_syms].rank(axis=1, pct=True)
    key = pd.MultiIndex.from_arrays([tab["ts"], tab["symbol"]])
    tab["xs_rank_ret24"] = rank.stack().reindex(key).to_numpy()
    tab["btc_ret24"] = r24["BTCUSDT"].reindex(tab["ts"]).to_numpy()
    tab["btc_vol24"] = v24["BTCUSDT"].reindex(tab["ts"]).to_numpy()
    tab["breadth_up24"] = ((r24[trade_syms] > 0).sum(axis=1) / r24[trade_syms].notna().sum(axis=1)).reindex(tab["ts"]).to_numpy()
    tab["rel_vol"] = tab["vol24"].to_numpy() / v24[trade_syms].median(axis=1).reindex(tab["ts"]).to_numpy()
    tab = tab.replace([np.inf, -np.inf], np.nan)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    tab = tab.dropna(subset=["net_long", "net_short", "ret_168", "vol_ratio"]).reset_index(drop=True)
    if smoke:
        tab = tab[tab.ts < pd.Timestamp("2023-01-01", tz="UTC")].reset_index(drop=True)
    if rehearsal:
        tab = tab[tab.ts < pd.Timestamp("2024-01-01", tz="UTC")].reset_index(drop=True)
    f0cols = list(E.FEATURES)
    f1cols = [c for c in tab.columns if c in ("fund", "fund_ma3d", "fund_z", "oi_chg24", "oi_z", "ls_top_cnt", "ls_top_pos", "ls_all", "taker_ratio", "taker_ratio_ma24")]
    f2cols = [c for c in tab.columns if c.startswith("m_")]
    fam = {"F0": f0cols, "F1": f1cols, "F2": f2cols, "F3": [], "F1o": [c for c in f1cols if c in F1_OI_COLS]}
    if NEED_BASIS:
        fam["F1b"] = [c for c in tab.columns if c in BASIS_COLS]
    if NEED_BOOK:
        fam["F1d"] = [c for c in tab.columns if c in BOOK_COLS]
    for k, cols in fam.items():     # coverage audit: first/last non-null and the null share at decision rows, per family and symbol
        cov[k] = {"n_features": len(cols), "columns": cols,
                  "per_symbol": {s: ({"first": str(g.loc[g[cols].notna().any(axis=1), "ts"].min()), "last": str(g.loc[g[cols].notna().any(axis=1), "ts"].max()),
                                      "null_share_any": round(float(g[cols].isna().all(axis=1).mean()), 4)} if cols else {"read_state": "no_source_in_driver"})
                                 for s, g in tab.groupby("symbol")}}
    if NEED_BOOK:
        cov["F1d"]["file_census"] = {s: {k: c[k] for k in ("days_expected", "days_present", "days_absent_404", "days_unreachable", "days_unparseable", "first_absent_days")}
                                     for s, c in book_census.items()}
    cov["F3"]["note"] = "F3 text/embedding: no point-in-time history source wired in this driver -> arm UNAVAILABLE (reported, not run, not silently dropped)"
    return tab, fam, cov


# ----------------------------------------------------------------------------------------------- model + policy
def arm_cols(fam: dict, name: str) -> list[str]:
    cols = list(fam["F0"])
    for k in (FEATURE_SETS[name] if name in FEATURE_SETS else EXTRA_ARMS[name]):   # F0 maps to [] (falsy): test membership, never truthiness
        cols += fam[k]
    return cols


MODEL = "lgbm"                         # --model: "lgbm" = the registered fixed LightGBM (default, every earlier unit); "logit" = low-capacity arm (unit RQ-20261112-7d41-01/-02)
LOGIT_C = 0.05                         # L2 inverse strength of the low-capacity arm, fixed here BEFORE any run (no tuning loop)


def _fit_predict_logit(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Low-capacity head: median-impute + standardise + L2 logistic regression for the win label; the TP head is ONE constant per side
    (q60 of the training MFE, clipped like the LightGBM head), so the only per-bar information is the entry score."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    out = pd.DataFrame(index=test.index)
    for side in ("long", "short"):
        m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=LOGIT_C, max_iter=500))
        m.fit(train[cols], train[f"y_{side}"])
        out[f"p_{side}"] = m.predict_proba(test[cols])[:, 1]
        out[f"tp_{side}"] = float(np.clip(np.nanquantile(train[f"mfe_{side}"].to_numpy(float), TP_Q), TP_LO, TP_HI))
    return out


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if MODEL == "logit":
        return _fit_predict_logit(train, test, cols)
    import lightgbm as lgb
    out = pd.DataFrame(index=test.index)
    for side in ("long", "short"):
        m = lgb.LGBMClassifier(**LGB).fit(train[cols], train[f"y_{side}"])
        out[f"p_{side}"] = m.predict_proba(test[cols])[:, 1]
        q = lgb.LGBMRegressor(objective="quantile", alpha=TP_Q, **LGB).fit(train[cols], train[f"mfe_{side}"])
        out[f"tp_{side}"] = np.clip(q.predict(test[cols]), TP_LO, TP_HI)
    return out


class Replay:
    """First-passage replay of ONE trade with a model-set TP (R units), from the per-symbol bar arrays."""
    def __init__(self, cache: Path, symbols: list[str], cost):
        self.cost = cost
        self.bars = {}
        for s in symbols:
            d = load_kl(cache, s)
            self.bars[s] = (d["ts"], *(d[k].to_numpy(float) for k in ("open", "high", "low", "close")))

    def trade(self, sym: str, i: int, side: int, atr: float, tp_r: float) -> dict:
        ts, o, h, lo, c = self.bars[sym]
        sl_ = slice(i + 1, i + 1 + H)
        Ob, Hh, Lb, Cb = (a[sl_][None, :] for a in (o, h, lo, c))
        entry = Ob[:, 0]; a = np.array([atr]); risk = SL_ATR * atr
        px, j, reason = E.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=SL_ATR, tp_atr=float(tp_r) * SL_ATR)
        j = int(j[0]); px = float(px[0]); e = float(entry[0])
        gross = side * (px - e) / risk
        fav = (Hh[0, :j].max() - e) if side > 0 else (e - Lb[0, :j].min())
        return {"symbol": sym, "direction": "long" if side > 0 else "short", "entry_time": str(ts.iloc[i + 1]),
                "exit_time": str(ts.iloc[i + j] + pd.Timedelta(hours=BAR_H)), "entry": e, "sl": e - side * risk,
                "exit_reason": {0: "time", 1: "sl", 2: "take_profit"}[int(reason[0])], "gross_r": round(gross, 6),
                "mfe_r": round(max(fav / risk, gross), 6),
                "net_r": round(float(gross - self.cost(e, px, risk, j * BAR_H)), 6), "tp_r": round(float(tp_r), 4), "hold_bars": j}


def run_policy(test: pd.DataFrame, pred: pd.DataFrame, tau: float, rp: Replay) -> pd.DataFrame:
    t = test.join(pred).sort_values(["symbol", "i"])
    t = t[(t[["p_long", "p_short"]].max(axis=1) > tau)]
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for r in g.itertuples(index=False):
            if r.i <= busy:
                continue
            side = 1 if r.p_long >= r.p_short else -1
            tp = r.tp_long if side > 0 else r.tp_short
            tr = rp.trade(sym, int(r.i), side, float(r.atr), float(tp))
            tr["p"] = round(float(max(r.p_long, r.p_short)), 4)
            out.append(tr); busy = int(r.i) + tr["hold_bars"]
    cols = ["symbol", "direction", "entry_time", "exit_time", "entry", "sl", "exit_reason", "gross_r", "mfe_r", "net_r", "tp_r", "hold_bars", "p"]
    return pd.DataFrame(out, columns=cols)


def fold_bounds(smoke: bool) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    end = DISC_END or HOLDOUT_START
    edges = list(pd.date_range(DEV_START_FOLDS, end, freq="QS", tz="UTC"))
    if edges[-1] != pd.Timestamp(end, tz="UTC"):
        edges.append(pd.Timestamp(end, tz="UTC"))
    if smoke:
        edges = [e for e in edges if e <= pd.Timestamp("2023-01-01", tz="UTC")]
    return list(itertools.pairwise(edges))


def purged_train(tab: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    return tab[tab.ts + pd.Timedelta(hours=7 * 24 + (H + 1) * BAR_H) <= start]   # 7 d + the label horizon + one bar


# ----------------------------------------------------------------------------------------------- stats
def boot_ci(x: list[float], block: int = 5, bar: dict | None = None) -> dict:
    x = np.asarray(x, float); n = len(x)
    if n < 2 * block:
        return {"n": n, "mean": float(x.mean()) if n else None, "ci_lo": None, "read_state": "n_too_small"}
    rng = np.random.default_rng(SEED)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(BOOT_DRAWS, nb))
    means = np.array([np.concatenate([x[s:s + block] for s in row])[:n].mean() for row in starts])
    p = (bar or {}).get("ci_lo_percentile", 2.5)   # deflated on a re-read of the held-out span (holdout ledger; HOLDOUT-DEFLATED-REUSE)
    return {"n": n, "mean": float(x.mean()), "ci_lo": float(np.percentile(means, p)), "ci_hi": float(np.percentile(means, 100 - p)),
            "ci_lo_percentile": p, "read_state": "ok"}


def regime_clause(oos: pd.DataFrame) -> dict:
    """E3 on the walk-forward OOS + held-out trades of the selected arm, calendar years 2023..2026."""
    d = oos.copy(); d["t"] = pd.to_datetime(d["entry_time"], utc=True); d = d[d.t >= pd.Timestamp("2023-01-01", tz="UTC")]
    if d.empty:
        return {"pass": False, "read_state": "no_trades"}
    yr = d.groupby(d.t.dt.year)["net_r"].sum()
    years = [2023, 2024, 2025, 2026]
    pos_years = int(sum(float(yr.get(y, 0.0)) > 0 for y in years))
    tot = float(d["net_r"].sum())
    max_share = float(yr.max() / tot) if tot > 0 else None
    side = d.groupby("direction")["net_r"].sum().to_dict()
    mid = d.t.min() + (d.t.max() - d.t.min()) / 2
    halves = [float(d[d.t <= mid]["net_r"].sum()), float(d[d.t > mid]["net_r"].sum())]
    ok = pos_years >= 3 and tot > 0 and max_share is not None and max_share <= 0.5 and all(v >= 0 for v in side.values()) \
        and len(side) == 2 and all(v > 0 for v in halves)
    return {"pass": bool(ok), "per_year_net_r": {int(k): round(float(v), 3) for k, v in yr.items()}, "years_positive_of_4": pos_years,
            "total_net_r": round(tot, 3), "max_year_share": None if max_share is None else round(max_share, 3),
            "side_net_r": {k: round(float(v), 3) for k, v in side.items()}, "halves_net_r": [round(v, 3) for v in halves], "read_state": "ok"}


# ----------------------------------------------------------------------------------------------- distinctness D1-D4
def _ts(x):
    return pd.to_datetime(x, utc=True)


def _norm(rows: list[dict]) -> pd.DataFrame:
    d = pd.DataFrame(rows)
    d["entry_time"] = _ts(d["entry_time"]); d["exit_time"] = _ts(d["exit_time"])
    d["dir"] = np.where(d["direction"].astype(str).str.lower().isin(["long", "buy"]), 1, -1)
    d["g"] = pd.to_numeric(d["gross_r"], errors="coerce")
    return d


def _pos_series(d: pd.DataFrame, idx: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    out = {}
    for s, g in d.groupby("symbol"):
        v = np.zeros(len(idx), dtype=np.int8)
        for r in g.itertuples(index=False):
            m = (idx >= r.entry_time.floor("h")) & (idx < r.exit_time.ceil("h"))
            v[m] = r.dir
        out[s] = v
    return out


def distinct(new_rows: list[dict], ref_rows: dict[str, list[dict]], span: tuple[str, str]) -> dict:
    """D1 same-bar same-direction overlap share of the new leg's entries (<= 0.10); D2 |rho| hourly signed position (<= 0.30);
    D3 |rho| daily gross-R P&L (<= 0.30); D4 share of the new leg's in-position hours opposite to a ref leg on the same symbol (<= 0.05).
    Computed over the span intersected with each ref's coverage (needs >= 30 days of overlap; else read_state ``insufficient_overlap``)."""
    a, b = _ts(span[0]), _ts(span[1]) + pd.Timedelta(days=1)
    nw = _norm(new_rows); nw = nw[(nw.entry_time >= a) & (nw.entry_time < b)]
    res = {"span": list(span), "n_new": len(nw), "refs": {}, "pass": True}
    for name, rows in ref_rows.items():
        rf = _norm(rows)
        if rf.empty or nw.empty:
            res["refs"][name] = {"read_state": "empty"}; continue
        lo, hi = max(a, rf.entry_time.min()), min(b, rf.exit_time.max())
        if (hi - lo) < pd.Timedelta(days=30):
            res["refs"][name] = {"read_state": "insufficient_overlap", "overlap_days": max(0.0, (hi - lo).days)}; continue
        n2 = nw[(nw.entry_time >= lo) & (nw.entry_time < hi)]; r2 = rf[(rf.entry_time >= lo - pd.Timedelta(days=5)) & (rf.entry_time < hi)]
        d1 = float(np.mean([bool(((r2.symbol == r.symbol) & (r2.dir == r.dir) & ((r2.entry_time - r.entry_time).abs() <= pd.Timedelta(hours=1))).any())
                            for r in n2.itertuples(index=False)])) if len(n2) else None
        idx = pd.date_range(lo.floor("h"), hi.ceil("h"), freq="h", inclusive="left")
        pn, pr = _pos_series(n2, idx), _pos_series(r2, idx)
        syms = sorted(set(pn) | set(pr))
        vn = np.concatenate([pn.get(s, np.zeros(len(idx), np.int8)) for s in syms]).astype(float)
        vr = np.concatenate([pr.get(s, np.zeros(len(idx), np.int8)) for s in syms]).astype(float)
        d2 = float(np.corrcoef(vn, vr)[0, 1]) if vn.std() > 0 and vr.std() > 0 else 0.0
        days = pd.date_range(lo.floor("D"), hi.ceil("D"), freq="D", inclusive="left")
        dn = n2.groupby(n2.exit_time.dt.floor("D"))["g"].sum().reindex(days, fill_value=0.0).to_numpy()
        dr = r2.groupby(r2.exit_time.dt.floor("D"))["g"].sum().reindex(days, fill_value=0.0).to_numpy()
        d3 = float(np.corrcoef(dn, dr)[0, 1]) if dn.std() > 0 and dr.std() > 0 else 0.0
        inpos = sum(int((pn[s] != 0).sum()) for s in pn)
        opp = sum(int(((pn[s] != 0) & (pr.get(s, np.zeros(len(idx), np.int8)) == -pn[s])).sum()) for s in pn)
        d4 = opp / inpos if inpos else None
        ok = (d1 is not None and d1 <= 0.10) and abs(d2) <= 0.30 and abs(d3) <= 0.30 and (d4 is not None and d4 <= 0.05)
        res["refs"][name] = {"read_state": "ok", "overlap_days": int((hi - lo).days), "n_new_in_overlap": len(n2), "n_ref": len(r2),
                             "D1_same_bar_overlap_share": d1, "D2_position_rho": round(d2, 4), "D3_daily_pnl_rho": round(d3, 4),
                             "D4_opposite_hours_share": d4, "opposite_hours": opp, "in_position_hours": inpos, "pass": bool(ok)}
        res["pass"] = bool(res["pass"] and ok)
    if not any(v.get("read_state") == "ok" for v in res["refs"].values()):
        res["pass"] = None; res["read_state"] = "no_ref_with_overlap"
    return res


def load_refs(extra: list[str]) -> dict[str, list[dict]]:
    refs = {}
    for leg in ("trend_donchian_eth_prop", "trend_donchian_sol_prop", "eth_pullback_prop_2h"):
        f = REPO / "comms/strategy_evidence" / f"{leg}.json"
        if f.exists():
            sr = REPO / json.loads(f.read_text())["source_run"]
            if sr.exists():
                refs[leg] = [json.loads(x) for x in sr.read_text().splitlines() if x.strip()]
    ml = REPO / "docs/research/ml-entry-prop-gate-2026-11-02/ledgers/ml_entry_ethsol.jsonl"
    if ml.exists():
        refs["ml_entry_ethsol"] = [json.loads(x) for x in ml.read_text().splitlines() if x.strip()]
    for p in extra:
        refs[Path(p).stem] = [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
    return refs


# ----------------------------------------------------------------------------------------------- run
def selectable(grid: dict, select_from: str) -> list[dict]:
    """The eligible draws the selection may pick from. `select_from` is a comma list of arm names; "" = every arm (the default, so no existing unit changes).
    An arm outside the list is still graded and reported (a matched control), but is never selected and so never causes the held-out to be read."""
    allowed = {x.strip() for x in select_from.split(",") if x.strip()}
    return [g for g in grid.values() if g["eligible"] and (not allowed or g["arm"] in allowed)]


def run(a) -> int:
    global HOLDOUT_START, HOLDOUT_END, N_HELD_FLOOR, H, BAR_H, TAUS, DEV_START_FOLDS, DISC_END, DISC_FLOOR_TS, NEED_BASIS, NEED_BOOK, MODEL
    MODEL = getattr(a, "model", "lgbm")
    BAR_H = int(a.bar_hours); H = 48 // BAR_H
    NEED_BASIS = "F0+BASIS" in [x.strip() for x in (a.arms or "").split(",")]     # opt-in only: no other unit downloads or adds the basis columns
    NEED_BOOK = "F0+BOOK" in [x.strip() for x in (a.arms or "").split(",")]       # opt-in only: no other unit downloads or adds the book-depth columns
    if a.taus:
        TAUS = tuple(float(x) for x in a.taus.split(","))
    if a.rehearsal:     # exercises the held-out/finish path on a DEV window (2023-07..2023-12); the real held-out span is never loaded
        HOLDOUT_START, HOLDOUT_END, N_HELD_FLOOR = "2023-07-01", "2023-12-31", 5
    backward = False
    if a.heldout_span:      # RQ-20261105-d256-01: a time-disjoint held-out span; BEFORE --discovery-start = backward design
        HOLDOUT_START, HOLDOUT_END = a.heldout_span.split(":")
        if a.discovery_start:
            DEV_START_FOLDS = a.discovery_start
            DISC_FLOOR_TS = pd.Timestamp(a.discovery_start, tz="UTC")
            if pd.Timestamp(HOLDOUT_END, tz="UTC") < DISC_FLOOR_TS:
                backward = True
                DISC_END = a.discovery_end or "2026-10-01"
                gap_h = (DISC_FLOOR_TS - pd.Timestamp(HOLDOUT_END, tz="UTC") - pd.Timedelta(days=1)).total_seconds() / 3600
                need_h = 7 * 24 + (48 // int(a.bar_hours) + 1) * int(a.bar_hours)
                if gap_h < need_h:
                    raise SystemExit(f"backward held-out needs an embargo of {need_h} h between its end and --discovery-start; got {gap_h:.0f} h")
    prof = PROFILES[a.profile]; out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tab, fam, cov = build_table(cache, prof, a.smoke, a.rehearsal)
    full_tab = tab
    if DISC_FLOOR_TS is not None:     # discovery never sees rows before --discovery-start (the sealed backward span)
        tab = tab[tab.ts >= DISC_FLOOR_TS].reset_index(drop=True)
    (out / "coverage.json").write_text(json.dumps(cov, indent=1))
    cost = make_cost(prof); rp = Replay(cache, prof["symbols"] + CONTEXT_SYMBOLS, cost)
    folds = fold_bounds(a.smoke)
    arms = [n for n in FEATURE_SETS if not (n.endswith("F3") or "F3" in FEATURE_SETS[n])]
    if a.arms:
        want = [x.strip() for x in a.arms.split(",")]
        arms = [n for n in [*arms, *EXTRA_ARMS] if n in want]
    unavailable = [n for n in FEATURE_SETS if n not in arms]
    grid = {}
    for name in arms:
        cols = arm_cols(fam, name); preds = []
        for lo, hi in folds:
            te = tab[(tab.ts >= lo) & (tab.ts < hi)]; tr = purged_train(tab, lo)
            if len(tr) < 5000 or te.empty:
                continue
            p = fit_predict(tr, te, cols); preds.append((lo, te, p))
            print(f"[{name}] fold {lo:%Y-%m-%d} train={len(tr)} test={len(te)} t={time.time()-t0:.0f}s", flush=True)
        for tau in TAUS:
            led = []
            for lo, te, p in preds:
                led.append(run_policy(te, p, tau, rp).assign(fold=str(lo.date())))
            led = pd.concat(led, ignore_index=True) if led else pd.DataFrame()
            fn = led.groupby("fold")["net_r"].sum() if len(led) else pd.Series(dtype=float)
            usable = len(fn); posf = int((fn > 0).sum())
            grid[(name, tau)] = {"arm": name, "tau": tau, "n": len(led), "sum_net_r": round(float(led["net_r"].sum()), 3) if len(led) else 0.0,
                                 "folds_with_trades": usable, "folds_positive": posf,
                                 "eligible": bool(len(led) >= N_DISC_FLOOR and usable > 0 and posf >= math.ceil(2 * usable / 3)
                                                  and (not a.require_positive_sum or (len(led) and float(led["net_r"].sum()) > 0))), "_led": led}
    table = [{k: v for k, v in g.items() if k != "_led"} for g in grid.values()]
    elig = selectable(grid, a.select_from)
    res = {"schema": SCHEMA, "profile": a.profile, "smoke": bool(a.smoke), "rehearsal": bool(a.rehearsal), "bar_hours": BAR_H, "taus": list(TAUS), "horizon_bars": H, "arms_run": arms, "arms_unavailable": unavailable,
           "require_positive_sum": bool(a.require_positive_sum), "arm_denominator_registered": len(arms) * len(TAUS), "arms_graded": len(grid), "discovery_table": table,
           "folds": len(folds), "data_rows": len(tab), "elapsed_s": round(time.time() - t0)}
    if a.smoke:
        res.update({"verdict": "smoke", "read_state": "smoke_no_holdout"})
        (out / "result.json").write_text(json.dumps(res, indent=1)); print(json.dumps({k: res[k] for k in ("verdict", "arms_graded", "data_rows")}))
        print(pd.DataFrame(table).to_string()); return 0
    if not elig:
        res.update({"verdict": "FAIL", "read_state": "measured", "reason": "no arm x tau eligible on discovery (>= 100 trades and >= 2/3 of folds net-positive" + (" and discovery sum > 0)" if a.require_positive_sum else ")")
                    + (f"; selection restricted to {a.select_from}" if a.select_from else "")})
        return finish(out, res, prof, None, None)
    sel = max(elig, key=lambda g: g["sum_net_r"]); name, tau = sel["arm"], sel["tau"]
    res["selected"] = {"arm": name, "tau": tau, "discovery_sum_net_r": sel["sum_net_r"], "discovery_n": sel["n"]}
    if a.no_heldout:    # forward design: the held-out span is spent for this lane, so the selection is FROZEN here and graded later on bars that did not exist yet
        res.update({"verdict": "INDETERMINATE", "read_state": "measured", "reason": "forward_pending: an arm is eligible on discovery; the held-out span was NOT read (--no-heldout); grade it on the forward window",
                    "forward_pending": True})
        return finish(out, res, prof, None, None)
    cols = arm_cols(fam, name); hs = pd.Timestamp(HOLDOUT_START, tz="UTC")
    res["holdout_claim"] = claim = None if a.rehearsal else _claim(a, prof, f"{name}-tau{tau}")   # recorded BEFORE any held-out outcome
    held = full_tab[(full_tab.ts >= hs) & (full_tab.ts < pd.Timestamp(HOLDOUT_END, tz="UTC") + pd.Timedelta(days=1))]
    if backward:   # ONE fit on every discovery row (all strictly after the span + embargo, asserted at start), ONE read of the sealed span
        res["heldout_design"] = {"kind": "backward", "train_from": str(DISC_FLOOR_TS.date()), "train_to": DISC_END, "span": [HOLDOUT_START, HOLDOUT_END]}
        p = fit_predict(tab, held, cols)
    else:
        p = fit_predict(purged_train(tab, hs), held, cols)         # one fit; a re-read of the span is graded on the ledger's deflated bar
    hl = run_policy(held, p, tau, rp)
    dev = sel["_led"].drop(columns=["fold"])
    res["heldout"] = {"n": len(hl), "mean_net_r": float(hl["net_r"].mean()) if len(hl) else None}
    return finish(out, res, prof, hl, dev, held=held, extra_refs=a.ref_ledger, bar=(claim or {}).get("bar"))


def _claim(a, prof: dict, arm: str) -> dict:
    """Record the held-out read (family PROPML-<profile>) in a COPY of the holdout ledger inside the out dir (the runner does not
    commit the repo ledger; the lane appends the line). Re-reads are allowed and graded stricter (HOLDOUT-DEFLATED-REUSE)."""
    import shutil

    import holdout_lock as HL
    led = Path(a.out) / "holdout_reads.jsonl"
    if not led.exists() and HL.LEDGER.exists():
        shutil.copy(HL.LEDGER, led)
    return HL.claim_read(f"PROPML-{a.profile}-{BAR_H}h-{arm}", HOLDOUT_START, HOLDOUT_END, getattr(a, "unit", None) or Path(a.out).name,
                         "prop_ml_leg.py run", led, symbols=list(prof["symbols"]), family=f"PROPML-{a.profile}",
                         train_end=str((pd.Timestamp(HOLDOUT_START) - pd.Timedelta(days=1)).date()))


def finish(out: Path, res: dict, prof: dict, hl, dev, held=None, extra_refs=(), bar: dict | None = None) -> int:
    if hl is None:
        return _write(out, res, "indeterminate" if res.get("forward_pending") else "fail")
    rows = hl.to_dict("records")
    (out / "ledger_heldout.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out / "ledger_dev_oos.jsonl").write_text("\n".join(json.dumps(r) for r in dev.to_dict("records")) + "\n")
    n = len(hl)
    if n < N_HELD_FLOOR:
        res.update({"verdict": "INDETERMINATE", "read_state": "measured", "reason": "n_below_floor", "n_heldout": n, "floor": N_HELD_FLOOR})
        return _write(out, res, "indeterminate")
    net = hl["net_r"].to_numpy()
    bs = boot_ci(list(net), bar=bar)
    e1 = bool(net.mean() >= 0.10 and bs.get("ci_lo") is not None and bs["ci_lo"] > 0)
    # baselines on the identical held-out span
    b1 = {s: float(np.r_[held.loc[held.symbol == s, "net_long"].to_numpy(), held.loc[held.symbol == s, "net_short"].to_numpy()].mean()) for s in prof["symbols"]}
    b1_all = float(np.r_[held["net_long"].to_numpy(), held["net_short"].to_numpy()].mean())
    rng = np.random.default_rng(SEED); k_by = hl.groupby("symbol").size().to_dict(); draws = []
    cache_rows = {s: held[held.symbol == s].reset_index(drop=True) for s in k_by}
    for _ in range(RANDOM_DRAWS):
        tot = []
        for s, k in k_by.items():
            g = cache_rows[s]; pick = rng.integers(0, len(g), size=k); sd = rng.integers(0, 2, size=k)
            tot.append(np.where(sd == 1, g["net_long"].to_numpy()[pick], g["net_short"].to_numpy()[pick]))   # reference-TP bracket, random side
        draws.append(float(np.concatenate(tot).mean()))
    rand_p95 = float(np.percentile(draws, 95))
    refs = load_refs(list(extra_refs))
    b2 = None
    if "trend_donchian_eth_prop" in refs:
        d = _norm(refs["trend_donchian_eth_prop"]); d = d[(d.entry_time >= pd.Timestamp(HOLDOUT_START, tz="UTC")) & (d.entry_time < pd.Timestamp(HOLDOUT_END, tz="UTC") + pd.Timedelta(days=1))]
        if len(d):
            risk = (d["entry"].astype(float) - d["sl"].astype(float)).abs()
            hold_b = ((d.exit_time - d.entry_time).dt.total_seconds() / 3600.0).to_numpy()
            nr = d["g"].to_numpy() - make_cost(prof)(d["entry"].astype(float).to_numpy(), d["entry"].astype(float).to_numpy(), risk.to_numpy(), hold_b)
            b2 = {"n": len(d), "mean_net_r": float(nr.mean())}
    e2 = bool(net.mean() > 0 and net.mean() > b1_all and net.mean() > rand_p95 and (b2 is None or net.mean() > b2["mean_net_r"]))
    oos = pd.concat([dev, hl], ignore_index=True)
    e3 = regime_clause(oos)
    # E4: V3 prop gate on the held-out ledger (scripts/research/ml_variant_prop_gate.py, unchanged)
    gate_dir = out / "prop_gate"
    cmd = [sys.executable, str(REPO / "scripts/research/ml_variant_prop_gate.py"), "--variant", f"{res['profile']}-ml-leg", "--ledger", str(out / "ledger_heldout.jsonl"),
           "--out-dir", str(gate_dir), "--symbols", ",".join(prof["symbols"]), "--leg-key", prof["leg_key"], "--jobs", "4"] + \
          (["--edge-z", str(bar["ci_z"])] if bar else [])
    subprocess.run(cmd, check=True, cwd=str(REPO), stdout=subprocess.DEVNULL)
    gate = json.loads((gate_dir / "result.json").read_text())
    e4_by = {acct: {arm: gate["firms"][acct][arm]["v3_verdict"] for arm in ("ven", "cur")} for acct in prof["accounts"]} if gate.get("read_state") == "graded" else None
    acct_pass = [acct for acct, arms in (e4_by or {}).items() if all(v == "PASS" for v in arms.values())]
    e4 = bool(e4_by and (len(acct_pass) == len(e4_by) if prof["pass_rule"] == "all" else len(acct_pass) >= 1))
    dh = distinct(rows, refs, (HOLDOUT_START, HOLDOUT_END))
    dd = distinct(dev.to_dict("records") + rows, refs, ("2023-01-01", HOLDOUT_END))
    d_ok = bool(dh["pass"] and (dd["pass"] is not False)) if prof["grade_distinct"] else True   # bv: reported, not graded (no multi-firm rule between Breakout and Velotrade)
    res.update({"read_state": "measured", "n_heldout": n, "E1": {"pass": e1, "mean_net_r": float(net.mean()), "bootstrap": bs},
                "E2": {"pass": e2, "model_mean": float(net.mean()), "B0": 0.0, "B1_all_bars_mean": b1_all, "B1_by_symbol": b1,
                       "B1_random_p95_mean": rand_p95, "B1_random_median_mean": float(np.median(draws)), "B2_incumbent": b2, "random_draws": RANDOM_DRAWS},
                "E3": e3, "E4": {"pass": e4, "by_account": e4_by, "pass_accounts": acct_pass, "gate_read_state": gate.get("read_state"), "gate_n": gate.get("n")},
                "D_heldout": dh, "D_oos": dd, "D_pass": d_ok, "D_graded": prof["grade_distinct"], "refs_used": sorted(refs),
                "note": "unit stack is stricter than the gate's `ven` arm on slippage (3 bps/side vs 3 bps round trip); E1 uses the unit stack, E4 the gate's own arms"})
    edge_ok = e1 and e2 and e3["pass"] and e4
    verdict = "PASS" if (edge_ok and d_ok) else ("FAIL_DISTINCT" if edge_ok else "FAIL")
    res["verdict"] = verdict
    return _write(out, res, "pass" if verdict == "PASS" else "fail")


def _write(out: Path, res: dict, v: str) -> int:
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str))
    pop = f"profile {res['profile']}: pooled {'/'.join(PROFILES[res['profile']]['symbols'])}, held-out {HOLDOUT_START}..{HOLDOUT_END}, n={res.get('n_heldout', res.get('heldout', {}).get('n'))}"
    (out / "verdict.json").write_text(json.dumps({"verdict": v, "read_state": "measured" if res.get("read_state") in ("measured", None) or v != "indeterminate" else res.get("read_state"),
                                                  "population": pop, "n": res.get("n_heldout", 0),
                                                  "measurement": {k: res.get(k) for k in ("verdict", "selected", "E1", "E2", "E3", "E4", "D_pass", "arms_unavailable", "arms_graded")},
                                                  "note": f"{SCHEMA}; full record result.json; verdict_detail={res['verdict']}"}, default=str, indent=1))
    print(json.dumps({"verdict": res["verdict"], "selected": res.get("selected"), "n_heldout": res.get("n_heldout")}, default=str))
    return 0


# ----------------------------------------------------------------------------------------------- self-test
def _self_test() -> int:
    ok = True
    def check(n, c):
        nonlocal ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
    # B3: the ml_entry reference the unit registered (+0.01704 R, n 381, tradeify_1 ven arm, window 2025-10-01..2026-09-30)
    led = REPO / "docs/research/ml-entry-prop-gate-2026-11-02/ledgers/ml_entry_ethsol.jsonl"
    rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    edge = G.edge_ci(G.ledger_net_r(rows, "tradeify_1", "ven"))
    check(f"B3 reproduces n=381 (got {edge['n']})", edge["n"] == 381)
    check(f"B3 reproduces edge mean +0.01704 within 0.001 (got {edge['mean_r']})", abs(edge["mean_r"] - 0.01704) < 0.001)
    # B2: the incumbent's committed record (net_r_oos -0.2512 over n=165) is the sum of its ledger's net_r
    ev = json.loads((REPO / "comms/strategy_evidence/trend_donchian_eth_prop.json").read_text())
    tr = [json.loads(x) for x in (REPO / ev["source_run"]).read_text().splitlines() if x.strip()]
    check(f"B2 ledger n={len(tr)} equals the record's n_trades_oos {ev['n_trades_oos']}", len(tr) == ev["n_trades_oos"])
    check(f"B2 sum net_r {sum(float(r['net_r']) for r in tr):.4f} equals record {ev['net_r_oos']} within 0.001", abs(sum(float(r['net_r']) for r in tr) - ev["net_r_oos"]) < 0.001)
    # opt-in arms (2026-11-09): F0+OI is selectable by name only, carries the OI/flow columns and NOT the funding columns; the default arm list is unchanged
    fam_t = {"F0": ["a"], "F1": ["fund", "fund_z", "oi_chg24", "taker_ratio"], "F2": ["m_x"], "F3": [], "F1o": ["oi_chg24", "taker_ratio"]}
    default_arms = [n for n in FEATURE_SETS if not (n.endswith("F3") or "F3" in FEATURE_SETS[n])]
    _r = np.random.default_rng(1); _t = pd.DataFrame({"a": _r.normal(size=400), "b": _r.normal(size=400)}); _t.loc[::7, "b"] = np.nan
    for _s in ("long", "short"):
        _t[f"y_{_s}"] = (_t["a"] + _r.normal(size=400) > 0).astype(int); _t[f"mfe_{_s}"] = np.abs(_r.normal(2, 1, 400))
    _p = _fit_predict_logit(_t.iloc[:300], _t.iloc[300:], ["a", "b"])
    check("--model logit: NaN-safe, probabilities in (0,1), ONE constant TP per side inside [TP_LO, TP_HI]",
          _p[["p_long", "p_short"]].notna().all().all() and _p["p_long"].between(0, 1).all() and _p["tp_long"].nunique() == 1 and TP_LO <= _p["tp_long"].iloc[0] <= TP_HI)
    check("--model default is the registered LightGBM", MODEL == "lgbm")
    check("F0+OI is NOT in the default arm list", "F0+OI" not in default_arms and default_arms == ["F0", "F0+F1", "F0+F1+F2"])
    check("F0+OI = F0 + the OI/flow columns, no funding", arm_cols(fam_t, "F0+OI") == ["a", "oi_chg24", "taker_ratio"])
    check("F0 (price-only control) resolves to its own columns, not a KeyError", arm_cols(fam_t, "F0") == ["a"])
    check("F0+F1 still carries the funding columns", "fund" in arm_cols(fam_t, "F0+F1"))
    check("F1_OI_COLS holds no funding column", not any(c.startswith("fund") for c in F1_OI_COLS))
    check("tradeify_es is the ETH+SOL slice of tradeify with the same account, stack and leg key",
          PROFILES["tradeify_es"]["symbols"] == ["ETHUSDT", "SOLUSDT"] and all(PROFILES["tradeify_es"][k] == PROFILES["tradeify"][k]
          for k in ("accounts", "comm_bps_side", "slip_bps_side", "swap_bps_night", "leg_key", "pass_rule")))
    # F0+BASIS (2026-11-09): opt-in by name, the basis columns only (no funding, no OI), and the loader/features are point-in-time
    fam_b = dict(fam_t, F1b=list(BASIS_COLS))
    check("F0+BASIS is NOT in the default arm list", "F0+BASIS" not in default_arms and default_arms == ["F0", "F0+F1", "F0+F1+F2"])
    check("F0+BASIS = F0 + the four basis columns, nothing from F1", arm_cols(fam_b, "F0+BASIS") == ["a", *BASIS_COLS])
    check("BASIS_COLS holds no funding or OI column", not any(c.startswith(("fund", "oi_", "ls_", "taker")) for c in BASIS_COLS))
    m1 = pd.DataFrame({"ts": pd.date_range("2022-03-01 00:00", periods=125, freq="1min", tz="UTC"), "close": np.arange(125, dtype=float)})
    hp = hourly_premium(m1)
    check("hourly_premium stamps an hour when it has CLOSED and carries that hour's last 1m close",
          list(hp["ts"][:2]) == [pd.Timestamp("2022-03-01 01:00", tz="UTC"), pd.Timestamp("2022-03-01 02:00", tz="UTC")] and list(hp["premium"][:2]) == [59.0, 119.0])
    global BAR_H
    saved_bar = BAR_H; BAR_H = 4
    try:
        hrs = pd.date_range("2022-03-01 01:00", periods=600, freq="1h", tz="UTC")           # stamps; reading k = 0.001 * k
        prem0 = pd.DataFrame({"ts": hrs, "premium": 0.001 * np.arange(600)})
        kl_t = pd.DataFrame({"ts": pd.date_range("2022-03-02 00:00", periods=60, freq="4h", tz="UTC")})
        f_a = basis_features(kl_t, prem0)
        j = 10; close_j = kl_t["ts"][j] + pd.Timedelta(hours=4)
        want = 0.001 * (hrs <= close_j).sum() - 0.001                                       # the newest reading stamped <= the bar close
        check("basis is the newest hourly reading stamped at or before the bar CLOSE", abs(f_a["basis"][j] - want) < 1e-12)
        prem1 = prem0.copy(); prem1.loc[prem1.ts > close_j, "premium"] += 5.0                # change only readings AFTER bar j closes
        f_b = basis_features(kl_t, prem1)
        check("changing readings after a bar's close leaves that bar and every earlier bar unchanged (no look-ahead)",
              np.allclose(f_a.loc[:j, list(BASIS_COLS)].to_numpy(), f_b.loc[:j, list(BASIS_COLS)].to_numpy(), equal_nan=True) and not np.allclose(f_a.loc[j + 3:, "basis"], f_b.loc[j + 3:, "basis"]))
        prem2 = prem0[~((prem0.ts >= pd.Timestamp("2022-03-05 00:00", tz="UTC")) & (prem0.ts < pd.Timestamp("2022-03-05 20:00", tz="UTC")))]   # 20 h hole
        f_c = basis_features(kl_t, prem2)
        gap_bar = kl_t.index[(kl_t["ts"] + pd.Timedelta(hours=4) >= pd.Timestamp("2022-03-05 12:00", tz="UTC")) & (kl_t["ts"] + pd.Timedelta(hours=4) < pd.Timestamp("2022-03-05 20:00", tz="UTC"))]
        check("a reading older than BASIS_STALE_H at the bar close is NaN (a hole never carries a stale value forward)", len(gap_bar) > 0 and f_c.loc[gap_bar, "basis"].isna().all())
        cl = kl_t["ts"] + pd.Timedelta(hours=4)
        day_after = kl_t.index[(cl >= pd.Timestamp("2022-03-06 02:00", tz="UTC")) & (cl < pd.Timestamp("2022-03-06 18:00", tz="UTC"))]   # own reading fresh, 24 h-ago reference inside the hole
        check("the 24 h change is NaN while its reference hour sits in the hole, though the reading itself is fresh (exact 24 h shift on a complete grid)",
              len(day_after) > 0 and f_c.loc[day_after, "basis"].notna().all() and f_c.loc[day_after, "basis_chg24"].isna().all())
        ref_ok = kl_t.index[cl >= pd.Timestamp("2022-03-07 00:00", tz="UTC")][:3]
        check("the 24 h change is the exact difference of two readings 24 h apart when neither sits in a hole", len(ref_ok) > 0 and np.allclose(f_c.loc[ref_ok, "basis_chg24"], 0.024))
        check("no basis history before the first reading: NaN, not zero", basis_features(pd.DataFrame({"ts": pd.date_range("2021-01-01", periods=3, freq="4h", tz="UTC")}), prem0)["basis"].isna().all())
        check("no source at all: all four columns present and NaN", basis_features(kl_t, None)[list(BASIS_COLS)].isna().all().all())
        # F0+BOOK (2026-11-09): opt-in by name; the features are exactly book_depth_pit.FEATURES and are joined as of the bar CLOSE
        fam_d = dict(fam_t, F1d=list(BOOK_COLS))
        check("F0+BOOK is NOT in the default arm list", "F0+BOOK" not in default_arms)
        check("F0+BOOK = F0 + the book columns, nothing from F1", arm_cols(fam_d, "F0+BOOK") == ["a", *BOOK_COLS])
        check("BOOK_COLS is the builder's own feature list", BOOK_COLS == tuple(BD.FEATURES))
        T0 = pd.Timestamp("2022-03-02 04:00", tz="UTC")
        bt = pd.DataFrame({"T": pd.date_range(T0, periods=60, freq="4h"), **{c: np.arange(60, dtype=float) + k for k, c in enumerate(BOOK_COLS)}})
        kl_b = pd.DataFrame({"ts": pd.date_range("2022-03-02 00:00", periods=60, freq="4h", tz="UTC")})
        f_bk = book_features(kl_b, bt)
        check("the value for bar t is the table row stamped at t + BAR_H (the bar close)", all(f_bk[c][5] == 5.0 + k for k, c in enumerate(BOOK_COLS)))
        bt2 = bt.copy()
        bt2.loc[bt2["T"] > kl_b["ts"][5] + pd.Timedelta(hours=4), list(BOOK_COLS)] += 100.0   # change only rows stamped AFTER bar 5 closes
        f_bk2 = book_features(kl_b, bt2)
        check("changing table rows after a bar's close leaves that bar and every earlier bar unchanged (no look-ahead)",
              np.allclose(f_bk.loc[:5, list(BOOK_COLS)].to_numpy(), f_bk2.loc[:5, list(BOOK_COLS)].to_numpy()) and not np.allclose(f_bk.loc[7:, "imb1"], f_bk2.loc[7:, "imb1"]))
        check("a bar whose close has no table row is NaN, not zero", book_features(pd.DataFrame({"ts": pd.date_range("2021-01-01", periods=3, freq="4h", tz="UTC")}), bt)["imb1"].isna().all())
        check("no source at all: all book columns present and NaN", book_features(kl_b, None)[list(BOOK_COLS)].isna().all().all())
        g_t = {("F0", 0.5): {"arm": "F0", "eligible": True, "sum_net_r": 5.0}, ("F0+BOOK", 0.5): {"arm": "F0+BOOK", "eligible": False, "sum_net_r": 1.0}}
        check("default selection: every eligible arm may be selected (no existing unit changes)", [g["arm"] for g in selectable(g_t, "")] == ["F0"])
        check("--select-from F0+BOOK: an eligible control F0 is graded but NOT selectable, so the held-out is not read for it", selectable(g_t, "F0+BOOK") == [])
        g_t[("F0+BOOK", 0.5)]["eligible"] = True
        check("--select-from F0+BOOK: an eligible F0+BOOK cell is selectable", [g["arm"] for g in selectable(g_t, "F0+BOOK")] == ["F0+BOOK"])
    finally:
        BAR_H = saved_bar
    # D1-D4 on constructed ledgers
    base = pd.Timestamp("2026-01-01", tz="UTC")
    mk = lambda d, s, dr, h, g=1.0: {"symbol": s, "direction": dr, "entry_time": str(base + pd.Timedelta(days=d)), "exit_time": str(base + pd.Timedelta(days=d, hours=h)), "gross_r": g}
    A = [mk(i, "ETHUSDT", "long", 5, 1.0 if i % 2 else -1.0) for i in range(0, 90, 3)]
    same = distinct(A, {"same": A}, ("2026-01-01", "2026-04-30"))
    check("identical ledger FAILS (D1=1, |rho|=1)", same["pass"] is False and same["refs"]["same"]["D1_same_bar_overlap_share"] == 1.0)
    B = [mk(i + 1.5, "SOLUSDT", "short", 4, 1.0 if i % 3 else -1.0) for i in range(0, 90, 3)]
    far = distinct(A, {"far": B}, ("2026-01-01", "2026-04-30"))
    check(f"disjoint symbols/times PASS D1-D4 ({far['refs']['far']})", far["pass"] is True)
    C = [mk(i, "ETHUSDT", "short", 5) for i in range(0, 90, 3)]
    opp = distinct(A, {"opp": C}, ("2026-01-01", "2026-04-30"))
    check("opposite same-symbol positions FAIL D4", opp["refs"]["opp"]["D4_opposite_hours_share"] > 0.05 and opp["pass"] is False)
    short = distinct(A, {"tiny": A[:2]}, ("2026-01-01", "2026-01-10"))
    check("ref with <30 d overlap is insufficient_overlap, pass None (never a silent pass)", short["pass"] is None)
    cst = make_cost(PROFILES["tradeify"])(np.array([100.0]), np.array([100.0]), np.array([1.0]), np.array([24]))
    check(f"cost R: (2*(4+3)bps + 3.3bps*1d) on 100 / risk 1 = 0.1730 (got {float(cst[0]):.4f})", abs(float(cst[0]) - 0.1730) < 1e-4)
    print("SELF-TEST " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run"); r.add_argument("--profile", choices=sorted(PROFILES), required=True); r.add_argument("--out", required=True)
    r.add_argument("--cache", default="/tmp/prop_ml_cache"); r.add_argument("--smoke", action="store_true"); r.add_argument("--rehearsal", action="store_true"); r.add_argument("--bar-hours", type=int, default=1, choices=[1, 2, 4, 8]); r.add_argument("--taus", default=""); r.add_argument("--require-positive-sum", action="store_true"); r.add_argument("--arms", default=""); r.add_argument("--no-heldout", action="store_true"); r.add_argument("--model", choices=["lgbm", "logit"], default="lgbm", help="entry head: lgbm (registered default) or logit (low-capacity, RQ-20261112-7d41)"); r.add_argument("--ref-ledger", nargs="*", default=[])
    r.add_argument("--select-from", default="", help="comma list of arms the discovery selection may pick; other arms are graded controls and never selected (default: all)")
    r.add_argument("--heldout-span", default="", help="START:END (ISO dates); default the registered 2025-10-01:2026-09-30")
    r.add_argument("--discovery-start", default="", help="rows before it are excluded from discovery; with a held-out span ending before it = backward design")
    r.add_argument("--discovery-end", default="", help="backward design only: last discovery fold edge (default 2026-10-01)")
    d = sub.add_parser("distinct"); d.add_argument("--ledger", required=True); d.add_argument("--span-start", required=True); d.add_argument("--span-end", required=True)
    d.add_argument("--refs", nargs="*", default=[])
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.cmd == "run":
        return run(a)
    if a.cmd == "distinct":
        new = [json.loads(x) for x in Path(a.ledger).read_text().splitlines() if x.strip()]
        print(json.dumps(distinct(new, load_refs(a.refs), (a.span_start, a.span_end)), indent=1)); return 0
    ap.print_help(); return 2


if __name__ == "__main__":
    raise SystemExit(main())
