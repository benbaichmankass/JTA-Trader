#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-a5b3-03 (MARKOUT-HARNESS) -- `export` is run by a session with read access to the diag
# journal and commits an aggregated, non-secret per-fill table; `run` is the unit's runner command over that table.
"""MARKOUT-HARNESS: per-fill markouts vs the journal's recorded cost (row MARKOUT-HARNESS, unit RQ-20261118-a5b3-03).

Two steps, so the runner needs no VM credential:

  export  pages GET /api/diag/journal?table=trades (read-only; limit/offset) and writes ONE ROW PER FILL (entry and exit of
          every closed, non-backtest trade since --since): account (the config account name), account_class, leg
          (strategy_name), symbol, kind (entry|exit), side (+1 buy / -1 sell), fill time and price, exit_reason (the
          order-type proxy: tp = limit, sl/stale_stop = stop, else market), cost_source and the recorded cost in bps
          (fee_maker_usd + fee_taker_usd over the trade's two-fill notional, split evenly per fill). Position size, P&L,
          dollar fees, broker order ids and the journal row's free text are NOT written: only ratios and market prices.
  run     reads that table, fetches public candles per symbol (scripts/ops/fetch_backtest_candles.py; 1m where the source
          serves it, else 5m, recorded per fill as mid_interval), and computes per fill
              markout_h = side x (P(t_fill + h) - fill) / fill x 1e4 - fee_bps_per_fill      (h in 1 h, 4 h; bps)
              gap_h     = (-markout_h) - recorded_cost_bps                                   (cost unseen by the journal)
          where P(t + h) is the CLOSE of the first candle that opens at or after t + h (within 24 h, else the fill's mid
          is missing) and fee_bps_per_fill is execution_costs.resolve_fee_bps_roundtrip(symbol) / 2. Grades the
          a5b3-03 rule on gap at +1 h: fill-grouped bootstrap (grouped by trade) 95% CI, pooled; per account and
          order-type proxy reported.

    python3 scripts/research/markout_fills.py --self-test
    python3 scripts/research/markout_fills.py export --since 2026-09-01 --out comms/research/markout_fills/<date>.jsonl
    python3 scripts/research/markout_fills.py run --fills <jsonl> --unit ID --rule-id R --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

# The canonical HTTPS base first, as scripts/ops/diag_fetch.sh does: a stale or plain-http DIAG_BASE_URL must not strand it.
_ENV_BASE = os.environ.get("DIAG_BASE_URL") or ""
BASE = _ENV_BASE if _ENV_BASE.startswith("https://") else "https://ict-bot.duckdns.org"
HORIZONS_H = (1, 4)
MID_MAX_LAG = timedelta(hours=24)
N_MIN = 200
MISSING_MAX = 0.10
NOT_UNDERSTATED_BPS = 2.0
BOOT = 4000
SEED = 20261119
_KEEP = ("account_id", "account_class", "strategy_name", "symbol", "direction", "entry_price", "exit_price",
         "created_at", "timestamp", "closed_at", "exit_reason", "cost_source")


def _ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:   # a malformed journal time stamp: the row is dropped (counted as unparseable by export)
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def order_type_proxy(kind: str, exit_reason: Optional[str]) -> str:
    if kind == "entry":
        return "entry"
    r = (exit_reason or "").lower()
    if r in ("tp", "take_profit", "tp_cross"):
        return "limit_tp"
    if r in ("sl", "stop", "stale_stop", "sl_cross", "trail_stop"):
        return "stop"
    return "market_other"


def fills_from_rows(rows: List[Dict[str, Any]], since: str) -> List[Dict[str, Any]]:
    """Journal trade rows -> per-fill rows (only ratios and market prices leave this function)."""
    out = []
    lo = _ts(since + "T00:00:00+00:00")
    for r in rows:
        if r.get("status") != "closed" or r.get("is_backtest"):
            continue
        t_in, t_out = _ts(r.get("timestamp") or r.get("created_at")), _ts(r.get("closed_at"))
        ep, xp, qty = r.get("entry_price"), r.get("exit_price"), r.get("position_size")
        if not (t_in and t_out and ep and xp and qty) or t_in < lo:
            continue
        long = str(r.get("direction") or "").lower() in ("long", "buy")
        notional2 = abs(float(qty)) * (float(ep) + float(xp))
        fees = float(r.get("fee_maker_usd") or 0.0) + float(r.get("fee_taker_usd") or 0.0)
        rec_bps = (fees / notional2 * 1e4) if notional2 > 0 and r.get("cost_source") else None   # per fill (two fills share)
        base = {"trade": str(r.get("id")), "account": r.get("account_id"), "account_class": r.get("account_class"),
                "leg": r.get("strategy_name"), "symbol": r.get("symbol"), "cost_source": r.get("cost_source"),
                "recorded_cost_bps": None if rec_bps is None else round(rec_bps, 4), "exit_reason": r.get("exit_reason")}
        out.append({**base, "kind": "entry", "side": 1 if long else -1, "t": t_in.isoformat(), "price": float(ep),
                    "order_type": "entry"})
        out.append({**base, "kind": "exit", "side": -1 if long else 1, "t": t_out.isoformat(), "price": float(xp),
                    "order_type": order_type_proxy("exit", r.get("exit_reason"))})
    return out


def _get(url: str) -> Any:
    req = urllib.request.Request(url)
    tok = os.environ.get("DIAG_READ_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - fixed host
        return json.load(r)


def export(since: str, out: Path, page: int = 1000) -> Dict[str, Any]:
    rows, off = [], 0
    while True:
        batch = _get(f"{BASE}/api/diag/journal?table=trades&limit={page}&offset={off}")
        batch = batch if isinstance(batch, list) else batch.get("rows") or []
        rows += [{k: r.get(k) for k in _KEEP + ("id", "status", "is_backtest", "position_size", "fee_maker_usd",
                                                  "fee_taker_usd")} for r in batch]
        if len(batch) < page or min((r.get("created_at") or "9") for r in batch) < since:
            break
        off += page
    fills = fills_from_rows(rows, since)
    bad = sum(1 for r in rows if r.get("status") == "closed" and not r.get("is_backtest")
              and (_ts(r.get("closed_at")) is None or _ts(r.get("timestamp") or r.get("created_at")) is None))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in fills))
    return {"journal_rows_read": len(rows), "closed_rows_unparseable_time": bad, "fills": len(fills), "out": str(out)}


# ------------------------------------------------------------------------------------------------ run
def price_after(bars: List[tuple], t: datetime) -> Optional[float]:
    """Close of the first bar opening at or after t (bars: sorted [(open_time, close)]), within MID_MAX_LAG."""
    lo, hi = 0, len(bars)
    while lo < hi:
        m = (lo + hi) // 2
        if bars[m][0] < t:
            lo = m + 1
        else:
            hi = m
    if lo < len(bars) and bars[lo][0] - t <= MID_MAX_LAG:
        return bars[lo][1]
    return None


def markouts(fills: List[Dict[str, Any]], bars_by_sym: Dict[str, tuple], fee_bps: Dict[str, float]) -> List[Dict[str, Any]]:
    out = []
    for f in fills:
        interval, bars = bars_by_sym.get(f["symbol"], (None, []))
        t = _ts(f["t"])
        row = {**f, "mid_interval": interval}
        for h in HORIZONS_H:
            p = price_after(bars, t + timedelta(hours=h)) if bars else None
            if p is None or f.get("recorded_cost_bps") is None:
                row[f"markout_{h}h_bps"] = row[f"gap_{h}h_bps"] = None
                continue
            mk = f["side"] * (p - f["price"]) / f["price"] * 1e4 - fee_bps.get(f["symbol"], 0.0) / 2
            row[f"markout_{h}h_bps"] = round(mk, 4)
            row[f"gap_{h}h_bps"] = round(-mk - f["recorded_cost_bps"], 4)
        out.append(row)
    return out


def grouped_boot_ci(rows: List[Dict[str, Any]], key: str, draws: int = BOOT, seed: int = SEED) -> Dict[str, Any]:
    """Mean of `key` and a 95% CI from a bootstrap that resamples whole TRADES (their two fills move together)."""
    by: Dict[str, List[float]] = {}
    for r in rows:
        if r.get(key) is not None:
            by.setdefault(r["trade"], []).append(r[key])
    groups = list(by.values())
    n = sum(len(g) for g in groups)
    if not groups:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    mean = sum(sum(g) for g in groups) / n
    rng = random.Random(seed)
    ms = []
    for _ in range(draws):
        s = c = 0
        for _ in range(len(groups)):
            g = groups[rng.randrange(len(groups))]
            s += sum(g)
            c += len(g)
        ms.append(s / c)
    ms.sort()
    return {"n": n, "trades": len(groups), "mean": round(mean, 4), "lo": round(ms[int(0.025 * draws)], 4),
            "hi": round(ms[int(0.975 * draws) - 1], 4)}


def grade(rows: List[Dict[str, Any]]) -> tuple:
    """RQ-20261118-a5b3-03's registered rule, on gap at +1 h."""
    n_all = len(rows)
    missing = sum(1 for r in rows if r.get("gap_1h_bps") is None)
    ci = grouped_boot_ci(rows, "gap_1h_bps")
    if ci["n"] < N_MIN:
        return "indeterminate", f"n {ci['n']} measured fills < {N_MIN}", ci, missing
    if n_all and missing / n_all > MISSING_MAX:
        return "indeterminate", f"mids or recorded cost missing for {missing}/{n_all} fills (> {MISSING_MAX:.0%}): read_state partial", ci, missing
    if ci["lo"] > 0:
        return "pass", f"UNDERSTATED: pooled +1 h (markout cost - recorded cost) {ci['mean']:+.2f} bps, CI [{ci['lo']:+.2f}, {ci['hi']:+.2f}]", ci, missing
    if ci["hi"] < NOT_UNDERSTATED_BPS:
        return "fail", f"NOT UNDERSTATED: CI upper {ci['hi']:+.2f} bps < {NOT_UNDERSTATED_BPS}", ci, missing
    return "indeterminate", f"CI [{ci['lo']:+.2f}, {ci['hi']:+.2f}] straddles the bars", ci, missing


def fetch_bars(symbol: str, start: str, end: str, work: Path) -> tuple:
    """(interval, [(open_time, close)]) via fetch_backtest_candles: 1m, then 5m on the default source, then dukascopy 5m
    (yfinance caps intraday history at 7 d for 1m / 60 d for 5m, so older equity fills need the dukascopy lane)."""
    import csv
    crypto = symbol.upper().endswith(("USDT", "USDC", "USD")) and not symbol.upper().endswith("=F")
    plan = (("1", None), ("5", None)) if crypto else (("1", "dukascopy"), ("5", "dukascopy"), ("5", "yfinance"))
    for iv, src in plan:   # `auto` is the crypto lane (bybit, binance); equities / futures go to dukascopy, then yfinance
        out = work / f"{symbol}_{iv}_{src or 'auto'}.csv"
        cmd = [sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", symbol,
               "--interval", iv, "--start-date", start, "--end-date", end, "--output", str(out)]
        if src:
            cmd += ["--source", src]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if p.returncode == 0 and out.exists():
            bars = []
            with out.open() as fh:
                for row in csv.DictReader(fh):
                    t = _ts(row.get("timestamp") or row.get("time") or row.get("open_time"))
                    c = row.get("close")
                    if t and c:
                        bars.append((t, float(c)))
            if bars and bars[0][0] <= _ts(start + "T23:59:59+00:00"):   # the series must reach back to the first fill
                return f"{iv}m{'/' + src if src else ''}", sorted(bars)
    return None, []


def run(fills_path: Path) -> Dict[str, Any]:
    from src.runtime.execution_costs import resolve_fee_bps_roundtrip
    fills = [json.loads(x) for x in fills_path.read_text().splitlines() if x.strip()]
    work = Path(tempfile.mkdtemp(prefix="markout_"))
    bars, fee = {}, {}
    for sym in sorted({f["symbol"] for f in fills}):
        ts = sorted(_ts(f["t"]) for f in fills if f["symbol"] == sym)
        bars[sym] = fetch_bars(sym, ts[0].date().isoformat(), (ts[-1] + timedelta(days=1)).date().isoformat(), work)
        try:
            fee[sym] = float(resolve_fee_bps_roundtrip(sym))
        except Exception:  # noqa: BLE001  # allow-silent: an unknown symbol's fee falls back to 0 and is reported per symbol
            fee[sym] = 0.0
    rows = markouts(fills, bars, fee)
    v, why, ci, missing = grade(rows)
    split = {}
    for k in ("account", "order_type", "account_class"):
        split[k] = {val: grouped_boot_ci([r for r in rows if r.get(k) == val], "gap_1h_bps", draws=1000)
                    for val in sorted({str(r.get(k)) for r in rows})}
    return {"verdict": v, "note": why, "n": ci["n"], "pooled_gap_1h": ci,
            "pooled_gap_4h": grouped_boot_ci(rows, "gap_4h_bps"), "pooled_markout_1h": grouped_boot_ci(rows, "markout_1h_bps"),
            "missing_fills": missing, "fills_total": len(rows), "split_gap_1h": split,
            "mid_interval_by_symbol": {s: b[0] for s, b in bars.items()}, "fee_bps_roundtrip_by_symbol": fee,
            "fills_source": str(fills_path)}


# ------------------------------------------------------------------------------------------------ self-test
def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    rows = [{"id": 1, "status": "closed", "is_backtest": False, "timestamp": t0.isoformat(), "closed_at": (t0 + timedelta(hours=6)).isoformat(),
             "entry_price": 100.0, "exit_price": 101.0, "position_size": 2.0, "fee_maker_usd": 0.0, "fee_taker_usd": 0.2018,
             "direction": "long", "symbol": "XUSDT", "account_id": "bybit_1", "account_class": "demo", "strategy_name": "leg",
             "cost_source": "broker", "exit_reason": "tp", "pnl": 999.0},
            {"id": 2, "status": "open", "is_backtest": False}, {"id": 3, "status": "closed", "is_backtest": True}]
    f = fills_from_rows(rows, "2026-09-01")
    check("one closed live trade -> two fills (open and backtest rows dropped)", len(f) == 2)
    check("no dollar or size field leaves export", all("pnl" not in x and "position_size" not in x and "fee_taker_usd" not in x for x in f))
    check("recorded cost is fees over two-fill notional, in bps (0.2018 / (2 x 201) x 1e4 = 5.02)", abs(f[0]["recorded_cost_bps"] - 5.0199) < 1e-3)
    check("long entry is a buy (+1), its exit a sell (-1); tp exit -> limit_tp", f[0]["side"] == 1 and f[1]["side"] == -1 and f[1]["order_type"] == "limit_tp")
    bars = [(t0 + timedelta(minutes=5 * k), 100.0 + 0.01 * k) for k in range(400)]
    check("price_after takes the first bar at/after t", price_after(bars, t0 + timedelta(minutes=61)) == bars[13][1])
    check("price_after returns None past the max lag", price_after(bars, t0 + timedelta(days=5)) is None)
    m = markouts(f, {"XUSDT": ("5m", bars)}, {"XUSDT": 0.0})
    # entry buy at 100, +1h close = 100 + 0.12 -> +12 bps favourable; gap = -12 - 5.02
    check("buy markout is side-adjusted and positive when price rises", abs(m[0]["markout_1h_bps"] - 12.0) < 1e-6
          and abs(m[0]["gap_1h_bps"] - (-12.0 - 5.0199)) < 1e-3)
    # grader
    def mk(gap, n):
        return [{"trade": str(i // 2), "gap_1h_bps": gap + (0.5 if i % 2 else -0.5)} for i in range(n)]
    check("grade: CI above 0 -> pass (UNDERSTATED)", grade(mk(10.0, 400))[0] == "pass")
    check("grade: CI below 2 bps -> fail (NOT UNDERSTATED)", grade(mk(-10.0, 400))[0] == "fail")
    check("grade: n < 200 -> indeterminate", grade(mk(10.0, 100))[0] == "indeterminate")
    rows_m = mk(10.0, 400) + [{"trade": f"x{i}", "gap_1h_bps": None} for i in range(60)]
    check("grade: > 10% missing -> indeterminate (partial)", grade(rows_m)[0] == "indeterminate")
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export")
    e.add_argument("--since", required=True)
    e.add_argument("--out", required=True)
    r = sub.add_parser("run")
    for k in ("--fills", "--unit", "--rule-id", "--out"):
        r.add_argument(k, required=True)
    r.add_argument("--registered-at", default="2026-11-18")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd == "export":
        print(json.dumps(export(a.since, Path(a.out))))
        return 0
    if a.cmd != "run":
        ap.error("export | run | --self-test")
    res = run(Path(a.fills))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    row = {"schema_version": 1, "schema": "markout_fills/1", "research_unit": a.unit, "read_state": "measured" if res["verdict"] != "indeterminate" or res["n"] >= N_MIN else "partial",
           "verdict": res["verdict"], "n": res["n"], "note": res["note"],
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": f"closed live/paper fills exported from trade_journal into {a.fills}; markouts from public candles",
           "measurement": res}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"MARKOUT {row['verdict']}: {row['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
