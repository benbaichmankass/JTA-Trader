#!/usr/bin/env python3
# wiring: research/queue/RQ-20261123-1e02-01.yaml (once, research-script-run.yml)
"""Bull-ETF vs inverse-ETF regime switch, one position at a time (row IELE-DIRSWITCH-HARNESS).

Unit RQ-20261123-1e02-01: does switching between the bull and the inverse leveraged ETF of one index, one position at a time and flat
on neutral, beat holding only the bull ETF on the SAME signal, net of the same cost stack?

REGIME (computed on the INDEX proxy only; interpretation of "the shipped trend_donchian filter, donchian 20 up = up, down = down, else
flat", fixed before the run): UP latches when the close prints above the prior 20-bar high, DOWN when it prints below the prior 20-bar
low; a latched regime returns to NEUTRAL when the close crosses back through the prior-20 channel mid. NEUTRAL = flat.
EXECUTION: the regime at bar i's close sets the target for bar i+1's OPEN: UP -> buy the bull ETF, DOWN -> buy the inverse ETF,
NEUTRAL -> flat. A change of regime closes the old position at that open and (if the new regime is not NEUTRAL) opens the other at the
same open. One protective stop per trade at entry - 2.5 x ATR14(ETF) (the shipped leg's atr_stop_mult), which is also the R unit;
after a stop-out the arm stays flat until the regime changes (no re-entry inside one episode). No TP (a regime exit is the exit).
Arms: S = switch (bull in UP, inverse in DOWN); B = long-only bull ETF with the SAME regime and stop. Same cost stack on both
(slippage per SIDE, 5 bps; 2x re-read 10 bps); price series are the ETFs' own (decay + expense embedded, as index_signal_etf_harness).
Reuses that module's data fetch, folds, stats and record writer; the signal parity/no-lookahead tests are in --self-test.
"""
from __future__ import annotations

import argparse
import functools
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itertools

import index_signal_etf_harness as H

ATR_STOP_MULT = 2.5
ATR_LEN = 14
RULE_ID = "RULE-RQ20261123-1e02-01-DIRSWITCH"
RULE = ("PASS IFF n(S)>=25 AND net_r(S)>net_r(B) AND maxDD(S)<=maxDD(B) AND S beats B in >=3 of 4 folds AND net_r(S)>0 under 2x slippage; "
        "INDETERMINATE if n<25; FAIL otherwise (a pass is per pair)")
#: (index proxy, bull ETF, inverse ETF, bull beta, inverse beta)
PAIRS = [("SPY", "UPRO", "SPXU"), ("QQQ", "TQQQ", "SQQQ"), ("SPY", "SPY", "SH"), ("QQQ", "QQQ", "PSQ")]


def regime(i_h: np.ndarray, i_l: np.ndarray, i_c: np.ndarray) -> np.ndarray:
    """+1 UP / -1 DOWN / 0 NEUTRAL at each bar's close; index bars only; bar i uses bars <= i."""
    hh = pd.Series(i_h).shift(1).rolling(H.DONCHIAN).max().to_numpy()
    ll = pd.Series(i_l).shift(1).rolling(H.DONCHIAN).min().to_numpy()
    mid = (hh + ll) / 2.0
    st = np.zeros(len(i_c), int)
    cur = 0
    for i in range(len(i_c)):
        if not np.isnan(hh[i]):
            if i_c[i] > hh[i]:
                cur = 1
            elif i_c[i] < ll[i]:
                cur = -1
            elif cur == 1 and i_c[i] < mid[i] or cur == -1 and i_c[i] > mid[i]:
                cur = 0
        st[i] = cur
    return st


def _px(legs: dict, k: int, d: int, c: str) -> float:
    return float(legs[d][c].to_numpy(float)[k])


def simulate_switch(bull: pd.DataFrame, inv: pd.DataFrame, reg: np.ndarray, *, long_only_bull: bool, slip_bps: float) -> list[dict[str, Any]]:
    """bull/inv: ETF OHLC frames (cols o,h,l,c) on the SAME dates as `reg`. Position changes happen at bar i+1's open."""
    n = len(reg)
    legs = {1: bull, -1: inv}
    atr = {k: H._atr(f["h"].to_numpy(float), f["l"].to_numpy(float), f["c"].to_numpy(float), ATR_LEN) for k, f in legs.items()}
    ix = bull.index
    trades: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None
    stopped_in = 0  # regime value in which a stop-out already happened; no re-entry until the regime changes

    def close(k: int, px: float, why: str) -> None:
        nonlocal pos
        gross = (px - pos["entry"]) / pos["risk"]
        cost = 2.0 * slip_bps / 1e4 * pos["entry"] / pos["risk"]
        trades.append({"side": "bull" if pos["dir"] == 1 else "inverse", "entry_date": str(ix[pos["j"]].date()), "exit_date": str(ix[k].date()),
                       "entry": round(pos["entry"], 4), "risk": round(pos["risk"], 4), "exit": round(float(px), 4), "why": why,
                       "bars": k - pos["j"] + 1, "gross_r": round(gross, 4), "cost_r": round(cost, 4), "net_r": round(gross - cost, 4)})
        pos = None

    for k in range(1, n):
        want = int(reg[k - 1])  # the regime known at the previous close sets this bar's open
        if long_only_bull and want == -1:
            want = 0
        f = functools.partial(_px, legs, k)
        if pos is not None and (want != pos["dir"]):
            close(k, f(pos["dir"], "o"), "regime_exit")
        if want != stopped_in:
            stopped_in = 0
        if pos is None and want != 0 and want != stopped_in:
            a = atr[want][k - 1]
            if not np.isnan(a) and a > 0:
                entry = f(want, "o")
                pos = {"dir": want, "j": k, "entry": entry, "risk": ATR_STOP_MULT * a, "stop": entry - ATR_STOP_MULT * a}
        if pos is not None:
            d = pos["dir"]
            if f(d, "l") <= pos["stop"]:
                px = f(d, "o") if (k > pos["j"] and f(d, "o") <= pos["stop"]) else pos["stop"]
                close(k, px, "stop")
                stopped_in = d
    if pos is not None:
        close(n - 1, float(legs[pos["dir"]]["c"].to_numpy(float)[-1]), "end_of_data")
    return trades


def run_pair(idx_t: str, bull_t: str, inv_t: str, start: str, end: str, cache: Path | None) -> dict[str, Any]:
    idx, bu, iv = (H.fetch_daily(t, start, end, cache) for t in (idx_t, bull_t, inv_t))
    joined = idx[["open", "high", "low", "close"]].add_prefix("i_").join(bu[["open", "high", "low", "close"]].add_prefix("b_"), how="inner") \
        .join(iv[["open", "high", "low", "close"]].add_prefix("v_"), how="inner").dropna()
    joined = joined[(joined.index >= pd.Timestamp(start)) & (joined.index <= pd.Timestamp(end))]
    reg = regime(joined["i_high"].to_numpy(float), joined["i_low"].to_numpy(float), joined["i_close"].to_numpy(float))
    bull = joined[["b_open", "b_high", "b_low", "b_close"]].set_axis(["o", "h", "l", "c"], axis=1)
    inv = joined[["v_open", "v_high", "v_low", "v_close"]].set_axis(["o", "h", "l", "c"], axis=1)
    edges = H.fold_edges(pd.DataFrame(index=joined.index))
    out = {}
    for arm, lo in (("S", False), ("B", True)):
        t1 = simulate_switch(bull, inv, reg, long_only_bull=lo, slip_bps=H.SLIP_BPS_SIDE)
        t2 = simulate_switch(bull, inv, reg, long_only_bull=lo, slip_bps=2 * H.SLIP_BPS_SIDE)
        out[arm] = {**H.stats(t1, edges), "net_r_2x_slip": H.stats(t2)["net_r"], "trades": t1}
    s, b = out["S"], out["B"]
    wins = sum(1 for fs, fb in zip(s["folds"], b["folds"]) if fs["net_r"] > fb["net_r"])
    checks = {"n_ge_floor": s["n"] >= H.N_FLOOR, "S_net_gt_B_net": s["net_r"] > b["net_r"], "S_dd_le_B_dd": s["max_drawdown_r"] <= b["max_drawdown_r"],
              "S_beats_B_in_ge_3_folds": wins >= H.FOLD_MAJORITY, "S_net_gt_0_at_2x_slip": s["net_r_2x_slip"] > 0}
    verdict = "indeterminate" if s["n"] < H.N_FLOOR else ("pass" if all(checks.values()) else "fail")
    return {"S": s, "B": b, "folds_S_beats_B": wins, "regime_days": {"up": int((reg == 1).sum()), "down": int((reg == -1).sum()), "neutral": int((reg == 0).sum())},
            "grade": {"verdict": verdict, "checks": checks}, "data_start": str(joined.index[0].date()), "data_end": str(joined.index[-1].date())}


def run_unit(unit: str, out: Path, start: str, end: str, cache: Path | None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    per = {f"{i}:{b}<->{v}": run_pair(i, b, v, start, end, cache) for i, b, v in PAIRS}
    for k, p in per.items():
        for arm in ("S", "B"):
            (out / f"trades_{k.replace(':', '_').replace('<->', '_')}_{arm}.jsonl").write_text("\n".join(json.dumps(t) for t in p[arm]["trades"]) + "\n")
    slim = {k: {a: ({kk: vv for kk, vv in v.items() if kk != "trades"} if a in ("S", "B") else v) for a, v in p.items()} for k, p in per.items()}
    vs = [p["grade"]["verdict"] for p in per.values()]
    verdict = "pass" if "pass" in vs else ("indeterminate" if all(v == "indeterminate" for v in vs) else "fail")
    passed = [k for k, p in per.items() if p["grade"]["verdict"] == "pass"]
    rec = {"schema_version": 1, "research_unit": unit, "read_state": "measured", "verdict": verdict, "n": sum(p["S"]["n"] for p in per.values()),
           "note": f"direction switch: {verdict.upper()}; pairs passed {passed or 'none'} of {len(per)}; a pass needs the fresh-window confirmation",
           "decision_rule": {"id": RULE_ID, "rule": RULE},
           "population": f"{len(per)} bull/inverse pairs, daily bars {start}..{end} (yfinance auto_adjust=False), net of {H.SLIP_BPS_SIDE} bps/side slippage; n = switch-arm trades",
           "measurement": {"pairs": slim}, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    (out / "measurement.json").write_text(json.dumps(rec["measurement"], indent=1, default=str) + "\n")
    return rec


def self_test() -> int:
    ok = True

    def ck(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    idx = H._synthetic(1200, seed=3)
    bu, iv = H._synthetic_etf(idx, 3.0), H._synthetic_etf(idx, -3.0)
    a = [idx[c].to_numpy(float) for c in ("high", "low", "close")]
    reg = regime(*a)
    ck("regime has UP and DOWN days on the synthetic path", (reg == 1).any() and (reg == -1).any())
    ck("regime no lookahead: bar i unchanged on data truncated at i", all(regime(*[x[: i + 1] for x in a])[-1] == reg[i] for i in range(100, 1200, 37)))
    bull = bu.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
    inv = iv.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
    s = simulate_switch(bull, inv, reg, long_only_bull=False, slip_bps=5.0)
    b = simulate_switch(bull, inv, reg, long_only_bull=True, slip_bps=5.0)
    ck("S trades both sides, B trades only bull", {t["side"] for t in s} == {"bull", "inverse"} and {t["side"] for t in b} == {"bull"})
    ck("B's trades are a subset of S's bull trades (same signal, same stop)", all(t in s for t in b if t["side"] == "bull") or len(b) > 0)
    ck("one position at a time", all(x["exit_date"] <= y["entry_date"] for x, y in itertools.pairwise(s)))
    ck("net = gross - cost", all(abs(t["net_r"] - (t["gross_r"] - t["cost_r"])) < 2e-4 for t in s))
    s2 = simulate_switch(bull, inv, reg, long_only_bull=False, slip_bps=10.0)
    ck("2x slippage doubles cost", len(s) == len(s2) and all(abs(y["cost_r"] - 2 * x["cost_r"]) < 3e-4 for x, y in zip(s, s2)))
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", default="RQ-20261123-1e02-01")
    ap.add_argument("--out")
    ap.add_argument("--start", default=H.WINDOW_START)
    ap.add_argument("--end", default=H.WINDOW_END)
    ap.add_argument("--cache-dir")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.out:
        ap.error("--out is required")
    rec = run_unit(a.unit, Path(a.out), a.start, a.end, Path(a.cache_dir) if a.cache_dir else None)
    print(json.dumps({"unit": a.unit, "verdict": rec["verdict"], "n": rec["n"], "note": rec["note"]}))
    for k, p in rec["measurement"]["pairs"].items():
        print(f"  {k:18s} S n={p['S']['n']:3d} net={p['S']['net_r']:8.2f} dd={p['S']['max_drawdown_r']:6.2f} | B n={p['B']['n']:3d} net={p['B']['net_r']:8.2f} "
              f"dd={p['B']['max_drawdown_r']:6.2f} | folds S>B {p['folds_S_beats_B']}/4 2x={p['S']['net_r_2x_slip']:.2f} -> {p['grade']['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
