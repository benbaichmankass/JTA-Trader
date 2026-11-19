#!/usr/bin/env python3
# wiring: research/queue units of programme P8 node P8-Q7-rotation (research/programmes/08-alpaca-live-book.yaml)
"""ETF ROTATION / DUAL MOMENTUM, Stage 0 on the alpaca_live cash book (programme P8, node P8-Q7-rotation).

A NEW strategy family sized for a small long-only whole-share cash account: hold the ONE ETF of a fixed, pre-declared list
with the best trailing 126-session total return, only if it beats the cash ETF (absolute momentum), else hold cash; decide
on the last session of each month, trade at the first session's open; no lookback grid (parameters are module constants).

Mechanics registered here (each a constant, not a flag):
  * signal: adjusted-close total return over the 126 sessions ending at the month's LAST session close (no lookahead);
  * entry / exit at the next session's OPEN; a holding continues while the month's pick is unchanged (no churn);
  * a catastrophic bracket stop at entry x (1 - STOP_FRAC) (BRACKETS-ALWAYS: every live order carries a stop), gap-aware:
    a session that opens below the stop exits at the open, else at the stop when the low touches it;
  * R = STOP_FRAC x entry (the stop distance); net_r = gross R minus the round-trip cost stack in R
    (src.runtime.execution_costs.resolve_cost_policy slippage + resolve_fee_bps_roundtrip per symbol);
  * the BASELINE is buy-and-hold of the equity ETF (the first in the list) with the same stop and re-entry rule
    (re-enter at the next month's first open after a stop), on the same book.

Both trade lists go through scripts/research/alpaca_live_book.py::replay (the live sizer constants, one slot, T+1, whole shares).
Gold: IAUM is the account-affordable gold ETF but has no history before 2021, so GLD stands in for signal AND price; GLD's
higher share price can only add `unaffordable_whole_share` refusals, so the substitution is conservative for the book.

    python3 scripts/research/etf_rotation_stage0.py --self-test
    python3 scripts/research/etf_rotation_stage0.py run --out DIR --unit ID --rule-id R --registered-at D
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

UNIVERSE = ["SPYM", "SCHA", "IEF", "TLT", "GLD"]    # equity large / small, rates mid / long, gold (IAUM proxy, see docstring)
CASH = "BIL"
LOOKBACK = 126
STOP_FRAC = 0.15
DISCOVERY = ("2010-01-01", "2023-12-31")
CONFIRM = ("2024-01-01", "2026-10-31")
N_FLOOR = 39


def fetch_prices(symbols: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    """Daily OHLC + adjusted close from Yahoo (yfinance). Columns: open, high, low, close, adj (index: session date)."""
    import yfinance as yf
    out = {}
    for s in symbols:
        df = yf.download(s, start=start, end=end, auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj"})
        out[s] = df[["open", "high", "low", "close", "adj"]].dropna()
        out[s].index = pd.to_datetime(out[s].index).tz_localize(None)
    return out


def _costs(symbols: List[str]) -> Dict[str, float]:
    """Round-trip cost in bps per symbol from the shared cost policy (slippage + fee)."""
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    return {s: float(resolve_cost_policy(s)[0]) + float(resolve_fee_bps_roundtrip(s)) for s in symbols}


def month_ends(idx: pd.DatetimeIndex) -> List[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    return list(s.groupby([idx.year, idx.month]).max())


def picks(px: Dict[str, pd.DataFrame], universe: List[str], cash: str) -> Dict[pd.Timestamp, Optional[str]]:
    """Month-end date -> the symbol to hold next month (None = cash). Uses only adjusted closes up to that date."""
    cal = px[cash].index
    out = {}
    for d in month_ends(cal):
        rets = {}
        for s in universe + [cash]:
            a = px[s]["adj"].loc[:d]
            if len(a) > LOOKBACK:
                rets[s] = float(a.iloc[-1] / a.iloc[-1 - LOOKBACK] - 1.0)
        if cash not in rets or not any(s in rets for s in universe):
            continue
        best = max((s for s in universe if s in rets), key=lambda s: rets[s])
        out[d] = best if rets[best] > rets[cash] else None
    return out


def simulate(px: Dict[str, pd.DataFrame], plan: Dict[pd.Timestamp, Optional[str]], cost_bps: Dict[str, float],
             start: str, end: str) -> List[Dict[str, Any]]:
    """Walk the month-end plan into trades (entry/exit at next open, catastrophic stop, no churn while the pick holds)."""
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    trades: List[Dict[str, Any]] = []
    pos = None   # dict(symbol, entry_date, entry, sl)
    dates = sorted(d for d in plan if lo <= d <= hi)

    def next_session(sym: str, d: pd.Timestamp) -> Optional[pd.Timestamp]:
        ix = px[sym].index
        k = ix.searchsorted(d, side="right")
        return ix[k] if k < len(ix) else None

    def close_pos(exit_date, exit_px, reason):
        nonlocal pos
        risk = pos["entry"] - pos["sl"]
        gross_r = (exit_px - pos["entry"]) / risk
        cost_r = (cost_bps[pos["symbol"]] / 1e4) * pos["entry"] / risk
        trades.append({"symbol": pos["symbol"], "entry_time": str(pos["entry_date"]), "exit_time": str(exit_date),
                       "entry": round(pos["entry"], 6), "sl": round(pos["sl"], 6), "exit": round(float(exit_px), 6),
                       "net_r": round(gross_r - cost_r, 6), "gross_r": round(gross_r, 6), "exit_reason": reason, "direction": "long"})
        pos = None

    for k, d in enumerate(dates):
        want = plan[d]
        seg_end = dates[k + 1] if k + 1 < len(dates) else hi
        if pos and pos["symbol"] != want:
            nd = next_session(pos["symbol"], d)
            if nd is not None:
                close_pos(nd, float(px[pos["symbol"]].loc[nd, "open"]), "rebalance")
        if want and pos is None:
            nd = next_session(want, d)
            if nd is None or nd > hi:
                continue
            e = float(px[want].loc[nd, "open"])
            pos = {"symbol": want, "entry_date": nd, "entry": e, "sl": e * (1 - STOP_FRAC)}
        if pos:   # stop check through the month, from the session after entry (the entry session's low counts too)
            seg = px[pos["symbol"]].loc[pos["entry_date"]:seg_end]
            for dt, row in seg.iterrows():
                if dt > seg_end:
                    break
                if row["open"] <= pos["sl"] and dt != pos["entry_date"]:
                    close_pos(dt, float(row["open"]), "stop_gap")
                    break
                if row["low"] <= pos["sl"]:
                    close_pos(dt, pos["sl"], "stop")
                    break
    if pos:   # mark to the last close in the window (an open trade at the window end)
        last = px[pos["symbol"]].loc[:hi].index[-1]
        close_pos(last, float(px[pos["symbol"]].loc[last, "close"]), "window_end")
    return trades


def hold_plan(px: Dict[str, pd.DataFrame], sym: str, cash: str) -> Dict[pd.Timestamp, Optional[str]]:
    return {d: sym for d in month_ends(px[cash].index)}


def stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"n": 0, "net_r": 0.0}
    r = np.array([t["net_r"] for t in trades])
    yrs = pd.Series(r, index=[pd.Timestamp(t["exit_time"]).year for t in trades]).groupby(level=0).sum()
    tot = float(r.sum())
    return {"n": int(len(r)), "net_r": tot, "mean_r": float(r.mean()),
            "by_year": {int(k): round(float(v), 4) for k, v in yrs.items()},
            "years_positive_share": float((yrs > 0).mean()), "max_year_share": float(yrs.max() / tot) if tot > 0 else None,
            "exit_reasons": pd.Series([t["exit_reason"] for t in trades]).value_counts().to_dict()}


def grade_discovery(rot: Dict[str, Any], rot_book: Dict[str, Any], base_book: Dict[str, Any]) -> tuple:
    """Registered discovery rule. INDETERMINATE under N_FLOOR trades or n_taken < 30 on the book."""
    if rot["n"] < N_FLOOR or int(rot_book.get("n_taken") or 0) < 30:
        return "indeterminate", f"n {rot['n']} trades / n_taken {rot_book.get('n_taken')} under the floors ({N_FLOOR} / 30)"
    cl = {"net_positive": rot["net_r"] > 0,
          "years_positive_ge_75pct": rot["years_positive_share"] >= 0.75,
          "no_year_over_half": rot["max_year_share"] is not None and rot["max_year_share"] <= 0.5,
          "book_dd_le_0.6x_hold": float(rot_book.get("max_drawdown_usd") or 0) <= 0.6 * float(base_book.get("max_drawdown_usd") or 0),
          "book_return_ge_0.75x_hold": float(rot_book.get("return_pct_per_month") or 0) >= 0.75 * float(base_book.get("return_pct_per_month") or 0)}
    ok = all(cl.values())
    return ("pass" if ok else "fail"), json.dumps(cl)


def run(px: Dict[str, pd.DataFrame], cost_bps: Dict[str, float], replay_kw: Dict[str, Any], cash0: float) -> Dict[str, Any]:
    import alpaca_live_book as B
    plan = picks(px, UNIVERSE, CASH)
    base_plan = hold_plan(px, UNIVERSE[0], CASH)
    out = {}
    for name, (a, b) in (("discovery", DISCOVERY), ("confirm", CONFIRM)):
        rot = simulate(px, plan, cost_bps, a, b)
        base = simulate(px, base_plan, cost_bps, a, b)
        out[name] = {"rotation": stats(rot), "hold": stats(base),
                     "rotation_book": B.replay(rot, cash0, **replay_kw), "hold_book": B.replay(base, cash0, **replay_kw),
                     "trades": rot}
    v, why = grade_discovery(out["discovery"]["rotation"], out["discovery"]["rotation_book"], out["discovery"]["hold_book"])
    conf = out["confirm"]
    if v == "pass":   # the ONE confirm read, registered: net R > 0 AND book drawdown not worse than the hold book's
        c_ok = conf["rotation"]["net_r"] > 0 and float(conf["rotation_book"].get("max_drawdown_usd") or 0) <= \
            float(conf["hold_book"].get("max_drawdown_usd") or 0)
        v, why = ("pass", f"discovery {why}; confirm net R {conf['rotation']['net_r']:+.2f}, DD within the hold book's") if c_ok else \
            ("fail", f"discovery passed {why}, CONFIRM failed (net R {conf['rotation']['net_r']:+.2f} or DD worse than hold)")
    return {"verdict": v, "note": why, "n": out["discovery"]["rotation"]["n"], "windows": {k: {kk: vv for kk, vv in w.items() if kk != "trades"}
            for k, w in out.items()}, "trades": {k: w["trades"] for k, w in out.items()}}


# ------------------------------------------------------------------------------------------------ self-test
def _synth(n=1500, seed=3) -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    drift = {"SPYM": 0.0006, "SCHA": 0.0003, "IEF": 0.0001, "TLT": 0.0, "GLD": 0.0002, "BIL": 0.00008}
    px = {}
    for s, mu in drift.items():
        r = rng.normal(mu, 0.01 if s != "BIL" else 0.0002, n)
        c = 50 * np.exp(np.cumsum(r))
        o = np.concatenate([[50.0], c[:-1]])
        px[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c, "adj": c}, index=idx)
    return px


def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    px = _synth()
    plan = picks(px, UNIVERSE, CASH)
    d0 = sorted(plan)[10]
    # no lookahead: the pick at d0 is unchanged when every row after d0 is removed
    trunc = {s: df.loc[:d0] for s, df in px.items()}
    check("pick at a month end uses no later data", picks(trunc, UNIVERSE, CASH).get(d0, "x") == plan[d0])
    # absolute momentum: if every risky asset falls, the pick is cash
    bear = {s: (df.assign(adj=df["adj"].iloc[::-1].to_numpy()) if s != CASH else df) for s, df in px.items()}
    bp = picks(bear, UNIVERSE, CASH)
    check("absolute momentum can choose cash (None)", any(v is None for v in bp.values()))
    cb = {s: 10.0 for s in UNIVERSE + [CASH]}
    tr = simulate(px, plan, cb, "2015-08-01", "2020-12-31")
    check("trades are produced and carry entry/sl/net_r", len(tr) > 3 and all(t["sl"] < t["entry"] for t in tr))
    check("no two trades overlap (one holding at a time)",
          all(pd.Timestamp(a["exit_time"]) <= pd.Timestamp(b["entry_time"]) for a, b in zip(tr, tr[1:])))
    # a planted crash triggers the stop at the stop price
    px2 = {s: df.copy() for s, df in px.items()}
    hp = hold_plan(px2, "SPYM", CASH)
    t0 = simulate(px2, hp, cb, "2016-01-01", "2016-12-31")[0]
    k = px2["SPYM"].index.get_loc(pd.Timestamp(t0["entry_time"])) + 3
    px2["SPYM"].iloc[k, px2["SPYM"].columns.get_loc("low")] = t0["entry"] * 0.5
    t1 = simulate(px2, hp, cb, "2016-01-01", "2016-12-31")[0]
    check("the catastrophic stop exits at the stop price on an intraday touch",
          t1["exit_reason"] == "stop" and abs(t1["exit"] - t1["entry"] * (1 - STOP_FRAC)) < 1e-6)
    check("net R on a stop is about -1 R minus cost", -1.1 < t1["net_r"] < -1.0)
    # the grader
    ok_rot = {"n": 60, "net_r": 20.0, "years_positive_share": 0.8, "max_year_share": 0.3}
    bk = lambda dd, rr: {"n_taken": 50, "max_drawdown_usd": dd, "return_pct_per_month": rr}  # noqa: E731
    check("grader: passes when every clause holds", grade_discovery(ok_rot, bk(5, 0.8), bk(10, 1.0))[0] == "pass")
    check("grader: drawdown above 0.6x hold fails", grade_discovery(ok_rot, bk(7, 0.8), bk(10, 1.0))[0] == "fail")
    check("grader: return under 0.75x hold fails", grade_discovery(ok_rot, bk(5, 0.7), bk(10, 1.0))[0] == "fail")
    check("grader: thin n is indeterminate", grade_discovery({**ok_rot, "n": 20}, bk(5, 0.8), bk(10, 1.0))[0] == "indeterminate")
    import alpaca_live_book as B
    r = B.replay(tr, 1000.0)
    check("rotation trades replay through the alpaca_live book", r["n_candidates"] == len(tr) and r["n_taken"] >= 1)
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("run")
    for k in ("--out", "--unit", "--rule-id", "--registered-at"):
        p.add_argument(k, required=True)
    p.add_argument("--where", default="local")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run":
        ap.error("run or --self-test")
    import alpaca_live_book as B
    t0 = time.time()
    syms = UNIVERSE + [CASH]
    px = fetch_prices(syms, "2009-01-01", "2026-11-01")
    sz = B._live_sizer_constants()
    r = run(px, _costs(syms), dict(risk_pct=sz["risk_pct"], wall=sz["wall"], roundup=sz["roundup"]), B.CASH0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rotation_trades.json").write_text(json.dumps(r.pop("trades"), indent=1, default=str))
    row = {"schema_version": 1, "schema": "etf_rotation_stage0/1", "research_unit": a.unit, "read_state": "measured", "verdict": r["verdict"],
           "n": r["n"], "note": r["note"], "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": f"monthly dual-momentum rotation over {UNIVERSE} vs {CASH} (Yahoo daily), discovery {DISCOVERY}, confirm {CONFIRM}, "
                         f"replayed through the alpaca_live cash book (cash0 source {B.CASH0_SOURCE}); baseline buy-and-hold {UNIVERSE[0]}",
           "measurement": {**r, "sizer": sz, "constants": {"lookback": LOOKBACK, "stop_frac": STOP_FRAC, "universe": UNIVERSE, "cash": CASH},
                           "runtime_s": round(time.time() - t0, 1)},
           "produced_by": {"tool": "python3 scripts/research/etf_rotation_stage0.py run", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"ROTATION {row['verdict']}: {row['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
