#!/usr/bin/env python3
"""ML-AM-NEXT-LIVE follow-up (PI-20261029-IFMPNGJK-0002): a STATIC mid-trade 50% partial close on the real-money legs,
graded under RULE-AM-RISK-ADJUSTED-V1 (scripts/research/am_risk_adjusted.grade_risk_adjusted, imported, never copied)
plus a non-inferiority bound, against hold and a same-rate random partial close, with a blind holdout.

VARIANTS (pre-stated, K = 4; nothing is fitted, so CPCV has nothing to train and the main-window grade IS the
out-of-sample grade of a rule fixed before the run): close 50% at the close of bar k of the trade, k in {3, 6, 12, 24}
bars of the leg's own timeframe, on every trade still open after bar k (the rest of the trades are untouched). Both
brackets stay on the remainder (ARCHITECTURE § Active management clause 3).

PRICING (the a7e1 / d6e7-06 construction): delta = F x (open_r_b - fee - slippage - funding x (b+1)/bars - c_exit -
net_r), F = 0.5, net of the full cost stack, c_exit an extra exit-slippage charge.

MULTIPLICITY (4 variants): R4's beat fraction rises from 0.95 to 1 - 0.05/4 = 0.9875 of the random draws, and the
non-inferiority one-sided bound uses alpha 0.05/4.

RANDOM CONTROL: per draw, the variant's fired share of trades within each of 6 calendar groups is drawn at random from
that group's trades, each closed 50% at a UNIFORMLY drawn decision bar (2,000 draws, seed 20261030 + variant index).
DISCLOSED: RQ-20261029-a7e1-01's random arm (a uniform-bar 50% partial at the ML head's fire rate) was observed before
this unit was registered (TD median +0.0146 R/trade, 29% maxDD cut). This unit's variants are fixed-bar, its seeds
are fresh, and nothing is tuned on that observation.

Usage:
  python3 scripts/research/am_static_partial.py --out <dir> [--corpus-dir D --holdout-corpus-dir H]
  python3 scripts/research/am_static_partial.py --self-test
Observe-only research: writes only under --out. Requires scripts/research/am_risk_adjusted.py (PR #21283).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import first_passage_paths as fpp
from ml_am_partial_noninferior import GATE_FAMILIES, delta_full, load_corpus, to_trades
from ml_overlay_noninferior import month_block_lb

RULE_ID = "RULE-AM-STATIC-PARTIAL-V1"
FRACTION = 0.5
VARIANTS = (3, 6, 12, 24)
K = len(VARIANTS)
ALPHA = 0.05
NI_MARGIN = -0.02
N_RAND = 2000
SEED0 = 20261030
N_GROUPS = 6
HOLDOUT_N_MIN = 100
EMBARGO = pd.Timedelta(days=7)
LEG_ACCOUNTS_KEY = "strategies"


def _iso(ts: pd.Timestamp) -> str:
    return ts.isoformat()


def _book(trades: list[dict], net: np.ndarray) -> list[dict]:
    return [{"entry_time": _iso(t["entry_time"]), "exit_time": _iso(t["exit_time"]), "net_r": float(r),
             "mfe_r": float(np.nanmax(t["peak_r"])) if len(t["peak_r"]) else None} for t, r in zip(trades, net)]


def variant_deltas(trades: list[dict], ev: list[dict], k: int) -> tuple[np.ndarray, np.ndarray]:
    """Per trade: delta of a 50% close at bar offset k (decision index k-1) and whether it fired."""
    d = np.zeros(len(trades))
    fired = np.zeros(len(trades), dtype=bool)
    for i, (t, e) in enumerate(zip(trades, ev)):
        if e["n"] >= k:
            d[i] = FRACTION * float(delta_full(t, e)[k - 1])
            fired[i] = True
    return d, fired


def groups_of(trades: list[dict], n_groups: int) -> np.ndarray:
    ent = pd.Series([t["entry_time"] for t in trades])
    t0, t1 = ent.min(), ent.max()
    return np.minimum(((ent - t0) / (t1 - t0) * n_groups).astype(float).fillna(0).to_numpy().astype(int), n_groups - 1)


def random_books(trades, ev, fired, groups, rng) -> tuple[list[np.ndarray], np.ndarray]:
    """Same-rate random partial close: per calendar group, as many trades as the variant fired on, drawn at random among
    the group's trades that have a decision bar, each closed at a uniformly drawn decision bar."""
    dfs = [FRACTION * delta_full(t, e) if e["n"] else np.zeros(0) for t, e in zip(trades, ev)]
    net = np.array([t["net_r"] for t in trades])
    eligible = np.array([len(x) > 0 for x in dfs])
    nets, means = [], np.empty(N_RAND)
    for j in range(N_RAND):
        dk = np.zeros(len(trades))
        for g in np.unique(groups):
            pool = np.where((groups == g) & eligible)[0]
            m = min(int(fired[groups == g].sum()), len(pool))
            for i in rng.choice(pool, size=m, replace=False):
                dk[i] = dfs[i][rng.integers(0, len(dfs[i]))]
        nets.append(net + dk)
        means[j] = dk.mean()
    return nets, means


def roster_risk_pcts(legs: list[str]) -> dict[str, float]:
    """accounts.yaml risk_pct for every account that rosters one of `legs` (REPORTED % view only)."""
    from am_risk_adjusted import _accounts
    accs = _accounts()
    out = {}
    for name, a in accs.items():
        roster = a.get(LEG_ACCOUNTS_KEY) or []
        names = {r if isinstance(r, str) else (r or {}).get("name") for r in roster} if isinstance(roster, list) \
            else set(roster) if isinstance(roster, dict) else set()
        if names & set(legs) and isinstance(a.get("risk"), dict) and a["risk"].get("risk_pct") is not None:
            out[name] = float(a["risk"]["risk_pct"])
    return out


def grade_family(trades, ev, sel, legs, *, seed_base: int, holdout=False, risk_pcts=None) -> dict:
    from am_risk_adjusted import RULE_V1, grade_risk_adjusted
    idx = np.where(sel)[0]
    tr = [trades[i] for i in idx]
    evs = [ev[i] for i in idx]
    if len(tr) == 0:
        return {"n": 0, "verdict": "indeterminate", "why": "no trades"}
    net = np.array([t["net_r"] for t in tr])
    months = np.array([t["entry_time"].strftime("%Y-%m") for t in tr])
    groups = groups_of(tr, 3 if holdout else N_GROUPS)
    params = {"min_control_beat_frac": 1 - ALPHA / K}
    if holdout:
        params.update(folds=3, fold_majority=2)
    out = {"n": len(tr), "rule_params": {**{k: RULE_V1[k] for k in RULE_V1 if k != "doctrine"}, **params},
           "variants": {}}
    for vi, k in enumerate(VARIANTS):
        d, fired = variant_deltas(tr, evs, k)
        rng = np.random.default_rng(seed_base + vi)
        rnets, rmeans = random_books(tr, evs, fired, groups, rng)
        books = {"hold": _book(tr, net), "cand": _book(tr, net + d)}
        ctl = []
        for j, rn in enumerate(rnets):
            books[f"rnd{j}"] = _book(tr, rn)
            ctl.append(f"rnd{j}")
        g = grade_risk_adjusted(books, baseline="hold", candidates=["cand"], controls={"cand": ctl}, params=params,
                                risk_pct_by_account=risk_pcts)
        c = g["candidates"]["cand"]
        lb = month_block_lb(d, months, np.random.default_rng(seed_base + 100 + vi), ALPHA / K)
        beat = sum(v["beats"] for v in c["controls"].values()) / len(c["controls"])
        row = {"k_bars": k, "fire_rate": round(float(fired.mean()), 4), "delta_mean": round(float(d.mean()), 4),
               "delta_lb_month_block_alpha_over_k": round(lb, 4), "noninferior": bool(lb > NI_MARGIN),
               "r_cost_per_trade": c["r_cost_per_trade"], "dd_cut_pct": c["dd_cut_pct"],
               "cvar5_week_cut_pct": c["cvar5_cut_pct"], "folds_held": c["folds_held"], "n_folds": c["n_folds"],
               "clauses": c["clauses"], "am_verdict": c["verdict"], "am_label": c["label"],
               "random_beat_frac": round(beat, 4), "random_mean_delta_p50": round(float(np.median(rmeans)), 4),
               "random_mean_delta_p90": round(float(np.quantile(rmeans, 0.9)), 4),
               "baseline_book": g["baseline_book"], "candidate_book": c["book"],
               "pnl_by_account": c["pnl_by_account"]}
        if holdout:
            A, C = g["baseline_book"], c["book"]
            row["confirms"] = bool(c["r_cost_per_trade"] <= RULE_V1["max_r_cost_per_trade"] and lb > NI_MARGIN
                                   and C["max_drawdown_r"] <= A["max_drawdown_r"] + 1e-9
                                   and (C["cvar5_week_r"] or 0) >= (A["cvar5_week_r"] or 0) - 1e-9
                                   and d.mean() > float(np.median(rmeans)))
        else:
            row["passes_main"] = bool(c["verdict"] == "pass" and row["noninferior"])
        out["variants"][str(k)] = row
    return out


def run(trades, reps, htrades, hreps, out: Path) -> dict:
    fe = sorted({t["leg"] for t in trades})
    ev = [fpp.events(t, fe) for t in trades]
    hev = [fpp.events(t, fe) for t in htrades]
    fam_of = {lg: f for f, ls in GATE_FAMILIES.items() for lg in ls}
    present = {t["leg"] for t in trades}
    res = {"rule": RULE_ID, "variants": list(VARIANTS), "fraction": FRACTION, "families": {}, "legs": reps,
           "holdout_legs": hreps, "n_trades": len(trades)}
    for fi, (f, legs) in enumerate(GATE_FAMILIES.items()):
        try:
            rp = roster_risk_pcts(legs)
        except Exception as exc:  # noqa: BLE001  # allow-silent: the % view is REPORTED only; its absence is stated
            rp, res.setdefault("pnl_view_error", str(exc)[:200])
        sel = np.array([fam_of.get(t["leg"]) == f for t in trades])
        hsel = np.array([fam_of.get(t["leg"]) == f for t in htrades]) if htrades else np.zeros(0, dtype=bool)
        main = grade_family(trades, ev, sel, legs, seed_base=SEED0 + 1000 * fi, risk_pcts=rp)
        hold = (grade_family(htrades, hev, hsel, legs, seed_base=SEED0 + 1000 * fi + 500, holdout=True)
                if int(hsel.sum()) >= HOLDOUT_N_MIN else {"n": int(hsel.sum()), "verdict": "indeterminate",
                                                          "why": f"n {int(hsel.sum())} < {HOLDOUT_N_MIN}"})
        missing = [lg for lg in legs if lg not in present]
        bad = [r["leg"] for r in reps if r["leg"] in legs and r["state"] != "included"]
        passing = [k for k, v in main.get("variants", {}).items() if v.get("passes_main")]
        if missing or bad or main["n"] < 200:
            state, why = "INDETERMINATE", f"corpus/parity {missing + bad} or n {main['n']} < 200"
        elif not passing:
            state, why = "FAIL", "no variant passes RULE-AM-RISK-ADJUSTED-V1 (K-corrected) + non-inferiority"
        elif hold.get("verdict") == "indeterminate":
            state, why = "INDETERMINATE", f"variants {passing} pass the main window; holdout {hold['why']}"
        else:
            conf = [k for k in passing if hold["variants"][k]["confirms"]]
            state = "PASS" if conf else "FAIL"
            why = (f"variants {conf} pass and the holdout confirms" if conf
                   else f"variants {passing} pass the main window; the holdout does not confirm")
        res["families"][f] = {"state": state, "why": why, "accounts_risk_pct": rp, "main": main, "holdout": hold}
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    return res


def _self_test() -> int:
    import ml_am_partial_noninferior as m
    saved = dict(GATE_FAMILIES)
    GATE_FAMILIES.clear()
    GATE_FAMILIES["SYN"] = ["trend_donchian_syn_4h", "syn_pullback_2h"]
    global N_RAND
    n_saved, N_RAND = N_RAND, 200
    try:
        tr, rp = m.to_trades(fpp.synthetic_corpus(planted=False, n_trades=600))
        with tempfile.TemporaryDirectory() as td:
            r = run(tr, rp, tr[:150], rp, Path(td))
        st = r["families"]["SYN"]["state"]
        ok = st != "PASS" and set(r["families"]["SYN"]["main"]["variants"]) == {str(k) for k in VARIANTS}
        print(f"self-test null: {st} -> {'ok' if ok else 'FAILED'}")
        return 0 if ok else 1
    finally:
        GATE_FAMILIES.clear()
        GATE_FAMILIES.update(saved)
        N_RAND = n_saved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-10-15 23:59")
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--holdout-start", default="2017-09-01")
    ap.add_argument("--holdout-end", default="2020-06-30 23:59")
    ap.add_argument("--holdout-days", type=int, default=3500)
    ap.add_argument("--corpus-dir", default=None, help="reuse a built main-window corpus (same argv and window)")
    ap.add_argument("--holdout-corpus-dir", default=None)
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

    def corpus(dir_, start, end, days, prefix):
        if dir_:
            d = Path(dir_)
            loaded = []
            for lg in legs:
                pth, trd = d / f"{lg}__paths.jsonl", d / f"{lg}__trades.jsonl"
                if pth.exists() and trd.exists():
                    import yaml
                    cfg = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
                    cfg = cfg.get("strategies", cfg)
                    rd = lambda p: [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]  # noqa: E731
                    loaded.append((lg, rd(pth), rd(trd), cfg[lg].get("timeframe")))
            return loaded, [{"leg": lg, "reason": "absent from corpus dir"} for lg in legs
                            if not (d / f"{lg}__paths.jsonl").exists()]
        wd = Path(tempfile.mkdtemp(prefix=prefix, dir=str(out)))
        c, failed, _runs = load_corpus(legs, start=start, end=end, days=days, wd=wd)
        return c, failed

    c, failed = corpus(a.corpus_dir, a.start, a.end, a.days, "main_")
    trades, reps = to_trades(c)
    reps += [{"leg": f["leg"], "state": "missing", "error": f.get("reason") or f.get("error")} for f in failed]
    hc, hfailed = corpus(a.holdout_corpus_dir, a.holdout_start, a.holdout_end, a.holdout_days, "holdout_")
    htrades, hreps = to_trades(hc)
    before = pd.Timestamp("2020-07-01", tz="UTC") - EMBARGO
    htrades = [t for t in htrades if t["exit_time"] < before]
    r = run(trades, reps, htrades, hreps, out)
    for f, v in r["families"].items():
        print(f"{f}: {v['state']} -- {v['why']}")
        for k, row in v["main"].get("variants", {}).items():
            print(f"  k={k}: fire {row['fire_rate']} d {row['delta_mean']} LB {row['delta_lb_month_block_alpha_over_k']}"
                  f" cost {row['r_cost_per_trade']} ddcut {row['dd_cut_pct']} cvwk {row['cvar5_week_cut_pct']}"
                  f" folds {row['folds_held']}/{row['n_folds']} beat {row['random_beat_frac']} -> {row['am_label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
