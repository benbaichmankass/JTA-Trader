#!/usr/bin/env python3
"""ML-AM-NEXT-LIVE: an ML-gated PARTIAL CLOSE (an in-trade de-risk action) on the real-money legs, graded
non-inferior on net R AND risk-reducing under RULE-AM-RISK-ADJUSTED-V1, against a matched random partial close.

THE POLICY (one action class, reduce only; both brackets stay on the remainder -- ARCHITECTURE § Active management
clause 3): at every closed bar of an open trade, a logistic head scores P(holding to the leg's own exit loses to
exiting now by more than the exit cost) on the R1 state of RQ-20261024-09a6-01 (open R, peak R, bars held, bars
since peak, room to the IN-FORCE stop and target in ATR, momentum 3/6, ADX and its slope, 3-bar range, close
location, leg fixed effects; `first_passage_paths.events`, which also defines the label). The FIRST bar whose score
is >= tau (the q-quantile of the training states' scores) closes 50% of the position at that bar's close; the rest
rides the leg's own stop/target unchanged. At most one action per trade.

PRICING (the d6e7-06 construction, scaled by the fraction): a full close at bar b nets
  pol_b = open_r_b - fee - slippage - funding * (b+1)/bars - c_exit
(c_exit: an EXTRA exit slippage charge, conservative: the harness already charges exit slippage in net_r), so
  delta_b = F * (pol_b - net_r),  F = 0.5,
on a harness path whose stop/target are price levels the partial does not move. Units: R of initial risk, net of
the full cost stack (fee + slippage + funding, the harness venue policy).

VALIDATION: CPCV over the pooled gate legs (6 calendar groups by entry, 2 test groups: 15 splits, 5 paths), purge
of training trades overlapping a test block, 7-day embargo (`ml_overlay_noninferior.cpcv_splits`); each trade's
delta is the mean of its 5 OOS decisions. Training is trade-weighted (each trade's states sum to weight 1).
Fresh-window holdout: the primary model fit on the whole main window scores the gate legs' trades of 2017-09-01 ..
2020-06-23 (entry before 2020-07-01 minus the embargo).

RANDOM CONTROL (same class, same rate, practice T1/M6): per draw, the policy's per-trade fire weights are permuted
within each calendar group, and each weighted trade is partially closed at a UNIFORMLY drawn bar of its own
decision bars (2,000 draws).

Usage:
  python3 scripts/research/ml_am_partial_noninferior.py --out <dir>   (the registered run; see the unit)
  python3 scripts/research/ml_am_partial_noninferior.py --self-test
Observe-only research: fetches public candles, writes only under --out. Places no order, edits no config.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import first_passage_paths as fpp  # noqa: E402
from ml_overlay_noninferior import (  # noqa: E402
    cpcv_splits,
    cvar5,
    max_dd,
    month_block_lb,
    predict,
)

RULE_ID = "RULE-ML-AM-PARTIAL-V1"
GATE_FAMILIES = {"TD": ["trend_donchian_eth_4h", "trend_donchian_xrp_4h", "trend_donchian_eth_prop",
                        "trend_donchian_sol_prop"],
                 "PB2H": ["ada_pullback_2h", "xrp_pullback_2h"]}
FRACTION = 0.5
PRIMARY = {"C": 0.1, "q": 0.90}
GRID = [{"C": c, "q": q} for c in (0.1, 1.0) for q in (0.80, 0.90, 0.95)]
NI_MARGIN = -0.02          # canary non-inferiority margin (RULE-ML-OVERLAY-NONINFERIOR-V1/V2)
COST_CAP = -0.05           # RULE-AM-RISK-ADJUSTED-V1: give up at most 0.05 R/trade
RISK_CUT = 0.15            # ... while cutting maxDD or CVaR5 by >= 15%
LEG_FLOOR = -0.05          # no gate leg (n >= LEG_N) worse than this
LEG_N = 100
ALPHA = 0.05
RANDOM_PCTL = 0.90
FIRE_MIN, FIRE_MAX = 0.05, 0.60
FOLDS_NEEDED = 4
N_RAND = 2000
N_GATE_MIN = 200
HOLDOUT_N_MIN = 100
EMBARGO = pd.Timedelta(days=7)
SEED = 20261029


# ------------------------------------------------------------------------------------------------ model
def fit_logistic_w(X: np.ndarray, y: np.ndarray, w: np.ndarray, C: float, iters: int = 60):
    """Weighted L2 logistic by IRLS (penalty 1/(2C)||coef||^2 on the trade-count scale, intercept unpenalised)."""
    n, p = X.shape
    Xa = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(p + 1)
    lam = np.full(p + 1, 1.0 / C)
    lam[0] = 0.0
    for _ in range(iters):
        mu = 1.0 / (1.0 + np.exp(-np.clip(Xa @ beta, -30, 30)))
        g = Xa.T @ (w * (mu - y)) + lam * beta
        H = (Xa * (w * mu * (1 - mu))[:, None]).T @ Xa + np.diag(lam) + 1e-9 * np.eye(p + 1)
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta[1:], float(beta[0])


def fit_head(ev: list[dict], idx: np.ndarray, C: float, q: float) -> dict:
    """Fit on the states of trades `idx`; NaN -> training median; standardise on training states."""
    X = np.vstack([ev[i]["X1"] for i in idx if ev[i]["n"]])
    y = np.concatenate([ev[i]["y"] for i in idx if ev[i]["n"]])
    w = np.concatenate([np.full(ev[i]["n"], 1.0 / ev[i]["n"]) for i in idx if ev[i]["n"]])
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    X = np.where(np.isfinite(X), X, med)
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    coef, b = fit_logistic_w((X - mu) / sd, y, w, C)
    tau = float(np.quantile(predict((X - mu) / sd, coef, b), q))
    return {"median": med, "mean": mu, "std": sd, "coef": coef, "intercept": b, "tau": tau, "C": C, "q": q,
            "n_train_trades": len(idx), "n_train_states": len(y)}


def score(head: dict, X: np.ndarray) -> np.ndarray:
    X = np.where(np.isfinite(X), X, head["median"])
    return predict((X - head["mean"]) / head["std"], head["coef"], head["intercept"])


def delta_full(t: dict, e: dict) -> np.ndarray:
    """Per decision bar: a FULL close there minus the trade's own net (the d6e7-06 pricing)."""
    b = np.arange(e["n"])
    pol = e["x"] - t["cost_fee_r"] - t["cost_slippage_r"] - t["cost_funding_r"] * (b + 1) / t["bars"] - t["c_exit"]
    return pol - t["net_r"]


def first_fire(head: dict, e: dict) -> int | None:
    if not e["n"]:
        return None
    hit = np.nonzero(score(head, e["X1"]) >= head["tau"])[0]
    return int(hit[0]) if len(hit) else None


def events(t: dict, fe_legs: list[str]) -> dict:
    """first_passage_paths.events plus the per-bar peak R (for the static giveback rule)."""
    e = fpp.events(t, fe_legs)
    if e["n"]:
        e["peak"] = t["peak_r"][:e["n"]]
    return e


# Static partial-close rules (practice T1 best_static): partial at the first bar where the rule fires.
STATIC_RULES = {
    "open_ge_0.5r": lambda e: e["x"] >= 0.5,
    "open_ge_1r": lambda e: e["x"] >= 1.0,
    "open_ge_2r": lambda e: e["x"] >= 2.0,
    "giveback_ge_1r": lambda e: (e["peak"] - e["x"]) >= 1.0,
    "open_le_-0.5r": lambda e: e["x"] <= -0.5,
    "bar_ge_6": lambda e: np.arange(e["n"]) + 1 >= 6,
    "bar_ge_12": lambda e: np.arange(e["n"]) + 1 >= 12,
}


def static_delta(t: dict, e: dict, rule: str) -> float:
    if not e["n"]:
        return 0.0
    hit = np.nonzero(STATIC_RULES[rule](e))[0]
    return 0.0 if not len(hit) else FRACTION * float(delta_full(t, e)[int(hit[0])])


# ------------------------------------------------------------------------------------------------ evaluation
def cpcv_policy(trades: list[dict], ev: list[dict], cfg: dict) -> dict:
    ent = pd.Series([t["entry_time"] for t in trades])
    ext = pd.Series([t["exit_time"] for t in trades])
    n = len(trades)
    paths = math.comb(5, 1)
    d = np.full((n, paths), np.nan)
    fired = np.full((n, paths), np.nan)
    ds = np.full((n, paths), np.nan)
    sd_all = {r: np.array([static_delta(trades[i], ev[i], r) for i in range(n)]) for r in STATIC_RULES}
    chosen = []
    groups = None
    for _sid, tg, train, test, g in cpcv_splits(ent, ext):
        groups = g
        head = fit_head(ev, np.where(train)[0], cfg["C"], cfg["q"])
        best = max(STATIC_RULES, key=lambda r: float(sd_all[r][train].mean()))  # selected on training trades only
        chosen.append(best)
        for i in np.where(test)[0]:
            b = first_fire(head, ev[i])
            val = 0.0 if b is None else FRACTION * float(delta_full(trades[i], ev[i])[b])
            col = int(np.sum(~np.isnan(d[i])))
            d[i, col] = val
            fired[i, col] = 0.0 if b is None else 1.0
            ds[i, col] = sd_all[best][i]
    return {"delta": np.nanmean(d, axis=1), "fire": np.nanmean(fired, axis=1), "groups": groups,
            "static_delta": np.nanmean(ds, axis=1), "static_chosen": {r: chosen.count(r) for r in set(chosen)},
            "paths_filled": int(np.min(np.sum(~np.isnan(d), axis=1)))}


def random_arm(trades, ev, fire_w, groups, rng, sel) -> dict:
    """Same-rate random partial close: weights permuted within calendar group, uniform bar per trade."""
    idx = np.where(sel)[0]
    dfs = [FRACTION * delta_full(trades[i], ev[i]) if ev[i]["n"] else np.zeros(1) for i in idx]
    lens = np.array([len(x) for x in dfs])
    flat = np.concatenate(dfs)
    off = np.r_[0, np.cumsum(lens)[:-1]]
    net = np.array([trades[i]["net_r"] for i in idx])
    order = np.argsort([trades[i]["exit_time"].value for i in idx], kind="stable")
    g = groups[idx]
    w = fire_w[idx]
    means, dds, cvs = np.empty(N_RAND), np.empty(N_RAND), np.empty(N_RAND)
    for k in range(N_RAND):
        wk = w.copy()
        for gk in np.unique(g):
            ix = np.where(g == gk)[0]
            wk[ix] = w[rng.permutation(ix)]
        b = np.minimum((rng.random(len(idx)) * lens).astype(int), lens - 1)
        dk = wk * flat[off + b]
        means[k] = dk.mean()
        r = net + dk
        dds[k] = max_dd(r[order])
        cvs[k] = cvar5(r)
    return {"mean": means, "maxdd": dds, "cvar5": cvs}


def risk(r: np.ndarray, exits: np.ndarray) -> tuple[float, float]:
    return max_dd(r[np.argsort(exits, kind="stable")]), cvar5(r)


def evaluate_family(trades, ev, res, sel, rng, n_groups: int = 6) -> dict:
    idx = np.where(sel)[0]
    n = len(idx)
    if n == 0:
        return {"n": 0, "pass": False, "checks": {}}
    delta = res["delta"][idx]
    net = np.array([trades[i]["net_r"] for i in idx])
    exits = np.array([trades[i]["exit_time"].value for i in idx])
    months = np.array([trades[i]["entry_time"].strftime("%Y-%m") for i in idx])
    pol = net + delta
    dd0, cv0 = risk(net, exits)
    dd1, cv1 = risk(pol, exits)
    lb = month_block_lb(delta, months, rng, ALPHA)
    rnd = random_arm(trades, ev, res["fire"], res["groups"], rng, sel)
    p90 = float(np.quantile(rnd["mean"], RANDOM_PCTL))
    dd_cut = (dd0 - dd1) / dd0 if dd0 > 0 else 0.0
    cv_cut = (cv1 - cv0) / abs(cv0) if cv0 < 0 else 0.0
    rnd_dd_cut = float(np.median((dd0 - rnd["maxdd"]) / dd0)) if dd0 > 0 else 0.0
    rnd_cv_cut = float(np.median((rnd["cvar5"] - cv0) / abs(cv0))) if cv0 < 0 else 0.0
    fire_rate = float(res["fire"][idx].mean())
    g = res["groups"][idx]
    grp = {}
    for gk in range(n_groups):
        m = g == gk
        if not m.any():
            continue
        gdd0, _ = risk(net[m], exits[m])
        gdd1, _ = risk(pol[m], exits[m])
        grp[str(gk)] = {"n": int(m.sum()), "delta": round(float(delta[m].mean()), 4),
                        "maxdd_hold": round(gdd0, 3), "maxdd_policy": round(gdd1, 3),
                        "ok": bool(delta[m].mean() > NI_MARGIN and gdd1 <= gdd0 + 1e-9)}
    legs = {}
    for lg in sorted({trades[i]["leg"] for i in idx}):
        m = np.array([trades[i]["leg"] == lg for i in idx])
        legs[lg] = {"n": int(m.sum()), "delta": round(float(delta[m].mean()), 4),
                    "fire_rate": round(float(res["fire"][idx][m].mean()), 4),
                    "ok": bool(m.sum() < LEG_N or delta[m].mean() >= LEG_FLOOR)}
    checks = {
        "a_noninferior": bool(lb > NI_MARGIN and delta.mean() >= COST_CAP),
        "b_risk_cut": bool((dd_cut >= RISK_CUT or cv_cut >= RISK_CUT) and dd1 <= dd0 + 1e-9 and cv1 >= cv0 - 1e-9),
        "c_beats_random": bool(delta.mean() > p90),
        "d_risk_cut_beats_random": bool((dd_cut >= RISK_CUT and dd_cut >= rnd_dd_cut)
                                        or (cv_cut >= RISK_CUT and cv_cut >= rnd_cv_cut)),
        "e_fire_rate": bool(FIRE_MIN <= fire_rate <= FIRE_MAX),
        "f_folds": bool(sum(v["ok"] for v in grp.values()) >= FOLDS_NEEDED),
        "g_legs": bool(all(v["ok"] for v in legs.values())),
    }
    if "static_delta" in res:
        checks["h_beats_best_static"] = bool(delta.mean() > float(res["static_delta"][idx].mean()))
    return {"n": n, "delta_mean": round(float(delta.mean()), 4), "delta_lb95_month_block": round(lb, 4),
            "net_hold_per_trade": round(float(net.mean()), 4), "net_policy_per_trade": round(float(pol.mean()), 4),
            "maxdd_hold": round(dd0, 3), "maxdd_policy": round(dd1, 3), "maxdd_cut": round(dd_cut, 4),
            "cvar5_hold": round(cv0, 4), "cvar5_policy": round(cv1, 4), "cvar5_cut": round(cv_cut, 4),
            "fire_rate": round(fire_rate, 4),
            "random": {"mean_delta_p50": round(float(np.median(rnd["mean"])), 4), "mean_delta_p90": round(p90, 4),
                       "maxdd_cut_p50": round(rnd_dd_cut, 4), "cvar5_cut_p50": round(rnd_cv_cut, 4),
                       "draws": N_RAND},
            "best_static": None if "static_delta" not in res else {
                "delta_mean": round(float(res["static_delta"][idx].mean()), 4),
                "chosen_per_split": res.get("static_chosen")},
            "groups": grp, "legs": legs, "checks": checks, "pass": all(checks.values())}


def evaluate_holdout(trades, ev, head, sel, rng) -> dict:
    idx = np.where(sel)[0]
    if len(idx) < HOLDOUT_N_MIN:
        return {"state": "INDETERMINATE", "n": len(idx), "reasons": [f"n {len(idx)} < {HOLDOUT_N_MIN}"]}
    delta = np.zeros(len(trades))
    fire = np.zeros(len(trades))
    for i in idx:
        b = first_fire(head, ev[i])
        if b is not None:
            delta[i] = FRACTION * float(delta_full(trades[i], ev[i])[b])
            fire[i] = 1.0
    ent = pd.Series([trades[i]["entry_time"] for i in range(len(trades))])
    t0, t1 = ent[idx].min(), ent[idx].max()
    g = np.minimum(((ent - t0) / (t1 - t0) * 3).astype(float).fillna(0).to_numpy().astype(int), 2)
    ev_ = evaluate_family(trades, ev, {"delta": delta, "fire": fire, "groups": g}, sel, rng, n_groups=3)
    ck = {"a_noninferior": ev_["checks"]["a_noninferior"],
          "b_risk_not_worse": bool(ev_["maxdd_policy"] <= ev_["maxdd_hold"] + 1e-9
                                   and ev_["cvar5_policy"] >= ev_["cvar5_hold"] - 1e-9),
          "c_beats_random": ev_["checks"]["c_beats_random"]}
    return {"state": "CONFIRMS" if all(ck.values()) else "FAILS", "n": len(idx),
            "reasons": [k for k, v in ck.items() if not v], "checks": ck,
            "eval": {k: v for k, v in ev_.items() if k not in ("checks", "pass")}}


# ------------------------------------------------------------------------------------------------ corpus
def load_corpus(legs, *, start, end, days, wd: Path):
    corpus, failed, runs = fpp.run_harness_legs(legs, days=days, start=start, end=end, wd=wd, data_csv=None)
    return corpus, failed, runs


def to_trades(corpus) -> tuple[list[dict], list[dict]]:
    trades, reps = [], []
    for leg, prow, trow, tf in corpus:
        ts, rep = fpp.build_trades(leg, prow, trow, tf)
        reps.append(rep)
        if rep["state"] == "included":
            trades.extend(ts)
    trades.sort(key=lambda t: (t["entry_time"].value, t["leg"]))
    return trades, reps


def run(trades, reps, fe_legs, *, holdout_trades=None, holdout_reps=None, out: Path) -> dict:
    rng = np.random.default_rng(SEED)
    ev = [events(t, fe_legs) for t in trades]
    fam_of = {lg: f for f, ls in GATE_FAMILIES.items() for lg in ls}
    legs_present = {t["leg"] for t in trades}
    grid = {}
    for cfg in GRID:
        res = cpcv_policy(trades, ev, cfg)
        key = f"C{cfg['C']}_q{cfg['q']}"
        fams = {}
        for f in GATE_FAMILIES:
            sel = np.array([fam_of.get(t["leg"]) == f for t in trades])
            fams[f] = evaluate_family(trades, ev, res, sel, np.random.default_rng(SEED), n_groups=6)
        grid[key] = {"cfg": cfg, "families": fams, "paths_filled_min": res["paths_filled"]}
    pk = f"C{PRIMARY['C']}_q{PRIMARY['q']}"
    primary = grid[pk]
    verdicts = {}
    for f, legs in GATE_FAMILIES.items():
        reasons = []
        bad = [r["leg"] for r in reps if r["leg"] in legs and r["state"] != "included"]
        missing = [lg for lg in legs if lg not in legs_present]
        if bad or missing:
            reasons.append(f"corpus/parity failed: {bad + missing}")
        fe = primary["families"][f]
        if fe["n"] < N_GATE_MIN:
            reasons.append(f"n {fe['n']} < {N_GATE_MIN}")
        hold = None
        if holdout_trades is not None:
            full = fit_head(ev, np.arange(len(trades)), PRIMARY["C"], PRIMARY["q"])
            hev = [events(t, fe_legs) for t in holdout_trades]
            hsel = np.array([fam_of.get(t["leg"]) == f for t in holdout_trades])
            hold = evaluate_holdout(holdout_trades, hev, full, hsel, rng) if len(holdout_trades) else \
                {"state": "INDETERMINATE", "n": 0, "reasons": ["no holdout corpus"]}
        if reasons:
            state = "INDETERMINATE"
        elif not fe["pass"]:
            state = "FAIL"
            reasons = [k for k, v in fe["checks"].items() if not v]
        elif hold is None or hold["state"] == "INDETERMINATE":
            state = "INDETERMINATE"
            reasons = ["holdout: " + "; ".join((hold or {}).get("reasons", ["not run"]))]
        elif hold["state"] == "FAILS":
            state = "FAIL"
            reasons = ["holdout: " + ",".join(hold["reasons"])]
        else:
            state = "PASS"
        verdicts[f] = {"state": state, "reasons": reasons, "holdout": hold}
    out.mkdir(parents=True, exist_ok=True)
    rec = {"rule": RULE_ID, "primary": pk, "verdicts": verdicts, "grid": grid, "legs": reps,
           "holdout_legs": holdout_reps, "fe_legs": fe_legs,
           "n_trades": len(trades), "n_states": int(sum(e["n"] for e in ev))}
    if any(v["state"] == "PASS" for v in verdicts.values()):
        full = fit_head(ev, np.arange(len(trades)), PRIMARY["C"], PRIMARY["q"])
        art = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in full.items()}
        art.update(features=fpp.R1, fe_legs=fe_legs, fraction=FRACTION, rule=RULE_ID,
                   label="L_t = 1 if exit_r - open_r_t < -c_exit (first_passage_paths.events)")
        (out / "am_partial_head.json").write_text(json.dumps(art, indent=1) + "\n", encoding="utf-8")
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    return rec


def _self_test() -> int:
    """Driftless synthetic corpus: the head carries no information, so the policy must NOT beat the random arm
    in the large majority of seeds' worth of noise -- here we check the machinery end to end and that a null
    reads FAIL/INDETERMINATE, never PASS."""
    global GATE_FAMILIES
    saved = GATE_FAMILIES
    GATE_FAMILIES = {"SYN": ["trend_donchian_syn_4h", "syn_pullback_2h"]}
    try:
        corpus = fpp.synthetic_corpus(planted=False, n_trades=600)
        trades, reps = to_trades(corpus)
        fe = sorted({t["leg"] for t in trades})
        with tempfile.TemporaryDirectory() as td:
            rec = run(trades, reps, fe, holdout_trades=trades[:150], holdout_reps=reps, out=Path(td))
        v = rec["verdicts"]["SYN"]["state"]
        ok = v != "PASS" and rec["grid"]["C0.1_q0.9"]["paths_filled_min"] == 5
        # positive control: a planted regime the ADX reads -> the head's partial close beats the random arm
        tp, rpp = to_trades(fpp.synthetic_corpus(planted=True, n_trades=600))
        with tempfile.TemporaryDirectory() as td:
            pos = run(tp, rpp, sorted({t["leg"] for t in tp}), holdout_trades=tp[:150], holdout_reps=rpp, out=Path(td))
        pc = pos["grid"]["C0.1_q0.9"]["families"]["SYN"]["checks"]["c_beats_random"]
        print(f"self-test planted: c_beats_random {pc}")
        ok = ok and pc
        print(f"self-test null: verdict {v}, paths_filled_min {rec['grid']['C0.1_q0.9']['paths_filled_min']}"
              f" -> {'ok' if ok else 'FAILED'}")
        return 0 if ok else 1
    finally:
        GATE_FAMILIES = saved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-10-15 23:59")
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--holdout-start", default="2017-09-01")
    ap.add_argument("--holdout-end", default="2020-06-30 23:59")
    ap.add_argument("--holdout-days", type=int, default=3500)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    legs = [lg for ls in GATE_FAMILIES.values() for lg in ls]
    wd = Path(tempfile.mkdtemp(prefix="main_", dir=str(out)))
    corpus, failed, runs = load_corpus(legs, start=a.start, end=a.end, days=a.days, wd=wd)
    trades, reps = to_trades(corpus)
    reps += [{"leg": f["leg"], "state": "harness_failed", "error": f.get("error")} for f in failed]
    hwd = Path(tempfile.mkdtemp(prefix="holdout_", dir=str(out)))
    hcorpus, hfailed, hruns = load_corpus(legs, start=a.holdout_start, end=a.holdout_end, days=a.holdout_days,
                                          wd=hwd)
    htrades, hreps = to_trades(hcorpus)
    before = pd.Timestamp("2020-07-01", tz="UTC") - EMBARGO
    htrades = [t for t in htrades if t["exit_time"] < before]
    hreps += [{"leg": f["leg"], "state": "harness_failed", "error": f.get("error")} for f in hfailed]
    fe_legs = sorted({t["leg"] for t in trades})
    rec = run(trades, reps, fe_legs, holdout_trades=htrades, holdout_reps=hreps, out=out)
    rec["runs"] = {"main": runs, "holdout": hruns}
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    for f, v in rec["verdicts"].items():
        fe = rec["grid"][rec["primary"]]["families"][f]
        print(f"{f}: {v['state']} {v['reasons']} | n {fe['n']} delta {fe.get('delta_mean')} "
              f"LB {fe.get('delta_lb95_month_block')} ddcut {fe.get('maxdd_cut')} cvcut {fe.get('cvar5_cut')} "
              f"fire {fe.get('fire_rate')} rnd_p90 {fe.get('random', {}).get('mean_delta_p90')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
