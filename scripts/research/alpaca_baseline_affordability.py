#!/usr/bin/env python3
# wiring: research/queue/RQ-20261106-d5a1-01.yaml (once, research-script-run.yml)
"""Alpaca ml_entry baseline -- what would a 1-share minimum actually reach, and can the live data path carry the pull?

WHY (row PROD-LEGS-DSR-DECISION; Manager Session 2026-11-05b, 2026-11-06 ~01:23Z, option (iii), verbatim: "author and fire the
price/ATR + pull-load measurement unit now")
------------------------------------------------------------------------------------------------------------------------------------
The operator asked for ml_entry on alpaca_live at the smallest size Alpaca allows, trading the RQ-20261104-a41f-01 pooled population
(173 liquid ETFs). Two facts were missing before anyone decides how to wire it:

  1. AFFORDABILITY -- how many of the 173 does the account-level 1-share minimum reach at alpaca_live's equity? The sizer is
     src/units/accounts/risk.py::RiskManager.position_size on a whole-unit venue (alpaca): a sub-1-share risk size rounds UP to
     1 share only when one share's stop risk <= _ROUND_UP_BUDGET_MULT (1.5) x the per-trade budget (risk_pct x equity); and one share
     must fit the cash (alpaca_live is a long-only CASH book). ml_entry's stop is 2 x ATR14 on 1h bars.
  2. PULL LOAD -- the live trader would fetch every rostered symbol's 1h bars each tick through
     src/exchange/alpaca_connector.py::AlpacaMarketData.get_ohlcv(symbol, "1h", limit=400) (ml_entry's fetch). Nothing measured
     whether that path can pull 173 symbols without 429s or a slow tick.

WHAT IT DOES (read-only; never the live tick path, never an order)
------------------------------------------------------------------
  * Population: the 173 ``pool_symbols`` of the committed a41f measurement (sha256 recorded). No symbol is chosen here.
  * PASS 1 (affordability): the PACED read-only research client (scripts/research/alpaca_readonly.py, 0.4 s between calls) pulls
    ~30 days of 1h bars per symbol; RTH bars only (the a41f rule, rth_hourly); last close and ATR14 (Wilder) on them.
    affordable = close <= cash AND 2 x ATR14 <= 1.5 x risk_pct x equity. The figures come from config/accounts.yaml (risk_pct) and
    --equity (alpaca_live's MEASURED balance, passed in with its as-of). The confidence scalar can only LOWER the budget, so
    the count is an UPPER BOUND at full confidence, and the record says so.
  * PASS 2 (pull load): the LIVE fetch class, unpaced, sequential over the 173 symbols, exactly as one tick would call it; per-symbol
    latency, total wall time, HTTP status counts (429s), bar counts. requests.get is wrapped only to COUNT responses.
    ⚠️ The research runner holds the shared PAPER key pair, the same pair alpaca_paper's live fetch uses, so this pass shares that
    key's data rate limit for its duration. That is the load a 173-symbol roster would add, measured, not simulated.

    python3 scripts/research/alpaca_baseline_affordability.py run --equity <alpaca_live equity, in memory only> --equity-as-of <ISO ts> --out OUT
    python3 scripts/research/alpaca_baseline_affordability.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

UNIT = "RQ-20261106-d5a1-01"
RULE_ID = "RULE-RQ20261106-d5a1-01-ALPACA-BASELINE-MEASURE"
POOL_FILE = REPO / "comms" / "research" / "RQ-20261104-a41f-01" / "42091158467" / "measurement.json"
ACCOUNT = "alpaca_live"
ROUND_UP_MULT = 1.5          # src/units/accounts/risk.py::_ROUND_UP_BUDGET_MULT (asserted in the self-test)
ATR_STOP_MULT = 2.0          # ml_entry: SL 2 x ATR14 (config/strategies.yaml::ml_entry.atr_stop_mult; asserted at run time)
ATR_N = 14
LIVE_LIMIT = 400             # ml_entry's live 1h fetch limit (alpaca_connector docstring: "ml_entry's limit=400 1h fetch")


def wilder_atr(high: List[float], low: List[float], close: List[float], n: int = ATR_N) -> Optional[float]:
    """ATR(n), Wilder smoothing, on the given bars; None when fewer than n+1 bars."""
    if len(close) < n + 1:
        return None
    trs = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])) for i in range(1, len(close))]
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def judge(close: Optional[float], atr: Optional[float], equity: float, risk_pct: float) -> Dict[str, Any]:
    """One symbol under the 1-share minimum. Returns the reason, never a silent bool."""
    if close is None or atr is None:
        return {"affordable": None, "reason": "no_bars"}
    budget = risk_pct * equity
    one_share_risk = ATR_STOP_MULT * atr
    if close > equity:
        return {"affordable": False, "reason": "cash", "one_share_risk_usd": round(one_share_risk, 4)}
    if one_share_risk > ROUND_UP_MULT * budget:
        return {"affordable": False, "reason": "stop_risk_over_1.5x_budget", "one_share_risk_usd": round(one_share_risk, 4)}
    return {"affordable": True, "reason": "ok", "one_share_risk_usd": round(one_share_risk, 4)}


def _pool() -> tuple[List[str], str]:
    raw = POOL_FILE.read_bytes()
    syms = list(json.loads(raw)["pool_symbols"])
    return syms, hashlib.sha256(raw).hexdigest()


def _risk_pct() -> float:
    from src.config.accounts_loader import load_accounts_dict
    acct = (load_accounts_dict() or {})[ACCOUNT]
    return float(acct["risk"]["risk_pct"])


def _atr_stop_mult() -> float:
    import yaml
    s = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    return float((s.get("strategies", s))["ml_entry"]["atr_stop_mult"])


def pass_affordability(syms: List[str], equity: float, risk_pct: float) -> Dict[str, Any]:
    import pandas as pd
    from alpaca_readonly import AlpacaReadOnly
    from ml_entry_alpaca_score import alpaca_bars_df, rth_hourly
    client = AlpacaReadOnly.from_env()
    # SIP bars newer than 15 min are not served on the data plan the runner key holds; end 20 min back (a41f read month-old ends).
    end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20)).floor("min")
    start = end - pd.Timedelta(days=30)
    per: Dict[str, Any] = {}
    for i, s in enumerate(syms, 1):
        got = client.bars([s], "1Hour", start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        rows = got.get(s) or []
        close = atr = None
        last_ts = None
        if rows:
            df = rth_hourly(alpaca_bars_df(rows))
            if len(df):
                close = float(df.close.iloc[-1])
                last_ts = str(df.ts.iloc[-1])
                atr = wilder_atr(df.high.tolist(), df.low.tolist(), df.close.tolist())
        per[s] = {"close": close, "atr14_1h": None if atr is None else round(atr, 6), "last_bar": last_ts, **judge(close, atr, equity, risk_pct)}
        if i % 25 == 0:
            print(f"[afford] {i}/{len(syms)} calls={client.calls} 429s={client.n_429}", flush=True)
    vals = [v for v in per.values()]
    return {"per_symbol": per, "client_calls": client.calls, "client_429s": client.n_429, "key_kind": client.key_kind,
            "n_affordable": sum(1 for v in vals if v["affordable"] is True),
            "n_refused_cash": sum(1 for v in vals if v["reason"] == "cash"),
            "n_refused_stop_risk": sum(1 for v in vals if v["reason"] == "stop_risk_over_1.5x_budget"),
            "n_no_bars": sum(1 for v in vals if v["reason"] == "no_bars"),
            "window": [str(start), str(end)]}


def pass_pull_load(syms: List[str]) -> Dict[str, Any]:
    import requests
    from src.exchange.alpaca_connector import AlpacaMarketData
    status: Dict[str, int] = {}
    orig = requests.get

    def counted(*a, **k):
        r = orig(*a, **k)
        status[str(r.status_code)] = status.get(str(r.status_code), 0) + 1
        return r

    requests.get = counted
    md = AlpacaMarketData()
    lat: List[float] = []
    bars: Dict[str, int] = {}
    t0 = time.monotonic()
    try:
        for s in syms:
            a = time.monotonic()
            df = md.get_ohlcv(s, "1h", limit=LIVE_LIMIT)
            lat.append(time.monotonic() - a)
            bars[s] = 0 if df is None else int(len(df))
    finally:
        requests.get = orig
    wall = time.monotonic() - t0
    srt = sorted(lat)

    def q(p: float) -> float:
        return round(srt[min(len(srt) - 1, int(p * len(srt)))], 3) if srt else None

    return {"fetch_class": "src.exchange.alpaca_connector.AlpacaMarketData.get_ohlcv(symbol, '1h', limit=400)", "feed": md.feed,
            "order": "sequential, unpaced (one tick)", "n_symbols": len(syms), "wall_seconds": round(wall, 2),
            "latency_s": {"p50": q(0.5), "p95": q(0.95), "max": round(max(lat), 3) if lat else None},
            "http_status_counts": status, "n_429": status.get("429", 0), "http_calls": sum(status.values()),
            "n_symbols_with_bars": sum(1 for v in bars.values() if v > 0), "n_symbols_empty": sum(1 for v in bars.values() if v == 0)}


def run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms, sha = _pool()
    risk_pct = _risk_pct()
    asm = _atr_stop_mult()
    if asm != ATR_STOP_MULT:
        raise SystemExit(f"ml_entry.atr_stop_mult is {asm}, this harness assumes {ATR_STOP_MULT}")
    t0 = time.time()
    afford = pass_affordability(syms, a.equity, risk_pct)
    load = pass_pull_load(syms)
    complete = afford["n_no_bars"] < len(syms) and load["http_calls"] > 0
    meas = {"population": {"source": str(POOL_FILE.relative_to(REPO)), "sha256": sha, "n": len(syms)},
            "account": ACCOUNT, "equity_as_of": a.equity_as_of, "equity_source": a.equity_source,
            # the balance itself and budget_usd (= risk_pct x equity) are NEVER written: the record is committed to a public repo
            "risk_pct": risk_pct,
            "one_share_rule": f"close <= equity AND {ATR_STOP_MULT} x ATR14(1h RTH) <= {ROUND_UP_MULT} x budget",
            "upper_bound_note": "at full confidence; RiskManager._confidence_scalar can only lower the budget, so fewer may size",
            "affordability": afford, "pull_load": load, "elapsed_s": round(time.time() - t0)}
    # `n` is required at the top level by script_run --derive-record (run 42145318852 measured both passes but was recorded
    # producer_failed: "verdict.json malformed: n must be present"). n = the population measured.
    v = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured" if complete else "producer_failed",
         "verdict": "pass" if complete else "not_applicable", "n": len(syms) if complete else None,
         "note": (f"affordable {afford['n_affordable']}/{len(syms)} at the {ACCOUNT} balance (as of {a.equity_as_of}); "
                  f"pull {load['n_symbols']} syms in {load['wall_seconds']}s, 429s={load['n_429']}, p95 {load['latency_s']['p95']}s"),
         "decision_rule": {"id": RULE_ID, "rule": "PASS IF both passes complete (a measurement; no edge claim)."},
         "population": f"RQ-20261104-a41f-01 pooled ETF population, {len(syms)} symbols (pool file sha256 {sha[:12]}); "
                       f"alpaca_live balance as of {a.equity_as_of}",
         "measurement": meas, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=str) + "\n")
    (out / "measurement.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    print(json.dumps({"note": v["note"], "verdict": v["verdict"]}), flush=True)
    return 0 if complete else 1


def self_test() -> int:
    ok = True

    def ck(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    import re
    src = (REPO / "src" / "units" / "accounts" / "risk.py").read_text()
    m = re.search(r"^_ROUND_UP_BUDGET_MULT\s*=\s*([0-9.]+)", src, re.M)
    ck("ROUND_UP_MULT matches risk.py::_ROUND_UP_BUDGET_MULT", m and float(m.group(1)) == ROUND_UP_MULT)
    ck("ATR on a flat series is 0", wilder_atr([1.0] * 20, [1.0] * 20, [1.0] * 20) == 0.0)
    ck("ATR needs n+1 bars", wilder_atr([1.0] * 14, [1.0] * 14, [1.0] * 14) is None)
    ck("ATR of a constant 1.0 range is 1.0", abs(wilder_atr([2.0] * 30, [1.0] * 30, [1.5] * 30) - 1.0) < 1e-12)
    eq, rp = 200.0, 0.02          # synthetic fixture (never a real balance): budget 4.0; 1.5x = 6.0
    ck("cash-bound refuses", judge(250.0, 0.1, eq, rp)["reason"] == "cash")
    ck("stop risk over 1.5x budget refuses", judge(50.0, 3.5, eq, rp)["reason"] == "stop_risk_over_1.5x_budget")
    ck("cheap, tight stop is affordable", judge(50.0, 1.0, eq, rp)["affordable"] is True)
    ck("boundary 2xATR == 1.5x budget is affordable", judge(50.0, 6.0 / 2, eq, rp)["affordable"] is True)
    ck("no bars is unknown, never False", judge(None, None, eq, rp)["affordable"] is None)
    syms, sha = _pool()
    ck("population is the a41f 173", len(syms) == 173 and len(sha) == 64)
    ck("ml_entry.atr_stop_mult is 2.0", _atr_stop_mult() == ATR_STOP_MULT)
    print(f"alpaca-baseline-affordability self-test: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--equity", type=float, required=True, help="alpaca_live MEASURED equity, USD")
    r.add_argument("--equity-as-of", required=True)
    r.add_argument("--equity-source", default="GET /api/bot/accounts/balances (balance_snapshots, db)")
    r.add_argument("--unit", default=UNIT)
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd == "run":
        return run(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
