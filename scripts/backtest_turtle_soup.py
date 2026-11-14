#!/usr/bin/env python3
"""Per-leg Stage-0 harness for turtle_soup — build gap (b), RQ-20261101-78fc-12 / row E25.

WHY. ``comms/strategy_evidence/turtle_soup.json`` reads ``coverage_state: no_harness``:
``regime_debt_matrix.classify()`` routes nothing for this leg, so it trades on bybit_1 with no
Stage-0 measurement at all. Row E25 was marked DONE without the branch (manager, 2026-11-13 04:00Z).

WHAT IT MEASURES. The leg exactly as the LIVE unit runs it, by reusing the system harness engine
(``scripts/backtest_system.run_system_backtest``) with a one-leg roster:
  * entries: the REAL ``src.units.strategies.turtle_soup.order_package`` on every closed 15m bar
    (the live adapter is single-frame 15m; ``entry_tf: 1m`` / ``max_entry_wait_bars_1m`` /
    ``trail_atr_mult`` are config keys the live adapter never reads, so they carry no behaviour here
    either; see regime_debt_matrix ``_TS_PLAIN``);
  * fills at the next bar's open; intrabar venue SL/TP; then the REAL ``monitor()`` (TP1 partial
    of ``partial_close_pct`` with the runner rolled to TP2, break-even at ``be_at_r`` with
    ``be_offset_bps``), through the shared ``monitor_verdict`` interpreter;
  * the full cost stack: venue fee + slippage + perp funding (``src.research.run_costs``), never fee-only.
The daily-loss cap is disabled (100 %): a per-leg Stage-0 record measures the leg's R, not the
shared account's capital constraints (that is the system gate's job).

OUTPUT, in the shape regime_debt_matrix / build_strategy_evidence read from every harness:
  ``--emit-trades``  one JSONL row per POSITION (TP1 partial + runner summed): entry_time,
                     exit_time, direction, entry, sl (entry-time stop), net_r, net_r_fee_only, ...
                     R = net PnL / (initial qty x |entry - entry-time sl|).
  ``--json``         total_trades, net_total_r, net_total_r_fee_only, data_start, data_end,
                     fee/slippage/funding bps, monitor errors.

Tier 1: research tooling; imports the live unit read-only, no order path.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LEG = "turtle_soup"


def position_rows(closed: List[Any]) -> List[Dict[str, Any]]:
    """Group the engine's closed fills by position (owner, entry_ts, entry) and express each in R
    against the ENTRY-time stop and the position's initial quantity. A TP1 partial and its runner
    are one position, one row."""
    groups: "OrderedDict[tuple, List[Any]]" = OrderedDict()
    for t in closed:
        groups.setdefault((getattr(t, "owner", None), str(t.entry_ts), float(t.entry), t.side), []).append(t)
    rows: List[Dict[str, Any]] = []
    for (_owner, entry_ts, entry, side), fills in groups.items():
        sl = fills[0].sl
        qty0 = sum(float(f.qty) for f in fills)
        # 1R = the UNIT's own risk per unit (order_package meta.risk_per_unit: signal-bar entry - stop), the basis
        # live sizing uses. The engine fills at the NEXT bar's open, so |fill - sl| collapses toward 0 (or flips
        # sign) when that open gaps to the stop: normalising by it turned one gap into -194 R (smoke 2026-11-13).
        meta = getattr(fills[0], "meta", None) or {}
        try:
            rpu = float(meta.get("risk_per_unit"))
        except (TypeError, ValueError):
            rpu = None
        if rpu is None or not rpu > 0:
            rpu = abs(entry - float(sl)) if sl is not None else 0.0
        risk = rpu * qty0
        if risk <= 0:
            continue
        pnl = sum(float(f.pnl) for f in fills)
        cost_extra = sum(float(getattr(f, "slippage", 0.0) or 0.0) + float(getattr(f, "funding", 0.0) or 0.0)
                         for f in fills)
        last = fills[-1]
        rows.append({
            "strategy": LEG, "entry_time": entry_ts, "exit_time": str(last.exit_ts),
            "direction": side, "entry": entry, "sl": float(sl), "risk_per_unit": rpu,
            "exit_reason": "+".join(str(f.reason) for f in fills),
            "n_fills": len(fills),
            "net_r": round(pnl / risk, 6),
            "net_r_fee_only": round((pnl + cost_extra) / risk, 6),
            "cost_slippage_r": round(sum(float(getattr(f, "slippage", 0.0) or 0.0) for f in fills) / risk, 6),
            "cost_funding_r": round(sum(float(getattr(f, "funding", 0.0) or 0.0) for f in fills) / risk, 6),
            "confidence": getattr(fills[0], "confidence", None),
        })
    return rows


def run(data: str, *, symbol: str, start: Optional[str], end: Optional[str],
        fee_bps_roundtrip: Optional[float], slippage_bps_roundtrip: Optional[float],
        funding_bps_per_window: Optional[float], overrides: Dict[str, Any], tf: str = "15m") -> Dict[str, Any]:
    import backtest_system as bs
    from src.research.run_costs import resolve_run_costs
    base = bs._load_candles(data)
    costs = resolve_run_costs(symbol, fee_bps_roundtrip=fee_bps_roundtrip,
                              slippage_bps_roundtrip=slippage_bps_roundtrip,
                              funding_bps_per_window=funding_bps_per_window)
    # DEMO-FLOOR-ITER (2026-11-13), the TIMEFRAME lever family: the same unit on a coarser setup bar. The engine builds the
    # leg's frame from ROSTER[leg]["tf"] and clocks on clock_tf, so both follow ``tf``; the unit reads its bar size from
    # cfg["timeframe"] (sweep_lookback_15m is a BAR COUNT, so it spans 4x / 16x the clock time at 1h / 4h -- stated, not hidden).
    saved = dict(bs.ROSTER[LEG])
    bs.ROSTER[LEG] = {**saved, "tf": tf}
    ov = {**(overrides or {}), "timeframe": tf} if tf != "15m" else (overrides or {})
    try:
        out = bs.run_system_backtest(
            base, roster=[LEG], start=start, end=end, initial_balance=10_000.0, risk_pct=0.3,
            daily_loss_pct=100.0, signal_ttl_bars=1, overrides={LEG: ov} if ov else {},
            refresh=True, clock_tf=tf, symbol=symbol, costs=costs, require_full_costs=False,
            attach_full=True)   # attach_full: the per-trade ledger (closed_trades); the summary math is unchanged
    finally:
        bs.ROSTER[LEG] = saved
    return out


def summarize(out: Dict[str, Any], rows: List[Dict[str, Any]], data_start: Any, data_end: Any) -> Dict[str, Any]:
    pol = out.get("cost_policy") or {}
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rows:                                   # rows are in entry order (the engine books them chronologically)
        eq += r["net_r"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    by_outcome: Dict[str, int] = {}
    for r in rows:
        by_outcome[r["exit_reason"]] = by_outcome.get(r["exit_reason"], 0) + 1
    return {
        "harness": "scripts/backtest_turtle_soup.py", "strategy": LEG,
        "total_trades": len(rows),
        "net_total_r": round(sum(r["net_r"] for r in rows), 4),
        "net_total_r_fee_only": round(sum(r["net_r_fee_only"] for r in rows), 4),
        "max_drawdown_r": round(mdd, 4),
        "by_outcome": by_outcome,
        "data_start": str(data_start) if data_start is not None else None,
        "data_end": str(data_end) if data_end is not None else None,
        "fee_bps_roundtrip": pol.get("fee_bps_roundtrip"),
        "slippage_bps_roundtrip": pol.get("slippage_bps_roundtrip"),
        "funding_bps_per_window": pol.get("funding_bps_per_window"),
        "cost_policy": pol,
        "monitor_errors": out.get("monitor_errors"),
        "engine_closed_fills": len(out.get("closed_trades") or []),
    }


def _self_test() -> int:
    from types import SimpleNamespace as NS

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    # A long entry 100 / sl 98 (risk 2/unit), qty 1: TP1 partial 25 % at 102 then runner stopped at BE 100.15.
    fills = [NS(owner=LEG, entry_ts="2025-01-01 00:00:00+00:00", entry=100.0, side="long", sl=98.0, qty=0.25,
                pnl=0.25 * 2.0 - 0.01, exit_ts="t1", reason="tp1_partial", slippage=0.005, funding=0.0, confidence=0.7),
             NS(owner=LEG, entry_ts="2025-01-01 00:00:00+00:00", entry=100.0, side="long", sl=98.0, qty=0.75,
                pnl=0.75 * 0.15 - 0.02, exit_ts="t2", reason="be_sl", slippage=0.01, funding=0.002, confidence=0.7),
             NS(owner=LEG, entry_ts="2025-01-02 00:00:00+00:00", entry=50.0, side="short", sl=51.0, qty=2.0,
                pnl=-2.0 - 0.05, exit_ts="t3", reason="sl", slippage=0.03, funding=0.0, confidence=0.5)]
    fills.append(NS(owner=LEG, entry_ts="2025-01-03 00:00:00+00:00", entry=71425.0, side="long", sl=71425.66, qty=10.0,
                    pnl=10.0 * 0.66 - 50.0, exit_ts="t4", reason="sl", slippage=5.0, funding=0.0, confidence=0.6,
                    meta={"risk_per_unit": 120.0}))
    rows = position_rows(fills)
    gap = rows[2]
    check("a next-open fill gapped to the stop is normalised by the unit's risk_per_unit, not |fill - sl|",
          gap["risk_per_unit"] == 120.0 and abs(gap["net_r"] - round((10.0 * 0.66 - 50.0) / (120.0 * 10.0), 6)) < 1e-9)
    rows = rows[:2]
    check("a TP1 partial + its runner are ONE position row", len(rows) == 2 and rows[0]["n_fills"] == 2)
    exp = ((0.25 * 2.0 - 0.01) + (0.75 * 0.15 - 0.02)) / 2.0
    check("R = summed net PnL / (initial qty x entry-time risk)", abs(rows[0]["net_r"] - round(exp, 6)) < 1e-9)
    check("a full stop-out is -1R minus costs", abs(rows[1]["net_r"] - (-2.05 / 2.0)) < 1e-9)
    check("fee-only R adds slippage + funding back", rows[0]["net_r_fee_only"] > rows[0]["net_r"])
    s = summarize({"cost_policy": {"fee_bps_roundtrip": 11.0, "slippage_bps_roundtrip": 3.0,
                                   "funding_bps_per_window": 1.0}}, rows, "a", "b")
    check("max drawdown in R = the peak-to-trough of the running equity (+win then the -1.025R stop)",
          s["max_drawdown_r"] == round(-rows[1]["net_r"], 4))
    check("summary totals the rows", s["total_trades"] == 2 and abs(s["net_total_r"] - round(rows[0]["net_r"] + rows[1]["net_r"], 4)) < 1e-9)
    print("self-test passed")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="turtle_soup per-leg Stage-0 harness (live order_package + monitor).")
    p.add_argument("--data")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--resample", default="15m", help="setup bar: 15m (the live unit) or 1h / 4h (the timeframe lever family)")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--fee-bps-roundtrip", type=float, default=None)
    p.add_argument("--slippage-bps-roundtrip", type=float, default=None)
    p.add_argument("--funding-bps-per-window", type=float, default=None)
    p.add_argument("--override", action="append", default=[], metavar="key=val",
                   help="turtle_soup param override (an exit_lever_ablation arm), e.g. atr_stop_mult=0.35")
    p.add_argument("--emit-trades")
    p.add_argument("--json", dest="json_out")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.data:
        p.error("--data is required")
    tf = {"15min": "15m"}.get(str(a.resample).lower(), str(a.resample).lower())
    if tf not in ("15m", "1h", "4h"):
        print(f"ERROR: turtle_soup is modelled on 15m (live) and, for the timeframe lever family, 1h / 4h; "
              f"--resample {a.resample!r} is not", file=sys.stderr)
        return 2
    overrides: Dict[str, Any] = {}
    for kv in a.override:
        k, _, v = kv.partition("=")
        try:
            overrides[k] = json.loads(v)
        except ValueError:
            overrides[k] = v
    out = run(a.data, symbol=a.symbol, start=a.start, end=a.end, fee_bps_roundtrip=a.fee_bps_roundtrip,
              slippage_bps_roundtrip=a.slippage_bps_roundtrip, funding_bps_per_window=a.funding_bps_per_window,
              overrides=overrides, tf=tf)
    rows = position_rows(out.get("closed_trades") or [])
    import pandas as pd
    import backtest_system as bs
    base = bs._load_candles(a.data)
    ts = pd.to_datetime(base["timestamp"], utc=True)
    if a.start:
        ts = ts[ts >= pd.Timestamp(a.start, tz="UTC") if pd.Timestamp(a.start).tzinfo is None else pd.Timestamp(a.start)]
    if a.end:
        ts = ts[ts <= pd.Timestamp(a.end, tz="UTC") if pd.Timestamp(a.end).tzinfo is None else pd.Timestamp(a.end)]
    summ = summarize(out, rows, ts.min() if len(ts) else None, ts.max() if len(ts) else None)
    if a.emit_trades:
        Path(a.emit_trades).write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(summ, indent=2, default=str))
    print(f"turtle_soup: trades={summ['total_trades']} net_total_r={summ['net_total_r']} "
          f"(fee-only {summ['net_total_r_fee_only']}) window {summ['data_start']}..{summ['data_end']} "
          f"costs fee={summ['fee_bps_roundtrip']} slip={summ['slippage_bps_roundtrip']} fund={summ['funding_bps_per_window']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
