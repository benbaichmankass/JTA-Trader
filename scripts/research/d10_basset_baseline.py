#!/usr/bin/env python3
# wiring: research/queue/RQ-20261117-aadc-05.yaml (row ML-D10-BASSET-BASELINE); session-local first read over diag-relay pulls,
#         then the same command on the VM journal (--journal-db) when a VM-side run is routed
"""D10 Basset BASELINE: how well does a plain decay detector on realised net R anticipate a leg going bad, and does the blind
post-trade grade (CJ-4) do any better? (row ML-D10-BASSET-BASELINE; Tier-1 research, reads only.)

D10 (review & grading) has no model. Before any learned grade is built, the bar it must beat is set here:

  BASELINE  per leg, in closed_at order, a one-sided Page CUSUM on winsorised net R below the leg's OWN Stage-0 expectancy
            (comms/strategy_evidence/<leg>.json `expectancy_r_oos`, coverage_state measured):
                S_i = max(0, S_{i-1} + (mu0 - K - clip(R_i, -CLIP, +CLIP)))
            S_i uses trades <= i only.
  OUTCOME   decay(i) = 1 iff the mean net R of the leg's NEXT N trades (i+1 .. i+N) is < 0. Points without N future trades
            are not labelled (counted).
  SCORE     AUC of S_i for decay(i), pooled over (leg, i); 95% CI by a LEG-cluster bootstrap (legs resampled, 2000 draws).
            Also the alarm view at S_i >= H: alarm share, decay rate when alarmed vs not.
  COMPARATOR (reported, part of the rule) the blind grade: g_i = -(mean grade_score of the leg's last W graded trades <= i)
            (low grades -> higher decay score), AUC on the points where it exists. 089f-01 found grade ANTI-correlated with net R
            (rho -0.18), so the comparator's registered direction is stated before the run and not flipped after it.

Net R = net USD / initial risk USD, net USD = pnl - taker fee - maker fee - funding, initial risk = |entry - PACKAGE sl| x qty
(the package's sl is the initial stop; trades.stop_loss is mirrored from trailing amends, ml.datasets.families.claude_judgments).

    python3 scripts/research/d10_basset_baseline.py --trades 'P/trades_*.json' --packages 'P/op_*.json' --out O
    python3 scripts/research/d10_basset_baseline.py --journal-db trade_journal.db --out O
    python3 scripts/research/d10_basset_baseline.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[2]
UNIT = "RQ-20261117-aadc-05"
RULE_ID = "RULE-RQ20261117-aadc-05-D10-BASELINE"
K, CLIP, H = 0.25, 3.0, 3.0      # CUSUM slack (R), winsor (R), alarm level (R): fixed by the unit before the run
N_NEXT, W_GRADE = 20, 10
MIN_STOP_FRAC = 0.001   # a risk basis tighter than 0.1% of entry is degenerate (see degenerate_basis)
MIN_POINTS, MIN_LEGS = 200, 3
BOOT, SEED = 2000, 20261117


# ── data ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _f(v) -> Optional[float]:
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def needs_multiplier(t: dict) -> bool:
    """Futures (IB) and options legs: the journal pnl carries the contract multiplier but entry x qty does not, so R without the
    row's own contract value is inflated by the multiplier (MEASURED 2026-11-17 on the first aadc-06 read: mgc_trend_1h +2,550 R
    over 18 trades, mhg_pullback_1d -1,052 R over 5). Such a row is uncomputable unless it carries contract_value(_usd)."""
    acct = str(t.get("account_id") or "")
    return acct.startswith("ib") or "option" in acct


def contract_value(t: dict) -> Optional[float]:
    for k in ("contract_value_usd", "contract_value"):
        v = _f(t.get(k))
        if v is not None and v > 0:
            return v
    return None if needs_multiplier(t) else 1.0


def degenerate_basis(t: dict) -> bool:
    """MEASURED 2026-11-17 (second read of aadc-05/-06): on some closed rows order_packages.sl equals the AMENDED stop (moved to
    ~breakeven), e.g. trade 6168 entry 10.541, package sl 10.542163, so |entry - sl| / entry ~ 1e-4 and net R reaches +1,475 R.
    The package sl is therefore not always the initial stop; such a row has no usable initial-risk basis."""
    e, sl = _f(t.get("entry_price")), _f(t.get("pkg_sl"))
    return e is not None and sl is not None and e > 0 and abs(e - sl) / e < MIN_STOP_FRAC


def net_r(t: dict, pkg_sl: Optional[float]) -> Optional[float]:
    pnl, e, q = _f(t.get("pnl")), _f(t.get("entry_price")), _f(t.get("position_size"))
    cv = contract_value(t)
    if pnl is None or e is None or q is None or pkg_sl is None or cv is None:
        return None
    risk = abs(e - pkg_sl) * abs(q) * cv
    if risk <= 0:
        return None
    net = pnl - (_f(t.get("fee_taker_usd")) or 0.0) - (_f(t.get("fee_maker_usd")) or 0.0) - (_f(t.get("funding_paid_usd")) or 0.0)
    return net / risk


def load_pages(trades_glob: str, packages_glob: str) -> List[dict]:
    T: Dict[int, dict] = {}
    for f in sorted(glob.glob(trades_glob)):
        for t in json.loads(Path(f).read_text()):
            T[int(t["id"])] = t
    P: Dict[str, dict] = {}
    for f in sorted(glob.glob(packages_glob)):
        for p in json.loads(Path(f).read_text()):
            P[str(p["order_package_id"])] = p
    out = []
    for t in T.values():
        p = P.get(str(t.get("order_package_id") or ""))
        out.append({**t, "pkg_sl": _f(p.get("sl")) if p else None, "pkg_entry": _f(p.get("entry")) if p else None,
                    "pkg_direction": p.get("direction") if p else None, "pkg_meta": p.get("meta") if p else None})
    return out


def load_db(db: Path) -> List[dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT t.*, op.sl AS pkg_sl, op.entry AS pkg_entry, op.direction AS pkg_direction, op.meta AS pkg_meta "
                            "FROM trades t LEFT JOIN order_packages op "
                            "ON op.order_package_id = t.order_package_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stage0(evidence_dir: Path) -> Dict[str, float]:
    out = {}
    for f in evidence_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if d.get("coverage_state") == "measured" and _f(d.get("expectancy_r_oos")) is not None:
            out[f.stem] = float(d["expectancy_r_oos"])
    return out


def _vol_tag(meta) -> Optional[float]:
    """The live vol regime the package was routed under (1 volatile, 0 calm/normal), read from order_packages.meta (top level
    or one level down, e.g. a regime-gate block); None when the package recorded none. Never imputed."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            return None
    if not isinstance(meta, dict):
        return None
    cands = [meta] + [v for v in meta.values() if isinstance(v, dict)]
    for d in cands:
        for k in ("vol_regime", "vol_regime_ml", "vol_regime_frozen"):
            v = str(d.get(k) or "").lower()
            if v == "volatile":
                return 1.0
            if v in ("calm", "normal", "low", "range"):
                return 0.0
    return None


def entry_info(t: dict) -> dict:
    """Per-trade NEW-INFORMATION inputs (RQ-20261119-a10d-03), all known by the trade's close (and most at its entry):
    risk_pct = |fill - package stop| / fill (the stop distance is ATR-scaled on most legs, so it reads the volatility regime
    at entry); cost_r = (fees + funding) / initial risk; slip_r = adverse entry slippage (fill vs package entry) / initial
    risk; vol_tag = the live vol regime the package was routed under. None where the journal does not carry the input."""
    e, sl, q, cv = _f(t.get("entry_price")), _f(t.get("pkg_sl")), _f(t.get("position_size")), contract_value(t)
    out = {"risk_pct": None, "cost_r": None, "slip_r": None, "vol_tag": _vol_tag(t.get("pkg_meta"))}
    if e is None or sl is None or e <= 0:
        return out
    out["risk_pct"] = abs(e - sl) / e
    risk = abs(e - sl) * abs(q) * cv if (q is not None and cv is not None) else None
    if risk and risk > 0:
        cost = (_f(t.get("fee_taker_usd")) or 0.0) + (_f(t.get("fee_maker_usd")) or 0.0) + (_f(t.get("funding_paid_usd")) or 0.0)
        out["cost_r"] = cost / risk
    pe = _f(t.get("pkg_entry"))
    d = str(t.get("pkg_direction") or t.get("direction") or "").lower()
    if pe is not None and pe > 0 and abs(e - sl) > 0 and d in ("long", "short", "buy", "sell"):
        sign = 1.0 if d in ("long", "buy") else -1.0
        out["slip_r"] = sign * (e - pe) / abs(e - sl)
    return out


def leg_series(trades: List[dict], mu: Dict[str, float]) -> tuple[Dict[str, List[dict]], dict]:
    ex = {"not_closed": 0, "no_leg_record": 0, "no_contract_multiplier": 0, "degenerate_risk_basis": 0, "no_net_r": 0,
          "backtest": 0}
    by: Dict[str, List[dict]] = {}
    for t in trades:
        if t.get("is_backtest"):
            ex["backtest"] += 1
            continue
        if str(t.get("status")) != "closed" or not t.get("closed_at"):
            ex["not_closed"] += 1
            continue
        leg = str(t.get("strategy_name") or "")
        if leg not in mu:
            ex["no_leg_record"] += 1
            continue
        if contract_value(t) is None:
            ex["no_contract_multiplier"] += 1
            continue
        if degenerate_basis(t):
            ex["degenerate_risk_basis"] += 1
            continue
        r = net_r(t, t.get("pkg_sl"))
        if r is None:
            ex["no_net_r"] += 1
            continue
        # winsorised at +-CLIP everywhere (labels and action sums too, not only inside the CUSUM): per-trade R is heavy-tailed
        by.setdefault(leg, []).append({"trade_id": int(t["id"]), "closed_at": str(t["closed_at"]),
                                       "r": float(np.clip(r, -CLIP, CLIP)), "r_raw": r, **entry_info(t)})
    for v in by.values():
        v.sort(key=lambda x: (x["closed_at"], x["trade_id"]))
    return by, ex


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def cusum_path_mu(rs: List[float], mus: List[float]) -> List[float]:
    """CUSUM with a per-trade reference expectancy (RQ-20261117-aadc-09: the expectancy of the folds BEFORE each trade)."""
    s, out = 0.0, []
    for r, m in zip(rs, mus):
        s = max(0.0, s + (float(m) - K - float(np.clip(r, -CLIP, CLIP))))
        out.append(s)
    return out


def cusum_path(rs: List[float], mu0: float) -> List[float]:
    s, out = 0.0, []
    for r in rs:
        s = max(0.0, s + (mu0 - K - float(np.clip(r, -CLIP, CLIP))))
        out.append(s)
    return out


def points(by: Dict[str, List[dict]], mu: Dict[str, float], grades: Dict[int, int]) -> List[dict]:
    pts = []
    for leg, seq in by.items():
        rs = [x["r"] for x in seq]
        S = cusum_path(rs, mu[leg])
        graded: List[int] = []
        for i, x in enumerate(seq):
            if x["trade_id"] in grades:
                graded.append(grades[x["trade_id"]])
            if i + N_NEXT >= len(seq):
                continue
            fut = float(np.mean(rs[i + 1:i + 1 + N_NEXT]))
            g = -float(np.mean(graded[-W_GRADE:])) if graded else None
            pts.append({"leg": leg, "i": i, "cusum": S[i], "grade_score_signal": g, "decay": int(fut < 0)})
    return pts


def auc(score: np.ndarray, y: np.ndarray) -> Optional[float]:
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return None
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort().astype(float) + 1
    # average ranks for ties
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / cnt)[inv]
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def leg_boot(pts: List[dict], key: str) -> dict:
    sel = [p for p in pts if p[key] is not None]
    legs = sorted({p["leg"] for p in sel})
    if not sel:
        return {"n": 0, "legs": 0, "auc": None, "ci95": None}
    s, y = np.array([p[key] for p in sel], float), np.array([p["decay"] for p in sel])
    a = auc(s, y)
    by = {lg: [k for k, p in enumerate(sel) if p["leg"] == lg] for lg in legs}
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(BOOT):
        idx = np.concatenate([by[legs[j]] for j in rng.integers(0, len(legs), len(legs))])
        v = auc(s[idx], y[idx])
        if v is not None:
            bs.append(v)
    ci = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)] if bs else None
    return {"n": len(sel), "legs": len(legs), "decay_rate": round(float(y.mean()), 4), "auc": None if a is None else round(a, 4),
            "ci95": ci}


def verdict(base: dict) -> tuple[str, str]:
    if base["n"] < MIN_POINTS or base["legs"] < MIN_LEGS or base["ci95"] is None:
        return "indeterminate", f"labelled points {base['n']} / legs {base['legs']} below {MIN_POINTS} / {MIN_LEGS}"
    if base["auc"] > 0.5 and base["ci95"][0] > 0.5:
        return "pass", f"CUSUM baseline AUC {base['auc']} (leg-cluster CI95 {base['ci95']}) > 0.5: a working decay detector"
    return "fail", f"CUSUM baseline AUC {base['auc']} (CI95 {base['ci95']}) does not clear 0.5: no baseline skill"



# ── LEARNED degradation score (RQ-20261118-aadc-14): does a GBM on past-only leg stats beat the CUSUM baseline? ──────
LEARNED_UNIT = "RQ-20261118-aadc-14"
LEARNED_RULE_ID = "RULE-RQ20261118-aadc-14-D10-LEARNED"
LEARNED_BAR = 0.654          # aadc-05's CUSUM AUC, the standing bar (manager / week plan 2026-11-18)
LEARNED_FEATURES = ["cusum", "mean5", "mean10", "mean20", "std10", "win10", "dd", "gap_mu", "n_seen", "mu"]
N_GROUP_FOLDS = 5


def learned_points(by: Dict[str, List[dict]], mu: Dict[str, float]) -> List[dict]:
    """One point per (leg, trade i) with N_NEXT later trades, as points(): every feature uses trades 0..i only."""
    pts = []
    for leg, seq in by.items():
        rs = [x["r"] for x in seq]
        S = cusum_path(rs, mu[leg])
        cum = np.cumsum(rs)
        peak = np.maximum.accumulate(cum)
        for i in range(len(seq)):
            if i + N_NEXT >= len(seq):
                continue
            past = np.array(rs[:i + 1], float)
            def m(k):
                return float(past[-k:].mean())
            pts.append({"leg": leg, "i": i, "cusum": S[i], "mean5": m(5), "mean10": m(10), "mean20": m(20),
                        "std10": float(past[-10:].std()) if len(past) > 1 else 0.0, "win10": float((past[-10:] > 0).mean()),
                        "dd": float(peak[i] - cum[i]), "gap_mu": float(m(20) - mu[leg]), "n_seen": float(i + 1),
                        "mu": float(mu[leg]), "decay": int(float(np.mean(rs[i + 1:i + 1 + N_NEXT])) < 0)})
    return pts


def learned_oof(pts: List[dict], seed: int = SEED, features: Optional[List[str]] = None) -> np.ndarray:
    """Out-of-fold P(decay): legs are split into N_GROUP_FOLDS groups, so no leg's own points train its score."""
    import lightgbm as lgb
    legs = sorted({p["leg"] for p in pts})
    rng = np.random.default_rng(seed)
    order = list(rng.permutation(len(legs)))
    fold_of = {legs[j]: k % N_GROUP_FOLDS for k, j in enumerate(order)}
    X = np.array([[p[f] for f in (features or LEARNED_FEATURES)] for p in pts], float)
    y = np.array([p["decay"] for p in pts], int)
    f = np.array([fold_of[p["leg"]] for p in pts])
    oof = np.full(len(pts), np.nan)
    for k in range(N_GROUP_FOLDS):
        tr, te = f != k, f == k
        if te.sum() == 0 or len(set(y[tr].tolist())) < 2:
            continue
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=40,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                                 random_state=seed, verbose=-1)
        clf.fit(X[tr], y[tr])
        # provenance: predict — P(decay) = P(mean net R of the leg's next N_NEXT trades < 0), out of fold by leg group
        oof[te] = clf.predict_proba(X[te])[:, 1]
    return oof


def paired_leg_boot(pts: List[dict], a_key: str, b_key: str) -> dict:
    """AUC(a) - AUC(b) on the SAME points, leg-cluster bootstrap (BOOT draws)."""
    sel = [p for p in pts if p.get(a_key) is not None and p.get(b_key) is not None and not np.isnan(p[a_key])]
    legs = sorted({p["leg"] for p in sel})
    if not sel:
        return {"n": 0, "legs": 0, "delta": None, "ci95": None}
    a = np.array([p[a_key] for p in sel], float)
    b = np.array([p[b_key] for p in sel], float)
    y = np.array([p["decay"] for p in sel])
    by = {lg: [k for k, p in enumerate(sel) if p["leg"] == lg] for lg in legs}
    d0 = (auc(a, y) or np.nan) - (auc(b, y) or np.nan)
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(BOOT):
        idx = np.concatenate([by[legs[j]] for j in rng.integers(0, len(legs), len(legs))])
        va, vb = auc(a[idx], y[idx]), auc(b[idx], y[idx])
        if va is not None and vb is not None:
            bs.append(va - vb)
    ci = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)] if bs else None
    return {"n": len(sel), "legs": len(legs), "delta": None if np.isnan(d0) else round(float(d0), 4), "ci95": ci}


def learned_verdict(learn: dict, base: dict, paired: dict) -> tuple[str, str]:
    if learn["n"] < MIN_POINTS or learn["legs"] < MIN_LEGS or paired["ci95"] is None or learn["auc"] is None:
        return "indeterminate", f"labelled points {learn['n']} / legs {learn['legs']} below {MIN_POINTS} / {MIN_LEGS}"
    if learn["auc"] >= LEARNED_BAR and paired["delta"] > 0 and paired["ci95"][0] > 0:
        return "pass", (f"learned AUC {learn['auc']} >= bar {LEARNED_BAR} and beats CUSUM {base['auc']} on the same points by "
                        f"{paired['delta']} (leg-cluster CI95 {paired['ci95']})")
    return "fail", (f"learned AUC {learn['auc']} (CI95 {learn['ci95']}) vs CUSUM {base['auc']}: paired delta {paired['delta']} "
                    f"CI95 {paired['ci95']} does not clear 0 with AUC >= {LEARNED_BAR}")

# ── FALSIFIER (RQ-20261118-f7c1-07): is aadc-14's below-chance AUC a leg-identity artifact of leg-grouped CV? ─────────
FALSIFY_UNIT = "RQ-20261118-f7c1-07"
FALSIFY_RULE_ID = "RULE-RQ20261118-f7c1-07-D10-LEGID-ARTIFACT"
LEG_LEVEL = ["n_seen", "mu"]          # leg-constant (mu) or leg-age (n_seen) inputs: under leg-grouped CV they identify the leg
REPRO_TOL = 0.02


def within_leg_auc(pts: List[dict], key: str) -> dict:
    """Pair-weighted mean of per-leg AUCs (legs with both classes): ranking skill INSIDE a leg, free of between-leg base rates."""
    num = den = 0.0
    legs = 0
    for lg in sorted({p["leg"] for p in pts}):
        sel = [p for p in pts if p["leg"] == lg and p.get(key) is not None and not np.isnan(p[key])]
        y = np.array([p["decay"] for p in sel])
        a = auc(np.array([p[key] for p in sel], float), y) if sel else None
        if a is None:
            continue
        w = float(y.sum() * (len(y) - y.sum()))
        num, den, legs = num + a * w, den + w, legs + 1
    return {"auc": round(num / den, 4) if den else None, "legs": legs, "pairs": int(den)}


def falsify_verdict(full: dict, drop: dict, wl_full: dict, ref_auc: float) -> tuple[str, str]:
    if drop["n"] < MIN_POINTS or drop["legs"] < MIN_LEGS or drop["ci95"] is None or full["auc"] is None:
        return "indeterminate", f"labelled points {drop['n']} / legs {drop['legs']} below {MIN_POINTS} / {MIN_LEGS}"
    if abs(full["auc"] - ref_auc) > REPRO_TOL:
        return "indeterminate", f"full-feature arm AUC {full['auc']} does not reproduce aadc-14's {ref_auc} within {REPRO_TOL}"
    if drop["auc"] >= 0.5 and (wl_full["auc"] or 0) >= 0.5:
        return "pass", (f"artifact SUPPORTED: without {LEG_LEVEL} pooled AUC {drop['auc']} (CI95 {drop['ci95']}) >= 0.5 and the full "
                        f"arm's within-leg AUC {wl_full['auc']} >= 0.5 while its pooled AUC is {full['auc']}")
    if drop["ci95"][1] < 0.5:
        return "fail", f"artifact REFUTED: without {LEG_LEVEL} pooled AUC {drop['auc']} CI95 {drop['ci95']} is still below 0.5"
    return "indeterminate", (f"neither: drop-arm AUC {drop['auc']} CI95 {drop['ci95']}, full-arm within-leg AUC {wl_full['auc']}")


# ── NULL CALIBRATION (PI-20261119-JX6BUNMV-0001, the f7c1-07 harness audit) ─────────────────────────────────────────
# AUDIT FINDING (ML-PRIMARY-9, 2026-11-19). The below-chance learned AUC of aadc-14 / f7c1-07 is NOT a leak in learned_points
# or learned_oof: features read trades 0..i, the label reads i+1..i+N_NEXT, folds are by leg group (self-tests below). It is
# that 0.5 is the wrong null for this design, for two measured reasons (iid synthetic legs, no signal at all, 24 legs of
# 21 + geometric(mean 28) trades like aadc-14's 670 points / 24 legs, 20 seeds, through these exact functions):
#   1. WITHIN-LEG, a short realised series splits a fixed total between the past window and the next-N window, so any
#      "bad recent R -> decay" score ranks BELOW chance with no signal: within-leg AUC -mean20 0.364, CUSUM 0.373.
#   2. POOLED out-of-fold by leg group, a fold whose legs decay more is scored by a model fitted on legs that decay less
#      (base-rate anti-learning): learned pooled AUC 0.461-0.477 with no signal. With leg means that differ (sd 0.3 R) but
#      no change over time, the CUSUM pooled AUC is 0.706, so a pooled AUC above 0.5 also reads "this leg is persistently
#      below its Stage-0 expectancy", not "this leg is turning".
# So every D10 AUC is graded against the ORDER NULL below: each leg's trades are shuffled (same legs, lengths, trade set and
# mean; only the order is destroyed), points and scores are rebuilt, and the read is observed minus the null mean, with
# p = share of null draws >= observed. A learned score refits on every null draw.
NULL_DRAWS_CUSUM, NULL_DRAWS_LEARNED = 200, 40
NULL_UNIT = "RQ-20261119-b9d0-01"
NULL_RULE_ID = "RULE-RQ20261119-b9d0-01-D10-ORDER-NULL"
NULL_MIN_LEARNED_DRAWS = 30


def null_verdict(cal: dict, n: int, legs: int) -> tuple[str, str]:
    """RULE-RQ20261119-b9d0-01-D10-ORDER-NULL, as registered: INDETERMINATE if points < 200 OR legs < 3 OR fewer than 30 learned
    null draws scored; PASS if learned pooled excess > 0 AND its p < 0.05 AND it exceeds the CUSUM's pooled excess; FAIL if
    the learned pooled p >= 0.20; INDETERMINATE otherwise. Emits only result-contract verdicts (script_run.VERDICTS): the
    collector treats any other token as producer_failed and retries the run (the b9d0-01 double dispatch, 2026-11-19)."""
    lp, cp = cal["learned"]["pooled"], cal["cusum"]["pooled"]
    if n < MIN_POINTS or legs < MIN_LEGS or (lp.get("draws") or 0) < NULL_MIN_LEARNED_DRAWS or lp.get("p_one_sided") is None:
        return "indeterminate", f"points {n} / legs {legs} / learned null draws {lp.get('draws')} below {MIN_POINTS} / {MIN_LEGS} / {NULL_MIN_LEARNED_DRAWS}"
    ex, p, cex = lp["excess"], lp["p_one_sided"], cp.get("excess")
    txt = f"learned pooled excess {ex:+.4f} (p {p}) vs CUSUM {cex:+.4f} (p {cp.get('p_one_sided')})"
    if ex > 0 and p < 0.05 and cex is not None and ex > cex:
        return "pass", txt + ": the learned score ranks decay beyond the order null and beyond the CUSUM"
    if p >= 0.20:
        return "fail", txt + ": no learned skill over the order null"
    return "indeterminate", txt + ": between the bars"


def _shuffle_legs(by: Dict[str, List[dict]], rng: np.random.Generator) -> Dict[str, List[dict]]:
    out = {}
    for leg, seq in by.items():
        rs = [x["r"] for x in seq]
        perm = rng.permutation(len(rs))
        out[leg] = [{**x, "r": rs[j]} for x, j in zip(seq, perm)]
    return out


def score_points(by: Dict[str, List[dict]], mu: Dict[str, float], key: str, seed: int = SEED,
                 features: Optional[List[str]] = None) -> List[dict]:
    """learned_points with p[key] filled: key 'cusum' is the baseline itself; any other key is the out-of-fold learned score."""
    lp = learned_points(by, mu)
    if key != "cusum":
        for p, s_ in zip(lp, learned_oof(lp, seed=seed, features=features)):
            p[key] = None if np.isnan(s_) else float(s_)
    return lp


def _aucs(lp: List[dict], key: str) -> tuple[Optional[float], Optional[float]]:
    sel = [p for p in lp if p.get(key) is not None]
    if not sel:
        return None, None
    return auc(np.array([p[key] for p in sel], float), np.array([p["decay"] for p in sel])), within_leg_auc(sel, key)["auc"]


def order_null(by: Dict[str, List[dict]], mu: Dict[str, float], key: str, draws: int, seed: int = SEED,
               features: Optional[List[str]] = None) -> dict:
    """Observed pooled / within-leg AUC of `key`, the order-null mean of each, the excess and its one-sided p."""
    obs_p, obs_w = _aucs(score_points(by, mu, key, seed, features), key)
    rng = np.random.default_rng(seed + 1)
    nulls_p, nulls_w = [], []
    for d in range(draws):
        np_, nw = _aucs(score_points(_shuffle_legs(by, rng), mu, key, seed + 2 + d, features), key)
        if np_ is not None:
            nulls_p.append(np_)
        if nw is not None:
            nulls_w.append(nw)

    def side(obs, nulls):
        if obs is None or not nulls:
            return {"observed": obs, "null_mean": None, "excess": None, "p_one_sided": None, "draws": len(nulls)}
        m = float(np.mean(nulls))
        return {"observed": round(obs, 4), "null_mean": round(m, 4), "null_sd": round(float(np.std(nulls)), 4),
                "excess": round(obs - m, 4), "p_one_sided": round((1 + sum(v >= obs for v in nulls)) / (1 + len(nulls)), 4),
                "draws": len(nulls)}
    return {"key": key, "pooled": side(obs_p, nulls_p), "within_leg": side(obs_w, nulls_w)}


# ── NEW INFORMATION (RQ-20261119-a10d-03): regime at entry + cost drift, the aadc-14 / b9d0-01 fail_action lever ─────────
# aadc-14 FAILED and b9d0-01 FAILED (the learned score on recent-path statistics has no skill over the order null); both name
# the next lever as NEW INFORMATION, not a stronger learner. One factor against aadc-14's learned score on the same points,
# folds and learner: add five past-only inputs the realised-R path cannot see.
#   volreg_z   log(risk_pct_i) - median log(risk_pct) of the leg's trades 0..i-1   (the vol regime at entry vs the leg's own)
#   volreg_z5  mean volreg_z over the last 5 trades
#   vol_tag10  share of the last 10 trades routed under a volatile live vol regime (packages that recorded one; else NaN)
#   cost10     mean realised cost in R (fees + funding / initial risk) over the last 10 trades
#   cost_drift cost10 - the leg's mean cost_r over trades 0..i-10 (NaN until there is an earlier window)
#   slip10     mean adverse entry slippage in R (fill vs package entry) over the last 10 trades
# Missing inputs stay NaN (LightGBM routes them), never 0. The ORDER NULL here permutes WHOLE TRADE RECORDS (r together with
# its entry info), because a null that shuffled r alone would leave the new inputs in time order and credit them with order.
NEWINFO_UNIT = "RQ-20261119-a10d-03"
NEWINFO_RULE_ID = "RULE-RQ20261119-a10d-03-D10-NEWINFO"
NEWINFO_FEATURES = ["volreg_z", "volreg_z5", "vol_tag10", "cost10", "cost_drift", "slip10"]
NEWINFO_MIN_COVERAGE = 0.5
NEWINFO_NULL_DRAWS = 40


def _nanmean(xs) -> float:
    v = [x for x in xs if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return float(np.mean(v)) if v else float("nan")


def newinfo_points(by: Dict[str, List[dict]], mu: Dict[str, float]) -> List[dict]:
    """learned_points plus NEWINFO_FEATURES; every new input reads trades 0..i only."""
    lp = learned_points(by, mu)
    extra: Dict[tuple, dict] = {}
    for leg, seq in by.items():
        lrp = [np.log(x["risk_pct"]) if (x.get("risk_pct") or 0) > 0 else None for x in seq]
        z: List[float] = []
        for i, x in enumerate(seq):
            prior = [v for v in lrp[:i] if v is not None]
            z.append(float(lrp[i] - np.median(prior)) if (lrp[i] is not None and prior) else float("nan"))
            cost = [y.get("cost_r") for y in seq[:i + 1]]
            c10 = _nanmean(cost[-10:])
            extra[(leg, i)] = {"volreg_z": z[i], "volreg_z5": _nanmean(z[-5:]),
                               "vol_tag10": _nanmean([y.get("vol_tag") for y in seq[max(0, i - 9):i + 1]]),
                               "cost10": c10, "cost_drift": (c10 - _nanmean(cost[:-10])) if len(cost) > 10 else float("nan"),
                               "slip10": _nanmean([y.get("slip_r") for y in seq[max(0, i - 9):i + 1]])}
    for p in lp:
        p.update(extra[(p["leg"], p["i"])])
    return lp


def newinfo_coverage(pts: List[dict]) -> dict:
    n = len(pts)
    per = {f: (round(sum(not np.isnan(p[f]) for p in pts) / n, 4) if n else None) for f in NEWINFO_FEATURES}
    core = round(sum((not np.isnan(p["volreg_z"])) and (not np.isnan(p["cost10"])) for p in pts) / n, 4) if n else None
    return {"per_feature": per, "core_volreg_and_cost": core}


def _shuffle_records(by: Dict[str, List[dict]], rng: np.random.Generator) -> Dict[str, List[dict]]:
    """Order null for the new-information arm: each leg's trade RECORDS permuted (r and entry info move together)."""
    out = {}
    for leg, seq in by.items():
        perm = rng.permutation(len(seq))
        out[leg] = [{**seq[j], "trade_id": seq[k]["trade_id"], "closed_at": seq[k]["closed_at"]} for k, j in enumerate(perm)]
    return out


def newinfo_scored(by: Dict[str, List[dict]], mu: Dict[str, float], seed: int = SEED) -> List[dict]:
    lp = newinfo_points(by, mu)
    for key, feats in (("learned_base", LEARNED_FEATURES), ("learned_newinfo", LEARNED_FEATURES + NEWINFO_FEATURES)):
        for p, s_ in zip(lp, learned_oof(lp, seed=seed, features=feats)):
            p[key] = None if np.isnan(s_) else float(s_)
    return lp


def newinfo_null(by: Dict[str, List[dict]], mu: Dict[str, float], draws: int, seed: int = SEED) -> dict:
    """Pooled / within-leg AUC of the newinfo score vs its RECORD-order null (refit on every draw)."""
    obs = newinfo_scored(by, mu, seed)
    obs_p, obs_w = _aucs(obs, "learned_newinfo")
    rng = np.random.default_rng(seed + 1)
    nulls_p, nulls_w = [], []
    for d in range(draws):
        lp = newinfo_points(_shuffle_records(by, rng), mu)
        for p, s_ in zip(lp, learned_oof(lp, seed=seed + 2 + d, features=LEARNED_FEATURES + NEWINFO_FEATURES)):
            p["learned_newinfo"] = None if np.isnan(s_) else float(s_)
        a_p, a_w = _aucs(lp, "learned_newinfo")
        if a_p is not None:
            nulls_p.append(a_p)
        if a_w is not None:
            nulls_w.append(a_w)

    def side(o, nulls):
        if o is None or not nulls:
            return {"observed": o, "null_mean": None, "excess": None, "p_one_sided": None, "draws": len(nulls)}
        m = float(np.mean(nulls))
        return {"observed": round(o, 4), "null_mean": round(m, 4), "null_sd": round(float(np.std(nulls)), 4),
                "excess": round(o - m, 4), "p_one_sided": round((1 + sum(v >= o for v in nulls)) / (1 + len(nulls)), 4),
                "draws": len(nulls)}
    return {"points": obs, "pooled": side(obs_p, nulls_p), "within_leg": side(obs_w, nulls_w)}


def newinfo_verdict(n: int, legs: int, cov: dict, nul: dict, paired: dict) -> tuple[str, str]:
    """RULE-RQ20261119-a10d-03-D10-NEWINFO, as registered: INDETERMINATE if points < 200 OR legs < 3 OR core coverage < 0.5 OR
    fewer than 30 null draws scored; PASS if the newinfo pooled excess over the record-order null > 0 with p < 0.05 AND its
    within-leg excess > 0 AND the paired AUC(newinfo) - AUC(base) leg-cluster CI95 lower bound > 0; FAIL if the newinfo pooled
    p >= 0.20 OR the paired CI95 upper bound <= 0; INDETERMINATE otherwise."""
    pp, wl = nul["pooled"], nul["within_leg"]
    core = cov.get("core_volreg_and_cost") or 0.0
    if n < MIN_POINTS or legs < MIN_LEGS or core < NEWINFO_MIN_COVERAGE or (pp.get("draws") or 0) < NULL_MIN_LEARNED_DRAWS \
            or pp.get("p_one_sided") is None or paired.get("ci95") is None:
        return "indeterminate", (f"points {n} / legs {legs} / core coverage {core} / null draws {pp.get('draws')} below "
                                 f"{MIN_POINTS} / {MIN_LEGS} / {NEWINFO_MIN_COVERAGE} / {NULL_MIN_LEARNED_DRAWS}")
    txt = (f"newinfo pooled excess {pp['excess']:+.4f} (p {pp['p_one_sided']}), within-leg excess {wl.get('excess')}, "
           f"paired AUC(newinfo) - AUC(base) {paired['delta']} CI95 {paired['ci95']}")
    if pp["excess"] > 0 and pp["p_one_sided"] < 0.05 and (wl.get("excess") or 0) > 0 and paired["ci95"][0] > 0:
        return "pass", txt + ": the new information ranks decay beyond the record-order null and beyond the path-only score"
    if pp["p_one_sided"] >= 0.20 or paired["ci95"][1] <= 0:
        return "fail", txt + ": the new information adds no ranking skill"
    return "indeterminate", txt + ": between the bars"


# ── ACTION replay (RQ-20261117-aadc-06): does acting on the alarm add net R? ─────────────────────────────────────────
ACTION_UNIT = "RQ-20261117-aadc-06"
ACTION_RULE_ID = "RULE-RQ20261117-aadc-06-D10-ALARM-ACTION"
MIN_ALARMED = 50


def action_replay(by: Dict[str, List[dict]], mu: Dict[str, float], draws: int = BOOT, seed: int = SEED, h: float = H) -> dict:
    """Policy DEMOTE-ON-ALARM: trade i of a leg is NOT taken on the real-money book when the leg's CUSUM through trade i-1 is
    >= H (the alarm is known before trade i is entered). The leg keeps trading on the demo floor, so the CUSUM keeps updating on
    every trade (alarmed ones included) and the alarm clears when S falls below H. added_r = -(sum net R of the skipped trades).
    Control: per leg, skip the SAME number of trades at uniformly random positions (draws, seed); control_p = share of draws
    whose added_r >= actual (+1 smoothing). Per-leg added_r reported."""
    rng = np.random.default_rng(seed)
    skipped_r, per_leg, legs_r = [], {}, []
    split = {"onset_cum_negative": [], "onset_cum_nonnegative": []}   # RQ-20261117-aadc-07 (b): no lookahead
    for leg, seq in by.items():
        rs = np.array([x["r"] for x in seq], float)
        S = cusum_path_mu(list(rs), [x.get("mu", mu.get(leg)) for x in seq])
        alarmed = np.array([i > 0 and S[i - 1] >= h for i in range(len(rs))])
        k = int(alarmed.sum())
        legs_r.append((rs, k))
        cum = np.concatenate([[0.0], np.cumsum(rs)])        # cum[i] = leg net R of trades < i (known before trade i)
        onset_cum = None
        for i in range(len(rs)):
            if alarmed[i]:
                if i == 0 or not alarmed[i - 1]:
                    onset_cum = cum[i]
                split["onset_cum_negative" if onset_cum < 0 else "onset_cum_nonnegative"].append(float(rs[i]))
        if k:
            per_leg[leg] = {"n": len(rs), "skipped": k, "added_r": round(float(-rs[alarmed].sum()), 3)}
            skipped_r.extend(rs[alarmed].tolist())
    actual = float(-np.sum(skipped_r)) if skipped_r else 0.0
    ctrl = np.empty(draws)
    for d in range(draws):
        tot = 0.0
        for rs, k in legs_r:
            if k:
                tot -= rs[rng.choice(len(rs), k, replace=False)].sum()
        ctrl[d] = tot
    p = float((np.sum(ctrl >= actual) + 1) / (draws + 1))
    return {"n_alarmed": len(skipped_r), "legs_with_alarm": len(per_leg), "added_r": round(actual, 3),
            "mean_r_skipped": round(float(np.mean(skipped_r)), 4) if skipped_r else None,
            "control_mean_added_r": round(float(ctrl.mean()), 3), "control_p95_added_r": round(float(np.percentile(ctrl, 95)), 3),
            "control_p": round(p, 4), "legs_positive": sum(1 for v in per_leg.values() if v["added_r"] > 0), "h": h,
            "split_by_onset_cum_sign": {k2: {"n": len(v2), "added_r": round(float(-np.sum(v2)), 3),
                                             "mean_r": round(float(np.mean(v2)), 4) if v2 else None} for k2, v2 in split.items()},
            "per_leg": per_leg}


# ── fresh-window confirmation (RQ-20261117-aadc-09) ──────────────────────────────────────────────────────────────────
CONFIRM_RULE_ID = "RULE-RQ20261117-aadc-09-D10-H2-STAGE0-CONFIRM"
CONFIRM_H = 2.0
STAGE0_BEFORE = "2026-05-01"


def stage0_series(evidence_dir: Path, before: str) -> tuple[Dict[str, List[dict]], dict]:
    """Per leg: its Stage-0 OOS trades (source_run) entered before `before`, in entry order, each carrying mu = mean net R of the
    leg's trades in folds that ENDED before this trade's fold started (fold_detail start/end). Trades in a leg's first fold, or with
    no earlier fold trades, are not scored (counted). Net R is winsorised at +-CLIP like the live series."""
    by: Dict[str, List[dict]] = {}
    info = {"legs_with_series": 0, "trades_read": 0, "trades_after_cutoff": 0, "trades_no_prior_fold": 0, "trades_used": 0}
    for f in sorted(evidence_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        src = d.get("source_run")
        folds = d.get("fold_detail") or []
        if d.get("coverage_state") != "measured" or not src or not (REPO / src).exists() or not folds:
            continue
        info["legs_with_series"] += 1
        bounds = sorted((str(fd.get("start")), str(fd.get("end"))) for fd in folds if fd.get("start") and fd.get("end"))
        rows = []
        for line in (REPO / src).read_text().splitlines():
            if line.strip():
                t = json.loads(line)
                if _f(t.get("net_r")) is not None and t.get("entry_time"):
                    rows.append(t)
        info["trades_read"] += len(rows)
        rows.sort(key=lambda t: str(t["entry_time"]))
        seq = []
        for t in rows:
            et = str(t["entry_time"])
            if et[:10] >= before:
                info["trades_after_cutoff"] += 1
                continue
            k = next((i for i, (a0, b0) in enumerate(bounds) if a0[:10] <= et[:10] <= b0[:10]), None)
            prior = [float(np.clip(_f(x["net_r"]), -CLIP, CLIP)) for x in rows
                     if k is not None and k > 0 and str(x["entry_time"])[:10] <= bounds[k - 1][1][:10]]
            if not prior:
                info["trades_no_prior_fold"] += 1
                continue
            seq.append({"trade_id": len(seq), "closed_at": et, "r": float(np.clip(_f(t["net_r"]), -CLIP, CLIP)),
                        "mu": float(np.mean(prior))})
        if seq:
            by[f.stem] = seq
            info["trades_used"] += len(seq)
    return by, info


# ── alarm-level sweep (RQ-20261117-aadc-07) ──────────────────────────────────────────────────────────────────────────
SWEEP_UNIT = "RQ-20261117-aadc-07"
SWEEP_RULE_ID = "RULE-RQ20261117-aadc-07-D10-ALARM-H-SWEEP"
SWEEP_H = (2.0, 4.0, 6.0)


def sweep_verdict(arms: List[dict]) -> tuple[str, str, Optional[float]]:
    """Per arm PASS iff skipped >= MIN_ALARMED AND added_r > 0 AND control_p <= 0.05 / len(arms) (Bonferroni, every arm
    counted). UNIT PASS iff any arm passes (chosen = the passing arm with the highest added_r); FAIL iff every arm has
    >= MIN_ALARMED skipped trades and none passes; INDETERMINATE otherwise."""
    bar = 0.05 / len(arms)
    measured = [a for a in arms if a["n_alarmed"] >= MIN_ALARMED]
    win = [a for a in measured if a["added_r"] > 0 and a["control_p"] <= bar]
    if win:
        best = max(win, key=lambda a: a["added_r"])
        return "pass", f"H {best['h']} adds {best['added_r']:+.2f} R, control_p {best['control_p']} <= {bar:.4f}", best["h"]
    if len(measured) == len(arms):
        return "fail", "no arm: " + "; ".join(f"H {a['h']} {a['added_r']:+.1f} R p {a['control_p']}" for a in arms) + \
            f" (bar {bar:.4f})", None
    return "indeterminate", "an arm has < %d skipped trades" % MIN_ALARMED, None


def action_verdict(r: dict) -> tuple[str, str]:
    if r["n_alarmed"] < MIN_ALARMED:
        return "indeterminate", f"alarmed trades {r['n_alarmed']} < {MIN_ALARMED}"
    if r["added_r"] > 0 and r["control_p"] <= 0.05:
        return "pass", f"demote-on-alarm adds {r['added_r']:+.2f} R over {r['n_alarmed']} skipped trades, control_p {r['control_p']}"
    return "fail", f"demote-on-alarm added_r {r['added_r']:+.2f} R, control_p {r['control_p']} (needs > 0 and <= 0.05)"


def run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.stage0_confirm:
        sby, sinfo = stage0_series(Path(a.evidence_dir), STAGE0_BEFORE)
        ar = action_replay(sby, {}, h=CONFIRM_H)
        v, why = action_verdict(ar)
        res = {"verdict": v, "read_state": "measured", "n": ar["n_alarmed"],
               "population": (f"Stage-0 OOS per-trade series (comms/strategy_evidence/<leg>.json source_run) of {len(sby)} legs, trades "
                              f"entered before {STAGE0_BEFORE} (disjoint from the aadc-05..07 window), CUSUM reference = mean net R of "
                              f"the leg's EARLIER folds; demote-on-alarm at H {CONFIRM_H}"),
               "note": why, "measurement": {"rule": CONFIRM_RULE_ID, "replay": {k2: v2 for k2, v2 in ar.items() if k2 != "per_leg"},
                                            "per_leg": ar["per_leg"], "series": sinfo, "params": {"K": K, "CLIP": CLIP, "H": CONFIRM_H}}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    trades = load_db(Path(a.journal_db)) if a.journal_db else load_pages(a.trades, a.packages)
    mu = stage0(Path(a.evidence_dir))
    grades = {}
    for line in Path(a.judgments).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if isinstance(r.get("trade_id"), int) and isinstance(r.get("grade_score"), int):
                grades[r["trade_id"]] = r["grade_score"]
    by, ex = leg_series(trades, mu)
    if a.learned:
        # the learned mode FITS LightGBM on the trainer (needs_vm_data), so it takes the trainer heavy queue like every fitting job
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            from scripts.ml._heavy_queue import take_heavy_queue
            _lock = take_heavy_queue("d10-basset-learned")   # noqa: F841 - held for the process lifetime
        except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
            print(f"WARN heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked", file=sys.stderr)
        lp = learned_points(by, mu)
        oof = learned_oof(lp)
        for p, s_ in zip(lp, oof):
            p["learned"] = None if np.isnan(s_) else float(s_)
        learn, base = leg_boot(lp, "learned"), leg_boot(lp, "cusum")
        paired = paired_leg_boot(lp, "learned", "cusum")
        v, why = learned_verdict(learn, base, paired)
        res = {"verdict": v, "read_state": "measured", "n": learn["n"],
               "population": (f"(leg, trade) points of closed live/paper trades on {len(by)} legs with a measured Stage-0 record "
                              f"(aadc-05's population and label: mean net R of the next {N_NEXT} trades < 0); learned score out of "
                              f"fold by {N_GROUP_FOLDS} leg groups"),
               "note": why, "measurement": {"rule": LEARNED_RULE_ID, "learned": learn, "cusum_same_points": base,
                                            "paired_delta_auc": paired, "bar": LEARNED_BAR, "features": LEARNED_FEATURES,
                                            "params": {"K": K, "CLIP": CLIP, "N_NEXT": N_NEXT, "folds": N_GROUP_FOLDS},
                                            "trades_in": len(trades), "excluded": ex}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    if a.falsify_legid:
        lp = learned_points(by, mu)
        drop_feats = [f for f in LEARNED_FEATURES if f not in LEG_LEVEL]
        for key, feats in (("learned_full", LEARNED_FEATURES), ("learned_drop", drop_feats)):
            for p, s_ in zip(lp, learned_oof(lp, features=feats)):
                p[key] = None if np.isnan(s_) else float(s_)
        full, drop, base = leg_boot(lp, "learned_full"), leg_boot(lp, "learned_drop"), leg_boot(lp, "cusum")
        wl = {k: within_leg_auc(lp, k) for k in ("learned_full", "learned_drop", "cusum")}
        v, why = falsify_verdict(full, drop, wl["learned_full"], 0.4137)
        res = {"verdict": v, "read_state": "measured", "n": drop["n"],
               "population": (f"aadc-14's (leg, trade) points: closed live/paper trades on {len(by)} legs with a measured Stage-0 record, "
                              f"label mean net R of the next {N_NEXT} trades < 0, out of fold by {N_GROUP_FOLDS} leg groups"),
               "note": why, "measurement": {"rule": FALSIFY_RULE_ID, "learned_full": full, "learned_drop": drop,
                                            "cusum_same_points": base, "within_leg_auc": wl, "dropped_features": LEG_LEVEL,
                                            "paired_drop_vs_cusum_reported_not_gating": paired_leg_boot(lp, "learned_drop", "cusum"),
                                            "params": {"K": K, "CLIP": CLIP, "N_NEXT": N_NEXT, "folds": N_GROUP_FOLDS, "repro_ref": 0.4137},
                                            "trades_in": len(trades), "excluded": ex}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    if a.null_calibrate:
        # RQ-20261119-b9d0-01: the order-null calibration of the CUSUM baseline and the learned score on the same points, graded
        # by that unit's registered rule (null_verdict). The learned refits on every draw, so it takes the heavy queue.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            from scripts.ml._heavy_queue import take_heavy_queue
            _lock = take_heavy_queue("d10-basset-null")   # noqa: F841 - held for the process lifetime
        except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
            print(f"WARN heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked", file=sys.stderr)
        cal = {"cusum": order_null(by, mu, "cusum", a.null_draws_cusum),
               "learned": order_null(by, mu, "learned", a.null_draws_learned)}
        n_pts = len(learned_points(by, mu))
        v, why = null_verdict(cal, n_pts, len(by))
        res = {"verdict": v, "read_state": "measured", "n": n_pts,
               "population": (f"aadc-14's (leg, trade) points: closed live/paper trades on {len(by)} legs with a measured Stage-0 "
                              f"record, label mean net R of the next {N_NEXT} trades < 0; null = each leg's trades shuffled"),
               "note": (f"{why}; order-null excess AUC (pooled / within-leg): cusum {cal['cusum']['pooled']['excess']} / "
                        f"{cal['cusum']['within_leg']['excess']}, learned {cal['learned']['pooled']['excess']} / "
                        f"{cal['learned']['within_leg']['excess']}"),
               "measurement": {"rule": NULL_RULE_ID, "calibration": cal, "features": LEARNED_FEATURES,
                               "params": {"K": K, "CLIP": CLIP, "N_NEXT": N_NEXT, "folds": N_GROUP_FOLDS},
                               "trades_in": len(trades), "excluded": ex}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": res["note"]}, indent=1))
        return 0
    if a.newinfo:
        # RQ-20261119-a10d-03: aadc-14's learned score with and without the new-information inputs, graded against the
        # record-order null. It refits on every draw, so it takes the trainer heavy queue.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            from scripts.ml._heavy_queue import take_heavy_queue
            _lock = take_heavy_queue("d10-basset-newinfo")   # noqa: F841 - held for the process lifetime
        except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
            print(f"WARN heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked", file=sys.stderr)
        nul = newinfo_null(by, mu, a.null_draws_learned)
        lp = nul.pop("points")
        cov = newinfo_coverage(lp)
        paired = paired_leg_boot(lp, "learned_newinfo", "learned_base")
        arms = {k: leg_boot(lp, k) for k in ("learned_newinfo", "learned_base", "cusum")}
        v, why = newinfo_verdict(len(lp), len(by), cov, nul, paired)
        res = {"verdict": v, "read_state": "measured", "n": len(lp),
               "population": (f"aadc-14's (leg, trade) points: closed live/paper trades on {len(by)} legs with a measured Stage-0 "
                              f"record, label mean net R of the next {N_NEXT} trades < 0, out of fold by {N_GROUP_FOLDS} leg groups; "
                              "null = each leg's trade records permuted"),
               "note": why,
               "measurement": {"rule": NEWINFO_RULE_ID, "null": nul, "paired_newinfo_minus_base": paired, "arms": arms,
                               "within_leg_auc": {k: within_leg_auc(lp, k) for k in ("learned_newinfo", "learned_base", "cusum")},
                               "coverage": cov, "features_base": LEARNED_FEATURES, "features_new": NEWINFO_FEATURES,
                               "params": {"K": K, "CLIP": CLIP, "N_NEXT": N_NEXT, "folds": N_GROUP_FOLDS},
                               "trades_in": len(trades), "excluded": ex}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        print(json.dumps({"verdict": v, "note": why, "coverage": cov}, indent=1))
        return 0
    if a.alarm_h_sweep:
        arms =[action_replay(by, mu, h=hh) for hh in SWEEP_H]
        v, why, chosen = sweep_verdict(arms)
        res = {"verdict": v, "read_state": "measured", "n": max(x["n_alarmed"] for x in arms),
               "population": (f"closed live/paper journal trades on {len(by)} legs with a measured Stage-0 record (as aadc-05/-06); "
                              f"demote-on-alarm at H in {list(SWEEP_H)}, within-leg matched-random control per arm"),
               "note": why, "measurement": {"rule": SWEEP_RULE_ID, "chosen_h": chosen, "bonferroni_bar": 0.05 / len(SWEEP_H),
                                            "arms": [{k2: v2 for k2, v2 in x.items() if k2 != "per_leg"} for x in arms],
                                            "params": {"K": K, "CLIP": CLIP}, "trades_in": len(trades), "excluded": ex}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    if a.action_replay:
        ar = action_replay(by, mu)
        v, why = action_verdict(ar)
        res = {"verdict": v, "read_state": "measured", "n": ar["n_alarmed"],
               "population": (f"closed live/paper journal trades on {len(by)} legs with a measured Stage-0 record, net R on the package "
                              "initial stop, in closed_at order; skipped = trades entered while the leg's CUSUM through the previous "
                              f"trade was >= {H}"),
               "note": why, "measurement": {"rule": ACTION_RULE_ID, "replay": ar, "params": {"K": K, "CLIP": CLIP, "H": H},
                                            "trades_in": len(trades), "excluded": ex, "stage0_records": len(mu)}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    pts = points(by, mu, grades)
    base, comp = leg_boot(pts, "cusum"), leg_boot(pts, "grade_score_signal")
    al = [p for p in pts if p["cusum"] >= H]
    na = [p for p in pts if p["cusum"] < H]
    alarm = {"h": H, "alarm_share": round(len(al) / len(pts), 4) if pts else None,
             "decay_rate_alarmed": round(float(np.mean([p["decay"] for p in al])), 4) if al else None,
             "decay_rate_not_alarmed": round(float(np.mean([p["decay"] for p in na])), 4) if na else None}
    v, why = verdict(base)
    res = {"verdict": v, "read_state": "measured", "n": base["n"],
           "population": (f"(leg, trade) points of closed live/paper trades on legs with a measured Stage-0 record, net R on the "
                          f"package initial stop, each with {N_NEXT} later trades on the same leg; {len(by)} legs"),
           "note": f"{why}; comparator (blind grade, low = decay) AUC {comp['auc']} CI95 {comp['ci95']} on n {comp['n']}",
           "measurement": {"rule": RULE_ID, "baseline_cusum": base, "comparator_blind_grade": comp, "alarm": alarm,
                           "params": {"K": K, "CLIP": CLIP, "H": H, "N_NEXT": N_NEXT, "W_GRADE": W_GRADE},
                           "trades_in": len(trades), "excluded": ex, "legs": {lg: len(s) for lg, s in by.items()},
                           "stage0_records": len(mu), "grades_in": len(grades)}}
    (out / "verdict.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({"verdict": v, "note": res["note"]}, indent=1))
    return 0


# ── self-test ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _self_test() -> int:
    assert cusum_path([0.5, -1.0, -1.0, 2.0], 0.25) == [0.0, 1.0, 2.0, 0.0]
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2, "fee_taker_usd": 1, "fee_maker_usd": 0,
                  "funding_paid_usd": 1}, 95.0) == 0.8
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2}, None) is None
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2, "account_id": "ib_paper"}, 95.0) is None
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2, "account_id": "ib_paper", "contract_value": 10}, 95.0) == 0.1
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2, "account_id": "alpaca_options_paper"}, 95.0) is None
    assert degenerate_basis({"entry_price": 10.541, "pkg_sl": 10.542163}) and not degenerate_basis({"entry_price": 100, "pkg_sl": 98})
    assert auc(np.array([1, 2, 3, 4.0]), np.array([0, 0, 1, 1])) == 1.0
    assert auc(np.array([1, 1, 1, 1.0]), np.array([0, 1, 0, 1])) == 0.5
    # synthetic: legs that turn bad mid-series -> CUSUM must detect (AUC > 0.5); a grade unrelated to decay ~0.5
    rng = np.random.default_rng(3)
    by, mu, grades = {}, {}, {}
    tid = 0
    for k in range(6):
        leg = f"L{k}"
        mu[leg] = 0.2
        seq = []
        for i in range(120):
            bad = i >= 60 and k % 2 == 0
            seq.append({"trade_id": tid, "closed_at": f"2026-01-01T{i:04d}", "r": float(rng.normal(-0.6 if bad else 0.3, 1.0))})
            grades[tid] = int(rng.integers(0, 5))
            tid += 1
        by[leg] = seq
    pts = points(by, mu, grades)
    b, c = leg_boot(pts, "cusum"), leg_boot(pts, "grade_score_signal")
    assert b["auc"] > 0.6 and b["legs"] == 6, b
    assert abs(c["auc"] - 0.5) < 0.1, c
    assert verdict({"n": 50, "legs": 6, "auc": 0.7, "ci95": [0.6, 0.8]})[0] == "indeterminate"
    assert verdict({"n": 500, "legs": 6, "auc": 0.7, "ci95": [0.6, 0.8]})[0] == "pass"
    assert verdict({"n": 500, "legs": 6, "auc": 0.55, "ci95": [0.45, 0.65]})[0] == "fail"
    by2, ex = leg_series([{"id": 1, "status": "open"}, {"id": 2, "status": "closed", "closed_at": "x", "strategy_name": "nope"}], mu)
    assert ex["not_closed"] == 1 and ex["no_leg_record"] == 1 and not by2
    # action replay: a leg that turns bad -> skipping alarmed trades adds R and beats random skips
    ar = action_replay(by, mu, draws=300)
    assert ar["n_alarmed"] > 0 and ar["added_r"] > 0 and ar["control_p"] < 0.05, ar
    assert action_verdict({"n_alarmed": 10, "added_r": 5, "control_p": 0.01})[0] == "indeterminate"
    assert action_verdict({"n_alarmed": 80, "added_r": 5, "control_p": 0.2})[0] == "fail"
    # the alarm uses S through trade i-1 only: a single huge loss at the last trade is never itself skipped
    one = {"L": [{"trade_id": 0, "closed_at": "a", "r": 0.3}, {"trade_id": 1, "closed_at": "b", "r": -3.0}]}
    assert action_replay(one, {"L": 0.2}, draws=10)["n_alarmed"] == 0
    arms = [action_replay(by, mu, draws=200, h=hh) for hh in SWEEP_H]
    assert [x["h"] for x in arms] == list(SWEEP_H) and all("split_by_onset_cum_sign" in x for x in arms)
    sp = arms[0]["split_by_onset_cum_sign"]
    assert sp["onset_cum_negative"]["n"] + sp["onset_cum_nonnegative"]["n"] == arms[0]["n_alarmed"]
    assert sweep_verdict([{"h": 2, "n_alarmed": 80, "added_r": 5, "control_p": 0.02},
                          {"h": 4, "n_alarmed": 80, "added_r": 5, "control_p": 0.01},
                          {"h": 6, "n_alarmed": 80, "added_r": 1, "control_p": 0.5}])[2] == 4
    assert sweep_verdict([{"h": 2, "n_alarmed": 80, "added_r": 5, "control_p": 0.02}] * 3)[0] == "fail"
    assert sweep_verdict([{"h": 2, "n_alarmed": 10, "added_r": 5, "control_p": 0.5}] * 3)[0] == "indeterminate"
    assert cusum_path_mu([0.5, -1.0, -1.0, 2.0], [0.25] * 4) == cusum_path([0.5, -1.0, -1.0, 2.0], 0.25)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ev = Path(td)
        src = ev / "_selftest_leg__trades.jsonl"
        lines = [{"entry_time": f"2026-0{m}-15 00:00:00+00:00", "net_r": r} for m, r in ((1, 1.0), (2, -1.0), (3, 0.5), (6, 2.0))]
        src.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        (ev / "L.json").write_text(json.dumps({"coverage_state": "measured", "source_run": str(src),
            "fold_detail": [{"start": "2026-01-01", "end": "2026-01-31"}, {"start": "2026-02-01", "end": "2026-02-28"},
                            {"start": "2026-03-01", "end": "2026-06-30"}]}))
        sb, si = stage0_series(ev, "2026-05-01")
        assert si["trades_after_cutoff"] == 1 and si["trades_no_prior_fold"] == 1 and si["trades_used"] == 2, si
        assert sb["L"][0]["mu"] == 1.0 and sb["L"][1]["mu"] == 0.0, sb
    # LEARNED (aadc-14): features read only trades 0..i; the paired delta is learned minus cusum on the same points
    seq = [{"trade_id": k, "closed_at": f"t{k:03d}", "r": (1.0 if k < 30 else -1.0)} for k in range(60)]
    lp = learned_points({"A": seq}, {"A": 0.2})
    assert len(lp) == 60 - N_NEXT and lp[0]["n_seen"] == 1.0 and lp[0]["mean5"] == 1.0, lp[0]
    p29 = [q for q in lp if q["i"] == 29][0]
    assert p29["mean20"] == 1.0 and p29["dd"] == 0.0, p29     # trade 30 (the first loser) is not visible at i = 29
    pts2 = [{"leg": f"L{j % 4}", "decay": j % 2, "a": float(j % 2) + 0.1, "b": 0.5} for j in range(400)]
    pr = paired_leg_boot(pts2, "a", "b")
    assert pr["delta"] == 0.5 and pr["ci95"][0] > 0, pr
    assert learned_verdict({"n": 400, "legs": 4, "auc": 0.70, "ci95": [0.6, 0.8]}, {"auc": 0.65}, pr)[0] == "pass"
    assert learned_verdict({"n": 400, "legs": 4, "auc": 0.60, "ci95": [0.5, 0.7]}, {"auc": 0.55}, pr)[0] == "fail"
    assert learned_verdict({"n": 50, "legs": 4, "auc": 0.70, "ci95": [0.6, 0.8]}, {"auc": 0.65}, pr)[0] == "indeterminate"
    # FALSIFIER (f7c1-07): within-leg AUC ignores between-leg base rates; verdict branches
    wpts = ([{"leg": "A", "decay": d, "s": v} for d, v in ((1, 0.9), (0, 0.1), (1, 0.8), (0, 0.2))]
            + [{"leg": "B", "decay": d, "s": v} for d, v in ((1, 0.4), (0, 0.3))])
    assert within_leg_auc(wpts, "s")["auc"] == 1.0 and within_leg_auc(wpts, "s")["legs"] == 2
    good = {"n": 400, "legs": 10, "auc": 0.55, "ci95": [0.45, 0.65]}
    assert falsify_verdict({"auc": 0.41}, good, {"auc": 0.56}, 0.4137)[0] == "pass"
    assert falsify_verdict({"auc": 0.41}, {**good, "auc": 0.40, "ci95": [0.30, 0.48]}, {"auc": 0.4}, 0.4137)[0] == "fail"
    assert falsify_verdict({"auc": 0.50}, good, {"auc": 0.56}, 0.4137)[0] == "indeterminate"      # does not reproduce aadc-14
    assert falsify_verdict({"auc": 0.41}, {**good, "n": 10}, {"auc": 0.56}, 0.4137)[0] == "indeterminate"
    # NULL CALIBRATION (PI-20261119-JX6BUNMV-0001). Short iid legs, no signal: the within-leg AUC of "bad recent R -> decay"
    # is BELOW 0.5 by construction (the audit finding), and the order null absorbs it (excess ~ 0).
    nrng = np.random.default_rng(11)
    nby = {f"N{j}": [{"trade_id": k, "closed_at": f"t{k:04d}", "r": float(np.clip(nrng.normal(0, 1), -CLIP, CLIP))}
                     for k in range(21 + int(nrng.geometric(1 / 28)))] for j in range(24)}
    nmu = {lg: 0.05 for lg in nby}
    nlp = learned_points(nby, nmu)
    for p in nlp:
        p["neg_m20"] = -p["mean20"]
    assert within_leg_auc(nlp, "neg_m20")["auc"] < 0.45, within_leg_auc(nlp, "neg_m20")
    on = order_null(nby, nmu, "cusum", draws=60)
    assert abs(on["within_leg"]["excess"]) < 0.06 and on["within_leg"]["null_mean"] < 0.45, on
    assert on["pooled"]["p_one_sided"] > 0.05, on
    # null_verdict emits only result-contract verdicts, and maps the registered branches
    def _cal(ex, p, d, cex=0.1):
        return {"learned": {"pooled": {"excess": ex, "p_one_sided": p, "draws": d}}, "cusum": {"pooled": {"excess": cex, "p_one_sided": 0.005}}}
    assert null_verdict(_cal(0.2, 0.01, 40), 675, 24)[0] == "pass"
    assert null_verdict(_cal(0.05, 0.01, 40), 675, 24)[0] == "indeterminate"     # beats the null but not the CUSUM, p < 0.20
    assert null_verdict(_cal(-0.0107, 0.5122, 40), 675, 24)[0] == "fail"         # the b9d0-01 live read
    assert null_verdict(_cal(0.02, 0.10, 40), 675, 24)[0] == "indeterminate"
    assert null_verdict(_cal(-0.01, 0.5, 20), 675, 24)[0] == "indeterminate"     # too few learned draws
    assert null_verdict(_cal(-0.01, 0.5, 40), 150, 24)[0] == "indeterminate"     # too few points
    assert {null_verdict(_cal(*a), 675, 24)[0] for a in ((0.2, 0.01, 40), (-0.01, 0.5, 40), (0.02, 0.1, 40))} <= {
        "pass", "fail", "no_action_warranted", "indeterminate", "not_applicable"}
    # the shuffle keeps each leg's trade set and length, and changes only the order
    sh = _shuffle_legs(nby, np.random.default_rng(0))
    assert all(sorted(x["r"] for x in sh[lg]) == sorted(x["r"] for x in nby[lg]) for lg in nby)
    # NEW INFORMATION (a10d-03): entry_info reads the journal fields; features read trades 0..i only; record shuffle moves r
    # and its entry info together; the verdict emits only contract tokens
    ei = entry_info({"entry_price": 100.0, "pkg_sl": 98.0, "position_size": 2, "fee_taker_usd": 0.4, "pkg_entry": 99.9,
                     "pkg_direction": "long", "pkg_meta": json.dumps({"gate": {"vol_regime": "volatile"}})})
    assert abs(ei["risk_pct"] - 0.02) < 1e-12 and abs(ei["cost_r"] - 0.1) < 1e-12 and abs(ei["slip_r"] - 0.05) < 1e-9 \
        and ei["vol_tag"] == 1.0, ei
    assert entry_info({"entry_price": 100.0})["risk_pct"] is None and _vol_tag("not json") is None and _vol_tag("{}") is None
    iseq = [{"trade_id": k, "closed_at": f"t{k:03d}", "r": 0.1, "risk_pct": 0.01 if k < 30 else 0.04, "cost_r": 0.05,
             "slip_r": None, "vol_tag": None} for k in range(60)]
    ip = {q["i"]: q for q in newinfo_points({"A": iseq}, {"A": 0.2})}
    assert np.isnan(ip[0]["volreg_z"]) and ip[29]["volreg_z"] == 0.0 and ip[30]["volreg_z"] > 1.0, (ip[0], ip[29], ip[30])
    assert np.isnan(ip[5]["cost_drift"]) and abs(ip[20]["cost_drift"]) < 1e-12 and np.isnan(ip[10]["slip10"])
    cov = newinfo_coverage(list(ip.values()))
    assert cov["per_feature"]["slip10"] == 0.0 and 0.9 < cov["core_volreg_and_cost"] < 1.0, cov
    rs = _shuffle_records({"A": iseq}, np.random.default_rng(1))["A"]
    assert sorted((x["r"], x["risk_pct"]) for x in rs) == sorted((x["r"], x["risk_pct"]) for x in iseq)
    assert [x["closed_at"] for x in rs] == [x["closed_at"] for x in iseq]
    _nn = {"pooled": {"excess": 0.06, "p_one_sided": 0.02, "draws": 40}, "within_leg": {"excess": 0.03}}
    _cv = {"core_volreg_and_cost": 0.9}
    assert newinfo_verdict(600, 20, _cv, _nn, {"delta": 0.05, "ci95": [0.01, 0.09]})[0] == "pass"
    assert newinfo_verdict(600, 20, _cv, _nn, {"delta": -0.02, "ci95": [-0.06, -0.001]})[0] == "fail"
    assert newinfo_verdict(600, 20, {"core_volreg_and_cost": 0.3}, _nn, {"delta": 0.05, "ci95": [0.01, 0.09]})[0] == "indeterminate"
    assert newinfo_verdict(600, 20, _cv, {"pooled": {"excess": -0.01, "p_one_sided": 0.6, "draws": 40}, "within_leg": {}},
                           {"delta": 0.0, "ci95": [-0.03, 0.03]})[0] == "fail"
    try:
        import lightgbm  # noqa: F401
    except ImportError:  # allow-silent: the learned checks need lightgbm (trainer / research venv); stated on stdout
        print("d10_basset_baseline self-test OK (learned planted-leak / order-null checks SKIPPED: lightgbm not installed)")
        return 0
    # PLANTED LEAK: a feature that reads the label must drive the out-of-fold AUC near 1, i.e. the OOF path CAN surface a
    # leak, so a below-chance score from it is not a hidden leak running backwards.
    for p in nlp:
        p["leak"] = float(p["decay"]) + float(nrng.normal(0, 0.3))
    loof = learned_oof(nlp, features=["leak"] + LEARNED_FEATURES)
    ok = ~np.isnan(loof)
    assert auc(loof[ok], np.array([p["decay"] for p in nlp])[ok]) > 0.9
    # a learned score with real within-leg signal (legs that turn bad) clears the order null
    tby = {f"T{j}": [{"trade_id": k, "closed_at": f"t{k:04d}",
                      "r": float(np.clip(nrng.normal(-0.6 if (j % 2 == 0 and k >= 40) else 0.3, 1), -CLIP, CLIP))}
                     for k in range(90)] for j in range(12)}
    tn = order_null(tby, {lg: 0.2 for lg in tby}, "learned", draws=8)
    assert tn["within_leg"]["excess"] > 0.05 and tn["pooled"]["excess"] > 0.05, tn
    # NEW INFORMATION planted signal: every leg alternates 30-trade good / bad blocks (no between-leg difference), and its cost
    # rises over the 10 trades BEFORE each bad block -> only the new input leads, so the newinfo score clears its record null
    pby = {}
    for j in range(12):
        seq = []
        for k in range(150):
            bad = (k + 7 * j) % 60 >= 30
            lead = 20 <= (k + 7 * j) % 60 < 30
            seq.append({"trade_id": k, "closed_at": f"t{k:04d}",
                        "r": float(np.clip(nrng.normal(-0.6 if bad else 0.4, 0.8), -CLIP, CLIP)),
                        "risk_pct": 0.01, "cost_r": 0.4 if lead else 0.05, "slip_r": None, "vol_tag": None})
        pby[f"P{j}"] = seq
    pn = newinfo_null(pby, {lg: 0.2 for lg in pby}, draws=6)
    assert pn["pooled"]["excess"] > 0.05 and pn["within_leg"]["excess"] > 0.05, pn
    print("d10_basset_baseline self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trades", help="glob of /api/diag/journal?table=trades JSON pages")
    ap.add_argument("--packages", help="glob of /api/diag/journal?table=order_packages JSON pages")
    ap.add_argument("--journal-db", help="trade_journal.db (read-only) instead of the page globs")
    ap.add_argument("--evidence-dir", default=str(REPO / "comms" / "strategy_evidence"))
    ap.add_argument("--judgments", default=str(REPO / "comms" / "claude_judgments" / "blind_grades.jsonl"))
    ap.add_argument("--out")
    ap.add_argument("--action-replay", action="store_true", help="RQ-20261117-aadc-06: demote-on-alarm replay instead of the AUC read")
    ap.add_argument("--alarm-h-sweep", action="store_true", help="RQ-20261117-aadc-07: demote-on-alarm at H in SWEEP_H, Bonferroni")
    ap.add_argument("--stage0-confirm", action="store_true", help="RQ-20261117-aadc-09: H 2 on the Stage-0 OOS series before 2026-05-01")
    ap.add_argument("--learned", action="store_true", help="RQ-20261118-aadc-14: learned degradation score vs the CUSUM baseline")
    ap.add_argument("--falsify-legid", action="store_true",
                    help="RQ-20261118-f7c1-07: aadc-14 with and without the leg-level inputs (n_seen, mu) + within-leg AUC")
    ap.add_argument("--null-calibrate", action="store_true",
                    help="PI-20261119-JX6BUNMV-0001: order-null calibration (excess AUC) of the CUSUM and learned scores")
    ap.add_argument("--newinfo", action="store_true",
                    help="RQ-20261119-a10d-03: aadc-14's learned score plus regime-at-entry and cost-drift inputs, record-order null")
    ap.add_argument("--null-draws-cusum", type=int, default=NULL_DRAWS_CUSUM)
    ap.add_argument("--null-draws-learned", type=int, default=NULL_DRAWS_LEARNED)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.stage0_confirm and a.out:
        return run(a)
    if not a.out or not (a.journal_db or (a.trades and a.packages)):
        ap.error("--out and either --journal-db or (--trades and --packages) are required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
