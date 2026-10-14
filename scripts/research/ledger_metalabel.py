#!/usr/bin/env python3
# wiring: research/queue units (run.command) via research-script-run.yml -- the token-free runner
"""Meta-labeling and peak-to-exit measurements over the COMMITTED per-trade test-result ledgers.

WHY THIS EXISTS (02-AI-TRADER programme, 2026-10-14; M23 revived by the operator). Meta-labeling
(Lopez de Prado ch. 3) is a secondary head that decides whether to ACT on a primary strategy's own
signal. The operator's 2026-10-14 direction is that the AI trader is fed ALL test results and trade
outcomes, not only the ~99 closed real-money trades behind the label wall. The one committed corpus
of test results this repo already has is `comms/strategy_evidence/runs/<run>/<leg>__trades.jsonl`
(the harnesses' `--emit-trades` rows, net of the full cost stack: `net_r` = gross - fee - slippage -
funding). Nothing read it as a meta-label corpus before this script. It is also the only corpus that
carries a peak-to-exit quantity (`mfe_r`) at scale, which is the raw material of the exit-model line.

WHAT IT MEASURES
  --mode census    (deterministic) per leg family: n, win rate, mean net_r, the peak-to-exit label
                   distribution (giveback_r = mfe_r - net_r; giveback_frac = giveback_r / mfe_r on
                   trades with mfe_r > 0), the ORACLE-PEAK upper bound (a perfect exit at the peak:
                   mean max(mfe_r, net_r) vs mean net_r) and the headroom per trade. Verdict by the
                   unit's registered thresholds (--headroom-pass-r / --headroom-fail-r / --min-n).
  --mode classify  (experiment) WITHIN EACH LEG (never pooled across legs -- the M18/M23 base-rate
                   trap): purged expanding walk-forward, learners prior / numpy_logit / lightgbm from
                   scripts/research/ml_bakeoff.py on the decision-time columns the ledgers carry,
                   target `won` (net_r > 0) or `giveback_gt` (giveback_frac > --threshold). Reports
                   per-leg fold-mean AUC vs the class prior (0.5) with a paired t-interval, plus the
                   SELECTION LIFT that matters for a take/skip head: mean net_r of the test trades the
                   learner KEEPS (drops its bottom --skip-quantile by score, scored on train-only
                   folds) minus mean net_r of taking all. Verdict by the unit's thresholds
                   (--auc-gain / --lift-r / --min-leg-n).

HONEST LIMITS, STATED IN THE RECORD
  * The ledgers carry THIN decision-time context: `confidence`, `direction`, `entry_time` (hour,
    day-of-week), `adx_at_entry` (null on ~96% of rows, MEASURED 2026-10-14) and `regime_weight`.
    A null result here closes only THESE columns; the lever that widens the emits is a build row.
  * `mfe_r` is a lagged lower bound (gross_r > mfe_r on 825 of 12,141 committed rows, 2026-10-14),
    so giveback is understated and the oracle bound is conservative, never optimistic.
  * Bootstrap sub-ledgers (`<leg>__B<k>`, `<leg>__M`) are resamples of one leg and are excluded by
    default so a trade is never counted twice.
  * Nothing here places orders, touches config, or promotes anything. A PASS earns the next
    pre-registered unit, not a roster or sizing change (Tier-3 is elsewhere).

Writes `<out>/verdict.json` in the shape script_run.py --derive-record consumes
({verdict, read_state, population, n, measurement, note}). Tier-1 research code: reads committed
files, no network, no VM, no live path. `--self-test` plants a synthetic ledger with a known signal
and a known giveback shape and asserts both modes see them.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research.ml_bakeoff import LEARNERS, _auc_binary, paired_delta, probe_learner, purged_folds  # noqa: E402

DEFAULT_LEDGERS = "comms/strategy_evidence/runs/*/*__trades.jsonl"
RESAMPLE_RE = re.compile(r"__B\d+$|__M$")
#: Decision-time columns the ledgers carry today (MEASURED 2026-10-14 over 13,070 committed rows:
#: confidence present on 12,304, adx_at_entry on 3,137 (mostly null), regime_weight on 3,137).
BASE_FEATURES = ["confidence", "direction_long", "hour_of_day", "dayofweek", "adx_at_entry", "regime_weight"]
#: Leg -> strategy unit module (the family a meta-head would be scoped to). Equity/futures legs are named
#: <ticker>_<family>_<tf>; crypto legs carry the module name or a `pullback_`/`squeeze_` prefix.
FAMILY_RE = re.compile(r"^(trend_donchian|htf_pullback|ict_scalp|squeeze|fade|fvg_range|turtle_soup|pullback)")
FAMILY_ALIAS = {"htf_pullback": "pullback", "trend": "trend_donchian"}


# ── corpus ────────────────────────────────────────────────────────────────────
def newest_ledgers(glob_pat: str, include_resamples: bool = False) -> Dict[str, Path]:
    """{leg: newest committed ledger}; newest = lexicographically last run directory (same rule as
    regime_impact_scoping.newest_ledgers, re-stated here so this script has no network import)."""
    import glob as _glob
    out: Dict[str, Path] = {}
    for f in sorted(_glob.glob(str(REPO / glob_pat) if not os.path.isabs(glob_pat) else glob_pat)):
        leg = os.path.basename(f)[: -len("__trades.jsonl")]
        if not include_resamples and RESAMPLE_RE.search(leg):
            continue
        out[leg] = Path(f)
    return out


def family_of(leg: str) -> str:
    m = FAMILY_RE.match(leg)
    fam = m.group(1) if m else (leg.split("_")[1] if len(leg.split("_")) >= 3 else leg)
    return FAMILY_ALIAS.get(fam, fam)


def load_corpus(glob_pat: str, leg_re: Optional[str], include_resamples: bool):
    import pandas as pd
    rows: List[Dict[str, Any]] = []
    files: List[str] = []
    for leg, path in newest_ledgers(glob_pat, include_resamples).items():
        if leg_re and not re.search(leg_re, leg):
            continue
        files.append(str(path.relative_to(REPO)) if REPO in path.parents else str(path))
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            r["leg"] = leg
            r["family"] = family_of(leg)
            rows.append(r)
    if not rows:
        return pd.DataFrame(), files
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["entry_time", "net_r"]).sort_values(["leg", "entry_time"]).reset_index(drop=True)
    for c in ("confidence", "adx_at_entry", "regime_weight", "mfe_r", "gross_r"):
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["direction_long"] = (df.get("direction", "long").astype(str).str.lower() == "long").astype(float)
    df["hour_of_day"] = df["entry_time"].dt.hour.astype(float)
    df["dayofweek"] = df["entry_time"].dt.dayofweek.astype(float)
    df["won"] = (df["net_r"] > 0).astype(int)
    pos = df["mfe_r"] > 0
    df["giveback_r"] = np.where(pos, df["mfe_r"] - df["net_r"], np.nan)
    df["giveback_frac"] = np.where(pos, (df["mfe_r"] - df["net_r"]) / df["mfe_r"].where(pos), np.nan)
    df["oracle_peak_r"] = np.where(df["mfe_r"].notna(), np.maximum(df["mfe_r"].fillna(-np.inf), df["net_r"]), df["net_r"])
    return df, files


# ── census ────────────────────────────────────────────────────────────────────
def _q(x: np.ndarray, qs=(0.25, 0.5, 0.75)) -> Dict[str, Optional[float]]:
    x = x[~np.isnan(x)]
    return {f"p{int(q * 100)}": (float(np.quantile(x, q)) if len(x) else None) for q in qs}


def census_group(g) -> Dict[str, Any]:
    mfe_ok = g["mfe_r"].notna()
    pos = g["mfe_r"] > 0
    n = int(len(g))
    real = float(g["net_r"].mean()) if n else None
    # recomputed HERE from mfe_r / net_r (not read from precomputed columns) so a caller that re-assigns
    # mfe_r -- the self-test's zero-headroom control -- is measured on what it passed in
    mfe = g["mfe_r"].to_numpy(dtype=float)
    net = g["net_r"].to_numpy(dtype=float)
    ok = mfe_ok.to_numpy()
    oracle = float(np.maximum(mfe[ok], net[ok]).mean()) if ok.any() else None
    real_on_mfe_rows = float(net[ok].mean()) if ok.any() else None
    p = pos.to_numpy()
    gf = ((mfe[p] - net[p]) / mfe[p]) if p.any() else np.array([], dtype=float)
    return {
        "n": n, "n_with_mfe": int(mfe_ok.sum()), "n_mfe_positive": int(pos.sum()),
        "win_rate": float(g["won"].mean()) if n else None,
        "mean_net_r": real,
        "mean_net_r_on_mfe_rows": real_on_mfe_rows,
        "mean_oracle_peak_r": oracle,
        "exit_headroom_r_per_trade": (oracle - real_on_mfe_rows) if (oracle is not None and real_on_mfe_rows is not None) else None,
        "giveback_frac": {**_q(gf), "share_gt_0_5": float(np.mean(gf > 0.5)) if len(gf) else None,
                          "share_gt_1_0": float(np.mean(gf > 1.0)) if len(gf) else None},
        "mfe_r": _q(g.loc[mfe_ok, "mfe_r"].to_numpy(dtype=float)),
        "exit_reasons": {str(k): int(v) for k, v in g["exit_reason"].value_counts(dropna=False).items()} if "exit_reason" in g else {},
        "mfe_lower_bound_rows": int(((g["gross_r"] > g["mfe_r"]) & mfe_ok).sum()) if "gross_r" in g else None,
    }


def run_census(df, *, min_n: int, pass_r: float, fail_r: float) -> Dict[str, Any]:
    fams = {str(f): census_group(g) for f, g in df.groupby("family")}
    legs = {str(leg): census_group(g) for leg, g in df.groupby("leg")}
    pooled = census_group(df)
    eligible = {f: c for f, c in fams.items() if c["n_with_mfe"] >= min_n and c["exit_headroom_r_per_trade"] is not None}
    if not eligible:
        return {"verdict": "indeterminate", "label": "no_family_at_min_n", "families": fams, "legs": legs, "pooled": pooled}
    best = max(eligible.items(), key=lambda kv: kv[1]["exit_headroom_r_per_trade"])
    if best[1]["exit_headroom_r_per_trade"] >= pass_r:
        v, label = "pass", f"exit_headroom_present ({best[0]} {best[1]['exit_headroom_r_per_trade']:.3f} R/trade >= {pass_r})"
    elif all(c["exit_headroom_r_per_trade"] < fail_r for c in eligible.values()):
        v, label = "fail", f"no_exit_headroom (every family at n>={min_n} < {fail_r} R/trade)"
    else:
        v, label = "indeterminate", "headroom_between_bars"
    return {"verdict": v, "label": label, "families": fams, "legs": legs, "pooled": pooled, "eligible_families": sorted(eligible)}


# ── classify ──────────────────────────────────────────────────────────────────
def _impute(Xtr: np.ndarray, Xte: np.ndarray, kind: str) -> Tuple[np.ndarray, np.ndarray]:
    """LightGBM handles NaN natively; the prior ignores X; the numpy logit needs an impute (train medians)."""
    if kind != "numpy_logit":
        return Xtr, Xte
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    return np.where(np.isnan(Xtr), med, Xtr), np.where(np.isnan(Xte), med, Xte)


def classify_leg(g, *, target: str, features: List[str], learners: Dict[str, str], folds: int, embargo: int,
                 min_train_frac: float, skip_q: float, status: Dict[str, Optional[str]]) -> Dict[str, Any]:
    g = g.reset_index(drop=True)
    y = g[target].to_numpy(dtype=int)
    X = np.column_stack([g[c].to_numpy(dtype=float) for c in features]) if features else np.zeros((len(g), 0))
    net = g["net_r"].to_numpy(dtype=float)
    plan = purged_folds(len(g), folds, embargo, min_train_frac)
    out: Dict[str, Any] = {"n": int(len(g)), "base_rate": float(y.mean()) if len(y) else None, "folds": len(plan), "arms": {}}
    if len(plan) < 1 or len(set(y.tolist())) < 2:
        out["note"] = "too few folds or a single class"
        return out
    take_all = [float(net[te].mean()) for _, te in plan]
    for name, kind in learners.items():
        if status.get(name):
            out["arms"][name] = {"status": "unavailable", "reason": status[name]}
            continue
        fit = LEARNERS[kind][0]
        aucs, lifts, kept_n = [], [], 0
        try:
            for tr, te in plan:
                if len(set(y[tr].tolist())) < 2:
                    aucs.append(float("nan"))
                    lifts.append(float("nan"))
                    continue
                A, B = _impute(X[tr], X[te], kind)
                P = fit(A, y[tr], B, 2, {})
                s = P[:, 1]
                aucs.append(_auc_binary(y[te], s))
                # take/skip selection: threshold learned on TRAIN scores only (no peeking at the test fold)
                Ptr = fit(A, y[tr], A, 2, {})[:, 1]
                thr = float(np.quantile(Ptr, skip_q)) if skip_q > 0 else -np.inf
                keep = s > thr
                kept_n += int(keep.sum())
                lifts.append(float(net[te][keep].mean() - net[te].mean()) if keep.any() else float("nan"))
        except Exception as e:  # allow-silent: one arm failing is contained and recorded as status=error
            out["arms"][name] = {"status": "error", "reason": f"{type(e).__name__}: {e}"}
            continue
        auc_d = paired_delta(aucs, [0.5] * len(aucs))
        lift_d = paired_delta(lifts, [0.0] * len(lifts))
        out["arms"][name] = {"status": "ok", "kind": kind, "fold_auc": aucs, "auc_minus_prior": auc_d,
                             "fold_selection_lift_r": lifts, "selection_lift_r": lift_d,
                             "kept_test_trades": kept_n, "take_all_fold_mean_net_r": take_all}
    return out


def run_classify(df, *, target: str, threshold: float, features: List[str], learner_kinds: List[str], folds: int,
                 embargo: int, min_train_frac: float, min_leg_n: int, skip_q: float,
                 auc_gain: float, lift_r: float) -> Dict[str, Any]:
    if target == "giveback_gt":
        df = df[df["mfe_r"] > 0].copy()
        df["giveback_gt"] = (df["giveback_frac"] > threshold).astype(int)
    tcol = "won" if target == "won" else "giveback_gt"
    learners = {k: k for k in learner_kinds}
    status = {k: probe_learner(k, {}) for k in learners}
    legs: Dict[str, Any] = {}
    for leg, g in df.groupby("leg"):
        if len(g) < min_leg_n:
            continue
        legs[str(leg)] = classify_leg(g, target=tcol, features=features, learners=learners, folds=folds, embargo=embargo,
                                      min_train_frac=min_train_frac, skip_q=skip_q, status=status)
    passing, evaluated = [], 0
    all_null = True
    for leg, r in legs.items():
        for name, arm in r["arms"].items():
            if arm.get("status") != "ok" or name == "prior":
                continue
            evaluated += 1
            ad, ld = arm["auc_minus_prior"], arm["selection_lift_r"]
            ci = ad.get("ci95")
            if ad.get("mean") is not None and ad["mean"] >= auc_gain and ci and ci[0] > 0 \
                    and ld.get("mean") is not None and ld["mean"] >= lift_r:
                passing.append({"leg": leg, "arm": name, "auc_gain": ad["mean"], "lift_r": ld["mean"]})
            if ci and ci[0] > 0:
                all_null = False
    unavailable = {k: v for k, v in status.items() if v}
    if not legs:
        v, label = "indeterminate", f"no leg with n >= {min_leg_n}"
    elif passing:
        v, label = "pass", f"within-leg separation on {len(passing)} (leg, arm) pair(s)"
    elif unavailable:
        v, label = "indeterminate", f"no pass; UNAVAILABLE ARMS {sorted(unavailable)} (a FAIL needs every arm)"
    elif evaluated and all_null:
        v, label = "fail", "every evaluated arm's AUC interval contains the class prior on every leg"
    else:
        v, label = "indeterminate", "no arm clears both bars; some AUC intervals exclude the prior"
    return {"verdict": v, "label": label, "target": tcol, "threshold": threshold if tcol == "giveback_gt" else None,
            "features": features, "learners": learner_kinds, "arm_status": status, "legs": legs, "passing": passing,
            "n_test_trades": int(sum(sum(len(te) for _, te in purged_folds(r["n"], folds, embargo, min_train_frac)) for r in legs.values()))}


# ── record ────────────────────────────────────────────────────────────────────
def write_verdict(out: Path, verdict: Dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=False)
    ap.add_argument("--mode", choices=("census", "classify"), default="census")
    ap.add_argument("--ledgers", default=DEFAULT_LEDGERS)
    ap.add_argument("--legs", default=None, help="regex on leg name (default: every leg)")
    ap.add_argument("--include-resamples", action="store_true")
    # census bars
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--headroom-pass-r", type=float, default=0.25)
    ap.add_argument("--headroom-fail-r", type=float, default=0.10)
    # classify
    ap.add_argument("--target", choices=("won", "giveback_gt"), default="won")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--features", default=",".join(BASE_FEATURES))
    ap.add_argument("--learners", default="prior,numpy_logit,lightgbm")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--embargo", type=int, default=5)
    ap.add_argument("--min-train-frac", type=float, default=0.4)
    ap.add_argument("--min-leg-n", type=int, default=100)
    ap.add_argument("--skip-quantile", type=float, default=0.2)
    ap.add_argument("--auc-gain", type=float, default=0.05)
    ap.add_argument("--lift-r", type=float, default=0.05)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    df, files = load_corpus(a.ledgers, a.legs, a.include_resamples)
    pop_base = (f"newest committed ledger per leg under {a.ledgers}"
                f"{' matching ' + a.legs if a.legs else ''}; resamples {'included' if a.include_resamples else 'excluded (__B<k>/__M)'}; "
                f"{len(files)} ledger file(s), {len(df)} trades, {df['leg'].nunique() if len(df) else 0} legs; "
                f"net_r is the harness value net of fee + slippage + funding")
    if len(df) == 0:
        write_verdict(Path(a.out), {"verdict": "not_applicable", "read_state": "no_data", "n": 0, "population": pop_base,
                                    "note": "no_data: no committed ledger matched", "measurement": {"files": files}})
        print("ledger_metalabel: no_data")
        return 0
    if a.mode == "census":
        m = run_census(df, min_n=a.min_n, pass_r=a.headroom_pass_r, fail_r=a.headroom_fail_r)
        measured = bool(m.get("eligible_families"))
        rec = {"verdict": m["verdict"] if measured else "not_applicable", "read_state": "measured" if measured else "no_data",
               "n": int(m["pooled"]["n_with_mfe"]) if measured else 0, "population": pop_base,
               "measurement": {"mode": "census", "bars": {"min_n": a.min_n, "headroom_pass_r": a.headroom_pass_r, "headroom_fail_r": a.headroom_fail_r},
                               "files": files, **{k: m[k] for k in ("label", "families", "legs", "pooled") if k in m},
                               "eligible_families": m.get("eligible_families", [])},
               "note": (f"{m['label']}. Peak-to-exit census, NOT a promotion case. mfe_r is a lagged LOWER bound "
                        f"({m['pooled'].get('mfe_lower_bound_rows')} rows have gross_r > mfe_r), so headroom is understated. "
                        "The oracle-peak bound is unattainable by construction; it sizes the prize an exit model could chase.")}
    else:
        feats = [f for f in a.features.split(",") if f]
        m = run_classify(df, target=a.target, threshold=a.threshold, features=feats, learner_kinds=a.learners.split(","),
                         folds=a.folds, embargo=a.embargo, min_train_frac=a.min_train_frac, min_leg_n=a.min_leg_n,
                         skip_q=a.skip_quantile, auc_gain=a.auc_gain, lift_r=a.lift_r)
        measured = bool(m["legs"])
        rec = {"verdict": m["verdict"] if measured else "not_applicable", "read_state": "measured" if measured else "no_data",
               "n": m["n_test_trades"] if measured else 0, "population": pop_base + f"; legs with n >= {a.min_leg_n}: {len(m['legs'])}",
               "measurement": {"mode": "classify", "bars": {"auc_gain": a.auc_gain, "lift_r": a.lift_r, "min_leg_n": a.min_leg_n,
                                                            "skip_quantile": a.skip_quantile, "folds": a.folds, "embargo": a.embargo},
                               "files": files, **m},
               "note": (f"{m['label']}. Within-leg meta-label test on the decision-time columns the ledgers carry "
                        f"({', '.join(feats)}); a null closes only these columns. Selection lift = mean net_r of kept test trades "
                        f"minus take-all, skip threshold learned on train folds. Not a promotion case.")}
    write_verdict(Path(a.out), rec)
    print(f"ledger_metalabel {a.mode}: verdict={rec['verdict']} read_state={rec['read_state']} n={rec['n']}")
    return 0


# ── self-test ─────────────────────────────────────────────────────────────────
def _self_test() -> int:
    rng = np.random.default_rng(3)
    with tempfile.TemporaryDirectory() as td:
        run = Path(td) / "runs" / "2026-01-01"
        run.mkdir(parents=True)
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for leg, signal in (("trend_donchian_sig_4h", 2.5), ("trend_donchian_null_4h", 0.0)):
            rows = []
            for i in range(400):
                conf = float(rng.uniform(0, 1))
                p = 1 / (1 + math.exp(-(signal * (conf - 0.5))))
                won = rng.uniform() < p
                net = float(rng.normal(1.2, 0.4)) if won else float(-rng.normal(0.9, 0.3))
                mfe = max(net, 0.0) + float(rng.exponential(0.6))
                rows.append({"strategy": "trend_donchian", "symbol": "XUSDT", "entry_time": (t0 + timedelta(hours=4 * i)).isoformat(),
                             "direction": "long" if i % 2 else "short", "net_r": net, "gross_r": net + 0.03, "mfe_r": mfe,
                             "exit_reason": "trail_stop", "confidence": conf})
            (run / f"{leg}__trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        # a resample that must be excluded by default
        (run / "trend_donchian_sig_4h__B0__trades.jsonl").write_text((run / "trend_donchian_sig_4h__trades.jsonl").read_text())
        pat = str(run / "*__trades.jsonl")
        df, _files = load_corpus(pat, None, False)
        ok = True
        if df["leg"].nunique() != 2 or len(df) != 800:
            print(f"  FAIL  resample exclusion: legs={df['leg'].nunique()} rows={len(df)}")
            ok = False
        else:
            print("  PASS  resample ledgers excluded by default")
        c = run_census(df, min_n=100, pass_r=0.25, fail_r=0.10)
        head = c["families"]["trend_donchian"]["exit_headroom_r_per_trade"]
        if c["verdict"] == "pass" and head and head > 0.25:
            print(f"  PASS  census sees the planted giveback headroom ({head:.2f} R/trade)")
        else:
            print(f"  FAIL  census: {c['verdict']} headroom={head}")
            ok = False
        # control: the exit already sits AT the peak on every trade (mfe_r == net_r) -> zero headroom by construction
        c2 = run_census(df.assign(mfe_r=df["net_r"]), min_n=100, pass_r=0.25, fail_r=0.10)
        if c2["verdict"] == "fail":
            print("  PASS  census FAILs when the exit already captures the peak (no headroom)")
        else:
            print(f"  FAIL  census no-headroom control: {c2['verdict']}")
            ok = False
        m = run_classify(df, target="won", threshold=0.5, features=["confidence", "direction_long", "hour_of_day", "dayofweek"],
                         learner_kinds=["prior", "numpy_logit"], folds=4, embargo=5, min_train_frac=0.4, min_leg_n=100,
                         skip_q=0.2, auc_gain=0.05, lift_r=0.05)
        legs_pass = {p["leg"] for p in m["passing"]}
        if m["verdict"] == "pass" and legs_pass == {"trend_donchian_sig_4h"}:
            print("  PASS  classify finds the planted leg and not the null leg")
        else:
            print(f"  FAIL  classify: {m['verdict']} passing={m['passing']}")
            ok = False
        null_only = run_classify(df[df["leg"] == "trend_donchian_null_4h"], target="won", threshold=0.5,
                                 features=["confidence", "direction_long"], learner_kinds=["prior", "numpy_logit"], folds=4,
                                 embargo=5, min_train_frac=0.4, min_leg_n=100, skip_q=0.2, auc_gain=0.05, lift_r=0.05)
        if null_only["verdict"] in ("fail", "indeterminate"):
            print(f"  PASS  classify does not pass the null leg alone ({null_only['verdict']})")
        else:
            print(f"  FAIL  null leg graded {null_only['verdict']}")
            ok = False
        out = Path(td) / "out"
        rc = main(["--out", str(out), "--mode", "census", "--ledgers", pat])
        rec = json.loads((out / "verdict.json").read_text())
        if rc == 0 and rec["read_state"] == "measured" and rec["verdict"] == "pass":
            print("  PASS  verdict.json written in the script_run record shape")
        else:
            print(f"  FAIL  record: rc={rc} {rec.get('read_state')} {rec.get('verdict')}")
            ok = False
    print("ledger_metalabel self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
