#!/usr/bin/env python3
# wiring: manual-only - run by the research queue unit emitted from programme node P3-Q3-soak-equity-overlap (research-script-run.yml, via queue_replenish); otherwise a session runs it by hand.
"""Overlap / leave-one-out read of the soak-book 1d legs' committed Stage-0 trade ledgers.

Question (programme 03 node P3-Q3-soak-equity-overlap): SPY / QQQ / QLD / IWM trend legs are one
equity-beta factor on paper. Are the legs that passed Stage 0 separate bets, or one bet counted
several times, before any MD-PROMOTE-S1-S2 case is made for them?

Statistic (registered in the unit, not changed after a result). Per leg, each trade's ``net_r`` is
spread evenly over its calendar holding days (entry..exit inclusive) so two legs that are long the
same equity move at the same time overlap even when they exit in different weeks; weekly net R =
the sum of those daily amounts in each W-SUN week, over the weeks every leg's ledger covers. Pairwise Pearson correlation of those series; N_eff = (sum lambda)^2 / sum lambda^2 over the
correlation matrix's eigenvalues (participation ratio: k identical series give 1, k independent give
k). Leave-one-out: equal-weight pooled weekly net R with each leg dropped, mean / sd of the weekly
series (an information ratio, not an annualised Sharpe).

Reads committed ledgers only: no network, no config, places nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_weekly(path: str) -> pd.Series:
    rows = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        raise ValueError(f"{path}: no trades")
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True).dt.normalize()
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True).dt.normalize()
    daily: dict[pd.Timestamp, float] = {}
    for t0, t1, r in zip(df["entry_time"], df["exit_time"], df["net_r"].astype(float)):
        days = pd.date_range(t0, max(t1, t0), freq="D")
        for d in days:
            daily[d] = daily.get(d, 0.0) + r / len(days)
    return pd.Series(daily).sort_index().resample("W-SUN").sum()


def n_eff(corr: np.ndarray) -> float:
    lam = np.clip(np.linalg.eigvalsh(corr), 0.0, None)
    return float(lam.sum() ** 2 / (lam ** 2).sum())


def ir(s: pd.Series) -> float | None:
    sd = float(s.std(ddof=1))
    return round(float(s.mean()) / sd, 4) if sd > 0 else None


def analyse(ledgers: dict[str, str], min_weeks: int, min_neff: float, same_bet_corr: float) -> dict:
    series = {leg: load_weekly(p) for leg, p in ledgers.items()}
    lo = max(s.index.min() for s in series.values())
    hi = min(s.index.max() for s in series.values())
    wk = pd.date_range(lo, hi, freq="W-SUN")
    df = pd.DataFrame({leg: s.reindex(wk).fillna(0.0) for leg, s in series.items()})
    if len(df) < min_weeks or len(df.columns) < 2:
        return {"verdict": "indeterminate", "read_state": "measured", "n": int(len(df)),
                "note": f"INDETERMINATE: {len(df)} common weeks (< {min_weeks}) or < 2 legs"}
    corr = df.corr()
    neff = n_eff(corr.to_numpy())
    pairs = [(a, b, round(float(corr.loc[a, b]), 3)) for i, a in enumerate(df.columns) for b in df.columns[i + 1:]]
    same = [p for p in pairs if p[2] >= same_bet_corr]
    pooled = df.mean(axis=1)
    loo = {leg: {"pooled_ir_without": ir(df.drop(columns=leg).mean(axis=1))} for leg in df.columns}
    verdict = "pass" if neff >= min_neff else "fail"
    return {
        "verdict": verdict, "read_state": "measured", "n": int(len(df)),
        "population": {"description": f"{len(df.columns)} legs, {len(df)} common weeks "
                                      f"{wk[0].date()}..{wk[-1].date()}, weekly net R (trade R spread over its holding days) from committed "
                                      "ledgers (net of the harness cost stack)", "n": int(len(df))},
        "measurement": {"n_eff": round(neff, 3), "corr": {a: {b: round(float(corr.loc[a, b]), 3) for b in df.columns}
                                                          for a in df.columns},
                        "same_bet_pairs": same, "pooled_ir": ir(pooled), "leave_one_out": loo,
                        "per_leg_ir": {leg: ir(df[leg]) for leg in df.columns}},
        "note": f"{verdict.upper()} / n_eff {neff:.2f} of {len(df.columns)} legs (bar >= {min_neff}); "
                f"{len(same)} pair(s) with corr >= {same_bet_corr}",
    }


def _selftest() -> int:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2015-01-04", periods=400, freq="W-SUN", tz="UTC")
    base = rng.normal(size=400)

    def ledger(tmp: Path, name: str, x: np.ndarray) -> str:
        p = tmp / f"{name}.jsonl"
        p.write_text("".join(json.dumps({"entry_time": str(t - pd.Timedelta(days=3)), "exit_time": str(t), "net_r": float(v)}) + "\n" for t, v in zip(idx, x)))
        return str(p)

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        same = {f"l{i}": ledger(tmp, f"s{i}", base + 0.05 * rng.normal(size=400)) for i in range(3)}
        indep = {f"l{i}": ledger(tmp, f"i{i}", rng.normal(size=400)) for i in range(3)}
        a = analyse(same, 100, 2.0, 0.5)
        b = analyse(indep, 100, 2.0, 0.5)
    assert a["verdict"] == "fail" and a["measurement"]["n_eff"] < 1.3, a
    assert b["verdict"] == "pass" and b["measurement"]["n_eff"] > 2.4, b
    print("self-test ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--leg", action="append", default=[], help="NAME=path/to/trades.jsonl (repeat)")
    ap.add_argument("--min-weeks", type=int, default=104)
    ap.add_argument("--min-neff", type=float, default=2.0)
    ap.add_argument("--same-bet-corr", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _selftest()
    ledgers = dict(x.split("=", 1) for x in a.leg)
    rec = analyse(ledgers, a.min_weeks, a.min_neff, a.same_bet_corr)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"], "note": rec["note"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
