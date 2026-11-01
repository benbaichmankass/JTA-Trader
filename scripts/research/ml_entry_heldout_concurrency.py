#!/usr/bin/env python3
"""ml_entry held-out CONCURRENCY + per-symbol population (lane ML-ENTRY universe widening, 2026-11-01).

Re-runs the c692-01 final fit exactly as ``ml_decision_entry.traded_subset`` does (same universe, same purge, same
LightGBM params, tau from the c692-01 summary) and scores the sealed held-out window ``HOLDOUT_START..END`` that
c692-01 already read. It reads no new window; it re-derives what that read produced, adding what the summary does not
keep:

* per-symbol held-out n and mean net R (the population a widened traded universe is drawn from);
* each taken decision's open interval, from which the number of ml_entry positions open at once is counted.

Interval: a decision at bar t (``ts`` = bar t's open, decided at its close) enters at bar t+1's open = ts + 1h and
exits inside bar t+j (j = ``bars_<side>``), i.e. no later than ts + (j + 1)h. Counting to that upper bound makes the
concurrency figures conservative (a position is counted open for at most one hour longer than it was).

Concurrency is reported over the hourly grid of the held-out window (time-weighted) and at entry instants, for the
full population and for any ``--subset`` list (e.g. the Bybit-listed symbols).

Writes ``<out>/summary.json`` and ``<out>/decisions.csv.gz``. Read-only: no order path, no VM.
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
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts/research"))

import ml_decision_entry as mde  # noqa: E402

C692_01_SUMMARY = REPO / "comms/research/RQ-20261101-c692-01/local-20261101T0835Z/summary.json"


def heldout_decisions(cache: Path) -> tuple[pd.DataFrame, dict]:
    tau = json.loads(C692_01_SUMMARY.read_text())["walk_forward"]["tau_star"]
    syms = mde.universe()
    mde.fetch(cache, syms)
    tab = mde.build_table(cache, syms)
    hs = pd.Timestamp(mde.HOLDOUT_START, tz="UTC")
    train = mde.purge_train(tab[tab.ts < hs], hs)
    models = mde.fit_models(train)
    test = tab[tab.ts >= hs]
    # provenance: predict — LGBMRegressor.predict is the regressed net R of that side, not a probability
    pl, ps = models["long"].predict(test[mde.FEATURES]), models["short"].predict(test[mde.FEATURES])
    taken = mde.policy(test, pl, ps, tau)
    bars = test[["symbol", "ts", "bars_long", "bars_short", "atr", "entry"]]
    taken = taken.merge(bars, on=["symbol", "ts"], how="left", validate="one_to_one")
    taken["bars"] = np.where(taken.side == "long", taken.bars_long, taken.bars_short).astype(int)
    taken["stop_pct"] = mde.SL_ATR * taken.atr / taken.entry
    taken["open_ts"] = pd.to_datetime(taken.ts, utc=True) + pd.Timedelta(hours=1)
    taken["close_ts"] = pd.to_datetime(taken.ts, utc=True) + pd.to_timedelta(taken.bars + 1, unit="h")
    meta = {"tau": tau, "n_train": len(train), "n_test_rows": len(test), "universe_size": len(syms),
            "window": [str(test.ts.min()), str(test.ts.max())]}
    return taken.drop(columns=["bars_long", "bars_short"]), meta


def _q(a, p) -> float:
    return float(np.percentile(a, p))


def concurrency(taken: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    if taken.empty:
        return {"n": 0}
    grid = pd.date_range(start.floor("h"), end.ceil("h"), freq="h", tz="UTC")
    g = grid.to_numpy().astype("datetime64[ns]").astype("int64")
    o = taken.open_ts.to_numpy().astype("datetime64[ns]").astype("int64")
    c = taken.close_ts.to_numpy().astype("datetime64[ns]").astype("int64")
    # open at hour h  <=>  open_ts <= h < close_ts
    hourly = np.searchsorted(np.sort(o), g, side="right") - np.searchsorted(np.sort(c), g, side="right")
    at_entry = np.searchsorted(np.sort(o), o, side="right") - np.searchsorted(np.sort(c), o, side="right")
    peak_i = int(np.argmax(hourly))
    peak_h = grid[peak_i]
    open_at_peak = taken[(taken.open_ts <= peak_h) & (taken.close_ts > peak_h)]
    return {"n": len(taken), "n_symbols": int(taken.symbol.nunique()), "hours": len(grid),
            "hourly": {"max": int(hourly.max()), "p99": _q(hourly, 99), "p95": _q(hourly, 95), "p50": _q(hourly, 50),
                       "mean": float(hourly.mean()), "share_hours_zero": float((hourly == 0).mean())},
            "at_entry": {"max": int(at_entry.max()), "p95": _q(at_entry, 95), "p50": _q(at_entry, 50)},
            "peak_hour": str(peak_h), "peak_open_by_side": open_at_peak.side.value_counts().to_dict(),
            "peak_open_symbols": sorted(open_at_peak.symbol.tolist()),
            "mean_hold_h": float((taken.close_ts - taken.open_ts).dt.total_seconds().mean() / 3600)}


def margin_sim(taken: pd.DataFrame, risk_pct: float, leverage: float, buffer: float) -> dict:
    """Summed open stop-risk (fraction of equity) over the held-out entries, ml_entry ALONE on the account.

    Each entry is sized as ``RiskManager.position_size`` does: notional = risk_pct * E / stop_pct, then clamped by the
    margin pre-flight to (available * leverage * buffer), available = E - sum(open notional) / leverage. Equity is
    held at E (no PnL), so the clamp is the only thing that changes a position's size. Other bybit_2 legs share the
    same margin, so in live trading the clamp binds EARLIER than here.
    """
    ev = []
    for r in taken.itertuples(index=False):
        ev.append((r.open_ts.value, 1, r.stop_pct))
        ev.append((r.close_ts.value, 0, r.stop_pct))
    ev.sort(key=lambda x: (x[0], x[1]))           # closes before opens at the same instant
    open_pos: list[tuple[float, float]] = []      # (notional_mult, stop_pct) ; FIFO by stop_pct match on close
    raw_risk, clamped_risk, notional_tot, n_clamped, n_refused = [], [], [], 0, 0
    for _t, kind, sp in ev:
        if kind == 0:
            for i, (_nm, s_) in enumerate(open_pos):
                if s_ == sp:
                    open_pos.pop(i)
                    break
            continue
        want = risk_pct / sp
        used = sum(nm for nm, _ in open_pos)
        cap = max(0.0, (1.0 - used / leverage) * leverage * buffer)
        got = min(want, cap)
        if got < want:
            n_clamped += 1
        if got <= 0:
            n_refused += 1
        open_pos.append((got, sp))
        raw_risk.append(risk_pct * len(open_pos))
        clamped_risk.append(sum(nm * s_ for nm, s_ in open_pos))
        notional_tot.append(sum(nm for nm, _ in open_pos))
    return {"risk_pct": risk_pct, "leverage": leverage, "buffer": buffer, "entries": len(raw_risk),
            "summed_stop_risk_unclamped_pct_equity": {"max": 100 * max(raw_risk), "p95": 100 * _q(raw_risk, 95),
                                                       "p50": 100 * _q(raw_risk, 50)},
            "summed_stop_risk_margin_clamped_pct_equity": {"max": 100 * max(clamped_risk),
                                                           "p95": 100 * _q(clamped_risk, 95), "p50": 100 * _q(clamped_risk, 50)},
            "gross_notional_x_equity": {"max": max(notional_tot), "p95": _q(notional_tot, 95), "p50": _q(notional_tot, 50)},
            "entries_clamped_by_margin": n_clamped, "entries_refused_by_margin": n_refused,
            "stop_pct": {"p50": float(taken.stop_pct.median()), "p05": float(taken.stop_pct.quantile(0.05)),
                         "p95": float(taken.stop_pct.quantile(0.95))},
            "notional_x_equity_per_trade_p50": float((risk_pct / taken.stop_pct).median())}


def per_symbol(taken: pd.DataFrame) -> dict:
    return {k: {"n": len(g), "mean_net_r": round(float(g.net_r.mean()), 4)}
            for k, g in sorted(taken.groupby("symbol"), key=lambda kv: kv[0])}


def pooled(taken: pd.DataFrame) -> dict:
    return {"n": len(taken), "mean_net_r": float(taken.net_r.mean()) if len(taken) else None,
            "n_symbols": int(taken.symbol.nunique())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", required=True)
    ap.add_argument("--save-decisions", default="", help="also pickle the decision frame here (re-analysis)")
    ap.add_argument("--risk-pct", type=float, default=0.015)
    ap.add_argument("--leverage", type=float, default=3.0)
    ap.add_argument("--margin-buffer", type=float, default=0.9)
    ap.add_argument("--subset", action="append", default=[],
                    help="NAME=SYM1,SYM2,... ; repeatable. Each subset gets its own pooled / concurrency block.")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    taken, meta = heldout_decisions(Path(args.cache))
    start = pd.Timestamp(mde.HOLDOUT_START, tz="UTC")
    end = taken.close_ts.max()
    res = {"schema": "ml_entry_heldout_concurrency/1", "source": "c692-01 final fit, re-run (ml_decision_entry.fit_models)",
           "meta": meta, "pooled": pooled(taken),
           "reproduces_c692_01": {"n": len(taken), "mean_net_r": float(taken.net_r.mean()),
                                  "c692_01_n": json.loads(C692_01_SUMMARY.read_text())["holdout"]["model"]["n"],
                                  "c692_01_mean_net_r": json.loads(C692_01_SUMMARY.read_text())["holdout"]["model"]["mean_net_r"]},
           "per_symbol": per_symbol(taken), "concurrency_all": concurrency(taken, start, end),
           "margin_all": margin_sim(taken, args.risk_pct, args.leverage, args.margin_buffer), "subsets": {},
           "interval_rule": "open [ts+1h, ts+(bars+1)h): exit counted to the END of the exit bar (upper bound)",
           "git_sha": mde._git_sha()}
    for spec in args.subset:
        name, _, lst = spec.partition("=")
        keep = {s.strip() for s in lst.split(",") if s.strip()}
        sub = taken[taken.symbol.isin(keep)]
        res["subsets"][name] = {"symbols": sorted(keep), "missing_from_population": sorted(keep - set(taken.symbol)),
                                "pooled": pooled(sub), "concurrency": concurrency(sub, start, end),
                                "margin": margin_sim(sub, args.risk_pct, args.leverage, args.margin_buffer) if len(sub) else None}
    res["elapsed_s"] = round(time.time() - t0)
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    taken.to_csv(out / "decisions.csv.gz", index=False)
    if args.save_decisions:
        taken.to_pickle(args.save_decisions)
    print(json.dumps({k: res[k] for k in ("pooled", "reproduces_c692_01")}, default=str), flush=True)
    print(json.dumps(res["concurrency_all"], default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
