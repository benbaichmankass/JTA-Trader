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
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
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
LGB_PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=500, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=SEED, verbose=-1, n_jobs=4)
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
        except Exception:  # noqa: BLE001 - retried with backoff; a month that never arrives is recorded, not fatal
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch(cache: Path, symbols: list[str]) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    report = {}

    def one(sym: str) -> tuple[str, dict]:
        p = cache / f"{sym}.pkl"
        if p.exists():
            df = pd.read_pickle(p)
            return sym, {"rows": len(df), "cached": True}
        frames, missing = [], []
        for m in _months(START, END):
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
        df = df[(df.ts >= pd.Timestamp(START, tz="UTC")) & (df.ts < pd.Timestamp(END, tz="UTC") + pd.Timedelta(days=1))]
        df = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        df.to_pickle(p)
        return sym, {"rows": len(df), "missing_months": missing}

    with cf.ThreadPoolExecutor(8) as ex:
        for sym, rep in ex.map(one, symbols):
            report[sym] = rep
    return report


# ----------------------------------------------------------------------------------------------- labels
def bracket_outcome(o, h, l, c, entry, atr, side, sl_atr=SL_ATR, tp_atr=TP_ATR):
    """Vectorised first passage. o/h/l/c are (N, H) arrays of the H bars AFTER the decision bar (bar t+1..t+H);
    entry (N,) is bar t+1's open; side is +1 long / -1 short. Returns (exit_px, exit_j [1..H], reason) where reason
    0 = time, 1 = SL, 2 = TP. Tie (SL and TP touched in one bar) -> SL. Gap through the stop -> fill at the open."""
    n, H = o.shape
    risk = sl_atr * atr
    sl = entry - side * risk
    tp = entry + side * tp_atr * atr
    if side > 0:
        hit_sl = l <= sl[:, None]
        hit_tp = h >= tp[:, None]
        gap_sl = o <= sl[:, None]
    else:
        hit_sl = h >= sl[:, None]
        hit_tp = l <= tp[:, None]
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


def label_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Decision rows for one symbol: every DECISION_EVERY_H-th bar whose close is the decision time."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
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
    O, Hh, L, C = o[win], h[win], l[win], c[win]
    entry = O[:, 0]
    a = atr[cand]
    risk = SL_ATR * a
    out = {"i": cand, "ts": ts.to_numpy()[cand], "atr": a, "entry": entry}
    t_entry_s = (t_ns[cand + 1] / 1e9)
    for name, side in (("long", 1), ("short", -1)):
        px, j, reason = bracket_outcome(O, Hh, L, C, entry, a, side)
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
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------- features
def features_symbol(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = (df[k].astype(float) for k in ("close", "high", "low", "volume"))
    lr = np.log(c).diff()
    vol24 = lr.rolling(24).std()
    vol168 = lr.rolling(168).std()
    f = pd.DataFrame({"ts": df["ts"]})
    for k in (1, 4, 12, 24, 72, 168):
        f[f"ret_{k}"] = (np.log(c) - np.log(c.shift(k))) / (vol24 * np.sqrt(k))
    f["vol24"] = vol24
    f["vol_ratio"] = vol24 / vol168
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    f["atr_pct"] = tr.rolling(ATR_N).mean() / c
    for k in (24, 168):
        hi, lo = h.rolling(k).max(), l.rolling(k).min()
        f[f"range_pos_{k}"] = (c - lo) / (hi - lo).replace(0, np.nan)
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


def build_table(cache: Path, symbols: list[str], xs_symbols: list[str] | None = None) -> pd.DataFrame:
    """``xs_symbols`` None: cross-sectional context over ``symbols`` (the c692-01 recipe, unchanged). Given: context is
    computed against that fixed REFERENCE set for every row, so a row's inputs do not depend on which other symbols are
    in the table (the c692-04 training-universe arms)."""
    rows, feats = [], {}
    for sym in symbols:
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        f = features_symbol(df)
        feats[sym] = f
        lab = label_symbol(df)
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
def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    import lightgbm as lgb
    preds = []
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**LGB_PARAMS)
        m.fit(train[FEATURES], train[f"net_{side}"])
        preds.append(m.predict(test[FEATURES]))
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
    s = {"n": int(len(taken)), "mean_net_r": float(taken.net_r.mean()), "sum_net_r": float(taken.net_r.sum()),
         "mean_gross_r": float(taken.gross_r.mean()) if "gross_r" in taken else None,
         "mean_cost_r": float(taken.cost_r.mean()) if "cost_r" in taken else None,
         "n_symbols": int(taken.symbol.nunique())}
    if "side" in taken:
        s["by_side"] = {k: {"n": int(len(g)), "mean_net_r": float(g.net_r.mean())} for k, g in taken.groupby("side")}
        s["exit_reason_counts"] = {str({0: "time", 1: "sl", 2: "tp"}[k]): int(v)
                                   for k, v in taken.reason.value_counts().items()}
        by_sym = taken.groupby("symbol").net_r.sum()
        top = by_sym.abs().idxmax()
        ex = taken[taken.symbol != top]
        s["ex_max_symbol"] = {"symbol": top, "n": int(len(ex)), "mean_net_r": float(ex.net_r.mean()) if len(ex) else None}
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


def walk_forward(tab: pd.DataFrame) -> dict:
    dev = tab[tab.ts < pd.Timestamp(HOLDOUT_START, tz="UTC")]
    bounds = [pd.Timestamp(x, tz="UTC") for x in DEV_FOLDS] + [pd.Timestamp(HOLDOUT_START, tz="UTC")]
    folds, per_tau = [], {tau: [] for tau in TAU_GRID}
    for a, b in zip(bounds[:-1], bounds[1:]):
        test = dev[(dev.ts >= a) & (dev.ts < b)]
        # the fold's test rows must also stop H bars before b so no label reads past the fold
        test = test[test.ts < b - pd.Timedelta(hours=HORIZON_H + 1)]
        train = purge_train(dev, a)
        pl, ps = fit_predict(train, test)
        rec = {"test_start": str(a.date()), "test_end": str(b.date()), "n_train": int(len(train)), "n_test_rows": int(len(test))}
        for tau in TAU_GRID:
            tk = policy(test, pl, ps, tau)
            per_tau[tau].append(tk)
            rec[f"tau_{tau}"] = {"n": int(len(tk)), "mean_net_r": float(tk.net_r.mean()) if len(tk) else None}
        folds.append(rec)
        print(json.dumps(rec), flush=True)
    pooled = {}
    for tau in TAU_GRID:
        allk = pd.concat(per_tau[tau]) if per_tau[tau] else pd.DataFrame(columns=["net_r"])
        pooled[str(tau)] = {"n": int(len(allk)), "mean_net_r": float(allk.net_r.mean()) if len(allk) else None,
                            "folds_positive": int(sum(1 for f in folds if (f[f"tau_{tau}"]["mean_net_r"] or -1) > 0))}
    eligible = [t for t in TAU_GRID if pooled[str(t)]["n"] >= TAU_MIN_DEV_N and pooled[str(t)]["mean_net_r"] is not None]
    tau_star = max(eligible, key=lambda t: (pooled[str(t)]["mean_net_r"], t)) if eligible else None
    return {"folds": folds, "pooled_by_tau": pooled, "tau_star": tau_star,
            "tau_rule": f"argmax pooled dev mean net R per decision over TAU_GRID with dev n >= {TAU_MIN_DEV_N}; tie -> larger tau"}


def holdout(tab: pd.DataFrame, tau: float) -> dict:
    hs = pd.Timestamp(HOLDOUT_START, tz="UTC")
    train = purge_train(tab[tab.ts < hs], hs)
    test = tab[tab.ts >= hs]
    pl, ps = fit_predict(train, test)
    taken = policy(test, pl, ps, tau)
    res = {"n_train": int(len(train)), "n_test_rows": int(len(test)), "test_symbols": int(test.symbol.nunique()),
           "window": [str(test.ts.min()), str(test.ts.max())], "model": summarize(taken)}
    # baselines under identical mechanics
    res["baseline_no_trade"] = {"n": 0, "mean_net_r": 0.0}
    al = sequential_baseline(test, lambda r: "long")
    res["baseline_always_long"] = {"n": int(len(al)), "mean_net_r": float(al.net_r.mean())}
    ash = sequential_baseline(test, lambda r: "short")
    res["baseline_always_short_reported"] = {"n": int(len(ash)), "mean_net_r": float(ash.net_r.mean())}
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


def verdict(h: dict) -> tuple[str, str]:
    m = h["model"]
    n, mean, ns = m["n"], m["mean_net_r"], m.get("n_symbols", 0)
    if n < N_FLOOR or ns < SYMBOL_FLOOR:
        return "indeterminate", f"held-out n={n} (floor {N_FLOOR}) / symbols={ns} (floor {SYMBOL_FLOOR})"
    if mean >= 0:
        return "pass", f"held-out mean net R per decision {mean:+.4f} >= 0 at n={n}, {ns} symbols"
    return "fail", f"held-out mean net R per decision {mean:+.4f} < 0 at n={n}, {ns} symbols"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
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
    label_stats = {"rows": int(len(tab)), "dev_rows": int((tab.ts < pd.Timestamp(HOLDOUT_START, tz='UTC')).sum()),
                   "mean_net_long": float(tab.net_long.mean()), "mean_net_short": float(tab.net_short.mean()),
                   "mean_cost_r": float(tab.cost_long.mean()), "tie_rule": "SL", "entry": "next bar open"}
    wf = walk_forward(tab)
    if wf["tau_star"] is None:
        res = {"walk_forward": wf, "holdout": None}
        v, why = "indeterminate", f"no tau reached dev n >= {TAU_MIN_DEV_N}"
    else:
        h = holdout(tab, wf["tau_star"])
        v, why = verdict(h)
        res = {"walk_forward": wf, "holdout": h}
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
    import yaml
    acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())
    acc = acc.get("accounts", acc)
    return [str(x) for x in (acc["bybit_2"].get("symbols") or [])]


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
    for a, b in zip(bounds[:-1], bounds[1:]):
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
    pl, ps = models["long"].predict(test[FEATURES]), models["short"].predict(test[FEATURES])
    taken_all = policy(test, pl, ps, tau)
    taken = taken_all[taken_all.symbol.isin(traded)]
    m = summarize(taken)
    per_sym = {k: {"n": int(len(g)), "mean_net_r": float(g.net_r.mean())} for k, g in taken.groupby("symbol")}
    art = out / "model"
    art.mkdir(exist_ok=True)
    for side, mdl in models.items():
        mdl.booster_.save_model(str(art / f"entry_{side}.txt"))
    meta = {"schema": "ml_decision_entry_model/1", "features": FEATURES, "tau": tau, "train_rows": int(len(train)),
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
            "per_symbol": per_sym, "pooled_reproduction": {"n": int(len(taken_all)), "mean_net_r": meta["pooled_heldout_mean_net_r"]},
            "git_sha": meta["git_sha"], "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": m["n"], "measurement": meas, "note": why,
          "population": f"c692-01 frozen model (tau {tau}) held-out {HOLDOUT_START}..{END} decisions on the bybit_2 symbols {traded}"}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why, "pooled_reproduction": meas["pooled_reproduction"]}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- self-test
def _self_test() -> None:
    H = 4
    o = np.array([[100, 100, 100, 100.]]); h = o + 1; l = o - 1; c = o.copy()
    # long, atr=1 -> sl 98, tp 103: never hit -> time stop at close of bar H
    px, j, r = bracket_outcome(o, h, l, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 0 and j[0] == H and px[0] == 100.0
    # bar 2 touches both sl and tp -> SL (tie conservative)
    h2 = h.copy(); l2 = l.copy(); h2[0, 1] = 104; l2[0, 1] = 97
    px, j, r = bracket_outcome(o, h2, l2, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 1 and j[0] == 2 and px[0] == 98.0, (px, j, r)
    # gap through the stop at bar 3 open -> fill at that open (95), worse than 98
    o3 = o.copy(); o3[0, 2] = 95; l3 = l.copy(); l3[0, 2] = 94; h3 = h.copy(); h3[0, 2] = 96
    px, j, r = bracket_outcome(o3, h3, l3, c, np.array([100.]), np.array([1.]), +1)
    assert r[0] == 1 and j[0] == 3 and px[0] == 95.0, (px, j, r)
    # short: tp at 97 hit at bar 2 low
    l4 = l.copy(); l4[0, 1] = 96.5
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
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "universe-arms", "traded-subset"])
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_decision_entry_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--entry-summary", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "traded-subset":
        return traded_subset(a)
    return universe_arms(a) if a.cmd == "universe-arms" else run(a)


if __name__ == "__main__":
    sys.exit(main())
