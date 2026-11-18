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
        out.append({**t, "pkg_sl": _f(p.get("sl")) if p else None})
    return out


def load_db(db: Path) -> List[dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT t.*, op.sl AS pkg_sl FROM trades t LEFT JOIN order_packages op "
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
                                       "r": float(np.clip(r, -CLIP, CLIP)), "r_raw": r})
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


def learned_oof(pts: List[dict], seed: int = SEED) -> np.ndarray:
    """Out-of-fold P(decay): legs are split into N_GROUP_FOLDS groups, so no leg's own points train its score."""
    import lightgbm as lgb
    legs = sorted({p["leg"] for p in pts})
    rng = np.random.default_rng(seed)
    order = list(rng.permutation(len(legs)))
    fold_of = {legs[j]: k % N_GROUP_FOLDS for k, j in enumerate(order)}
    X = np.array([[p[f] for f in LEARNED_FEATURES] for p in pts], float)
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
    if a.alarm_h_sweep:
        arms = [action_replay(by, mu, h=hh) for hh in SWEEP_H]
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
