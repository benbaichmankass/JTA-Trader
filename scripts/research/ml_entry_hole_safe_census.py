#!/usr/bin/env python3
# wiring: research harness for row ML-ENTRY-HOLE-SAFE-ADOPT (manual / research-script-run); evidence in comms/research/ml_entry_hole_safe/
"""Census of hourly bar holes in the crypto 1h lake, legacy-vs-hole-safe table diff, and re-grade of the committed entry grades.

Tier 1, offline, public Binance Vision klines only. Does NOT touch the holdout ledger (no claim_read): it re-scores windows the
committed grade records already read, so it is a recomputation, never a new read.

  python3 scripts/research/ml_entry_hole_safe_census.py --cache DIR --out DIR [--refit]
  python3 scripts/research/ml_entry_hole_safe_census.py --self-test

``--cache`` is the ``<SYM>.pkl`` lake built by ``ml_entry_retrain.fetch_through`` (run date >= 2026-11-12).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))
import ml_decision_entry as E  # noqa: E402

HOLE = (pd.Timestamp("2026-10-28", tz="UTC"), pd.Timestamp("2026-10-29", tz="UTC"))   # the grade-time hole (bar_gaps_last_30d)
RECORDS = [  # (record, window_start, window_end, served model dir, candidate: committed dir or None -> refit as of asof)
    {"run": "42257779569", "start": "2026-10-23", "end": "2026-11-05", "served": "ml_decision_entry_v1",
     "candidate": "ml_decision_entry_v1r20261106", "asof": "2026-10-23"},
    {"run": "42473814600", "start": "2026-10-25", "end": "2026-11-07", "served": "ml_decision_entry_v1r20261106",
     "candidate": None, "asof": "2026-10-25"},
]


def hourly_gaps(ts: pd.Series) -> list[dict]:
    t = ts.reset_index(drop=True)
    d = t.diff()
    return [{"after": str(t[i - 1]), "before": str(t[i]), "missing_hours": int(d[i] / pd.Timedelta(hours=1)) - 1}
            for i in d[d > pd.Timedelta(hours=1)].index]


def census(cache: Path, symbols: list[str]) -> dict:
    wins, per_sym = {}, {}
    for s in symbols:
        ts = pd.read_pickle(cache / f"{s}.pkl")["ts"]
        g = hourly_gaps(ts)
        per_sym[s] = {"first_bar": str(ts.min()), "last_bar": str(ts.max()), "n_bars": int(len(ts)),
                      "n_holes": len(g), "missing_hours": sum(x["missing_hours"] for x in g)}
        for x in g:
            wins.setdefault((x["after"], x["before"]), []).append(s)
    return {"n_symbols": len(symbols), "n_symbols_with_holes": sum(1 for v in per_sym.values() if v["n_holes"]),
            "n_distinct_windows": len(wins),
            "windows": [{"after": a, "before": b, "missing_hours": int((pd.Timestamp(b) - pd.Timestamp(a)) / pd.Timedelta(hours=1)) - 1,
                         "n_symbols": len(v), "symbols": sorted(v)} for (a, b), v in sorted(wins.items())],
            "per_symbol": per_sym}


def drop_hole(src: Path, dst: Path, symbols: list[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for s in symbols:
        df = pd.read_pickle(src / f"{s}.pkl")
        pd.to_pickle(df[~((df.ts >= HOLE[0]) & (df.ts < HOLE[1]))].reset_index(drop=True), dst / f"{s}.pkl")


def table_diff(legacy: pd.DataFrame, safe: pd.DataFrame) -> dict:
    k = ["symbol", "ts"]
    m = legacy.merge(safe, on=k, how="outer", suffixes=("_l", "_s"), indicator=True)
    both = m[m["_merge"] == "both"]
    feat = {}
    for f in E.FEATURES:
        a, b = both[f + "_l"].to_numpy(float), both[f + "_s"].to_numpy(float)
        feat[f] = round(float(np.mean(~np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))), 6)
    lab = {c: round(float(np.mean(~np.isclose(both[c + "_l"].to_numpy(float), both[c + "_s"].to_numpy(float), rtol=1e-9, atol=1e-12,
                                              equal_nan=True))), 6) for c in ("net_long", "net_short")}
    only_l = m[m["_merge"] == "left_only"]
    return {"legacy_rows": int(len(legacy)), "safe_rows": int(len(safe)), "common": int(len(both)),
            "legacy_only": int(len(only_l)), "safe_only": int((m["_merge"] == "right_only").sum()),
            "legacy_only_by_month": {str(k_): int(v) for k_, v in only_l.ts.dt.strftime("%Y-%m").value_counts().sort_index().items()},
            "common_rows_with_feature_diff_fraction": feat, "common_rows_with_label_diff_fraction": lab,
            "common_rows_any_feature_diff": int((np.column_stack([~np.isclose(both[f + "_l"].to_numpy(float), both[f + "_s"].to_numpy(float),
                                                                              rtol=1e-9, atol=1e-12, equal_nan=True) for f in E.FEATURES])).any(axis=1).sum())}


def score(models: dict, tab: pd.DataFrame, rec: dict, tau: float) -> dict:
    t = tab[(tab.ts >= pd.Timestamp(rec["start"], tz="UTC")) & (tab.ts < pd.Timestamp(rec["end"], tz="UTC"))]   # last labelled day = window_end - 1 (a decision needs 24 forward bars; the grade run's data ended at window_end), matching the committed window_rows
    if t.empty:
        return {"window_rows": 0, "n": 0}
    pl, ps = models["long"].predict(t[E.FEATURES]), models["short"].predict(t[E.FEATURES])
    r = E.summarize(E.policy(t, pl, ps, tau))
    keep = ("n", "mean_net_r", "sum_net_r", "se_net_r", "n_symbols", "by_side")
    return {"window_rows": int(len(t)), **{k: r.get(k) for k in keep}}


def regrade(cache: Path, out: Path, refit: bool) -> dict:
    syms = E.universe()
    holed = out / "lake_holed"
    drop_hole(cache, holed, syms)
    builds = {}
    for name, c in (("complete", cache), ("hole_10_28", holed)):
        for hs in (False, True):
            builds[(name, hs)] = E.build_table(c, syms, hole_safe=hs)
    res = {"table_diff_complete_lake": table_diff(builds[("complete", False)], builds[("complete", True)]),
           "table_diff_hole_10_28_lake": table_diff(builds[("hole_10_28", False)], builds[("hole_10_28", True)]), "records": {}}
    for rec in RECORDS:
        ev = json.loads((REPO / f"comms/research/ml_entry_grade/{rec['run']}/grade_evidence.json").read_text())
        smeta, sboost = E._frozen_models(REPO / "ml/served" / rec["served"] / "model.json")
        tau = float(ev["tau"])
        cand_kind = "committed booster"
        if rec["candidate"]:
            _, cboost = E._frozen_models(REPO / "ml/served" / rec["candidate"] / "model.json")
        elif refit:
            asof = pd.Timestamp(rec["asof"], tz="UTC")
            cboost = {k: v.booster_ for k, v in E.fit_models(E.purge_train(builds[("complete", True)][builds[("complete", True)].ts < asof], asof)).items()}
            cand_kind = "REFIT hole-safe on the complete lake (not bit-reproducible vs the graded booster, which is not committed)"
        else:
            cboost, cand_kind = None, "not re-scored (booster not committed; pass --refit)"
        r = {"window": [rec["start"], rec["end"]], "tau": tau, "served_model": rec["served"], "candidate_kind": cand_kind,
             "as_committed": {"served": ev["served"]["result"] | {"by_month": None}, "candidate": ev["candidate"]["result"],
                              "window_rows": ev["window_rows"], "verdict": ev["verdict"]}, "regrade": {}}
        for (name, hs), tab in builds.items():
            key = f"{name}/{'hole_safe' if hs else 'legacy'}"
            r["regrade"][key] = {"served": score(sboost, tab, rec, tau)}
            if cboost is not None:
                r["regrade"][key]["candidate"] = score(cboost, tab, rec, tau)
        res["records"][rec["run"]] = r
    return res


def _self_test() -> None:
    ts = pd.Series(pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC")).drop([3, 4, 5])
    g = hourly_gaps(ts)
    assert len(g) == 1 and g[0]["missing_hours"] == 3, g
    assert E.build_table.__defaults__[-1] is True, "hole_safe must default ON"
    print("ml_entry_hole_safe_census self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--out")
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = E.universe()
    c = census(Path(a.cache), syms)
    (out / "census.json").write_text(json.dumps(c, indent=1) + "\n")
    print(f"census: {c['n_symbols_with_holes']}/{c['n_symbols']} symbols, {c['n_distinct_windows']} windows", flush=True)
    res = regrade(Path(a.cache), out, a.refit)
    (out / "regrade.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    shutil.rmtree(out / "lake_holed", ignore_errors=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
