#!/usr/bin/env python3
# wiring: research/queue RQ-20261101-78fc-05 via .github/workflows/research-script-run.yml (row ML-HOLDBIAS-EXIT-MODEL); no schedule consumes it.
"""exit-holdbias-v1: the conservative hold-biased exit/management model, trained and graded on the action-grid labels.

Plan docs/plans/ml-live-promotion-plan-2026-10-29.md section 2a (P6), unit research/queue RQ-20261101-78fc-05, row
ML-HOLDBIAS-EXIT-MODEL. Operator (relayed 2026-10-28): "a conservative production ML that will mostly recommend holding
outside of edge cases".

INPUT    The action-grid labels of scripts/research/desk_lifecycle_driver.py --action-grid (ML-EXIT-ACTIONGRID-LABELS):
         one row per check-in, the state features, `fold` (6 calendar folds by entry), `leg`, and
         labels{action: {feasible, value_r}} with value_r = net R(action at this check-in, hold after) - net R(hold).
         Default: corpus B (the six crypto real-money legs' Stage-0 trades), the population the unit registers.
MODEL    One LightGBM value head per action of the 13-action enum (each class's levels are separate heads), fit on the
         feasible rows of the TRAIN trades. State = the packet features (now_r, mfe/mae, bars held/left, distance to SL/TP
         in R and ATR, ATR ratio, 3-bar momentum, trigger tags) + leg fixed effects. Fixed hyper-parameters (below),
         never tuned on a test fold.
DECISION Fixed before any run (plan section 2a): at a check-in, emit the best FEASIBLE action only if its predicted value
         beats hold by >= TAU_R = 0.15 R; otherwise HOLD.
POLICY   As-if-applied, one intervention per trade: the FIRST check-in where the model emits a non-hold action applies it;
         the rest of the path is hold-to-bracket. The trade's dR vs hold is that action's realized value_r (0 if the
         model never acts). The labels are one-step, so a second action on the same trade cannot be priced; stated.
FOLDS    Walk-forward over the 6 calendar folds by entry. Each fold is the test set once; its train set is every other
         trade NOT purged: a train trade is dropped when [first check-in, last check-in + embargo] overlaps the test
         fold's window, embargo = the longest trade span in the corpus (cross-leg, cross-symbol).
RULE     RULE-RQ-20261101-78fc-05 (registered 2026-11-01, plan section 2a sanity rule registered 2026-10-28), UNCHANGED:
         PASS iff  (a) trade-bootstrap 95% lower bound of the pooled mean dR > -0.01 R/trade
              AND  (b) advice rate (check-ins where the model emits non-hold / all held-out check-ins) <= 15%
              AND  (c) no leg's mean dR < -0.05 R/trade.
         FAIL otherwise. INDETERMINATE if fewer than 500 held-out trades.
REPORTED, NOT GRADED  a matched-random policy (per fold: the same number of acting trades and the same action mix, each
         at a random check-in of a random trade; 200 draws), per-fold and per-leg dR, the action mix.

Tier-1 research code: reads committed labels, writes only --out. Trains nothing persistent, registers, serves or promotes
nothing.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LABELS = REPO / "comms" / "research" / "desk_lifecycle" / "action-grid" / "corpus-b" / "grid_labels.jsonl.gz"

# ---------------------------------------------------------------- registered (plan section 2a / RULE-RQ-20261101-78fc-05)
TAU_R = 0.15
LB_FLOOR_R = -0.01
ADVICE_RATE_MAX = 0.15
LEG_FLOOR_R = -0.05
MIN_HELDOUT_TRADES = 500
SEED = 20261101
N_BOOT = 10_000
RANDOM_DRAWS = 200
LGBM_PARAMS = {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 100,
               "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.9, "reg_lambda": 1.0, "verbose": -1}
NUM_FEATURES = ("now_r", "stop_r", "tp_r", "mfe_r", "mae_r", "bars_held", "bars_left", "dist_sl_r", "dist_tp_r",
                "atr_r", "dist_sl_atr", "dist_tp_atr", "atr_ratio", "mom3_r")


def read_labels(path: Path) -> List[dict]:
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def build_matrix(rows: List[dict]) -> Dict[str, Any]:
    """X (check-ins x features), per-action value / feasibility arrays, trade + fold + leg indices."""
    actions = sorted({a for r in rows for a in r["labels"]})
    tags = sorted({t for r in rows for t in (r.get("tags") or [])})
    legs = sorted({r.get("leg") or "" for r in rows})
    n = len(rows)
    X = np.full((n, len(NUM_FEATURES) + len(tags) + len(legs)), np.nan)
    V = np.full((n, len(actions)), np.nan)
    for i, r in enumerate(rows):
        for j, f in enumerate(NUM_FEATURES):
            v = r.get(f)
            X[i, j] = float(v) if v is not None else np.nan
        ts = set(r.get("tags") or [])
        for j, t in enumerate(tags):
            X[i, len(NUM_FEATURES) + j] = 1.0 if t in ts else 0.0
        for j, lg in enumerate(legs):
            X[i, len(NUM_FEATURES) + len(tags) + j] = 1.0 if (r.get("leg") or "") == lg else 0.0
        for j, a in enumerate(actions):
            lab = r["labels"].get(a) or {}
            if lab.get("feasible") and lab.get("value_r") is not None:
                V[i, j] = float(lab["value_r"])
    tid = np.array([r["entry_id"] for r in rows])
    return {"X": X, "V": V, "actions": actions, "feature_names": list(NUM_FEATURES) + [f"tag:{t}" for t in tags]
            + [f"leg:{lg}" for lg in legs], "trade": tid, "fold": np.array([int(r["fold"]) for r in rows]),
            "leg": np.array([r.get("leg") or "" for r in rows]), "k": np.array([int(r["k"]) for r in rows]),
            "t": np.array([int(r["bar_t"]) for r in rows], dtype=np.int64)}


def purged_train_mask(M: Dict[str, Any], test_fold: int) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Check-in mask of the train set for `test_fold`, with the trade-level purge + embargo; and what was dropped."""
    trades = defaultdict(lambda: [np.iinfo(np.int64).max, np.iinfo(np.int64).min, -1])
    for tr, t, f in zip(M["trade"], M["t"], M["fold"]):
        s = trades[tr]
        s[0], s[1], s[2] = min(s[0], t), max(s[1], t), f
    emb = max(int(v[1] - v[0]) for v in trades.values()) if trades else 0
    test = [v for v in trades.values() if v[2] == test_fold]
    if not test:
        return np.zeros(len(M["trade"]), dtype=bool), {"embargo_s": emb, "purged_trades": 0, "test_trades": 0}
    w0, w1 = min(v[0] for v in test), max(v[1] for v in test)
    keep = {tr for tr, v in trades.items() if v[2] != test_fold and not (v[1] + emb >= w0 and v[0] <= w1 + emb)}
    purged = sum(1 for tr, v in trades.items() if v[2] != test_fold and tr not in keep)
    return (np.array([tr in keep for tr in M["trade"]]),
            {"embargo_s": emb, "window": [int(w0), int(w1)], "purged_trades": purged, "train_trades": len(keep),
             "test_trades": len(test)})


def fit_heads(X: np.ndarray, V: np.ndarray, mask: np.ndarray, seed: int) -> List[Any]:
    from lightgbm import LGBMRegressor  # noqa: PLC0415  (installed by research-script-run.yml, lightgbm==4.6.0)
    heads: List[Any] = []
    for j in range(V.shape[1]):
        m = mask & np.isfinite(V[:, j])
        if m.sum() < LGBM_PARAMS["min_child_samples"] * 2:
            heads.append(None)
            continue
        h = LGBMRegressor(random_state=seed, **LGBM_PARAMS)
        h.fit(X[m], V[m, j])
        heads.append(h)
    return heads


def decide(heads: Sequence[Any], X: np.ndarray, V: np.ndarray, tau: float = TAU_R) -> Tuple[np.ndarray, np.ndarray]:
    """(action index or -1 = HOLD, predicted value) per check-in: the best FEASIBLE head, acted on only at >= tau."""
    P = np.full(V.shape, -np.inf)
    for j, h in enumerate(heads):
        if h is not None:
            P[:, j] = h.predict(X)
    P[~np.isfinite(V)] = -np.inf
    best = P.argmax(axis=1)
    pv = P[np.arange(len(best)), best]
    act = np.where(pv >= tau, best, -1)
    return act, pv


def as_if_applied(M: Dict[str, Any], idx: np.ndarray, act: np.ndarray) -> Dict[str, Tuple[float, Optional[int]]]:
    """{trade: (dR vs hold, action index or None)} -- the first acted check-in's realized value, else 0."""
    order = np.lexsort((M["k"][idx], M["trade"][idx]))
    out: Dict[str, Tuple[float, Optional[int]]] = {}
    for o in order:
        i = idx[o]
        tr = M["trade"][i]
        if tr in out and out[tr][1] is not None:
            continue
        a = int(act[o])
        if a >= 0:
            out[tr] = (float(M["V"][i, a]), a)
        elif tr not in out:
            out[tr] = (0.0, None)
    return out


def boot_lb(x: np.ndarray, seed: int = SEED, n_boot: int = N_BOOT) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    if len(x) == 0:
        return float("nan"), float("nan")
    means = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n_boot)])
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def matched_random(M: Dict[str, Any], idx: np.ndarray, policy: Dict[str, Tuple[float, Optional[int]]],
                   seed: int, draws: int = RANDOM_DRAWS) -> np.ndarray:
    """Mean dR per draw of a random policy with the model's acting-trade count and action mix on these check-ins."""
    mix = [a for _d, a in policy.values() if a is not None]
    trades = sorted(policy)
    if not mix:
        return np.zeros(draws)
    by_trade: Dict[str, List[int]] = defaultdict(list)
    for i in idx:
        by_trade[M["trade"][i]].append(int(i))
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for d in range(draws):
        pick = rng.choice(len(trades), size=len(mix), replace=False)
        tot = 0.0
        for a, p in zip(mix, pick):
            cand = [i for i in by_trade[trades[p]] if np.isfinite(M["V"][i, a])]
            tot += float(M["V"][rng.choice(cand), a]) if cand else 0.0
        out[d] = tot / len(trades)
    return out


def grade(n_trades: int, lb: float, advice_rate: float, leg_means: Dict[str, float]) -> Tuple[str, Dict[str, Any]]:
    clauses = {"a_lb_gt_floor": {"value": lb, "floor": LB_FLOOR_R, "ok": bool(lb > LB_FLOOR_R)},
               "b_advice_rate": {"value": advice_rate, "max": ADVICE_RATE_MAX, "ok": bool(advice_rate <= ADVICE_RATE_MAX)},
               "c_no_leg_below": {"worst_leg": min(leg_means.items(), key=lambda kv: kv[1]) if leg_means else None,
                                  "floor": LEG_FLOOR_R, "ok": bool(all(v >= LEG_FLOOR_R for v in leg_means.values()))}}
    if n_trades < MIN_HELDOUT_TRADES:
        return "indeterminate", clauses
    return ("pass" if all(c["ok"] for c in clauses.values()) else "fail"), clauses


def select_tau_inner(M: Dict[str, Any], outer_mask: np.ndarray, outer_fold: int, grid: Sequence[float],
                     seed: int) -> Dict[str, Any]:
    """PI-20261119-RIMARY12-0005 (iteration of 78fc-05, the MARGIN lever): choose the act margin tau INSIDE the outer
    fold's training data only. Inner leave-one-fold-out over the other folds; each inner train set is the outer
    train mask AND the inner fold's own purged mask (so neither the outer test fold nor trades near either test window
    are ever fit or scored). Pooled inner-OOF advice rate and mean dR per grid tau; SELECTED = the highest inner mean dR
    among taus with inner advice rate <= ADVICE_RATE_MAX; a tie goes to the LARGER tau (more hold-biased). If no tau
    meets the cap, the largest grid tau is used and flagged (``cap_unreachable``). The outer test fold is not read."""
    inner_folds = sorted({int(f) for f in M["fold"][outer_mask].tolist()} - {int(outer_fold)})
    pooled = {t: {"checkins": 0, "advice": 0, "dR": []} for t in grid}
    for g in inner_folds:
        in_mask, _p = purged_train_mask(M, g)
        fit_mask = outer_mask & in_mask
        idx = np.where(outer_mask & (M["fold"] == g))[0]
        if not len(idx) or not fit_mask.any():
            continue
        heads = fit_heads(M["X"], M["V"], fit_mask, seed)
        best, pv = decide(heads, M["X"][idx], M["V"][idx], tau=-np.inf)   # tau -inf: the best feasible head everywhere
        for t in grid:
            act = np.where(pv >= t, best, -1)
            pooled[t]["checkins"] += len(idx)
            pooled[t]["advice"] += int((act >= 0).sum())
            pooled[t]["dR"] += [v for v, _a in as_if_applied(M, idx, act).values()]
    table = []
    for t in grid:
        c = pooled[t]
        table.append({"tau": t, "advice_rate": (c["advice"] / c["checkins"]) if c["checkins"] else None,
                      "mean_dR": float(np.mean(c["dR"])) if c["dR"] else None, "trades": len(c["dR"])})
    ok = [r for r in table if r["advice_rate"] is not None and r["mean_dR"] is not None and r["advice_rate"] <= ADVICE_RATE_MAX]
    if ok:
        best_v = max(r["mean_dR"] for r in ok)
        sel = max((r for r in ok if abs(r["mean_dR"] - best_v) <= 1e-12), key=lambda r: r["tau"])
        return {"selected_tau": sel["tau"], "cap_unreachable": False, "inner_folds": inner_folds, "table": table}
    return {"selected_tau": max(grid), "cap_unreachable": True, "inner_folds": inner_folds, "table": table}


def run(labels: Path, seed: int = SEED, n_boot: int = N_BOOT, draws: int = RANDOM_DRAWS,
        tau_grid: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """``tau_grid`` None = the registered fixed TAU_R (78fc-05, byte-identical); a grid = tau chosen per outer fold by
    ``select_tau_inner`` on that fold's training data only."""
    rows = read_labels(labels)
    M = build_matrix(rows)
    folds = sorted(set(M["fold"].tolist()))
    pol: Dict[str, Tuple[float, Optional[int]]] = {}
    n_checkins = n_advice = 0
    per_fold: Dict[str, Any] = {}
    rand_by_fold: List[np.ndarray] = []
    rand_w: List[int] = []
    for f in folds:
        tr_mask, purge = purged_train_mask(M, f)
        tau_sel = select_tau_inner(M, tr_mask, f, tau_grid, seed) if tau_grid else None
        heads = fit_heads(M["X"], M["V"], tr_mask, seed)
        idx = np.where(M["fold"] == f)[0]
        act, _pv = decide(heads, M["X"][idx], M["V"][idx], tau=tau_sel["selected_tau"] if tau_sel else TAU_R)
        n_checkins += len(idx)
        n_advice += int((act >= 0).sum())
        p = as_if_applied(M, idx, act)
        pol.update(p)
        d = np.array([v for v, _a in p.values()])
        rnd = matched_random(M, idx, p, seed + f, draws)
        rand_by_fold.append(rnd)
        rand_w.append(len(p))
        per_fold[str(f)] = {"trades": len(p), "checkins": int(len(idx)), "advice_rate": float((act >= 0).mean()),
                            "acted_trades": sum(1 for _v, a in p.values() if a is not None),
                            "mean_dR": float(d.mean()) if len(d) else None, "matched_random_mean_dR": float(rnd.mean()),
                            "heads_fit": sum(h is not None for h in heads), "purge": purge,
                            **({"tau_selection": tau_sel} if tau_sel else {})}
    dR = np.array([v for v, _a in pol.values()])
    leg_of = {str(tr): str(lg) for tr, lg in zip(M["trade"], M["leg"])}
    by_leg: Dict[str, List[float]] = defaultdict(list)
    for tr, (v, _a) in pol.items():
        by_leg[leg_of[str(tr)]].append(v)
    leg_means = {lg: float(np.mean(v)) for lg, v in by_leg.items()}
    lb, ub = boot_lb(dR, seed, n_boot)
    advice_rate = n_advice / n_checkins if n_checkins else float("nan")
    verdict, clauses = grade(len(dR), lb, advice_rate, leg_means)
    rnd_pooled = sum(r * w for r, w in zip(rand_by_fold, rand_w)) / max(1, sum(rand_w))
    mix = defaultdict(int)
    for _v, a in pol.values():
        if a is not None:
            mix[M["actions"][a]] += 1
    sha = hashlib.sha256(Path(labels).read_bytes()).hexdigest()
    return {
        "verdict": verdict, "read_state": "measured" if len(dR) else "no_data", "n": int(len(dR)) if len(dR) else None,
        "population": f"{len(dR)} held-out trades ({n_checkins} check-ins) over {len(folds)} calendar folds, legs "
                      f"{sorted(by_leg)}; labels {labels.name} sha256 {sha[:16]}",
        "rule": ("RULE-RQ-20261101-78fc-05 (plan docs/plans/ml-live-promotion-plan-2026-10-29.md section 2a sanity rule), unchanged"
                 if not tau_grid else "the 78fc-05 clauses (a)-(c), unchanged, with tau selected per fold on training data (--tau-grid)"),
        "clauses": clauses,
        "measurement": {"mean_dR_per_trade": float(dR.mean()) if len(dR) else None, "lb95": lb, "ub95": ub,
                        "advice_rate": advice_rate, "acted_trades": sum(1 for _v, a in pol.values() if a is not None),
                        "per_leg_mean_dR": leg_means, "per_leg_trades": {lg: len(v) for lg, v in by_leg.items()},
                        "action_mix": dict(mix), "per_fold": per_fold,
                        "matched_random": {"draws": draws, "mean_dR": float(rnd_pooled.mean()),
                                           "p_random_ge_model": float((rnd_pooled >= (dR.mean() if len(dR) else 0)).mean()),
                                           "graded": False}},
        "config": {"tau_r": TAU_R if not tau_grid else "per-fold inner selection (see per_fold.tau_selection)",
                   "tau_grid": list(tau_grid) if tau_grid else None, "lgbm": LGBM_PARAMS, "seed": seed, "n_boot": n_boot, "features": M["feature_names"],
                   "actions": M["actions"], "labels": str(labels), "labels_sha256": sha},
        "stated_limits": ["one intervention per trade: after the first action the path is hold-to-bracket (one-step labels)",
                          "corpus B = harness Stage-0 trades on their INITIAL bracket on 1h candles, not live paths and not "
                          "the leg's own trail; iaum_pullback_1d is out of scope",
                          "matched random is reported, not graded (the registered rule has no random clause)"],
        "what_it_does_not_do": "Trains nothing persistent; registers, serves, promotes or applies nothing; changes no config.",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--draws", type=int, default=RANDOM_DRAWS)
    ap.add_argument("--tau-grid", default=None,
                    help="comma list: choose tau per outer fold on its training data only (default off = fixed TAU_R)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        grid = [float(x) for x in a.tau_grid.split(",") if x.strip()] if a.tau_grid else None
        v = run(Path(a.labels), a.seed, a.n_boot, a.draws, tau_grid=grid)
    except Exception as exc:  # noqa: BLE001  # allow-silent: written as a producer_failed record with the error, never a pass
        v = {"verdict": "indeterminate", "read_state": "producer_failed", "n": None, "error": repr(exc)[:600],
             "population": None}
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=float) + "\n")
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "n", "population")}))
    return 0 if v.get("read_state") != "producer_failed" else 1


if __name__ == "__main__":
    sys.exit(main())
