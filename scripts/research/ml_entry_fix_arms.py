#!/usr/bin/env python3
# wiring: research/queue/RQ-20261124-f1x0-0{1..5}.yaml (ML-ENTRY fix arms, lane ML-PRIMARY 2026-11-24); diagnosis docs/research/ml-entry-review-2026-11-24.md
"""ml_entry FIX ARMS: five diagnosed, one-factor fixes for the live ml_entry failure, each against the registered recipe on the
8 dev folds and each with a matched control, net of the full cost stack (Tier-1 research; changes no served model, config or
order path).

Diagnosis (docs/research/ml-entry-review-2026-11-24.md; RQ-20261124-e1a7-02 measurement): the side is set by a market-wide
contrarian rule on btc_ret24 / btc_vol24; on the dev folds the registered recipe's LONG side is net -0.0063 R/decision (n 25,793)
vs SHORT +0.0082 (n 45,541); the policy averages 11.8 same-bar entries, bar-level max DD 1,604 R at full risk per entry.

Arms (``--arm``, one per queue unit; each graded by its own registered rule, written to <out>/verdict.json):

  long_mute     SIDE ASYMMETRY. The long side is unavailable when BTC's 7d log return < 0 AND BTC vol24 sits at or above its 90d
                median (btc_vol_pct90d >= 0.5): the "buy the panic inside a downtrend" cell the review measured. The short side is
                unchanged (a muted long may still trade short if the short prediction clears tau). Control: the same share of
                long candidates muted at RANDOM (100 seeded draws). Reported, not graded: short-only and a long-side tau of 0.20.
  bar_split     BAR RISK SPLIT. Identical decisions; each decision bar's k entries share 1R (weight 1/k) instead of 1R each.
                Statistic: net R per 1R deployed, bar Sharpe and bar max drawdown at matched mean risk. Control: random
                Dirichlet(1) weights per bar summing to 1 (100 draws). A risk lever, so its rule is non-inferiority + risk.
  regime_heads  REGIME-CONDITIONED HEADS. The long and short regressors are fit separately in the BTC 7d up (btc_ret168 >= 0)
                and down cells, and a row is scored by its cell's pair. Placebo: the same split on a seeded coin per timestamp
                with the train up-share (prices halving each head's training set).
  book_feats    BOOK / RECENCY INPUTS, policy-independent and point-in-time: the symbol's own long / short bracket outcome of the
                decision 24 h earlier (closed by bar t's close), and across the universe at t-24 h the mean long net R and the
                long / short stop-out shares. Placebo: the same 5 columns with their timestamps shuffled (seeded).
  sl_wide       SL PLACEMENT. Same predictions; the bracket is SL 3 / TP 4.5 ATR14 (same 1.5 reward:risk, 24 h stop) instead of
                SL 2 / TP 3, each decision in its own R (sizing is by risk). Control (reported, attributes the gain): random-side
                entries on the same rows under both brackets.

  ev_calib      CALIBRATED EV (iteration 2, from the 2026-11-24 dev calibration read: on 477,6xx dev rows the LONG head's realised net R is
                negative in EVERY prediction decile, top decile pred +0.28 -> realised -0.044; the SHORT head is positive only for preds 0.03-0.22
                and its top decile loses). Each side's regressor gets a cross-fitted isotonic map pred -> realised net R (CALIB_BLOCKS time blocks
                of the training window, purged by the label horizon); the policy trades the better CALIBRATED side iff its calibrated EV > 0.
                Control: the base policy thinned at random to the arm's per-side take rate (100 draws).
  ev_cap3       ev_calib plus at most CAP_K entries per decision bar, ranked by calibrated EV; control: a random CAP_K-of-k pick from the same
                calibrated candidates (100 draws).

  ev_calib_recent ITERATION 3 of the calibration lever (ev_calib INDETERMINATE -0.0099: the whole-window isotonic map is non-stationary across
                folds; a short-side max calibrated EV of +0.02 in some folds and a side switched off in another): the same cross-fitted OOF
                predictions, but the isotonic map is fit ONLY on the most recent training block (the one nearest the test fold), so the side EVs
                track the current regime. Control: random thinning at the arm's per-side take rate (100 draws), as ev_calib.
  volsl_retrain REGIME ARM 2 (f1a0-12's pre-named next form): the SL 4 / TP 6 recipe with the bracket WIDTH set by the regime: SL = 3 + 2 x
                BTC vol24 percentile over 90 d (3..5 ATR14), TP = 1.5 x SL, 24 h; refit on those labels. Graded vs the fixed SL 4 / TP 6 / 24 h refit
                (the one factor is the vol scaling); random-side entries under both reported.
  rsz_xwide     REGIME-CONDITIONED SIZING (REGIME-PROGRAM R4): the SL 4 / TP 6 / 24 h refit's decisions, each sized by
                clip(train-median BTC vol24 / BTC vol24 at the bar, 0.5, 2) normalised to mean 1 (vol parity across regimes; keeps every decision,
                so no power loss). Statistic as bar_split: net R per 1R deployed (non-inferiority), bar Sharpe and bar max DD vs the same decisions
                unweighted; control: the same weights permuted across bars.
  lim_xwide     PULLBACK LIMIT ENTRY (cost per R is the binding constraint: gross ~ +0.067 vs cost ~ 0.064 R/decision on the registered recipe).
                The SL 4 / TP 6 / 24 h refit's OWN decisions, each entered by a post-only limit LIM_K ATR14 better than the decision price (bar t+1
                open), resting LIM_W hours; STRICT fill iff a bar trades LIM_TICK_BPS through the limit; fill at the limit; maker fee on entry
                (MAKER_BPS) and the taker convention on the exit (TAKER_BPS + half the 3 bps slippage), funding as usual; the bracket is measured
                from the fill (24 bars from the fill bar; on the fill bar a stop touch counts, a target touch does not). An unfilled decision is
                0 R and keeps the symbol busy for the window. Graded per DECISION vs the same decisions entered at market (the one factor is the
                entry order); control: the market outcomes of the same decisions thinned AT RANDOM to the arm's fill rate (100 draws), so a pass
                means the fill SELECTION + price beats random thinning, not just fewer trades.
  rsw_xwide_h48 REGIME ARM (operator 2026-11-24: regime classification is a standing lever). The sl_xwide_h48_retrain recipe with every
                training row WEIGHTED by a Gaussian kernel of its BTC regime-state distance (RSW_STATE: 30d return, distance from the 1200 h mean,
                vol percentile; standardized on the training window) to the mean state of the RSW_REF_DAYS before the test fold; weights normalized
                to mean 1. Graded against the SAME recipe with uniform weights (the one factor); control: the same weighting with the regime states
                permuted across timestamps (placebo). Per-regime-cell net R (BTC 30d trend sign x vol above/below median) reported for each arm.
  sl_xwide_h48_retrain ITERATION 4 of the bracket / cost lever (sl_xwide_retrain INDETERMINATE +0.0087, t 0.59, cost 0.037 R; with a 4-ATR stop
                the 24 h time stop ends most trades): SL 4 / TP 6 labels and trading with a 48 h horizon (H48). The training purge (7-day embargo)
                exceeds the 48 h label; the base stays the registered 24 h SL-2 recipe.
  sl_xwide_retrain ITERATION 3 of the bracket / cost lever (11 arms: gross ~ +0.067 R/decision vs cost ~ 0.064 R; sl_wide_retrain cut cost to
                0.045 at a neutral delta, positive 2024-25): the recipe refit on SL 4 / TP 6 ATR14 labels and traded under that bracket.
  sl_wide_retrain  ITERATION 2 of sl_wide (FAIL: the SL-2-trained predictions lose more gross edge under SL 3 than the cost they save): the recipe
                REFIT on SL 3 / TP 4.5 labels per fold and traded under that bracket, vs the SL-2 recipe under SL 2. Control (reported): random-side
                entries under both brackets, as sl_wide.

    python3 scripts/research/ml_entry_fix_arms.py --arm long_mute --cache /tmp/ml_entry_klines --fetch --run-date 2026-11-22 --out /tmp/o
    python3 scripts/research/ml_entry_fix_arms.py --self-test
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as M  # noqa: E402

ARMS = ["long_mute", "bar_split", "regime_heads", "book_feats", "sl_wide", "ev_calib", "ev_cap3", "sl_wide_retrain", "ev_calib_recent", "sl_xwide_retrain", "sl_xwide_h48_retrain", "rsw_xwide_h48", "volsl_retrain", "rsz_xwide", "lim_xwide"]
CALIB_BLOCKS = 4                      # time blocks of the training window for the cross-fitted calibration map
EV_TAU = 0.0                          # ev_calib / ev_cap3 trade iff the CALIBRATED expected net R (full cost stack) > 0
CAP_K = 3
DRAWS = 100                           # matched-random draws (research-queue-design-fields-guard minimum)
TAU = 0.10
SEED = 20261124
BOOK_FEATURES = ["own_prev_net_long", "own_prev_net_short", "xs_prev_net_long", "xs_prev_stop_long", "xs_prev_stop_short"]
SL_WIDE, TP_WIDE = 3.0, 4.5
SL_XWIDE, TP_XWIDE = 4.0, 6.0          # sl_xwide_retrain: cost per R ~ half of SL 2 at the same 1.5 reward:risk
RSW_STATE = ["btc_ret720", "btc_dist_sma1200", "btc_vol_pct90d"]   # rsw_xwide_h48: the causal 2-axis BTC regime state (trend, vol)
RSW_BW = 1.0                          # Gaussian kernel bandwidth in train-standardized state units (fixed, no grid)
RSW_REF_DAYS = 7                      # the reference state = mean state over the last 7 days BEFORE the test fold (point-in-time)
VOLSL_LO, VOLSL_HI = 3.0, 5.0         # volsl_retrain: SL = 3 + 2 x BTC vol percentile (ATR14 multiples), TP = 1.5 x SL, 24 h
RSZ_CAP = (0.5, 2.0)                   # rsz_xwide: per-decision weight = clip(train-median BTC vol24 / BTC vol24 at the bar), then mean 1
RSZ_RULE = {"id": "RULE-ML-ENTRY-FIX-ARMS-20261124", "noninferiority_margin_r": 0.0068, "min_t": 2.0, "min_bars": 3000,
            "max_dd_ratio": 0.85, "min_folds_sharpe_better": 5}
LIM_K, LIM_W = 0.5, 4                 # lim_xwide: limit LIM_K x ATR14 better than bar t+1's open, resting LIM_W 1h bars (fixed, no grid)
LIM_TICK_BPS = 1.0                    # strict fill: the bar must trade 1 bp THROUGH the limit (queue position)
MAKER_BPS, TAKER_BPS = 2.0, 5.5       # Bybit linear per side, the same constants as ml_entry_maker_replay.py (delta_F: 5.5 - 2.0 if filled)
H48 = 48                              # sl_xwide_h48_retrain: the label / time-stop horizon in 1h bars (registered 24)
LEVER = dict(M.LEVER_RULE, id="RULE-ML-ENTRY-FIX-ARMS-20261124")
SPLIT_RULE = {"id": "RULE-ML-ENTRY-FIX-ARMS-20261124", "noninferiority_margin_r": 0.0068, "min_t": 2.0, "min_bars": 3000,
              "max_dd_ratio": 0.7, "min_folds_sharpe_better": 5}


# ------------------------------------------------------------------------------------------------ fast sequential policy
class Seq:
    """One fold's test rows in (symbol, i) order with the arrays the sequential policy needs; built once, reused by every draw."""

    def __init__(self, test: pd.DataFrame, label_cols: pd.DataFrame | None = None):
        order = np.lexsort((test["i"].to_numpy(), test["symbol"].to_numpy()))
        self.idx = test.index.to_numpy()[order]
        t = test.loc[self.idx] if label_cols is None else test.loc[self.idx].assign(**{c: label_cols.loc[self.idx, c] for c in label_cols})
        self.t = t
        self.order = order
        self.sym = t["symbol"].to_numpy()
        self.i = t["i"].to_numpy()
        self.bars = {s: t[f"bars_{s}"].to_numpy() for s in ("long", "short")}
        starts = np.r_[0, np.flatnonzero(self.sym[1:] != self.sym[:-1]) + 1, len(self.sym)]
        self.groups = list(itertools.pairwise(starts))

    def run(self, pl: np.ndarray, ps: np.ndarray, tau: float = TAU) -> pd.DataFrame:
        """pl / ps in the ORIGINAL test order. Same rule as M.policy: better side, > tau, symbol busy until its exit bar."""
        pl, ps = pl[self.order], ps[self.order]
        is_long = pl >= ps
        p = np.where(is_long, pl, ps)
        take = []
        for a, b in self.groups:
            busy = -1
            for j in range(a, b):
                if self.i[j] <= busy or not p[j] > tau:
                    continue
                take.append(j)
                busy = self.i[j] + self.bars["long" if is_long[j] else "short"][j]
        take = np.asarray(take, dtype=int)
        lg = is_long[take]
        t = self.t
        pick = lambda k: np.where(lg, t[f"{k}_long"].to_numpy()[take], t[f"{k}_short"].to_numpy()[take])  # noqa: E731
        return pd.DataFrame({"symbol": self.sym[take], "ts": t["ts"].to_numpy()[take], "side": np.where(lg, "long", "short"),
                             "net_r": pick("net"), "gross_r": pick("gross"), "cost_r": pick("cost"),
                             "reason": pick("reason").astype(int), "pred": p[take]})


# ------------------------------------------------------------------------------------------------ statistics
def wdiff(a: pd.DataFrame, wa: np.ndarray, b: pd.DataFrame, wb: np.ndarray) -> dict:
    """Weighted mean net R of a minus that of b, week-clustered influence se (the weighted analogue of M.arm_diff)."""
    def infl(x, w):
        r = x.net_r.to_numpy(float)
        m = float((w * r).sum() / w.sum())
        wk = pd.to_datetime(x.ts, utc=True).dt.strftime("%G-%V").to_numpy()
        return m, pd.Series(w * (r - m) / w.sum()).groupby(wk).sum()
    ma, ia = infl(a, wa)
    mb, ib = infl(b, wb)
    se = float(np.sqrt((ia.sub(ib, fill_value=0.0) ** 2).sum()))
    d = ma - mb
    return {"n_a": len(a), "n_b": len(b), "mean_a": ma, "mean_b": mb, "delta": d, "se_week_clustered": se, "t": d / se if se > 0 else None}


def bar_series(taken: pd.DataFrame, w: np.ndarray) -> pd.Series:
    return pd.Series(w * taken.net_r.to_numpy(float)).groupby(pd.to_datetime(taken.ts, utc=True).to_numpy()).sum().sort_index()


def sharpe(b: pd.Series) -> float | None:
    sd = float(b.std(ddof=1)) if len(b) > 1 else 0.0
    return float(b.mean() / sd) if sd > 0 else None


def max_dd(b: pd.Series) -> float:
    eq = np.concatenate([[0.0], b.cumsum().to_numpy()])
    return float((np.maximum.accumulate(eq) - eq).max())


def split_weights(taken: pd.DataFrame, rng: np.random.Generator | None = None) -> np.ndarray:
    ts = pd.to_datetime(taken.ts, utc=True).to_numpy()
    if rng is None:
        k = pd.Series(1.0, index=range(len(ts))).groupby(ts).transform("sum").to_numpy()
        return 1.0 / k
    g = rng.exponential(1.0, len(ts))
    return g / pd.Series(g).groupby(ts).transform("sum").to_numpy()


def split_verdict(d: dict, sh: dict, dd: dict, folds_sh: int, rule: dict = SPLIT_RULE) -> tuple[str, str]:
    """PASS iff n_bars >= min AND delta - 2se > -margin (non-inferior per 1R deployed) AND bar Sharpe split > base AND split Sharpe >
    the random-weight control's AND maxDD(split) <= 0.7 x maxDD(base at matched mean risk) AND split Sharpe better in >= 5 of 8 folds.
    FAIL iff delta + 2se < -margin OR bar Sharpe split <= base. INDETERMINATE otherwise."""
    m, t = rule["noninferiority_margin_r"], rule["min_t"]
    if sh["n_bars"] < rule["min_bars"] or d["delta"] is None:
        return "indeterminate", f"bars {sh['n_bars']} < {rule['min_bars']}"
    lo, hi = d["delta"] - t * d["se_week_clustered"], d["delta"] + t * d["se_week_clustered"]
    sb, ss, sr = sh["base"], sh["split"], sh["random"]
    why = (f"delta/1R {d['delta']:+.4f} [{lo:+.4f},{hi:+.4f}]; sharpe split {ss} base {sb} random {sr}; "
           f"dd ratio {dd['ratio']:.3f}; folds sharpe better {folds_sh}")
    if hi < -m or (ss is not None and sb is not None and ss <= sb):
        return "fail", why
    if lo > -m and ss > sb and (sr is None or ss > sr) and dd["ratio"] <= rule["max_dd_ratio"] and folds_sh >= rule["min_folds_sharpe_better"]:
        return "pass", why
    return "indeterminate", why


# ------------------------------------------------------------------------------------------------ columns
def book_columns(tab: pd.DataFrame) -> pd.DataFrame:
    """BOOK_FEATURES per row: outcomes of the decision 24 h earlier (its 24-bar window ends at bar t, so it is closed by t's close)."""
    prev = tab[["symbol", "ts", "net_long", "net_short", "reason_long", "reason_short"]].copy()
    prev["ts"] = prev["ts"] + pd.Timedelta(hours=M.HORIZON_H)
    own = tab[["symbol", "ts"]].merge(prev[["symbol", "ts", "net_long", "net_short"]], on=["symbol", "ts"], how="left")
    xs = prev.groupby("ts").agg(xs_prev_net_long=("net_long", "mean"),
                                xs_prev_stop_long=("reason_long", lambda r: float((r == 1).mean())),
                                xs_prev_stop_short=("reason_short", lambda r: float((r == 1).mean())))
    out = pd.DataFrame({"own_prev_net_long": own["net_long"].to_numpy(), "own_prev_net_short": own["net_short"].to_numpy()})
    x = xs.reindex(pd.to_datetime(tab["ts"], utc=True)).reset_index(drop=True)
    return pd.concat([out, x], axis=1)[BOOK_FEATURES]


def shuffle_ts(tab: pd.DataFrame, cols: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Placebo: each timestamp's values are moved to another (seeded) timestamp; distribution kept, timing destroyed."""
    ts = pd.to_datetime(tab["ts"], utc=True)
    uniq = np.sort(ts.unique())
    perm = np.random.default_rng(seed).permutation(len(uniq))
    src = pd.Series(uniq[perm], index=uniq)
    key = pd.DataFrame({"symbol": tab["symbol"].to_numpy(), "ts": ts.to_numpy()})
    lut = pd.concat([key, cols.reset_index(drop=True)], axis=1).drop_duplicates(["symbol", "ts"]).set_index(["symbol", "ts"])
    want = pd.MultiIndex.from_arrays([key["symbol"], src.reindex(key["ts"]).to_numpy()])
    xs_cols = [c for c in cols if c.startswith("xs_")]
    xs = pd.concat([key[["ts"]], cols[xs_cols].reset_index(drop=True)], axis=1).drop_duplicates("ts").set_index("ts")
    own = lut.reindex(want)[[c for c in cols if not c.startswith("xs_")]].reset_index(drop=True)
    return pd.concat([own, xs.reindex(src.reindex(key["ts"]).to_numpy()).reset_index(drop=True)], axis=1)[list(cols.columns)]


def alt_labels(cache: Path, symbols: list[str], tab: pd.DataFrame, sl=SL_WIDE, tp=TP_WIDE, horizon: int | None = None) -> pd.DataFrame:
    """label_symbol's arithmetic with a different bracket (risk = sl x ATR14), joined to ``tab`` on (symbol, ts). ``sl`` may be a callable
    ts_array -> per-row SL multiple (then TP = ``tp`` x SL, ``tp`` read as a reward:risk ratio)."""
    rows = []
    for sym in symbols:
        df = M.regrid_hourly(pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True))
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
        atr = pd.Series(tr).rolling(M.ATR_N, min_periods=M.ATR_N).mean().to_numpy()
        ts = df["ts"]
        close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
        H, N = (horizon or M.HORIZON_H), len(df)
        cand = np.where((close_hour % M.DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
        cand = cand[cand + H < N]
        t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
        cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * 3_600_000_000_000]
        win = cand[:, None] + np.arange(1, H + 1)[None, :]
        Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
        entry, a = Ob[:, 0], atr[cand]
        sl_r = np.asarray(sl(ts.to_numpy()[cand]), float) if callable(sl) else sl
        tp_r = tp * sl_r if callable(sl) else tp
        risk = sl_r * a
        out = {"symbol": sym, "ts": ts.to_numpy()[cand]}
        for name, side in (("long", 1), ("short", -1)):
            px, j, reason = M.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=sl_r, tp_atr=tp_r)
            gross = side * (px - entry) / risk
            fee, slip, fund = M._cost_r(entry, px, risk, t_ns[cand + 1] / 1e9, t_ns[cand + j] / 1e9 + 3600.0)
            out |= {f"net_{name}": gross - fee - slip - fund, f"gross_{name}": gross, f"cost_{name}": fee + slip + fund,
                    f"reason_{name}": reason, f"bars_{name}": j}
        rows.append(pd.DataFrame(out))
    alt = pd.concat(rows, ignore_index=True)
    alt["ts"] = pd.to_datetime(alt["ts"], utc=True)
    m = tab[["symbol", "ts"]].reset_index().merge(alt, on=["symbol", "ts"], how="left").set_index("index")
    return m.drop(columns=["symbol", "ts"])


# ------------------------------------------------------------------------------------------------ regime-similarity weights
def lim_labels(cache: Path, symbols: list[str], tab: pd.DataFrame, k: float = LIM_K, lw: int = LIM_W, sl: float = SL_XWIDE,
               tp: float = TP_XWIDE) -> pd.DataFrame:
    """Per decision row and side: the outcome of a post-only limit entry ``k`` ATR14 better than bar t+1's open, resting ``lw`` bars, then the
    SL ``sl`` / TP ``tp`` ATR14 bracket measured from the fill for M.HORIZON_H bars (the fill bar counts as the first: its low/high may stop
    the trade, its target side never counts). Unfilled: net = gross = cost = 0, reason -1, bars = lw (busy while the order rests)."""
    from src.runtime.execution_costs import FUNDING_WINDOW_HOURS, resolve_cost_policy
    slip_bps, fund_bps = resolve_cost_policy("BTCUSDT")
    rows = []
    for sym in symbols:
        df = M.regrid_hourly(pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True))
        o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
        atr = pd.Series(tr).rolling(M.ATR_N, min_periods=M.ATR_N).mean().to_numpy()
        ts = df["ts"]
        close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
        H, N = M.HORIZON_H, len(df)
        span = lw + H
        cand = np.where((close_hour % M.DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
        cand = cand[cand + span < N]
        t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
        cand = cand[(t_ns[cand + span] - t_ns[cand]) == span * 3_600_000_000_000]
        a = atr[cand]
        p0 = o[cand + 1]
        out = {"symbol": sym, "ts": ts.to_numpy()[cand]}
        for name, side in (("long", 1), ("short", -1)):
            lim = p0 - side * k * a
            wf = cand[:, None] + np.arange(1, lw + 1)[None, :]
            through = (lo[wf] <= (lim * (1 - LIM_TICK_BPS / 1e4))[:, None]) if side > 0 else (h[wf] >= (lim * (1 + LIM_TICK_BPS / 1e4))[:, None])
            filled = through.any(1)
            jf = np.where(filled, through.argmax(1) + 1, lw)          # offset of the fill bar from the decision bar (1..lw)
            net = np.zeros(len(cand))
            gross = np.zeros(len(cand))
            cost = np.zeros(len(cand))
            reason = np.full(len(cand), -1, dtype=np.int64)
            bars = np.full(len(cand), lw, dtype=np.int64)
            f = np.flatnonzero(filled)
            if len(f):
                fb = cand[f] + jf[f]                                   # absolute index of the fill bar
                win = fb[:, None] + np.arange(0, H)[None, :]
                Ob, Hh, Lb, Cb = o[win].copy(), h[win].copy(), lo[win].copy(), c[win].copy()
                e = lim[f]
                Ob[:, 0] = e
                if side > 0:
                    Hh[:, 0] = e                                       # no target credit on the fill bar
                else:
                    Lb[:, 0] = e
                px, j, rs = M.bracket_outcome(Ob, Hh, Lb, Cb, e, a[f], side, sl_atr=sl, tp_atr=tp)
                risk = sl * a[f]
                g = side * (px - e) / risk
                per_r = ((np.abs(e) + np.abs(px)) / 2.0) / risk
                w = FUNDING_WINDOW_HOURS * 3600.0
                t_in, t_out = t_ns[fb] / 1e9, t_ns[fb + j - 1] / 1e9 + 3600.0
                nwin = np.floor(t_out / w) - np.floor(t_in / w)
                cst = per_r * (MAKER_BPS + TAKER_BPS + slip_bps / 2.0 + fund_bps * nwin) / 1e4
                gross[f], cost[f], net[f] = g, cst, g - cst
                reason[f], bars[f] = rs.astype(np.int64), jf[f] + j - 1
            out |= {f"net_{name}": net, f"gross_{name}": gross, f"cost_{name}": cost, f"reason_{name}": reason, f"bars_{name}": bars}
        rows.append(pd.DataFrame(out))
    alt = pd.concat(rows, ignore_index=True)
    alt["ts"] = pd.to_datetime(alt["ts"], utc=True)
    m = tab[["symbol", "ts"]].reset_index().merge(alt, on=["symbol", "ts"], how="left").set_index("index")
    return m.drop(columns=["symbol", "ts"])


def regime_weights(train: pd.DataFrame, test_start: pd.Timestamp, placebo_seed: int | None = None, bw: float = RSW_BW) -> tuple[np.ndarray, dict]:
    """Gaussian-kernel weights of each training row's regime state to the state just before the test fold. Point-in-time: the reference uses
    only rows strictly before test_start (the last RSW_REF_DAYS of the training window). ``placebo_seed``: states permuted across timestamps."""
    st = train[RSW_STATE].astype(float)
    mu, sd = st.mean(), st.std(ddof=0).replace(0, 1.0)
    z = ((st - mu) / sd).to_numpy()
    ts = pd.to_datetime(train["ts"], utc=True)
    if placebo_seed is not None:                       # permute WHOLE timestamps (all symbols share the market state at a ts)
        uts = np.sort(ts.unique())
        perm = pd.Series(np.random.default_rng(placebo_seed).permutation(uts), index=uts)
        lut = pd.DataFrame(z, columns=RSW_STATE).assign(ts=ts.to_numpy()).drop_duplicates("ts").set_index("ts")
        z = lut.reindex(perm.reindex(ts.to_numpy()).to_numpy()).to_numpy()
    ref_mask = (ts >= test_start - pd.Timedelta(days=RSW_REF_DAYS)).to_numpy()
    ref = np.nanmean(((st[ref_mask] - mu) / sd).to_numpy(), axis=0) if ref_mask.any() else np.zeros(len(RSW_STATE))
    d2 = np.nansum((z - ref) ** 2, axis=1)
    w = np.exp(-d2 / (2.0 * bw * bw))
    w = np.where(np.isfinite(w), w, 0.0)
    w = w / w.mean() if w.mean() > 0 else np.ones(len(w))
    return w, {"ref_state": dict(zip(RSW_STATE, np.round(ref, 4).tolist())), "eff_n_share": float((w.sum() ** 2 / (w ** 2).sum()) / len(w))}


def fit_predict_w(train: pd.DataFrame, test: pd.DataFrame, w: np.ndarray, n_jobs: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """M.fit_predict with per-row sample weights (same FEATURES and LGB_PARAMS)."""
    import lightgbm as lgb
    params = M.LGB_PARAMS if n_jobs is None else {**M.LGB_PARAMS, "n_jobs": n_jobs}
    out = []
    for side in ("long", "short"):
        m = lgb.LGBMRegressor(**params)
        m.fit(train[M.FEATURES], train[f"net_{side}"], sample_weight=w)
        # provenance: predict -- LGBMRegressor.predict is the regressed net R of that side, not a probability
        out.append(m.predict(test[M.FEATURES]))
    return out[0], out[1]


def regime_cells(taken: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Net R per BTC regime cell (30d trend sign x vol percentile above / below 0.5) of the taken decisions. Reported, never gating."""
    if taken.empty:
        return {}
    st = test.drop_duplicates("ts").set_index("ts")[["btc_ret720", "btc_vol_pct90d"]]
    s = st.reindex(pd.to_datetime(taken.ts, utc=True))
    cell = np.where(s.btc_ret720.to_numpy() > 0, "up", "down").astype(object) + np.where(s.btc_vol_pct90d.to_numpy() >= 0.5, "_hivol", "_lovol")
    g = pd.Series(taken.net_r.to_numpy()).groupby(cell)
    return {k: {"n": int(v.count()), "mean_net_r": float(v.mean())} for k, v in g}


# ------------------------------------------------------------------------------------------------ calibration
def calibrated_predict(train: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, n_jobs: int | None = None,
                       blocks: int = CALIB_BLOCKS, recent_only: bool = False) -> tuple[np.ndarray, np.ndarray, dict]:
    """Cross-fitted isotonic calibration: the training window is cut into ``blocks`` time blocks; each block is scored by the recipe fitted on the
    other blocks (rows within the label horizon of the block's edges are dropped from that fit), the out-of-fold predictions are mapped to realised
    net R by an increasing isotonic fit per side, and the map is applied to the full-train predictions ``pl`` / ``ps`` of the test rows."""
    from sklearn.isotonic import IsotonicRegression
    tr = train.sort_values("ts")
    edges = np.array_split(np.arange(len(tr)), blocks)
    hz = pd.Timedelta(hours=M.HORIZON_H + 1)
    oof = {"long": np.full(len(tr), np.nan), "short": np.full(len(tr), np.nan)}
    for idx in edges:
        if len(idx) == 0:
            continue
        t0, t1 = tr.ts.iloc[idx[0]], tr.ts.iloc[idx[-1]]
        fit = tr[(tr.ts < t0 - hz) | (tr.ts > t1 + hz)]
        a, b = M.fit_predict(fit, tr.iloc[idx], None, n_jobs)
        oof["long"][idx], oof["short"][idx] = a, b
    out, info = [], {}
    for side, p in (("long", pl), ("short", ps)):
        y = tr[f"net_{side}"].to_numpy()
        ok = np.isfinite(oof[side])
        if recent_only:                       # ev_calib_recent: fit the map on the last time block only (nearest the test fold)
            last = np.zeros(len(tr), bool)
            last[edges[-1]] = True
            ok &= last
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(oof[side][ok], y[ok])
        # provenance: predict -- IsotonicRegression.predict maps a regressed net R to the calibrated expected net R (R units), not a probability
        out.append(iso.predict(p))
        # provenance: predict -- the same isotonic map on the out-of-fold regressed net R: calibrated expected net R in R units
        info[side] = {"oof_n": int(ok.sum()), "max_calibrated": float(np.max(iso.predict(oof[side][ok]))),
                      "share_test_ev_pos": float(np.mean(out[-1] > EV_TAU))}
    return out[0], out[1], info


# ------------------------------------------------------------------------------------------------ the fold loop
def years_and_folds(cat: dict, folds: list[dict], arm: str, ref: str = "base") -> tuple[int, dict, int]:
    fb = sum(1 for f in folds if f.get(arm) and f[arm]["all"]["mean_net_r"] is not None and f[ref]["all"]["mean_net_r"] is not None
             and f[arm]["all"]["mean_net_r"] > f[ref]["all"]["mean_net_r"])
    yearly = {}
    for y in sorted({pd.Timestamp(f["test_start"]).year for f in folds}):
        a_ = cat[arm][pd.to_datetime(cat[arm].ts, utc=True).dt.year == y]
        b_ = cat[ref][pd.to_datetime(cat[ref].ts, utc=True).dt.year == y]
        yearly[str(y)] = float(a_.net_r.mean() - b_.net_r.mean()) if len(a_) and len(b_) else None
    return fb, yearly, sum(1 for v in yearly.values() if v is not None and v > 0)


def run_arm(tab: pd.DataFrame, arm: str, alt: pd.DataFrame | None = None, n_jobs: int | None = None, folds_lim: int | None = None) -> dict:
    bounds = [pd.Timestamp(x, tz="UTC") for x in M.DEV_FOLDS] + [pd.Timestamp(M.HOLDOUT_START, tz="UTC")]
    dev = tab[tab.ts < bounds[-1]]
    pooled: dict[str, list] = {}
    folds, extra = [], []
    for fi, (a, b) in enumerate(itertools.pairwise(bounds)):
        if folds_lim is not None and fi >= folds_lim:
            break
        test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=M.HORIZON_H + 1))]
        if test.empty:
            continue
        train = M.purge_train(dev, a)
        pl, ps = M.fit_predict(train, test, None, n_jobs)
        seq = Seq(test)
        tk = {"base": seq.run(pl, ps)}
        rng = np.random.default_rng(SEED + fi)
        info: dict = {"test_start": str(a.date())}
        if arm == "long_mute":
            mute = (test.btc_ret168.to_numpy() < 0) & (test.btc_vol_pct90d.to_numpy() >= 0.5)
            cand = (pl >= ps) & (pl > TAU)
            rate = float(mute[cand].mean()) if cand.any() else 0.0
            tk["arm"] = seq.run(np.where(mute, -np.inf, pl), ps)
            tk["control"] = pd.concat([seq.run(np.where(rng.random(len(pl)) < rate, -np.inf, pl), ps) for _ in range(DRAWS)], ignore_index=True)
            tk["short_only"] = seq.run(np.full(len(pl), -np.inf), ps)
            tk["long_tau_020"] = seq.run(np.where(pl > 0.20, pl, -np.inf), ps)
            info |= {"mute_rate_of_long_candidates": rate, "rows_in_mute_cell": float(mute.mean())}
        elif arm == "regime_heads":
            up_tr = train.btc_ret168.to_numpy() >= 0
            up_te = test.btc_ret168.to_numpy() >= 0
            share = float(up_tr.mean())
            coin = lambda d: (pd.util.hash_pandas_object(pd.Series(pd.to_datetime(d.ts, utc=True).astype("int64")), index=False)  # noqa: E731
                              .to_numpy() % 10_000 / 10_000.0) < share
            arms_p = {}
            for name, (mtr, mte) in {"arm": (up_tr, up_te), "control": (coin(train), coin(test))}.items():
                ql, qs = np.zeros(len(test)), np.zeros(len(test))
                for cell in (True, False):
                    if (mte == cell).any():
                        l_, s_ = M.fit_predict(train[mtr == cell], test[mte == cell], None, n_jobs)
                        ql[mte == cell], qs[mte == cell] = l_, s_
                arms_p[name] = (ql, qs)
                tk[name] = seq.run(ql, qs)
            info |= {"train_up_share": share, "test_up_share": float(up_te.mean())}
        elif arm == "book_feats":
            for name, cols in {"arm": BOOK_FEATURES, "control": [f"pb_{c}" for c in BOOK_FEATURES]}.items():
                ql, qs = M.fit_predict(train, test, M.FEATURES + cols, n_jobs)
                tk[name] = seq.run(ql, qs)
        elif arm == "sl_wide":
            seq_alt = Seq(test, alt.loc[test.index])
            tk["arm"] = seq_alt.run(pl, ps)
            rb, ra = [], []
            for _ in range(DRAWS):
                side_long = rng.random(len(pl)) < 0.5
                fl, fs = np.where(side_long, 1.0, -1.0), np.where(side_long, -1.0, 1.0)
                rb.append(seq.run(fl, fs, tau=0.0))
                ra.append(seq_alt.run(fl, fs, tau=0.0))
            tk["control_base_bracket"], tk["control"] = pd.concat(rb, ignore_index=True), pd.concat(ra, ignore_index=True)
        elif arm in ("sl_wide_retrain", "sl_xwide_retrain", "sl_xwide_h48_retrain"):
            lab = [c for c in alt.columns if c.split("_")[0] in ("net", "gross", "cost", "reason", "bars")]
            tr_alt = train.assign(**{c: alt.loc[train.index, c] for c in lab})
            al, as_ = M.fit_predict(tr_alt, test, None, n_jobs)
            seq_alt = Seq(test, alt.loc[test.index])
            tk["arm"] = seq_alt.run(al, as_)
            rb, ra = [], []
            for _ in range(DRAWS):
                side_long = rng.random(len(pl)) < 0.5
                fl, fs = np.where(side_long, 1.0, -1.0), np.where(side_long, -1.0, 1.0)
                rb.append(seq.run(fl, fs, tau=0.0))
                ra.append(seq_alt.run(fl, fs, tau=0.0))
            tk["control_base_bracket"], tk["control"] = pd.concat(rb, ignore_index=True), pd.concat(ra, ignore_index=True)
        elif arm in ("volsl_retrain", "rsz_xwide"):
            alt, alt2 = alt
            lab = [c for c in alt.columns if c.split("_")[0] in ("net", "gross", "cost", "reason", "bars")]
            tr_fix = train.assign(**{c: alt.loc[train.index, c] for c in lab})
            seq_fix = Seq(test, alt.loc[test.index])
            fl_, fs_ = M.fit_predict(tr_fix, test, None, n_jobs)
            tk["fixed"] = seq_fix.run(fl_, fs_)
            if arm == "volsl_retrain":
                tr_v = train.assign(**{c: alt2.loc[train.index, c] for c in lab})
                seq_v = Seq(test, alt2.loc[test.index])
                vl, vs = M.fit_predict(tr_v, test, None, n_jobs)
                tk["arm"] = seq_v.run(vl, vs)
                rb, ra = [], []
                for _ in range(DRAWS):
                    side_long = rng.random(len(pl)) < 0.5
                    fl, fs = np.where(side_long, 1.0, -1.0), np.where(side_long, -1.0, 1.0)
                    rb.append(seq_fix.run(fl, fs, tau=0.0))
                    ra.append(seq_v.run(fl, fs, tau=0.0))
                tk["control_base_bracket"], tk["control"] = pd.concat(rb, ignore_index=True), pd.concat(ra, ignore_index=True)
                info["regime_cells"] = {k: regime_cells(tk[k], test) for k in ("fixed", "arm")}
            else:
                fx = tk["fixed"]
                vol = test.drop_duplicates("ts").set_index("ts")["btc_vol24"].reindex(pd.to_datetime(fx.ts, utc=True)).to_numpy()
                med = float(np.nanmedian(train.btc_vol24))
                w = np.clip(med / np.where(np.isfinite(vol) & (vol > 0), vol, med), *RSZ_CAP)
                w = w / w.mean() if len(w) else w
                perms = [w[rng.permutation(len(w))] for _ in range(DRAWS)]     # DRAWS permuted-weight controls (same weights, random bars)
                bs, bb = bar_series(fx, w), bar_series(fx, np.ones(len(fx)))
                info |= {"sharpe_split": sharpe(bs), "sharpe_base": sharpe(bb),
                         "sharpe_random_mean": float(np.nanmean([sharpe(bar_series(fx, pw)) or np.nan for pw in perms]))}
                extra.append((fx, w, perms))
        elif arm == "lim_xwide":
            fixed, lim = alt
            lab = [c for c in fixed.columns if c.split("_")[0] in ("net", "gross", "cost", "reason", "bars")]
            tr_fix = train.assign(**{c: fixed.loc[train.index, c] for c in lab})
            fl_, fs_ = M.fit_predict(tr_fix, test, None, n_jobs)
            tk["fixed"] = Seq(test, fixed.loc[test.index]).run(fl_, fs_)
            tk["arm"] = Seq(test, lim.loc[test.index]).run(fl_, fs_)
            fill = float((tk["arm"].reason != -1).mean()) if len(tk["arm"]) else 0.0
            fx = fixed.loc[test.index, lab]
            ctl = []
            for _ in range(DRAWS):
                keep = rng.random(len(fx)) < fill
                cc = fx.copy()
                for sd in ("long", "short"):
                    for col in ("net", "gross", "cost"):
                        cc.loc[~keep, f"{col}_{sd}"] = 0.0
                    cc.loc[~keep, f"reason_{sd}"] = -1
                    cc.loc[~keep, f"bars_{sd}"] = LIM_W
                ctl.append(Seq(test, cc).run(fl_, fs_))
            tk["control"] = pd.concat(ctl, ignore_index=True)
            filled = tk["arm"][tk["arm"].reason != -1]
            info |= {"fill_rate": fill, "filled_mean_net_r": float(filled.net_r.mean()) if len(filled) else None,
                     "filled_mean_cost_r": float(filled.cost_r.mean()) if len(filled) else None}
        elif arm == "rsw_xwide_h48":
            lab = [c for c in alt.columns if c.split("_")[0] in ("net", "gross", "cost", "reason", "bars")]
            tr_alt = train.assign(**{c: alt.loc[train.index, c] for c in lab})
            seq_alt = Seq(test, alt.loc[test.index])
            ul, us = M.fit_predict(tr_alt, test, None, n_jobs)
            w, winfo = regime_weights(tr_alt, a)
            wl, ws = fit_predict_w(tr_alt, test, w, n_jobs)
            pw, _ = regime_weights(tr_alt, a, placebo_seed=SEED + fi)
            ql, qs = fit_predict_w(tr_alt, test, pw, n_jobs)
            tk["uniform"], tk["arm"], tk["control"] = seq_alt.run(ul, us), seq_alt.run(wl, ws), seq_alt.run(ql, qs)
            info |= {"regime_weights": winfo, "regime_cells": {k: regime_cells(tk[k], test) for k in ("uniform", "arm", "control")}}
        elif arm in ("ev_calib", "ev_cap3", "ev_calib_recent"):
            cl, cs, cinfo = calibrated_predict(train, pl, ps, n_jobs, recent_only=arm == "ev_calib_recent")
            info["calibration"] = cinfo
            if arm in ("ev_calib", "ev_calib_recent"):
                tk["arm"] = seq.run(cl, cs, tau=EV_TAU)
                nb = tk["base"].side.value_counts()
                na = tk["arm"].side.value_counts()
                rate = {sd: min(1.0, float(na.get(sd, 0)) / float(nb[sd])) if nb.get(sd, 0) else 0.0 for sd in ("long", "short")}
                info["take_rate_vs_base"] = rate
                tk["control"] = pd.concat([seq.run(np.where(rng.random(len(pl)) < rate["long"], pl, -np.inf),
                                                   np.where(rng.random(len(ps)) < rate["short"], ps, -np.inf)) for _ in range(DRAWS)], ignore_index=True)
            else:
                tk["arm"] = M.policy_bar_topk(test, cl, cs, EV_TAU, CAP_K)
                tk["control"] = pd.concat([M.policy_bar_topk(test, cl, cs, EV_TAU, CAP_K, rng=rng) for _ in range(DRAWS)], ignore_index=True)
                tk["calib_uncapped"] = seq.run(cl, cs, tau=EV_TAU)
        elif arm == "bar_split":
            base = tk["base"]
            w = split_weights(base)
            ctl_w = [split_weights(base, rng) for _ in range(DRAWS)]
            bs, bb = bar_series(base, w), bar_series(base, np.ones(len(base)))
            info |= {"sharpe_split": sharpe(bs), "sharpe_base": sharpe(bb),
                     "sharpe_random_mean": float(np.nanmean([sharpe(bar_series(base, cw)) or np.nan for cw in ctl_w]))}
            extra.append((base, w, ctl_w))
        for k, v in tk.items():
            pooled.setdefault(k, []).append(v)
            info[k] = M.split_by_side(v)
        folds.append(info)
        print(json.dumps({"fold": info["test_start"]} | {k: (info[k]["all"]["n"], info[k]["all"]["mean_net_r"]) for k in tk}), flush=True)
    cat = {k: pd.concat(v, ignore_index=True) for k, v in pooled.items()}
    res = {"arm": arm, "folds": folds, "pooled": {k: M.split_by_side(v) | {"bar_risk": M.bar_risk(v)} for k, v in cat.items()}}
    if arm in ("bar_split", "rsz_xwide"):
        base = cat["base"] if arm == "bar_split" else cat["fixed"]
        w = np.concatenate([e[1] for e in extra])
        ctl = pd.concat([e[0] for e in extra for _ in range(DRAWS)], ignore_index=True)
        ctl_w = np.concatenate([cw for e in extra for cw in e[2]]) / DRAWS
        d = wdiff(base, w, base, np.ones(len(base)))
        bs, bb = bar_series(base, w), bar_series(base, np.ones(len(base)))
        mean_k = float(len(base) / len(bb))
        rnd = [sharpe(bar_series(e[0], cw)) for e in extra for cw in e[2]]
        sh = {"n_bars": len(bb), "split": sharpe(bs), "base": sharpe(bb), "random": float(np.nanmean([x for x in rnd if x is not None]))}
        dd = {"split_max_dd_r": max_dd(bs), "base_max_dd_r_full": max_dd(bb), "base_max_dd_r_matched_mean_risk": max_dd(bb / mean_k),
              "mean_entries_per_bar": mean_k}
        dd["ratio"] = dd["split_max_dd_r"] / dd["base_max_dd_r_matched_mean_risk"] if dd["base_max_dd_r_matched_mean_risk"] > 0 else float("inf")
        folds_sh = sum(1 for f in folds if f["sharpe_split"] is not None and f["sharpe_base"] is not None and f["sharpe_split"] > f["sharpe_base"])
        v, why = split_verdict(d, sh, dd, folds_sh, SPLIT_RULE if arm == "bar_split" else RSZ_RULE)
        _ = ctl, ctl_w
        res |= {"diffs": {"split_vs_base_per_1R": d}, "bar_sharpe": sh, "drawdown": dd, "folds_sharpe_better": folds_sh,
                "verdict": v, "why": why, "n": len(bb), "rule": SPLIT_RULE if arm == "bar_split" else RSZ_RULE}
        return res
    ref = "uniform" if arm == "rsw_xwide_h48" else ("fixed" if arm in ("volsl_retrain", "lim_xwide") else "base")      # rsw: the one factor is the weighting, so the comparator is the same recipe unweighted
    diffs = {"vs_base": M.arm_diff(cat["arm"], cat[ref]), "vs_control": M.arm_diff(cat["arm"], cat["control"])}
    if arm == "rsw_xwide_h48":
        diffs["uniform_vs_registered_base"] = M.arm_diff(cat["uniform"], cat["base"])
    if arm in ("sl_wide", "sl_wide_retrain", "sl_xwide_retrain", "sl_xwide_h48_retrain", "volsl_retrain"):
        diffs["control_alt_vs_base_bracket"] = M.arm_diff(cat["control"], cat["control_base_bracket"])
    fb, yearly, ys = years_and_folds(cat, folds, "arm", ref)
    ctl_gates = arm not in ("sl_wide", "sl_wide_retrain", "sl_xwide_retrain", "sl_xwide_h48_retrain", "volsl_retrain")
    v, why = M.lever_verdict(diffs, fb, ys, rule=LEVER, control="vs_control" if ctl_gates else None)
    res |= {"diffs": diffs, "folds_better": fb, "n_folds": len(folds), "yearly_delta": yearly, "years_positive": ys,
            "verdict": v, "why": why, "n": diffs["vs_base"]["n_a"], "rule": LEVER, "control_gates": ctl_gates}
    return res


def build(cache: Path, arm: str) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    syms = M.universe()
    tab = M.build_table(cache, syms)
    alt = None
    if arm in ("long_mute", "regime_heads"):
        tab = pd.concat([tab.reset_index(drop=True), M.regime_columns(cache, syms, tab)[M.REGIME_FEATURES]], axis=1)
        tab = tab.dropna(subset=["btc_ret168", "btc_vol_pct90d"]).reset_index(drop=True)
    if arm == "book_feats":
        bc = book_columns(tab)
        pb = shuffle_ts(tab, bc).add_prefix("pb_")
        tab = pd.concat([tab.reset_index(drop=True), bc, pb], axis=1)
    if arm in ("volsl_retrain", "rsz_xwide"):
        tab = pd.concat([tab.reset_index(drop=True), M.regime_columns(cache, syms, tab)[M.REGIME_FEATURES]], axis=1)
        tab = tab.dropna(subset=["btc_vol_pct90d"]).reset_index(drop=True)
        fixed = alt_labels(cache, syms, tab, SL_XWIDE, TP_XWIDE)
        vp = tab.drop_duplicates("ts").set_index(pd.to_datetime(tab.drop_duplicates("ts").ts, utc=True))["btc_vol_pct90d"]

        def sl_of(ts_arr, _vp=vp):
            v = _vp.reindex(pd.to_datetime(ts_arr, utc=True)).to_numpy()
            return VOLSL_LO + (VOLSL_HI - VOLSL_LO) * np.where(np.isfinite(v), v, 0.5)
        volsl = alt_labels(cache, syms, tab, sl_of, TP_XWIDE / SL_XWIDE) if arm == "volsl_retrain" else fixed
        ok = (fixed["net_long"].notna() & fixed["net_short"].notna() & volsl["net_long"].notna() & volsl["net_short"].notna()).to_numpy()
        return tab[ok], (fixed[ok], volsl[ok])
    if arm == "lim_xwide":
        fixed = alt_labels(cache, syms, tab, SL_XWIDE, TP_XWIDE)
        lim = lim_labels(cache, syms, tab)
        ok = (fixed["net_long"].notna() & fixed["net_short"].notna() & lim["net_long"].notna() & lim["net_short"].notna()).to_numpy()
        return tab[ok], (fixed[ok], lim[ok])
    if arm == "rsw_xwide_h48":
        tab = pd.concat([tab.reset_index(drop=True), M.regime_columns(cache, syms, tab)[M.REGIME_FEATURES]], axis=1)
        tab = tab.dropna(subset=RSW_STATE).reset_index(drop=True)
    if arm in ("sl_wide", "sl_wide_retrain", "sl_xwide_retrain", "sl_xwide_h48_retrain", "rsw_xwide_h48"):
        tab = tab.reset_index(drop=True)
        sl_tp = (SL_XWIDE, TP_XWIDE) if arm in ("sl_xwide_retrain", "sl_xwide_h48_retrain", "rsw_xwide_h48") else (SL_WIDE, TP_WIDE)
        alt = alt_labels(cache, syms, tab, *sl_tp, horizon=H48 if arm in ("sl_xwide_h48_retrain", "rsw_xwide_h48") else None)
        ok = alt["net_long"].notna() & alt["net_short"].notna()
        tab, alt = tab[ok.to_numpy()], alt[ok]
    return tab, alt


def cache_fingerprint(cache: Path, symbols: list[str], fetch_report: dict | None = None) -> dict:
    """What the run READ (PI-20261124-LDATAEND-0001: two runs with the same --run-date built tables of 72,996 vs 73,236 decisions). sha256 over
    each symbol's (rows, first bar, last bar, close checksum), plus the archives fetch_through could not get (404 / not yet published), so a
    re-run that read different data is visible in its verdict instead of silently differing."""
    import hashlib
    h, per, missing = hashlib.sha256(), {}, {}
    for sym in symbols:
        f = cache / f"{sym}.pkl"
        if not f.exists():
            per[sym] = None
            continue
        df = pd.read_pickle(f)
        key = (len(df), str(df.ts.min()), str(df.ts.max()), round(float(df.close.sum()), 6))
        per[sym] = key
        h.update(repr((sym,) + key).encode())
    for sym, rep in (fetch_report or {}).items():
        if rep.get("missing"):
            missing[sym] = rep["missing"]
    return {"sha256": h.hexdigest(), "n_symbols": sum(v is not None for v in per.values()), "missing_archives": missing,
            "provenance": "MEASURED (read from the klines cache this run used)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=ARMS)
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_fix_arms")
    ap.add_argument("--unit", default="")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run-date", default="2026-11-22")
    ap.add_argument("--folds", type=int, default=None, help="diagnostic only: first N dev folds (never for a registered read)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if not a.arm:
        ap.error("--arm is required")
    from datetime import date

    import ml_entry_retrain as R
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fetch_report = R.fetch_through(cache, M.universe(), R.plan(date.fromisoformat(a.run_date))) if a.fetch else None
    data_fp = cache_fingerprint(cache, M.universe(), fetch_report)
    tab, alt = build(cache, a.arm)
    res = run_arm(tab, a.arm, alt, folds_lim=a.folds)
    pop = (f"registered recipe refit per dev fold {M.DEV_FOLDS[0]}..{M.HOLDOUT_START} (60-perp frozen universe, {tab.symbol.nunique()} symbols, "
           f"{len(tab)} rows), tau {TAU}, net R fee {M.FEE_BPS}+slip 3+funding 1 bps/8h, week-clustered se; arm {a.arm}"
           + (f"; DIAGNOSTIC first {a.folds} folds only" if a.folds else ""))
    res |= {"data_fingerprint": data_fp, "schema": "ml_entry_fix_arms/1", "unit": a.unit, "git_sha": M._git_sha(), "population": pop, "elapsed_s": round(time.time() - t0),
            "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    verdict = res["verdict"] if not a.folds else "indeterminate"
    vj = {"verdict": verdict, "read_state": "measured", "n": res["n"], "note": res["why"], "population": pop, "arm": a.arm,
          "rule": res["rule"], "data_window": {"klines_cache_sha256": data_fp["sha256"], "n_symbols": data_fp["n_symbols"],
                                               "missing_archives": data_fp["missing_archives"]},
          "measurement": {k: v for k, v in res.items() if k not in ("folds",)}}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"arm": a.arm, "verdict": verdict, "why": res["why"]}), flush=True)
    return 0


def _self_test() -> None:
    ts = pd.to_datetime(["2025-01-01 00:00"] * 3 + ["2025-01-01 04:00"], utc=True)
    test = pd.DataFrame({"symbol": ["A", "B", "C", "A"], "i": [0, 0, 0, 4], "ts": ts,
                         "net_long": [1.0, -1.0, 0.5, 2.0], "net_short": [0.3] * 4, "gross_long": [1.0, -1.0, 0.5, 2.0],
                         "gross_short": [0.3] * 4, "cost_long": [0.0] * 4, "cost_short": [0.0] * 4, "reason_long": [2, 1, 0, 2],
                         "reason_short": [0] * 4, "bars_long": [24] * 4, "bars_short": [2] * 4}, index=[10, 11, 12, 13])
    pl, ps = np.array([0.5, 0.9, 0.05, 0.6]), np.array([0.0, 0.0, 0.2, 0.0])
    ref = M.policy(test, pl, ps, TAU)
    got = Seq(test).run(pl, ps)
    assert list(got.symbol) == list(ref.symbol) and np.allclose(got.net_r, ref.net_r), (got, ref)   # identical to the registered policy
    mute = Seq(test).run(np.where([True, False, False, False], -np.inf, pl), ps)
    assert list(mute.symbol) == ["A", "B", "C"] and list(mute.side) == ["long", "long", "short"] and str(mute.ts[0])[11:16] == "04:00", mute   # A muted at 00:00 -> free at 04:00
    w = split_weights(ref)
    assert np.allclose(w, [1 / 3] * 3), w
    rw = split_weights(ref, np.random.default_rng(0))
    assert abs(rw.sum() - 1.0) < 1e-12
    d = wdiff(ref, w, ref, np.ones(len(ref)))
    assert abs(d["delta"]) < 1e-12                                     # equal weights within one bar: same mean per 1R
    bad = {"delta": -0.05, "se_week_clustered": 0.01}
    assert split_verdict(bad, {"n_bars": 5000, "split": 0.1, "base": 0.05, "random": 0.0}, {"ratio": 0.5}, 8)[0] == "fail"
    good = {"delta": 0.0, "se_week_clustered": 0.002}
    assert split_verdict(good, {"n_bars": 5000, "split": 0.1, "base": 0.05, "random": 0.0}, {"ratio": 0.5}, 6)[0] == "pass"
    assert split_verdict(good, {"n_bars": 5000, "split": 0.04, "base": 0.05, "random": 0.0}, {"ratio": 0.5}, 6)[0] == "fail"
    tab = pd.DataFrame({"symbol": ["A", "A", "B", "B"], "ts": pd.to_datetime(["2025-01-01 00:00", "2025-01-02 00:00"] * 2, utc=True),
                        "net_long": [1.0, 2.0, -1.0, 0.0], "net_short": [-1.0, -2.0, 1.0, 0.0], "reason_long": [2, 0, 1, 0], "reason_short": [1, 0, 2, 0]})
    bc = book_columns(tab)
    assert np.isnan(bc.own_prev_net_long[0]) and bc.own_prev_net_long[1] == 1.0 and bc.own_prev_net_long[3] == -1.0
    assert bc.xs_prev_net_long[1] == 0.0 and bc.xs_prev_stop_long[1] == 0.5 and bc.xs_prev_stop_short[1] == 0.5
    sh = shuffle_ts(tab, bc)
    assert sh.shape == bc.shape and sorted(sh.own_prev_net_long.fillna(9)) == sorted(bc.own_prev_net_long.fillna(9))
    # regime_weights: mean 1; rows whose state matches the pre-test reference weigh most; the placebo permutes whole timestamps
    tsr = pd.date_range("2024-01-01", periods=40, freq="1D", tz="UTC")
    tr = pd.DataFrame({"ts": np.repeat(tsr, 2), "btc_ret720": np.repeat(np.r_[np.full(30, -0.2), np.full(10, 0.2)], 2),
                       "btc_dist_sma1200": np.repeat(np.r_[np.full(30, -0.1), np.full(10, 0.1)], 2),
                       "btc_vol_pct90d": np.repeat(np.r_[np.full(30, 0.9), np.full(10, 0.2)], 2)})
    w, wi = regime_weights(tr, tsr[-1] + pd.Timedelta(days=1))
    assert abs(w.mean() - 1.0) < 1e-9 and w[-1] > w[0] and 0 < wi["eff_n_share"] <= 1.0, (w[:3], w[-3:], wi)
    wp, _ = regime_weights(tr, tsr[-1] + pd.Timedelta(days=1), placebo_seed=1)
    assert abs(wp.mean() - 1.0) < 1e-9 and not np.allclose(wp, w)
    assert np.allclose(wp[0::2], wp[1::2])            # both symbols at one timestamp share a weight under the placebo too
    # lim_labels: flat 100 +- 0.5 bars (ATR 1): a long limit at 99.5 never fills strictly; one bar dipping to 99.0 fills it at 99.5, and the
    # flat path then time-exits at 100 -> gross +0.5 / (4 x 1) = +0.125 R, cost 25 x (2 + 5.5 + 1.5 + funding) bps >= 0.0225 R; the short side (limit 100.5, never traded through) stays unfilled
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        n_b = 120
        tsb = pd.date_range("2025-01-01", periods=n_b, freq="1h", tz="UTC")
        lo_b = np.full(n_b, 99.5)
        k_dip = 60
        lo_b[k_dip] = 99.0
        pd.DataFrame({"ts": tsb, "open": 100.0, "high": 100.5, "low": lo_b, "close": 100.0, "volume": 1.0}).to_pickle(Path(td) / "A.pkl")
        dec = [i for i in range(n_b) if (tsb[i] + pd.Timedelta(hours=1)).hour % M.DECISION_EVERY_H == 0]
        tabl = pd.DataFrame({"symbol": "A", "ts": tsb[dec]})
        lab = lim_labels(Path(td), ["A"], tabl)
        hit = [j for j, i in enumerate(dec) if k_dip - LIM_W <= i < k_dip and lab.net_long.notna().iloc[j]]
        miss = [j for j, i in enumerate(dec) if i < k_dip - LIM_W and lab.net_long.notna().iloc[j]]
        assert hit and miss, (hit, miss)
        assert all(lab.reason_long.iloc[j] == -1 and lab.net_long.iloc[j] == 0.0 for j in miss)
        assert all(lab.reason_long.iloc[j] == 0 and abs(lab.gross_long.iloc[j] - 0.125) < 1e-9 for j in hit), lab.iloc[hit]
        assert all(0.0225 <= lab.cost_long.iloc[j] < 0.03 for j in hit) and (lab.reason_short.dropna() == -1).all()
    print("self-test ok")


if __name__ == "__main__":
    sys.exit(main())
