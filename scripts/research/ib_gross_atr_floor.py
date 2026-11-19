#!/usr/bin/env python3
# wiring: manual-only - run by queue unit RQ-20261119-b9a4-01 (research-script-run.yml, once the manager merges it); no schedule consumes it.
"""IB-GROSS-ATR-FLOOR-S0 -- does flooring the futures risk distance at k x ATR14 cap gross exposure without giving up the dollar edge?

Registered BEFORE any run: work-store event 16958 on row IB-GROSS-NO-CAP-FIX (AM-OPS-4, 2026-11-19 01:17Z), rule id RULE-IB-GROSS-ATR-FLOOR-S0.
This file is that rule made executable; nothing here is tunable. Tier-1 research tooling: reads committed evidence and public candles, writes only
under --out, changes no sizer and no config.

CORPUS  the committed Stage-0 per-trade rows (net of the full cost stack, each with entry, sl, net_r) under
        comms/strategy_evidence/runs/2026-09-24-e55/: mgc_trend_1h, mhg_pullback_1d, mgc_pullback_1d, mes_trend_long_1d (141 trades at registration).
        ict_scalp_mgc_15m is EXCLUDED (no committed per-trade rows). Each leg's TIMEFRAME is read from its ``__bt.json`` (field beats filename: the
        two ``*_pullback_1d`` legs are 2h htf_pullback_trend_2h legs and ``mes_trend_long_1d`` is a 1h trend_donchian leg).
ATR14   at entry, from the instrument's bars at the leg's timeframe, using ONLY bars closed before entry_time (bar open + tf <= entry_time);
        the strategies' ATR (``desk_scan_packet.atr_series``, SMA of 14 true ranges). A trade with no such ATR is not "computable".
ARMS    A = current sizing, risk 1.5% of equity over |entry-sl|. B_k = risk distance max(|entry-sl|, k x ATR14), k in {0.5, 1.0}. The SL is unchanged in
        every arm, so each trade's net R is unchanged; only its dollar weight w_i = |entry-sl| / max(|entry-sl|, k x ATR14) changes. A trade with no
        computable ATR keeps w = 1 in every arm (the same trades in every arm). Trades run on ONE compounding equity path in entry_time order;
        sizing equity = the realised equity at entry; a trade's P&L is credited at exit_time; [entry, exit] windows define concurrency; a row with no
        exit_time uses its leg's median hold.
METRICS M1 = max concurrent gross notional / equity (the notional/equity of one trade is 0.015 x E_entry x entry / risk distance, E_entry = equity at
           its entry, divided by the equity now; the contract multiplier cancels). M2 = dollar-weighted return sum(w_i x net_r_i) and its ratio to
           arm A. M3 = total return / max drawdown of the realised equity path.
BAR     PASS for the SMALLEST k where (a) M1 <= 1.5 at every point AND (b) the 80% bootstrap lower bound of M2(B_k)/M2(A) >= 0.80 (10,000 trade
        resamples, seed 20261119; "80% lower bound" = the one-sided 20th percentile) AND (c) M3(B_k) >= 0.90 x M3(A). FAIL if no k passes.
        INDETERMINATE if fewer than 60 trades have a computable ATR14.
POWER   paired design: the same trades in every arm, only the weights differ. If more than 50% of trades are reweighted the bound widens and
        INDETERMINATE is the likely verdict (stated before the run); the reweighted share is reported.
DIAGNOSTIC (reported, not a clause of the rule): for the trend_donchian legs the stop is atr_stop_mult x ATR14 by construction, so
        median(|entry-sl| / (atr_stop_mult x ATR14_mine)) should be about 1; a value far from 1 means this ATR is not the backtest's.
pass_action (data-backed Tier 3): size futures legs on max(stop, k x ATR14); re-read whether 1.5x ever binds on ib_paper and propose retiring both IB
        caps if it never does; read exposure from the venue, not the journal. fail_action: the caps stay; the next lever is a per-leg risk_pct for the
        15m scalp. Gates this adds or changes: none.
Provenance: counts, weights and metrics are MEASURED when a run lands; nothing in this file is a result.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RULE_ID = "RULE-IB-GROSS-ATR-FLOOR-S0"
EVIDENCE = REPO / "comms" / "strategy_evidence" / "runs" / "2026-09-24-e55"
LEGS = ("mgc_trend_1h", "mhg_pullback_1d", "mgc_pullback_1d", "mes_trend_long_1d")
KS = (0.5, 1.0)
RISK_PCT = 0.015
M1_CAP = 1.5
RATIO_BAR = 0.80
M3_FRAC = 0.90
N_ATR_MIN = 60
BOOT = 10_000
SEED = 20261119
LOWER_PCT = 20.0
TF_SEC = {"1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
FETCH_FROM_DAYS_MARGIN = 45


def _t(s: str) -> datetime:
    return datetime.fromisoformat(str(s))


# ----------------------------------------------------------------------------- corpus
def load_corpus(evidence: Path = EVIDENCE) -> List[dict]:
    rows: List[dict] = []
    for leg in LEGS:
        bt = json.loads((evidence / f"{leg}__bt.json").read_text())
        tf = bt["timeframe"]
        trades = [json.loads(x) for x in (evidence / f"{leg}__trades.jsonl").read_text().splitlines() if x.strip()]
        holds = [(_t(r["exit_time"]) - _t(r["entry_time"])).total_seconds() for r in trades if r.get("exit_time")]
        med = statistics.median(holds) if holds else 0.0
        for r in trades:
            et = _t(r["entry_time"])
            xt = _t(r["exit_time"]) if r.get("exit_time") else et + timedelta(seconds=med)
            rows.append({"leg": leg, "symbol": r["symbol"], "tf": tf, "strategy": bt.get("strategy"), "atr_stop_mult": (bt.get("params") or {}).get("atr_stop_mult"),
                         "entry_time": et, "exit_time": xt, "entry": float(r["entry"]), "sl": float(r["sl"]), "net_r": float(r["net_r"]),
                         "dist": abs(float(r["entry"]) - float(r["sl"])), "exit_imputed": not r.get("exit_time")})
    rows.sort(key=lambda r: (r["entry_time"], r["leg"]))
    return rows


def feeds(rows: List[dict]) -> List[tuple]:
    return sorted({(r["symbol"], r["tf"]) for r in rows})


def fetch(root: Path, rows: List[dict]) -> None:
    from scripts.research import desk_replay_driver as d7   # the one candle route (Yahoo futures; CANDLE_DATA_ROOT served on Kaggle)
    first = min(r["entry_time"] for r in rows)
    days = (datetime.now(first.tzinfo) - first).days + FETCH_FROM_DAYS_MARGIN
    for sym, tf in feeds(rows):
        d7.fetch_candles(sym, tf, days, root / "candles" / f"{sym}_{tf}.csv")


def load_bars(root: Path, rows: List[dict]) -> Dict[tuple, Any]:
    import desk_scan_packet as dsp
    out: Dict[tuple, Any] = {}
    for sym, tf in feeds(rows):
        got = dsp.candles_from_dir(root / "candles", [sym], tf).get(sym)
        if not got:
            raise SystemExit(f"no {tf} candles for {sym} under {root / 'candles'}: refusing to score without them")
        bars = sorted(got, key=lambda b: b["time"])
        out[(sym, tf)] = (np.array([b["time"] for b in bars], dtype=np.int64), dsp.atr_series(bars))
    return out


def attach_atr(rows: List[dict], bars: Dict[tuple, Any]) -> None:
    """row['atr'] = ATR14 of the last bar closed at or before entry_time (open + tf <= entry), else None."""
    for r in rows:
        t, atr = bars[(r["symbol"], r["tf"])]
        k = int(np.searchsorted(t + TF_SEC[r["tf"]], int(r["entry_time"].timestamp()), side="right")) - 1
        a = atr[k] if k >= 0 else None
        r["atr"] = float(a) if a is not None and a > 0 else None


# ----------------------------------------------------------------------------- the arms
def weights(rows: List[dict], k: Optional[float]) -> np.ndarray:
    """w_i = |entry-sl| / max(|entry-sl|, k ATR14); 1 for arm A (k None), for a zero-distance row, and for a row with no ATR."""
    w = np.ones(len(rows))
    if k is None:
        return w
    for i, r in enumerate(rows):
        if r["atr"] is not None and r["dist"] > 0:
            w[i] = r["dist"] / max(r["dist"], k * r["atr"])
    return w


def path(rows: List[dict], w: np.ndarray, k: Optional[float]) -> Dict[str, Any]:
    """One compounding realised-equity path (E0 = 1). Returns M1 (max gross notional / equity), total return, max drawdown, M3."""
    ev = []
    for i, r in enumerate(rows):
        ev.append((r["entry_time"], 1, i))
        ev.append((r["exit_time"], 0, i))               # an exit at the same instant as an entry is credited first
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    eq, peak, mdd, m1 = 1.0, 1.0, 0.0, 0.0
    open_: Dict[int, tuple] = {}                         # i -> (notional in equity units at entry, pnl in equity units)
    for _, kind, i in ev:
        r = rows[i]
        if kind == 1:
            risk_dist = r["dist"] if (k is None or r["atr"] is None) else max(r["dist"], k * r["atr"])
            if risk_dist <= 0:
                open_[i] = (0.0, 0.0)
            else:
                open_[i] = (RISK_PCT * eq * r["entry"] / risk_dist, eq * RISK_PCT * w[i] * r["net_r"])
            m1 = max(m1, sum(v[0] for v in open_.values()) / eq)
        else:
            eq += open_.pop(i, (0.0, 0.0))[1]
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
    ret = eq - 1.0
    return {"m1_max": m1, "total_return": ret, "max_drawdown": mdd, "m3": (ret / mdd) if mdd > 0 else (float("inf") if ret > 0 else None)}


def bootstrap_ratio(net_r: np.ndarray, w: np.ndarray, draws: int = BOOT, seed: int = SEED) -> Dict[str, Any]:
    """Distribution of sum(w net_r) / sum(net_r) over trade resamples; a draw whose arm-A sum is not positive counts as -inf (fails)."""
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(net_r), size=(draws, len(net_r)))
    num = (w * net_r)[ix].sum(axis=1)
    den = net_r[ix].sum(axis=1)
    ratio = np.where(den > 0, num / np.where(den > 0, den, 1.0), -np.inf)
    return {"lower_80": float(np.percentile(ratio, LOWER_PCT)), "median": float(np.median(ratio)), "draws_den_not_positive": int((den <= 0).sum())}


def evaluate(rows: List[dict], draws: int = BOOT) -> Dict[str, Any]:
    n = len(rows)
    n_atr = sum(1 for r in rows if r["atr"] is not None)
    net = np.array([r["net_r"] for r in rows])
    res: Dict[str, Any] = {"rule": RULE_ID, "n_trades": n, "n_atr_computable": n_atr, "per_leg": {}, "exit_imputed": sum(1 for r in rows if r["exit_imputed"])}
    for leg in LEGS:
        lr = [r for r in rows if r["leg"] == leg]
        ratios = [r["dist"] / (r["atr_stop_mult"] * r["atr"]) for r in lr if r["atr"] and r["atr_stop_mult"]]
        res["per_leg"][leg] = {"n": len(lr), "timeframe": lr[0]["tf"] if lr else None, "n_atr": sum(1 for r in lr if r["atr"] is not None),
                               "stop_over_atr_median": float(np.median([r["dist"] / r["atr"] for r in lr if r["atr"]])) if any(r["atr"] for r in lr) else None,
                               "stop_vs_atr_stop_mult_median": float(np.median(ratios)) if ratios else None}
    a = path(rows, weights(rows, None), None)
    res["A"] = dict(a, m2=float(net.sum()))
    arms: Dict[str, Any] = {}
    for k in KS:
        w = weights(rows, k)
        p = path(rows, w, k)
        m2 = float((w * net).sum())
        boot = bootstrap_ratio(net, w, draws=draws)
        m3_ok = (p["m3"] is not None and a["m3"] is not None and p["m3"] >= M3_FRAC * a["m3"])
        arms[str(k)] = dict(p, m2=m2, m2_ratio=(m2 / float(net.sum())) if net.sum() > 0 else None, reweighted_share=float((w < 1 - 1e-12).mean()),
                            mean_w=float(w.mean()), ratio_boot=boot, a_m1_ok=bool(p["m1_max"] <= M1_CAP), b_ratio_ok=bool(boot["lower_80"] >= RATIO_BAR),
                            c_m3_ok=bool(m3_ok))
        arms[str(k)]["passes"] = bool(arms[str(k)]["a_m1_ok"] and arms[str(k)]["b_ratio_ok"] and arms[str(k)]["c_m3_ok"])
    res["arms"] = arms
    res["power_note"] = ("paired design, the same trades in every arm; more than 50% reweighted widens the bound (INDETERMINATE likely)"
                         f"; reweighted share k=0.5 {arms['0.5']['reweighted_share']:.2f}, k=1.0 {arms['1.0']['reweighted_share']:.2f}")
    if n_atr < N_ATR_MIN:
        res["verdict"], res["verdict_reason"] = "INDETERMINATE", f"only {n_atr} of {n} trades have a computable ATR14 (< {N_ATR_MIN})"
    else:
        win = next((str(k) for k in KS if arms[str(k)]["passes"]), None)
        res["verdict"] = "PASS" if win else "FAIL"
        res["smallest_passing_k"] = float(win) if win else None
        res["verdict_reason"] = (f"smallest passing k = {win}" if win else
                                 "no k passes: " + "; ".join(f"k={k}: M1 {arms[str(k)]['m1_max']:.2f} (<=1.5 {arms[str(k)]['a_m1_ok']}), ratio lb80 "
                                                              f"{arms[str(k)]['ratio_boot']['lower_80']:.3f} ({arms[str(k)]['b_ratio_ok']}), M3 ok {arms[str(k)]['c_m3_ok']}" for k in KS))
    return res


# ----------------------------------------------------------------------------- self-test
def _row(leg, tf, t0, hold_h, entry, sl, net_r, atr):
    et = datetime.fromisoformat(t0)
    return {"leg": leg, "symbol": "X", "tf": tf, "strategy": "s", "atr_stop_mult": None, "entry_time": et, "exit_time": et + timedelta(hours=hold_h), "entry": entry,
            "sl": sl, "net_r": net_r, "dist": abs(entry - sl), "exit_imputed": False, "atr": atr}


def self_test() -> int:
    # weights: dist 1, ATR 4 -> k=0.5 floors the risk distance at 2 (w .5), k=1 at 4 (w .25); a wide stop (dist 10) is untouched; no ATR -> 1
    rows = [_row("a", "1h", "2026-01-01T00:00:00+00:00", 5, 100.0, 99.0, 2.0, 4.0), _row("a", "1h", "2026-01-02T00:00:00+00:00", 5, 100.0, 90.0, -1.0, 4.0),
            _row("a", "1h", "2026-01-03T00:00:00+00:00", 5, 100.0, 99.0, 1.0, None)]
    assert np.allclose(weights(rows, 0.5), [0.5, 1.0, 1.0]) and np.allclose(weights(rows, 1.0), [0.25, 1.0, 1.0]) and np.allclose(weights(rows, None), 1.0)
    # one trade, arm A: notional/equity = 0.015 x 100 / 1 = 1.5; B_1.0: 0.015 x 100 / 4 = 0.375 (hand-computed)
    one = [_row("a", "1h", "2026-01-01T00:00:00+00:00", 5, 100.0, 99.0, 2.0, 4.0)]
    assert abs(path(one, weights(one, None), None)["m1_max"] - 1.5) < 1e-12
    assert abs(path(one, weights(one, 1.0), 1.0)["m1_max"] - 0.375) < 1e-12
    # compounding: arm A return = 0.015 x 2.0 = 0.03 on E0 = 1; B_1.0 return = 0.015 x 0.25 x 2.0 = 0.0075
    assert abs(path(one, weights(one, None), None)["total_return"] - 0.03) < 1e-12 and abs(path(one, weights(one, 1.0), 1.0)["total_return"] - 0.0075) < 1e-12
    # concurrency: two overlapping trades add (both sized at E0 = 1): A = 1.5 + 1.5 = 3.0
    two = [_row("a", "1h", "2026-01-01T00:00:00+00:00", 10, 100.0, 99.0, 1.0, 4.0), _row("b", "1h", "2026-01-01T02:00:00+00:00", 10, 100.0, 99.0, 1.0, 4.0)]
    assert abs(path(two, weights(two, None), None)["m1_max"] - 3.0) < 1e-12
    # a trade that exits at the instant the next enters is credited first (no overlap, no double count)
    seq = [_row("a", "1h", "2026-01-01T00:00:00+00:00", 5, 100.0, 99.0, 1.0, 4.0), _row("b", "1h", "2026-01-01T05:00:00+00:00", 5, 100.0, 99.0, 1.0, 4.0)]
    assert path(seq, weights(seq, None), None)["m1_max"] < 1.51
    # bootstrap: arm A against itself has ratio exactly 1; uniform halving has ratio 0.5
    net = np.array([1.0, -0.5, 2.0, 0.5] * 20)
    assert abs(bootstrap_ratio(net, np.ones(len(net)), draws=500)["lower_80"] - 1.0) < 1e-12
    assert abs(bootstrap_ratio(net, np.full(len(net), 0.5), draws=500)["median"] - 0.5) < 1e-12
    # ATR lookback uses only bars CLOSED before entry: a bar opening at the entry hour is not used (planted: its true range is huge)
    import desk_scan_packet as dsp
    base = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    bars = [{"time": int((base + timedelta(hours=i)).timestamp()), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(30)]
    bars[20] = dict(bars[20], high=1000.0)
    t = np.array([b["time"] for b in bars], dtype=np.int64)
    atr = dsp.atr_series(bars)
    ent = base + timedelta(hours=20)                  # the bar opening at hour 20 is NOT closed at entry
    k = int(np.searchsorted(t + 3600, int(ent.timestamp()), side="right")) - 1
    assert k == 19 and abs(atr[k] - 2.0) < 1e-9, (k, atr[k])
    # full evaluate on a planted corpus: all-wide stops -> every weight 1 -> ratio 1, PASS only if M1 <= 1.5 (it is not for tight stops)
    big = [_row("mgc_trend_1h", "1h", f"2026-02-{d:02d}T00:00:00+00:00", 6, 100.0, 99.0, 1.0 if d % 3 else -1.0, 4.0) for d in range(1, 28)] * 3
    for i, r in enumerate(big):
        r["entry_time"] = r["entry_time"] + timedelta(seconds=i)       # distinct entries
        r["exit_time"] = r["entry_time"] + timedelta(hours=6)
    for leg in LEGS[1:]:
        big += [dict(big[0], leg=leg)]
    r = evaluate(sorted(big, key=lambda x: x["entry_time"]), draws=500)
    assert r["verdict"] in ("PASS", "FAIL") and r["n_atr_computable"] == len(big)
    thin = [dict(x, atr=None) for x in big]
    assert evaluate(thin, draws=100)["verdict"] == "INDETERMINATE"      # fewer than 60 computable ATRs
    # the registered corpus loads: 141 rows, 4 legs, timeframes read from bt.json (not from the file names)
    rows = load_corpus()
    assert len(rows) == 141 and {r["leg"] for r in rows} == set(LEGS), len(rows)
    tfs = {r["leg"]: r["tf"] for r in rows}
    assert tfs["mhg_pullback_1d"] == "2h" and tfs["mes_trend_long_1d"] == "1h", tfs
    print("self-test OK", {"n": len(rows), "tfs": tfs})
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("fetch", "run"))
    ap.add_argument("--root")
    ap.add_argument("--out")
    ap.add_argument("--fetch", action="store_true", help="run: fetch the candles first (a runner starts with an empty cache)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode:
        ap.error("mode or --self-test required")
    root = Path(a.root)
    out = Path(a.out or root / "out")
    rows = load_corpus()
    if a.mode == "fetch" or a.fetch:
        fetch(root, rows)
        if a.mode == "fetch":
            return 0
    attach_atr(rows, load_bars(root, rows))
    res = evaluate(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ib_gross_atr_floor.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[res["verdict"]], "read_state": "measured",
        "population": f"{res['n_trades']} committed Stage-0 trades over 4 IB futures legs (comms/strategy_evidence/runs/2026-09-24-e55), "
                      f"{res['n_atr_computable']} with a computable ATR14", "n": res["n_atr_computable"], "measurement": res, "note": res["verdict_reason"],
        "data_inputs": ["comms/strategy_evidence/runs/2026-09-24-e55", "yahoo futures candles"]}, indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("n_trades", "n_atr_computable", "verdict", "verdict_reason", "power_note")}, indent=1))
    print("A", json.dumps(res["A"]))
    for k, v in res["arms"].items():
        print("k", k, json.dumps({x: v[x] for x in ("m1_max", "m2_ratio", "m3", "reweighted_share", "ratio_boot", "a_m1_ok", "b_ratio_ok", "c_m3_ok", "passes")}, default=str))
    print("per_leg", json.dumps(res["per_leg"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
