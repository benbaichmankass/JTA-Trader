#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-cd01-01.yaml (rows CRYPTO-ENTRY-RETRAIN-UNIT + ML-DECISION-LABEL-VOL-CONFOUND), run.command via research-script-run.yml
"""Why did the served crypto ml_entry replay negative? Regime vs selection vs cost, a clean-model control, and the gross-label ranking.

Rule (registered BEFORE the run, in research/queue/RQ-20261112-cd01-01.yaml, RULE-RQ20261112-cd01-01-REGIME-SELECT-COST):
  S = served v1r20261106 (train_end 2026-10-14); V = frozen ml_decision_entry_v1 (train_end 2025-09-22, clean on every window).
  A = 2025-10-01..2026-09-29 (V reference year)   B = 2026-10-25..2026-11-07 (S post-train replay window)   F = 2026-11-08.. (fresh forward)
  per taken decision k: pool_k = mean over every candidate row at the same ts and side (the REGIME read); excess_k = r_k - pool_k.
  R1 gap = net(S,B) - net(V,A) = dpool + dex  -> NO-GAP | REGIME | SELECTION | MIXED (-UNRESOLVED if leader |t| < 2); COST-NOT-DRIVER|CONTRIBUTES
  R2 control on B: REFIT-DAMAGE | REGIME-SHARED | REFIT-NEUTRAL (day-cluster bootstrap)
  R3 gross-label ranking of atr_pct: COST-ARTIFACT | SAME-RANKING | MIXED
Tier-1 research tooling: public Binance Vision candles, committed boosters read-only, writes only under --out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E  # noqa: E402
import ml_decision_vol_decomp as VD  # noqa: E402

RULE_ID = "RULE-RQ20261112-cd01-01-REGIME-SELECT-COST"
TAU = 0.1
A = ("2025-10-01", "2026-09-29 23:00")
B = ("2026-10-25", "2026-11-07 23:00")
F_START = "2026-11-08"
N_MIN = 100
GAP_MIN = -0.05
SHARE = 0.5
COST_SHARE = 0.25
REFIT_DELTA = -0.10
SHARED_LEVEL = -0.05
IC_ABS, IC_REL = 0.15, 0.5
BOOT, SEED = 2000, 20261112


def kframe(window: pd.DataFrame, taken: pd.DataFrame) -> pd.DataFrame:
    """One row per taken decision with its same-time same-side pool means and atr_pct-tercile pool means (net and gross)."""
    rows = []
    for side in ("long", "short"):
        tk = taken[taken.side == side]
        if tk.empty:
            continue
        pool = window[["symbol", "ts", "atr_pct", f"net_{side}", f"gross_{side}"]].dropna()
        pool = pool.rename(columns={f"net_{side}": "net", f"gross_{side}": "gross"})
        pool["bucket"] = pool.groupby("ts")["atr_pct"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 3, labels=False) if len(x) >= 3 else np.nan)
        allm = pool.groupby("ts")[["net", "gross"]].mean().add_prefix("all_")
        bm = pool.groupby(["ts", "bucket"])[["net", "gross"]].mean().add_prefix("b_").reset_index()
        k = tk.merge(pool[["symbol", "ts", "bucket"]], on=["symbol", "ts"], how="left")
        k = k.join(allm, on="ts").merge(bm, on=["ts", "bucket"], how="left")
        rows.append(k.assign(side=side))
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).dropna(subset=["bucket", "all_net", "b_net"])


def _cl(v, k):
    return VD._t_clustered(np.asarray(v, float), k.ts.astype("int64").to_numpy())


def summarise(k: pd.DataFrame) -> dict:
    """Net / gross / cost taken mean, the pool (regime) mean over the same decisions, excess, tilt, select; by side too."""
    if k.empty:
        return {"n": 0}
    out = {"n": int(len(k)), "by_side": {s: int((k.side == s).sum()) for s in ("long", "short")}}
    net, gross = k.net_r.to_numpy(float), k.gross_r.to_numpy(float)
    out["net"] = {"taken": _cl(net, k), "pool": _cl(k.all_net.to_numpy(float), k), "excess": _cl(net - k.all_net.to_numpy(float), k),
                  "tilt": _cl(k.b_net.to_numpy(float) - k.all_net.to_numpy(float), k),
                  "select": _cl(net - k.b_net.to_numpy(float), k)}
    out["gross"] = {"taken": _cl(gross, k), "pool": _cl(k.all_gross.to_numpy(float), k), "excess": _cl(gross - k.all_gross.to_numpy(float), k),
                    "select": _cl(gross - k.b_gross.to_numpy(float), k)}
    out["cost"] = {"taken": _cl(gross - net, k)}
    out["by_side_net"] = {s: {"taken": _cl(g.net_r.to_numpy(float), g), "pool": _cl(g.all_net.to_numpy(float), g),
                              "excess": _cl((g.net_r - g.all_net).to_numpy(float), g)}
                          for s, g in k.groupby("side")}
    return out


def _diff(x: dict, y: dict):
    """x - y of two independent windows' ts-clustered means -> (diff, se)."""
    if x.get("mean") is None or y.get("mean") is None or x.get("se_ts_clustered") is None or y.get("se_ts_clustered") is None:
        return None, None
    return x["mean"] - y["mean"], float(np.hypot(x["se_ts_clustered"], y["se_ts_clustered"]))


def judge_r1(sB: dict, vA: dict) -> dict:
    if sB.get("n", 0) < N_MIN or vA.get("n", 0) < N_MIN:
        return {"verdict": "INDETERMINATE", "why": f"n S,B {sB.get('n', 0)} or V,A {vA.get('n', 0)} < {N_MIN}"}
    gap, gse = _diff(sB["net"]["taken"], vA["net"]["taken"])
    dpool, pse = _diff(sB["net"]["pool"], vA["net"]["pool"])
    dex, ese = _diff(sB["net"]["excess"], vA["net"]["excess"])
    dcost, _ = _diff(sB["cost"]["taken"], vA["cost"]["taken"])
    base = {"gap": gap, "gap_se": gse, "d_pool_regime": dpool, "d_pool_se": pse, "d_excess_selection": dex, "d_excess_se": ese, "d_cost": dcost,
            "identity_residual": None if None in (gap, dpool, dex) else round(gap - dpool - dex, 6)}
    if gap is None or gap >= GAP_MIN:
        return {**base, "verdict": "NO-GAP", "why": f"gap {gap} >= {GAP_MIN}"}
    need = SHARE * (-gap)
    if -dpool >= need and -dex < need:
        lead, v, t = "regime", "REGIME", dpool / pse if pse else 0
    elif -dex >= need and -dpool < need:
        lead, v, t = "selection", "SELECTION", dex / ese if ese else 0
    else:
        lead, v, t = None, "MIXED", None
    unres = lead is not None and abs(t) < 2.0
    cost = "COST-NOT-DRIVER" if (dcost is not None and dcost < COST_SHARE * abs(gap)) else "COST-CONTRIBUTES"
    return {**base, "verdict": v + ("-UNRESOLVED" if unres else ""), "cost_verdict": cost, "leader": lead, "leader_t": None if t is None else round(t, 2),
            "why": f"gap {gap:.4f} = regime {dpool:.4f} + selection {dex:.4f}; d_cost {dcost:.4f}"}


def boot_diff(kS: pd.DataFrame, kV: pd.DataFrame) -> dict:
    """Day-cluster bootstrap of mean_net(S) - mean_net(V) on the same window."""
    d = pd.concat([kS.assign(arm="S"), kV.assign(arm="V")])
    d["day"] = pd.to_datetime(d.ts, utc=True).dt.floor("D")
    g = d.groupby(["day", "arm"]).net_r.agg(["sum", "count"]).unstack("arm").fillna(0.0)
    days = g.index.to_numpy()
    sS, nS, sV, nV = (g[("sum", "S")].to_numpy(), g[("count", "S")].to_numpy(), g[("sum", "V")].to_numpy(), g[("count", "V")].to_numpy())
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(days), size=(BOOT, len(days)))
    with np.errstate(invalid="ignore", divide="ignore"):
        diffs = sS[idx].sum(1) / nS[idx].sum(1) - sV[idx].sum(1) / nV[idx].sum(1)
    diffs = diffs[np.isfinite(diffs)]
    point = float(sS.sum() / nS.sum() - sV.sum() / nV.sum())
    lo, hi = (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))) if len(diffs) else (None, None)
    return {"point": point, "ci95_lo": lo, "ci95_hi": hi, "n_days": int(len(days)), "n_S": int(nS.sum()), "n_V": int(nV.sum())}


def judge_r2(kS: pd.DataFrame, kV: pd.DataFrame) -> dict:
    if len(kS) < N_MIN or len(kV) < N_MIN:
        return {"verdict": "INDETERMINATE", "why": f"n S {len(kS)} or V {len(kV)} < {N_MIN}"}
    b = boot_diff(kS, kV)
    vB = float(kV.net_r.mean())
    if b["point"] <= REFIT_DELTA and b["ci95_hi"] is not None and b["ci95_hi"] < 0:
        v = "REFIT-DAMAGE"
    elif vB <= SHARED_LEVEL:
        v = "REGIME-SHARED"
    else:
        v = "REFIT-NEUTRAL"
    return {**b, "mean_net_V": vB, "mean_net_S": float(kS.net_r.mean()), "verdict": v,
            "why": f"S-V {b['point']:.4f} CI [{b['ci95_lo']:.4f},{b['ci95_hi']:.4f}]; V on B {vB:.4f}"}


def rank_ic(tab: pd.DataFrame) -> dict:
    """Mean per-ts cross-sectional Spearman of atr_pct (and vol24, ret_24) against the net and gross label, sides averaged."""
    t = tab.dropna(subset=["atr_pct", "net_long", "net_short", "gross_long", "gross_short"])
    out = {}
    for feat in ("atr_pct", "vol24", "ret_24"):
        res = {}
        for lab in ("net", "gross"):
            ics = []
            for side in ("long", "short"):
                cols = t[["ts", feat, f"{lab}_{side}"]].copy()
                r = cols.groupby("ts")[[feat, f"{lab}_{side}"]].rank()
                r = r - r.groupby(cols.ts).transform("mean")
                num = (r[feat] * r[f"{lab}_{side}"]).groupby(cols.ts).sum()
                den = np.sqrt((r[feat] ** 2).groupby(cols.ts).sum() * (r[f"{lab}_{side}"] ** 2).groupby(cols.ts).sum())
                ic = (num / den).replace([np.inf, -np.inf], np.nan).dropna()
                ics.append(float(ic.mean()))
            res[lab] = round(float(np.mean(ics)), 4)
            res[f"{lab}_long_short"] = [round(x, 4) for x in ics]
        out[feat] = res
    return out


def judge_r3(ic: dict) -> dict:
    n, g = ic["atr_pct"]["net"], ic["atr_pct"]["gross"]
    if g < IC_ABS and g < IC_REL * n:
        v = "COST-ARTIFACT"
    elif g >= IC_REL * n and g >= IC_ABS:
        v = "SAME-RANKING"
    else:
        v = "MIXED"
    return {"verdict": v, "why": f"IC(atr_pct, net) {n}, IC(atr_pct, gross) {g}"}


def _score(tab, models, feats, lo, hi):
    w = tab[(tab.ts >= pd.Timestamp(lo, tz="UTC")) & (tab.ts <= pd.Timestamp(hi, tz="UTC"))]
    # provenance: predict -- the regressed net R of each side (policy() thresholds it at tau), not a probability
    taken = E.policy(w, models["long"].predict(w[feats]), models["short"].predict(w[feats]), TAU)
    return w, taken


def run(a) -> int:
    from src.runtime.ml_entry_served import served_artifact
    t0 = time.time()
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = E.universe()
    from datetime import date
    import ml_entry_retrain as RT
    rep = RT.fetch_through(cache, syms, RT.plan(date.fromisoformat(a.run_date)))
    tab = E.build_table(cache, syms)
    last_ts = str(tab.ts.max())
    sp = served_artifact()
    sm, smod = E._frozen_models(sp)
    vm, vmod = E._frozen_models(REPO / "ml" / "served" / "ml_decision_entry_v1" / "model.json")
    sf = sm["features"] if isinstance(sm["features"], list) else json.loads(sm["features"].replace("'", '"'))
    vf = vm["features"] if isinstance(vm["features"], list) else json.loads(vm["features"].replace("'", '"'))
    assert abs(float(sm["tau"]) - TAU) < 1e-12 and abs(float(vm["tau"]) - TAU) < 1e-12
    claims = {}
    if not a.no_ledger:
        import holdout_lock
        for mid, meta, win in (("ENTRY-v1-regime-split", vm, A), ("ENTRY-v1-regime-split", vm, B),
                               ("ENTRY-v1r20261106-regime-split", sm, B)):
            claims[f"{mid}|{win[0]}..{win[1][:10]}"] = holdout_lock.claim_read(
                mid, win[0], win[1][:10], a.unit, a.reader, holdout_lock.LEDGER,
                train_end=str(meta["train_end_exclusive"])[:10], family="ENTRY")
    res = {}
    wA, tVA = _score(tab, vmod, vf, *A)
    wB, tVB = _score(tab, vmod, vf, *B)
    _, tSB = _score(tab, smod, sf, *B)
    kVA, kVB, kSB = kframe(wA, tVA), kframe(wB, tVB), kframe(wB, tSB)
    res["V_A"], res["V_B"], res["S_B"] = summarise(kVA), summarise(kVB), summarise(kSB)
    f_hi = last_ts
    fw_n = int(((tab.ts >= pd.Timestamp(F_START, tz="UTC")) & (tab.ts <= pd.Timestamp(f_hi))).sum())
    if fw_n:
        wF, tSF = _score(tab, smod, sf, F_START, f_hi)
        _, tVF = _score(tab, vmod, vf, F_START, f_hi)
        res["S_F"], res["V_F"] = summarise(kframe(wF, tSF)), summarise(kframe(wF, tVF))
    r1, r2 = judge_r1(res["S_B"], res["V_A"]), judge_r2(kSB, kVB)
    ic = rank_ic(tab[tab.ts <= pd.Timestamp("2026-09-29 23:00", tz="UTC")])
    r3 = judge_r3(ic)
    note = f"R1 {r1['verdict']}" + (f" ({r1.get('cost_verdict')})" if r1.get("cost_verdict") else "") + f" | R2 {r2['verdict']} | R3 {r3['verdict']} | R4 F indeterminate by rule"
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate", "note": note,
           "n": res["S_B"].get("n"), "decision_rule": {"id": RULE_ID, "registered_at": "2026-11-12", "registered_before_run": True},
           "population": (f"served {sp.parent.name} (S) and frozen ml_decision_entry_v1 (V) taken decisions, tau {TAU}, {tab.symbol.nunique()}-perp universe, "
                          f"windows A {A[0]}..{A[1][:10]} (V), B {B[0]}..{B[1][:10]} (S,V), F {F_START}..{f_hi[:10]} (descriptive); pool = every candidate row at the same ts and side"),
           "measurement": {"R1": r1, "R2": r2, "R3": {**r3, "rank_ic": ic}, "windows": res, "holdout_claims": claims,
                           "latest_bar": max(v["last_bar"] for v in rep.values()), "git_sha": E._git_sha(), "runtime_s": round(time.time() - t0)},
           "produced_by": {"tool": "python3 scripts/research/ml_entry_regime_split.py", "where": a.reader}}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(note, flush=True)
    return 0


def self_test() -> int:
    import tempfile
    import ml_entry_crypto_struct as C
    root = Path(tempfile.mkdtemp())
    syms = C._synthetic_cache(root)
    tab = E.build_table(root, syms)
    train = tab[tab.ts < tab.ts.max() - pd.Timedelta(days=40)]
    models = E.fit_models(train.sample(min(len(train), 20000), random_state=0))
    lo, hi = str((tab.ts.max() - pd.Timedelta(days=30)).date()), str(tab.ts.max())
    w, tk = _score(tab, models, E.FEATURES, lo, hi)
    k = kframe(w, tk)
    s = summarise(k)
    assert s["n"] == len(k) and abs(s["net"]["taken"]["mean"] - (s["net"]["pool"]["mean"] + s["net"]["excess"]["mean"])) < 1e-3, s
    assert abs(s["net"]["excess"]["mean"] - s["net"]["tilt"]["mean"] - s["net"]["select"]["mean"]) < 1e-3
    # R1 identity and branch coverage on planted summaries
    def S(taken, pool, cost, n=500):
        c = lambda m: {"mean": m, "se_ts_clustered": 0.02, "n": n}
        return {"n": n, "net": {"taken": c(taken), "pool": c(pool), "excess": c(taken - pool)}, "cost": {"taken": c(cost)}}
    assert judge_r1(S(-0.13, -0.15, 0.07), S(0.007, 0.0, 0.066))["verdict"].startswith("REGIME")
    assert judge_r1(S(-0.13, 0.0, 0.07), S(0.007, 0.0, 0.066))["verdict"].startswith("SELECTION")
    assert judge_r1(S(0.0, 0.0, 0.07), S(0.007, 0.0, 0.066))["verdict"] == "NO-GAP"
    assert judge_r1(S(-0.125, -0.0625, 0.07), S(0.0, 0.0, 0.066))["verdict"] == "MIXED"
    r2 = judge_r2(k.assign(net_r=k.net_r - 0.5), k)
    assert r2["verdict"] in ("REFIT-DAMAGE", "INDETERMINATE"), r2
    assert judge_r3({"atr_pct": {"net": 0.49, "gross": -0.08}})["verdict"] == "COST-ARTIFACT"
    assert judge_r3({"atr_pct": {"net": 0.49, "gross": 0.4}})["verdict"] == "SAME-RANKING"
    ic = rank_ic(tab)
    assert set(ic) == {"atr_pct", "vol24", "ret_24"} and all(-1 <= ic[f][l] <= 1 for f in ic for l in ("net", "gross"))
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out")
    ap.add_argument("--unit", default="RQ-20261112-cd01-01")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-12")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.out:
        ap.error("--out is required")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
