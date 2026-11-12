#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-*-01.yaml (ENTRY decision model, lane ML-DECISION-MODELS); spec docs/research/ml-decision-models-2026-11-01/DESIGN.md section 2
"""ENTRY decision model: at a bar, go LONG / SHORT / NOTHING over a fixed horizon, pooled across symbols (Tier-1 research).

Spec: docs/research/ml-decision-models-2026-11-01/DESIGN.md section 2 (pre-registered). Not a strategy, not a grade of a
strategy's trades: the label is built from MARKET BARS alone, and one model is trained over every symbol of the frozen
60-perp universe (ML-DATA-BROAD-PATHS manifest bp2-f4271084b120) on a symbol-agnostic representation.

Pipeline (each stage deterministic given the inputs; the data is Binance Vision public klines, regenerable):

1. ``fetch``     1h USDT-M monthly klines for the 60 symbols, 2020-07..2026-09, cached under ``--cache``.
2. ``label``     decision bars every ``DECISION_EVERY_H`` hours; entry at the NEXT bar's open; reference bracket
                 SL = ``SL_ATR`` x ATR14, TP = ``TP_ATR`` x ATR14, time stop at ``HORIZON_H`` bars (exit at that bar's
                 close). First passage on bar high/low; a bar that touches both SL and TP is resolved as SL
                 (conservative); a bar that OPENS through the stop fills at its open (worse than the stop); a TP fills at
                 the TP price (no favourable gap credit). R = side x (exit - entry) / (SL distance). Net R subtracts the
                 full cost stack from ``src/runtime/execution_costs.roundtrip_cost_r``: fee ``FEE_BPS`` (the bybit:linear
                 measured round trip, applied to EVERY symbol), slippage ``resolve_cost_policy`` (3.0 bps perp),
                 funding 1.0 bps per 8h window crossed (directionless drag, the canonical model).
3. ``features``  point-in-time only (bar t's close is the last input): vol-normalised returns over 1..168 h, realised
                 vol and its ratio, ATR/price, position in the 24h / 168h range, volume z, hour / weekday, and
                 cross-sectional context at the same timestamp (the symbol's 24h-return rank across the universe,
                 BTC's 24h return and vol, universe breadth). No symbol id is a feature.
4. ``walk``      purged + embargoed expanding walk-forward on the DEVELOPMENT window only (< ``HOLDOUT_START``); two
                 LightGBM regressors (net R long, net R short) with fixed hyper-parameters; the policy takes the
                 better side when its prediction exceeds tau, one open position per symbol at a time; tau is chosen
                 from ``TAU_GRID`` on pooled dev OOS mean net R per decision subject to dev n >= ``TAU_MIN_DEV_N``.
5. ``holdout``   ONE final fit on all dev rows (purged + embargoed from the holdout) and ONE scoring of the sealed
                 held-out window with tau fixed, plus the registered baselines (no-trade, always-long, random at matched
                 rate and side mix, 200 draws).

    python3 scripts/research/ml_decision_entry.py run --cache /tmp/klines --out /tmp/out
    python3 scripts/research/ml_decision_entry.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import io
import itertools
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

SCHEMA = "ml_decision_entry/1"
MANIFEST = REPO / "comms/research/broad_paths/bp2-f4271084b120/manifest.json"
START, END = "2020-07-01", "2026-09-30"
HOLDOUT_START = "2025-10-01"          # sealed: never read by the dev walk-forward
DECISION_EVERY_H = 4
HORIZON_H = 24
SL_ATR, TP_ATR = 2.0, 3.0
ATR_N = 14
FEE_BPS = 11.0                        # bybit:linear measured round trip (resolve_fee_bps_roundtrip('BTCUSDT'))
EMBARGO_DAYS = 7
DEV_FOLDS = ["2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01",
             "2025-07-01"]           # each fold tests [start, next start) ; the last tests [2025-07-01, HOLDOUT_START)
TAU_GRID = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
TAU_MIN_DEV_N = 1000
N_FLOOR = 300                         # held-out decisions needed for a verdict
SYMBOL_FLOOR = 10                     # distinct symbols traded in the held-out
RANDOM_DRAWS = 200
SEED = 20261101
LGB_PARAMS = {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 500, "subsample": 0.8,
              "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": SEED, "verbose": -1,
              "n_jobs": 4}
_BASE = "https://data.binance.vision/data/futures/um/monthly/klines"


# ----------------------------------------------------------------------------------------------- fetch
def universe() -> list[str]:
    m = json.loads(MANIFEST.read_text())
    return [s["symbol"] for s in m["hash_inputs"]["symbols"]]


def _months(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start[:7], end[:7], freq="M")]


def _fetch_month(sym: str, month: str) -> pd.DataFrame | None:
    import requests
    url = f"{_BASE}/{sym}/1h/{sym}-1h-{month}.zip"
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            raw = zf.read(zf.namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            df = pd.read_csv(io.StringIO(raw), header=0 if first.startswith("open_time") else None)
            df = df.iloc[:, :6]
            df.columns = ["open_time", "open", "high", "low", "close", "volume"]
            return df
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch(cache: Path, symbols: list[str], end: str = END) -> dict:
    """``end`` other than END is used only by universe-costed, which passes its own cache directory."""
    cache.mkdir(parents=True, exist_ok=True)
    report = {}

    def one(sym: str) -> tuple[str, dict]:
        p = cache / f"{sym}.pkl"
        if p.exists():
            df = pd.read_pickle(p)
            return sym, {"rows": len(df), "cached": True}
        frames, missing = [], []
        for m in _months(START, end):
            d = _fetch_month(sym, m)
            if d is None:
                missing.append(m)
            else:
                frames.append(d)
        df = pd.concat(frames, ignore_index=True)
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        df = df[(df.ts >= pd.Timestamp(START, tz="UTC")) & (df.ts < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))]
        df = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        df.to_pickle(p)
        return sym, {"rows": len(df), "missing_months": missing}

    with cf.ThreadPoolExecutor(8) as ex:
        for sym, rep in ex.map(one, symbols):
            report[sym] = rep
    return report


# ----------------------------------------------------------------------------------------------- labels
def bracket_outcome(o, h, lo, c, entry, atr, side, sl_atr=SL_ATR, tp_atr=TP_ATR):
    """Vectorised first passage. o/h/l/c are (N, H) arrays of the H bars AFTER the decision bar (bar t+1..t+H);
    entry (N,) is bar t+1's open; side is +1 long / -1 short. Returns (exit_px, exit_j [1..H], reason) where reason
    0 = time, 1 = SL, 2 = TP. Tie (SL and TP touched in one bar) -> SL. Gap through the stop -> fill at the open."""
    n, H = o.shape
    risk = sl_atr * atr
    sl = entry - side * risk
    tp = entry + side * tp_atr * atr
    if side > 0:
        hit_sl = lo <= sl[:, None]
        hit_tp = h >= tp[:, None]
        gap_sl = o <= sl[:, None]
    else:
        hit_sl = h >= sl[:, None]
        hit_tp = lo <= tp[:, None]
        gap_sl = o >= sl[:, None]
    big = H + 1
    j_sl = np.where(hit_sl.any(1), hit_sl.argmax(1), big)
    j_tp = np.where(hit_tp.any(1), hit_tp.argmax(1), big)
    reason = np.zeros(n, dtype=np.int8)
    exit_j = np.full(n, H - 1)
    exit_px = c[:, H - 1].copy()
    sl_first = (j_sl <= j_tp) & (j_sl < big)
    tp_first = (j_tp < j_sl) & (j_tp < big)
    idx = np.arange(n)
    exit_j = np.where(sl_first, j_sl, np.where(tp_first, j_tp, exit_j))
    gap = gap_sl[idx, np.minimum(j_sl, H - 1)] & sl_first
    sl_fill = np.where(gap, o[idx, np.minimum(j_sl, H - 1)], sl)
    exit_px = np.where(sl_first, sl_fill, np.where(tp_first, tp, exit_px))
    reason = np.where(sl_first, 1, np.where(tp_first, 2, 0)).astype(np.int8)
    return exit_px, exit_j + 1, reason


def _cost_r(entry, exit_px, risk, t_entry_s, t_exit_s):
    """The canonical cost stack, vectorised: identical arithmetic to execution_costs.roundtrip_cost_r."""
    from src.runtime.execution_costs import FUNDING_WINDOW_HOURS, resolve_cost_policy
    slip_bps, fund_bps = resolve_cost_policy("BTCUSDT")
    per_r = ((np.abs(entry) + np.abs(exit_px)) / 2.0) / risk
    w = FUNDING_WINDOW_HOURS * 3600.0
    n_win = np.floor(t_exit_s / w) - np.floor(t_entry_s / w)
    fee = FEE_BPS / 1e4 * per_r
    slip = slip_bps / 1e4 * per_r
    fund = fund_bps / 1e4 * n_win * per_r
    return fee, slip, fund


def label_symbol(df: pd.DataFrame, recost_inputs: bool = False) -> pd.DataFrame:
    """Decision rows for one symbol: every DECISION_EVERY_H-th bar whose close is the decision time. ``recost_inputs``
    (universe-costed only) adds per_r_* / nwin_*; off by default so every other caller's frame is byte-identical."""
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(ATR_N, min_periods=ATR_N).mean().to_numpy()
    ts = df["ts"]
    close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
    N = len(df)
    H = HORIZON_H
    cand = np.where((close_hour % DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
    cand = cand[cand + H < N]
    # require the H forward bars to be contiguous hourly bars (no data hole)
    t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")   # explicit ns: pandas 3 parses to ms units
    contiguous = (t_ns[cand + H] - t_ns[cand]) == H * 3_600_000_000_000
    cand = cand[contiguous]
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
    entry = Ob[:, 0]
    a = atr[cand]
    risk = SL_ATR * a
    out = {"i": cand, "ts": ts.to_numpy()[cand], "atr": a, "entry": entry}
    t_entry_s = (t_ns[cand + 1] / 1e9)
    for name, side in (("long", 1), ("short", -1)):
        px, j, reason = bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side)
        gross = side * (px - entry) / risk
        # exit time: SL/TP fill inside bar j (use that bar's open time + 1h as a conservative upper bound);
        # a time stop exits at bar H's close
        t_exit_s = t_ns[cand + j] / 1e9 + 3600.0
        fee, slip, fund = _cost_r(entry, px, risk, t_entry_s, t_exit_s)
        out[f"gross_{name}"] = gross
        out[f"net_{name}"] = gross - fee - slip - fund
        out[f"cost_{name}"] = fee + slip + fund
        out[f"reason_{name}"] = reason
        out[f"bars_{name}"] = j
        if not recost_inputs:
            continue
        # re-costing inputs for universe-costed (a24c-01): price-per-R and funding windows crossed
        out[f"per_r_{name}"] = ((np.abs(entry) + np.abs(px)) / 2.0) / risk
        from src.runtime.execution_costs import FUNDING_WINDOW_HOURS
        w = FUNDING_WINDOW_HOURS * 3600.0
        out[f"nwin_{name}"] = np.floor(t_exit_s / w) - np.floor(t_entry_s / w)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------- features
def features_symbol(df: pd.DataFrame) -> pd.DataFrame:
    c, h, lo, v = (df[k].astype(float) for k in ("close", "high", "low", "volume"))
    lr = np.log(c).diff()
    vol24 = lr.rolling(24).std()
    vol168 = lr.rolling(168).std()
    f = pd.DataFrame({"ts": df["ts"]})
    for k in (1, 4, 12, 24, 72, 168):
        f[f"ret_{k}"] = (np.log(c) - np.log(c.shift(k))) / (vol24 * np.sqrt(k))
    f["vol24"] = vol24
    f["vol_ratio"] = vol24 / vol168
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    f["atr_pct"] = tr.rolling(ATR_N).mean() / c
    for k in (24, 168):
        hi, lw = h.rolling(k).max(), lo.rolling(k).min()
        f[f"range_pos_{k}"] = (c - lw) / (hi - lw).replace(0, np.nan)
    lv = np.log1p(v)
    f["vol_z"] = (lv - lv.rolling(168).mean()) / lv.rolling(168).std()
    up = lr.clip(lower=0).rolling(14).mean()
    dn = (-lr.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = up / (up + dn).replace(0, np.nan)
    close_ts = df["ts"] + pd.Timedelta(hours=1)
    f["hour"] = close_ts.dt.hour
    f["dow"] = close_ts.dt.dayofweek
    f["ret24_raw"] = np.log(c) - np.log(c.shift(24))
    return f


FEATURES = ["ret_1", "ret_4", "ret_12", "ret_24", "ret_72", "ret_168", "vol24", "vol_ratio", "atr_pct",
            "range_pos_24", "range_pos_168", "vol_z", "rsi14", "hour", "dow",
            "xs_rank_ret24", "btc_ret24", "btc_vol24", "breadth_up24", "rel_vol"]


def regrid_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex one symbol's bars onto a complete hourly grid so a data hole becomes NaN bars, not a seam. Without it the
    positional rolling features (ret_k, vol_ratio, vol_z, range_pos, atr) silently span the hole (ENTRY-GRADE-REPRO)."""
    full = pd.date_range(df["ts"].min(), df["ts"].max(), freq="1h", tz="UTC")
    return df.set_index("ts").reindex(full).rename_axis("ts").reset_index()


def build_table(cache: Path, symbols: list[str], xs_symbols: list[str] | None = None,
                recost_inputs: bool = False, hole_safe: bool = False) -> pd.DataFrame:
    """``xs_symbols`` None: cross-sectional context over ``symbols`` (the c692-01 recipe, unchanged). Given: context is
    computed against that fixed REFERENCE set for every row, so a row's inputs do not depend on which other symbols are
    in the table (the c692-04 training-universe arms)."""
    rows, feats = [], {}
    for sym in symbols:
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        if hole_safe:   # default off: every committed table/grade keeps its byte-identical build
            df = regrid_hourly(df)
        f = features_symbol(df)
        feats[sym] = f
        lab = label_symbol(df, recost_inputs=recost_inputs)
        lab = lab.join(f.drop(columns=["ts"]), on="i")
        lab["symbol"] = sym
        rows.append(lab)
    tab = pd.concat(rows, ignore_index=True)
    # cross-sectional context at the same timestamp (point-in-time: every input is <= bar t's close)
    r24 = pd.DataFrame({s: feats[s].set_index("ts")["ret24_raw"] for s in symbols})
    v24 = pd.DataFrame({s: feats[s].set_index("ts")["vol24"] for s in symbols})
    rank = r24.rank(axis=1, pct=True)
    breadth = (r24 > 0).sum(axis=1) / r24.notna().sum(axis=1)
    med_vol = v24.median(axis=1)
    key = pd.MultiIndex.from_arrays([tab["ts"], tab["symbol"]])
    if xs_symbols is None:
        tab["xs_rank_ret24"] = rank.stack().reindex(key).to_numpy()
    else:
        missing = [x for x in xs_symbols if x not in r24.columns]
        if missing:
            raise RuntimeError(f"cross-sectional reference symbols not in the table: {missing[:5]} (+{max(0, len(missing)-5)})")
        ref = r24[list(xs_symbols)]
        v24 = v24[ref.columns]
        breadth = (ref > 0).sum(axis=1) / ref.notna().sum(axis=1)
        med_vol = v24.median(axis=1)
        own = r24.stack().reindex(key).to_numpy()
        refv = ref.reindex(tab["ts"]).to_numpy()
        valid = (~np.isnan(refv)).sum(axis=1)
        less = (refv < own[:, None]).sum(axis=1)
        eq = (refv == own[:, None]).sum(axis=1)
        tab["xs_rank_ret24"] = np.where(valid > 0, (less + 0.5 * eq) / np.maximum(valid, 1), np.nan)
    tab["btc_ret24"] = r24["BTCUSDT"].reindex(tab["ts"]).to_numpy()
    tab["btc_vol24"] = v24["BTCUSDT"].reindex(tab["ts"]).to_numpy()
    tab["breadth_up24"] = breadth.reindex(tab["ts"]).to_numpy()
    tab["rel_vol"] = tab["vol24"].to_numpy() / med_vol.reindex(tab["ts"]).to_numpy()
    tab = tab.replace([np.inf, -np.inf], np.nan)
    tab = tab.dropna(subset=["net_long", "net_short", "ret_168", "vol_ratio"]).reset_index(drop=True)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    if tab.empty or tab.symbol.nunique() < max(1, len(symbols) // 2):
        raise RuntimeError(f"label table degenerate: rows={len(tab)} symbols={tab.symbol.nunique()} of {len(symbols)}")
    return tab


# ----------------------------------------------------------------------------------------------- model + policy
def fit_predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str] | None = None,
                n_jobs: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    import lightgbm as lgb
    feats = FEATURES if features is None else features
    params = LGB_PARAMS if n_jobs is None else {**LGB_PARAMS, "n_jobs": n_jobs}
    preds = []
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**params)
        m.fit(train[feats], train[f"net_{side}"])
        # provenance: predict — LGBMRegressor.predict is the regressed net R of that side, not a probability
        preds.append(m.predict(test[feats]))
    return preds[0], preds[1]


def policy(test: pd.DataFrame, p_long: np.ndarray, p_short: np.ndarray, tau: float) -> pd.DataFrame:
    """Sequential per symbol: at each decision bar with no open position, take the better side iff its predicted net R
    > tau; the position blocks the symbol until its exit bar. Returns the taken decisions."""
    t = test.assign(p_long=p_long, p_short=p_short).sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy_until = -1
        for row in g.itertuples(index=False):
            if row.i <= busy_until:
                continue
            side = "long" if row.p_long >= row.p_short else "short"
            p = row.p_long if side == "long" else row.p_short
            if p > tau:
                bars = getattr(row, f"bars_{side}")
                out.append((sym, row.ts, side, getattr(row, f"net_{side}"), getattr(row, f"gross_{side}"),
                            getattr(row, f"cost_{side}"), int(getattr(row, f"reason_{side}")), p))
                busy_until = row.i + bars
    return pd.DataFrame(out, columns=["symbol", "ts", "side", "net_r", "gross_r", "cost_r", "reason", "pred"])


def sequential_baseline(test: pd.DataFrame, choose, rng=None) -> pd.DataFrame:
    """A non-model policy under the same one-position-per-symbol mechanics. ``choose(rng)`` -> 'long'|'short'|None."""
    t = test.sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy_until = -1
        for row in g.itertuples(index=False):
            if row.i <= busy_until:
                continue
            side = choose(rng)
            if side is None:
                continue
            out.append((sym, getattr(row, f"net_{side}")))
            busy_until = row.i + getattr(row, f"bars_{side}")
    return pd.DataFrame(out, columns=["symbol", "net_r"])


def summarize(taken: pd.DataFrame) -> dict:
    if taken.empty:
        return {"n": 0, "mean_net_r": None}
    s = {"n": len(taken), "mean_net_r": float(taken.net_r.mean()), "sum_net_r": float(taken.net_r.sum()),
         "se_net_r": float(taken.net_r.std(ddof=1) / np.sqrt(len(taken))) if len(taken) > 1 else None,
         "mean_gross_r": float(taken.gross_r.mean()) if "gross_r" in taken else None,
         "mean_cost_r": float(taken.cost_r.mean()) if "cost_r" in taken else None,
         "n_symbols": int(taken.symbol.nunique())}
    if "side" in taken:
        s["by_side"] = {k: {"n": len(g), "mean_net_r": float(g.net_r.mean())} for k, g in taken.groupby("side")}
        s["exit_reason_counts"] = {str({0: "time", 1: "sl", 2: "tp"}[k]): int(v)
                                   for k, v in taken.reason.value_counts().items()}
        by_sym = taken.groupby("symbol").net_r.sum()
        top = by_sym.abs().idxmax()
        ex = taken[taken.symbol != top]
        s["ex_max_symbol"] = {"symbol": top, "n": len(ex), "mean_net_r": float(ex.net_r.mean()) if len(ex) else None}
        m = taken.assign(month=pd.to_datetime(taken.ts, utc=True).dt.strftime("%Y-%m")).groupby("month").net_r
        s["by_month"] = {k: {"n": int(v.count()), "mean_net_r": round(float(v.mean()), 4)} for k, v in m}
        rng = np.random.default_rng(SEED)
        bs = [taken.net_r.sample(len(taken), replace=True, random_state=int(rng.integers(1 << 31))).mean()
              for _ in range(500)]
        s["bootstrap_ci95_mean_net_r_reported_not_gating"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    return s


def purge_train(tab: pd.DataFrame, test_start: pd.Timestamp) -> pd.DataFrame:
    cut = test_start - pd.Timedelta(days=EMBARGO_DAYS) - pd.Timedelta(hours=HORIZON_H + 1)
    return tab[tab.ts < cut]


def walk_forward(tab: pd.DataFrame, features: list[str] | None = None, dev_folds: list[str] | None = None,
                 dev_end: str | None = None, n_jobs: int | None = None) -> dict:
    """Defaults reproduce c692-01 exactly (FEATURES, DEV_FOLDS, HOLDOUT_START); the optional arguments serve the v2 units."""
    end = dev_end or HOLDOUT_START
    dev = tab[tab.ts < pd.Timestamp(end, tz="UTC")]
    bounds = [pd.Timestamp(x, tz="UTC") for x in (dev_folds or DEV_FOLDS)] + [pd.Timestamp(end, tz="UTC")]
    folds, per_tau = [], {tau: [] for tau in TAU_GRID}
    for a, b in itertools.pairwise(bounds):
        test = dev[(dev.ts >= a) & (dev.ts < b)]
        # the fold's test rows must also stop H bars before b so no label reads past the fold
        test = test[test.ts < b - pd.Timedelta(hours=HORIZON_H + 1)]
        train = purge_train(dev, a)
        pl, ps = fit_predict(train, test, features, n_jobs)
        rec = {"test_start": str(a.date()), "test_end": str(b.date()), "n_train": len(train), "n_test_rows": len(test)}
        for tau in TAU_GRID:
            tk = policy(test, pl, ps, tau)
            per_tau[tau].append(tk)
            rec[f"tau_{tau}"] = {"n": len(tk), "mean_net_r": float(tk.net_r.mean()) if len(tk) else None,
                                 "sum_net_r": float(tk.net_r.sum()) if len(tk) else 0.0}
        folds.append(rec)
        print(json.dumps(rec), flush=True)
    pooled = {}
    for tau in TAU_GRID:
        allk = pd.concat(per_tau[tau]) if per_tau[tau] else pd.DataFrame(columns=["net_r"])
        pooled[str(tau)] = {"n": len(allk), "mean_net_r": float(allk.net_r.mean()) if len(allk) else None,
                            "folds_positive": int(sum(1 for f in folds if (f[f"tau_{tau}"]["mean_net_r"] or -1) > 0))}
    eligible = [t for t in TAU_GRID if pooled[str(t)]["n"] >= TAU_MIN_DEV_N and pooled[str(t)]["mean_net_r"] is not None]
    tau_star = max(eligible, key=lambda t: (pooled[str(t)]["mean_net_r"], t)) if eligible else None
    return {"folds": folds, "pooled_by_tau": pooled, "tau_star": tau_star,
            "tau_rule": f"argmax pooled dev mean net R per decision over TAU_GRID with dev n >= {TAU_MIN_DEV_N}; tie -> larger tau"}


def holdout(tab: pd.DataFrame, tau: float, features: list[str] | None = None, start: str | None = None,
            end: str | None = None, n_jobs: int | None = None) -> dict:
    """Defaults reproduce c692-01 (window = HOLDOUT_START..). v2 units pass their own sealed window; the CALLER must have
    claimed the read from scripts/research/holdout_lock.py first."""
    hs = pd.Timestamp(start or HOLDOUT_START, tz="UTC")
    train = purge_train(tab[tab.ts < hs], hs)
    test = tab[tab.ts >= hs]
    if end:
        test = test[test.ts < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    pl, ps = fit_predict(train, test, features, n_jobs)
    taken = policy(test, pl, ps, tau)
    res = {"n_train": len(train), "n_test_rows": len(test), "test_symbols": int(test.symbol.nunique()),
           "window": [str(test.ts.min()), str(test.ts.max())], "model": summarize(taken)}
    # baselines under identical mechanics
    res["baseline_no_trade"] = {"n": 0, "mean_net_r": 0.0}
    al = sequential_baseline(test, lambda r: "long")
    res["baseline_always_long"] = {"n": len(al), "mean_net_r": float(al.net_r.mean())}
    ash = sequential_baseline(test, lambda r: "short")
    res["baseline_always_short_reported"] = {"n": len(ash), "mean_net_r": float(ash.net_r.mean())}
    n_free = len(sequential_baseline(test, lambda r: "long"))  # free decision slots under always-take mechanics
    p_take = min(1.0, len(taken) / max(1, n_free))
    p_long = float((taken.side == "long").mean()) if len(taken) else 0.5
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(RANDOM_DRAWS):
        rd = sequential_baseline(test, lambda r: (("long" if r.random() < p_long else "short") if r.random() < p_take else None), rng)
        draws.append(float(rd.net_r.mean()) if len(rd) else 0.0)
    m = res["model"]["mean_net_r"]
    res["baseline_random_matched"] = {"draws": RANDOM_DRAWS, "p_take": p_take, "p_long": p_long,
                                      "mean_of_means": float(np.mean(draws)), "p95": float(np.percentile(draws, 95)),
                                      "model_percentile": float(np.mean([d < m for d in draws])) if m is not None else None}
    return res


def verdict(h: dict, bar: dict | None = None) -> tuple[str, str]:
    """``bar`` is the holdout ledger's deflated bar for this read (holdout_lock.claim_read(...)["bar"]). On the family's 1st read
    it is today's bar (mean >= 0); on the N-th read the mean must clear point_t_min standard errors (HOLDOUT-DEFLATED-REUSE)."""
    import holdout_lock as HL
    bar = bar or HL.bar_for(1)
    m = h["model"]
    n, mean, ns = m["n"], m["mean_net_r"], m.get("n_symbols", 0)
    if n < N_FLOOR or ns < SYMBOL_FLOOR:
        return "indeterminate", f"held-out n={n} (floor {N_FLOOR}) / symbols={ns} (floor {SYMBOL_FLOOR})"
    hurdle = f"{bar['point_t_min']:.2f} SE (read {bar['n_tries']} of the family on this window)"
    if HL.point_ok(mean, m.get("se_net_r"), bar):
        return "pass", f"held-out mean net R per decision {mean:+.4f} >= {hurdle} at n={n}, {ns} symbols"
    return "fail", f"held-out mean net R per decision {mean:+.4f} < {hurdle} at n={n}, {ns} symbols"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001  # allow-silent: provenance only; an empty sha is recorded, not hidden
        return ""


def run(args) -> int:
    cache, out = Path(args.cache), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = universe()
    t0 = time.time()
    fetch_rep = fetch(cache, syms)
    tab = build_table(cache, syms)
    data_fp = hashlib.sha256(pd.util.hash_pandas_object(tab[["ts", "symbol", "net_long", "net_short"]], index=False)
                             .to_numpy().tobytes()).hexdigest()[:16]
    print(f"table rows={len(tab)} symbols={tab.symbol.nunique()} fp={data_fp} t={time.time()-t0:.0f}s", flush=True)
    label_stats = {"rows": len(tab), "dev_rows": int((tab.ts < pd.Timestamp(HOLDOUT_START, tz='UTC')).sum()),
                   "mean_net_long": float(tab.net_long.mean()), "mean_net_short": float(tab.net_short.mean()),
                   "mean_cost_r": float(tab.cost_long.mean()), "tie_rule": "SL", "entry": "next bar open"}
    wf = walk_forward(tab)
    if wf["tau_star"] is None:
        res = {"walk_forward": wf, "holdout": None}
        v, why = "indeterminate", f"no tau reached dev n >= {TAU_MIN_DEV_N}"
    else:
        import holdout_lock as HL  # record the read BEFORE any held-out outcome is touched; a re-read is graded on a deflated bar
        claim = HL.claim_read(args.model_id if args.model_id != "ENTRY-v1-universe-costed" else f"ENTRY-v1-{args.unit or 'run'}",
                              HOLDOUT_START, END, args.unit or "unregistered-run", args.reader,
                              Path(args.ledger) if args.ledger else HL.LEDGER,
                              train_end=str((pd.Timestamp(HOLDOUT_START) - pd.Timedelta(days=1)).date()))
        h = holdout(tab, wf["tau_star"])
        v, why = verdict(h, claim["bar"])
        res = {"walk_forward": wf, "holdout": h, "holdout_claim": claim}
    summary = {"schema": SCHEMA, "unit": args.unit, "verdict": v, "why": why, "git_sha": _git_sha(),
               "data_fingerprint": data_fp, "config": {k: globals()[k] for k in (
                   "START", "END", "HOLDOUT_START", "DECISION_EVERY_H", "HORIZON_H", "SL_ATR", "TP_ATR", "ATR_N",
                   "FEE_BPS", "EMBARGO_DAYS", "DEV_FOLDS", "TAU_GRID", "TAU_MIN_DEV_N", "N_FLOOR", "SYMBOL_FLOOR",
                   "RANDOM_DRAWS", "SEED", "LGB_PARAMS", "FEATURES")},
               "fetch": {"symbols": len(fetch_rep), "missing_months": {k: v.get("missing_months") for k, v in fetch_rep.items() if v.get("missing_months")}},
               "labels": label_stats, **res, "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    hm = (res.get("holdout") or {}).get("model") or {}
    meas = {"heldout_mean_net_r_per_decision": hm.get("mean_net_r"), "heldout_n": hm.get("n"),
            "heldout_n_symbols": hm.get("n_symbols"), "tau_star": wf["tau_star"],
            "dev_pooled_by_tau": wf["pooled_by_tau"], "data_fingerprint": data_fp, "git_sha": summary["git_sha"]}
    if res.get("holdout"):
        h = res["holdout"]
        meas.update({k: h[k] for k in ("baseline_no_trade", "baseline_always_long", "baseline_always_short_reported",
                                       "baseline_random_matched", "window")},
                    model_detail={k: hm.get(k) for k in ("mean_gross_r", "mean_cost_r", "by_side", "exit_reason_counts",
                                                         "ex_max_symbol", "bootstrap_ci95_mean_net_r_reported_not_gating")})
    vj = {"verdict": v, "read_state": "measured", "n": hm.get("n"),
          "population": (f"ENTRY decision model held-out decisions {HOLDOUT_START}..{END} on the 60-perp universe "
                         f"bp2-f4271084b120 (Binance Vision 1h), one position per symbol, reference bracket "
                         f"SL {SL_ATR} ATR / TP {TP_ATR} ATR / {HORIZON_H}h time stop, net of fee {FEE_BPS} + slip 3.0 bps + funding 1 bps/8h"),
          "measurement": meas, "note": why}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- c692-04 universe arms
def traded_symbols() -> list[str]:
    """The bybit_2 data-pull list, re-parsed at run time (CLAUDE.md: never quote roster counts)."""
    from src.config.accounts_loader import load_accounts_dict
    return [str(x) for x in (load_accounts_dict()["bybit_2"].get("symbols") or [])]


def wide_universe() -> list[str]:
    """Every Binance Vision USDT-M perp passing the frozen-universe listing rule, with no cap (arm c)."""
    import broad_paths_corpus as bpc
    prefixes = bpc._s3_list(bpc._PREFIX)
    syms = [p.rstrip("/").split("/")[-1] for p in prefixes]
    syms = [x for x in syms if bpc._PERP.match(x)]
    spans = {}
    with cf.ThreadPoolExecutor(16) as ex:
        for sym, sp in zip(syms, ex.map(bpc._span, syms)):
            if sp:
                spans[sym] = sp
    return [r["symbol"] for r in bpc.select_universe(spans, n=10 ** 6)]


def arm_eval(tab: pd.DataFrame, train_syms: set, eval_syms: set) -> dict:
    hs = pd.Timestamp(HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    bounds = [pd.Timestamp(x, tz="UTC") for x in DEV_FOLDS] + [hs]
    per_tau = {t: [] for t in TAU_GRID}
    for a, b in itertools.pairwise(bounds):
        test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=HORIZON_H + 1)) & dev.symbol.isin(eval_syms)]
        train = purge_train(dev[dev.symbol.isin(train_syms)], a)
        pl, ps = fit_predict(train, test)
        for t in TAU_GRID:
            per_tau[t].append(policy(test, pl, ps, t))
    pooled = {str(t): {"n": int(sum(len(x) for x in v)),
                       "mean_net_r": float(pd.concat(v).net_r.mean()) if sum(len(x) for x in v) else None}
              for t, v in per_tau.items()}
    elig = [t for t in TAU_GRID if pooled[str(t)]["n"] >= TAU_MIN_DEV_N]
    tau = max(elig, key=lambda t: (pooled[str(t)]["mean_net_r"], t)) if elig else None
    res = {"n_train_symbols": len(train_syms), "dev_pooled_by_tau": pooled, "tau_star": tau}
    if tau is None:
        res.update(verdict="indeterminate", why=f"no tau reaches dev n >= {TAU_MIN_DEV_N}")
        return res
    train = purge_train(dev[dev.symbol.isin(train_syms)], hs)
    test = tab[(tab.ts >= hs) & tab.symbol.isin(eval_syms)]
    pl, ps = fit_predict(train, test)
    tk = policy(test, pl, ps, tau)
    m = summarize(tk)
    res["heldout"] = m
    res["_taken"] = tk
    if m["n"] < N_FLOOR:
        res.update(verdict="indeterminate", why=f"held-out n={m['n']} < {N_FLOOR}")
    elif m["mean_net_r"] >= 0:
        res.update(verdict="pass", why=f"held-out mean net R {m['mean_net_r']:+.4f} >= 0 at n={m['n']}")
    else:
        res.update(verdict="fail", why=f"held-out mean net R {m['mean_net_r']:+.4f} < 0 at n={m['n']}")
    return res


def universe_arms(args) -> int:
    cache, out = Path(args.cache), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    traded, frozen = traded_symbols(), universe()
    wide = sorted(set(wide_universe()) | set(frozen) | set(traded))
    fetch(cache, wide)
    tab = build_table(cache, wide, xs_symbols=frozen)
    print(f"rows={len(tab)} symbols={tab.symbol.nunique()} t={time.time()-t0:.0f}s", flush=True)
    ev = set(traded)
    arms = {"a_traded": set(traded), "b_frozen60": set(frozen), "c_wide": set(tab.symbol.unique())}
    results = {}
    for name, ts in arms.items():
        results[name] = arm_eval(tab, ts, ev)
        print(name, results[name]["verdict"], results[name]["why"], f"t={time.time()-t0:.0f}s", flush=True)
    paired = {}
    for x in ("b_frozen60", "c_wide"):
        if "heldout" in results[x] and "heldout" in results["a_traded"]:
            paired[f"{x}_minus_a_mean_net_r"] = results[x]["heldout"]["mean_net_r"] - results["a_traded"]["heldout"]["mean_net_r"]
    for r in results.values():
        r.pop("_taken", None)
    passing = [k for k, r in results.items() if r["verdict"] == "pass"]
    if passing:
        adopt = max(passing, key=lambda k: results[k]["heldout"]["mean_net_r"])
        v = "pass"
    else:
        cand = {k: r["dev_pooled_by_tau"][str(r["tau_star"])]["mean_net_r"] for k, r in results.items() if r["tau_star"] is not None}
        adopt = max(cand, key=cand.get) if cand else None
        v = "fail" if any(r["verdict"] == "fail" for r in results.values()) else "indeterminate"
    meas = {"traded_symbols": traded, "n_wide_symbols": len(arms["c_wide"]), "arms": results, "paired_vs_a": paired,
            "adopted_arm": adopt, "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    records = [{"verdict": r["verdict"], "read_state": "measured", "n": (r.get("heldout") or {}).get("n"),
                "population": f"arm {k}: trained on {r['n_train_symbols']} symbols, scored on traded {traded} held-out {HOLDOUT_START}..{END}",
                "measurement": {kk: r[kk] for kk in r if kk not in ("dev_pooled_by_tau",)}, "note": r["why"]}
               for k, r in results.items()]
    vj = {"verdict": v, "read_state": "measured", "n": sum((r.get("heldout") or {}).get("n") or 0 for r in results.values()),
          "population": f"ENTRY training-universe arms a/b/c scored on the traded symbols {traded}, held-out {HOLDOUT_START}..{END}",
          "measurement": meas, "note": f"adopted arm: {adopt}", "records": records}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "adopted": adopt}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- c692-06 traded subset
def fit_models(train: pd.DataFrame) -> dict:
    import lightgbm as lgb
    models = {}
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**LGB_PARAMS)
        m.fit(train[FEATURES], train[f"net_{side}"])
        models[side] = m
    return models


def traded_subset(args) -> int:
    """Precondition (b): the c692-01 final fit, unchanged, scored on the bybit_2 symbols. Also writes the frozen model
    artifact (LightGBM text dumps + feature list + tau + data fingerprint) that ML-ENTRY-LIVE-ADAPTER serves."""
    cache, out = Path(args.cache), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tau = json.loads(Path(args.entry_summary).read_text())["walk_forward"]["tau_star"]
    syms, traded = universe(), traded_symbols()
    fetch(cache, syms)
    tab = build_table(cache, syms)
    hs = pd.Timestamp(HOLDOUT_START, tz="UTC")
    train = purge_train(tab[tab.ts < hs], hs)
    models = fit_models(train)
    test = tab[tab.ts >= hs]
    # provenance: predict — LGBMRegressor.predict is the regressed net R of that side, not a probability
    pl, ps = models["long"].predict(test[FEATURES]), models["short"].predict(test[FEATURES])
    taken_all = policy(test, pl, ps, tau)
    taken = taken_all[taken_all.symbol.isin(traded)]
    m = summarize(taken)
    per_sym = {k: {"n": len(g), "mean_net_r": float(g.net_r.mean())} for k, g in taken.groupby("symbol")}
    art = out / "model"
    art.mkdir(exist_ok=True)
    for side, mdl in models.items():
        mdl.booster_.save_model(str(art / f"entry_{side}.txt"))
    meta = {"schema": "ml_decision_entry_model/1", "features": FEATURES, "tau": tau, "train_rows": len(train),
            "train_end_exclusive": str(train.ts.max()), "lgb_params": LGB_PARAMS, "bracket": {"sl_atr": SL_ATR, "tp_atr": TP_ATR,
            "atr_n": ATR_N, "horizon_h": HORIZON_H, "decision_every_h": DECISION_EVERY_H}, "xs_reference": syms,
            "git_sha": _git_sha(), "pooled_heldout_mean_net_r": summarize(taken_all)["mean_net_r"]}
    (art / "meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    if m["n"] < 30:
        v, why = "indeterminate", f"traded-symbol held-out n={m['n']} < 30"
    elif m["mean_net_r"] >= 0:
        v, why = "pass", f"traded-symbol held-out mean net R per decision {m['mean_net_r']:+.4f} >= 0 at n={m['n']}"
    else:
        v, why = "fail", f"traded-symbol held-out mean net R per decision {m['mean_net_r']:+.4f} < 0 at n={m['n']}"
    meas = {"traded_symbols": traded, "tau": tau, "traded": {k: m.get(k) for k in ("n", "mean_net_r", "sum_net_r", "mean_gross_r",
            "mean_cost_r", "by_side", "exit_reason_counts", "bootstrap_ci95_mean_net_r_reported_not_gating")},
            "per_symbol": per_sym, "pooled_reproduction": {"n": len(taken_all), "mean_net_r": meta["pooled_heldout_mean_net_r"]},
            "git_sha": meta["git_sha"], "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": m["n"], "measurement": meas, "note": why,
          "population": f"c692-01 frozen model (tau {tau}) held-out {HOLDOUT_START}..{END} decisions on the bybit_2 symbols {traded}"}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why, "pooled_reproduction": meas["pooled_reproduction"]}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- a24c-01 universe-costed
# RQ-20261101-a24c-01 (decision_rule RULE-RQ20261101-a24c-01-ENTRY-UNIVERSE-COSTED). Every constant below is copied from
# the unit as registered; none is a tuning knob.
UC_C_GRID = [10.0, 15.0, 20.0, 30.0, 50.0, float("inf")]
UC_DEV_MIN_N = 1000
UC_FWD_MIN_N = 300
UC_MIN_SYMBOLS = 10
UC_MAX_MISSING_COST = 0.10
UC_Q_USD = 5000.0
UC_N_TRIALS = 12                      # 6 C values x 2 arms
UC_FUND_BPS = 1.0
UC_FROZEN_FAMILY = "ENTRY-v1"         # any ledger claim whose model_id starts with this read the SAME frozen artifact
_DAILY = "https://data.binance.vision/data/futures/um/daily/klines"


def corwin_schultz_bps(h: np.ndarray, lo: np.ndarray) -> np.ndarray:
    """Corwin & Schultz (2012) two-bar high-low spread estimate, in bps, for each bar pair (t-1, t); negative -> 0."""
    h1, l1, h2, l2 = h[:-1], lo[:-1], h[1:], lo[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.log(h1 / l1) ** 2 + np.log(h2 / l2) ** 2
        gamma = np.log(np.maximum(h1, h2) / np.minimum(l1, l2)) ** 2
        k = 3.0 - 2.0 * np.sqrt(2.0)
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        s = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return np.r_[np.nan, np.clip(s, 0.0, None) * 1e4]


def cost_table(df: pd.DataFrame, tick: float, turnover_ratio: float, q_usd: float = UC_Q_USD,
               quoted_spread_bps: float | None = None) -> pd.DataFrame:
    """Per calendar month: spread_bps (CS monthly median, floored at one tick at the month's median price),
    sigma_daily, adv_bybit (Binance median daily quote volume x Bybit/Binance turnover ratio), impact_bps round trip
    = 2 x 1e4 x sigma_daily x sqrt(Q / adv_bybit)."""
    d = df.copy()
    d["cs"] = corwin_schultz_bps(d["high"].to_numpy(float), d["low"].to_numpy(float))
    d["month"] = d["ts"].dt.strftime("%Y-%m")
    d["day"] = d["ts"].dt.floor("D")
    daily = d.groupby("day").agg(close=("close", "last"), qv=("volume", lambda v: float((v * d.loc[v.index, "close"]).sum())))
    daily["lr"] = np.log(daily.close).diff()
    daily["month"] = daily.index.strftime("%Y-%m")
    out = []
    for m, g in d.groupby("month"):
        dg = daily[daily.month == m]
        px = float(g.close.median())
        tick_bps = 1e4 * tick / px if px > 0 else np.nan
        # re-registration 2026-11-05 (manager decision on lane ML-WEEK-1105 report 1): the venue's QUOTED spread floored at one
        # tick replaces the Corwin-Schultz estimate, which reads intrabar volatility as spread on 1h crypto bars
        # (comms/research/RQ-20261101-a24c-01/local-20261105/RESULT.md). CS is kept, reported, never used for cost.
        base = float(np.nanmedian(g.cs)) if quoted_spread_bps is None else float(quoted_spread_bps)
        spread = max(base, tick_bps)
        sig = float(dg.lr.std())
        adv = float(dg.qv.median()) * turnover_ratio
        imp = 2.0 * 1e4 * sig * np.sqrt(q_usd / adv) if adv > 0 and np.isfinite(sig) else np.nan
        out.append({"month": m, "spread_bps": spread, "cs_bps_reported": float(np.nanmedian(g.cs)), "tick_bps": tick_bps, "sigma_daily": sig, "adv_bybit": adv,
                    "impact_bps": imp})
    return pd.DataFrame(out)


def recost(tab: pd.DataFrame, costs: dict[str, pd.DataFrame], impact_mult: float = 1.0) -> pd.DataFrame:
    """Replace the flat slippage with each row's symbol-month spread + impact; fee and funding as c692-01. Adds
    ``rt_bps_{side}`` (fee + spread + impact + funding) and ``cost_ok``. ``impact_mult`` = sqrt(Q'/Q) for sensitivity."""
    t = tab.copy()
    t["month"] = t["ts"].dt.strftime("%Y-%m")
    c = pd.concat([v.assign(symbol=k) for k, v in costs.items()], ignore_index=True)[["symbol", "month", "spread_bps", "impact_bps"]]
    t = t.merge(c, on=["symbol", "month"], how="left")
    t["cost_ok"] = t.spread_bps.notna() & t.impact_bps.notna()
    var_bps = t.spread_bps + t.impact_bps * impact_mult
    for side in ("long", "short"):
        bps = FEE_BPS + var_bps + UC_FUND_BPS * t[f"nwin_{side}"]
        t[f"rt_bps_{side}"] = bps
        t[f"cost_{side}"] = t[f"per_r_{side}"] * bps / 1e4
        t[f"net_{side}"] = t[f"gross_{side}"] - t[f"cost_{side}"]
    return t


def choose_c(dev_scored: pd.DataFrame, taken: pd.DataFrame) -> dict:
    """The registered liquidity rule on the DEV folds only: symbol IN iff its dev median round-trip bps <= C; C =
    argmax pooled dev mean net R per decision (re-costed) with dev n >= UC_DEV_MIN_N; tie -> larger C."""
    med = dev_scored.groupby("symbol").apply(lambda g: float(np.nanmedian(np.r_[g.rt_bps_long, g.rt_bps_short])),
                                             include_groups=False)
    by_c = {}
    for C in UC_C_GRID:
        u = sorted(med[med <= C].index)
        tk = taken[taken.symbol.isin(u)]
        by_c[str(C)] = {"n": len(tk), "n_symbols": len(u), "mean_net_r": float(tk.net_r.mean()) if len(tk) else None,
                        "universe": u}
    elig = [C for C in UC_C_GRID if by_c[str(C)]["n"] >= UC_DEV_MIN_N and by_c[str(C)]["mean_net_r"] is not None]
    c_star = max(elig, key=lambda C: (by_c[str(C)]["mean_net_r"], C)) if elig else None
    return {"dev_median_rt_bps": {k: round(v, 2) for k, v in med.items()}, "by_c": by_c, "c_star": c_star}


def prior_reads(start: str, end: str, ledger: Path | None = None) -> list[dict]:
    import holdout_lock
    rows = holdout_lock._rows(ledger or holdout_lock.LEDGER)
    return [r for r in rows if r["model_id"].startswith(UC_FROZEN_FAMILY) and holdout_lock._overlap(r["start"], r["end"], start, end)]


def uc_verdict(c_star, fwd: dict | None, gate: dict | None, missing_share: float | None, prior: list,
               bar: dict | None = None) -> tuple[str, str]:
    """``prior`` reads of the frozen family no longer block the read (HOLDOUT-DEFLATED-REUSE, operator 2026-11-05): they raise the
    bar, which arrives as ``bar`` from the holdout ledger claim."""
    import holdout_lock as HL
    bar = bar or HL.bar_for(len(prior) + 1)
    if c_star is None:
        return "indeterminate", f"no C reaches dev n >= {UC_DEV_MIN_N}"
    n, ns = fwd["n"], fwd.get("n_symbols", 0)
    if n < UC_FWD_MIN_N or fwd["universe_size"] < UC_MIN_SYMBOLS:
        return "indeterminate", f"forward n={n} (floor {UC_FWD_MIN_N}) / |U(C)|={fwd['universe_size']} (floor {UC_MIN_SYMBOLS})"
    if missing_share is not None and missing_share > UC_MAX_MISSING_COST:
        return "indeterminate", f"cost model missing for {missing_share:.1%} of U(C) decisions (> {UC_MAX_MISSING_COST:.0%})"
    a_ok = HL.point_ok(fwd["mean_net_r"], fwd.get("se_net_r"), bar)
    b_ok = bool(gate and gate.get("passed"))
    why = (f"arm A forward mean net R {fwd['mean_net_r']:+.4f} at n={n}, {ns} symbols vs a {bar['point_t_min']:.2f}-SE hurdle (read "
           f"{bar['n_tries']} of the family on this window); arm B cost_gate {gate.get('reason') if gate else None}")
    return ("pass" if a_ok and b_ok else "fail"), why


def _binance_day_quote_volume(sym: str, day: str) -> float | None:
    import requests
    r = requests.get(f"{_DAILY}/{sym}/1d/{sym}-1d-{day}.zip", timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    raw = zf.read(zf.namelist()[0]).decode().strip().split("\n")
    row = raw[-1].split(",")
    return float(row[7])


def _frozen_models(served: Path):
    import lightgbm as lgb
    meta = json.loads(served.read_text())
    bt = meta["booster_txt"]
    bt = bt if isinstance(bt, dict) else json.loads(bt)
    return meta, {k: lgb.Booster(model_str=v) for k, v in bt.items()}


def universe_costed(args) -> int:
    cache, out = Path(args.cache) / f"thru-{args.fwd_end}", Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    specs = json.loads(Path(args.bybit_specs).read_text())
    meta, models = _frozen_models(Path(args.served))
    tau, feats = float(meta["tau"]), meta["features"]
    feats = feats if isinstance(feats, list) else json.loads(feats.replace("'", '"'))
    ref = meta["xs_reference"]
    ref = ref if isinstance(ref, list) else json.loads(ref.replace("'", '"'))
    listed = {k for k, v in specs.items() if v and v.get("status") == "Trading" and v.get("contractType") == "LinearPerpetual"}
    cands = [s for s in ref if s in listed]
    fetch(cache, ref, end=args.fwd_end)
    tab = build_table(cache, ref, xs_symbols=ref, recost_inputs=True)
    # costs per symbol-month
    snap_day = args.snapshot_day
    costs, dropped = {}, {}
    for sym in cands:
        qv = _binance_day_quote_volume(sym, snap_day)
        tv = float(specs[sym].get("turnover24h") or 0)
        if not qv or not tv:
            dropped[sym] = "no Bybit/Binance turnover ratio"
            continue
        df = pd.read_pickle(cache / f"{sym}.pkl")
        q = None
        if args.spread_source == "quoted":
            q = specs[sym].get("spread_bps")
            if q is None:
                dropped[sym] = "no quoted spread in the snapshot"
                continue
        costs[sym] = cost_table(df, float(specs[sym]["tickSize"]), tv / qv, quoted_spread_bps=q)
    tab = tab[tab.symbol.isin(list(costs))].reset_index(drop=True)
    sc = recost(tab, costs)
    hs, fs = pd.Timestamp(HOLDOUT_START, tz="UTC"), pd.Timestamp(args.fwd_start, tz="UTC")
    print(f"rows={len(sc)} cands={len(cands)} costed={len(costs)} dropped={len(dropped)} t={time.time()-t0:.0f}s", flush=True)
    # dev folds: the c692-01 recipe refit per fold (dev only, never >= HOLDOUT_START), the frozen tau, re-costed net
    dev = sc[sc.ts < hs]
    bounds = [pd.Timestamp(x, tz="UTC") for x in DEV_FOLDS] + [hs]
    full_dev = tab[tab.ts < hs]
    taken_dev = []
    for a, b in itertools.pairwise(bounds):
        test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=HORIZON_H + 1))]
        pl, ps = fit_predict(purge_train(full_dev, a), test)
        taken_dev.append(policy(test, pl, ps, tau))
    taken_dev = pd.concat(taken_dev, ignore_index=True)
    rule = choose_c(dev, taken_dev)
    c_star = rule["c_star"]
    prior = prior_reads(args.fwd_start, args.fwd_end, Path(args.ledger) if args.ledger else None)
    res = {"schema": "ml_decision_entry_universe_costed/1", "unit": args.unit, "tau": tau, "c_star": c_star,
           "liquidity_rule": rule, "candidates": cands, "dropped": dropped, "prior_reads_frozen": prior,
           "q_usd": UC_Q_USD, "snapshot_day": snap_day, "git_sha": _git_sha()}
    fwd, gate, missing, claim = None, None, None, None
    if c_star is not None:      # a prior read of the family raises the bar (claim["bar"]); it no longer blocks the read
        import holdout_lock
        claim = holdout_lock.claim_read(args.model_id, args.fwd_start, args.fwd_end, args.unit, args.reader,
                                        Path(args.ledger) if args.ledger else holdout_lock.LEDGER,
                                        train_end=str((hs - pd.Timedelta(days=1)).date()))   # family ENTRY
        U = rule["by_c"][str(c_star)]["universe"]
        fw = sc[(sc.ts >= fs) & (sc.ts < pd.Timestamp(args.fwd_end, tz="UTC") + pd.Timedelta(days=1)) & sc.symbol.isin(U)]
        # provenance: predict — Booster.predict is the regressed net R of that side, not a probability
        pl, ps = models["long"].predict(fw[feats]), models["short"].predict(fw[feats])
        tk = policy(fw, pl, ps, tau)
        fwd = {**summarize(tk), "universe_size": len(U), "universe": U}
        missing = float((~fw.cost_ok).mean()) if len(fw) else None
        # arm B: every opportunity row, better side by prediction, taken iff pred > tau
        side_long = pl >= ps
        net = np.where(side_long, fw.net_long, fw.net_short)
        taken_flag = np.maximum(pl, ps) > tau
        from ml.promotion.cost_gate import evaluate_cost_gate
        g = evaluate_cost_gate(list(zip(taken_flag.tolist(), net.astype(float).tolist())),
                               eval_cost_bases={"net_of_cost": len(fw)}, value_column="net_r", threshold=tau,
                               enforced=False, n_trials=UC_N_TRIALS)
        gate = g.to_dict()
        # reported, never gating
        flat = fw.copy()
        for side in ("long", "short"):
            flat[f"net_{side}"] = flat[f"gross_{side}"] - flat[f"per_r_{side}"] * (FEE_BPS + 3.0 + UC_FUND_BPS * flat[f"nwin_{side}"]) / 1e4
        res["reported"] = {
            "flat_3bps": summarize(policy(flat, pl, ps, tau))["mean_net_r"],
            "bybit2_symbols": summarize(tk[tk.symbol.isin(traded_symbols())]),
            "per_symbol": {k: {"n": len(v), "mean_net_r": float(v.net_r.mean())} for k, v in tk.groupby("symbol")},
            "impact_sensitivity": {}}
        for mult_name, q in (("q_x0.25", 0.25), ("q_x4", 4.0)):
            s2 = recost(tab[tab.symbol.isin(U)], costs, impact_mult=float(np.sqrt(q)))
            s2 = s2[(s2.ts >= fs) & (s2.ts < pd.Timestamp(args.fwd_end, tz="UTC") + pd.Timedelta(days=1))]
            # provenance: predict — Booster.predict is the regressed net R of that side, not a probability
            pl2, ps2 = models["long"].predict(s2[feats]), models["short"].predict(s2[feats])
            res["reported"]["impact_sensitivity"][mult_name] = summarize(policy(s2, pl2, ps2, tau))["mean_net_r"]
    v, why = uc_verdict(c_star, fwd, gate, missing, prior, (claim or {}).get("bar"))
    res.update({"verdict": v, "why": why, "forward": fwd, "arm_b_cost_gate": gate, "cost_missing_share": missing,
                "holdout_claim": claim, "elapsed_s": round(time.time() - t0)})
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": (fwd or {}).get("n"), "note": why,
          "population": (f"frozen ml_decision_entry_v1 (tau {tau}) decisions {args.fwd_start}..{args.fwd_end} on U(C*={c_star}) of the "
                         f"Bybit-listed c692-01 reference symbols, each re-costed fee {FEE_BPS} + Corwin-Schultz spread + sqrt impact "
                         f"(Q {UC_Q_USD:.0f} USD) + funding {UC_FUND_BPS} bps/8h"),
          "measurement": {k: res[k] for k in ("c_star", "forward", "arm_b_cost_gate", "prior_reads_frozen", "cost_missing_share",
                                              "holdout_claim") if k in res} | {"dev_by_c": {k: {kk: vv for kk, vv in x.items() if kk != "universe"}
                                                                                     for k, x in rule["by_c"].items()}}}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why, "c_star": c_star}), flush=True)
    return 0


def _self_test_universe_costed() -> None:
    import tempfile
    rng = np.random.default_rng(1)
    ts = pd.date_range("2024-01-01", periods=24 * 62, freq="h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(ts))))
    liquid = pd.DataFrame({"ts": ts, "open": c, "high": c * 1.002, "low": c * 0.998, "close": c, "volume": 1e6})
    thin = liquid.assign(high=c * 1.03, low=c * 0.97, volume=10.0)
    ct_l = cost_table(liquid, 0.0001, 1.0)
    ct_t = cost_table(thin, 0.0001, 0.1)
    assert (ct_t.spread_bps > ct_l.spread_bps).all() and (ct_t.impact_bps > 50 * ct_l.impact_bps).all(), (ct_l, ct_t)
    # a one-tick floor: a price-1 symbol with a 0.01 tick cannot quote tighter than 100 bps
    flat = liquid.assign(high=liquid.close, low=liquid.close, close=1.0)
    assert abs(cost_table(flat, 0.01, 1.0).spread_bps.iloc[0] - 100.0) < 1e-9
    # quoted source: a 0.01 bps quote on a wide-bar symbol is used as quoted (not the CS estimate), and still floored at one tick
    qt = cost_table(thin, 1e-7, 1.0, quoted_spread_bps=0.01)
    assert (qt.spread_bps == 0.01).all() and (qt.cs_bps_reported > 1.0).all(), qt
    assert abs(cost_table(flat, 0.01, 1.0, quoted_spread_bps=0.01).spread_bps.iloc[0] - 100.0) < 1e-9
    # the dev rule excludes the planted illiquid symbol at any finite C it fails, and takes the larger C on a tie
    dev = pd.DataFrame({"symbol": ["L"] * 4 + ["T"] * 4, "rt_bps_long": [14] * 4 + [400] * 4, "rt_bps_short": [14] * 4 + [400] * 4})
    taken = pd.DataFrame({"symbol": ["L"] * 1200 + ["T"] * 1200, "net_r": [0.05] * 1200 + [-0.3] * 1200})
    r = choose_c(dev, taken)
    assert r["c_star"] == 50.0 and r["by_c"]["50.0"]["universe"] == ["L"], r["by_c"]
    # recost: a 0-spread 0-impact month equals fee + funding only
    tab = pd.DataFrame({"symbol": ["L"], "ts": [ts[0]], "gross_long": [1.0], "gross_short": [-1.0], "per_r_long": [10.0],
                        "per_r_short": [10.0], "nwin_long": [3.0], "nwin_short": [3.0]})
    rc = recost(tab, {"L": pd.DataFrame({"month": ["2024-01"], "spread_bps": [0.0], "impact_bps": [0.0]})})
    assert abs(rc.net_long.iloc[0] - (1.0 - 10.0 * (FEE_BPS + 3.0) / 1e4)) < 1e-12
    # the window clause: a prior frozen-v1 read makes the verdict indeterminate whatever the numbers
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "reads.jsonl"
        led.write_text(json.dumps({"model_id": "ENTRY-v1-frozen-ref-x", "start": "2026-10-01", "end": "2026-10-31",
                                   "read_at": "t", "reader": "r", "unit": "u"}) + "\n")
        pr = prior_reads("2026-10-01", "2026-10-31", led)
        assert len(pr) == 1 and not prior_reads("2026-11-01", "2026-11-30", led)
        # a prior read no longer blocks (HOLDOUT-DEFLATED-REUSE): it raises the bar. mean 0.01 at se 0.05 clears read 1 (>= 0) but
        # not read 2 (needs >= 0.52 se, t here 0.2); mean 0.01 at se 0.005 (t = 2) clears both
        fw = {"n": 999, "n_symbols": 40, "universe_size": 40, "mean_net_r": 0.01, "se_net_r": 0.05}
        assert uc_verdict(50.0, fw, {"passed": True}, 0.0, pr)[0] == "fail"
        assert uc_verdict(50.0, fw, {"passed": True}, 0.0, [])[0] == "pass"
        assert uc_verdict(50.0, {**fw, "se_net_r": 0.005}, {"passed": True}, 0.0, pr)[0] == "pass"
    v, _ = uc_verdict(50.0, {"n": 999, "n_symbols": 40, "universe_size": 40, "mean_net_r": 0.01}, {"passed": True}, 0.0, [])
    assert v == "pass"
    v, _ = uc_verdict(50.0, {"n": 999, "n_symbols": 40, "universe_size": 40, "mean_net_r": 0.01}, {"passed": False, "reason": "x"}, 0.0, [])
    assert v == "fail"
    print("universe-costed self-test ok")


# ----------------------------------------------------------------------------------------------- self-test
def _self_test() -> None:
    H = 4
    o = np.array([[100, 100, 100, 100.]])
    h = o + 1
    lw = o - 1
    c = o.copy()
    # long, atr=1 -> sl 98, tp 103: never hit -> time stop at close of bar H
    px, j, r = bracket_outcome(o, h, lw, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 0 and j[0] == H and px[0] == 100.0
    # bar 2 touches both sl and tp -> SL (tie conservative)
    h2 = h.copy()
    l2 = lw.copy()
    h2[0, 1] = 104
    l2[0, 1] = 97
    px, j, r = bracket_outcome(o, h2, l2, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 1 and j[0] == 2 and px[0] == 98.0, (px, j, r)
    # gap through the stop at bar 3 open -> fill at that open (95), worse than 98
    o3 = o.copy()
    o3[0, 2] = 95
    l3 = lw.copy()
    l3[0, 2] = 94
    h3 = h.copy()
    h3[0, 2] = 96
    px, j, r = bracket_outcome(o3, h3, l3, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 1 and j[0] == 3 and px[0] == 95.0, (px, j, r)
    # short: tp at 97 hit at bar 2 low
    l4 = lw.copy()
    l4[0, 1] = 96.5
    px, j, r = bracket_outcome(o, h, l4, c, np.array([100.]), np.array([1.]), -1)
    assert r[0] == 2 and j[0] == 2 and px[0] == 97.0, (px, j, r)
    # cost arithmetic equals the canonical roundtrip_cost_r
    from src.runtime.execution_costs import roundtrip_cost_r
    ref = roundtrip_cost_r(entry=100.0, exit_price=103.0, risk=2.0, entry_time=0, exit_time=9 * 3600,
                           fee_bps_roundtrip=FEE_BPS, slippage_bps_roundtrip=3.0, funding_bps_per_window=1.0)
    fee, slip, fund = _cost_r(np.array([100.]), np.array([103.]), np.array([2.]), np.array([0.]), np.array([9 * 3600.]))
    assert abs((fee + slip + fund)[0] - ref["total_cost_r"]) < 1e-12, (fee + slip + fund, ref)
    # policy: one position per symbol at a time
    test = pd.DataFrame({"symbol": ["A"] * 3, "i": [0, 4, 30], "ts": pd.to_datetime(["2025-01-01"] * 3, utc=True),
                         "net_long": [1.0, 1.0, -1.0], "net_short": [0, 0, 0], "gross_long": [1, 1, -1],
                         "gross_short": [0, 0, 0], "cost_long": [.1] * 3, "cost_short": [.1] * 3,
                         "reason_long": [2, 2, 1], "reason_short": [0] * 3, "bars_long": [24, 24, 24], "bars_short": [24] * 3})
    tk = policy(test, np.array([1., 1., 1.]), np.array([0., 0., 0.]), 0.0)
    assert list(tk.net_r) == [1.0, -1.0], tk  # the i=4 bar is blocked by the open position from i=0
    t = traded_symbols()
    assert t and all(x.endswith("USDT") for x in t), t
    _self_test_universe_costed()
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "universe-arms", "traded-subset", "universe-costed"])
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_decision_entry_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--entry-summary", default="")
    ap.add_argument("--bybit-specs", default="comms/research/ML-ENTRY-UNIVERSE/local-20261101T1830Z/bybit_specs_20261101.json")
    ap.add_argument("--spread-source", choices=["quoted", "cs"], default="quoted",
                    help="quoted = the Bybit snapshot spread floored at one tick (a24c-01 as re-registered 2026-11-05); cs = Corwin-Schultz")
    ap.add_argument("--snapshot-day", default="2026-11-01", help="UTC day of the Bybit snapshot; Binance 1d quote volume of that day")
    ap.add_argument("--served", default=str(REPO / "ml/served/ml_decision_entry_v1/model.json"))
    ap.add_argument("--fwd-start", default="2026-10-01")
    ap.add_argument("--fwd-end", default="2026-10-31")
    ap.add_argument("--model-id", default="ENTRY-v1-universe-costed")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "traded-subset":
        return traded_subset(a)
    if a.cmd == "universe-costed":
        return universe_costed(a)
    return universe_arms(a) if a.cmd == "universe-arms" else run(a)


if __name__ == "__main__":
    sys.exit(main())
