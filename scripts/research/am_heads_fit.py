#!/usr/bin/env python3
# wiring: research/queue/RQ-20261123-a9d1-01.yaml (AM v2 stage A: model skill of the TARGET and INVALIDATION heads on the cf_bar_labels corpus); spec docs/research/ml-am-heads-design-2026-11-23.md sections 3-6
"""AM v2 heads, STAGE A (model skill only; Tier 1 research, no served model, no order path).

Fits, per purged time fold, on the per-bar labels of ``cf_bar_labels_run`` (one row per trade per open bar):
  TARGET head        LightGBM quantile regressors (q in QUANTILES) of ``fwd_mfe_r`` (remaining favourable excursion in R0, capped), plus binary
                     heads for ``reach_1`` / ``reach_2`` (P(reach +j R0 from the bar-k close before the stop)).
  INVALIDATION head  binary ``stop_first`` (stop touched before +2R from the bar-k close) and ``dip_recovers``.
Baseline per head (design memo section 3-4): the training fold's own UNCONDITIONAL per-(strategy, timeframe) quantile / base rate. Skill =
1 - loss_model / loss_baseline on the test fold (pinball for quantiles, log-loss for binaries), plus AUC. Skill is NECESSARY, NEVER SUFFICIENT: the
verdict of record is the head applied as a CF-replay arm under RULE-AM-RISK-ADJUSTED-V1 (a separate unit); this script does not make that claim.

Folds: calendar half-years of TRADE ENTRY time, 2022-01-01 .. 2026-01-01 (dev), then the HOLDOUT 2026-01-01 .. end (claimed in the holdout ledger
before it is scored). A training trade is dropped when its label window [entry, exit + FWD_BARS bars] reaches within EMBARGO_DAYS of the test start
(the whole trade, never only some of its bars: the split unit is the trade). Features are the point-in-time ones ``cf_bar_labels`` emits (bars 1..k):
open_r, peak_r, mae_r, bars_since_peak, bars_open, range_atr_k, plus side, timeframe and the strategy code. Richer features (structure, market state)
are NOT built here and are recorded as a limitation.

  python3 scripts/research/am_heads_fit.py run --labels DIR [DIR...] --corpus ROOT --out DIR [--max-trades N] [--rows-per-fold N]
  python3 scripts/research/am_heads_fit.py dump --labels DIR [DIR...] --corpus ROOT --out DIR [--rows-per-fold 400000]
  python3 scripts/research/am_heads_fit.py --self-test

``dump`` (AM v2 STAGE B, unit family RQ-20261124-b5a1-*): re-fits the Stage A recipe (same features, LGB params, seed, row cap, purged folds) on each
fold's TRAIN rows only and SAVES the heads, one LightGBM text model per (fold, head) plus ``manifest.json`` (fold id and test window, feature list,
strategy-code map, per-file sha256, and the training-score thresholds the policy uses). It scores NO test row and claims NO holdout: the holdout
fold's head is fitted on trades whose label window ends 7 days before 2026-01-01, never on a holdout outcome. A replay then loads the head of the
fold a trade ENTERED in, i.e. a head that never saw that trade (``am_policy_arm.load_heads``). Stage A's own models were not saved, so these are
re-fits of the same recipe with the same seed, not byte-identical copies of the Stage A fits; the manifest says so.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import sys
import time
from array import array
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

SCHEMA = "am_heads_fit/1"
QUANTILES = (0.25, 0.5, 0.75, 0.9)
MFE_CAP = 10.0
FWD_BARS = 48
EMBARGO_DAYS = 7
DEV_FOLDS = ["2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01"]
HOLDOUT_START = "2026-01-01"
FEATS = ["open_r", "peak_r", "mae_r", "bars_since_peak", "bars_open", "range_atr_k", "side", "tf_log_sec", "strat"]
BIN_HEADS = ("reach_1", "reach_2", "stop_first", "dip_recovers")
SEED = 20261123
LGB = {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 2000, "subsample": 0.7, "subsample_freq": 1,
       "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": SEED, "verbose": -1, "n_jobs": 4}


def pinball(y: np.ndarray, q: np.ndarray, a: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(a * d, (a - 1.0) * d)))


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def pinball_rows(y, q, a):
    d = y - q
    return np.maximum(a * d, (a - 1.0) * d)


def logloss_rows(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def by_strategy_cut(strat_te, y_te, loss_model, loss_state, loss_uncond):
    """Per-strategy [n, sum loss_model, sum loss_state, sum loss_uncond, sum y] on the test rows (aggregated across folds by the caller)."""
    out = {}
    for sid in np.unique(strat_te):
        m = strat_te == sid
        out[int(sid)] = [int(m.sum()), float(loss_model[m].sum()), float(loss_state[m].sum()), float(loss_uncond[m].sum()), float(y_te[m].sum())]
    return out


def skill(loss_model: float, loss_base: float):
    return None if not loss_base else round(1.0 - loss_model / loss_base, 5)


def load(label_dirs, jobs, tf_sec, max_trades=None, seed=SEED):
    """Per-row arrays + per-row trade index; trade table with entry / label_end (epoch s). Censored rows are dropped (counted)."""
    import lightgbm  # noqa: F401  (fail early, before the long read)
    cols = {k: array("f") for k in FEATS + ["fwd_mfe_r"] + list(BIN_HEADS)}
    tidx = array("i")
    trade_entry, trade_end, strat_ids = [], [], {}
    rng = np.random.default_rng(seed)
    files = sorted(f for d in label_dirs for f in glob.glob(str(Path(d) / "**" / "*.jsonl.gz"), recursive=True))
    n_cens = n_trades = n_nojob = 0
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for ln in fh:
                if max_trades and rng.random() > max_trades / 469172.0:
                    continue
                r = json.loads(ln)
                job = jobs.get(r["trade_key"])
                if job is None:
                    n_nojob += 1
                    continue
                import live_review_counterfactual as lrc
                t0, t1 = lrc._ts(job.get("entry_time")), lrc._ts(job.get("exit_time"))
                sec = tf_sec[r["timeframe"]]
                if t0 is None or t1 is None:
                    n_nojob += 1
                    continue
                sid = strat_ids.setdefault(str(r.get("strategy")), len(strat_ids))
                ti = len(trade_entry)
                trade_entry.append(t0)
                trade_end.append(t1 + FWD_BARS * sec)
                n_trades += 1
                side = 1.0 if str(r.get("direction")).lower() in ("long", "buy") else -1.0
                for x in r["rows"]:
                    lab = x["labels"]
                    if lab["censored"]:
                        n_cens += 1
                        continue
                    ft = x["features"]
                    for k in ("open_r", "peak_r", "mae_r", "bars_since_peak", "bars_open"):
                        cols[k].append(ft[k])
                    cols["range_atr_k"].append(ft["range_atr_k"] if ft["range_atr_k"] is not None else np.nan)
                    cols["side"].append(side)
                    cols["tf_log_sec"].append(float(np.log(sec)))
                    cols["strat"].append(sid)
                    cols["fwd_mfe_r"].append(min(max(lab["fwd_mfe_r"], 0.0), MFE_CAP))
                    for h in BIN_HEADS:
                        cols[h].append(float(lab[h]))
                    tidx.append(ti)
    arr = {k: np.frombuffer(v, dtype=np.float32) for k, v in cols.items()}
    meta = {"n_files": len(files), "n_trades": n_trades, "n_rows": int(len(tidx)), "n_censored_dropped": n_cens, "n_trades_without_job": n_nojob,
            "strategies": {v: k for k, v in strat_ids.items()}}
    return arr, np.frombuffer(tidx, dtype=np.int32), np.array(trade_entry), np.array(trade_end), meta


def split(trade_entry, trade_end, test_a, test_b, embargo_s):
    """Trade-level purge: train = trades whose whole label window ends before test_a - embargo; test = trades ENTERING in [test_a, test_b)."""
    train = np.where(trade_end < test_a - embargo_s)[0]
    test = np.where((trade_entry >= test_a) & (trade_entry < test_b))[0]
    return train, test


def fit_eval(arr, tidx, train_trades, test_trades, rows_per_fold, rng):
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    tr_mask = np.isin(tidx, train_trades)
    te_mask = np.isin(tidx, test_trades)
    tr = np.where(tr_mask)[0]
    te = np.where(te_mask)[0]
    if len(tr) > rows_per_fold:
        tr = rng.choice(tr, rows_per_fold, replace=False)
    if len(te) > rows_per_fold:
        te = rng.choice(te, rows_per_fold, replace=False)
    if len(tr) < 5000 or len(te) < 1000:
        return {"skipped": f"train rows {len(tr)}, test rows {len(te)}"}
    X = np.column_stack([arr[k] for k in FEATS])
    strat = arr["strat"].astype(np.int32)
    out = {"n_train_rows": int(len(tr)), "n_test_rows": int(len(te)), "n_train_trades": int(len(train_trades)), "n_test_trades": int(len(test_trades)),
           "heads": {}}
    # unconditional per-strategy baseline from the TRAIN rows
    def base_q(y_tr, a):
        by = {s: np.quantile(y_tr[strat[tr] == s], a) for s in np.unique(strat[tr])}
        glob_q = float(np.quantile(y_tr, a))
        return np.array([by.get(s, glob_q) for s in strat[te]])
    def base_p(y_tr):
        by = {s: float(y_tr[strat[tr] == s].mean()) for s in np.unique(strat[tr])}
        g = float(y_tr.mean())
        return np.array([by.get(s, g) for s in strat[te]])
    # STATE-CONDITIONED baseline (the PRIMARY comparison): the training fold's empirical rate / quantile per (strategy, open_r decile, bar-age bin).
    # A head must beat what a lookup on where the trade already sits can say; the unconditional per-strategy baseline above is kept as the weaker reference.
    import pandas as pd
    edges = np.unique(np.quantile(arr["open_r"][tr], np.linspace(0, 1, 11)[1:-1]))
    age_edges = np.array([2, 3, 4, 6, 9, 14, 22, 35])
    def skey(ix):
        return (strat[ix].astype(np.int64) * 10_000 + np.digitize(arr["open_r"][ix], edges).astype(np.int64) * 100
                + np.digitize(arr["bars_open"][ix], age_edges).astype(np.int64))
    k_tr, k_te = skey(tr), skey(te)
    def state_q(y_tr_, a):
        df = pd.DataFrame({"k": k_tr, "y": y_tr_})
        g = df.groupby("k")["y"].agg(["count", lambda v: float(np.quantile(v, a))])
        g.columns = ["n", "q"]
        g = g[g["n"] >= 200]["q"]
        fb = base_q(y_tr_, a)
        return np.where(pd.Series(k_te).isin(g.index).to_numpy(), pd.Series(k_te).map(g).to_numpy(), fb)
    def state_p(y_tr_):
        df = pd.DataFrame({"k": k_tr, "y": y_tr_})
        g = df.groupby("k")["y"].agg(["count", "mean"])
        g = g[g["count"] >= 200]["mean"]
        fb = base_p(y_tr_)
        return np.where(pd.Series(k_te).isin(g.index).to_numpy(), pd.Series(k_te).map(g).to_numpy(), fb)
    y_tr, y_te = arr["fwd_mfe_r"][tr], arr["fwd_mfe_r"][te]
    for a in QUANTILES:
        m = lgb.LGBMRegressor(objective="quantile", alpha=a, **LGB)
        m.fit(X[tr], y_tr, categorical_feature=[FEATS.index("strat")])
        # provenance: predict -- LGBMRegressor.predict is the conditional a-quantile of fwd_mfe_r in R0, not a probability
        p = m.predict(X[te])
        b = base_q(y_tr, a)
        out["heads"][f"q{a:g}"] = {"pinball_model": round(pinball(y_te, p, a), 5), "pinball_base": round(pinball(y_te, b, a), 5),
                                   "skill": skill(pinball(y_te, p, a), pinball(y_te, b, a)), "coverage": round(float((y_te <= p).mean()), 4)}
        sb = state_q(y_tr, a)
        out["heads"][f"q{a:g}"].update({"pinball_state_base": round(pinball(y_te, sb, a), 5),
                                        "skill_vs_state": skill(pinball(y_te, p, a), pinball(y_te, sb, a)),
                                        "by_strategy": by_strategy_cut(strat[te], y_te, pinball_rows(y_te, p, a), pinball_rows(y_te, sb, a),
                                                                       pinball_rows(y_te, b, a))})
    for h in BIN_HEADS:
        yb_tr, yb_te = arr[h][tr], arr[h][te]
        if yb_tr.min() == yb_tr.max() or yb_te.min() == yb_te.max():
            out["heads"][h] = {"skipped": "one class"}
            continue
        m = lgb.LGBMClassifier(**LGB)
        m.fit(X[tr], yb_tr, categorical_feature=[FEATS.index("strat")])
        # provenance: predict_proba -- the calibrated-by-fit P(label=1), a probability
        p = m.predict_proba(X[te])[:, 1]
        b = base_p(yb_tr)
        out["heads"][h] = {"logloss_model": round(logloss(yb_te, p), 5), "logloss_base": round(logloss(yb_te, b), 5),
                           "skill": skill(logloss(yb_te, p), logloss(yb_te, b)), "auc": round(float(roc_auc_score(yb_te, p)), 5),
                           "base_rate_test": round(float(yb_te.mean()), 5), "mean_pred": round(float(p.mean()), 5)}
        sbp = state_p(yb_tr)
        out["heads"][h].update({"logloss_state_base": round(logloss(yb_te, sbp), 5), "skill_vs_state": skill(logloss(yb_te, p), logloss(yb_te, sbp)),
                                "auc_state_base": round(float(roc_auc_score(yb_te, sbp)), 5),
                                "by_strategy": by_strategy_cut(strat[te], yb_te, logloss_rows(yb_te, p), logloss_rows(yb_te, sbp), logloss_rows(yb_te, b))})
    return out


def run(a) -> int:
    import pandas as pd
    import cf_bars
    import cf_bulk
    t0 = time.time()
    root = Path(a.corpus)
    jobs, counts = cf_bulk.load_jobs(cf_bulk.discover(root), root)
    arr, tidx, te_, tend, meta = load(a.labels, jobs, cf_bars.TF_SECONDS, a.max_trades)
    print(json.dumps({k: v for k, v in meta.items() if k != "strategies"}), flush=True)
    rng = np.random.default_rng(SEED)
    emb = EMBARGO_DAYS * 86400.0
    ts = lambda s: pd.Timestamp(s, tz="UTC").timestamp()  # noqa: E731
    bounds = [ts(x) for x in DEV_FOLDS] + [ts(HOLDOUT_START)]
    folds = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        trn, tst = split(te_, tend, lo, hi, emb)
        rec = {"test_start": pd.Timestamp(lo, unit="s", tz="UTC").strftime("%Y-%m-%d"), "kind": "dev", **fit_eval(arr, tidx, trn, tst, a.rows_per_fold, rng)}
        folds.append(rec)
        print(json.dumps({k: rec[k] for k in ("test_start", "n_train_rows", "n_test_rows") if k in rec}), flush=True)
    claim = None
    if not a.no_holdout:
        import holdout_lock
        end_day = pd.Timestamp(float(te_.max()), unit="s", tz="UTC").strftime("%Y-%m-%d")
        claim = holdout_lock.claim_read("AM-HEADS-stageA", HOLDOUT_START, end_day, a.unit or "am-heads-stage-a", a.reader,
                                        Path(a.ledger) if a.ledger else holdout_lock.LEDGER, train_end="2025-12-01", family="AM-HEADS")
        trn, tst = split(te_, tend, bounds[-1], float("inf"), emb)
        folds.append({"test_start": HOLDOUT_START, "kind": "holdout", **fit_eval(arr, tidx, trn, tst, a.rows_per_fold, rng)})
    pooled = {}
    for h in [f"q{x:g}" for x in QUANTILES] + list(BIN_HEADS):
        sk = [f["heads"][h]["skill"] for f in folds if f.get("kind") == "dev" and f.get("heads", {}).get(h, {}).get("skill") is not None]
        ss = [f["heads"][h]["skill_vs_state"] for f in folds if f.get("kind") == "dev" and f.get("heads", {}).get(h, {}).get("skill_vs_state") is not None]
        pooled[h] = {"n_dev_folds": len(sk), "dev_folds_skill_positive": int(sum(1 for s in sk if s > 0)),
                     "dev_mean_skill": round(float(np.mean(sk)), 5) if sk else None,
                     "dev_se_skill_across_folds": round(float(np.std(sk, ddof=1) / np.sqrt(len(sk))), 5) if len(sk) > 1 else None,
                     "dev_folds_state_skill_positive": int(sum(1 for s in ss if s > 0)),
                     "dev_mean_skill_vs_state": round(float(np.mean(ss)), 5) if ss else None,
                     "dev_se_skill_vs_state_across_folds": round(float(np.std(ss, ddof=1) / np.sqrt(len(ss))), 5) if len(ss) > 1 else None}
    names = meta["strategies"]
    by_leg = {}
    for h in [f"q{x:g}" for x in QUANTILES] + list(BIN_HEADS):
        acc = {}
        for f in folds:
            if f.get("kind") != "dev":
                continue
            for sid, v in (f.get("heads", {}).get(h, {}).get("by_strategy") or {}).items():
                t = acc.setdefault(int(sid), [0, 0.0, 0.0, 0.0, 0.0])
                for i in range(5):
                    t[i] += v[i]
        by_leg[h] = {names.get(sid, str(sid)): {"n_test_rows_dev": int(t[0]), "base_rate_or_mean_y": round(t[4] / t[0], 5),
                                               "skill_vs_state": skill(t[1] / t[0], t[2] / t[0]), "skill_vs_unconditional": skill(t[1] / t[0], t[3] / t[0])}
                     for sid, t in sorted(acc.items()) if t[0] >= 2000}
    res = {"schema": SCHEMA, "unit": a.unit, "by_strategy_dev_pooled": by_leg, "meta": {k: v for k, v in meta.items() if k != "strategies"}, "strategies": meta["strategies"],
           "corpus_jobs": counts.get("distinct_jobs"), "folds": folds, "pooled_dev": pooled, "holdout_claim": claim,
           "limits": "features are the 6 PIT path features + side/tf/strategy only (no structure/market state); skill is a loss ratio vs the per-strategy unconditional baseline, not a P&L claim",
           "read_state": "measured", "provenance": "ESTIMATED", "elapsed_s": round(time.time() - t0)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    if not a.no_holdout:
        v, per = stage_a_verdict(pooled, folds)
        vj = {"verdict": v, "read_state": "measured", "n": meta["n_rows"], "rule": STAGE_A_RULE, "per_head": per,
              "note": f"per head {per}; target needs >=1 pass AND invalidation needs >=1 pass; skill_vs_state is vs the state-conditioned empirical baseline",
              "population": (f"{meta['n_trades']} labelled trades / {meta['n_rows']} uncensored per-bar rows of the run-w corpus (cf_bar_labels), "
                             f"8 dev half-year folds 2022-01..2026-01 + claimed holdout {HOLDOUT_START}.., purged by trade, <= {a.rows_per_fold} rows per fold"),
              "measurement": {"pooled_dev": pooled}}
        (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
        print(json.dumps({"verdict": v, "per_head": per}), flush=True)
    print(json.dumps(pooled), flush=True)
    return 0


HEADS_DUMP_SCHEMA = "am_heads_dump/1"
#: heads saved by ``dump`` (every head Stage A fitted); the Stage B policy reads q0.5, q0.9, stop_first and dip_recovers
DUMP_HEADS = tuple(f"q{a:g}" for a in QUANTILES) + BIN_HEADS
#: training-score percentiles stored per binary head: the policy acts on the TOP DECILE of the fold's own training scores (a pre-registered, fold-PIT cut)
THRESH_PCTS = (50, 90)


def dump_fold(arr, tidx, train_trades, rows_per_fold, rng, fold_id, out_dir: Path) -> dict:
    """Fit every head on the TRAIN rows of one fold and save them under ``out_dir/<fold_id>/``. Never touches a test row."""
    import hashlib
    import lightgbm as lgb
    tr = np.where(np.isin(tidx, train_trades))[0]
    if len(tr) > rows_per_fold:
        tr = rng.choice(tr, rows_per_fold, replace=False)
    if len(tr) < 5000:
        return {"fold_id": fold_id, "skipped": f"train rows {len(tr)}"}
    X = np.column_stack([arr[k] for k in FEATS])
    fdir = out_dir / fold_id
    fdir.mkdir(parents=True, exist_ok=True)
    files, thresholds = {}, {}
    for a in QUANTILES:
        m = lgb.LGBMRegressor(objective="quantile", alpha=a, **LGB)
        m.fit(X[tr], arr["fwd_mfe_r"][tr], categorical_feature=[FEATS.index("strat")])
        p = fdir / f"q{a:g}.txt"
        m.booster_.save_model(str(p))
        files[f"q{a:g}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    for h in BIN_HEADS:
        y = arr[h][tr]
        if y.min() == y.max():
            continue
        m = lgb.LGBMClassifier(**LGB)
        m.fit(X[tr], y, categorical_feature=[FEATS.index("strat")])
        p = fdir / f"{h}.txt"
        m.booster_.save_model(str(p))
        files[h] = hashlib.sha256(p.read_bytes()).hexdigest()
        # provenance: predict_proba -- P(label=1) on the TRAIN rows, used only to set the fold's percentile cuts
        sc = m.predict_proba(X[tr])[:, 1]
        thresholds[h] = {f"p{q}": float(np.percentile(sc, q)) for q in THRESH_PCTS}
    return {"fold_id": fold_id, "n_train_rows": int(len(tr)), "n_train_trades": int(len(train_trades)), "files": files, "thresholds": thresholds}


def dump(a) -> int:
    import pandas as pd
    import cf_bars
    import cf_bulk
    t0 = time.time()
    root = Path(a.corpus)
    jobs, counts = cf_bulk.load_jobs(cf_bulk.discover(root), root)
    arr, tidx, te_, tend, meta = load(a.labels, jobs, cf_bars.TF_SECONDS, a.max_trades)
    print(json.dumps({k: v for k, v in meta.items() if k != "strategies"}), flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    emb = EMBARGO_DAYS * 86400.0
    ts = lambda s: pd.Timestamp(s, tz="UTC").timestamp()  # noqa: E731
    bounds = [ts(x) for x in DEV_FOLDS] + [ts(HOLDOUT_START)]
    folds = []
    for i, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        trn, _ = split(te_, tend, lo, hi, emb)
        rec = dump_fold(arr, tidx, trn, a.rows_per_fold, np.random.default_rng(SEED + i), DEV_FOLDS[i], out)
        folds.append({**rec, "kind": "dev", "test_start": DEV_FOLDS[i], "test_end": (DEV_FOLDS[i + 1] if i + 1 < len(DEV_FOLDS) else HOLDOUT_START)})
        print(json.dumps({k: rec[k] for k in ("fold_id", "n_train_rows") if k in rec}), flush=True)
    trn, _ = split(te_, tend, bounds[-1], float("inf"), emb)
    rec = dump_fold(arr, tidx, trn, a.rows_per_fold, np.random.default_rng(SEED + len(DEV_FOLDS)), HOLDOUT_START, out)
    folds.append({**rec, "kind": "holdout", "test_start": HOLDOUT_START, "test_end": None})
    man = {"schema": HEADS_DUMP_SCHEMA, "feats": FEATS, "heads": list(DUMP_HEADS), "lgb_params": {k: v for k, v in LGB.items() if k != "n_jobs"},
           "seed": SEED, "rows_per_fold": a.rows_per_fold, "embargo_days": EMBARGO_DAYS, "mfe_cap": MFE_CAP, "strategies": meta["strategies"],
           "threshold_percentiles": list(THRESH_PCTS), "folds": folds,
           "note": "re-fit of the Stage A recipe (RQ-20261123-a9d1-01) on each fold's TRAIN rows; no test row scored, no holdout claimed or read; "
                   "Stage A's own models were not saved, so these are same-recipe, same-seed re-fits, not byte-identical copies",
           "labels_n_trades": meta["n_trades"], "corpus_jobs": counts.get("distinct_jobs"), "elapsed_s": round(time.time() - t0),
           "provenance": "ESTIMATED"}
    (out / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    return 0


STAGE_A_RULE = {"id": "RULE-AM-HEADS-STAGE-A-20261123", "min_dev_mean_skill_vs_state": 0.01, "min_dev_folds_positive": 6, "n_dev_folds": 8,
                "graded_heads": {"target": ["q0.5", "q0.9", "reach_2"], "invalidation": ["stop_first", "dip_recovers"]}}


def head_verdict(pooled_h: dict, holdout_h: dict | None, rule: dict = STAGE_A_RULE) -> str:
    """Per head: PASS iff dev mean skill_vs_state >= the bar AND >= min folds positive AND the holdout fold's skill_vs_state > 0;
    FAIL iff the dev mean skill_vs_state <= 0 OR fewer than half the dev folds are positive; else INDETERMINATE."""
    m, k = pooled_h.get("dev_mean_skill_vs_state"), pooled_h.get("dev_folds_state_skill_positive", 0)
    if m is None:
        return "indeterminate"
    if m <= 0 or k < rule["n_dev_folds"] / 2:
        return "fail"
    ho = (holdout_h or {}).get("skill_vs_state")
    if m >= rule["min_dev_mean_skill_vs_state"] and k >= rule["min_dev_folds_positive"] and ho is not None and ho > 0:
        return "pass"
    return "indeterminate"


def stage_a_verdict(pooled: dict, folds: list, rule: dict = STAGE_A_RULE):
    ho = next((f for f in folds if f.get("kind") == "holdout"), {})
    per = {h: head_verdict(pooled[h], (ho.get("heads") or {}).get(h), rule) for g in rule["graded_heads"].values() for h in g}
    tgt = [per[h] for h in rule["graded_heads"]["target"]]
    inv = [per[h] for h in rule["graded_heads"]["invalidation"]]
    if "pass" in tgt and "pass" in inv:
        v = "pass"
    elif all(x == "fail" for x in tgt + inv):
        v = "fail"
    else:
        v = "indeterminate"
    return v, per


def _self_test() -> None:
    assert head_verdict({"dev_mean_skill_vs_state": 0.02, "dev_folds_state_skill_positive": 7}, {"skill_vs_state": 0.01}) == "pass"
    assert head_verdict({"dev_mean_skill_vs_state": 0.02, "dev_folds_state_skill_positive": 7}, {"skill_vs_state": -0.01}) == "indeterminate"
    assert head_verdict({"dev_mean_skill_vs_state": 0.02, "dev_folds_state_skill_positive": 3}, {"skill_vs_state": 0.01}) == "fail"
    assert head_verdict({"dev_mean_skill_vs_state": -0.001, "dev_folds_state_skill_positive": 6}, None) == "fail"
    assert head_verdict({"dev_mean_skill_vs_state": 0.005, "dev_folds_state_skill_positive": 7}, {"skill_vs_state": 0.01}) == "indeterminate"
    y = np.array([0.0, 1.0, 2.0, 3.0])
    assert abs(pinball(y, np.full(4, 1.5), 0.5) - 0.5 * np.mean(np.abs(y - 1.5))) < 1e-12
    assert logloss(np.array([1.0, 0.0]), np.array([0.5, 0.5])) - np.log(2) < 1e-12
    assert skill(0.9, 1.0) == 0.1 and skill(1.0, 0.0) is None
    te = np.array([0.0, 10.0, 20.0, 30.0])
    tend = np.array([5.0, 15.0, 25.0, 35.0])
    tr, tst = split(te, tend, 20.0, 40.0, 2.0)
    assert list(tr) == [0, 1] and list(tst) == [2, 3]        # trade 2's window (20..25) is in test; trade 1 ends 15 < 18; none leaks
    tr2, _ = split(te, tend, 20.0, 40.0, 6.0)
    assert list(tr2) == [0]                                  # a bigger embargo drops trade 1 (ends 15, needs < 14)
    print("am_heads_fit self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "dump"])
    ap.add_argument("--labels", nargs="+", default=[])
    ap.add_argument("--corpus", default="")
    ap.add_argument("--out", default="/tmp/am_heads_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default="")
    ap.add_argument("--max-trades", type=int, default=0, help="subsample ~this many trades (dev smoke only; 0 = all)")
    ap.add_argument("--rows-per-fold", type=int, default=800_000)
    ap.add_argument("--no-holdout", action="store_true", help="dev smoke: do not claim or score the holdout")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if not a.labels or not a.corpus:
        ap.error("run/dump need --labels and --corpus")
    return dump(a) if a.cmd == "dump" else run(a)


if __name__ == "__main__":
    sys.exit(main())
