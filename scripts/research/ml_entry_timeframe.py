#!/usr/bin/env python3
"""ENTRY timeframe-scaling harness (row ML-TIMEFRAME, lever `timeframe`): the SAME pooled ENTRY pipeline at 5m / 15m / 1h / 4h bars.

What it answers (operator 2026-11-01 ~22:35Z: "queue a training session for 5 minutes bars as well so we can compare results and see
what scales tfs and what doesn't"): does the ENTRY edge scale to other bar sizes, and which features keep their role?

Two scalings, so "what scales" is measured, not assumed (a timeframe change moves two things at once: the bar size and the clock horizon):
  bar    the SAME numbers of BARS everywhere: windows 1,4,12,24,72,168, ATR 14, label horizon 24, decide every 4th bar.
  clock  the SAME clock time everywhere: every window, the ATR length, the horizon (24 h) and the decision cadence (4 h) are the 1h recipe's
         hours, converted to bars (round, floor 1). At 4h a window under one bar is floored to one bar (ret_1 and ret_4 coincide): stated.
At 1h the two scalings are the identical 1h recipe; the self-test proves this harness reproduces ml_decision_entry's labels and features there.

Held fixed across arms: the 60-perp frozen universe (the bp2 manifest), the 8 DEV walk-forward folds (2022-01..2025-09), the v1 LightGBM
recipe, the bracket (SL 2 / TP 3 ATR), the full cost stack (fee 11 bps + slippage + funding, ml_decision_entry._cost_r), the one-position-per-symbol
policy, seeds 7/11/13. DEV ONLY: no month after 2025-09 is ever downloaded, so the held-out year and W1 cannot be read.

    python3 scripts/research/ml_entry_timeframe.py run --unit RQ-20261101-b621-01 --out /tmp/tf --n-jobs 4
    python3 scripts/research/ml_entry_timeframe.py run --unit RQ-20261101-b621-01 --out /tmp/tf --smoke      # 6 symbols, for wiring checks
    python3 scripts/research/ml_entry_timeframe.py count                                                    # row-count / ETA model, no network
    python3 scripts/research/ml_entry_timeframe.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import itertools
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as E
import ml_entry_levers as L

REPO = Path(__file__).resolve().parents[2]
SEEDS = (7, 11, 13)
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
DEV_END = "2025-09-30"                    # last day ever downloaded; HOLDOUT_START is 2025-10-01
TAU = 0.10                                 # the frozen v1 entry threshold: a FIXED tau, nothing is selected on the result
GATE_MAX_COST_R = 0.06                     # v2's cost gate: refuse when k / atr_pct > 0.06
V2_MODEL = REPO / "ml/served/ml_decision_entry_v2/model.json"
GATE_K_FALLBACK = 0.0007744467             # read from the v2 artifact when present; this is its committed value
SHARED_GRID_MIN = 240                      # decisions at UTC multiples of 4 h exist in every arm: the overlap is measured there
UNITS = {                                  # unit id -> (timeframe, scaling)
    "RQ-20261101-b620-01": ("1h", "bar"),
    "RQ-20261101-b621-01": ("15m", "bar"), "RQ-20261101-b622-01": ("15m", "clock"),
    "RQ-20261101-b623-01": ("5m", "bar"), "RQ-20261101-b624-01": ("5m", "clock"),
    "RQ-20261101-b625-01": ("4h", "bar"), "RQ-20261101-b626-01": ("4h", "clock"),
}
REF_ROUND1 = {"source": "comms/research/RQ-20261101-b607-01 result.json arms.base (R0, seeds 7/11/13, tau 0.10, dev folds, pooled 60)",
              "mean": 0.0089485665675495, "n": [71950, 71886, 72063], "mean_tol": 0.0005, "n_rel_tol": 0.01}
FIT_S_PER_MROW = 6.0                       # INFERRED 2026-11-01: LGBMRegressor 300 trees x 20 float features, 4 threads, random data


def gate_k() -> float:
    try:
        return float(json.loads(V2_MODEL.read_text())["meta"]["cost_gate"]["k_cost_x_atr"])
    except Exception:  # noqa: BLE001  # allow-silent: the artifact is absent in a bare checkout; the committed constant is the fallback and is reported
        return GATE_K_FALLBACK


# ----------------------------------------------------------------------------------------------- scaling
def spec(tf: str, scaling: str) -> dict:
    m = TF_MIN[tf]
    b = 60.0 / m                                                   # bars per hour

    def f(k: float) -> int:
        return int(k) if (scaling == "bar" or tf == "1h") else max(1, int(round(k * b)))

    return {"tf": tf, "scaling": scaling, "m": m, "ret": [f(k) for k in (1, 4, 12, 24, 72, 168)], "v24": f(24), "v168": f(168), "atr": f(14),
            "rsi": f(14), "rng": [f(24), f(168)], "vz": f(168), "r24": f(24), "H": f(24), "C": f(4)}


# ----------------------------------------------------------------------------------------------- fetch (dev only)
def months(start="2020-07", end=DEV_END[:7]) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def fetch_month(sym: str, tf: str, month: str) -> pd.DataFrame | None:
    import requests
    url = f"{E._BASE}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            raw = zf.read(zf.namelist()[0]).decode()
            df = pd.read_csv(io.StringIO(raw), header=0 if raw.split("\n", 1)[0].startswith("open_time") else None).iloc[:, :6]
            df.columns = ["open_time", "open", "high", "low", "close", "volume"]
            return df
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch_symbol(cache: Path, sym: str, tf: str, first="2020-07") -> dict:
    p = cache / tf / f"{sym}.pkl"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return {"symbol": sym, "rows": len(pd.read_pickle(p)), "cached": True}
    frames, missing = [], []
    for mo in months(first):
        d = fetch_month(sym, tf, mo)
        (missing if d is None else frames).append(mo if d is None else d)
    df = pd.concat(frames, ignore_index=True)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df[df.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC")]                  # the held-out year is never kept
    df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(p)
    return {"symbol": sym, "rows": len(df), "missing_months": len(missing), "cached": False}


def fetch_all(cache: Path, symbols: list[str], tf: str, workers: int = 16, first="2020-07") -> list[dict]:
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda s: fetch_symbol(cache, s, tf, first), symbols))


# ----------------------------------------------------------------------------------------------- features / labels (scaled)
def features_tf(df: pd.DataFrame, sp: dict) -> pd.DataFrame:
    c, h, lo, v = (df[k].astype(float) for k in ("close", "high", "low", "volume"))
    lr = np.log(c).diff()
    vol24 = lr.rolling(sp["v24"]).std()
    vol168 = lr.rolling(sp["v168"]).std()
    f = pd.DataFrame({"ts": df["ts"]})
    for nm, k in zip((1, 4, 12, 24, 72, 168), sp["ret"]):
        f[f"ret_{nm}"] = (np.log(c) - np.log(c.shift(k))) / (vol24 * np.sqrt(k))
    f["vol24"] = vol24
    f["vol_ratio"] = vol24 / vol168
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    f["atr_pct"] = tr.rolling(sp["atr"]).mean() / c
    for nm, k in zip((24, 168), sp["rng"]):
        hi, lw = h.rolling(k).max(), lo.rolling(k).min()
        f[f"range_pos_{nm}"] = (c - lw) / (hi - lw).replace(0, np.nan)
    lv = np.log1p(v)
    f["vol_z"] = (lv - lv.rolling(sp["vz"]).mean()) / lv.rolling(sp["vz"]).std()
    up = lr.clip(lower=0).rolling(sp["rsi"]).mean()
    dn = (-lr.clip(upper=0)).rolling(sp["rsi"]).mean()
    f["rsi14"] = up / (up + dn).replace(0, np.nan)
    close_ts = df["ts"] + pd.Timedelta(minutes=sp["m"])
    f["hour"] = close_ts.dt.hour
    f["dow"] = close_ts.dt.dayofweek
    f["ret24_raw"] = np.log(c) - np.log(c.shift(sp["r24"]))
    return f


def _t_ns(ts: pd.Series) -> np.ndarray:
    return ts.to_numpy().astype("datetime64[ns]").astype("int64")      # explicit ns: pandas 3 parses to ms units


def label_tf(df: pd.DataFrame, sp: dict) -> pd.DataFrame:
    m, H, C = sp["m"], sp["H"], sp["C"]
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(sp["atr"], min_periods=sp["atr"]).mean().to_numpy()
    t_ns = _t_ns(df["ts"])
    close_min = (t_ns + m * 60_000_000_000) // 60_000_000_000
    N = len(df)
    cand = np.where((close_min % (C * m) == 0) & ~np.isnan(atr))[0]
    cand = cand[cand + H < N]
    cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * m * 60_000_000_000]     # the H forward bars must be contiguous
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
    entry = Ob[:, 0]
    a = atr[cand]
    risk = E.SL_ATR * a
    out = {"i": cand, "ts": df["ts"].to_numpy()[cand], "atr": a, "entry": entry}
    t_entry_s = t_ns[cand + 1] / 1e9
    for name, side in (("long", 1), ("short", -1)):
        px, j, reason = E.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side)
        gross = side * (px - entry) / risk
        t_exit_s = t_ns[cand + j] / 1e9 + m * 60.0
        fee, slip, fund = E._cost_r(entry, px, risk, t_entry_s, t_exit_s)
        out[f"gross_{name}"] = gross
        out[f"net_{name}"] = gross - fee - slip - fund
        out[f"cost_{name}"] = fee + slip + fund
        out[f"reason_{name}"] = reason
        out[f"bars_{name}"] = j
    return pd.DataFrame(out)


def build_table(cache: Path, symbols: list[str], sp: dict, drop_ts_before: str | None = None) -> pd.DataFrame:
    """The c692-01 table (cross-sectional context over ``symbols``), scaled. Panels are taken on the decision grid only (the same values
    ml_decision_entry reads at those timestamps), which keeps the 5m panel small."""
    m, C = sp["m"], sp["C"]
    rows, r24s, v24s = [], {}, {}
    for sym in symbols:
        df = pd.read_pickle(cache / sp["tf"] / f"{sym}.pkl").reset_index(drop=True)
        if drop_ts_before:
            df = df[df.ts >= pd.Timestamp(drop_ts_before, tz="UTC")].reset_index(drop=True)
        f = features_tf(df, sp)
        lab = label_tf(df, sp).join(f.drop(columns=["ts"]), on="i")
        lab["symbol"] = sym
        feat_cols = [x for x in lab.columns if x in E.FEATURES or x in ("ret24_raw",)]
        lab[feat_cols] = lab[feat_cols].astype("float32")
        lab["i"] = lab["i"].astype("int64")
        rows.append(lab)
        close_min = (_t_ns(df["ts"]) + m * 60_000_000_000) // 60_000_000_000
        g = f.loc[close_min % (C * m) == 0]
        r24s[sym] = g.set_index("ts")["ret24_raw"]
        v24s[sym] = g.set_index("ts")["vol24"]
    tab = pd.concat(rows, ignore_index=True)
    del rows
    r24, v24 = pd.DataFrame(r24s), pd.DataFrame(v24s)
    key = pd.MultiIndex.from_arrays([tab["ts"], tab["symbol"]])
    tab["xs_rank_ret24"] = r24.rank(axis=1, pct=True).stack().reindex(key).to_numpy().astype("float32")
    breadth = (r24 > 0).sum(axis=1) / r24.notna().sum(axis=1)
    med_vol = v24.median(axis=1)
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


# ----------------------------------------------------------------------------------------------- walk-forward
def policy_fast(test: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, tau: float, mask: np.ndarray | None = None) -> pd.DataFrame:
    """E.policy exactly, on the rows that can matter: a row whose best score is <= tau is skipped by E.policy without touching the busy
    state, so dropping it first changes nothing. ``mask`` (the cost gate) drops refused rows the same way a live refusal does."""
    keep = np.maximum(pl, ps) > tau
    if mask is not None:
        keep &= mask
    if not keep.any():
        return pd.DataFrame(columns=["symbol", "ts", "side", "net_r", "gross_r", "cost_r", "reason", "pred"])
    return E.policy(test[keep], pl[keep], ps[keep], tau)


def walk_forward(tab: pd.DataFrame, sp: dict, seeds=SEEDS, n_jobs: int = 4, folds: list[str] | None = None, keep_models: bool = True) -> dict:
    import lightgbm as lgb
    bounds = [pd.Timestamp(x, tz="UTC") for x in (folds or E.DEV_FOLDS)] + [pd.Timestamp(E.HOLDOUT_START, tz="UTC")]
    dev = tab[tab.ts < bounds[-1]]
    h_td = pd.Timedelta(minutes=sp["m"] * (sp["H"] + 1))

    def gate_ok(t: pd.DataFrame) -> np.ndarray:
        return (gate_k() / t["atr_pct"].to_numpy(float)) <= GATE_MAX_COST_R
    out = {"trades": {}, "folds": [], "preds": [], "models": None, "test_last": None}
    for sd in seeds:
        out["trades"][sd] = {"ungated": {t: [] for t in E.TAU_GRID}, "gated": {t: [] for t in E.TAU_GRID}}
    for k, (a, b) in enumerate(itertools.pairwise(bounds)):
        t0 = time.time()
        test = dev[(dev.ts >= a) & (dev.ts < b - h_td)]
        train = dev[dev.ts < a - pd.Timedelta(days=E.EMBARGO_DAYS) - h_td]
        gm = gate_ok(test)
        rec = {"fold": k, "test_start": str(a.date()), "n_train": len(train), "n_test_rows": len(test), "gate_pass_share": float(gm.mean()) if len(gm) else None}
        for sd in seeds:
            params = {**E.LGB_PARAMS, "random_state": sd, "n_jobs": n_jobs}
            preds, models = [], {}
            for side in ("long", "short"):
                mdl = lgb.LGBMRegressor(**params).fit(train[E.FEATURES], train[f"net_{side}"])
                # provenance: predict — LGBMRegressor.predict is the regressed net R of that side, not a probability
                preds.append(mdl.predict(test[E.FEATURES]))
                models[side] = mdl
            pl, ps = preds
            for tau in E.TAU_GRID:
                for var, msk in (("ungated", None), ("gated", gm)):
                    tk = policy_fast(test, pl, ps, tau, msk)
                    if len(tk):
                        out["trades"][sd][var][tau].append(tk.assign(fold=k, year=pd.to_datetime(tk.ts, utc=True).dt.year))
            if sd == seeds[0]:
                close = test["ts"] + pd.Timedelta(minutes=sp["m"])
                on_grid = (((close - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(minutes=1)) % SHARED_GRID_MIN == 0).to_numpy()
                out["preds"].append(pd.DataFrame({"symbol": test["symbol"].to_numpy()[on_grid], "close_ts": close.to_numpy()[on_grid],
                                                  "fold": k, "p_long": pl[on_grid], "p_short": ps[on_grid], "atr_pct": test["atr_pct"].to_numpy()[on_grid]}))
                if k == len(bounds) - 2 and keep_models:
                    out["models"], out["test_last"] = models, test
        rec["seconds"] = round(time.time() - t0, 1)
        out["folds"].append(rec)
        print(json.dumps(rec), flush=True)
    return out


def trades_frame(wf: dict, sd: int, var: str, tau: float) -> pd.DataFrame:
    lst = wf["trades"][sd][var][tau]
    return pd.concat(lst, ignore_index=True) if lst else pd.DataFrame(columns=["symbol", "ts", "side", "net_r", "gross_r", "cost_r", "reason", "pred", "fold", "year"])


def stats_or_empty(t: pd.DataFrame) -> dict:
    if len(t) == 0:
        return {"n": 0, "mean": None, "gross": None, "cost": None, "per_fold": [(0, None)] * 8, "per_year": {int(y): (0, None) for y in L.YEARS}, "min_fold_n": 0}
    return L.stats(t)


def arm_stats(wf: dict, var: str, tau: float = TAU) -> list[dict]:
    return [stats_or_empty(trades_frame(wf, sd, var, tau)) for sd in SEEDS]


def viable(sts: list[dict]) -> dict:
    """The registered 'is it an edge at all' read, on the seed means: mean net > 0, >= 6 of 8 folds positive, >= 3 of 4 years positive,
    every fold >= 1000 decisions. Not a comparison with 1h."""
    means = [s["mean"] for s in sts if s["mean"] is not None]
    if len(means) < len(sts):
        return {"viable": False, "why": "no decisions in at least one seed", "mean": None}
    mean = float(np.mean(means))
    pf = [np.mean([s["per_fold"][k][1] for s in sts if s["per_fold"][k][1] is not None] or [np.nan]) for k in range(8)]
    py = [np.mean([s["per_year"][y][1] for s in sts if s["per_year"][y][1] is not None] or [np.nan]) for y in L.YEARS]
    minn = min(s["min_fold_n"] for s in sts)
    fp, yp = int(sum(1 for x in pf if x > 0)), int(sum(1 for x in py if x > 0))
    ok = mean > 0 and fp >= 6 and yp >= 3 and minn >= L.MIN_FOLD_N
    return {"viable": bool(ok), "mean": mean, "folds_positive": fp, "years_positive": yp, "min_fold_n": int(minn),
            "why": None if ok else ("a fold under %d decisions" % L.MIN_FOLD_N if minn < L.MIN_FOLD_N else "mean/folds/years condition unmet")}


def headline(base_sts: list[dict], arm_sts: list[dict]) -> dict:
    v = viable(arm_sts)
    if any(s["mean"] is None for s in arm_sts) or min(s["min_fold_n"] for s in arm_sts) < L.MIN_FOLD_N:
        j = {"verdict": "indeterminate", "why": "a fold under %d decisions or no decisions" % L.MIN_FOLD_N, "arm_mean": v["mean"]}
    else:
        j = L.judge(base_sts, arm_sts)
    if j["verdict"] == "win":
        word = "beats_1h"
    elif v["viable"]:
        word = "viable_not_better"
    elif j["verdict"] == "indeterminate":
        word = "indeterminate"
    else:
        word = "not_viable"
    return {"verdict": word, "viable": v, "vs_1h": j}


# ----------------------------------------------------------------------------------------------- readouts
def importance(wf: dict) -> dict:
    """Gain share and the sign of each feature's SHAP-contribution relationship, per side, from the LAST dev fold's seed-7 models."""
    models, test = wf["models"], wf["test_last"]
    if models is None or test is None or len(test) == 0:
        return {}
    samp = test.sample(min(100_000, len(test)), random_state=7)
    X = samp[E.FEATURES]
    res = {}
    for side, mdl in models.items():
        gain = mdl.booster_.feature_importance("gain").astype(float)
        share = gain / gain.sum() if gain.sum() else gain
        contrib = mdl.predict(X, pred_contrib=True)[:, :-1]
        sign = [float(pd.Series(X.iloc[:, i].to_numpy(float)).corr(pd.Series(contrib[:, i]), method="spearman")) for i in range(len(E.FEATURES))]
        res[side] = {f: {"gain_share": float(share[i]), "shap_sign_rho": sign[i]} for i, f in enumerate(E.FEATURES)}
    return res


def compare_importance(arm: dict, base: dict) -> dict:
    out = {}
    for side in arm:
        if side not in base:
            continue
        ga = pd.Series({f: v["gain_share"] for f, v in arm[side].items()})
        gb = pd.Series({f: v["gain_share"] for f, v in base[side].items()})
        keeps, drops = [], []
        for f in E.FEATURES:
            sa, sb = arm[side][f]["shap_sign_rho"], base[side][f]["shap_sign_rho"]
            ratio = ga[f] / gb[f] if gb[f] > 0 else np.nan
            same_sign = (np.sign(sa) == np.sign(sb)) or abs(sb) < 0.05 or abs(sa) < 0.05      # a near-zero relationship has no sign to keep or lose
            (keeps if (same_sign and 0.5 <= ratio <= 2.0) else drops).append(f)
        out[side] = {"gain_rank_spearman_vs_1h": float(ga.corr(gb, method="spearman")), "keeps": keeps, "drops": drops,
                     "top5_arm": ga.sort_values(ascending=False).index[:5].tolist(), "top5_1h": gb.sort_values(ascending=False).index[:5].tolist()}
    return out


def overlap(arm_p: pd.DataFrame, base_p: pd.DataFrame, tau: float = TAU) -> dict:
    m = arm_p.merge(base_p, on=["symbol", "close_ts"], suffixes=("_a", "_b"))
    if m.empty:
        return {"n_shared_rows": 0}
    sa = np.maximum(m.p_long_a, m.p_short_a) > tau
    sb = np.maximum(m.p_long_b, m.p_short_b) > tau
    both = sa & sb
    side_a = np.where(m.p_long_a >= m.p_short_a, 1, -1)
    side_b = np.where(m.p_long_b >= m.p_short_b, 1, -1)
    return {"n_shared_rows": int(len(m)), "signal_rate_arm": float(sa.mean()), "signal_rate_1h": float(sb.mean()),
            "jaccard_signals": float(both.sum() / max(1, (sa | sb).sum())), "side_agreement_when_both": float((side_a[both] == side_b[both]).mean()) if both.any() else None}


# ----------------------------------------------------------------------------------------------- unit run
def universe() -> list[str]:
    return E.universe()


def per_tau_table(wf: dict, var: str) -> dict:
    tab = {}
    for tau in E.TAU_GRID:
        sts = [stats_or_empty(trades_frame(wf, sd, var, tau)) for sd in SEEDS]
        ms = [s["mean"] for s in sts if s["mean"] is not None]
        tab[str(tau)] = {"n": [s["n"] for s in sts], "mean_net_by_seed": [s["mean"] for s in sts], "mean_gross": sts[0]["gross"], "mean_cost": sts[0]["cost"],
                         "seed_range": float(max(ms) - min(ms)) if len(ms) == len(sts) else None}
    return tab


def run_unit(unit: str, out: Path, cache: Path, n_jobs: int, smoke: bool) -> dict:
    tf, scaling = UNITS[unit]
    syms = universe()[:6] if smoke else universe()
    first = "2021-01" if smoke else "2020-07"
    started = time.time()
    arms = [("1h", "bar")] if tf == "1h" else [("1h", "bar"), (tf, scaling)]
    wfs, pop, rows = {}, {}, {}
    for t, sc in arms:
        fr = fetch_all(cache, syms, t, first=first)
        sp = spec(t, sc)
        tab = build_table(cache, syms, sp, drop_ts_before=f"{first}-01")
        rows[f"{t}/{sc}"] = {"decision_rows": len(tab), "symbols": int(tab.symbol.nunique()), "bars_fetched": int(sum(x["rows"] for x in fr)),
                             "missing_months": int(sum(x.get("missing_months", 0) for x in fr))}
        print(unit, t, sc, rows[f"{t}/{sc}"], flush=True)
        wfs[(t, sc)] = walk_forward(tab, sp, n_jobs=n_jobs)
        pop[(t, sc)] = sp
        del tab
    base_wf, arm_wf = wfs[("1h", "bar")], wfs[(tf, scaling)]
    res = {"unit": unit, "schema": "ml_entry_timeframe/1", "read_state": "read", "timeframe": tf, "scaling": scaling, "smoke": smoke,
           "spec": pop[(tf, scaling)], "tau": TAU, "gate": {"max_cost_r": GATE_MAX_COST_R, "k_cost_x_atr": gate_k()}, "rows": rows,
           "dev_only": "no month after 2025-09 is downloaded", "folds": arm_wf["folds"], "baseline_1h_folds": base_wf["folds"]}
    for var in ("ungated", "gated"):
        b, a = arm_stats(base_wf, var), arm_stats(arm_wf, var)
        res[var] = {"arm": a, "base_1h": b, "headline": headline(b, a) if tf != "1h" else {"verdict": "base", "viable": viable(a)},
                    "per_tau_arm": per_tau_table(arm_wf, var), "per_tau_1h": per_tau_table(base_wf, var)}
    res["verdict"] = res["ungated"]["headline"]["verdict"]
    if tf == "1h":
        a = res["ungated"]["arm"]
        ok_mean = abs(float(np.mean([x["mean"] for x in a])) - REF_ROUND1["mean"]) <= REF_ROUND1["mean_tol"]
        ok_n = all(abs(x["n"] - r) <= REF_ROUND1["n_rel_tol"] * r for x, r in zip(a, REF_ROUND1["n"]))
        res["reproduces_round1"] = {"reference": REF_ROUND1, "mean_ok": bool(ok_mean), "n_ok": bool(ok_n), "got_mean": float(np.mean([x["mean"] for x in a])),
                                    "got_n": [x["n"] for x in a]}
        res["verdict"] = "reproduces" if (ok_mean and ok_n and not smoke) else ("smoke_not_judged" if smoke else "does_not_reproduce")
    res["gated_verdict"] = res["gated"]["headline"]["verdict"]
    imp_a, imp_b = importance(arm_wf), importance(base_wf)
    res["importance"] = {"arm": imp_a, "1h": imp_b, "compare": compare_importance(imp_a, imp_b) if tf != "1h" else None}
    if tf != "1h" and arm_wf["preds"] and base_wf["preds"]:
        res["overlap_vs_1h"] = overlap(pd.concat(arm_wf["preds"]), pd.concat(base_wf["preds"]))
    res["seconds_total"] = round(time.time() - started, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{unit}_result.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------------------------------------- count / ETA model
def count(dev_decision_rows_1h: int = 668_280, mean_train_frac: float = 0.5) -> dict:
    """Row-count and ETA model, no network. 668,280 = the measured 1h dev decision rows (60 frozen symbols, 2,673,122 1h bars < 2025-10-01,
    decide every 4th bar). Other arms scale with the decision cadence; fit time is INFERRED from a 1M-row random-data timing."""
    out = {}
    for tf, sc in (("1h", "bar"), ("15m", "bar"), ("15m", "clock"), ("5m", "bar"), ("5m", "clock"), ("4h", "bar"), ("4h", "clock")):
        sp = spec(tf, sc)
        rows = dev_decision_rows_1h * (4.0 * 60.0 / (sp["C"] * sp["m"]))          # 1h rows are one per 240 minutes; this arm's are one per C*m minutes
        fit_s = len(SEEDS) * 8 * 2 * (rows * mean_train_frac / 1e6) * FIT_S_PER_MROW
        out[f"{tf}/{sc}"] = {"decision_rows_est": int(rows), "fit_minutes_est": round(fit_s / 60, 1)}
    return out


# ----------------------------------------------------------------------------------------------- self-test
def _synth(n=4000, m=60, seed=3) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * (1 + np.abs(r.normal(0, 0.002, n))), np.minimum(o, c) * (1 - np.abs(r.normal(0, 0.002, n)))
    ts = pd.date_range("2022-01-01", periods=n, freq=f"{m}min", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "volume": r.uniform(50, 150, n)})


def _self_test() -> None:
    df = _synth()
    sp = spec("1h", "bar")
    # 1h reproduces ml_decision_entry exactly (labels and features), for either scaling name
    pd.testing.assert_frame_equal(label_tf(df, sp).reset_index(drop=True), E.label_symbol(df).reset_index(drop=True), check_dtype=False)
    pd.testing.assert_frame_equal(features_tf(df, sp), E.features_symbol(df), check_dtype=False)
    assert spec("1h", "clock") == {**sp, "scaling": "clock"}
    # scaling arithmetic
    s5b, s5c = spec("5m", "bar"), spec("5m", "clock")
    assert s5b["ret"] == [1, 4, 12, 24, 72, 168] and s5b["H"] == 24 and s5b["C"] == 4 and s5b["atr"] == 14
    assert s5c["ret"] == [12, 48, 144, 288, 864, 2016] and s5c["H"] == 288 and s5c["C"] == 48 and s5c["atr"] == 168
    s4c = spec("4h", "clock")
    assert s4c["ret"] == [1, 1, 3, 6, 18, 42] and s4c["H"] == 6 and s4c["C"] == 1 and s4c["atr"] == 4
    s15c = spec("15m", "clock")
    assert s15c["H"] == 96 and s15c["C"] == 16 and s15c["ret"][0] == 4
    # a 15m synthetic frame labels on the clock-aligned grid, with contiguous forward bars
    d15 = _synth(6000, 15)
    for sc in ("bar", "clock"):
        sp15 = spec("15m", sc)
        lab = label_tf(d15, sp15)
        cm = (_t_ns(d15["ts"])[lab["i"].to_numpy()] + 15 * 60_000_000_000) // 60_000_000_000
        assert (cm % (sp15["C"] * 15) == 0).all() and len(lab) > 100
        assert (lab["bars_long"] <= sp15["H"]).all() and (lab["bars_long"] >= 1).all()
    # the cost gate: refuse when k / atr_pct > 0.06
    assert gate_k() / 0.02 <= GATE_MAX_COST_R < gate_k() / 0.005
    # policy_fast == E.policy on the same rows
    r = np.random.default_rng(1)
    t = pd.DataFrame({"symbol": np.repeat(["A", "B"], 200), "i": np.tile(np.arange(200), 2), "ts": pd.date_range("2022-01-01", periods=400, freq="h", tz="UTC"),
                      "bars_long": r.integers(1, 6, 400), "bars_short": r.integers(1, 6, 400), "net_long": r.normal(0, 1, 400), "net_short": r.normal(0, 1, 400),
                      "gross_long": 0.0, "gross_short": 0.0, "cost_long": 0.0, "cost_short": 0.0, "reason_long": 0, "reason_short": 0})
    pl, ps = r.normal(0.05, 0.1, 400), r.normal(0.05, 0.1, 400)
    pd.testing.assert_frame_equal(policy_fast(t, pl, ps, 0.1).reset_index(drop=True), E.policy(t, pl, ps, 0.1).reset_index(drop=True))
    # count model: 5m bar-count is 12x the 1h rows, clock arms 1x, 4h bar 0.25x
    c = count()
    assert c["5m/bar"]["decision_rows_est"] == 12 * c["1h/bar"]["decision_rows_est"] and c["5m/clock"]["decision_rows_est"] == c["1h/bar"]["decision_rows_est"]
    assert c["4h/bar"]["decision_rows_est"] * 4 == c["1h/bar"]["decision_rows_est"] and c["15m/bar"]["decision_rows_est"] == 4 * c["1h/bar"]["decision_rows_est"]
    # viable / headline wording on constructed stats
    def mk(mean, n=2000, folds=None, yrs=None):
        pf = [(n, mean if folds is None else folds[k]) for k in range(8)]
        return {"n": n * 8, "mean": mean, "gross": 0.0, "cost": 0.0, "per_fold": pf, "per_year": {y: (n * 2, mean if yrs is None else yrs[i]) for i, y in enumerate(L.YEARS)}, "min_fold_n": n}
    base = [mk(0.009 + d) for d in (0.0, 0.002, 0.003)]
    assert headline(base, [mk(0.05)] * 3)["verdict"] == "beats_1h"
    assert headline(base, [mk(0.011)] * 3)["verdict"] == "viable_not_better"
    assert headline(base, [mk(-0.1)] * 3)["verdict"] == "not_viable"
    assert headline(base, [mk(0.05, n=500)] * 3)["verdict"] == "indeterminate"
    assert headline(base, [stats_or_empty(pd.DataFrame())] * 3)["verdict"] == "indeterminate"
    print("ml_entry_timeframe self-test OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["run", "count"])
    ap.add_argument("--unit")
    ap.add_argument("--out", default="/tmp/ml_tf")
    ap.add_argument("--cache")
    ap.add_argument("--n-jobs", type=int, default=4)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "count":
        print(json.dumps(count(), indent=1))
        return 0
    if a.cmd == "run":
        if a.unit not in UNITS:
            ap.error(f"--unit must be one of {sorted(UNITS)}")
        out = Path(a.out)
        res = run_unit(a.unit, out, Path(a.cache) if a.cache else out / "klines", a.n_jobs, a.smoke)
        print(json.dumps({"unit": a.unit, "verdict": res["verdict"], "gated_verdict": res["gated_verdict"]}))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
