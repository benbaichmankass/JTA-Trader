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

ARMS = ["long_mute", "bar_split", "regime_heads", "book_feats", "sl_wide", "ev_calib", "ev_cap3", "sl_wide_retrain"]
CALIB_BLOCKS = 4                      # time blocks of the training window for the cross-fitted calibration map
EV_TAU = 0.0                          # ev_calib / ev_cap3 trade iff the CALIBRATED expected net R (full cost stack) > 0
CAP_K = 3
DRAWS = 100                           # matched-random draws (research-queue-design-fields-guard minimum)
TAU = 0.10
SEED = 20261124
BOOK_FEATURES = ["own_prev_net_long", "own_prev_net_short", "xs_prev_net_long", "xs_prev_stop_long", "xs_prev_stop_short"]
SL_WIDE, TP_WIDE = 3.0, 4.5
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


def alt_labels(cache: Path, symbols: list[str], tab: pd.DataFrame, sl: float = SL_WIDE, tp: float = TP_WIDE) -> pd.DataFrame:
    """label_symbol's arithmetic with a different bracket (risk = sl x ATR14), joined to ``tab`` on (symbol, ts)."""
    rows = []
    for sym in symbols:
        df = M.regrid_hourly(pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True))
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
        atr = pd.Series(tr).rolling(M.ATR_N, min_periods=M.ATR_N).mean().to_numpy()
        ts = df["ts"]
        close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
        H, N = M.HORIZON_H, len(df)
        cand = np.where((close_hour % M.DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
        cand = cand[cand + H < N]
        t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
        cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * 3_600_000_000_000]
        win = cand[:, None] + np.arange(1, H + 1)[None, :]
        Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
        entry, a = Ob[:, 0], atr[cand]
        risk = sl * a
        out = {"symbol": sym, "ts": ts.to_numpy()[cand]}
        for name, side in (("long", 1), ("short", -1)):
            px, j, reason = M.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=sl, tp_atr=tp)
            gross = side * (px - entry) / risk
            fee, slip, fund = M._cost_r(entry, px, risk, t_ns[cand + 1] / 1e9, t_ns[cand + j] / 1e9 + 3600.0)
            out |= {f"net_{name}": gross - fee - slip - fund, f"gross_{name}": gross, f"cost_{name}": fee + slip + fund,
                    f"reason_{name}": reason, f"bars_{name}": j}
        rows.append(pd.DataFrame(out))
    alt = pd.concat(rows, ignore_index=True)
    alt["ts"] = pd.to_datetime(alt["ts"], utc=True)
    m = tab[["symbol", "ts"]].reset_index().merge(alt, on=["symbol", "ts"], how="left").set_index("index")
    return m.drop(columns=["symbol", "ts"])


# ------------------------------------------------------------------------------------------------ calibration
def calibrated_predict(train: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, n_jobs: int | None = None,
                       blocks: int = CALIB_BLOCKS) -> tuple[np.ndarray, np.ndarray, dict]:
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
        elif arm == "sl_wide_retrain":
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
        elif arm in ("ev_calib", "ev_cap3"):
            cl, cs, cinfo = calibrated_predict(train, pl, ps, n_jobs)
            info["calibration"] = cinfo
            if arm == "ev_calib":
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
    if arm == "bar_split":
        base = cat["base"]
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
        v, why = split_verdict(d, sh, dd, folds_sh)
        _ = ctl, ctl_w
        res |= {"diffs": {"split_vs_base_per_1R": d}, "bar_sharpe": sh, "drawdown": dd, "folds_sharpe_better": folds_sh,
                "verdict": v, "why": why, "n": len(bb), "rule": SPLIT_RULE}
        return res
    diffs = {"vs_base": M.arm_diff(cat["arm"], cat["base"]), "vs_control": M.arm_diff(cat["arm"], cat["control"])}
    if arm in ("sl_wide", "sl_wide_retrain"):
        diffs["control_alt_vs_base_bracket"] = M.arm_diff(cat["control"], cat["control_base_bracket"])
    fb, yearly, ys = years_and_folds(cat, folds, "arm")
    ctl_gates = arm not in ("sl_wide", "sl_wide_retrain")
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
    if arm in ("sl_wide", "sl_wide_retrain"):
        tab = tab.reset_index(drop=True)
        alt = alt_labels(cache, syms, tab)
        ok = alt["net_long"].notna() & alt["net_short"].notna()
        tab, alt = tab[ok.to_numpy()], alt[ok]
    return tab, alt


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
    if a.fetch:
        R.fetch_through(cache, M.universe(), R.plan(date.fromisoformat(a.run_date)))
    tab, alt = build(cache, a.arm)
    res = run_arm(tab, a.arm, alt, folds_lim=a.folds)
    pop = (f"registered recipe refit per dev fold {M.DEV_FOLDS[0]}..{M.HOLDOUT_START} (60-perp frozen universe, {tab.symbol.nunique()} symbols, "
           f"{len(tab)} rows), tau {TAU}, net R fee {M.FEE_BPS}+slip 3+funding 1 bps/8h, week-clustered se; arm {a.arm}"
           + (f"; DIAGNOSTIC first {a.folds} folds only" if a.folds else ""))
    res |= {"schema": "ml_entry_fix_arms/1", "unit": a.unit, "git_sha": M._git_sha(), "population": pop, "elapsed_s": round(time.time() - t0),
            "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    verdict = res["verdict"] if not a.folds else "indeterminate"
    vj = {"verdict": verdict, "read_state": "measured", "n": res["n"], "note": res["why"], "population": pop, "arm": a.arm,
          "rule": res["rule"], "measurement": {k: v for k, v in res.items() if k not in ("folds",)}}
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
    print("self-test ok")


if __name__ == "__main__":
    sys.exit(main())
