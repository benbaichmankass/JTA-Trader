#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-383f-01.yaml (ml_entry MOVING TP, lane ML-ENTRY-TP-REVISION); spec docs/research/ml-decision-models-2026-11-01/TP-REVISION.md
"""ml_entry MOVING TP: a pooled first-passage model re-scored at each 4h check-in moves the TP (Tier-1 research).

Spec (pre-registered before any run): docs/research/ml-decision-models-2026-11-01/TP-REVISION.md; rule in
research/queue/RQ-20261101-383f-01.yaml. Builds on scripts/research/ml_decision_entry.py (labels, features, cost stack,
ENTRY policy) and the served ENTRY artifact ml/served/ml_decision_entry_v1/model.json, unchanged.

Stages of ``run``:
1. dev table from the monthly cache (2020-07..2026-09, the c692-01 table).
2. dev ENTRY OOS trades at the served tau: the c692-01 walk-forward folds (2022-01..2025-09, its recipe) + the served
   model on 2025-10..2026-09 (trained < 2025-09-22, so out of sample).
3. TP-model training rows: check-ins (4, 8, .., 20 bars held, SL not yet hit) of every candidate position (each decision
   row, both sides), random subsample; label = 18 classes (highest TP-grid level touched before the stop) x (stop hit).
4. TP-model walk-forward in yearly folds -> OOS class probabilities at every dev ENTRY trade check-in; the margin m is
   chosen on the pooled dev Δ; the best static entry-time TP is chosen on dev.
5. ONE read of the forward window (2026-10, Binance Vision DAILY 1h klines): final fit on all dev rows (purged +
   embargoed), served ENTRY trades, policy vs fixed 3 ATR TP with ties from 1m for both arms, controls, verdict.

    python3 scripts/research/ml_entry_tp_revision.py run --cache /tmp/ml_decision_klines --out /tmp/tpr_out
    python3 scripts/research/ml_entry_tp_revision.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import io
import itertools
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E  # noqa: E402

SCHEMA = "ml_entry_tp_revision/1"
UNIT = "RQ-20261101-383f-01"
SERVED = REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json"
GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]       # TP levels, x ATR14(entry) from entry
BASE_TP = 3.0
CHECKINS = [4, 8, 12, 16, 20]                          # bars held at each 4h check-in
MIN_GAP_ATR = 0.25                                     # a candidate rests >= this beyond the check-in close
VENUE_CAP_PCT = 0.099                                  # src/runtime/tp_venue_cap.TP_VENUE_CAP_PCT (asserted in self-test)
MARGINS = [0.0, 0.02, 0.05, 0.10]
N_CLASS = 2 * (len(GRID) + 1)                          # reach 0..8 x stop hit
TRAIN_MAX_ROWS = 1_500_000
TRAIN_FRAC = 0.10
FWD_START, FWD_END = "2026-10-01", "2026-10-31"
DEV_END = "2026-10-01"                                 # exclusive; the forward window starts here
TP_FOLDS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01", "2025-10-01", "2026-10-01"]
N_FLOOR, SYMBOL_FLOOR, MOVED_FLOOR = 300, 10, 30
RANDOM_DRAWS = 200
SEED = 20261101
TP_LGB = {"objective": "multiclass", "num_class": N_CLASS, "n_estimators": 200, "learning_rate": 0.05,
          "num_leaves": 31, "min_child_samples": 500, "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8,
          "reg_lambda": 5.0, "random_state": SEED, "verbose": -1, "n_jobs": 4}
STATE = ["side", "bars_held", "open_r", "mfe_r", "mae_r", "dist_sl_atr", "atr_ratio", "sret_4", "sret_24"]
TP_FEATURES = E.FEATURES + STATE
H = E.HORIZON_H


# ------------------------------------------------------------------------------------------------ data
def _daily(sym: str, day: str, tf: str) -> pd.DataFrame | None:
    import requests
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{sym}/{tf}/{sym}-{tf}-{day}.zip"
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            raw = zipfile.ZipFile(io.BytesIO(r.content))
            txt = raw.read(raw.namelist()[0]).decode()
            first = txt.split("\n", 1)[0]
            df = pd.read_csv(io.StringIO(txt), header=0 if first.startswith("open_time") else None).iloc[:, :6]
            df.columns = ["open_time", "open", "high", "low", "close", "volume"]
            return df
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def forward_cache(dev_cache: Path, fwd_cache: Path, symbols: list[str]) -> dict:
    """dev pickles + 2026-10 daily 1h zips -> fwd_cache. Symbols with no October data are reported and left out."""
    fwd_cache.mkdir(parents=True, exist_ok=True)
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(FWD_START, FWD_END, freq="D")]
    rep = {}

    def one(sym):
        frames = [d for d in (_daily(sym, day, "1h") for day in days) if d is not None]
        if not frames:
            return sym, {"oct_days": 0}
        new = _norm(pd.concat(frames, ignore_index=True))
        old = pd.read_pickle(dev_cache / f"{sym}.pkl")
        df = pd.concat([old, new], ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        df.to_pickle(fwd_cache / f"{sym}.pkl")
        return sym, {"oct_days": len(frames), "oct_rows": len(new)}

    with cf.ThreadPoolExecutor(12) as ex:
        for sym, r in ex.map(one, symbols):
            rep[sym] = r
    return rep


class OneMinute:
    """Same-bar SL/TP ties from Binance Vision daily 1m klines, fetched lazily per (symbol, day) and cached."""

    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.mem: dict = {}
        self.counts = {"no_tie": 0, "1m": 0, "still_ambiguous": 0, "no_1m_data": 0}

    def _day(self, sym: str, day: str):
        k = (sym, day)
        if k not in self.mem:
            p = self.cache / f"{sym}-{day}.pkl"
            if p.exists():
                self.mem[k] = pd.read_pickle(p)
            else:
                d = _daily(sym, day, "1m")
                d = None if d is None else _norm(d).set_index("ts")
                pd.to_pickle(d, p)
                self.mem[k] = d
        return self.mem[k]

    def resolve(self, sym: str, bar_ts: pd.Timestamp, side: int, sl: float, tp: float) -> str:
        d = self._day(sym, bar_ts.strftime("%Y-%m-%d"))
        if d is None:
            self.counts["no_1m_data"] += 1
            return "sl"
        m = d.loc[bar_ts: bar_ts + pd.Timedelta(minutes=59)]
        t0 = int(bar_ts.timestamp())
        mins = [{"time": int(ts.timestamp()), "high": float(hi), "low": float(lo)}
                for ts, hi, lo in zip(m.index, m["high"].to_numpy(), m["low"].to_numpy())]
        res = resolve_same_bar({"time": t0}, 3600, mins, side > 0, tp, sl)
        if res is None:
            self.counts["still_ambiguous"] += 1      # one 1m bar touched both, or the 1m data does not cover the bar
            return "sl"
        self.counts["1m"] += 1
        return "sl" if res == "invalidation_first" else "tp"


def _local_resolve_same_bar(bar, bar_s, bars_1m, up, tgt, inv):
    """Identical semantics to scripts/research/forecast_first_passage.py::resolve_same_bar (PR #22077, lane
    FORECAST-GRADE-FIRST-PASSAGE), used only while that module is not importable here."""
    if not bars_1m:
        return None
    lo, hi = bar["time"], bar["time"] + bar_s
    sub = [m for m in bars_1m if lo <= m["time"] < hi]
    if not sub or sub[0]["time"] > lo or len(sub) < bar_s // 60:
        return None
    for m in sub:
        i = (m["low"] <= inv) if up else (m["high"] >= inv)
        t = (m["high"] >= tgt) if up else (m["low"] <= tgt)
        if i and t:
            return None
        if i:
            return "invalidation_first"
        if t:
            return "target_first"
    return None


try:  # the shared same-bar resolver (manager 2026-11-01): reuse it, never fork it
    from forecast_first_passage import resolve_same_bar
    TIE_RESOLVER = "scripts/research/forecast_first_passage.py::resolve_same_bar"
except ImportError:  # not on this branch's base yet (#22077); identical semantics, asserted in the self-test once it lands
    resolve_same_bar = _local_resolve_same_bar
    TIE_RESOLVER = "local copy of forecast_first_passage.resolve_same_bar (PR #22077 not on base)"


# ------------------------------------------------------------------------------------------------ panel
def load_bars(cache: Path, symbols: list[str]) -> dict:
    return {s: pd.read_pickle(cache / f"{s}.pkl").reset_index(drop=True) for s in symbols}


def feature_panel(bars: dict) -> dict:
    """Per-symbol per-bar ENTRY features (FEATURES) for EVERY bar, with the cross-sectional block computed exactly as
    ml_decision_entry.build_table does (xs_symbols=None). Asserted equal to the table rows in ``run``."""
    feats = {s: E.features_symbol(df) for s, df in bars.items()}
    r24 = pd.DataFrame({s: f.set_index("ts")["ret24_raw"] for s, f in feats.items()})
    v24 = pd.DataFrame({s: f.set_index("ts")["vol24"] for s, f in feats.items()})
    rank = r24.rank(axis=1, pct=True)
    breadth = (r24 > 0).sum(axis=1) / r24.notna().sum(axis=1)
    med_vol = v24.median(axis=1)
    out = {}
    for s, f in feats.items():
        ts = f["ts"]
        g = f.copy()
        g["xs_rank_ret24"] = rank[s].reindex(ts).to_numpy()
        g["btc_ret24"] = r24["BTCUSDT"].reindex(ts).to_numpy()
        g["btc_vol24"] = v24["BTCUSDT"].reindex(ts).to_numpy()
        g["breadth_up24"] = breadth.reindex(ts).to_numpy()
        g["rel_vol"] = g["vol24"].to_numpy() / med_vol.reindex(ts).to_numpy()
        g = g.replace([np.inf, -np.inf], np.nan)
        pc = bars[s]["close"].shift(1)
        tr = pd.concat([bars[s]["high"] - bars[s]["low"], (bars[s]["high"] - pc).abs(), (bars[s]["low"] - pc).abs()],
                       axis=1).max(axis=1)
        g["atr"] = tr.rolling(E.ATR_N, min_periods=E.ATR_N).mean().to_numpy()
        out[s] = g
    return out


def windows(df: pd.DataFrame, i: np.ndarray):
    w = i[:, None] + np.arange(1, H + 1)[None, :]
    return tuple(df[k].to_numpy(float)[w] for k in ("open", "high", "low", "close"))


# ------------------------------------------------------------------------------------------------ check-in rows
def checkin_rows(sym: str, df: pd.DataFrame, pan: pd.DataFrame, i: np.ndarray, atr: np.ndarray, side: np.ndarray,
                 with_label: bool) -> pd.DataFrame:
    """One row per (position, check-in) with the SL not yet hit. ``side`` +1/-1 per position."""
    Ob, Hh, L, C = windows(df, i)
    entry = Ob[:, 0]
    risk = E.SL_ATR * atr
    sl = entry - side * risk
    fav = np.where(side[:, None] > 0, Hh, -L)                     # favourable extreme, sign-adjusted
    adv = np.where(side[:, None] > 0, L, -Hh)
    hit = np.where(side[:, None] > 0, L <= sl[:, None], Hh >= sl[:, None])
    j_sl = np.where(hit.any(1), hit.argmax(1) + 1, H + 1)        # 1-based first stop bar
    t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
    rows = []
    for jc in CHECKINS:
        alive = j_sl > jc
        if not alive.any():
            continue
        a = np.where(alive)[0]
        ic = i[a] + jc
        f = pan.iloc[ic]
        s = side[a]
        r = {"symbol": sym, "pos": a, "i": i[a], "ic": ic, "ts_checkin": df["ts"].to_numpy()[ic]}
        for k in E.FEATURES:
            r[k] = f[k].to_numpy()
        c_now = C[a, jc - 1]
        r["side"] = s.astype(float)
        r["bars_held"] = np.full(len(a), float(jc))
        r["open_r"] = s * (c_now - entry[a]) / risk[a]
        r["mfe_r"] = (fav[a, :jc].max(1) - np.where(s > 0, entry[a], -entry[a])) / risk[a]
        r["mae_r"] = (adv[a, :jc].min(1) - np.where(s > 0, entry[a], -entry[a])) / risk[a]
        r["dist_sl_atr"] = s * (c_now - sl[a]) / atr[a]
        r["atr_ratio"] = f["atr"].to_numpy() / atr[a]
        r["sret_4"] = s * f["ret_4"].to_numpy()
        r["sret_24"] = s * f["ret_24"].to_numpy()
        if with_label:
            # reach over bars jc+1 .. j_sl-1 (bars before the stop bar: ties SL-first)
            js = j_sl[a]
            mask = (np.arange(1, H + 1)[None, :] > jc) & (np.arange(1, H + 1)[None, :] < js[:, None])
            fa = np.where(mask, fav[a], -np.inf).max(1)
            reach_atr = (fa - np.where(s > 0, entry[a], -entry[a])) / atr[a]
            ridx = np.searchsorted(np.array(GRID), reach_atr, side="right")       # levels <= reach
            stop = js <= H
            # outcome net R of the path WITHOUT a TP (stop fill or the 24-bar close)
            jj = np.minimum(js, H) - 1
            o_sl = Ob[a, jj]
            gap = np.where(s > 0, o_sl <= sl[a], o_sl >= sl[a])
            px = np.where(stop, np.where(gap, o_sl, sl[a]), C[a, H - 1])
            j_exit = np.where(stop, js, H)
            fee, slip, fund = E._cost_r(entry[a], px, risk[a], t_ns[i[a] + 1] / 1e9, t_ns[i[a] + j_exit] / 1e9 + 3600.0)
            r["y"] = (ridx + (len(GRID) + 1) * stop).astype(int)
            r["path_net_r"] = s * (px - entry[a]) / risk[a] - fee - slip - fund
        rows.append(pd.DataFrame(r))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def training_rows(tab: pd.DataFrame, bars: dict, panel: dict, end_excl: pd.Timestamp, rng_seed: int) -> pd.DataFrame:
    """Candidate positions (each decision row x both sides) with decision ts < end_excl; random subsample."""
    rng = np.random.default_rng(rng_seed)
    parts = []
    for sym, g in tab[tab.ts < end_excl].groupby("symbol"):
        for s in (1, -1):
            keep = rng.random(len(g)) < TRAIN_FRAC
            gg = g[keep]
            if gg.empty:
                continue
            parts.append(checkin_rows(sym, bars[sym], panel[sym], gg["i"].to_numpy(), gg["atr"].to_numpy(),
                                      np.full(len(gg), s), True))
    out = pd.concat(parts, ignore_index=True)
    if len(out) > TRAIN_MAX_ROWS:
        out = out.sample(TRAIN_MAX_ROWS, random_state=rng_seed)
    return out


def fit_tp_model(train: pd.DataFrame):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(**TP_LGB)
    y = train["y"].to_numpy()
    m.fit(train[TP_FEATURES], y)
    cls = list(m.classes_)
    means = np.zeros(N_CLASS)
    for c in range(N_CLASS):
        sel = y == c
        means[c] = float(train["path_net_r"].to_numpy()[sel].mean()) if sel.any() else 0.0
    return {"model": m, "classes": cls, "class_mean_net_r": means,
            "class_counts": np.bincount(y, minlength=N_CLASS).tolist(), "n_train": len(train)}


def predict_probs(tm: dict, rows: pd.DataFrame) -> np.ndarray:
    # provenance: predict_proba — LGBMClassifier class probabilities of the 18 first-passage classes (MEASURED model output)
    p = tm["model"].predict_proba(rows[TP_FEATURES])
    full = np.zeros((len(rows), N_CLASS))
    full[:, tm["classes"]] = p
    return full


# ------------------------------------------------------------------------------------------------ policy + walker
def expected_net_r(probs: np.ndarray, means: np.ndarray, level_cost_r: np.ndarray) -> np.ndarray:
    """(K,) expected net R of a TP at each grid level q, from one row of 18 class probabilities."""
    G = len(GRID) + 1
    p_free, p_stop = probs[:G], probs[G:]
    m_free, m_stop = means[:G], means[G:]
    out = np.empty(len(GRID))
    for q in range(1, len(GRID) + 1):
        p_tp = p_free[q:].sum() + p_stop[q:].sum()
        rest = (p_free[:q] * m_free[:q]).sum() + (p_stop[:q] * m_stop[:q]).sum()
        out[q - 1] = p_tp * (GRID[q - 1] / E.SL_ATR - level_cost_r[q - 1]) + rest
    return out


def valid_levels(side: int, entry: float, atr: float, close: float) -> np.ndarray:
    lv = entry + side * np.array(GRID) * atr
    beyond = side * (lv - close) >= MIN_GAP_ATR * atr
    cap = np.abs(lv - close) <= VENUE_CAP_PCT * close
    return beyond & cap


def walk(Ob, Hh, L, C, entry, atr, side, chooser, tie=None):
    """Sequential first passage with a TP that may move at each check-in (applies from the next bar). SL fixed.
    Gap rule and tie rule exactly as ml_decision_entry.bracket_outcome (tie -> ``tie`` callback, default SL).
    ``chooser(jc, tp_level_idx) -> new level idx | None``. Returns (exit_px, exit_j, reason, moves)."""
    risk = E.SL_ATR * atr
    sl = entry - side * risk
    q = GRID.index(BASE_TP)
    tp = entry + side * GRID[q] * atr
    moves = []
    for j in range(1, H + 1):
        o, h, lo = Ob[j - 1], Hh[j - 1], L[j - 1]
        hit_sl = lo <= sl if side > 0 else h >= sl
        hit_tp = h >= tp if side > 0 else lo <= tp
        if hit_sl and hit_tp and tie is not None:
            gap = o <= sl if side > 0 else o >= sl
            res = "sl" if gap else tie(j, sl, tp)
            hit_sl, hit_tp = res == "sl", res == "tp"
        if hit_sl:
            gap = o <= sl if side > 0 else o >= sl
            return (o if gap else sl), j, 1, moves
        if hit_tp:
            return tp, j, 2, moves
        if j in CHECKINS and chooser is not None:
            nq = chooser(j, q)
            if nq is not None and nq != q:
                moves.append((j, q, nq))
                q = nq
                tp = entry + side * GRID[q] * atr
    return C[H - 1], H, 0, moves


def trade_net(entry, px, j, atr, t_ns, i):
    risk = E.SL_ATR * atr
    fee, slip, fund = E._cost_r(np.array([entry]), np.array([px]), np.array([risk]), np.array([t_ns[i + 1] / 1e9]),
                                np.array([t_ns[i + j] / 1e9 + 3600.0]))
    return float((px - entry) / risk), float((fee + slip + fund)[0])


class Scorer:
    """Scores a trade set under: fixed TP (any grid level), the model policy (margin m), matched random moves."""

    def __init__(self, trades: pd.DataFrame, bars: dict, probs: dict, means: np.ndarray, tie_maker=None):
        self.trades = trades.reset_index(drop=True)
        self.bars, self.probs, self.means = bars, probs, means
        self.tie_maker = tie_maker
        self.t_ns = {s: df["ts"].to_numpy().astype("datetime64[ns]").astype("int64") for s, df in bars.items()}
        self.win = {}
        for k, t in self.trades.iterrows():
            df = bars[t.symbol]
            Ob, Hh, L, C = windows(df, np.array([t.i]))
            self.win[k] = (Ob[0], Hh[0], L[0], C[0])

    def _one(self, k, chooser_factory):
        t = self.trades.loc[k]
        s = 1 if t.side == "long" else -1
        Ob, Hh, L, C = self.win[k]
        entry = Ob[0]
        ch = chooser_factory(k, t, s, entry, C) if chooser_factory else None
        tie = self.tie_maker(t, s) if self.tie_maker else None
        px, j, reason, moves = walk(Ob, Hh, L, C, entry, t.atr, s, ch, tie)
        g, c = trade_net(entry, px, j, t.atr, self.t_ns[t.symbol], int(t.i))
        return s * g - c, reason, moves

    def fixed(self, level: float):
        """Hold-to-bracket with the entry-time TP at ``level`` (BASE_TP = the baseline exactly as ml_entry trades)."""
        if level == BASE_TP:
            return [self._one(k, None) for k in self.trades.index]
        q0 = GRID.index(level)
        out = []
        for k in self.trades.index:
            t = self.trades.loc[k]
            s = 1 if t.side == "long" else -1
            Ob, Hh, L, C = self.win[k]
            px, j, reason, _ = walk_static(Ob, Hh, L, C, Ob[0], t.atr, s, GRID[q0],
                                           self.tie_maker(t, s) if self.tie_maker else None)
            g, c = trade_net(Ob[0], px, j, t.atr, self.t_ns[t.symbol], int(t.i))
            out.append((s * g - c, reason, []))
        return out

    def policy(self, margin: float, log: list | None = None):
        def fac(k, t, s, entry, C):
            pr = self.probs.get(k, {})

            def ch(jc, q):
                if jc not in pr:
                    return None
                close = C[jc - 1]
                ok = valid_levels(s, entry, t.atr, close)
                cost = level_cost(entry, t.atr, s)
                ev = expected_net_r(pr[jc], self.means, cost)
                cur = ev[q]
                cand = np.where(ok, ev, -np.inf)
                best = int(np.argmax(cand))
                eligible = bool((ok & (np.arange(len(GRID)) != q)).any())
                if log is not None:
                    log.append({"k": k, "jc": jc, "eligible": eligible, "q": q})
                if np.isfinite(cand[best]) and best != q and cand[best] - cur > margin:
                    return best
                return None
            return ch
        return [self._one(k, fac) for k in self.trades.index]

    def random(self, rate: float, p_in: float, rng):
        def fac(k, t, s, entry, C):
            def ch(jc, q):
                ok = valid_levels(s, entry, t.atr, C[jc - 1])
                ok[q] = False
                if not ok.any() or rng.random() >= rate:
                    return None
                ins = [x for x in np.where(ok)[0] if x < q]
                outs = [x for x in np.where(ok)[0] if x > q]
                pool = ins if (ins and (not outs or rng.random() < p_in)) else outs
                return int(rng.choice(pool))
            return ch
        return [self._one(k, fac) for k in self.trades.index]


def walk_static(Ob, Hh, L, C, entry, atr, side, level, tie):
    risk = E.SL_ATR * atr
    sl = entry - side * risk
    tp = entry + side * level * atr
    for j in range(1, H + 1):
        o, h, lo = Ob[j - 1], Hh[j - 1], L[j - 1]
        hit_sl = lo <= sl if side > 0 else h >= sl
        hit_tp = h >= tp if side > 0 else lo <= tp
        if hit_sl and hit_tp and tie is not None:
            gap = o <= sl if side > 0 else o >= sl
            res = "sl" if gap else tie(j, sl, tp)
            hit_sl, hit_tp = res == "sl", res == "tp"
        if hit_sl:
            gap = o <= sl if side > 0 else o >= sl
            return (o if gap else sl), j, 1, []
        if hit_tp:
            return tp, j, 2, []
    return C[H - 1], H, 0, []


def level_cost(entry: float, atr: float, side: int) -> np.ndarray:
    """Cost (R) of a TP fill at each grid level, funding at 1.5 windows (the arithmetic of execution_costs)."""
    from src.runtime.execution_costs import resolve_cost_policy
    slip_bps, fund_bps = resolve_cost_policy("BTCUSDT")
    risk = E.SL_ATR * atr
    lv = entry + side * np.array(GRID) * atr
    per_r = ((abs(entry) + np.abs(lv)) / 2.0) / risk
    return (E.FEE_BPS + slip_bps + 1.5 * fund_bps) / 1e4 * per_r


# ------------------------------------------------------------------------------------------------ trades
def entry_trades_wf(tab: pd.DataFrame, tau: float) -> pd.DataFrame:
    """c692-01 walk-forward fold trades (2022-01..2025-09) at ``tau``, its recipe unchanged."""
    dev = tab[tab.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC")]
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [pd.Timestamp(E.HOLDOUT_START, tz="UTC")]
    out = []
    for a, b in itertools.pairwise(bounds):
        test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=H + 1))]
        pl, ps = E.fit_predict(E.purge_train(dev, a), test)
        out.append(policy_with_i(test, pl, ps, tau))
        print(f"entry fold {a.date()} trades={len(out[-1])}", flush=True)
    return pd.concat(out, ignore_index=True)


def policy_with_i(test, pl, ps, tau):
    tk = E.policy(test, pl, ps, tau)
    key = test.assign(p_long=pl, p_short=ps)[["symbol", "ts", "i", "atr"]]
    return tk.merge(key, on=["symbol", "ts"], how="left")


def served_trades(tab: pd.DataFrame, lo: str, hi: str, art: dict) -> pd.DataFrame:
    import lightgbm as lgb
    test = tab[(tab.ts >= pd.Timestamp(lo, tz="UTC")) & (tab.ts < pd.Timestamp(hi, tz="UTC"))]
    bl = lgb.Booster(model_str=art["booster_txt"]["long"])
    bs = lgb.Booster(model_str=art["booster_txt"]["short"])
    # provenance: predict — the served ENTRY regressors' net R per side (the artifact ml_entry serves)
    pl, ps = bl.predict(test[art["features"]]), bs.predict(test[art["features"]])
    return policy_with_i(test, pl, ps, float(art["tau"]))


def trade_checkins(trades: pd.DataFrame, bars: dict, panel: dict) -> pd.DataFrame:
    parts = []
    for sym, g in trades.groupby("symbol"):
        s = np.where(g.side.to_numpy() == "long", 1, -1)
        r = checkin_rows(sym, bars[sym], panel[sym], g["i"].to_numpy(), g["atr"].to_numpy(), s, True)
        if len(r):
            r["k"] = g.index.to_numpy()[r["pos"].to_numpy()]
            parts.append(r)
    return pd.concat(parts, ignore_index=True)


def probs_by_trade(rows: pd.DataFrame, P: np.ndarray) -> dict:
    out: dict = {}
    for k, jc, p in zip(rows["k"].to_numpy(), rows["bars_held"].to_numpy().astype(int), P):
        out.setdefault(int(k), {})[jc] = p
    return out


# ------------------------------------------------------------------------------------------------ reporting
def calibration(rows: pd.DataFrame, P: np.ndarray) -> dict:
    """Brier + 10-bin reliability per first-passage class at the 3 ATR level (target_first / stop_first / timeout)."""
    G = len(GRID) + 1
    q = GRID.index(BASE_TP) + 1
    y = rows["y"].to_numpy()
    reach, stop = y % G, y >= G
    real = {"target_first": reach >= q, "stop_first": stop & (reach < q), "timeout": (~stop) & (reach < q)}
    pred = {"target_first": P[:, q:G].sum(1) + P[:, G + q:].sum(1), "stop_first": P[:, G:G + q].sum(1),
            "timeout": P[:, :q].sum(1)}
    out = {}
    for c, yb in real.items():
        yv, pv = yb.astype(float), pred[c]
        bins = np.clip((pv * 10).astype(int), 0, 9)
        rel = [{"bin": b, "n": int((bins == b).sum()), "mean_pred": round(float(pv[bins == b].mean()), 4),
                "realized": round(float(yv[bins == b].mean()), 4)} for b in range(10) if (bins == b).any()]
        out[c] = {"brier": round(float(np.mean((pv - yv) ** 2)), 5), "base_rate": round(float(yv.mean()), 4),
                  "brier_climatology": round(float(np.mean((yv.mean() - yv) ** 2)), 5), "reliability": rel}
    return {"n_checkins": len(rows), "level_atr": BASE_TP, "classes": out}


def summarize_delta(trades: pd.DataFrame, base: list, pol: list, rng) -> dict:
    from intervention_controls import boot_ci_by_group
    b = np.array([x[0] for x in base])
    p = np.array([x[0] for x in pol])
    d = p - b
    moved = np.array([len(x[2]) > 0 for x in pol])
    kinds = [mv for x in pol for mv in x[2]]
    n_in = sum(1 for _, q0, q1 in kinds if q1 < q0)
    first_kind = np.array([("in" if x[2][0][2] < x[2][0][1] else "out") if x[2] else "" for x in pol])
    _mean, lo, hi = boot_ci_by_group(d, None, rng, draws=5000)
    res = {"n": len(d), "n_symbols": int(trades.symbol.nunique()), "baseline_mean_net_r": float(b.mean()),
           "policy_mean_net_r": float(p.mean()), "mean_delta_per_trade": float(d.mean()),
           "bootstrap_ci95_delta_by_trade_reported": [lo, hi], "n_trades_moved": int(moved.sum()),
           "mean_delta_per_moved_trade": float(d[moved].mean()) if moved.any() else None,
           "n_moves": len(kinds), "n_pull_in": n_in, "n_extend": len(kinds) - n_in,
           "delta_by_first_move": {k: {"n": int((first_kind == k).sum()), "mean_delta": float(d[first_kind == k].mean())}
                                   for k in ("in", "out") if (first_kind == k).any()},
           "exit_reasons_policy": {str(r): int(sum(1 for x in pol if x[1] == r)) for r in (0, 1, 2)},
           "exit_reasons_baseline": {str(r): int(sum(1 for x in base if x[1] == r)) for r in (0, 1, 2)},
           "by_side": {sd: {"n": int((trades.side == sd).sum()), "mean_delta": float(d[(trades.side == sd).to_numpy()].mean())}
                       for sd in ("long", "short") if (trades.side == sd).any()}}
    return res


def verdict(h: dict) -> tuple[str, str]:
    n, ns, nm, d = h["n"], h["n_symbols"], h["n_trades_moved"], h["mean_delta_per_trade"]
    if n < N_FLOOR or ns < SYMBOL_FLOOR or nm < MOVED_FLOOR:
        return "indeterminate", f"held-out trades={n} (floor {N_FLOOR}) symbols={ns} (floor {SYMBOL_FLOOR}) moved={nm} (floor {MOVED_FLOOR})"
    if d >= 0:
        return "pass", f"held-out mean delta net R per trade {d:+.4f} >= 0 at n={n}, {ns} symbols, {nm} moved"
    return "fail", f"held-out mean delta net R per trade {d:+.4f} < 0 at n={n}, {ns} symbols, {nm} moved"


# ------------------------------------------------------------------------------------------------ run
def dev_stage(cache: Path, out: Path) -> dict:
    t0 = time.time()
    art = json.loads(SERVED.read_text())
    syms = E.universe()
    E.fetch(cache, syms)
    tab = E.build_table(cache, syms)
    bars = load_bars(cache, syms)
    panel = feature_panel(bars)
    # parity: the per-bar panel equals the table's features on its rows
    smp = tab.sample(min(20000, len(tab)), random_state=SEED)
    worst = 0.0
    for sym, g in smp.groupby("symbol"):
        a = panel[sym].iloc[g["i"].to_numpy()][E.FEATURES].to_numpy(float)
        b = g[E.FEATURES].to_numpy(float)
        both = ~(np.isnan(a) | np.isnan(b))
        worst = max(worst, float(np.nanmax(np.abs(a - b)[both])) if both.any() else 0.0)
        assert (np.isnan(a) == np.isnan(b)).all(), sym
    assert worst < 1e-9, worst
    print(f"dev table rows={len(tab)} panel parity max|diff|={worst:.2e} t={time.time()-t0:.0f}s", flush=True)
    tau = float(art["tau"])
    wf = entry_trades_wf(tab, tau)
    sv = served_trades(tab, E.HOLDOUT_START, DEV_END, art)
    trades = pd.concat([wf, sv], ignore_index=True)
    # walker parity: the fixed 3 ATR walk reproduces the c692-01 label net R on every dev trade
    sc0 = Scorer(trades, bars, {}, np.zeros(N_CLASS))
    base = sc0.fixed(BASE_TP)
    diff = np.abs(np.array([x[0] for x in base]) - trades.net_r.to_numpy())
    assert diff.max() < 1e-9, diff.max()
    print(f"dev ENTRY trades={len(trades)} (wf {len(wf)} + served {len(sv)}), walker parity max|diff|={diff.max():.1e} "
          f"t={time.time()-t0:.0f}s", flush=True)
    # TP-model walk-forward
    tr_rows = trade_checkins(trades, bars, panel)
    probs, fold_rec = {}, []
    bounds = [pd.Timestamp(x, tz="UTC") for x in TP_FOLDS]
    for a, b in itertools.pairwise(bounds):
        cut = a - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=H + 1)
        train = training_rows(tab, bars, panel, cut, SEED)
        tm = fit_tp_model(train)
        tts = pd.to_datetime(trades.loc[tr_rows.k, "ts"].to_numpy(), utc=True)
        sel = tr_rows[(tts >= a) & (tts < b)]          # a trade belongs to the fold holding its decision bar
        P = predict_probs(tm, sel)
        for k, v in probs_by_trade(sel, P).items():
            probs[k] = (v, tm["class_mean_net_r"])
        fold_rec.append({"test_start": str(a.date()), "n_train": tm["n_train"], "n_checkins": len(sel)})
        print(json.dumps(fold_rec[-1]), f"t={time.time()-t0:.0f}s", flush=True)
    in_wf = trades.ts >= bounds[0]
    dtr = trades[in_wf].copy()
    # each trade carries its own fold's class means: score per fold, pooled
    by_margin = {}
    for m in MARGINS:
        res = []
        for fm in {id(v[1]): v[1] for v in probs.values()}.values():
            ks = [k for k, v in probs.items() if v[1] is fm]
            sub = trades.loc[ks]
            sc = Scorer(sub, bars, {kk: probs[k][0] for kk, k in zip(range(len(ks)), ks)}, fm)
            res += [(a0[0] - b0, len(a0[2]) > 0) for a0, b0 in zip(sc.policy(m), sub.net_r.to_numpy())]
        d = np.array([x[0] for x in res])
        by_margin[str(m)] = {"n": len(d), "mean_delta": float(d.mean()), "n_moved": int(sum(x[1] for x in res))}
        print("margin", m, by_margin[str(m)], f"t={time.time()-t0:.0f}s", flush=True)
    m_star = max(MARGINS, key=lambda m: (by_margin[str(m)]["mean_delta"], m))
    stat = {}
    sc_all = Scorer(dtr, bars, {}, np.zeros(N_CLASS))
    for lv in GRID:
        v = np.array([x[0] for x in sc_all.fixed(lv)])
        stat[str(lv)] = {"n": len(v), "mean_net_r": float(v.mean())}
    best_static = max(GRID, key=lambda lv: (stat[str(lv)]["mean_net_r"], -abs(lv - BASE_TP)))
    return {"tab_rows": len(tab), "dev_trades": len(trades), "dev_trades_scored": int(in_wf.sum()),
            "tp_folds": fold_rec, "dev_by_margin": by_margin, "margin_star": m_star,
            "dev_static_by_level": stat, "best_static_level": best_static, "tau": tau,
            "data_fingerprint": hashlib.sha256(pd.util.hash_pandas_object(tab[["ts", "symbol", "net_long", "net_short"]],
                                                                           index=False).to_numpy().tobytes()).hexdigest()[:16]}


def forward_stage(cache: Path, out: Path, dev: dict) -> dict:
    """THE ONE READ of the forward window."""
    t0 = time.time()
    art = json.loads(SERVED.read_text())
    syms = E.universe()
    fwd = out / "fwd_klines"
    rep = forward_cache(cache, fwd, syms)
    have = [s for s in syms if rep[s].get("oct_days")]
    # dev rows for the final TP fit come from the DEV cache (bars < 2026-10-01); forward rows from the forward cache
    tab_dev = E.build_table(cache, syms)
    bars_dev = load_bars(cache, syms)
    panel_dev = feature_panel(bars_dev)
    cut = pd.Timestamp(DEV_END, tz="UTC") - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=H + 1)
    tm = fit_tp_model(training_rows(tab_dev, bars_dev, panel_dev, cut, SEED))
    print(f"final TP fit n_train={tm['n_train']} t={time.time()-t0:.0f}s", flush=True)
    del tab_dev, bars_dev, panel_dev
    # cross-sectional context needs every universe symbol present at a ts: symbols without October simply drop out of it,
    # exactly as a delisted symbol drops out of the live reference set
    for s in syms:
        if s not in have:
            (fwd / f"{s}.pkl").write_bytes((cache / f"{s}.pkl").read_bytes())
    tab = E.build_table(fwd, syms)
    bars = load_bars(fwd, syms)
    panel = feature_panel(bars)
    lo, hi = pd.Timestamp(FWD_START, tz="UTC"), pd.Timestamp(FWD_END, tz="UTC") + pd.Timedelta(days=1)
    trades = served_trades(tab, FWD_START, str(hi.date()), art)
    trades = trades[(trades.ts >= lo) & (trades.ts + pd.Timedelta(hours=H + 1) <= hi)].reset_index(drop=True)
    rows = trade_checkins(trades, bars, panel)
    P = predict_probs(tm, rows)
    probs = probs_by_trade(rows, P)
    om = OneMinute(out / "klines_1m")

    def tie_maker(t, s):
        df = bars[t.symbol]

        def tie(j, sl, tp):
            return om.resolve(t.symbol, pd.Timestamp(df["ts"].iloc[int(t.i) + j]), s, sl, tp)
        return tie
    sc = Scorer(trades, bars, probs, tm["class_mean_net_r"], tie_maker)
    base = sc.fixed(BASE_TP)
    log: list = []
    pol = sc.policy(dev["margin_star"], log)
    rng = np.random.default_rng(SEED)
    h = summarize_delta(trades, base, pol, rng)
    elig = [x for x in log if x["eligible"]]
    rate = h["n_moves"] / max(1, len(elig))
    p_in = h["n_pull_in"] / max(1, h["n_moves"])
    b = np.array([x[0] for x in base])
    draws = []
    for _ in range(RANDOM_DRAWS):
        rd = sc.random(rate, p_in, rng)
        draws.append(float(np.mean([x[0] for x in rd]) - b.mean()))
    h["matched_random"] = {"draws": RANDOM_DRAWS, "move_rate_per_eligible_checkin": rate, "p_pull_in": p_in,
                           "mean_delta_of_draws": float(np.mean(draws)), "p5": float(np.percentile(draws, 5)),
                           "p95": float(np.percentile(draws, 95)),
                           "policy_percentile": float(np.mean([x < h["mean_delta_per_trade"] for x in draws]))}
    bs = np.array([x[0] for x in sc.fixed(dev["best_static_level"])])
    h["best_static_dev_chosen"] = {"level_atr": dev["best_static_level"], "mean_net_r": float(bs.mean()),
                                   "mean_delta_vs_base": float((bs - b).mean())}
    h["calibration_reported"] = calibration(rows, P)
    h["ties"] = {**om.counts, "resolver": TIE_RESOLVER}
    h["window"] = [str(trades.ts.min()), str(trades.ts.max())]
    h["forward_fetch"] = {"symbols_with_october": len(have), "symbols_without": [s for s in syms if s not in have]}
    h["final_fit"] = {"n_train": tm["n_train"], "class_counts": tm["class_counts"],
                      "class_mean_net_r": [round(float(x), 4) for x in tm["class_mean_net_r"]]}
    h["elapsed_s"] = round(time.time() - t0)
    return h


def run(args) -> int:
    cache, out = Path(args.cache), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    dev_p = out / "dev.json"
    if dev_p.exists():
        dev = json.loads(dev_p.read_text())
    else:
        dev = dev_stage(cache, out)
        dev_p.write_text(json.dumps(dev, indent=1, default=str) + "\n")
    print(json.dumps({k: dev[k] for k in ("dev_by_margin", "margin_star", "best_static_level")}), flush=True)
    if args.dev_only:
        return 0
    marker = out / "FORWARD_READ"
    if marker.exists():
        raise SystemExit("the forward window has already been read once (ML-BAR-ONE-READ); refusing a second read")
    marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    h = forward_stage(cache, out, dev)
    v, why = verdict(h)
    summary = {"schema": SCHEMA, "unit": args.unit or UNIT, "verdict": v, "why": why, "git_sha": E._git_sha(),
               "variants_read_on_window": 1, "config": {k: globals()[k] for k in (
                   "GRID", "BASE_TP", "CHECKINS", "MIN_GAP_ATR", "VENUE_CAP_PCT", "MARGINS", "TRAIN_FRAC", "TRAIN_MAX_ROWS",
                   "FWD_START", "FWD_END", "TP_FOLDS", "N_FLOOR", "SYMBOL_FLOOR", "MOVED_FLOOR", "RANDOM_DRAWS", "SEED",
                   "TP_LGB", "TP_FEATURES")}, "dev": dev, "heldout": h, "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": h["n"],
          "population": (f"ml_entry trades of the served ENTRY model (tau {dev['tau']}) on the 60-perp universe, forward "
                         f"{FWD_START}..{FWD_END} (Binance Vision daily 1h; ties from 1m), SL 2 ATR / TP 3 ATR / 24h, net of "
                         f"fee {E.FEE_BPS} + slip 3.0 bps + funding 1 bps/8h; moving-TP policy margin {dev['margin_star']}"),
          "measurement": {k: h[k] for k in h if k != "calibration_reported"}, "note": why}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> None:
    from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT
    assert VENUE_CAP_PCT == TP_VENUE_CAP_PCT
    o = np.full(H, 100.0)
    hh, ll, cc = o + 1, o - 1, o.copy()
    # fixed TP parity with bracket_outcome on random paths, ties SL-first, gaps at the open
    rng = np.random.default_rng(1)
    for _ in range(300):
        side = int(rng.choice([1, -1]))
        steps = rng.normal(0, 1.2, H).cumsum() + 100
        Ob = steps + rng.normal(0, .3, H)
        C = steps
        Hh = np.maximum(Ob, C) + rng.random(H) * 1.5
        L = np.minimum(Ob, C) - rng.random(H) * 1.5
        px, j, r = E.bracket_outcome(Ob[None], Hh[None], L[None], C[None], np.array([Ob[0]]), np.array([1.0]), side)
        px2, j2, r2, _ = walk(Ob, Hh, L, C, Ob[0], 1.0, side, None)
        assert (abs(px[0] - px2) < 1e-12) and j[0] == j2 and r[0] == r2, (px, px2, j, j2, r, r2)
    # a move at a check-in binds from the next bar: TP 3 ATR -> 1 ATR at bar 4 then bar 5 high 101.5 fills at 101
    hh2 = hh.copy()
    hh2[4] = 101.5
    px, j, r, mv = walk(o, hh2, ll, cc, 100.0, 1.0, 1, lambda jc, q: 0 if jc == 4 else None)
    assert (px, j, r) == (101.0, 5, 2) and mv == [(4, GRID.index(3.0), 0)], (px, j, r, mv)
    # without the move the same path times out
    px, j, r, mv = walk(o, hh2, ll, cc, 100.0, 1.0, 1, None)
    assert r == 0 and j == H
    # tie callback decides a same-bar double touch
    hh3, ll3 = hh.copy(), ll.copy()
    hh3[2], ll3[2] = 104, 97
    assert walk(o, hh3, ll3, cc, 100.0, 1.0, 1, None, lambda j, sl, tp: "tp")[2] == 2
    assert walk(o, hh3, ll3, cc, 100.0, 1.0, 1, None, lambda j, sl, tp: "sl")[2] == 1
    # expected net R: all mass on "reach >= 4 (3.0 ATR), no stop" -> level 3.0 pays 1.5R - cost, level 4.0 pays the class mean
    G = len(GRID) + 1
    p = np.zeros(N_CLASS)
    p[5] = 1.0
    means = np.zeros(N_CLASS)
    means[5] = 0.7
    ev = expected_net_r(p, means, np.zeros(len(GRID)))
    assert abs(ev[GRID.index(3.0)] - 1.5) < 1e-12 and abs(ev[GRID.index(4.0)] - 0.7) < 1e-12, ev
    assert abs(ev[0] - 0.5) < 1e-12
    # valid levels: never through price, >= MIN_GAP_ATR beyond the close
    ok = valid_levels(1, 100.0, 1.0, 102.3)
    assert not ok[GRID.index(2.5)] and ok[GRID.index(3.0)] and not ok[GRID.index(2.0)], ok
    ok = valid_levels(-1, 100.0, 1.0, 99.0)
    assert ok[GRID.index(1.5)] and not ok[GRID.index(1.0)]
    assert G == 9 and N_CLASS == 18
    # shared 1m tie resolver contract: first minute decides; a minute touching both, or partial coverage, is None
    mins = [{"time": 60 * k, "high": 100.5, "low": 99.5} for k in range(60)]
    mins[7] = {"time": 420, "high": 103.5, "low": 99.0}
    assert resolve_same_bar({"time": 0}, 3600, mins, True, 103.0, 98.0) == "target_first"
    mins[3] = {"time": 180, "high": 100.0, "low": 97.0}
    assert resolve_same_bar({"time": 0}, 3600, mins, True, 103.0, 98.0) == "invalidation_first"
    assert resolve_same_bar({"time": 0}, 3600, mins[:30], True, 103.0, 98.0) is None
    mins[3] = {"time": 180, "high": 104.0, "low": 97.0}
    assert resolve_same_bar({"time": 0}, 3600, mins, True, 103.0, 98.0) is None
    print("self-test ok")


def export(args) -> int:
    """Refit the FINAL TP model exactly as ``forward_stage`` did (dev cache only: no forward bar is read), assert it
    reproduces the run's final fit (row count, class counts, class means), and write the served artifact that
    ``src/units/strategies/ml_entry.py`` loads. The margin is the dev-chosen one from the same summary."""
    cache = Path(args.cache)
    s = json.loads(Path(args.summary).read_text())
    syms = E.universe()
    tab = E.build_table(cache, syms)
    bars = load_bars(cache, syms)
    panel = feature_panel(bars)
    cut = pd.Timestamp(DEV_END, tz="UTC") - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=H + 1)
    tm = fit_tp_model(training_rows(tab, bars, panel, cut, SEED))
    ff = s["heldout"]["final_fit"]
    assert tm["n_train"] == ff["n_train"] and tm["class_counts"] == ff["class_counts"], (tm["n_train"], ff["n_train"])
    got = [round(float(x), 4) for x in tm["class_mean_net_r"]]
    assert got == ff["class_mean_net_r"], (got, ff["class_mean_net_r"])
    art = {"model_id": "ml-entry-tp-revision-v1", "schema": "ml_entry_tp_revision_model/1", "unit": UNIT,
           "evidence": [f"research/results/{UNIT}/local-20261101T1030Z.jsonl"],
           "features": TP_FEATURES, "classes": [int(c) for c in tm["classes"]],
           "class_mean_net_r": [float(x) for x in tm["class_mean_net_r"]], "grid_atr": GRID, "base_tp_atr": BASE_TP,
           "checkins_bars_held": CHECKINS, "min_gap_atr": MIN_GAP_ATR, "margin_r": float(s["dev"]["margin_star"]),
           "sl_atr": E.SL_ATR, "horizon_h": H, "fee_bps": E.FEE_BPS, "n_train": tm["n_train"],
           "train_end_exclusive": str(cut), "lgb_params": TP_LGB, "git_sha": E._git_sha(),
           "booster_txt": tm["model"].booster_.model_to_string()}
    out = Path(args.artifact)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art) + "\n")
    print(json.dumps({"artifact": str(out), "bytes": out.stat().st_size, "n_train": tm["n_train"]}), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "export"])
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_tp_revision_out")
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--dev-only", action="store_true", help="stop before the one read of the forward window")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--summary", default="", help="export: the run summary.json whose final fit is reproduced")
    ap.add_argument("--artifact", default=str(REPO / "ml" / "served" / "ml_entry_tp_revision_v1" / "model.json"))
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return export(a) if a.cmd == "export" else run(a)


if __name__ == "__main__":
    sys.exit(main())
