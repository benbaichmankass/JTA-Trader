#!/usr/bin/env python3
# wiring: research/queue units declaring run.command ["python3","scripts/research/conformal_abstain_eval.py",...]
#         via the research-queue dispatcher (compute: auto -> research-script-run-kaggle-cpu.yml / research-script-run.yml)
"""Conformal abstention vs a plain max-probability threshold at MATCHED coverage (FRONTIER-LEVER-CONFORMAL).

WHY (ML-UNBLOCK-1018, 2026-10-18)
---------------------------------
``scripts/research/ml_bakeoff.py`` compares LEARNERS. Conformal abstention evaluates a SCORE STREAM:
given a fitted classifier, does "abstain when the conformal prediction set is not a singleton" give a
LOWER selective error than "abstain when max-probability is below a threshold", at the SAME fraction
of rows kept -- and does the conformal set keep its nominal coverage inside rolling windows (regime
shifts break exchangeability, so validity is a measured thing, not a theorem)? This scorer answers
that for a unit whose data is a LABELLED shard (the ``--published`` case: ``RQ-20261016-65ff-25``).
The shadow-log case (``RQ-20261011-9da8-03``) additionally needs the realised-label joiner
(``ML-HEAD-AGREEMENT-JOIN``) and is NOT covered here; it reuses ``evaluate_stream`` once that joiner
lands rows of ``(ts, proba[], y)``.

THE UNIT BLOCK (registered BEFORE the run, beside ``decision_rule``)
--------------------------------------------------------------------
::

    ml_bakeoff:                      # dataset / cv / learner reuse ml_bakeoff's schema so the compute router can
      dataset: {...}                 # check published-data paths and the loader stays the one owner of shard reading
      cv: {folds: 5, embargo_rows: 24, min_train_frac: 0.4}
      learners: {lgbm: {kind: lightgbm, params: {...}}}
    conformal:
      learner: lgbm                  # the score stream under test (one fitted learner)
      coverage_levels: [0.5, 0.7, 0.9]   # fraction of OOS rows KEPT (not abstained); matched between the two rules
      calib_frac: 0.25               # tail of each fold's TRAIN block held out for calibration (after an embargo)
      window_days: 30                # rolling validity windows (non-overlapping, by ts)
      min_window_rows: 200
      min_windows: 6
      validity_mode: 2se             # 2se (default): |empirical - nominal| <= 2 * SE, with SE combining the test-window
                                     #   binomial SE and the calibration-set SE (split-conformal coverage given ONE
                                     #   calibration set is Beta-distributed around nominal, Vovk 2012); tol: a fixed band
      validity_tol: 0.03             # the fixed band when validity_mode is tol (reported as a diagnostic either way)
      validity_min_share: 0.90       # share of windows that must satisfy the validity criterion
      mondrian: predicted_class      # predicted_class | none
      rule:
        pass_symbols_min: 2          # PASS needs >= this many groups passing BOTH conditions
        fail_symbols_min: 2          # FAIL needs >= this many groups failing EITHER condition

THE TWO RULES, BOTH TUNED ON THE CALIBRATION BLOCK ONLY
-------------------------------------------------------
* plain: keep a row iff ``max_p >= t_c``; ``t_c`` is the calibration quantile that keeps a share ``c``.
* conformal (split, Mondrian per predicted class): nonconformity ``s = 1 - p(y_true)``; the
  prediction set at level ``alpha`` is ``{y : 1 - p(y) <= q_alpha}`` with ``q_alpha`` the
  ``ceil((n+1)(1-alpha))/n`` calibration quantile of ``s`` within the row's predicted-class stratum;
  keep a row iff the set is a SINGLETON. ``alpha_c`` is chosen on the calibration block so the kept
  share is ``c`` (matched coverage), then applied unchanged to the test block.
* selective error = misclassification rate among KEPT test rows (the predicted class is argmax).
* validity = per rolling window of test rows, ``|P(y in set) - (1 - alpha_c)| <= validity_tol``.

Nothing here changes a head, threshold, stage or order path. Tier-1 research tooling: reads a shard,
writes only ``--out``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.research import ml_bakeoff as mb  # noqa: E402

DEFAULTS: dict[str, Any] = {
    "coverage_levels": [0.5, 0.7, 0.9], "calib_frac": 0.25, "window_days": 30, "min_window_rows": 200,
    "min_windows": 6, "validity_mode": "2se", "validity_tol": 0.03, "validity_min_share": 0.90,
    "mondrian": "predicted_class",
    "rule": {"pass_symbols_min": 2, "fail_symbols_min": 2},
}


# ── the two abstention rules ─────────────────────────────────────────────────
def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Finite-sample split-conformal quantile: the ceil((n+1)(1-alpha))/n empirical quantile of the
    calibration nonconformity scores (Vovk et al.; Angelopoulos & Bates 2021 eq. 2). ``inf`` when n is too
    small for the level, which makes every set the full label set (never a false singleton)."""
    n = len(scores)
    if n == 0:
        return float("inf")
    k = int(math.ceil((n + 1) * (1.0 - alpha)))
    if k > n:
        return float("inf")
    return float(np.sort(scores)[k - 1])


def _strata(pred: np.ndarray, mondrian: str) -> np.ndarray:
    return pred if mondrian == "predicted_class" else np.zeros(len(pred), dtype=int)


def conformal_sets(P: np.ndarray, qhat: dict[int, float], mondrian: str) -> np.ndarray:
    """Boolean (n, C) membership: y in set iff 1 - P[y] <= qhat[stratum(row)]."""
    pred = np.argmax(P, axis=1)
    st = _strata(pred, mondrian)
    q = np.array([qhat.get(int(s), float("inf")) for s in st])
    return (1.0 - P) <= q[:, None]


def fit_conformal(P_cal: np.ndarray, y_cal: np.ndarray, alpha: float, mondrian: str) -> dict[int, float]:
    pred = np.argmax(P_cal, axis=1)
    st = _strata(pred, mondrian)
    s = 1.0 - P_cal[np.arange(len(y_cal)), y_cal.astype(int)]
    return {int(g): conformal_quantile(s[st == g], alpha) for g in np.unique(st)}


def kept_share_conformal(P_cal: np.ndarray, y_cal: np.ndarray, alpha: float, mondrian: str) -> float:
    qhat = fit_conformal(P_cal, y_cal, alpha, mondrian)
    return float(np.mean(conformal_sets(P_cal, qhat, mondrian).sum(axis=1) == 1))


def tune_alpha(P_cal: np.ndarray, y_cal: np.ndarray, coverage: float, mondrian: str,
               grid: np.ndarray | None = None) -> tuple[float, float]:
    """The alpha at which the calibration SINGLETON share first reaches ``coverage``.

    The singleton share is UNIMODAL in alpha: as alpha rises from 0 the sets shrink from the full label set
    to singletons (share rises), then past the peak they empty out (share falls). Two alphas can therefore
    give the same kept share with opposite meanings -- 'uncertain' vs 'nothing fits'. The abstention rule
    wants the RISING branch (the highest nominal coverage that still keeps ``coverage`` of the rows), so the
    grid is walked upward and stops at the first alpha whose share >= ``coverage``. If the peak never
    reaches ``coverage`` the model is too weak to keep that many singletons: return the peak alpha and
    its share (the caller records ``coverage_matched: false``). Returns (alpha, share_on_calibration)."""
    grid = np.linspace(0.005, 0.95, 190) if grid is None else grid
    peak = (float("nan"), -1.0)
    for a in grid:
        share = kept_share_conformal(P_cal, y_cal, float(a), mondrian)
        if share >= coverage:
            return float(a), share
        if share > peak[1]:
            peak = (float(a), share)
    return peak


def tune_threshold(P_cal: np.ndarray, coverage: float) -> float:
    """Plain rule: keep iff max_p >= t; t = the (1 - coverage) quantile of calibration max_p."""
    mp = P_cal.max(axis=1)
    return float(np.quantile(mp, 1.0 - coverage))


def selective_error(P: np.ndarray, y: np.ndarray, keep: np.ndarray) -> float | None:
    if keep.sum() == 0:
        return None
    pred = np.argmax(P, axis=1)
    return float(np.mean(pred[keep] != y[keep].astype(int)))


# ── windows ─────────────────────────────────────────────────────────────────
def window_ids(ts: np.ndarray, window_days: int) -> np.ndarray:
    """Non-overlapping ``window_days`` windows over sorted UTC timestamps given as int64 epoch-ns."""
    t = np.asarray(ts, dtype="int64")
    w = int(window_days) * 86_400 * 10**9
    return ((t - t.min()) // w).astype(int)


# ── one group (symbol) ──────────────────────────────────────────────────────
def evaluate_stream(ts: np.ndarray, P: np.ndarray, y: np.ndarray, cal_mask: np.ndarray, test_mask: np.ndarray,
                    cfg: dict[str, Any]) -> dict[str, Any]:
    """Grade ONE fold's (calibration, test) pair of a score stream at every coverage level.
    ``P`` (n, C) probabilities, ``y`` int labels, masks index rows of the same arrays."""
    mondrian = str(cfg.get("mondrian", "predicted_class"))
    out: dict[str, Any] = {"levels": {}, "n_cal": int(cal_mask.sum()), "n_test": int(test_mask.sum())}
    Pc, yc = P[cal_mask], y[cal_mask]
    Pt, yt, tt = P[test_mask], y[test_mask], ts[test_mask]
    for c in cfg["coverage_levels"]:
        c = float(c)
        t_plain = tune_threshold(Pc, c)
        keep_plain = Pt.max(axis=1) >= t_plain
        alpha, share_cal = tune_alpha(Pc, yc, c, mondrian)
        qhat = fit_conformal(Pc, yc, alpha, mondrian)
        sets = conformal_sets(Pt, qhat, mondrian)
        keep_conf = sets.sum(axis=1) == 1
        covered = sets[np.arange(len(yt)), yt.astype(int)]
        # MATCHED coverage is a precondition of the comparison, not an assumption: singleton share is
        # unimodal in alpha, so a weak model may never keep 90% of rows as singletons. Report it.
        matched = abs(share_cal - c) <= float(cfg.get("match_tol", 0.03))
        out["levels"][str(c)] = {
            "plain": {"threshold": t_plain, "kept_share": float(keep_plain.mean()),
                      "selective_error": selective_error(Pt, yt, keep_plain)},
            "conformal": {"alpha": alpha, "nominal_coverage": 1.0 - alpha, "kept_share_calibration": share_cal,
                          "kept_share": float(keep_conf.mean()), "selective_error": selective_error(Pt, yt, keep_conf),
                          "set_coverage": float(covered.mean()), "qhat": {str(k): v for k, v in qhat.items()}},
            "coverage_matched": bool(matched),
            "_covered": covered, "_ts": tt,
        }
    return out


def run_group(df, spec: dict[str, Any], cfg: dict[str, Any], learner_name: str, learner: dict[str, Any],
              status: str | None) -> dict[str, Any]:
    ds, cv = spec["dataset"], spec.get("cv") or {}
    ts_col, target = ds.get("ts_col", "ts"), ds["target"]
    df = df.dropna(subset=[target]).sort_values(ts_col).reset_index(drop=True)
    classes = sorted(df[target].dropna().unique().tolist(), key=str)
    cmap = {c: i for i, c in enumerate(classes)}
    y = df[target].map(cmap).to_numpy().astype(int)
    k = len(classes)
    import pandas as pd
    # epoch-ns int64, tz-free. Explicit [ns]: pandas >= 3 keeps date_range at microsecond resolution, so a bare
    # astype('int64') would hand window_ids microseconds and collapse every window into one.
    ts = (pd.to_datetime(df[ts_col], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
          .astype("datetime64[ns]").astype("int64").to_numpy())
    X = np.column_stack([df[c].to_numpy(dtype=float) for c in ds["features"]])
    res: dict[str, Any] = {"n_rows": len(df), "classes": [str(c) for c in classes], "arm": learner_name}
    if status:
        res["arm_status"] = "unavailable"
        res["reason"] = status
        return res
    folds = mb.purged_folds(len(df), int(cv.get("folds", 5)), int(cv.get("embargo_rows", 0)),
                            float(cv.get("min_train_frac", 0.4)))
    fit = mb.LEARNERS[learner["kind"]][0]
    embargo = int(cv.get("embargo_rows", 0))
    calib_frac = float(cfg.get("calib_frac", 0.25))
    per_fold: list[dict[str, Any]] = []
    covered_by_level: dict[str, list[np.ndarray]] = {str(float(c)): [] for c in cfg["coverage_levels"]}
    ts_by_level: dict[str, list[np.ndarray]] = {str(float(c)): [] for c in cfg["coverage_levels"]}
    try:
        for tr, te in folds:
            n_cal = int(len(tr) * calib_frac)
            fit_idx = tr[: max(0, len(tr) - n_cal - embargo)]
            cal_idx = tr[len(tr) - n_cal:]
            if len(fit_idx) < 50 or len(cal_idx) < 50 or len(te) < 20:
                continue
            # ONE fit per fold, scored on calibration + test together (a learner refit between the two
            # blocks would break the exchangeability the conformal guarantee rests on)
            P_both = fit(X[fit_idx], y[fit_idx], np.vstack([X[cal_idx], X[te]]), k, dict(learner.get("params") or {}))
            P_cal, P_te = P_both[: len(cal_idx)], P_both[len(cal_idx):]
            P = np.zeros((len(df), k))
            P[cal_idx] = P_cal
            P[te] = P_te
            cal_mask = np.zeros(len(df), dtype=bool)
            cal_mask[cal_idx] = True
            te_mask = np.zeros(len(df), dtype=bool)
            te_mask[te] = True
            r = evaluate_stream(ts, P, y, cal_mask, te_mask, cfg)
            for lvl, d in r["levels"].items():
                covered_by_level[lvl].append(d.pop("_covered"))
                ts_by_level[lvl].append(d.pop("_ts"))
            per_fold.append(r)
    except mb.Unavailable as e:
        return {**res, "arm_status": "unavailable", "reason": str(e)}
    except Exception as e:  # allow-silent: one group breaking is contained and recorded as arm_status=error in the result
        return {**res, "arm_status": "error", "reason": f"{type(e).__name__}: {e}"}
    res["arm_status"] = "ok"
    res["n_folds"] = len(per_fold)
    res["folds"] = per_fold
    # pooled OOS verdict per level: selective errors are averaged over folds (paired), validity over windows
    levels: dict[str, Any] = {}
    for lvl in covered_by_level:
        se_plain = [f["levels"][lvl]["plain"]["selective_error"] for f in per_fold]
        se_conf = [f["levels"][lvl]["conformal"]["selective_error"] for f in per_fold]
        pairs = [(a, b) for a, b in zip(se_plain, se_conf) if a is not None and b is not None]
        d = mb.paired_delta([a for a, _ in pairs], [b for _, b in pairs]) if pairs else {"n_folds": 0, "mean": None}
        nominal = [f["levels"][lvl]["conformal"]["nominal_coverage"] for f in per_fold]
        n_cals = [f["n_cal"] for f in per_fold]
        win_rows = []
        if covered_by_level[lvl]:
            cov_all = np.concatenate(covered_by_level[lvl])
            ts_all = np.concatenate(ts_by_level[lvl])
            nom_all = np.concatenate([np.full(len(c), n) for c, n in zip(covered_by_level[lvl], nominal)])
            ncal_all = np.concatenate([np.full(len(c), n) for c, n in zip(covered_by_level[lvl], n_cals)])
            order = np.argsort(ts_all)
            cov_all, ts_all, nom_all, ncal_all = cov_all[order], ts_all[order], nom_all[order], ncal_all[order]
            wid = window_ids(ts_all, int(cfg.get("window_days", 30)))
            for w in np.unique(wid):
                m = wid == w
                if m.sum() < int(cfg.get("min_window_rows", 200)):
                    continue
                emp, nom = float(cov_all[m].mean()), float(nom_all[m].mean())
                # SE of a window's empirical coverage around nominal: the test-window binomial term PLUS the
                # calibration term (coverage conditional on one calibration set of size n_cal varies ~Beta,
                # Vovk 2012, sd ~ sqrt(nom(1-nom)/n_cal)); a fixed band ignores the second term.
                var = max(nom * (1.0 - nom), 1e-9)
                se = math.sqrt(var / float(m.sum()) + var / float(max(ncal_all[m].mean(), 1.0)))
                win_rows.append({"window": int(w), "n": int(m.sum()), "empirical": emp, "nominal": nom, "se": se,
                                 "within_tol": abs(emp - nom) <= float(cfg.get("validity_tol", 0.03)),
                                 "within_2se": abs(emp - nom) <= 2.0 * se})
            mode = str(cfg.get("validity_mode", "2se"))
            for w in win_rows:
                w["valid"] = w["within_2se"] if mode == "2se" else w["within_tol"]
        n_valid = sum(1 for w in win_rows if w["valid"])
        n_valid_tol = sum(1 for w in win_rows if w["within_tol"])
        n_valid_2se = sum(1 for w in win_rows if w["within_2se"])
        matched_all = all(f["levels"][lvl]["coverage_matched"] for f in per_fold) if per_fold else False
        levels[lvl] = {
            "selective_error_plain_mean": float(np.mean([a for a, _ in pairs])) if pairs else None,
            "selective_error_conformal_mean": float(np.mean([b for _, b in pairs])) if pairs else None,
            "delta_plain_minus_conformal": d,   # positive = conformal has LOWER selective error
            "conformal_lower": bool(d.get("mean") is not None and d["mean"] > 0),
            "coverage_matched_all_folds": matched_all,
            "windows": win_rows, "n_windows": len(win_rows), "n_valid_windows": n_valid,
            "validity_mode": str(cfg.get("validity_mode", "2se")),
            "valid_share": (n_valid / len(win_rows)) if win_rows else None,
            "valid_share_tol": (n_valid_tol / len(win_rows)) if win_rows else None,
            "valid_share_2se": (n_valid_2se / len(win_rows)) if win_rows else None,
        }
    res["levels"] = levels
    n_w = min((lv["n_windows"] for lv in levels.values()), default=0)
    res["n_windows_min"] = int(n_w)
    res["enough_windows"] = n_w >= int(cfg.get("min_windows", 6))
    res["gain_all_levels"] = all(lv["conformal_lower"] for lv in levels.values()) if levels else False
    res["valid_all_levels"] = all((lv["valid_share"] or 0.0) >= float(cfg.get("validity_min_share", 0.9))
                                  for lv in levels.values()) if levels else False
    res["coverage_matched_all_levels"] = all(lv["coverage_matched_all_folds"] for lv in levels.values()) if levels else False
    res["group_pass"] = bool(res["enough_windows"] and res["coverage_matched_all_levels"]
                             and res["gain_all_levels"] and res["valid_all_levels"])
    # a level whose coverage could not be matched is NOT a comparison: it can neither pass nor fail
    res["group_fail"] = bool(res["enough_windows"] and res["coverage_matched_all_levels"]
                             and not (res["gain_all_levels"] and res["valid_all_levels"]))
    return res


# ── the registered rule ─────────────────────────────────────────────────────
def evaluate_rule(groups: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    rule = {**DEFAULTS["rule"], **(cfg.get("rule") or {})}
    status = {g: r.get("arm_status") for g, r in groups.items()}
    if any(s != "ok" for s in status.values()):
        return {"verdict": "indeterminate", "why": f"arm unavailable/error on {sorted(g for g, s in status.items() if s != 'ok')}"}
    short = [g for g, r in groups.items() if not r.get("enough_windows")]
    if short:
        return {"verdict": "indeterminate", "why": f"fewer than min_windows usable windows on {short}"}
    passing = sorted(g for g, r in groups.items() if r.get("group_pass"))
    failing = sorted(g for g, r in groups.items() if r.get("group_fail"))
    if len(passing) >= int(rule["pass_symbols_min"]):
        return {"verdict": "pass", "why": f"conformal lower selective error at every level AND valid windows on {passing}",
                "passing": passing, "failing": failing}
    if len(failing) >= int(rule["fail_symbols_min"]):
        return {"verdict": "fail", "why": f"gain or validity fails on {failing}", "passing": passing, "failing": failing}
    return {"verdict": "indeterminate", "why": "between the pass bar and the fail floor", "passing": passing, "failing": failing}


def run_unit_spec(bakeoff: dict[str, Any], conformal: dict[str, Any], *, unit: str = "(inline)",
                  gdata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one unit's (ml_bakeoff, conformal) pair end to end; returns the verdict.json dict.
    ``gdata`` (tests) injects {group: DataFrame} in place of ``ml_bakeoff.load_groups``."""
    t0 = time.time()
    cfg = {**DEFAULTS, **(conformal or {})}
    learner_name = str(cfg.get("learner") or "")
    learners = bakeoff.get("learners") or {}
    if learner_name not in learners:
        raise ValueError(f"conformal.learner {learner_name!r} is not in ml_bakeoff.learners {sorted(learners)}")
    learner = learners[learner_name]
    status = mb.probe_learner(learner["kind"], learner.get("params") or {})
    gdata = mb.load_groups(bakeoff["dataset"]) if gdata is None else gdata
    groups = {g: run_group(df, bakeoff, cfg, learner_name, learner, status) for g, df in gdata.items()}
    graded = evaluate_rule(groups, cfg)
    n = sum(sum(f["n_test"] for f in r.get("folds", [])) for r in groups.values() if r.get("arm_status") == "ok")
    measurement = {"engine": "scripts/research/conformal_abstain_eval.py", "learner": learner_name,
                   "learner_kind": learner["kind"], "licence": mb.LEARNERS[learner["kind"]][1],
                   "config": {k: v for k, v in cfg.items()}, "groups": groups, "rule_evaluation": graded,
                   "delta_sign": "delta_plain_minus_conformal > 0 = conformal has LOWER selective error",
                   "seconds": round(time.time() - t0, 1)}
    if all(r.get("arm_status") != "ok" for r in groups.values()):
        return {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                "population": f"{unit}: the learner arm {learner_name!r} could not run on any group -- NEVER MEASURED",
                "note": "; ".join(f"{g}: {r.get('reason')}" for g, r in groups.items()), "measurement": measurement}
    if n == 0:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0,
                "population": f"{unit}: no usable folds (dataset too short for cv.folds/embargo/calib_frac)",
                "note": "no_data: looked, zero evaluable test rows", "measurement": measurement}
    return {"verdict": graded["verdict"], "read_state": "measured", "n": int(n),
            "population": (f"{len(groups)} group(s) {sorted(groups)}; learner {learner_name}; coverage levels "
                           f"{cfg['coverage_levels']}; n = OOS test rows summed over folds and groups; "
                           f"windows of {cfg['window_days']} d, min {cfg['min_windows']} per group"),
            "note": graded["why"], "measurement": measurement}


def load_unit(unit: str, queue_dir: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    import yaml
    qd = queue_dir or (_REPO / "research" / "queue")
    raw = yaml.safe_load((qd / f"{unit}.yaml").read_text(encoding="utf-8")) or {}
    bakeoff, conformal = raw.get("ml_bakeoff"), raw.get("conformal")
    if not isinstance(bakeoff, dict) or not isinstance(conformal, dict):
        raise ValueError(f"{unit}: needs both an `ml_bakeoff:` (dataset/cv/learners) and a `conformal:` block")
    return bakeoff, conformal


# ── self-test: exchangeable synthetic data must give nominal coverage ─────────
def _linear_synthetic(n: int, seed: int):
    """Exchangeable rows with a LINEARLY separable-ish 3-class latent, so the dependency-free logit is an
    informative scorer (ml_bakeoff's synthetic frame has an x0*x1 interaction a logit cannot learn, which
    leaves every nonconformity score at ~2/3 and makes the quantile ill-conditioned -- a test of the
    learner, not of the conformal mechanics)."""
    import pandas as pd
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 4))
    logits = np.column_stack([1.5 * x[:, 0] - 0.5 * x[:, 2], 1.5 * x[:, 1] + 0.5 * x[:, 3], -0.8 * (x[:, 0] + x[:, 1])])
    logits += rng.gumbel(size=logits.shape)
    y = np.argmax(logits, axis=1)
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"ts": ts, "x0": x[:, 0], "x1": x[:, 1], "x2": x[:, 2], "x3": x[:, 3], "label": y})


def _self_test() -> int:
    bakeoff = {"dataset": {"kind": "synthetic", "ts_col": "ts", "target": "label", "features": ["x0", "x1", "x2", "x3"]},
               "cv": {"folds": 4, "embargo_rows": 10, "min_train_frac": 0.4},
               "learners": {"logit": {"kind": "numpy_logit"}}}
    conformal = {"learner": "logit", "window_days": 7, "min_window_rows": 300, "min_windows": 3}
    gdata = {g: _linear_synthetic(12000, 11 + i) for i, g in enumerate(("A", "B", "C"))}
    v = run_unit_spec(bakeoff, conformal, unit="selftest", gdata=gdata)
    assert v["read_state"] == "measured", v
    for g, r in v["measurement"]["groups"].items():
        assert r["arm_status"] == "ok", r
        for lvl, lv in r["levels"].items():
            # exchangeable data: pooled empirical set coverage within 3 points of nominal
            pooled = np.average([w["empirical"] for w in lv["windows"]], weights=[w["n"] for w in lv["windows"]])
            nominal = np.average([w["nominal"] for w in lv["windows"]], weights=[w["n"] for w in lv["windows"]])
            assert abs(pooled - nominal) <= 0.03, (g, lvl, pooled, nominal)
            assert lv["n_windows"] >= 3, (g, lvl, lv["n_windows"])
            # exchangeable data: window coverage sits inside 2 SE of nominal almost always
            assert lv["valid_share_2se"] >= 0.8, (g, lvl, lv["valid_share_2se"])
            # matched coverage: an informative scorer keeps ~c of the rows under BOTH rules
            assert lv["coverage_matched_all_folds"], (g, lvl)
    # the finite-sample quantile: n too small for the level -> inf (full set, never a false singleton)
    assert conformal_quantile(np.array([0.1, 0.2]), 0.05) == float("inf")
    assert conformal_quantile(np.arange(1, 101) / 100.0, 0.10) == 0.91
    print("conformal_abstain_eval self-test OK:", v["verdict"], v["note"][:90])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit")
    ap.add_argument("--out", help="directory to write verdict.json into")
    ap.add_argument("--queue-dir", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.unit or not a.out:
        ap.error("--unit and --out are required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        bakeoff, conformal = load_unit(a.unit, Path(a.queue_dir) if a.queue_dir else None)
        verdict = run_unit_spec(bakeoff, conformal, unit=a.unit)
    except Exception as e:  # allow-silent: error.txt + stderr + exit 1; script_run derives producer_failed
        (out / "error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
        print(f"conformal_abstain_eval: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"conformal_abstain_eval {a.unit}: verdict={verdict['verdict']} read_state={verdict['read_state']} n={verdict['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
