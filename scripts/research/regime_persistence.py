#!/usr/bin/env python3
# wiring: research/queue/RQ-20261124-f1a0-13.yaml (REGIME-PROGRAM R1, lane ML-PRIMARY); reuses ml_decision_entry.build_table / regime_columns
"""REGIME-PROGRAM R1: how long do BTC regime STATES and the per-state SIDE EDGE persist? (Tier-1 research; no model, no gate.)

Motivation: RQ-20261124-f1a0-09 (calibration fit on the most recent block) FAILED because side EVs anti-persisted from one half-year fold to the next.
The regime classifier horizon for R2-R4 must come from measured persistence, not assumption.

Population: the ml_entry dev table (60-perp frozen universe, 2021..2025-10-01, every 4-h decision row; label_symbol net R of each side under the registered
SL 2 / TP 3 / 24 h bracket, full cost stack). Policy-free: every row, no model.

Measured, per window length W in {1w, 1m, 1q, 6m}:
  state_acf     lag-1 autocorrelation of the window-mean BTC regime state (30d return, distance from the 1200 h mean, vol percentile).
  cell_persist  share of consecutive windows whose dominant BTC cell (trend sign x vol above/below median) is unchanged.
  gap_corr      correlation of the window SIDE GAP (mean net_short - mean net_long over all rows) between window t and t+1, with a 1,000-draw
                block bootstrap 90% CI (blocks of consecutive window pairs).
  cell_gap_corr the same correlation within each BTC cell (pairs where the cell holds in both windows).

Registered verdict (RULE-REGIME-R1-PERSISTENCE-20261124): the PERSISTENCE HORIZON is the longest W whose gap_corr >= 0.3 with the bootstrap 90% CI lower
bound > 0. PASS iff such a W exists (the horizon is written to the result and fixes R2-R4's classifier horizon); FAIL iff every W has a CI upper bound
< 0.3 (no usable side persistence at any horizon: R2 must label regimes by STRATEGY performance, not by side); INDETERMINATE otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ml_decision_entry as M  # noqa: E402

WINDOWS = {"1w": "7D", "1m": "30D", "1q": "91D", "6m": "182D"}
STATE = ["btc_ret720", "btc_dist_sma1200", "btc_vol_pct90d"]
RULE = {"id": "RULE-REGIME-R1-PERSISTENCE-20261124", "min_corr": 0.3, "ci": 0.90, "boot": 1000}
SEED = 20261124


def corr_ci(x: np.ndarray, y: np.ndarray, boot: int = RULE["boot"], ci: float = RULE["ci"], seed: int = SEED) -> dict:
    """Pearson r of paired (x_t, y_t) with a moving-block bootstrap CI (block = sqrt(n) consecutive pairs)."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 6:
        return {"n_pairs": n, "r": None, "lo": None, "hi": None}
    r = float(np.corrcoef(x, y)[0, 1])
    rng = np.random.default_rng(seed)
    b = max(2, int(np.sqrt(n)))
    rs = []
    for _ in range(boot):
        starts = rng.integers(0, n - b + 1, size=int(np.ceil(n / b)))
        idx = np.concatenate([np.arange(s, s + b) for s in starts])[:n]
        if np.std(x[idx]) > 0 and np.std(y[idx]) > 0:
            rs.append(np.corrcoef(x[idx], y[idx])[0, 1])
    a = (1 - ci) / 2
    return {"n_pairs": n, "r": r, "lo": float(np.quantile(rs, a)) if rs else None, "hi": float(np.quantile(rs, 1 - a)) if rs else None}


def persistence(tab: pd.DataFrame) -> dict:
    t = tab.assign(ts=pd.to_datetime(tab.ts, utc=True), gap=tab.net_short - tab.net_long)
    t["cell"] = np.where(t.btc_ret720 > 0, "up", "down").astype(object) + np.where(t.btc_vol_pct90d >= 0.5, "_hi", "_lo")
    out = {}
    for name, freq in WINDOWS.items():
        g = t.set_index("ts").groupby(pd.Grouper(freq=freq))
        w = pd.DataFrame({"gap": g.gap.mean(), "n": g.gap.size(), **{s: g[s].mean() for s in STATE},
                          "cell": g.cell.agg(lambda c: c.mode().iat[0] if len(c) else None)}).dropna(subset=["gap"])
        w = w[w.n >= 50]
        rec = {"n_windows": len(w)}
        rec["state_acf"] = {s: (float(w[s].autocorr(1)) if len(w) > 3 else None) for s in STATE}
        rec["cell_persist"] = float((w.cell.to_numpy()[1:] == w.cell.to_numpy()[:-1]).mean()) if len(w) > 1 else None
        rec["gap_corr"] = corr_ci(w.gap.to_numpy()[:-1], w.gap.to_numpy()[1:])
        cg = {}
        for cell in sorted(t.cell.dropna().unique()):
            gc = t[t.cell == cell].set_index("ts").groupby(pd.Grouper(freq=freq)).gap.agg(["mean", "size"])
            gc = gc[gc["size"] >= 30]["mean"]
            # consecutive calendar windows only (the cell held in both)
            idx = gc.index
            pairs = [(gc.iloc[i], gc.iloc[i + 1]) for i in range(len(gc) - 1) if (idx[i + 1] - idx[i]) <= pd.Timedelta(freq) * 1.01]
            arr = np.array(pairs) if pairs else np.empty((0, 2))
            cg[cell] = corr_ci(arr[:, 0], arr[:, 1]) if len(arr) else {"n_pairs": 0, "r": None, "lo": None, "hi": None}
        rec["cell_gap_corr"] = cg
        rec["mean_gap"] = float(w.gap.mean())
        out[name] = rec
    return out


def verdict(res: dict, rule: dict = RULE) -> tuple[str, str, str | None]:
    ok = [k for k in WINDOWS if (c := res[k]["gap_corr"])["r"] is not None and c["r"] >= rule["min_corr"] and c["lo"] is not None and c["lo"] > 0]
    if ok:
        h = ok[-1]
        return "pass", f"persistence horizon {h}: gap_corr {res[h]['gap_corr']['r']:.3f} [{res[h]['gap_corr']['lo']:.3f},{res[h]['gap_corr']['hi']:.3f}]", h
    if all((c := res[k]["gap_corr"])["hi"] is not None and c["hi"] < rule["min_corr"] for k in WINDOWS):
        return "fail", "no window's side gap persists (every CI upper bound < %.1f)" % rule["min_corr"], None
    return "indeterminate", "; ".join(f"{k}: r {res[k]['gap_corr']['r']}" for k in WINDOWS), None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/regime_persistence")
    ap.add_argument("--unit", default="")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run-date", default="2026-11-22")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    from datetime import date

    import ml_entry_retrain as R
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if a.fetch:
        R.fetch_through(cache, M.universe(), R.plan(date.fromisoformat(a.run_date)))
    syms = M.universe()
    tab = M.build_table(cache, syms)
    tab = pd.concat([tab.reset_index(drop=True), M.regime_columns(cache, syms, tab)[M.REGIME_FEATURES]], axis=1).dropna(subset=STATE)
    tab = tab[pd.to_datetime(tab.ts, utc=True) < pd.Timestamp(M.HOLDOUT_START, tz="UTC")]
    res = persistence(tab)
    v, why, horizon = verdict(res)
    pop = (f"ml_entry dev table rows {tab.ts.min()}..{M.HOLDOUT_START} ({len(tab)} decision rows, {tab.symbol.nunique()} symbols), policy-free, side net R under "
           f"SL 2 / TP 3 / 24 h with fee {M.FEE_BPS}+slip 3+funding 1 bps/8h; windows {list(WINDOWS)}")
    summ = {"schema": "regime_persistence/1", "unit": a.unit, "verdict": v, "why": why, "horizon": horizon, "rule": RULE, "population": pop,
            "measurement": res, "git_sha": M._git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": v, "read_state": "measured", "n": int(len(tab)), "note": why, "population": pop,
                                                  "rule": RULE, "measurement": {"horizon": horizon, **res}}, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


def _self_test() -> None:
    rng = np.random.default_rng(0)
    x = rng.standard_normal(200)
    c = corr_ci(x[:-1], x[1:])
    assert abs(c["r"]) < 0.25 and c["lo"] < 0 < c["hi"], c                     # white noise: no persistence
    ar = np.zeros(200)
    for i in range(1, 200):
        ar[i] = 0.8 * ar[i - 1] + rng.standard_normal()
    c2 = corr_ci(ar[:-1], ar[1:])
    assert c2["r"] > 0.6 and c2["lo"] > 0.3, c2                                  # AR(1) 0.8: persistent
    res = {k: {"gap_corr": {"r": 0.1, "lo": -0.2, "hi": 0.25}} for k in WINDOWS}
    assert verdict(res)[0] == "fail"
    res["1m"]["gap_corr"] = {"r": 0.5, "lo": 0.2, "hi": 0.7}
    assert verdict(res)[:3:2] == ("pass", "1m")
    print("self-test ok")


if __name__ == "__main__":
    sys.exit(main())
