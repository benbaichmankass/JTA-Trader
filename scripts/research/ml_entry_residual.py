#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-4654-01.yaml (runner unit); lane FRONTIER-RESEARCH; work item FRONTIER-Q-RESID-ENTRY
# wiring: research/queue/RQ-20261118-f7c1-05.yaml (`--arms raw,lrank`: D3 LambdaRank arm, ml-week-plan 2026-11-19 section 4 #1)
"""Market-residual TARGET for the served crypto ENTRY recipe (frontier scan 2026-11-11 K1; FRONTIER-Q-RESID-ENTRY).

Question: the served ENTRY replay's result flips with the market's direction (RQ-20261108-98e3-23 SIDE-DRIVER). Does training the
SAME recipe (features, LightGBM params, purge, tau) on a target with the common BTC move removed beat training it on the raw target,
when BOTH are graded on the trades they would actually take, at the actual net R (the canonical cost stack, outright, unhedged)?

Three arms, each refit at the same 13 monthly origins over the frozen v1's clean held-out year (the RQ-20261108-98e3-26 design),
each scoring the 28 days after its origin, both-sides policy at the served tau:

  RAW      targets net_long / net_short (the served recipe)                                       -- the baseline
  RESID    targets net_long - m / net_short + m, where m = beta_i,t x BTC fwd return, in the asset's R units
  PLACEBO  as RESID but the BTC fwd return is PERMUTED across timestamps (same magnitudes, wrong times)

  m = beta x (BTC close[t+H] / BTC close[t] - 1) x entry / (SL_ATR x ATR)     (the asset's own R scale)
  beta = 720-bar rolling OLS slope of the asset's hourly log return on BTC's, through bar t (point-in-time), clipped to [-1, 3]

The fwd BTC return is in the LABEL only (as every label is forward); E.purge_train's embargo covers it. BTCUSDT is excluded from all
three arms (its residual target is degenerate: beta 1). The frozen v1 is reported on the same rows for context, not graded.

Rule (registered before the run, research/queue/RQ-20261112-4654-01.yaml):
  paired windows = windows where RAW and RESID each took >= 30 decisions; d_w = RESID mean - RAW mean (net R/decision)
  PASS          iff >= 10 paired windows, mean d >= +0.06, 95% t-CI low > 0, RESID pooled n >= 300, and the PLACEBO does not pass
                (PLACEBO paired mean vs RAW < +0.06 or its CI low <= 0) and RESID pooled mean > PLACEBO pooled mean
  FAIL          iff >= 10 paired windows and (mean d <= 0 or PLACEBO paired mean >= RESID paired mean)
  INDETERMINATE otherwise (below the n floors, or 0 < mean d with the CI or the +0.06 bar not met)

    python3 scripts/research/ml_entry_residual.py run --cache DIR --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..]
    python3 scripts/research/ml_entry_residual.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402

START, END, STEP_DAYS = "2025-10-01", "2026-09-30", 28
BETA_WIN, BETA_LO, BETA_HI = 720, -1.0, 3.0
WIN_N, MIN_WINDOWS, POOL_N, DELTA = 30, 10, 300, 0.06
PLACEBO_SEED = 20261112
ARMS = ("raw", "resid", "placebo")
#: FRONTIER-Q-XSEC-RANK-ENTRY (not part of RQ-20261112-4654-01): the ranking objective in regression form -- each side's net R
#: minus its cross-sectional mean over the symbols at the same decision timestamp, so only the relative order at a time is learned.
EXTRA_ARMS = ("xsdemean", "ens", "ridge", "conf", "gross", "cb", "ens3", "lrank")
# gross (ML-PRIMARY-3, 2026-11-15; diagnosis cd01-01 R3: the net-R label is cost-driven, IC net 0.497 vs gross 0.003): the
# DECOMPOSED score. LightGBM learns GROSS R per side; the decision score subtracts the KNOWN pre-trade cost per R,
# c_hat = k_side / (SL_ATR x atr_pct), where k_side = sum(cost) / sum(1 / (SL_ATR x atr_pct)) on the refit's OWN training rows.
# Only the score changes; graded at the realised net R like every other arm. Point-in-time: atr_pct is a decision-time feature.
# ens / ridge (FRONTIER-Q-ENS-RIDGE-ENTRY): the RAW target with a different learner -- ridge alone, or the equal-weight
# average of the LightGBM and ridge predictions (a heterogeneous ensemble). They change the learner, not the target.
LEARNER_ARMS = {"ens": "raw", "ridge": "raw"}
RIDGE_ALPHA = 10.0
# cb / ens3 (FRONTIER-Q-CATBOOST-ENTRY, ML-FRONTIER-PREP-20261118): the RAW target with CatBoost (ordered boosting, a
# different tree family from LightGBM; it beat LightGBM on the D2 yz features in RQ-20261117-dc44-02), and the
# equal-weight average of LightGBM, CatBoost and ridge. They change the learner, not the target. Params are fixed, not swept.
LEARNER_ARMS.update({"cb": "raw", "ens3": "raw"})
CB_PARAMS = {"iterations": 600, "depth": 6, "learning_rate": 0.05, "loss_function": "RMSE", "l2_leaf_reg": 3.0,
             "random_seed": 0, "verbose": 0, "allow_writing_files": False}
# conf (FRONTIER-Q-CONFORMAL-ENTRY): uncertainty-normalised selection at MATCHED COVERAGE. Inside each refit's training
# rows (time order): PROPER (first 70%) fits mu_p; CAL-A (next 15%) fits sigma = E|y - mu_p|; CAL-B (last 15%) picks the
# score threshold s* so E.policy on (mu_p / sigma) takes as many decisions there as E.policy on mu_p at tau. A 25-hour gap
# (label horizon + 1) separates the slices. On the test window the score is mu_full / sigma (mu_full = the RAW fit on
# all training rows, so the arm differs from RAW only in WHICH decisions it takes). Point-in-time: nothing reads the test window.
CONF_SPLIT = (0.70, 0.85)
CONF_SIGMA_FLOOR_Q = 0.05
LEARNER_ARMS["conf"] = "raw"
TAU_ARMS = ("conf", "lrank")
# lrank (RQ-20261118-f7c1-05, ML-PRIMARY-7): a TRUE ranking loss. Per side, LightGBM lambdarank (LGB_PARAMS + objective lambdarank)
# with one query group per decision timestamp (the cross-section of perps at that bar) and the relevance = net R graded into
# the fixed integer bins LRANK_EDGES. Unlike xsdemean (4654-06: a demeaned REGRESSION target, FAILED), the loss only sees the
# ORDER inside a timestamp, so its score has no net-R scale and cannot be thresholded at tau. Coverage is therefore matched
# out of sample inside the refit's training rows (the conf slices): the ranker and a RAW LightGBM are fit on PROPER + CAL-A;
# on CAL-B, s*_side = the ranker-score quantile that admits as many rows as RAW's prediction > tau admits there; the test
# score is ranker - s*_side + tau, so E.policy's ``> tau`` means ``ranker > s*_side`` and its side choice compares margins.
# The served ranker is the PROPER + CAL-A fit (no refit on CAL-B: a refit would move the score scale). Nothing reads the test window.
LRANK_EDGES = (-0.5, 0.0, 0.5, 1.5)          # net R bins -> relevance 0..4 (fixed before any run)
LRANK_PARAMS = {"objective": "lambdarank", "metric": "ndcg"}
# ftt / tabicl (D3-TABULAR-LEARNER-ARMS, 2026-11-26; units RQ-20261118-f7c1-06 / -dbf8-02): the RAW target with a deep tabular
# learner, GPU arms run on Kaggle. They change the learner, not the target. Both are FIXED before any run (no search):
#   ftt    FT-Transformer regressor per side (Gorishniy et al. 2021): per-feature linear tokens + CLS, 3 pre-norm transformer
#          blocks (d 192, 8 heads, FFN 256, dropout 0.1), head LayerNorm-ReLU-Linear on CLS. Features: train-median impute, then a
#          train-fit QuantileTransformer (normal); target standardised on train. AdamW lr 1e-4 wd 1e-5, batch 1024, <= 30 epochs,
#          early stop on the NEWEST 10% of the refit's training rows (time order, a HORIZON_H+1 h gap before it) with patience 3,
#          restoring the best epoch. Seeded. On cuda the forward runs under fp16 autocast with loss scaling (speed only).
#   tabicl TabICLv2 regressor (tabicl==2.2.0, checkpoint tabicl-regressor-v2-20260212.ckpt, BSD-3-Clause weights) at its
#          DEFAULT settings, in-context on ALL of the refit's training rows (full n: no cap, no subsample), one fit per side.
#          The checkpoint is read from $TABICL_MODEL_DIR (shipped in the Kaggle bundle); it never downloads.
# Each fit records {status, device, ...} per side. A window where a GPU arm is not status ok on cuda (CPU fallback, error, OOM,
# truncated) is recorded, and the unit's verdict is then INDETERMINATE, never FAIL (both units' registered rules).
LEARNER_ARMS.update({"ftt": "raw", "tabicl": "raw"})
GPU_ARMS = ("ftt", "tabicl")
FTT_CFG = {"d_token": 192, "n_blocks": 3, "n_heads": 8, "d_ffn": 256, "dropout": 0.1, "lr": 1e-4, "weight_decay": 1e-5,
           "batch_size": 1024, "max_epochs": 30, "patience": 3, "val_frac": 0.10, "seed": 0}
TABICL_CKPT = "tabicl-regressor-v2-20260212.ckpt"
TABICL_PARAMS = {"random_state": 0}            # every other TabICLRegressor argument at its 2.2.0 default
# Inference-MEMORY knobs only (2026-11-26, after dbf8-02 run 45797062321 OOMed on its first window: the column-embedding output
# buffer at full n was estimated at 30,727 MB with the default batch_size 8 and no disk_offload_dir). batch_size is how many of the
# 8 ensemble members run together (the model, n_estimators and every prediction-affecting argument are unchanged); with 1 the
# buffer is ~1/8 of that. disk_offload_dir lets TabICL's offload_mode="auto" (default) fall back to memory-mapped files if CPU
# memory is still short. Neither changes what is predicted beyond float rounding.
TABICL_MEMORY = {"batch_size": 1}
TABICL_OFFLOAD_DIR_DEFAULT = "/tmp/tabicl_offload"
EXTRA_ARMS = EXTRA_ARMS + GPU_ARMS


# ----------------------------------------------------------------------------------------------- target
def market_component(tab: pd.DataFrame, cache: Path, permute: bool = False, seed: int = PLACEBO_SEED) -> np.ndarray:
    """m per row in the asset's R units. Point-in-time beta; forward BTC return (label side only)."""
    btc = pd.read_pickle(cache / "BTCUSDT.pkl").reset_index(drop=True)
    bts = pd.to_datetime(btc["ts"], utc=True)
    bc = pd.Series(btc["close"].astype(float).to_numpy(), index=bts)
    blr = np.log(bc).diff()
    fwd = bc.shift(-E.HORIZON_H) / bc - 1.0
    fwd_map = fwd.copy()
    if permute:
        vals = fwd.dropna()
        rng = np.random.default_rng(seed)
        fwd_map = pd.Series(np.nan, index=fwd.index)
        fwd_map.loc[vals.index] = rng.permutation(vals.to_numpy())
    beta_parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        s = pd.Series(df["close"].astype(float).to_numpy(), index=pd.to_datetime(df["ts"], utc=True))
        alr = np.log(s).diff()
        b = blr.reindex(alr.index)
        cov = (alr * b).rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean() - \
            alr.rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean() * b.rolling(BETA_WIN, min_periods=BETA_WIN // 2).mean()
        var = b.rolling(BETA_WIN, min_periods=BETA_WIN // 2).var(ddof=0)
        beta = (cov / var.replace(0, np.nan)).clip(BETA_LO, BETA_HI)
        beta_parts.append(pd.Series(beta.reindex(g["ts"]).to_numpy(), index=g.index))
    beta = pd.concat(beta_parts).reindex(tab.index).to_numpy()
    r_btc = fwd_map.reindex(tab["ts"]).to_numpy()
    per_r = tab["entry"].to_numpy(float) / (E.SL_ATR * tab["atr"].to_numpy(float))
    return beta * r_btc * per_r


def add_targets(tab: pd.DataFrame, cache: Path) -> pd.DataFrame:
    t = tab[tab.symbol != "BTCUSDT"].copy()
    for arm, perm in (("resid", False), ("placebo", True)):
        m = market_component(t, cache, permute=perm)
        t[f"y_long_{arm}"] = t["net_long"].to_numpy() - m
        t[f"y_short_{arm}"] = t["net_short"].to_numpy() + m
    t["y_long_raw"], t["y_short_raw"] = t["net_long"], t["net_short"]
    t["y_long_gross"], t["y_short_gross"] = t["gross_long"], t["gross_short"]
    for side in ("long", "short"):           # xsdemean: market-neutral by construction (relative order at each timestamp)
        t[f"y_{side}_xsdemean"] = t[f"net_{side}"] - t.groupby("ts")[f"net_{side}"].transform("mean")
    keep = np.isfinite(t[[f"y_{s}_{a}" for s in ("long", "short") for a in ARMS]].to_numpy()).all(axis=1)
    return t[keep].reset_index(drop=True)


def fit_arm(train: pd.DataFrame, arm: str, sample: int | None = None, tau: float | None = None) -> dict:
    import lightgbm as lgb
    if sample:
        train = train.sample(min(len(train), sample), random_state=0)
    if arm == "conf":
        return fit_conf(train, tau if tau is not None else 0.0)
    if arm == "gross":
        return fit_gross(train)
    if arm == "lrank":
        return fit_lrank(train, tau if tau is not None else 0.0)
    if arm in GPU_ARMS:
        return fit_gpu_arm(train, arm)
    target = LEARNER_ARMS.get(arm, arm)
    out = {}
    for side in ("long", "short"):
        y = train[f"y_{side}_{target}"]
        ridge = None
        if arm in LEARNER_ARMS:
            from sklearn.impute import SimpleImputer
            from sklearn.linear_model import Ridge
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            ridge = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=RIDGE_ALPHA))
            ridge.fit(train[E.FEATURES], y)
        if arm == "ridge":
            out[side] = ridge
            continue
        cb = None
        if arm in ("cb", "ens3"):
            from catboost import CatBoostRegressor
            cb = CatBoostRegressor(**CB_PARAMS)
            cb.fit(train[E.FEATURES], y)
        if arm == "cb":
            out[side] = cb
            continue
        m = lgb.LGBMRegressor(**E.LGB_PARAMS)
        m.fit(train[E.FEATURES], y)
        out[side] = _Blend(m, ridge) if arm == "ens" else (_Blend3(m, cb, ridge) if arm == "ens3" else m)
    return out


def _slices(train: pd.DataFrame) -> tuple:
    t = train.sort_values("ts")
    ts = t["ts"].sort_values().unique()
    gap = pd.Timedelta(hours=E.HORIZON_H + 1)
    c1, c2 = (pd.Timestamp(ts[int(len(ts) * q)]) for q in CONF_SPLIT)
    return (t[t.ts < c1 - gap], t[(t.ts >= c1) & (t.ts < c2 - gap)], t[t.ts >= c2])


def _match_threshold(cal: pd.DataFrame, z: dict, n_target: int, tau: float) -> float:
    """The score threshold s* at which E.policy on z takes n_target decisions on ``cal`` (bisection; count falls as s rises)."""
    lo = float(min(z["long"].min(), z["short"].min())) - 1.0
    hi = float(max(z["long"].max(), z["short"].max())) + 1.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        n = len(E.policy(cal, z["long"] - mid + tau, z["short"] - mid + tau, tau))
        lo, hi = (mid, hi) if n > n_target else (lo, mid)
    return 0.5 * (lo + hi)


def fit_conf(train: pd.DataFrame, tau: float) -> dict:
    import lightgbm as lgb
    proper, cal_a, cal_b = _slices(train)
    full = fit_arm(train, "raw")
    out, z_b, mu_b = {}, {}, {}
    sig = {}
    for side in ("long", "short"):
        y = f"y_{side}_raw"
        mp = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(proper[E.FEATURES], proper[y])
        # provenance: predict -- mu_p, the PROPER-slice regressed net R, read on CAL-A to form the absolute residual sigma learns
        res_a = (cal_a[y] - mp.predict(cal_a[E.FEATURES])).abs()
        ms = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(cal_a[E.FEATURES], res_a)
        # provenance: predict -- sigma, the regressed absolute residual of mu_p (an uncertainty scale in R), floored
        floor = max(float(np.quantile(ms.predict(cal_a[E.FEATURES]), CONF_SIGMA_FLOOR_Q)), 1e-6)
        sig[side] = (ms, floor)
        # provenance: predict -- mu_p and sigma on CAL-B, to match coverage there
        mu_b[side] = mp.predict(cal_b[E.FEATURES])
        z_b[side] = mu_b[side] / np.maximum(ms.predict(cal_b[E.FEATURES]), floor)
    n_raw = len(E.policy(cal_b, mu_b["long"], mu_b["short"], tau))
    s_star = _match_threshold(cal_b, z_b, n_raw, tau)
    for side in ("long", "short"):
        out[side] = _Normalised(full[side], *sig[side], s_star, tau)
    out["_conf"] = {"s_star": s_star, "n_cal_b_raw": n_raw, "n_rows": [len(proper), len(cal_a), len(cal_b)]}
    return out


class _Normalised:
    """mu_full / sigma shifted so E.policy's ``> tau`` test means ``mu / sigma > s*``."""

    def __init__(self, mu, sigma, floor, s_star, tau):
        self.mu, self.sigma, self.floor, self.s_star, self.tau = mu, sigma, floor, s_star, tau

    def predict(self, x):
        # provenance: predict -- the RAW booster's regressed net R over the sigma model's absolute-residual scale, shifted
        return self.mu.predict(x) / np.maximum(self.sigma.predict(x), self.floor) - self.s_star + self.tau


def lrank_relevance(y: np.ndarray) -> np.ndarray:
    """Net R -> integer relevance 0..len(LRANK_EDGES) (bins closed on the left at the fixed edges)."""
    return np.searchsorted(np.asarray(LRANK_EDGES), np.asarray(y, float), side="right").astype(int)


def fit_lrank(train: pd.DataFrame, tau: float) -> dict:
    import lightgbm as lgb
    proper, cal_a, cal_b = _slices(train)
    fit_rows = pd.concat([proper, cal_a]).sort_values(["ts", "symbol"], kind="mergesort")
    groups = fit_rows.groupby("ts", sort=False).size().to_numpy()
    out, info = {}, {"n_rows": [len(fit_rows), len(cal_b)], "n_groups": int(len(groups))}
    for side in ("long", "short"):
        y = fit_rows[f"y_{side}_raw"].to_numpy(float)
        rk = lgb.LGBMRanker(**{**E.LGB_PARAMS, **LRANK_PARAMS})
        rk.fit(fit_rows[E.FEATURES], lrank_relevance(y), group=groups)
        rw = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(fit_rows[E.FEATURES], y)
        # provenance: predict -- RAW regressed net R on CAL-B (the coverage reference) and the lambdarank score (an order, no R scale)
        n_raw = int((rw.predict(cal_b[E.FEATURES]) > tau).sum())
        sc = rk.predict(cal_b[E.FEATURES])
        if n_raw <= 0:
            s_star = float(sc.max()) + 1.0
        elif n_raw >= len(sc):
            s_star = float(sc.min()) - 1.0
        else:
            s_star = float(np.quantile(sc, 1.0 - n_raw / len(sc)))
        out[side] = _Shifted(rk, s_star, tau)
        info[f"{side}_n_cal_b_raw"], info[f"{side}_s_star"] = n_raw, s_star
    out["_lrank"] = info
    return out


class _Shifted:
    """A ranker score shifted so ``> tau`` means ``score > s_star``."""

    def __init__(self, m, s_star, tau):
        self.m, self.s_star, self.tau = m, s_star, tau

    def predict(self, x):
        # provenance: predict -- LightGBM lambdarank score of one side (an order within a timestamp, not net R), shifted to the coverage threshold
        return self.m.predict(x) - self.s_star + self.tau


def _torch_device(want: str = "auto"):
    import torch
    if want == "cpu" or (want == "auto" and not torch.cuda.is_available()):
        return torch.device("cpu")
    return torch.device("cuda")


class _FTT:
    """A fitted FT-Transformer for one side: preprocessing + network; predict() returns regressed net R."""

    def __init__(self, imp, qt, net, y_mu, y_sd, dev):
        self.imp, self.qt, self.net, self.y_mu, self.y_sd, self.dev = imp, qt, net, y_mu, y_sd, dev

    def predict(self, x):
        import torch
        z = self.qt.transform(self.imp.transform(np.asarray(x[E.FEATURES] if hasattr(x, "columns") else x, dtype=float)))
        self.net.eval()
        out = []
        with torch.no_grad():
            for a in range(0, len(z), 8192):
                out.append(self.net(torch.as_tensor(z[a:a + 8192], dtype=torch.float32, device=self.dev)).float().cpu().numpy())
        # provenance: predict -- the FT-Transformer regressed net R of one side (de-standardised), not a probability
        return (np.concatenate(out) if out else np.zeros(0)) * self.y_sd + self.y_mu


def fit_ftt(train: pd.DataFrame, y_col: str, cfg: dict | None = None, device: str = "auto") -> tuple:
    """One side's FT-Transformer at FTT_CFG (fixed). Validation = the newest val_frac of rows by ts, after a label-horizon gap."""
    import torch
    from torch import nn
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import QuantileTransformer
    c = {**FTT_CFG, **(cfg or {})}
    t = train.sort_values("ts", kind="mergesort")
    cut = t["ts"].iloc[min(len(t) - 1, int(len(t) * (1.0 - c["val_frac"])))]
    gap = pd.Timedelta(hours=E.HORIZON_H + 1)
    tr, va = t[t.ts < cut - gap], t[t.ts >= cut]
    imp = SimpleImputer(strategy="median").fit(tr[E.FEATURES].to_numpy(float))
    qt = QuantileTransformer(output_distribution="normal", n_quantiles=1000, subsample=200_000, random_state=c["seed"])
    xtr = qt.fit_transform(imp.transform(tr[E.FEATURES].to_numpy(float)))
    xva = qt.transform(imp.transform(va[E.FEATURES].to_numpy(float)))
    ytr, yva = tr[y_col].to_numpy(float), va[y_col].to_numpy(float)
    y_mu, y_sd = float(ytr.mean()), float(ytr.std() + 1e-9)
    dev = _torch_device(device)
    torch.manual_seed(c["seed"])
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(c["seed"])
    nf, d = xtr.shape[1], c["d_token"]

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.w = nn.Parameter(torch.randn(nf, d) / math.sqrt(d))
            self.b = nn.Parameter(torch.zeros(nf, d))
            self.cls = nn.Parameter(torch.randn(1, 1, d) / math.sqrt(d))
            layer = nn.TransformerEncoderLayer(d, c["n_heads"], c["d_ffn"], c["dropout"], batch_first=True, norm_first=True)
            self.enc = nn.TransformerEncoder(layer, c["n_blocks"], enable_nested_tensor=False)
            self.head = nn.Sequential(nn.LayerNorm(d), nn.ReLU(), nn.Linear(d, 1))

        def forward(self, x):
            tok = x.unsqueeze(-1) * self.w + self.b
            h = self.enc(torch.cat([self.cls.expand(len(x), -1, -1), tok], dim=1))
            return self.head(h[:, 0]).squeeze(-1)

    net = Net().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=c["lr"], weight_decay=c["weight_decay"])
    amp = dev.type == "cuda"                  # fp16 autocast + loss scaling on the GPU only (declared in FTT_CFG's comment)
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    Xt = torch.as_tensor(xtr, dtype=torch.float32)
    Yt = torch.as_tensor((ytr - y_mu) / y_sd, dtype=torch.float32)
    Xv = torch.as_tensor(xva, dtype=torch.float32, device=dev)
    Yv = torch.as_tensor((yva - y_mu) / y_sd, dtype=torch.float32, device=dev)
    g = torch.Generator().manual_seed(c["seed"])
    best, bad, ran = {"loss": float("inf"), "epoch": -1, "state": None}, 0, 0
    for ep in range(c["max_epochs"]):
        net.train()
        perm = torch.randperm(len(Xt), generator=g)
        for a in range(0, len(perm), c["batch_size"]):
            ix = perm[a:a + c["batch_size"]]
            opt.zero_grad()
            with torch.autocast(device_type=dev.type, dtype=torch.float16, enabled=amp):
                loss = nn.functional.mse_loss(net(Xt[ix].to(dev)).float(), Yt[ix].to(dev))
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
        ran = ep + 1
        net.eval()
        with torch.no_grad():
            vl = float(sum(nn.functional.mse_loss(net(Xv[a:a + 8192]), Yv[a:a + 8192], reduction="sum")
                           for a in range(0, len(Xv), 8192)) / max(1, len(Xv)))
        if vl < best["loss"] - 1e-6:
            best, bad = {"loss": vl, "epoch": ep, "state": {k: v.detach().clone() for k, v in net.state_dict().items()}}, 0
        else:
            bad += 1
            if bad >= c["patience"]:
                break
    if best["state"] is not None:
        net.load_state_dict(best["state"])
    info = {"status": "ok", "device": dev.type, "epochs_run": ran, "best_epoch": best["epoch"],
            "best_val_mse_std": round(best["loss"], 6), "n_train": int(len(tr)), "n_val": int(len(va)),
            "schedule_complete": bool(ran == c["max_epochs"] or bad >= c["patience"])}
    return _FTT(imp, qt, net, y_mu, y_sd, dev), info


class _TabICL:
    def __init__(self, m):
        self.m = m

    def predict(self, x):
        # provenance: predict -- TabICLv2 in-context regressed net R of one side, not a probability
        return np.asarray(self.m.predict(np.asarray(x[E.FEATURES] if hasattr(x, "columns") else x, dtype=np.float32)), dtype=float)


def fit_tabicl(train: pd.DataFrame, y_col: str, device: str = "auto", max_rows: int | None = None) -> tuple:
    """TabICLv2 at its defaults on ALL training rows (``max_rows`` exists for the self-test only; a capped fit is flagged)."""
    import os
    from tabicl import TabICLRegressor
    ckpt = Path(os.environ.get("TABICL_MODEL_DIR", "")) / TABICL_CKPT
    if not ckpt.is_file():
        raise FileNotFoundError(f"TabICL checkpoint not found at {ckpt} (set TABICL_MODEL_DIR; this arm never downloads)")
    t = train if not max_rows or len(train) <= max_rows else train.sort_values("ts").tail(max_rows)
    dev = _torch_device(device)
    offload_dir = os.environ.get("TABICL_OFFLOAD_DIR") or TABICL_OFFLOAD_DIR_DEFAULT
    Path(offload_dir).mkdir(parents=True, exist_ok=True)
    m = TabICLRegressor(model_path=str(ckpt), allow_auto_download=False, device=dev.type, disk_offload_dir=offload_dir,
                        **TABICL_MEMORY, **TABICL_PARAMS)
    m.fit(t[E.FEATURES].to_numpy(np.float32), t[y_col].to_numpy(float))
    return _TabICL(m), {"status": "ok", "device": dev.type, "n_train": int(len(t)), "full_n": bool(len(t) == len(train)),
                        "checkpoint": TABICL_CKPT, "batch_size": TABICL_MEMORY["batch_size"], "disk_offload_dir": offload_dir}


def _free_gpu() -> None:
    """Release cached CUDA memory after a contained GPU-arm failure so the next window starts clean (no-op without torch/cuda)."""
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001  # allow-silent: best-effort cache release; the failure itself is already recorded
        pass


def _gpu_peak_reset() -> None:
    """Reset the CUDA peak-memory counter before a GPU window (no-op without torch/cuda)."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:  # noqa: BLE001  # allow-silent: a missing counter is reported as peak_gpu_mb null
        pass


def _gpu_peak_mb() -> float | None:
    """Peak CUDA memory allocated since the last reset, in MB; None when torch/cuda is absent (never 0)."""
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 2 ** 20, 1)
    except Exception:  # noqa: BLE001  # allow-silent: None means could not look, printed as such
        pass
    return None


#: BUDGET_SAFETY x the previous GPU window's wall time must fit before the deadline, or the window is skipped (dbf8-03 run
#: 45818155714: the deadline was only checked at a window's START, so one window ran past the 290-min budget into the
#: 330-min runner timeout and the whole command landed producer_failed with nothing measured).
BUDGET_SAFETY = 1.2


def fit_gpu_arm(train: pd.DataFrame, arm: str, device: str = "auto", **kw) -> dict:
    out, info = {}, {}
    for side in ("long", "short"):
        if arm == "ftt":
            out[side], info[side] = fit_ftt(train, f"y_{side}_raw", cfg=kw.get("cfg"), device=device)
        else:
            out[side], info[side] = fit_tabicl(train, f"y_{side}_raw", device=device, max_rows=kw.get("max_rows"))
    out[f"_{arm}"] = info
    return out


def gpu_arm_complete(info: dict | None, arm: str) -> bool:
    """True iff BOTH sides ran status ok ON CUDA, to the declared schedule (ftt) / at full n (tabicl)."""
    if not info or info.get("status") == "unavailable":
        return False
    for side in ("long", "short"):
        i = info.get(side) or {}
        if i.get("status") != "ok" or i.get("device") != "cuda":
            return False
        if arm == "ftt" and not i.get("schedule_complete"):
            return False
        if arm == "tabicl" and not i.get("full_n"):
            return False
    return True


def _per_r_hat(x: pd.DataFrame) -> np.ndarray:
    """Price per R at decision time, entry / (SL_ATR x ATR) ~= 1 / (SL_ATR x atr_pct): the multiplier every bps cost scales by."""
    a = x["atr_pct"].to_numpy(float)
    return 1.0 / (E.SL_ATR * np.where(a > 0, a, np.nan))


def fit_gross(train: pd.DataFrame) -> dict:
    import lightgbm as lgb
    out, ks = {}, {}
    pr = _per_r_hat(train)
    ok = np.isfinite(pr)
    for side in ("long", "short"):
        fin = np.isfinite(train[f"y_{side}_gross"].to_numpy(float))
        m = lgb.LGBMRegressor(**E.LGB_PARAMS).fit(train.loc[fin, E.FEATURES], train.loc[fin, f"y_{side}_gross"])
        c = train[f"cost_{side}"].to_numpy(float)
        k = float(np.nansum(c[ok]) / np.nansum(pr[ok]))
        ks[side] = k
        out[side] = _GrossMinusCost(m, k)
    out["_gross"] = {"k_long": ks["long"], "k_short": ks["short"]}
    return out


class _GrossMinusCost:
    """Regressed GROSS R minus the known pre-trade cost per R (k / (SL_ATR x atr_pct)); NaN atr_pct scores -inf (never taken)."""

    def __init__(self, m, k):
        self.m, self.k = m, k

    def predict(self, x):
        # provenance: predict -- the LightGBM regressed GROSS R of one side, minus the decision-time cost per R; not a probability
        c = self.k * _per_r_hat(x)
        return np.where(np.isfinite(c), self.m.predict(x[E.FEATURES]) - c, -np.inf)


class _Blend:
    """Equal-weight average of two fitted regressors' predictions (both in net-R units of the same target)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def predict(self, x):
        # provenance: predict -- mean of the LightGBM and ridge regressed net R, not a probability
        return 0.5 * (self.a.predict(x) + self.b.predict(x))


class _Blend3:
    """Equal-weight average of three fitted regressors' predictions (all in net-R units of the same target)."""

    def __init__(self, a, b, c):
        self.a, self.b, self.c = a, b, c

    def predict(self, x):
        # provenance: predict -- mean of the LightGBM, CatBoost and ridge regressed net R, not a probability
        return (self.a.predict(x) + self.b.predict(x) + self.c.predict(x)) / 3.0


# ----------------------------------------------------------------------------------------------- statistics
def _stats(t: pd.DataFrame | None) -> dict:
    if t is None or len(t) == 0:
        return {"n": 0, "mean_net_r": None}
    se = float(t.net_r.std(ddof=1) / math.sqrt(len(t))) if len(t) > 1 else None
    by_side = {s: {"n": int((t.side == s).sum()), "mean_net_r": float(t.net_r[t.side == s].mean()) if (t.side == s).any() else None}
               for s in ("long", "short")}
    return {"n": len(t), "mean_net_r": float(t.net_r.mean()), "se": se, "by_side": by_side}


def _paired(rows: list[dict], a: str, b: str) -> dict:
    d = [r[a]["mean_net_r"] - r[b]["mean_net_r"] for r in rows
         if r[a]["n"] >= WIN_N and r[b]["n"] >= WIN_N]
    k = len(d)
    if k < 2:
        return {"k": k, "mean": float(np.mean(d)) if d else None, "sd": None, "ci95": None}
    from scipy import stats as st
    mu, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    h = float(st.t.ppf(0.975, k - 1) * sd / math.sqrt(k))
    return {"k": k, "mean": mu, "sd": sd, "ci95": [mu - h, mu + h]}


def decide(p_res: dict, p_pla: dict, pooled: dict) -> str:
    if p_res["k"] < MIN_WINDOWS or p_res["mean"] is None:
        return "INDETERMINATE"
    pla_mean = p_pla["mean"] if p_pla["mean"] is not None else -math.inf
    if p_res["mean"] <= 0 or pla_mean >= p_res["mean"]:
        return "FAIL"
    placebo_passes = (p_pla["mean"] is not None and p_pla["ci95"] is not None
                      and p_pla["mean"] >= DELTA and p_pla["ci95"][0] > 0)
    if (p_res["mean"] >= DELTA and p_res["ci95"] is not None and p_res["ci95"][0] > 0
            and pooled["resid"]["n"] >= POOL_N and not placebo_passes
            and pooled["resid"]["mean_net_r"] > (pooled["placebo"]["mean_net_r"] if pooled["placebo"]["mean_net_r"] is not None else -math.inf)):
        return "PASS"
    return "INDETERMINATE"


def decide_vs_raw(p: dict, pooled_arm: dict) -> str:
    """The RESID bar without the placebo clause, for an EXTRA_ARMS unit (its own unit registers this rule before its run):
    PASS iff >= MIN_WINDOWS paired windows, mean >= DELTA, 95% CI low > 0 and pooled n >= POOL_N; FAIL iff >= MIN_WINDOWS and
    mean <= 0; INDETERMINATE otherwise."""
    if p.get("k", 0) < MIN_WINDOWS or p.get("mean") is None:
        return "INDETERMINATE"
    if p["mean"] <= 0:
        return "FAIL"
    if p["mean"] >= DELTA and p.get("ci95") and p["ci95"][0] > 0 and (pooled_arm.get("n") or 0) >= POOL_N:
        return "PASS"
    return "INDETERMINATE"


def replay(tab: pd.DataFrame, tau: float, frozen: dict | None = None, start: str = START, end: str = END,
           step_days: int = STEP_DAYS, fit=None, arms: tuple = ARMS, deadline: float | None = None,
           max_windows: int | None = None) -> dict:
    """``deadline`` (time.time() seconds, optional): once passed, GPU arms are recorded unavailable for the remaining windows
    so the run still lands a row (INDETERMINATE by the guard below) instead of dying at the backend's wall clock. A GPU window
    is also skipped when BUDGET_SAFETY x the previous GPU window's wall time would cross the deadline. Every GPU window prints
    one FLUSHED ``WINDOW_TIMING`` line (fit / predict seconds, peak GPU MB, train / window n) so a killed run still leaves its
    per-window cost on stdout. ``max_windows`` (probe mode) stops after that many non-empty windows."""
    import time as _time
    fit = fit or fit_arm
    ts0, ts1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    rows, alls = [], {a: [] for a in tuple(arms) + ("frozen",)}
    last_gpu_s: dict[str, float] = {}
    for k in range(int((ts1 - ts0).days // step_days)):
        if max_windows is not None and len(rows) >= max_windows:
            break
        a0 = ts0 + pd.Timedelta(days=k * step_days)
        a1 = a0 + pd.Timedelta(days=step_days)
        win = tab[(tab.ts >= a0) & (tab.ts < a1)].reset_index(drop=True)
        if len(win) == 0:
            continue
        train = E.purge_train(tab[tab.ts < a0], a0)
        row = {"start": str(a0.date())}
        for arm in arms:
            if arm in GPU_ARMS and deadline is not None and _time.time() > deadline:
                row[arm] = _stats(None)
                row[f"{arm}_info"] = {"status": "unavailable", "reason": "gpu-arm wall-clock budget spent before this window"}
                alls[arm].append(None)
                continue
            if (arm in GPU_ARMS and deadline is not None and arm in last_gpu_s
                    and _time.time() + BUDGET_SAFETY * last_gpu_s[arm] > deadline):
                row[arm] = _stats(None)
                row[f"{arm}_info"] = {"status": "unavailable", "reason": (
                    f"gpu-arm budget: {BUDGET_SAFETY} x the previous window ({last_gpu_s[arm]:.0f}s) would cross the deadline")}
                alls[arm].append(None)
                print(f"WINDOW_SKIP arm={arm} start={row['start']} prev_window_s={last_gpu_s[arm]:.1f}", flush=True)
                continue
            if arm in GPU_ARMS:
                # fit AND predict are contained: TabICL is in-context, so its forward (and an OOM) happens in predict()
                # (dbf8-02 run 45797062321 crashed the whole command on a predict-time OOM before this).
                _gpu_peak_reset()
                t0 = _time.time()
                t_fit = None
                try:
                    m = fit(train, arm)
                    t_fit = _time.time() - t0
                    # provenance: predict -- regressed target of each side (policy() thresholds at tau), not a probability
                    taken = E.policy(win, m["long"].predict(win[E.FEATURES]), m["short"].predict(win[E.FEATURES]), tau)
                except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as status=unavailable; forces INDETERMINATE below
                    row[arm] = _stats(None)
                    last_gpu_s[arm] = _time.time() - t0
                    row[f"{arm}_info"] = {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:500],
                                          "timing": {"fit_s": None if t_fit is None else round(t_fit, 1),
                                                     "total_s": round(last_gpu_s[arm], 1), "peak_gpu_mb": _gpu_peak_mb(),
                                                     "n_train": int(len(train)), "n_win": int(len(win)), "failed": True}}
                    alls[arm].append(None)
                    print(f"WINDOW_TIMING arm={arm} start={row['start']} status=unavailable fit_s={t_fit} "
                          f"total_s={last_gpu_s[arm]:.1f} peak_gpu_mb={_gpu_peak_mb()} n_train={len(train)} n_win={len(win)}",
                          flush=True)
                    _free_gpu()
                    continue
                last_gpu_s[arm] = _time.time() - t0
                timing = {"fit_s": round(t_fit, 1), "predict_s": round(last_gpu_s[arm] - t_fit, 1),
                          "total_s": round(last_gpu_s[arm], 1), "peak_gpu_mb": _gpu_peak_mb(),
                          "n_train": int(len(train)), "n_win": int(len(win))}
                m.setdefault(f"_{arm}", {})
                if isinstance(m[f"_{arm}"], dict):
                    m[f"_{arm}"]["timing"] = timing
                print(f"WINDOW_TIMING arm={arm} start={row['start']} status=ok " +
                      " ".join(f"{k}={v}" for k, v in timing.items()), flush=True)
            else:
                m = fit(train, arm, tau=tau) if arm in TAU_ARMS else fit(train, arm)
                # provenance: predict -- regressed target of each side (policy() thresholds at tau), not a probability
                taken = E.policy(win, m["long"].predict(win[E.FEATURES]), m["short"].predict(win[E.FEATURES]), tau)
            row[arm] = _stats(taken)
            if "_conf" in m:                 # conf: the matched threshold and slice sizes behind this window's decisions
                row[f"{arm}_info"] = m["_conf"]
            if "_gross" in m:                # gross: the training-set cost-per-R slopes behind this window's scores
                row[f"{arm}_info"] = m["_gross"]
            if "_lrank" in m:                # lrank: the matched coverage thresholds and group counts behind this window's scores
                row[f"{arm}_info"] = m["_lrank"]
            if f"_{arm}" in m and arm in GPU_ARMS:   # ftt / tabicl: per-side status, device, schedule / full-n flags
                row[f"{arm}_info"] = m[f"_{arm}"]
            alls[arm].append(taken)
        if frozen is not None:
            # provenance: predict -- the frozen v1 booster's regressed net R of each side (policy() thresholds at tau), not a probability
            fro = E.policy(win, frozen["long"].predict(win[E.FEATURES]), frozen["short"].predict(win[E.FEATURES]), tau)
            row["frozen"] = _stats(fro)
            alls["frozen"].append(fro)
        win_btc = win.drop_duplicates("ts")
        row["btc_ret24_mean"] = float(win_btc["btc_ret24"].mean()) if "btc_ret24" in win_btc else None
        rows.append(row)
    pooled = {a: _stats(pd.concat([x for x in v if x is not None])) if any(x is not None for x in v) else _stats(None)
              for a, v in alls.items()}
    p_res = _paired(rows, "resid", "raw") if "resid" in arms else {"k": 0, "mean": None, "sd": None, "ci95": None}
    p_pla = _paired(rows, "placebo", "raw") if "placebo" in arms else {"k": 0, "mean": None, "sd": None, "ci95": None}
    extra = {a: _paired(rows, a, "raw") for a in arms if a not in ARMS}
    if "resid" in arms:
        verdict = decide(p_res, p_pla, pooled)
    else:                                    # an EXTRA_ARMS unit: the same paired bar against RAW, no placebo arm
        a0 = next(iter(extra), None)
        verdict = decide_vs_raw(extra[a0], pooled.get(a0, {})) if a0 else "INDETERMINATE"
    gpu_complete = {a: all(gpu_arm_complete(r.get(f"{a}_info"), a) for r in rows) for a in arms if a in GPU_ARMS}
    head = next((a for a in arms if a not in ARMS), None)
    if head in GPU_ARMS and not gpu_complete[head] and verdict in ("PASS", "FAIL"):
        verdict = "INDETERMINATE"           # registered: a CPU-fallback / capped / failed / truncated GPU arm is never PASS or FAIL
    return {"verdict": verdict, "gpu_arm_complete": gpu_complete, "paired_resid_vs_raw": p_res, "paired_placebo_vs_raw": p_pla,
            "paired_extra_vs_raw": extra, "arms": list(arms), "pooled": pooled,
            "windows": rows, "tau": tau, "window": {"start": start, "end": end, "step_days": step_days},
            "thresholds": {"win_n": WIN_N, "min_windows": MIN_WINDOWS, "pool_n": POOL_N, "delta": DELTA,
                           "beta_win": BETA_WIN, "beta_clip": [BETA_LO, BETA_HI], "placebo_seed": PLACEBO_SEED}}


# ----------------------------------------------------------------------------------------------- entry points
PUBLISHED_RAW = "datasets-out/market_raw/{sym}/1h/v102/data.jsonl"   # metis-market-bp2 (scripts/research/market_data_bp2.py)


def cache_from_published(cache: Path, symbols: list[str], root: Path) -> tuple[dict, list[str]]:
    """KAGGLE ROUTE (D3-TABULAR-LEARNER-ARMS): write the <SYM>.pkl cache build_table reads from the PUBLISHED Binance-vision 1h
    market_raw (same venue, same ts/open/high/low/close/volume schema as fetch_through), so the run needs no internet. A symbol
    absent from the dataset is reported and left out, never invented. Returns (report, symbols present)."""
    cache.mkdir(parents=True, exist_ok=True)
    rep, present = {}, []
    for sym in symbols:
        f = root / PUBLISHED_RAW.format(sym=sym)
        if not f.is_file():
            rep[sym] = {"rows": 0, "missing": "absent from the published dataset", "last_bar": None}
            continue
        df = pd.read_json(f, lines=True)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        df = df[df.ts >= pd.Timestamp(E.START, tz="UTC")].drop_duplicates("ts").sort_values("ts")
        df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(cache / f"{sym}.pkl")
        rep[sym] = {"rows": int(len(df)), "first_bar": str(df.ts.min()), "last_bar": str(df.ts.max()), "missing": []}
        present.append(sym)
    return rep, present


def run(a) -> int:
    import os

    import ml_entry_retrain as RT
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    syms = E.universe()
    if a.cache_source == "published":
        root = Path(os.environ.get("ML_DATA_ROOT") or "")
        if not (root / "datasets-out").is_dir():
            raise SystemExit(f"--cache-source published needs $ML_DATA_ROOT with datasets-out/ (got {str(root)!r})")
        rep, syms = cache_from_published(cache, syms, root)
        if "BTCUSDT" not in syms:
            raise SystemExit("published cache has no BTCUSDT (the market leg every feature table needs)")
    else:
        rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = add_targets(E.build_table(cache, syms), cache)
    meta, frozen = E._frozen_models(REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json")
    assert str(meta["train_end_exclusive"]) < START, "the frozen model must not have seen the replay year"
    arms = tuple(x for x in a.arms.split(",") if x)
    bad = [x for x in arms if x not in ARMS + EXTRA_ARMS]
    if bad or "raw" not in arms:
        raise SystemExit(f"--arms must include raw and only {ARMS + EXTRA_ARMS}; got {arms}")
    import time as _time
    deadline = _time.time() + 60.0 * a.gpu_arm_budget_min if a.gpu_arm_budget_min > 0 else None
    d = replay(tab, float(meta["tau"]), frozen=frozen, arms=arms, deadline=deadline,
               max_windows=a.max_windows if a.max_windows and a.max_windows > 0 else None)
    v = d["verdict"] if not a.max_windows else "INDETERMINATE"   # a probe never grades the edge rule (set below if probing)
    if a.max_windows:
        ts0, ts1 = pd.Timestamp(START, tz="UTC"), pd.Timestamp(END, tz="UTC") + pd.Timedelta(days=1)
        n_full = int((ts1 - ts0).days // STEP_DAYS)
        tim = {g: [w[f"{g}_info"]["timing"] for w in d["windows"] if isinstance(w.get(f"{g}_info"), dict)
                   and "timing" in w[f"{g}_info"]] for g in arms if g in GPU_ARMS}
        d["probe"] = {"max_windows": a.max_windows, "windows_full_run": n_full, "timings": tim,
                      "projected_full_gpu_s": {g: (round(max(x["total_s"] for x in ts) * n_full, 1) if ts else None)
                                               for g, ts in tim.items()},
                      "peak_gpu_mb": {g: (max((x["peak_gpu_mb"] or 0) for x in ts) if ts and any(x["peak_gpu_mb"] for x in ts)
                                          else None) for g, ts in tim.items()},
                      "basis": "projection = the slowest probed window x the full run's window count (later windows train on more rows, so it is a LOWER bound)"}
        g0 = next((g for g in arms if g in GPU_ARMS), None)
        proj, peak = d["probe"]["projected_full_gpu_s"].get(g0), d["probe"]["peak_gpu_mb"].get(g0)
        # FEASIBILITY verdict (the probe unit's registered rule): fits iff the projected full GPU time is within the budget AND
        # the peak GPU memory is within --probe-peak-mb; a missing timing or memory read is INDETERMINATE, never a pass.
        oom = any("out of memory" in str((w.get(f"{g0}_info") or {}).get("reason", "")).lower() for w in d["windows"])
        if oom:
            v = "FAIL"           # the probed window ran out of GPU memory: infeasible as configured
        elif proj is None or peak is None or any(x.get("failed") for x in tim.get(g0, [])):
            v = "INDETERMINATE"
        elif proj <= 60.0 * a.probe_budget_min and peak <= a.probe_peak_mb:
            v = "PASS"
        else:
            v = "FAIL"
        d["probe"].update(arm=g0, budget_s=60.0 * a.probe_budget_min, peak_cap_mb=a.probe_peak_mb, feasible=v, oom=oom)
    verdict = {"PASS": "pass", "FAIL": "fail"}.get(v, "indeterminate")
    pr = d["paired_resid_vs_raw"]
    if "resid" in arms:
        note = (f"RESID-TARGET: {v} | paired resid-raw mean {pr['mean']} over k={pr['k']} windows, ci95 {pr['ci95']} | "
                f"placebo-raw mean {d['paired_placebo_vs_raw']['mean']} | pooled n raw/resid/placebo "
                f"{d['pooled']['raw']['n']}/{d['pooled']['resid']['n']}/{d['pooled']['placebo']['n']}")
    else:
        note = ("PROBE " + json.dumps(d.get("probe", {}).get("projected_full_gpu_s")) + " | " if a.max_windows else "") + \
            f"EXTRA-ARM: {v} | " + " | ".join(f"paired {k}-raw mean {p['mean']} k={p['k']} ci95 {p['ci95']} n={d['pooled'][k]['n']}"
                                                  for k, p in d["paired_extra_vs_raw"].items())
    head_arm = "resid" if "resid" in arms else next(x for x in arms if x != "raw")
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": verdict,
           "population": (f"ml_decision_entry recipe refit at 13 monthly origins over {START}..{END} ({STEP_DAYS}-day windows), "
                          f"{tab.symbol.nunique()} symbols (BTCUSDT excluded), both-sides at served tau, canonical cost stack, outright trades"),
           "note": note, "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {**d, "latest_bar": max(x["last_bar"] for x in rep.values() if x.get("last_bar")),
                           "cache_source": a.cache_source,
                           "symbols_absent": sorted(k for k, v in rep.items() if not v.get("rows"))}, "n": d["pooled"][head_arm]["n"],
           "produced_by": {"tool": "python3 scripts/research/ml_entry_residual.py run", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(note, flush=True)
    return 0


def self_test() -> int:
    import tempfile

    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    assert "BTCUSDT" in syms, syms
    tab = add_targets(E.build_table(root, syms), root)
    assert "BTCUSDT" not in set(tab.symbol) and len(tab) > 0
    # residual and placebo differ from raw, and the placebo is a permutation of the same magnitudes
    assert not np.allclose(tab.y_long_resid, tab.y_long_raw) and not np.allclose(tab.y_long_placebo, tab.y_long_resid)
    m_res = (tab.y_long_raw - tab.y_long_resid).to_numpy()
    assert np.allclose(tab.y_short_resid - tab.y_short_raw, m_res)

    def fit(t, arm, **kw):
        return fit_arm(t, arm, sample=15000, **kw)

    start = (tab.ts.max() - pd.Timedelta(days=56)).strftime("%Y-%m-%d")
    end = (tab.ts.max() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit)
    assert d["verdict"] in ("PASS", "FAIL", "INDETERMINATE") and len(d["windows"]) >= 1
    # decide(): the branches
    pooled = {"resid": {"n": 400, "mean_net_r": 0.1}, "placebo": {"n": 400, "mean_net_r": 0.0}}
    good = {"k": 13, "mean": 0.08, "ci95": [0.02, 0.14]}
    weak_pla = {"k": 13, "mean": 0.01, "ci95": [-0.03, 0.05]}
    assert decide(good, weak_pla, pooled) == "PASS"
    assert decide({"k": 13, "mean": -0.01, "ci95": [-0.05, 0.03]}, weak_pla, pooled) == "FAIL"
    assert decide(good, {"k": 13, "mean": 0.09, "ci95": [0.03, 0.15]}, pooled) == "FAIL"
    assert decide({"k": 13, "mean": 0.04, "ci95": [-0.01, 0.09]}, weak_pla, pooled) == "INDETERMINATE"
    assert decide({"k": 8, "mean": 0.2, "ci95": [0.1, 0.3]}, weak_pla, pooled) == "INDETERMINATE"
    # xsdemean (FRONTIER-Q-XSEC-RANK-ENTRY): zero cross-sectional mean at every timestamp; an extra-arm replay uses decide_vs_raw
    g = tab.groupby("ts")["y_long_xsdemean"].mean().abs().max()
    assert g < 1e-9, g
    d2 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "xsdemean"))
    assert "xsdemean" in d2["paired_extra_vs_raw"] and d2["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    # ens / ridge (FRONTIER-Q-ENS-RIDGE-ENTRY): same raw target, different learner; the verdict is on the FIRST extra arm (ens)
    mr = fit_arm(tab, "raw", sample=15000)
    me = fit_arm(tab, "ens", sample=15000)
    mg = fit_arm(tab, "ridge", sample=15000)
    xx = tab[E.FEATURES].head(50)
    # provenance: predict -- regressed net R of the long side for the raw / ens / ridge fits (a self-test identity check)
    assert np.allclose(me["long"].predict(xx), 0.5 * (mr["long"].predict(xx) + mg["long"].predict(xx)))
    d3 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "ens", "ridge"))
    assert set(d3["paired_extra_vs_raw"]) == {"ens", "ridge"} and d3["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    # conf (FRONTIER-Q-CONFORMAL-ENTRY): slices are time-ordered and gapped, coverage on CAL-B is matched to RAW's
    pr, ca, cb = _slices(tab)
    gap = pd.Timedelta(hours=E.HORIZON_H + 1)
    assert pr.ts.max() < ca.ts.min() - gap + pd.Timedelta(hours=1) and ca.ts.max() < cb.ts.min() - gap + pd.Timedelta(hours=1)
    mc = fit_conf(tab, 0.0)
    info = mc["_conf"]
    assert info["n_cal_b_raw"] > 0 and np.isfinite(info["s_star"]), info
    d4 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "conf"))
    assert "conf" in d4["paired_extra_vs_raw"] and d4["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    assert decide_vs_raw({"k": 13, "mean": 0.08, "ci95": [0.02, 0.14]}, {"n": 400}) == "PASS"
    assert decide_vs_raw({"k": 13, "mean": -0.01, "ci95": [-0.05, 0.03]}, {"n": 400}) == "FAIL"
    assert decide_vs_raw({"k": 8, "mean": 0.2, "ci95": [0.1, 0.3]}, {"n": 400}) == "INDETERMINATE"
    # gross (ML-PRIMARY-3): the decomposed score = gross prediction minus k x per-R; k reproduces the training mean cost per R
    assert {"y_long_gross", "y_short_gross", "cost_long", "cost_short"} <= set(tab.columns)
    mgr = fit_gross(tab.sample(min(len(tab), 15000), random_state=0))
    kk = mgr["_gross"]
    assert kk["k_long"] > 0 and kk["k_short"] > 0, kk
    xg = tab.head(50)
    # provenance: predict -- the gross booster's regressed gross R (a self-test identity check of the decomposition)
    assert np.allclose(mgr["long"].predict(xg), mgr["long"].m.predict(xg[E.FEATURES]) - kk["k_long"] * _per_r_hat(xg), equal_nan=True)
    d5 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "gross"))
    assert "gross" in d5["paired_extra_vs_raw"] and d5["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    # lrank (RQ-20261118-f7c1-05): fixed relevance bins; coverage on CAL-B matched to RAW's count above tau per side
    assert lrank_relevance(np.array([-2.0, -0.5, -0.1, 0.0, 0.4, 0.5, 1.0, 1.5, 3.0])).tolist() == [0, 1, 1, 2, 2, 3, 3, 4, 4]
    ml = fit_lrank(tab.sample(min(len(tab), 15000), random_state=0), 0.0)
    li = ml["_lrank"]
    assert li["n_groups"] > 1 and all(np.isfinite(li[f"{s}_s_star"]) for s in ("long", "short")), li
    xs = tab[E.FEATURES].head(50)
    # provenance: predict -- the lambdarank score of the long side, shifted (a self-test identity check of the shift)
    assert np.allclose(ml["long"].predict(xs), ml["long"].m.predict(xs) - li["long_s_star"])
    d6 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit, arms=("raw", "lrank"))
    assert "lrank" in d6["paired_extra_vs_raw"] and d6["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    assert any("lrank_info" in w for w in d6["windows"])
    # ftt / tabicl (D3-TABULAR-LEARNER-ARMS): a tiny FT-Transformer on CPU runs end to end, records its device, and the
    # registered guard turns any PASS/FAIL into INDETERMINATE because the arm did not run on cuda
    try:
        import torch  # noqa: F401
        have_torch = True
    except ImportError:
        have_torch = False
    tiny = {"d_token": 16, "n_blocks": 1, "n_heads": 2, "d_ffn": 32, "max_epochs": 2, "batch_size": 512}

    def fit_g(t, arm, **kw):
        if arm in GPU_ARMS:
            return fit_gpu_arm(t.sample(min(len(t), 4000), random_state=0), arm, device="cpu", cfg=tiny, max_rows=2000)
        return fit_arm(t, arm, sample=15000, **kw)

    if have_torch:
        mf = fit_g(tab, "ftt")
        fi = mf["_ftt"]["long"]
        assert fi["status"] == "ok" and fi["device"] == "cpu" and fi["n_val"] > 0 and fi["schedule_complete"], fi
        # provenance: predict -- the tiny FT-Transformer's regressed net R (a self-test shape check)
        pf = mf["long"].predict(tab[E.FEATURES].head(40))
        assert pf.shape == (40,) and np.isfinite(pf).all()
        assert not gpu_arm_complete(mf["_ftt"], "ftt"), "a CPU fit must never count as complete"
        d7 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_g, arms=("raw", "ftt"))
        assert d7["gpu_arm_complete"] == {"ftt": False} and d7["verdict"] == "INDETERMINATE", (d7["verdict"], d7["gpu_arm_complete"])
        assert all(w["ftt_info"]["long"]["device"] == "cpu" for w in d7["windows"])
    # tabicl with NO checkpoint: contained per window as status=unavailable, the verdict INDETERMINATE, never a crash or a FAIL
    import os
    old_dir = os.environ.pop("TABICL_MODEL_DIR", None)
    os.environ["TABICL_MODEL_DIR"] = str(root / "no-such-dir")
    d8 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_g, arms=("raw", "tabicl"))
    assert d8["verdict"] == "INDETERMINATE" and all(w["tabicl_info"]["status"] == "unavailable" for w in d8["windows"]), d8["windows"][0]
    if old_dir is not None:
        os.environ["TABICL_MODEL_DIR"] = old_dir
    else:
        os.environ.pop("TABICL_MODEL_DIR", None)
    d9 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_g, arms=("raw", "tabicl"), deadline=0.0)
    assert all("budget" in w["tabicl_info"]["reason"] for w in d9["windows"]) and d9["verdict"] == "INDETERMINATE"
    # a PREDICT-time failure (TabICL is in-context: its forward, and an OOM, run in predict) is contained per window too
    # (dbf8-02 run 45797062321 crashed the whole command on exactly this before 2026-11-26)

    class _OomAtPredict:
        def predict(self, x):  # inert: x — a stub that fails before reading its input, as the real OOM did
            raise RuntimeError("CPU memory allocation failed (CUDA error: out of memory) [self-test]")

    def fit_oom(t, arm, **kw):
        if arm in GPU_ARMS:
            return {"long": _OomAtPredict(), "short": _OomAtPredict(), f"_{arm}": {}}
        return fit_arm(t, arm, sample=15000, **kw)

    d10 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_oom, arms=("raw", "tabicl"))
    assert d10["verdict"] == "INDETERMINATE" and all(
        w["tabicl_info"]["status"] == "unavailable" and "out of memory" in w["tabicl_info"]["reason"] for w in d10["windows"])
    assert all(w["raw"] is not None for w in d10["windows"]), "the RAW arm must still be measured beside a failed GPU arm"
    # PROBE + budget-aware skip (dbf8-03 run 45818155714 timed out with no per-window record): a slow GPU window is timed and
    # printed, the next window is skipped when BUDGET_SAFETY x its time would cross the deadline, and max_windows caps the run.
    import time as _t

    class _Slow:
        def predict(self, x):
            return np.zeros(len(x))   # provenance: predict -- a zero score stub (nothing passes tau); timing-only self-test

    def fit_slow(t, arm, **kw):  # inert: t, kw — a timing stub; only the GPU arm's wall time matters here
        if arm in GPU_ARMS:
            _t.sleep(0.3)
            return {"long": _Slow(), "short": _Slow(), f"_{arm}": {}}
        return {"long": _Slow(), "short": _Slow()}    # a cheap RAW stub so only the GPU window's time counts

    d11 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_slow, arms=("raw", "tabicl"),
                 deadline=_t.time() + 0.5)
    assert d11["windows"][0]["tabicl_info"]["timing"]["fit_s"] >= 0.3, d11["windows"][0]["tabicl_info"]
    assert "previous window" in d11["windows"][1]["tabicl_info"]["reason"], d11["windows"][1]["tabicl_info"]
    d12 = replay(tab, 0.0, start=start, end=end, step_days=14, fit=fit_slow, arms=("raw", "tabicl"), max_windows=1)
    assert len(d12["windows"]) == 1 and d12["windows"][0]["tabicl_info"]["timing"]["n_win"] > 0
    i_ok = {"long": {"status": "ok", "device": "cuda", "full_n": True}, "short": {"status": "ok", "device": "cuda", "full_n": True}}
    assert gpu_arm_complete(i_ok, "tabicl") and not gpu_arm_complete({**i_ok, "short": {**i_ok["short"], "full_n": False}}, "tabicl")
    # the published-cache route writes the same pkl schema from market_raw JSONL
    pub = root / "pub"
    for sym in ("BTCUSDT", "ETHUSDT"):
        f = pub / PUBLISHED_RAW.format(sym=sym)
        f.parent.mkdir(parents=True, exist_ok=True)
        src = pd.read_pickle(root / f"{sym}.pkl")
        f.write_text("".join(json.dumps({"ts": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "open": o, "high": h, "low": lo, "close": c,
                                         "volume": v, "symbol": sym, "source": "binance_vision_um_perp_klines"}) + "\n"
                             for t, o, h, lo, c, v in zip(src.ts, src.open, src.high, src.low, src.close, src.volume)))
    rep, present = cache_from_published(root / "pcache", ["BTCUSDT", "ETHUSDT", "NOPEUSDT"], pub)
    assert present == ["BTCUSDT", "ETHUSDT"] and rep["NOPEUSDT"]["rows"] == 0, rep
    back = pd.read_pickle(root / "pcache" / "ETHUSDT.pkl")
    orig = pd.read_pickle(root / "ETHUSDT.pkl")
    orig = orig[orig.ts >= pd.Timestamp(E.START, tz="UTC")].reset_index(drop=True)
    assert list(back.columns) == ["ts", "open", "high", "low", "close", "volume"] and len(back) == len(orig)
    assert np.allclose(back.close.to_numpy(), orig.close.to_numpy()) and (back.ts.values == orig.ts.values).all()
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_residual_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-12")
    ap.add_argument("--gpu-arm-budget-min", dest="gpu_arm_budget_min", type=float, default=0.0,
                    help="wall-clock minutes after which ftt/tabicl are recorded unavailable for the remaining windows (0 = none)")
    ap.add_argument("--max-windows", dest="max_windows", type=int, default=0,
                    help="PROBE: stop after N non-empty windows; the verdict is then the FEASIBILITY rule below, never the edge rule")
    ap.add_argument("--probe-budget-min", dest="probe_budget_min", type=float, default=290.0,
                    help="PROBE: feasible iff the slowest probed window x the full window count <= this many GPU minutes")
    ap.add_argument("--probe-peak-mb", dest="probe_peak_mb", type=float, default=14500.0,
                    help="PROBE: feasible iff peak GPU memory <= this (a 16 GB T4 less headroom)")
    ap.add_argument("--cache-source", dest="cache_source", choices=("fetch", "published"), default="fetch",
                    help="fetch = data.binance.vision at run time (runner); published = $ML_DATA_ROOT metis-market-bp2 market_raw (Kaggle, no internet)")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    ap.add_argument("--arms", default=",".join(ARMS), help="comma list; default = the RQ-20261112-4654-01 arms (raw,resid,placebo). "
                    "xsdemean (FRONTIER-Q-XSEC-RANK-ENTRY), ens,ridge (FRONTIER-Q-ENS-RIDGE-ENTRY) and conf (FRONTIER-Q-CONFORMAL-ENTRY), lrank (RQ-20261118-f7c1-05) are EXTRA arms for their own units; "
                    "the verdict is on the first extra arm listed")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit:
        ap.error("run --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
