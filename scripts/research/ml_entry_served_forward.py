#!/usr/bin/env python3
# wiring: research/queue/RQ-20261119-b9d0-02.yaml (PI-20261118-JX6BUNMV-0001: forward read of the SERVED ENTRY refit v1r20261115)
"""FORWARD READ of the served ENTRY refit ml-decision-entry-v1r20261115 on the real-money (bybit_2) symbols (Tier-1 research;
reads public klines and a committed artifact; no order, no config, no registry).

The refit is what trades real money on bybit_2 since #26288 (2026-11-18 22:59Z). Its record is the promotion grade of
RULE-ENTRY-PROMOTE-20261106 on 2026-11-01..2026-11-14 (the window it was SELECTED on, over the 60-symbol universe). This read asks
how it does on decisions it was neither trained nor selected on, on the symbols that carry money:

  FRESH windows (gating): A = [the UTC day after train_end_exclusive, 2026-11-01)  (the purge gap: no training row, never graded)
                          B = [2026-11-15, --end]                 (after the grade's data_through 2026-11-14)
  SELECTION slice (reported, never gating): [2026-11-01, 2026-11-15)

Decisions: ``ml_decision_entry.policy`` (sequential, one position per symbol, tau from the artifact) on the c692-01 table built over
the artifact's universe (as the promotion grade built it), kept on ``traded_symbols()`` (bybit_2, re-parsed at run time). Outcome:
the c692-01 label's fixed bracket (SL 2xATR14, TP 3xATR14, 24 h), net of fee 11 + slippage 3 bps + funding 1 bps per 8 h; a
DECLARED fidelity gap vs the live exit. Decisions whose 24 h outcome passes the last fetched bar are dropped by the table build.
The read is claimed in the holdout ledger BEFORE any outcome is computed. The frozen v1 booster scores the same rows with its own
policy (reported, never gating).

    python3 scripts/research/ml_entry_served_forward.py --unit RQ-20261119-b9d0-02 --out O [--end YYYY-MM-DD] [--cache C]
    python3 scripts/research/ml_entry_served_forward.py --self-test
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

UNIT = "RQ-20261119-b9d0-02"
RULE_ID = "RULE-RQ20261119-b9d0-02-ENTRY-SERVED-FWD"
MODEL_ID = "ml-decision-entry-v1r20261115"
ART = REPO / "ml/served/ml_decision_entry_v1r20261115/model.json"
FROZEN_V1 = REPO / "comms/research/RQ-20261101-c692-06/41324826751/model"
SEL_START, SEL_END_EXCL = "2026-11-01", "2026-11-15"   # the promotion grade's window (selection), reported only
MIN_N = 60
REPS, SEED = 2000, 20261119


def window_a_start(train_end_excl: str) -> pd.Timestamp:
    """The next UTC midnight after the training end: the holdout ledger is date-grained and needs start > train_end."""
    te = pd.Timestamp(train_end_excl)
    te = te.tz_localize("UTC") if te.tzinfo is None else te.tz_convert("UTC")
    return te.normalize() + pd.Timedelta(days=1)


def windows(train_end_excl: str, end: str) -> dict:
    return {"A": (window_a_start(train_end_excl), pd.Timestamp(SEL_START, tz="UTC")),
            "SEL": (pd.Timestamp(SEL_START, tz="UTC"), pd.Timestamp(SEL_END_EXCL, tz="UTC")),
            "B": (pd.Timestamp(SEL_END_EXCL, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))}


def label_window(ts: pd.Series, w: dict) -> pd.Series:
    out = pd.Series("out", index=ts.index)
    for k, (lo, hi) in w.items():
        out[(ts >= lo) & (ts < hi)] = k
    return out


def bar_clustered(dec_ts: pd.Series, net: np.ndarray, reps: int = REPS, seed: int = SEED) -> dict:
    """Mean net R per decision with a bootstrap CI that resamples decision BARS (same-bar decisions move together)."""
    n = len(net)
    if n == 0:
        return {"n": 0, "mean_net_r": None, "sum_net_r": None, "ci95": None, "bars": 0}
    codes, _ = pd.factorize(pd.to_datetime(dec_ts, utc=True))
    nb = int(codes.max()) + 1
    s = np.bincount(codes, weights=net, minlength=nb)
    c = np.bincount(codes, minlength=nb).astype(float)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(reps):
        j = rng.integers(0, nb, nb)
        bs.append(s[j].sum() / c[j].sum())
    return {"n": n, "bars": nb, "mean_net_r": round(float(net.mean()), 4), "sum_net_r": round(float(net.sum()), 3),
            "ci95": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]}


def rule_verdict(fresh: dict) -> tuple[str, str]:
    n, ci = fresh["n"], fresh["ci95"]
    if n < MIN_N or ci is None:
        return "indeterminate", f"{n} fresh decisions < {MIN_N}"
    txt = f"mean net R {fresh['mean_net_r']:+.4f}/decision, bar-clustered CI95 {ci}, n {n}"
    if ci[0] > 0:
        return "pass", f"{txt}: the served refit makes money on fresh real-money-symbol decisions"
    if ci[1] < 0:
        return "fail", f"{txt}: the served refit LOSES on fresh real-money-symbol decisions (demotion evidence for the operator)"
    return "indeterminate", f"{txt}: CI spans 0"


def E_traded() -> list[str]:
    import ml_decision_entry as E
    return E.traded_symbols()


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # allow-silent: provenance only; recorded as unknown
        return "unknown"


def decisions(cache: Path, out: Path, end: str, art: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    import lightgbm as lgb
    import ml_decision_entry as E
    import ml_entry_tp_revision as TPR
    syms = E.universe()
    E.fetch(cache, syms, end=E.END)
    TPR.FWD_START, TPR.FWD_END = (pd.Timestamp(E.END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), end
    fwd = out / "fwd_cache"
    rep = TPR.forward_cache(cache, fwd, syms)
    have = [x for x in syms if (fwd / f"{x}.pkl").exists()]
    tab = E.build_table(fwd, have)
    w = windows(art["train_end_exclusive"], end)
    test = tab[(tab.ts >= w["A"][0]) & (tab.ts < w["B"][1])].reset_index(drop=True)
    feats = art.get("features") or E.FEATURES
    traded = E.traded_symbols()
    res = []
    served = {s: lgb.Booster(model_str=art["booster_txt"][s]) for s in ("long", "short")}
    frozen = {s: lgb.Booster(model_file=str(FROZEN_V1 / f"entry_{s}.txt")) for s in ("long", "short")}
    for name, bst, fl, tau in (("served", served, feats, float(art["tau"])), ("frozen_v1", frozen, E.FEATURES, 0.10)):
        # provenance: predict — each regression booster's predicted net R for that side (what policy() thresholds at tau), not a probability
        taken = E.policy(test, bst["long"].predict(test[fl]), bst["short"].predict(test[fl]), tau)
        taken = taken[taken.symbol.isin(traded)].reset_index(drop=True)
        d = pd.DataFrame({"model": name, "symbol": taken.symbol, "side": taken.side,
                          "decision_ts": pd.to_datetime(taken.ts, utc=True), "net_r": taken.net_r.astype(float),
                          "score": taken.pred.astype(float)})
        d["window"] = label_window(d.decision_ts, w)
        res.append(d)
    meta = {"universe": len(syms), "symbols_with_window_data": len(have), "traded_symbols": traded, "window_rows": len(test),
            "window_last_ts": str(test.ts.max()) if len(test) else None,
            "windows": {k: [str(a), str(b)] for k, (a, b) in w.items()},
            "fetch_days": {k: v.get("oct_days") for k, v in rep.items() if k in traded}}
    return res[0], res[1], meta


def run(a) -> int:
    import holdout_lock as HL
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    art = json.loads(ART.read_text())
    assert art["model_id"] == MODEL_ID, art["model_id"]
    try:
        from src.runtime.ml_entry_served import served_artifact
        still_served = Path(served_artifact()).resolve() == ART.resolve()
    except Exception as e:  # allow-silent: reported beside the result, the read is of this artifact either way
        still_served = f"unknown ({type(e).__name__})"
    end = a.end or (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    led = out / "holdout_reads.jsonl"
    if not led.exists() and HL.LEDGER.exists():
        shutil.copy(HL.LEDGER, led)
    claim = HL.claim_read(model_id=MODEL_ID, start=str(window_a_start(art["train_end_exclusive"]).date()), end=end, unit=UNIT,
                          reader="ml_entry_served_forward", ledger=led, symbols=E_traded(),
                          train_end=str(pd.Timestamp(art["train_end_exclusive"]).date()), family="ENTRY")   # BEFORE any outcome
    srv, frz, meta = decisions(Path(a.cache), out, end, art)
    pd.concat([srv, frz]).to_csv(out / "forward_decisions.csv.gz", index=False)
    by = {}
    for name, d in (("served", srv), ("frozen_v1", frz)):
        fr = d[d.window.isin(["A", "B"])]
        by[name] = {"fresh": bar_clustered(fr.decision_ts, fr.net_r.to_numpy()),
                    **{k: bar_clustered(d[d.window == k].decision_ts, d[d.window == k].net_r.to_numpy()) for k in ("A", "B", "SEL")}}
    v, why = rule_verdict(by["served"]["fresh"])
    meas = {"unit": UNIT, "rule_id": RULE_ID, "model_id": MODEL_ID, "artifact": str(ART.relative_to(REPO)),
            "artifact_still_served": still_served, "end": end, "holdout_claim": claim, **meta, "reads": by,
            "outcome": "c692-01 label fixed bracket (SL 2xATR14, TP 3xATR14, 24h), net of fee 11 + slip 3 bps + funding 1 bps/8h; "
                       "DECLARED fidelity gap vs the live exit",
            "reported_never_gating": "SEL slice (the promotion grade's selection window); frozen_v1 on the same rows",
            "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "measurement.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"research_unit": UNIT, "rule_id": RULE_ID, "verdict": v, "read_state": "measured", "n": int(by["served"]["fresh"]["n"]),
          "note": why, "population": (f"{MODEL_ID} decisions on the bybit_2 symbols in the fresh windows A [train_end, {SEL_START}) and "
                                      f"B [{SEL_END_EXCL}, {end}] (tau {art['tau']}, sequential one-position-per-symbol policy), "
                                      "fixed-bracket outcome"), "measurement": meas}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    shutil.rmtree(out / "fwd_cache", ignore_errors=True)
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


def _self_test() -> None:
    w = windows("2026-10-23 19:00:00+00:00", "2026-11-28")
    ts = pd.Series(pd.to_datetime(["2026-10-23 18:00", "2026-10-23 19:00", "2026-11-01 00:00", "2026-11-14 23:00",
                                   "2026-11-15 00:00", "2026-11-28 23:00", "2026-11-29 00:00"], utc=True))
    assert label_window(ts, w).tolist() == ["out", "out", "SEL", "SEL", "B", "B", "out"], label_window(ts, w).tolist()
    assert window_a_start("2026-10-23 19:00:00+00:00") == pd.Timestamp("2026-10-24", tz="UTC")
    b = bar_clustered(pd.Series(pd.to_datetime(["2026-11-15 00:00"] * 2 + ["2026-11-15 04:00"], utc=True)),
                      np.array([1.0, 1.0, -1.0]), reps=200)
    assert b["n"] == 3 and b["bars"] == 2 and b["mean_net_r"] == round(1 / 3, 4) and b["ci95"][0] <= b["ci95"][1]
    assert bar_clustered(pd.Series([], dtype="datetime64[ns, UTC]"), np.array([]))["n"] == 0
    f = {"n": 80, "ci95": [0.01, 0.2], "mean_net_r": 0.1}
    assert rule_verdict(f)[0] == "pass"
    assert rule_verdict({**f, "ci95": [-0.3, -0.01], "mean_net_r": -0.1})[0] == "fail"
    assert rule_verdict({**f, "ci95": [-0.1, 0.2]})[0] == "indeterminate"
    assert rule_verdict({**f, "n": 59})[0] == "indeterminate"
    art = json.loads(ART.read_text())
    assert art["model_id"] == MODEL_ID and set(art["booster_txt"]) == {"long", "short"} and art["tau"] > 0
    assert pd.Timestamp(art["train_end_exclusive"]) < pd.Timestamp(SEL_START, tz="UTC")
    print("ml_entry_served_forward self-test OK")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--unit", default=UNIT)
    p.add_argument("--out", default="out/entry_served_forward")
    p.add_argument("--cache", default="/tmp/klines")
    p.add_argument("--end", help="last decision day (inclusive); default today - 2 d so every 24 h outcome is complete")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.unit != UNIT:
        raise SystemExit(f"this harness answers {UNIT} only, got {a.unit}")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
