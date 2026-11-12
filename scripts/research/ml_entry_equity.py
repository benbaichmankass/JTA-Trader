#!/usr/bin/env python3
# wiring: research/queue/RQ-20261105-e9a1-01.yaml (dev) and RQ-20261105-e9a1-02.yaml (confirm); lane ML-ENTRY-EQUITY-NATIVE
"""EQUITY-NATIVE ENTRY model: trained on the 173-ETF Alpaca liquidity pool itself (row ML-ENTRY-EQUITY-NATIVE).

Operator popup 2026-11-05 ~20:50Z, verbatim: "Equity-native model (Rec.)", after the frozen crypto ENTRY v1 FAILED on this pool
(RQ-20261104-a41f-01: -0.0708 R at n 1099; gross +0.011 R vs cost 0.082 R). NOT the v1 artifact: a NEW LightGBM long-side net-R regressor
whose features are equity-native; NO BTC / crypto-breadth feature.

* POPULATION: the registered POOL_RULE of ml_entry_alpaca_score.py, UNCHANGED (sha256 e9702661...), rebuilt at run time.
* FEATURES: own price/volume/volatility (the 15 harness features), cross-sectional ranks and breadth ACROSS THE POOL at the same close,
  and market context from equity proxies (SPY, QQQ, IWM, TLT, VIXY as the VIX proxy).
* LABEL / EXECUTION (unchanged from the v1 read so the comparison is like for like): decisions at RTH closes with UTC hour % 4 == 0 that
  pass the live session gate; LONG when the regressed net R > tau (restricted argmax); entry next RTH open; SL 2 / TP 3 ATR14 / 24-bar
  time stop; one position per symbol; net of fee 0 + slippage 5 bps (PROVISIONAL) + regulatory 0.5 bps round trip.
* DEV stage: purged expanding walk-forward on dates <= TRAIN_END ONLY (the confirming window is never loaded), a fixed grid of
  CONFIGS x TAUS, selection = the registered criterion; unlimited iteration is allowed here (principles M13) and is not claimed.
* CONFIRM stage: refit the SAME config on all rows <= TRAIN_END (deterministic seed), score the time-disjoint window
  CONFIRM_START..last complete month ONCE, graded against the deflated bar holdout_lock.bar_for(N) with the read recorded in the ledger.

    python3 scripts/research/ml_entry_equity.py --self-test
    python3 scripts/research/ml_entry_equity.py dev     --cache /tmp/c --out /tmp/o --unit RQ-... --where research-script-run
    python3 scripts/research/ml_entry_equity.py confirm --cache /tmp/c --out /tmp/o --unit RQ-... --config A --tau 0.1 --dev-oof-mean 0.01
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E  # noqa: E402
import ml_entry_alpaca_score as S  # noqa: E402
import holdout_lock as HL  # noqa: E402

SCHEMA = "ml_entry_equity/1"
FAMILY = "ENTRY-EQ"
DATA_START = "2021-01-01"          # bars fetched from here; first ~337 RTH bars are feature warm-up
TRAIN_END = "2025-06-30"           # the last date the model may see (dev folds and the final fit stop here)
CONFIRM_START = "2025-07-15"       # > TRAIN_END + embargo (15 d > 2 x the 24-bar label horizon); enforced
PURGE_DAYS = 10                    # rows whose 24-bar label window reaches past a cut are dropped from training
EMBARGO_DAYS = 14
PROXIES = ["SPY", "QQQ", "IWM", "TLT", "VIXY"]
DEV_FOLDS = ["2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01"]   # each tests [start, next); the last to TRAIN_END
TAUS = [0.05, 0.10, 0.15, 0.20]
MIN_OOF_N = 300                    # selection constraint: a config/tau must take at least this many dev OOF trades
H = S.H
BASE_PARAMS = {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 500, "subsample": 0.8,
               "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": 20261105, "verbose": -1,
               "n_jobs": 4}
OWN = ["ret_1", "ret_4", "ret_12", "ret_24", "ret_72", "ret_168", "vol24", "vol_ratio", "atr_pct", "range_pos_24",
       "range_pos_168", "vol_z", "rsi14", "hour", "dow"]
XS = ["xs_rank_ret24", "xs_rank_ret168", "xs_rank_vol24", "xs_rank_volz", "breadth_up24", "rel_vol"]
MKT = ["spy_ret24", "spy_ret168", "spy_vol24", "qqq_ret24", "iwm_ret24", "tlt_ret24", "vixy_ret24", "vixy_vol24", "rel_ret_spy"]
CONFIGS = {   # the whole grid, fixed here BEFORE any dev result: 3 configs x 4 taus = 12 selection draws
    "A": {"features": OWN + XS + MKT, "params": {}},
    "B": {"features": OWN + XS, "params": {}},                                         # no market-context proxies
    "C": {"features": OWN + XS + MKT, "params": {"n_estimators": 200, "num_leaves": 15, "min_child_samples": 2000}},
}
REGISTERED_SELECTION = ("max pooled dev out-of-fold mean net R over (config, tau) subject to >= %d OOF trades" % MIN_OOF_N)


class _Ensemble:
    """Mean of several LGBMRegressors that differ only by seed (dev-stage variance reduction; no booster_ -- never exported or confirmed as is)."""

    def __init__(self, models):
        self.models = models

    def fit(self, X, y):
        for m in self.models:
            m.fit(X, y)
        return self

    def predict(self, X):
        return np.mean([m.predict(X) for m in self.models], axis=0)


def _lgb(params: dict):
    import lightgbm as lgb
    if "_ens_seeds" in params:
        base = {k: v for k, v in params.items() if k != "_ens_seeds"}
        return _Ensemble([lgb.LGBMRegressor(**{**BASE_PARAMS, **base, **PINNED, "random_state": int(sd), "bagging_seed": int(sd),
                                               "feature_fraction_seed": int(sd), "data_random_seed": int(sd)}) for sd in params["_ens_seeds"]])
    return lgb.LGBMRegressor(**{**BASE_PARAMS, **params})


STRUCT_SPEC = "pivot=5;sl_only"      # the LIVE ml_entry exit (config/strategies.yaml ml_entry.structure_exit), RQ-20261106-98e3-01 primary arm


def _structure_outcomes(df: pd.DataFrame, cand: np.ndarray, entry: np.ndarray, atr: np.ndarray, spec: str):
    """LONG first-passage under the LIVE SL-only structure exit for each decision bar: the stop path comes from
    src/runtime/structure_exit_live.replay (via ml_entry_tp_revision.structure_sl_path), the walk is ml_entry_tp_revision.walk
    with the TP fixed at the entry bracket (3 ATR, no revision) -- the same functions the structure arm of RQ-20261103-5e04-01 used."""
    import ml_entry_tp_revision as R
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    px, jj, rs = np.empty(len(cand)), np.empty(len(cand), int), np.empty(len(cand), int)
    for r, i in enumerate(cand):
        path = R.structure_sl_path(h, lo, c, int(i), float(entry[r]), float(atr[r]), 1, spec)
        sl = slice(i + 1, i + 1 + H)
        px[r], jj[r], rs[r], _ = R.walk(o[sl], h[sl], lo[sl], c[sl], float(entry[r]), float(atr[r]), 1, None, sl_path=path)
    return px, jj, rs


def symbol_rows(sym: str, df: pd.DataFrame, slip_bps: float, fee_bps: float, struct: str = "") -> pd.DataFrame:
    """Decision rows for one ETF on its own RTH bar sequence: harness features + the LONG first-passage net R (as equity_rows)."""
    f = E.features_symbol(df[["ts", "open", "high", "low", "close", "volume"]])
    f["hour"] = df.close_ts.dt.hour.to_numpy()
    f["dow"] = df.close_ts.dt.day_of_week.to_numpy()
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy()
    n = len(df)
    decision = (df.close_ts.dt.hour % 4 == 0).to_numpy()
    cand = np.where(decision & ~np.isnan(atr))[0]
    cand = cand[cand + H < n]
    if len(cand) == 0:
        return pd.DataFrame()
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    entry = o[win][:, 0]
    a = atr[cand]
    risk = 2.0 * a
    px, j, reason = E.bracket_outcome(o[win], h[win], lo[win], c[win], entry, a, 1)
    if struct:
        px, j, reason = _structure_outcomes(df, cand, entry, a, struct)
    gross = (px - entry) / risk
    per_r = ((np.abs(entry) + np.abs(px)) / 2.0) / risk
    cost = (fee_bps + slip_bps + S.REGULATORY_BPS) / 1e4 * per_r
    rows = pd.DataFrame({"i": cand, "ts": df.close_ts.to_numpy()[cand], "symbol": sym, "net_long": gross - cost,
                         "gross_long": gross, "cost_long": cost, "reason_long": reason, "bars_long": j})
    f["ret168_raw"] = np.log(df["close"].astype(float)) - np.log(df["close"].astype(float).shift(168))
    rows = rows.join(f.drop(columns=["ts"]), on="i")
    rows["ts"] = pd.to_datetime(rows["ts"], utc=True)
    return rows


def proxy_frame(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per close_ts with the equity-proxy context features (indexed by the proxy's own close time)."""
    out = {}
    for name, col in (("SPY", "spy"), ("QQQ", "qqq"), ("IWM", "iwm"), ("TLT", "tlt"), ("VIXY", "vixy")):
        df = bars.get(name)
        if df is None or len(df) == 0:
            continue
        f = E.features_symbol(df[["ts", "open", "high", "low", "close", "volume"]])
        f.index = pd.to_datetime(df.close_ts, utc=True).to_numpy()
        f["ret168_raw"] = (np.log(df["close"].astype(float)) - np.log(df["close"].astype(float).shift(168))).to_numpy()
        out[col] = f
    ctx = pd.DataFrame(index=sorted(set().union(*[set(v.index) for v in out.values()])))
    for col, f in out.items():
        ctx[f"{col}_ret24"] = f["ret24_raw"]
        if col == "spy":
            ctx["spy_ret168"], ctx["spy_vol24"] = f["ret168_raw"], f["vol24"]
        if col == "vixy":
            ctx["vixy_vol24"] = f["vol24"]
    return ctx


def build_table(bars: dict[str, pd.DataFrame], pool: list[str], slip: float, fee: float, struct: str = "") -> pd.DataFrame:
    frames = [symbol_rows(s, bars[s], slip, fee, struct) for s in pool if s in bars and len(bars[s]) > 400]
    frames = [f for f in frames if len(f)]
    t = pd.concat(frames, ignore_index=True)
    g = t.groupby("ts")
    t["xs_rank_ret24"] = g["ret24_raw"].rank(pct=True)
    t["xs_rank_ret168"] = g["ret168_raw"].rank(pct=True)
    t["xs_rank_vol24"] = g["vol24"].rank(pct=True)
    t["xs_rank_volz"] = g["vol_z"].rank(pct=True)
    t["breadth_up24"] = g["ret24_raw"].transform(lambda x: float((x > 0).mean()))
    t["rel_vol"] = t["vol24"] / g["vol24"].transform("median")
    ctx = proxy_frame(bars)
    t = t.join(ctx, on="ts")
    t["rel_ret_spy"] = t["ret24_raw"] - t["spy_ret24"]
    return t.replace([np.inf, -np.inf], np.nan)


def session_mask(ts: pd.Series) -> np.ndarray:
    return S.session_ok(ts)


def taken_trades(rows: pd.DataFrame, pred: np.ndarray, tau: float) -> pd.DataFrame:
    return S.take(rows, pred, np.zeros(len(rows)), tau, long_only=True, side_rule="restricted")


def _stats(tk: pd.DataFrame) -> dict:
    if tk.empty:
        return {"n": 0, "mean_net_r": None}
    return {"n": int(len(tk)), "mean_net_r": float(tk.net_r.mean()), "mean_gross_r": float(tk.gross_r.mean()),
            "mean_cost_r": float(tk.cost_r.mean()), "n_symbols": int(tk.symbol.nunique()),
            "se": float(tk.net_r.std(ddof=1) / np.sqrt(len(tk))) if len(tk) > 1 else None}


def purge(train: pd.DataFrame, cut: pd.Timestamp) -> pd.DataFrame:
    return train[train.ts < cut - pd.Timedelta(days=PURGE_DAYS)]


def dev_stage(tab: pd.DataFrame, folds: list[str] = DEV_FOLDS, train_end: str = TRAIN_END, taus=TAUS,
              configs: dict = CONFIGS, min_oof_n: int = MIN_OOF_N, log=print) -> dict:
    """Walk-forward on dates <= train_end ONLY. Returns every (config, tau) out-of-fold result and the registered selection."""
    te = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(days=1)
    dev = tab[tab.ts < te].dropna(subset=["net_long"])
    bounds = [pd.Timestamp(x, tz="UTC") for x in folds] + [te]
    res = {}
    for name, cfg in configs.items():
        feats = cfg["features"]
        oof = []
        for k in range(len(folds)):
            tr = purge(dev[dev.ts < bounds[k]], bounds[k]).dropna(subset=feats)
            ts_ = dev[(dev.ts >= bounds[k]) & (dev.ts < bounds[k + 1])].dropna(subset=feats)
            if len(tr) < 1000 or len(ts_) == 0:
                continue
            m = _lgb(cfg["params"]).fit(tr[feats], tr["net_long"])
            # provenance: predict -- LGBMRegressor.predict is the regressed net R of the LONG side, not a probability
            oof.append(ts_.assign(pred=m.predict(ts_[feats]), fold=k))
            log(f"[dev] config {name} fold {k} train={len(tr)} test={len(ts_)} t={time.strftime('%H:%M:%S')}")
        if not oof:
            continue
        o = pd.concat(oof)
        o = o[session_mask(o.ts)]
        for tau in taus:
            tk = taken_trades(o, o["pred"].to_numpy(), tau)
            st = _stats(tk)
            st["by_fold"] = ({int(k): {"n": int(len(g)), "mean_net_r": round(float(g.net_r.mean()), 4)}
                              for k, g in tk.assign(fold=_fold_of(tk.ts, bounds)).groupby("fold")} if len(tk) else {})
            res[f"{name}|{tau}"] = {"config": name, "tau": tau, **st}
    ok = {k: v for k, v in res.items() if v["n"] >= min_oof_n and v["mean_net_r"] is not None}
    best = max(ok.items(), key=lambda kv: kv[1]["mean_net_r"]) if ok else None
    return {"grid": res, "n_selection_draws": len(res), "selection_rule": REGISTERED_SELECTION,
            "selected": None if best is None else {"key": best[0], **best[1]}, "dev_rows": int(len(dev))}


def _fold_of(ts: pd.Series, bounds) -> np.ndarray:
    """Fold index per trade timestamp. Compares tz-aware timestamps directly: the dev run 42119511272 compared int64 .value (ns) against
    the Series' own unit (us in pandas 3), put every trade in fold 0 and so published a by_fold table with one fold."""
    return pd.DatetimeIndex(bounds[1:-1]).searchsorted(pd.to_datetime(ts, utc=True), side="right")


def confirm_stage(tab: pd.DataFrame, config: str, tau: float, dev_oof_mean: float, unit: str, ledger_dir: Path,
                  train_end: str = TRAIN_END, start: str = CONFIRM_START, end: str = "2026-10-31", symbols=None,
                  configs: dict = CONFIGS, claim: bool = True, model_tag: str = "", min_mean: float = 0.0,
                  min_n: int = 0, lb_z: float = 0.0) -> dict:
    """Refit on rows <= train_end, score [start, end] ONCE, grade against the deflated bar. The read is recorded in the ledger."""
    HL.check_window_disjoint(train_end, start)
    if pd.Timestamp(start) < pd.Timestamp(train_end) + pd.Timedelta(days=EMBARGO_DAYS):
        raise RuntimeError(f"confirm start {start} is inside the {EMBARGO_DAYS}-day embargo after train_end {train_end}")
    cfg = configs[config]
    feats = cfg["features"]
    te = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(days=1)
    tr = purge(tab[tab.ts < te], te).dropna(subset=feats + ["net_long"])
    m = _lgb(cfg["params"]).fit(tr[feats], tr["net_long"])
    booster_sha = hashlib.sha256((("".join(x.booster_.model_to_string() for x in m.models)) if isinstance(m, _Ensemble)
                                  else m.booster_.model_to_string()).encode()).hexdigest()
    hs, he = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / "holdout_reads.jsonl"
    if HL.LEDGER.exists() and not ledger.exists():
        shutil.copy(HL.LEDGER, ledger)
    model_id = f"{FAMILY}-v1-{config}-tau{tau}{model_tag}"
    if claim:
        rec = HL.claim_read(model_id, start, end, unit, "lane ML-ENTRY-EQUITY-NATIVE (research-script-run)", ledger=ledger,
                            symbols=symbols, train_end=train_end, family=FAMILY)
        bar = rec["bar"]
    else:
        bar, rec = HL.bar_for(1), None
    test = tab[(tab.ts >= hs) & (tab.ts < he)].dropna(subset=feats + ["net_long"])
    n_before = int(len(test))
    test = test[session_mask(test.ts)]
    # provenance: predict -- the regressed LONG net R, not a probability
    pred = m.predict(test[feats])
    tk = taken_trades(test, pred, tau)
    st = _stats(tk)
    n, mean, se = st["n"], st["mean_net_r"], st.get("se")
    if n < max(S.N_FLOOR, int(min_n)):
        v, why = "indeterminate", f"confirm n={n} < {max(S.N_FLOOR, int(min_n))}"
    else:
        pass_conf = HL.point_ok(mean, se, bar)
        pass_dev = dev_oof_mean is not None and dev_oof_mean > 0
        pass_margin = mean is not None and mean >= min_mean      # an extra registered floor (default 0 = the plain rule): e.g. the seed-noise margin
        pass_lb = (not lb_z) or (mean is not None and se is not None and mean - lb_z * se > 0)   # one-sided lower bound above 0 (forward unit)
        v = "pass" if (pass_conf and pass_dev and pass_margin and pass_lb) else "fail"
        why = (f"confirm mean net R {mean:+.4f} (se {se:.4f}, deflated point bar t_min {bar['point_t_min']}, N={bar['n_tries']}) "
               f"at n={n}; dev OOF mean {dev_oof_mean:+.4f}" + (f"; registered margin floor {min_mean:+.3f} {'met' if pass_margin else 'NOT met'}" if min_mean else "")
               + (f"; lower bound mean-{lb_z:g}*se {'> 0' if pass_lb else '<= 0'}" if lb_z else ""))
    mo = tk.assign(m=pd.to_datetime(tk.ts, utc=True).dt.strftime("%Y-%m")).groupby("m").net_r.agg(["count", "mean"]) if n else None
    clustered_se = None
    if mo is not None and len(mo) > 1:
        clustered_se = float(tk.assign(m=pd.to_datetime(tk.ts, utc=True).dt.strftime("%Y-%m")).groupby("m").net_r.sum().std(ddof=1) / n * np.sqrt(len(mo)))
    return {"verdict": v, "note": why, "stats": st, "bar": bar, "ledger_record": rec, "booster_sha256": booster_sha,
            "train_rows": int(len(tr)), "config": config, "tau": tau, "dev_oof_mean": dev_oof_mean,
            "decision_rows_before_session_gate": n_before, "decision_rows": int(len(test)),
            "by_month": {} if mo is None else {k: {"n": int(r["count"]), "mean_net_r": round(float(r["mean"]), 4)} for k, r in mo.iterrows()},
            "month_clustered_se_reported": clustered_se,
            "by_symbol_top": {} if n == 0 else tk.groupby("symbol").net_r.agg(["count", "mean"]).sort_values("count", ascending=False)
            .head(10).round(4).to_dict("index"),
            "window": {"train_end": train_end, "start": start, "end": end, "embargo_days": EMBARGO_DAYS}}


PINNED = {"deterministic": True, "force_row_wise": True, "n_jobs": 1, "bagging_seed": 20261105, "feature_fraction_seed": 20261105,
          "data_random_seed": 20261105}   # LightGBM thread/hardware nondeterminism pin (lane ML-FS-RECIPE heads-up 2026-11-06)


def export_ensemble(tab: pd.DataFrame, config: str, tau: float, pool: list[str], expect_sha: str, out: Path, seeds, train_end: str = TRAIN_END,
                    configs: dict = CONFIGS, n_fixture: int = 60, struct: str = "") -> dict:
    """ENSEMBLE EXPORT (lane ML-ENTRY-EQ-STRUCT-LIVE, 2026-11-08): refit the graded mean-of-pinned-seeds model EXACTLY as ``confirm_stage`` did (same
    ``_lgb`` ensemble, same rows) and write the N booster texts. sha256 = sha of the concatenated texts (the confirm stage's rule); ``sha_match`` says
    whether it reproduces ``expect_sha``. The caller must NOT ship a model whose sha does not match. Writes model.json + parity_fixture.json (mean preds)."""
    cfg = configs[config]
    feats = cfg["features"]
    seeds = [int(x) for x in seeds]
    te = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(days=1)
    tr = purge(tab[tab.ts < te], te).dropna(subset=feats + ["net_long"])
    m = _lgb({**cfg["params"], "_ens_seeds": seeds}).fit(tr[feats], tr["net_long"])
    texts = [x.booster_.model_to_string() for x in m.models]
    sha = hashlib.sha256("".join(texts).encode()).hexdigest()
    match = bool(expect_sha) and sha.startswith(expect_sha)
    model_id = f"ENTRY-EQ-v3-{config}-tau{tau}-STRUCT-{struct.replace(';', '-').replace('=', '')}-ENS{len(seeds)}"
    art = {"model_id": model_id, "schema": "ml_entry_eq_model/2", "features": feats, "structure_exit": struct or None, "tau": float(tau), "side": "long",
           "train_end_exclusive": str(te), "train_rows": int(len(tr)), "booster_sha256": sha, "shipped": "ENSEMBLE_PINNED_SEEDS", "ensemble_seeds": seeds,
           "n_boosters": len(texts), "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_bars": H, "decision_every_h": 4, "bar": "alpaca 1Hour RTH, hour-aligned"},
           "costs": {"fee_bps": 0.0, "slippage_bps": 5.0, "regulatory_bps": S.REGULATORY_BPS, "slippage_status": "PROVISIONAL"},
           "pool_rule_sha256": S.POOL_RULE_SHA256, "pool_symbols": list(pool), "proxies": PROXIES,
           "lgb_params": {**BASE_PARAMS, **cfg["params"], **PINNED}, "confirm_booster_sha256_expected": expect_sha, "sha_match_confirm": match,
           "evidence": ["RQ-20261107-98e3-06 (structure ensemble dev + confirming read, run 42432561069: n 207, net +0.4922 R, PASS)"],
           "booster_txt": {"long": texts}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps(art))
    tail = tr.sort_values("ts").tail(20000).sample(n_fixture, random_state=7)
    fx = {"model_id": model_id, "shipped": art["shipped"], "features": feats,
          "rows": [{"symbol": r.symbol, "ts": str(r.ts), **{f: float(getattr(r, f)) for f in feats}, "pred": float(p)}  # provenance: predict -- mean regressed net R
                   for r, p in zip(tail.itertuples(index=False), m.predict(tail[feats]))]}
    (out / "parity_fixture.json").write_text(json.dumps(fx))
    return {"model_id": model_id, "booster_sha256": sha, "expect_sha": expect_sha, "sha_match": match, "shipped": art["shipped"], "train_rows": int(len(tr)),
            "n_features": len(feats), "n_boosters": len(texts), "model_json_bytes": (out / "model.json").stat().st_size, "n_fixture_rows": n_fixture}


def export_stage(tab: pd.DataFrame, config: str, tau: float, pool: list[str], expect_sha: str, out: Path, train_end: str = TRAIN_END,
                 configs: dict = CONFIGS, n_fixture: int = 60, struct: str = "") -> dict:
    """EXPORT (row ML-ENTRY-EQUITY-NATIVE, manager 2026-11-06): refit the confirmed config and write a servable model.json. Reads NO date after
    train_end. Two fits on the SAME rows: A = exactly the confirm stage's params (n_jobs 4, no determinism pins) -> its booster sha256 is compared
    with ``expect_sha``; B = the same params PINNED deterministic (single thread, row-wise, all seeds fixed). LightGBM can differ run to run on
    identical data (lane ML-FS-RECIPE measured it), so sha_match for A may be false for that reason alone. SHIPPED = A when its sha matches (it IS the
    graded model), else B (reproducible from here on), and either way the record carries sha_match, the A-vs-B prediction delta on training-tail rows
    (max/mean abs, rank correlation, decision agreement at tau) and the params. Also writes parity_fixture.json for the serve-side parity test."""
    cfg = configs[config]
    feats = cfg["features"]
    te = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(days=1)
    tr = purge(tab[tab.ts < te], te).dropna(subset=feats + ["net_long"])
    ma = _lgb(cfg["params"]).fit(tr[feats], tr["net_long"])
    mb = _lgb({**cfg["params"], **PINNED}).fit(tr[feats], tr["net_long"])
    text_a, text_b = ma.booster_.model_to_string(), mb.booster_.model_to_string()
    sha_a, sha_b = hashlib.sha256(text_a.encode()).hexdigest(), hashlib.sha256(text_b.encode()).hexdigest()
    match = bool(expect_sha) and sha_a.startswith(expect_sha)
    shipped, model, text, sha, params = ("A_confirm_params", ma, text_a, sha_a, {**BASE_PARAMS, **cfg["params"]}) if match else \
        ("B_pinned_deterministic", mb, text_b, sha_b, {**BASE_PARAMS, **cfg["params"], **PINNED})
    samp = tr.sort_values("ts").tail(20000)
    pa, pb = ma.predict(samp[feats]), mb.predict(samp[feats])  # provenance: predict -- LGBMRegressor.predict is the regressed LONG net R, not a probability
    delta = {"n_rows": int(len(samp)), "max_abs": float(np.max(np.abs(pa - pb))), "mean_abs": float(np.mean(np.abs(pa - pb))),
             "spearman": float(pd.Series(pa).corr(pd.Series(pb), method="spearman")),
             "decision_agreement_at_tau": float(np.mean((pa > tau) == (pb > tau))), "taken_a": int((pa > tau).sum()), "taken_b": int((pb > tau).sum()),
             "sha_a_equals_sha_b": sha_a == sha_b}
    model_id = f"ENTRY-EQ-v1-{config}-tau{tau}" + ("-STRUCT-" + struct.replace(";", "-").replace("=", "") if struct else "")
    art = {"model_id": model_id, "schema": "ml_entry_eq_model/1", "features": feats, "structure_exit": struct or None, "tau": float(tau), "side": "long",
           "train_end_exclusive": str(te), "train_rows": int(len(tr)), "booster_sha256": sha, "shipped": shipped,
           "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_bars": H, "decision_every_h": 4, "bar": "alpaca 1Hour RTH, hour-aligned"},
           "costs": {"fee_bps": 0.0, "slippage_bps": 5.0, "regulatory_bps": S.REGULATORY_BPS, "slippage_status": "PROVISIONAL"},
           "pool_rule_sha256": S.POOL_RULE_SHA256, "pool_symbols": list(pool), "proxies": PROXIES, "lgb_params": params,
           "confirm_booster_sha256_expected": expect_sha, "sha_match_confirm": match, "a_vs_b_delta": delta,
           "evidence": (["RQ-20261106-98e3-01 (structure-label dev + confirming read)"] if struct else
                        ["RQ-20261105-e9a1-01 (dev walk-forward, run 42119511272)", "RQ-20261105-e9a1-02 (confirming read, run 42143223941: n 858, net +0.0392 R)"]),
           "booster_txt": {"long": text}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps(art))
    tail = tr.sort_values("ts").tail(20000).sample(n_fixture, random_state=7)
    fx = {"model_id": model_id, "shipped": shipped, "features": feats,
          "rows": [{"symbol": r.symbol, "ts": str(r.ts), **{f: float(getattr(r, f)) for f in feats}, "pred": float(p)}
                   for r, p in zip(tail.itertuples(index=False), model.predict(tail[feats]))]}
    (out / "parity_fixture.json").write_text(json.dumps(fx))
    return {"model_id": model_id, "booster_sha256": sha, "booster_sha256_a": sha_a, "booster_sha256_b": sha_b, "shipped": shipped,
            "expect_sha": expect_sha, "sha_match": match, "a_vs_b_delta": delta, "train_rows": int(len(tr)), "n_features": len(feats),
            "model_json_bytes": (out / "model.json").stat().st_size, "n_fixture_rows": n_fixture, "pinned_params": PINNED}


# ------------------------------------------------------------------------------------------------ runner glue
def _pool_and_bars(a, end_day: str):
    """The registered pool (POOL_RULE) + 1h RTH bars for pool and proxies. Read-only allowlisted Alpaca client."""
    import requests
    from alpaca_readonly import AlpacaReadOnly
    client = AlpacaReadOnly.from_env()
    nq = requests.get(S.NASDAQTRADED_URL, timeout=60, headers={"User-Agent": "jta-trader-research"}).text
    etfs = S.etf_symbols(nq)
    assets = client.assets()
    cand = sorted({x["symbol"] for x in assets if x.get("status") == "active" and x.get("tradable")
                   and x.get("class", "us_equity") == "us_equity"} & etfs)
    dev = {}
    for i in range(0, len(cand), 100):
        got = client.bars(cand[i:i + 100], "1Day", f"{S.DEV_START}T00:00:00Z", "2021-01-01T00:00:00Z")
        dev.update({s: S.alpaca_bars_df(bl) for s, bl in got.items() if bl})
    pool, prep = S.filter_pool(assets, etfs, dev)
    prep.update({"etf_file_sha256": hashlib.sha256(nq.encode()).hexdigest(), "pool_rule_sha256": S.POOL_RULE_SHA256,
                 "key_kind": client.key_kind})
    if prep["pool_rule_sha256"] != "e9702661d1a596a0f7e84e632c0ca8b5c2743a728f02147477c003644a0858e2":
        raise RuntimeError("POOL_RULE changed: the registered population is not what this module scores")
    print(f"[pool] {len(pool)} ETFs; {client.calls} calls", flush=True)
    want = sorted(set(pool) | set(PROXIES))
    end = (pd.Timestamp(end_day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    bars = S.fetch_alpaca_1h(client, want, Path(a.cache), end, start=DATA_START)
    missing = [p for p in PROXIES if p not in bars]
    if missing:
        raise RuntimeError(f"proxy bars missing: {missing} (the model needs its market-context features)")
    return pool, prep, bars, client


def structure_stage(tab: pd.DataFrame, unit: str, ledger_dir: Path, end: str, symbols, spec: str = STRUCT_SPEC,
                    configs: dict = None, train_end: str = TRAIN_END, start: str = CONFIRM_START, folds: list = None,
                    taus=TAUS, min_oof_n: int = MIN_OOF_N, claim: bool = True, log=print, ens_seeds=None, min_mean: float = 0.0) -> dict:
    """RQ-20261106-98e3-01: the equity ENTRY model RE-TRAINED on structure-exit labels (config B fixed), tau re-selected on the
    dev walk-forward by the registered rule (4 draws), then ONE confirming read of the same window as the fixed-bracket confirm
    (ledger N counts it: N=2). ``tab`` must already carry the structure-exit net_long/gross_long/cost_long."""
    configs = configs or {"B": CONFIGS["B"]}
    if ens_seeds:   # ONE served model = the mean of pinned fits at these seeds (RQ-20261107-98e3-06); config name stays "B"
        configs = {k: {"features": v["features"], "params": {**v["params"], "_ens_seeds": [int(x) for x in ens_seeds]}} for k, v in configs.items()}
    d = dev_stage(tab, folds=folds or DEV_FOLDS, train_end=train_end, taus=taus, configs=configs, min_oof_n=min_oof_n, log=log)
    sel = d["selected"]
    if sel is None:
        return {"verdict": "indeterminate", "note": "dev stage selected nothing (no tau with >= %d OOF trades)" % min_oof_n, "dev": d}
    c = confirm_stage(tab, sel["config"], float(sel["tau"]), float(sel["mean_net_r"]), unit, ledger_dir, train_end=train_end,
                      start=start, end=end, symbols=symbols, configs=configs, claim=claim, model_tag="-STRUCT-" + spec.replace(";", "-").replace("=", "") + (f"-ENS{len(ens_seeds)}" if ens_seeds else ""), min_mean=min_mean)
    c["dev"] = d
    c["structure_exit"] = spec
    return c


FWD_START = "2026-11-01"     # the first bar AFTER the 2025-07-15..2026-10-31 window every earlier ENTRY-EQ read used


def forward_stage(tab: pd.DataFrame, unit: str, ledger_dir: Path, end: str, symbols, tau: float, dev_oof_mean: float, ens_seeds,
                  spec: str = STRUCT_SPEC, configs: dict = None, train_end: str = TRAIN_END, start: str = FWD_START, min_mean: float = 0.0,
                  min_n: int = 0, lb_z: float = 0.0, claim: bool = True) -> dict:
    """RQ-20261108-98e3-13: the FROZEN structure ensemble (config B, mean of pinned fits at ``ens_seeds`` refit on rows <= train_end -- deterministic, so
    the graded model reproduces) scored ONCE at the fixed ``tau`` on bars AFTER every earlier read's window. No dev selection, no re-tuning."""
    configs = configs or {"B": CONFIGS["B"]}
    configs = {k: {"features": v["features"], "params": {**v["params"], "_ens_seeds": [int(x) for x in ens_seeds]}} for k, v in configs.items()}
    c = confirm_stage(tab, "B", float(tau), float(dev_oof_mean), unit, ledger_dir, train_end=train_end, start=start, end=end, symbols=symbols,
                      configs=configs, claim=claim, model_tag="-STRUCT-" + spec.replace(";", "-").replace("=", "") + f"-ENS{len(ens_seeds)}-FWD",
                      min_mean=min_mean, min_n=min_n, lb_z=lb_z)
    c["structure_exit"] = spec
    return c


H2H_FAMILY = "ENTRY-EQ-H2H"
H2H_V1 = "ml/candidates/ml_entry_eq_v1/model.json"                  # ENTRY-EQ-v1, tau 0.20, fixed bracket (ml_entry_eq, alpaca_paper)
H2H_STRUCT = "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json"  # ens5, tau 0.25, pivot=5;sl_only (ml_entry_eq_struct, alpaca_live + alpaca_portfolio)


def _artifact_scorer(path):
    """Frozen artifact -> (features, tau, predict_fn). The boosters are the shipped texts: nothing is refit."""
    import lightgbm as lgb
    art = json.loads((REPO / path).read_text()) if not Path(path).is_absolute() else json.loads(Path(path).read_text())
    bt = art["booster_txt"]["long"]
    boosters = [lgb.Booster(model_str=t) for t in (bt if isinstance(bt, list) else [bt])]
    feats = art["features"]

    def predict(df):
        return np.mean([b.predict(df[feats]) for b in boosters], axis=0)   # provenance: predict -- mean regressed LONG net R (a regressor, not a probability)
    return feats, float(art["tau"]), predict, art["model_id"]


def _cluster_t(day_sum: pd.Series):
    k = len(day_sum)
    if k < 3 or day_sum.std(ddof=1) == 0:
        return None
    return float(day_sum.mean() / (day_sum.std(ddof=1) / np.sqrt(k)))


def h2h_stage(tab_fixed: pd.DataFrame, tab_struct: pd.DataFrame, v1: tuple, st: tuple, unit: str, ledger_dir: Path, start: str, end: str,
              symbols=None, train_end: str = TRAIN_END, claim: bool = True, min_n_union: int = 100, t_min: float = 1.3) -> dict:
    """HEAD-TO-HEAD of two FROZEN equity ENTRY artifacts on the SAME decision bars (symbol, ts) of one window. Each model trades under its OWN live
    exit (v1: fixed SL2/TP3 ATR bracket; struct: pivot=5;sl_only), net of the same cost stack. Nothing is refit and nothing is tuned here.
    Per decision bar in the UNION of the two models' trades: c_m = net R of model m's trade there (0 if m does not trade the bar);
    d = c_struct - c_v1. The statistic is mean(d) with a calendar-DAY-clustered t. Reported, never gating: v1-only / struct-only / both-fire means
    (the consensus arm), and the same-exit control (both models' trades scored under the struct exit)."""
    HL.check_window_disjoint(train_end, start)
    if pd.Timestamp(start) < pd.Timestamp(train_end) + pd.Timedelta(days=EMBARGO_DAYS):
        raise RuntimeError(f"h2h start {start} is inside the {EMBARGO_DAYS}-day embargo after train_end {train_end}")
    hs, he = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    rec = None
    if claim:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger = ledger_dir / "holdout_reads.jsonl"
        if HL.LEDGER.exists() and not ledger.exists():
            shutil.copy(HL.LEDGER, ledger)
        rec = HL.claim_read(f"{H2H_FAMILY}-{v1[3]}-vs-{st[3]}", start, end, unit, "lane ML-PROGRAMME-CONSOLIDATION (research-script-run)", ledger=ledger,
                            symbols=symbols, train_end=train_end, family=H2H_FAMILY)

    def trades(tab, scorer):
        feats, tau, predict, _ = scorer
        w = tab[(tab.ts >= hs) & (tab.ts < he)].dropna(subset=feats + ["net_long"])
        w = w[session_mask(w.ts)]
        return w, taken_trades(w, predict(w[feats]), tau)

    wf, tk1 = trades(tab_fixed, v1)
    ws, tk2 = trades(tab_struct, st)
    k = ["symbol", "ts"]
    a = tk1[k + ["net_r"]].rename(columns={"net_r": "c_v1"}) if len(tk1) else pd.DataFrame(columns=k + ["c_v1"])
    b = tk2[k + ["net_r"]].rename(columns={"net_r": "c_st"}) if len(tk2) else pd.DataFrame(columns=k + ["c_st"])
    u = a.merge(b, on=k, how="outer")
    u["fire_v1"], u["fire_st"] = u.c_v1.notna(), u.c_st.notna()
    u[["c_v1", "c_st"]] = u[["c_v1", "c_st"]].fillna(0.0)
    u["d"] = u.c_st - u.c_v1
    # same-exit control: BOTH models' trades valued with the struct-exit outcome of that bar
    nl = tab_struct.set_index(k)["net_long"]
    u["same_v1"] = [float(nl.get((r.symbol, r.ts), np.nan)) if r.fire_v1 else 0.0 for r in u.itertuples()]
    u["same_st"] = [float(nl.get((r.symbol, r.ts), np.nan)) if r.fire_st else 0.0 for r in u.itertuples()]
    u["day"] = pd.to_datetime(u.ts, utc=True).dt.strftime("%Y-%m-%d")
    n_union = int(len(u))

    def arm(mask, col):
        x = u.loc[mask, col]
        return {"n": int(len(x)), "mean_net_r": None if len(x) == 0 else round(float(x.mean()), 4)}
    mean_d = float(u.d.mean()) if n_union else None
    t = _cluster_t(u.groupby("day").d.sum()) if n_union else None
    same_d = float((u.same_st - u.same_v1).mean()) if n_union else None
    st_stats = _stats(tk2)
    if n_union < min_n_union:
        v, why = "indeterminate", f"union decision bars n={n_union} < {min_n_union}"
    else:
        ok = mean_d > 0 and t is not None and t >= t_min and st_stats["mean_net_r"] is not None and st_stats["mean_net_r"] > 0
        v = "pass" if ok else "fail"
        why = (f"mean d (struct - v1, per union bar) {mean_d:+.4f} R, day-clustered t {None if t is None else round(t, 2)} (bar {t_min}), "
               f"struct own mean net R {st_stats['mean_net_r']}, n_union {n_union}")
    return {"verdict": v, "note": why, "n_union": n_union, "mean_d": mean_d, "day_clustered_t": t, "same_exit_mean_d": same_d,
            "v1": {"model_id": v1[3], "tau": v1[1], "stats": _stats(tk1)}, "struct": {"model_id": st[3], "tau": st[1], "stats": st_stats},
            "arms": {"v1_only": arm(u.fire_v1 & ~u.fire_st, "c_v1"), "struct_only": arm(~u.fire_v1 & u.fire_st, "c_st"),
                     "both_fire_v1_exit": arm(u.fire_v1 & u.fire_st, "c_v1"), "both_fire_struct_exit": arm(u.fire_v1 & u.fire_st, "c_st")},
            "window": {"train_end": train_end, "start": start, "end": end, "embargo_days": EMBARGO_DAYS},
            "decision_rows": {"fixed": int(len(wf)), "struct": int(len(ws))}, "ledger_record": rec}


def dev_row(d: dict, unit: str, where: str) -> dict:
    """The dev record in the runner's verdict.json contract (script_run.VERDICTS / READ_STATES): a descriptive stage carries
    verdict 'indeterminate' (run 42119511272 wrote 'descriptive' -> malformed; run 42166322024 wrote 'not_applicable' with read_state measured ->
    research_result.validate REFUSES that pair: not_applicable is reserved for states where nothing was measured)."""
    sel = d["selected"]
    return {"schema_version": 1, "research_unit": unit, "read_state": "measured", "verdict": "indeterminate",
            "population": (f"DEV stage: purged walk-forward OOF restricted-long decisions on the {d.get('n_pool')}-ETF Alpaca liquidity pool, "
                           f"dates <= {d.get('train_end')}, {d['n_selection_draws']} (config, tau) draws"),
            "note": ("DEV stage (walk-forward <= %s; no confirming window loaded). Selected %s: OOF mean net R %s at n=%s"
                     % (TRAIN_END, None if sel is None else sel["key"], None if sel is None else sel["mean_net_r"],
                        None if sel is None else sel["n"])),
            "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "measurement": d, "n": None if sel is None else sel["n"],
            "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py dev", "where": where}}


def main_run(a) -> int:
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    slip, _fund = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    # --full-bars (export): build the table from the SAME bars the graded confirm stage used (to the last complete month); training still takes rows < train_end only
    end_day = TRAIN_END if (a.cmd == "dev" or (a.cmd == "export" and not getattr(a, "full_bars", False))) else (pd.Timestamp.now(tz="UTC").normalize().replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    pool, prep, bars, client = _pool_and_bars(a, end_day)
    spec_used = getattr(a, "struct_spec", "") or STRUCT_SPEC   # dev-only override (pivot 3 / pivot 8 variants); default = the live exit
    tab = build_table(bars, pool, slip, fee, struct=spec_used if (a.cmd in ("structure", "forward") or getattr(a, "structure", False)) else "")
    print(f"[table] {len(tab)} decision rows, {tab.symbol.nunique()} symbols t={time.strftime('%H:%M:%S')}", flush=True)
    if a.cmd == "dev":
        cfgs = {k: CONFIGS[k] for k in a.configs.split(",")} if getattr(a, "configs", "") else CONFIGS
        if getattr(a, "seeds", ""):   # seed-variance read: each config refit under PINNED determinism and every seed in the list
            cfgs = {f"{k}_s{sd}": {"features": v["features"], "params": {**v["params"], **PINNED, "random_state": int(sd), "bagging_seed": int(sd),
                                                                          "feature_fraction_seed": int(sd), "data_random_seed": int(sd)}}
                    for k, v in cfgs.items() for sd in a.seeds.split(",")}
        if getattr(a, "ensemble_seeds", ""):   # one 5-seed-average model per config (variance-reduction read), alongside nothing else
            cfgs = {f"{k}_ens": {"features": v["features"], "params": {**v["params"], "_ens_seeds": [int(x) for x in a.ensemble_seeds.split(",")]}}
                    for k, v in cfgs.items()}
        d = dev_stage(tab, taus=[float(x) for x in a.taus.split(",")] if getattr(a, "taus", "") else TAUS, configs=cfgs)
        d.update({"structure_exit": spec_used if getattr(a, "structure", False) else None, "train_end": TRAIN_END, "pool": {k: v for k, v in prep.items() if k != "excluded"}, "n_pool": len(pool),
                  "costs": {"slippage_bps": slip, "fee_bps": fee, "regulatory_bps": S.REGULATORY_BPS},
                  "configs": {k: {"features": v["features"], "params": v["params"]} for k, v in CONFIGS.items()},
                  "alpaca_calls": client.calls, "runtime_s": round(time.time() - t0, 1)})
        row = dev_row(d, a.unit, a.where)
    elif a.cmd == "structure":
        c = structure_stage(tab, a.unit, out / "ledger", end_day, pool,
                            taus=[float(x) for x in a.taus.split(",")] if a.taus else TAUS,
                            ens_seeds=a.ensemble_seeds.split(",") if a.ensemble_seeds else None, min_mean=float(a.min_mean))
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c.get("stats", {}).get("n"), "description": f"equity-native ENTRY re-trained on structure-exit labels ({STRUCT_SPEC}), restricted-LONG on the "
                              f"{len(pool)}-ETF Alpaca liquidity pool, confirming window {CONFIRM_START}..{end_day}, net of the Alpaca cost stack"},
               "measurement": {**c, "pool": {k: v for k, v in prep.items() if k != "excluded"}, "n_pool": len(pool),
                               "alpaca_calls": client.calls, "runtime_s": round(time.time() - t0, 1)},
               "n": c.get("stats", {}).get("n"), "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py structure", "where": a.where}}
    elif a.cmd == "forward":
        c = forward_stage(tab, a.unit, out / "ledger", end_day, pool, float(a.tau), float(a.dev_oof_mean), a.ensemble_seeds.split(","),
                          start=a.fwd_start, min_mean=float(a.min_mean), min_n=int(a.min_n), lb_z=float(a.lb_z))
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c.get("stats", {}).get("n"), "description": f"FORWARD read of the frozen structure ensemble (tau {a.tau}, seeds {a.ensemble_seeds}), "
                              f"restricted-LONG on the {len(pool)}-ETF Alpaca liquidity pool, bars {a.fwd_start}..{end_day} only, net of the Alpaca cost stack"},
               "measurement": {**c, "pool": {k: v for k, v in prep.items() if k != "excluded"}, "n_pool": len(pool),
                               "alpaca_calls": client.calls, "runtime_s": round(time.time() - t0, 1)},
               "n": c.get("stats", {}).get("n"), "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py forward", "where": a.where}}
    elif a.cmd == "h2h":
        tab_s = build_table(bars, pool, slip, fee, struct=STRUCT_SPEC)
        c = h2h_stage(tab, tab_s, _artifact_scorer(H2H_V1), _artifact_scorer(H2H_STRUCT), a.unit, out / "ledger", a.start, a.end or end_day, pool,
                      min_n_union=int(a.min_n_union), t_min=float(a.t_min))
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c["n_union"], "description": f"frozen ml_entry_eq (v1, tau 0.20) vs ml_entry_eq_struct (ens5, tau 0.25) on the SAME decision bars of the "
                              f"{len(pool)}-ETF Alpaca liquidity pool, window {a.start}..{a.end or end_day}, each under its own live exit, net of the Alpaca cost stack"},
               "measurement": {**c, "pool": {k: v for k, v in prep.items() if k != "excluded"}, "n_pool": len(pool), "alpaca_calls": client.calls,
                               "runtime_s": round(time.time() - t0, 1)},
               "n": c["n_union"], "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py h2h", "where": a.where}}
    elif a.cmd == "export":
        if a.ensemble_seeds:
            e = export_ensemble(tab, a.config, float(a.tau), pool, a.expect_sha, out, a.ensemble_seeds.split(","), struct=STRUCT_SPEC if a.structure else "")
            e.setdefault("a_vs_b_delta", {"n_rows": 0, "max_abs": 0.0, "spearman": 1.0, "decision_agreement_at_tau": 1.0})
        else:
            e = export_stage(tab, a.config, float(a.tau), pool, a.expect_sha, out, struct=STRUCT_SPEC if a.structure else "")
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate",
               "population": f"EXPORT of {e['model_id']}: refit on rows < {TRAIN_END} over the {len(pool)}-ETF pool; no outcome after train_end read",
               "note": (f"export {e['model_id']}: confirm-params refit sha256 {e.get('booster_sha256_a', e['booster_sha256'])[:16]} "
                        f"{'MATCHES' if e['sha_match'] else 'DOES NOT MATCH'} the confirm run's {a.expect_sha}; shipped {e['shipped']}; "
                        f"A-vs-B on {e['a_vs_b_delta']['n_rows']} training-tail rows: max|d|={e['a_vs_b_delta']['max_abs']:.4f} "
                        f"spearman={e['a_vs_b_delta']['spearman']:.5f} decision agreement={e['a_vs_b_delta']['decision_agreement_at_tau']:.4f}"),
               "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "measurement": {**e, "pool": {k: v for k, v in prep.items() if k != "excluded"}},
               "n": e["train_rows"], "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py export", "where": a.where}}
    else:
        c = confirm_stage(tab, a.config, float(a.tau), float(a.dev_oof_mean), a.unit, out / "ledger", end=end_day,
                          symbols=pool)
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c["stats"]["n"], "description": f"equity-native ENTRY ({a.config}, tau {a.tau}) restricted-LONG on the "
                              f"{len(pool)}-ETF Alpaca liquidity pool, confirming window {CONFIRM_START}..{end_day}, net of the Alpaca cost stack"},
               "measurement": {**c, "pool": {k: v for k, v in prep.items() if k != "excluded"}, "n_pool": len(pool),
                               "alpaca_calls": client.calls, "runtime_s": round(time.time() - t0, 1)},
               "n": c["stats"]["n"], "produced_by": {"tool": "python3 scripts/research/ml_entry_equity.py confirm", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{a.cmd.upper()} {row['verdict']}: {row['note']}", flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _synthetic_bars(seed: int = 0, n_days: int = 700) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2021-01-04", periods=n_days, tz="America/New_York")
    out = {}
    for s in ["SPY", "QQQ", "IWM", "TLT", "VIXY"] + [f"E{i}" for i in range(8)]:
        px = 100.0
        rows = []
        for d in days:
            for hh in range(9, 16):
                t = (d + pd.Timedelta(hours=hh)).tz_convert("UTC")
                r = rng.normal(0, 0.003)
                o, c = px, px * (1 + r)
                rows.append((t, o, max(o, c) * 1.001, min(o, c) * 0.999, c, float(rng.integers(1e5, 1e6))))
                px = c
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        et = df.ts.dt.tz_convert("America/New_York")
        df["close_ts"] = pd.concat([df.ts + pd.Timedelta(hours=1), (et.dt.normalize() + pd.Timedelta(hours=16)).dt.tz_convert("UTC")],
                                   axis=1).min(axis=1)
        out[s] = df
    return out


def self_test() -> int:
    import tempfile
    bars = _synthetic_bars()
    pool = [f"E{i}" for i in range(8)]
    tab = build_table(bars, pool, 5.0, 0.0)
    assert not any("btc" in c for c in tab.columns), "no crypto feature may exist"
    assert set(OWN + XS + MKT) <= set(tab.columns), set(OWN + XS + MKT) - set(tab.columns)
    assert tab["xs_rank_ret24"].dropna().between(0, 1).all() and tab["breadth_up24"].dropna().between(0, 1).all()
    small = {"A": {"features": OWN + XS + MKT, "params": {"n_estimators": 20, "min_child_samples": 20}},
             "B": {"features": OWN + XS, "params": {"n_estimators": 20, "min_child_samples": 20}}}
    # dates: bars cover 2021-01..2023-08; use a miniature calendar
    d = dev_stage(tab, folds=["2022-09-01", "2023-01-01"], train_end="2023-04-30", taus=[0.0, 0.05], configs=small, min_oof_n=1,
                  log=lambda *_: None)
    assert d["n_selection_draws"] == 4 and d["selected"] is not None, d
    assert max(len(r["by_fold"]) for r in d["grid"].values()) >= 2, "by_fold collapsed into one fold"
    assert tab[tab.ts <= "2023-04-30"].shape[0] < tab.shape[0], "synthetic calendar must extend past train_end"
    # the confirming window must be refused when it overlaps training or sits inside the embargo
    for bad in ("2023-04-30", "2023-05-05"):
        try:
            confirm_stage(tab, "A", 0.0, 0.01, "RQ-T", Path(tempfile.mkdtemp()), train_end="2023-04-30", start=bad, end="2023-08-31",
                          configs=small, claim=False)
        except (HL.WindowOverlapsTraining, RuntimeError):
            continue
        raise AssertionError(f"start {bad} must be refused")
    with tempfile.TemporaryDirectory() as td:
        r = confirm_stage(tab, "A", 0.0, 0.01, "RQ-T", Path(td), train_end="2023-04-30", start="2023-05-20", end="2023-08-31",
                          configs=small, symbols=pool)
        assert r["verdict"] in ("pass", "fail", "indeterminate") and r["bar"]["n_tries"] == 1 and r["ledger_record"]["family"] == FAMILY, r
        r2 = confirm_stage(tab, "A", 0.0, 0.01, "RQ-T", Path(td), train_end="2023-04-30", start="2023-05-20", end="2023-08-31",
                           configs=small, symbols=pool)
        assert r2["bar"]["n_tries"] == 2 and r2["bar"]["point_t_min"] > 0, r2["bar"]      # a re-read is graded against the deflated bar
    with tempfile.TemporaryDirectory() as td:
        ex = export_stage(tab, "A", 0.0, pool, "", Path(td), train_end="2023-04-30", configs=small, n_fixture=10)
        art = json.loads((Path(td) / "model.json").read_text())
        assert art["features"] == small["A"]["features"] and "booster_txt" in art and art["shipped"] == "B_pinned_deterministic"
        ex2 = export_stage(tab, "A", 0.0, pool, "", Path(td) / "b", train_end="2023-04-30", configs=small, n_fixture=10)
        assert ex2["booster_sha256_b"] == ex["booster_sha256_b"], "the PINNED refit must be reproducible run to run"
        assert set(ex["a_vs_b_delta"]) >= {"max_abs", "mean_abs", "spearman", "decision_agreement_at_tau"}
        ex3 = export_stage(tab, "A", 0.0, pool, ex["booster_sha256_a"][:16], Path(td) / "c", train_end="2023-04-30", configs=small, n_fixture=10)
        assert ex3["sha_match"] and ex3["shipped"] == "A_confirm_params"       # a matching confirm hash ships the graded model itself
        ee = export_ensemble(tab, "A", 0.0, pool, "", Path(td) / "e", [1, 2], train_end="2023-04-30", configs=small, n_fixture=10)
        ee2 = export_ensemble(tab, "A", 0.0, pool, ee["booster_sha256"][:16], Path(td) / "e2", [1, 2], train_end="2023-04-30", configs=small, n_fixture=10)
        assert ee["n_boosters"] == 2 and ee2["sha_match"], "the pinned seed ensemble must reproduce its own sha"
        import lightgbm as lgb
        fx = json.loads((Path(td) / "parity_fixture.json").read_text())
        bst = lgb.Booster(model_str=art["booster_txt"]["long"])
        got = bst.predict(pd.DataFrame([{f: r[f] for f in art["features"]} for r in fx["rows"]]))
        assert np.allclose(got, [r["pred"] for r in fx["rows"]]), "loaded booster must reproduce the fixture predictions"
    # no dev row may sit in the confirming window and vice versa (the dev stage only ever sees <= TRAIN_END)
    te = pd.Timestamp("2023-04-30", tz="UTC") + pd.Timedelta(days=1)
    assert (tab[tab.ts < te].ts.max() < te) and (tab[tab.ts >= pd.Timestamp("2023-05-20", tz="UTC")].ts.min() >= pd.Timestamp("2023-05-20", tz="UTC"))
    # structure-exit arm: the table builds, labels differ from the fixed bracket only through the stop path, the stage runs end to end
    ts_tab = build_table(bars, pool, 5.0, 0.0, struct=STRUCT_SPEC)
    assert len(ts_tab) == len(tab) and ts_tab["bars_long"].between(1, H).all(), "structure table shape / hold length"
    assert not np.allclose(ts_tab["net_long"].to_numpy(), tab["net_long"].to_numpy()), "the structure exit must change some outcomes"
    with tempfile.TemporaryDirectory() as td:
        sm = {"B": {"features": OWN + XS, "params": {"n_estimators": 20, "min_child_samples": 20}}}
        r = structure_stage(ts_tab, "RQ-T", Path(td), "2023-08-31", pool, configs=sm, train_end="2023-04-30", start="2023-05-20",
                            folds=["2022-09-01", "2023-01-01"], taus=[0.0, 0.05], min_oof_n=1, log=lambda *_: None)
        assert r["verdict"] in ("pass", "fail", "indeterminate") and r["structure_exit"] == STRUCT_SPEC and r["dev"]["n_selection_draws"] == 2, r
    with tempfile.TemporaryDirectory() as td:
        r = structure_stage(ts_tab, "RQ-T", Path(td), "2023-08-31", pool, configs=sm, train_end="2023-04-30", start="2023-05-20",
                            folds=["2022-09-01", "2023-01-01"], taus=[0.0, 0.05], min_oof_n=1, log=lambda *_: None, ens_seeds=["1", "2"])
        assert r["verdict"] in ("pass", "fail", "indeterminate") and len(r["booster_sha256"]) == 64 and r["ledger_record"]["model_id"].endswith("-ENS2"), r
    with tempfile.TemporaryDirectory() as td:   # forward: a frozen ensemble at a fixed tau on a window with the n floor and lower-bound clauses
        r = forward_stage(ts_tab, "RQ-T", Path(td), "2023-08-31", pool, 0.0, 0.01, ["1", "2"], configs=sm, train_end="2023-04-30", start="2023-05-20",
                          min_mean=0.0, min_n=10**6, lb_z=1.2816)
        assert r["verdict"] == "indeterminate" and "< 1000000" in r["note"], r["note"]       # n floor binds
        r2 = forward_stage(ts_tab, "RQ-T", Path(td), "2023-08-31", pool, 0.0, 0.01, ["1", "2"], configs=sm, train_end="2023-04-30", start="2023-05-20",
                           min_mean=0.0, min_n=5, lb_z=1.2816)
        assert r2["verdict"] in ("pass", "fail") and r2["ledger_record"]["model_id"].endswith("-ENS2-FWD") and "lower bound" in r2["note"], r2["note"]
    with tempfile.TemporaryDirectory() as td:   # head-to-head: two frozen artifacts, same bars, own exits
        import lightgbm as lgb
        def _fake(td_, name, tau, struct):
            tr_ = ts_tab if struct else tab
            f_ = OWN + XS
            trn = purge(tr_[tr_.ts < pd.Timestamp("2023-05-01", tz="UTC")], pd.Timestamp("2023-05-01", tz="UTC")).dropna(subset=f_ + ["net_long"])
            m_ = _lgb({"n_estimators": 20, "min_child_samples": 20}).fit(trn[f_], trn["net_long"])
            pth = Path(td_) / f"{name}.json"
            pth.write_text(json.dumps({"model_id": name, "features": f_, "tau": tau, "booster_txt": {"long": m_.booster_.model_to_string()}}))
            return _artifact_scorer(str(pth))
        s1, s2 = _fake(td, "fake-v1", 0.0, False), _fake(td, "fake-struct", 0.0, True)
        r = h2h_stage(tab, ts_tab, s1, s2, "RQ-T", Path(td), "2023-05-20", "2023-08-31", pool, train_end="2023-04-30", min_n_union=5)
        assert r["verdict"] in ("pass", "fail") and r["n_union"] >= 5 and r["ledger_record"]["family"] == H2H_FAMILY, r["note"]
        n_both = r["arms"]["both_fire_v1_exit"]["n"]
        assert r["n_union"] == r["arms"]["v1_only"]["n"] + r["arms"]["struct_only"]["n"] + n_both, "union must partition into three arms"
        assert abs(r["mean_d"] - ((r["arms"]["struct_only"]["n"] and r["arms"]["struct_only"]["mean_net_r"] * r["arms"]["struct_only"]["n"] or 0)
                                  + (n_both and r["arms"]["both_fire_struct_exit"]["mean_net_r"] * n_both or 0)
                                  - (r["arms"]["v1_only"]["n"] and r["arms"]["v1_only"]["mean_net_r"] * r["arms"]["v1_only"]["n"] or 0)
                                  - (n_both and r["arms"]["both_fire_v1_exit"]["mean_net_r"] * n_both or 0)) / r["n_union"]) < 1e-3, "mean d must equal the arm decomposition"
        r0 = h2h_stage(tab, ts_tab, s1, s2, "RQ-T", Path(td), "2023-05-20", "2023-08-31", pool, train_end="2023-04-30", min_n_union=10**6, claim=False)
        assert r0["verdict"] == "indeterminate", r0
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("dev", "confirm", "export", "structure", "forward", "h2h"):
        p = sub.add_parser(name)
        p.add_argument("--cache", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--where", default="local")
        if name in ("confirm", "export"):
            p.add_argument("--config", required=True, choices=sorted(CONFIGS))
            p.add_argument("--tau", required=True)
        if name == "export":
            p.add_argument("--expect-sha", required=True, help="booster sha256 (prefix ok) of the confirm run to reproduce")
            p.add_argument("--structure", action="store_true", help="relabel with the live structure exit (pivot=5;sl_only) before the refit")
            p.add_argument("--full-bars", dest="full_bars", action="store_true", help="build the table from full bars (to the last complete month), as the graded confirm stage did; training rows stay < train_end")
            p.add_argument("--ensemble-seeds", dest="ensemble_seeds", default="", help="export the mean of pinned fits at these seeds (N boosters; sha = concatenated texts)")
        if name == "dev":
            p.add_argument("--structure", action="store_true", help="label with the live structure exit (pivot=5;sl_only)")
            p.add_argument("--struct-spec", dest="struct_spec", default="", help="dev-only: structure-exit spec overriding pivot=5;sl_only (needs --structure), e.g. pivot=3;sl_only")
            p.add_argument("--taus", default="", help="comma list overriding the registered tau grid (dev-only iteration)")
            p.add_argument("--configs", default="", help="comma list of configs to run (default all)")
            p.add_argument("--ensemble-seeds", dest="ensemble_seeds", default="", help="comma list of seeds: ONE model per config = the mean of pinned fits at these seeds")
            p.add_argument("--seeds", default="", help="comma list of LightGBM seeds: refit every config under PINNED determinism per seed (variance read)")
        if name == "forward":
            p.add_argument("--tau", required=True)
            p.add_argument("--dev-oof-mean", required=True)
            p.add_argument("--ensemble-seeds", dest="ensemble_seeds", required=True)
            p.add_argument("--fwd-start", dest="fwd_start", default=FWD_START)
            p.add_argument("--min-mean", dest="min_mean", default="0")
            p.add_argument("--min-n", dest="min_n", default="0")
            p.add_argument("--lb-z", dest="lb_z", default="0")
            p.add_argument("--rule-id", required=True)
            p.add_argument("--registered-at", required=True)
        if name == "h2h":
            p.add_argument("--start", default=CONFIRM_START)
            p.add_argument("--end", default="", help="default: the last complete month")
            p.add_argument("--min-n-union", dest="min_n_union", default="100")
            p.add_argument("--t-min", dest="t_min", default="1.3")
            p.add_argument("--rule-id", required=True)
            p.add_argument("--registered-at", required=True)
        if name == "structure":
            p.add_argument("--taus", default="", help="comma list overriding the tau grid (registered in the unit)")
            p.add_argument("--ensemble-seeds", dest="ensemble_seeds", default="", help="serve ONE model = mean of pinned fits at these seeds")
            p.add_argument("--min-mean", dest="min_mean", default="0", help="extra registered floor on the confirm mean (seed-noise margin)")
            p.add_argument("--rule-id", required=True)
            p.add_argument("--registered-at", required=True)
        if name == "confirm":
            p.add_argument("--dev-oof-mean", required=True)
            p.add_argument("--rule-id", required=True)
            p.add_argument("--registered-at", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    return main_run(a) if a.cmd in ("dev", "confirm", "export", "structure", "forward", "h2h") else 2


if __name__ == "__main__":
    sys.exit(main())
