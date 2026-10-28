#!/usr/bin/env python3
# wiring: .github/workflows/research-script-run.yml via research/queue/RQ-20261011-9da8-05.yaml (--mode tsmom) and -06 (--mode xsec).
"""Runner-reachable wrapper for the two frontier momentum units: fetch -> backtest -> grade -> verdict.json.

``research-script-run.yml`` runs ONE allow-listed python command and derives the E5 record from the
``verdict.json`` it writes. ``scripts/backtest_xsec_momentum.py`` takes pre-made CSVs and prints its own
JSON, and nothing fetched funding, so neither frontier unit could dispatch (FRONTIER-LEVER-XSEC-RUNNER).
This wrapper closes that gap and holds NO cost model of its own:

  * corpus  : daily klines (Binance-vision, keyless, reachable from the runner) via
              ``scripts/ops/fetch_backtest_candles.fetch_klines_binance_vision``;
  * funding : the SETTLED fundingRate series per symbol via ``scripts/research/funding_series.py``; the
              panel is trimmed to the last day every symbol has settled funding for (the current month has
              no monthly zip), so no held leg-day is silently charged zero;
  * engine  : ``--mode xsec`` -> ``scripts/backtest_xsec_momentum.run_backtest``; ``--mode tsmom`` ->
              ``scripts/backtest_tsmom.run_tsmom``. Both resolve fee / slippage / funding through
              ``src.runtime.execution_costs`` (the one cost owner);
  * grade   : the unit's PRE-REGISTERED rule, passed as flags (``--n-floor``), never chosen here.
              xsec (RULE-RQ1011-9DA8-06): PASS net_total_r>0 & n>=floor; FAIL net<=0 & n>=floor; else INDETERMINATE.
              tsmom (RULE-RQ1011-9DA8-05): per symbol; PASS if >=2 symbols have net>0 & n>=floor, FAIL if >=2
              have net<=0 & n>=floor, else INDETERMINATE (a lone pass is a re-queue, not a read).

verdict.json (``script_run.derive_record``): ``verdict, read_state, population, n, measurement, note``. The
measurement carries ``net_total_r`` and ``n_trades`` per symbol. UNIT: ``net_total_r`` is the sum of daily
FRACTIONAL returns of the book (xsec) or of each vol-targeted sleeve (tsmom) -- there is no stop distance in
either engine, so it is not a multiple of R; the verdict says so.

A fetch that returns nothing for a symbol writes ``read_state: no_data`` / ``verdict: not_applicable`` --
never a measured zero. Tier-1 research tooling; writes only under ``--out``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "scripts", _REPO / "scripts" / "research", _REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import backtest_tsmom  # noqa: E402
import backtest_xsec_momentum as xsec  # noqa: E402
import funding_series  # noqa: E402

DEFAULT_XSEC_BASKET = "ETHUSDT,SOLUSDT,ADAUSDT,AVAXUSDT,BNBUSDT,LINKUSDT"  # the P7 first-pass universe
DEFAULT_TSMOM_SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT"


def _fetch_closes(symbol: str, start: datetime, end: datetime) -> pd.Series:
    from fetch_backtest_candles import fetch_klines_binance_vision
    rows = fetch_klines_binance_vision(symbol, "D", int(start.timestamp() * 1000), int(end.timestamp() * 1000))
    if not rows:
        return pd.Series(dtype=float, name=symbol)
    idx = pd.DatetimeIndex([pd.Timestamp(r["timestamp"]).tz_convert("UTC").normalize() for r in rows])
    return pd.Series([r["close"] for r in rows], index=idx, name=symbol)


def build_inputs(symbols: List[str], days: int, *, now: Optional[datetime] = None,
                 fetch_close: Callable[..., pd.Series] = _fetch_closes,
                 fetch_fund: Callable[..., Dict[str, Any]] = funding_series.fetch_funding) -> Dict[str, Any]:
    """Fetch closes + funding, trim to the last fully-funded day. Returns panel, funding dict, coverage."""
    now = now or datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    closes: Dict[str, pd.Series] = {}
    funds: Dict[str, pd.Series] = {}
    coverage: Dict[str, Any] = {}
    empty: List[str] = []
    for sym in symbols:
        c = fetch_close(sym, start, end)
        f = fetch_fund(sym, start, end)
        fs = f["series"]
        coverage[sym] = {"close_rows": int(len(c)), "funding_days": int(len(fs)),
                         "funding_settlements": int(f["n_settlements"]),
                         "funding_months_missing": list(f["missing_months"])}
        if len(c) == 0 or len(fs) == 0:
            empty.append(sym)
            continue
        closes[sym] = c
        funds[sym] = fs
    if empty:
        return {"panel": None, "funding": {}, "coverage": coverage, "empty": empty, "start": start, "end": end}
    last_funded = min(s.index.max() for s in funds.values())
    panel = xsec_panel(closes)
    panel = panel[panel.index <= last_funded]
    return {"panel": panel, "funding": funds, "coverage": coverage, "empty": [], "start": start,
            "end": end, "trimmed_to": str(last_funded.date())}


def xsec_panel(closes: Dict[str, pd.Series]) -> pd.DataFrame:
    """Same alignment rule as ``xsec.load_panel`` (union of days, interior ffill, no back-fill)."""
    return pd.DataFrame(closes).sort_index().ffill()


def grade_xsec(net: float, n_trades: int, gross: float, funding_cost: float, n_floor: int) -> Dict[str, str]:
    if n_trades < n_floor:
        v, why = "indeterminate", f"n_trades {n_trades} < {n_floor}"
    elif net > 0:
        v, why = "pass", f"net_total_r {net:+.4f} > 0 with n_trades {n_trades} >= {n_floor}"
    else:
        v, why = "fail", f"net_total_r {net:+.4f} <= 0 with n_trades {n_trades} >= {n_floor}"
    if gross > 0 and net <= 0 and funding_cost > 0:
        why += f"; gross {gross:+.4f} > 0 and net <= 0 -- FUNDING share of gross {funding_cost / gross:.1%} (headline per the rule)"
    return {"verdict": v, "why": why}


def grade_tsmom(per_symbol: Dict[str, Dict[str, Any]], n_floor: int, min_syms: int = 2) -> Dict[str, str]:
    pos = [s for s, r in per_symbol.items() if r["n_trades"] >= n_floor and r["net_total_r"] > 0]
    neg = [s for s, r in per_symbol.items() if r["n_trades"] >= n_floor and r["net_total_r"] <= 0]
    thin = [s for s, r in per_symbol.items() if r["n_trades"] < n_floor]
    if len(pos) >= min_syms:
        return {"verdict": "pass", "why": f"net>0 with n>={n_floor} on {pos}"}
    if len(neg) >= min_syms:
        return {"verdict": "fail", "why": f"net<=0 with n>={n_floor} on {neg} (a lone pass would be a re-queue, not a read)"}
    return {"verdict": "indeterminate",
            "why": f"pass={pos} fail={neg} below_n_floor={thin}; neither side reaches {min_syms} symbols"}


def run(args: argparse.Namespace, *, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    inp = inputs or build_inputs(symbols, args.days)
    if inp["panel"] is None or inp["panel"].empty:
        return {"verdict": "not_applicable", "read_state": "no_data",
                "population": f"{args.mode}: no usable data for {inp.get('empty')} -- NEVER MEASURED",
                "n": None, "measurement": {"coverage": inp["coverage"]},
                "note": "no_data: a symbol returned no daily closes or no settled funding; nothing was graded."}
    panel, funds = inp["panel"], inp["funding"]
    cov = {"coverage": inp["coverage"], "panel_start": str(panel.index[0].date()),
           "panel_end": str(panel.index[-1].date()), "panel_days": int(len(panel)),
           "trimmed_to_last_funded_day": inp.get("trimmed_to")}
    unit_note = ("net_total_r is the sum of daily FRACTIONAL returns (no stop distance exists in this engine), "
                 "net of fee + slippage + signed funding from the settled series")
    if args.mode == "xsec":
        res = xsec.run_backtest(panel, formation=args.formation_days, skip=args.skip_days,
                                rebalance=args.rebalance_days, quantile=args.quantile,
                                fee_bps=xsec.FEE_BPS_ROUNDTRIP, fee_mult=args.fee_multiplier,
                                venue="perp", funding_series=funds)
        s = res["summary"]
        per = s["per_symbol"]
        n_tr = sum(v["n_trades"] for v in per.values())
        g = grade_xsec(s["net_total_return"], n_tr, s["gross_total_return"], s["funding_cost_total"], args.n_floor)
        meas = {**cov, "book": {"net_total_r": s["net_total_return"], "gross_total_r": s["gross_total_return"],
                                "n_trades": n_tr, "turnover_cost_total": s["turnover_cost_total"],
                                "funding_cost_total": s["funding_cost_total"],
                                "net_total_r_fee_only": s["net_total_return_fee_only"],
                                "sharpe_annualized": s["sharpe_annualized"], "weeks_total": s["weeks_total"]},
                "per_symbol": {k: {"net_total_r": v["net_return"], "n_trades": v["n_trades"],
                                   "gross_return": v["gross_return"], "funding_cost": v["funding_cost"],
                                   "turnover_cost": v["turnover_cost"]} for k, v in per.items()},
                "funding_basis": s["funding_basis"], "params": s["params"]}
        n_out, pop = n_tr, (f"xsec long/short, {len(per)} perps {sorted(per)}, daily {cov['panel_start']}..{cov['panel_end']} "
                            f"({cov['panel_days']} days), {s['weeks_total']} rebalances")
        missing = s["funding_basis"]["missing_leg_days"]
        flat = s["funding_basis"]["funding_flat_symbols"]
    else:
        res = backtest_tsmom.run_tsmom(panel, lookbacks=[int(x) for x in args.lookbacks.split(",")],
                                       vol_window=args.vol_window, target_vol=args.target_vol,
                                       max_leverage=args.max_leverage, rebalance=args.rebalance_days,
                                       fee_multiplier=args.fee_multiplier, venue="perp", funding_series=funds)
        per = res["per_symbol"]
        g = grade_tsmom(per, args.n_floor)
        meas = {**cov, "per_symbol": {k: {"net_total_r": v["net_total_r"], "n_trades": v["n_trades"],
                                          "gross_return": v["gross_return"], "funding_cost": v["funding_cost"],
                                          "turnover_cost": v["turnover_cost"],
                                          "funding_basis": v["funding_basis"],
                                          "funding_missing_days": v["funding_missing_days"]}
                                      for k, v in per.items()},
                "params": res["params"]}
        n_out = sum(v["n_trades"] for v in per.values())
        pop = (f"tsmom vol-targeted, {sorted(per)}, daily {cov['panel_start']}..{cov['panel_end']} "
               f"({cov['panel_days']} days), lookbacks {res['params']['lookbacks']}")
        missing = sum(v["funding_missing_days"] for v in per.values())
        flat = [k for k, v in per.items() if v["funding_basis"] != "real_series"]
    note = f"{g['verdict'].upper()}: {g['why']}. {unit_note}."
    if missing or flat:
        note += f" FUNDING GAPS: {missing} held leg-days uncharged, flat-fallback symbols {flat}."
    return {"verdict": g["verdict"], "read_state": "measured", "population": pop, "n": n_out,
            "measurement": meas, "note": note}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["xsec", "tsmom"], required=True)
    ap.add_argument("--symbols", default=None, help="comma list of Binance-USDM symbols")
    ap.add_argument("--days", type=int, default=1095, help="trailing window ending today (default 3y)")
    ap.add_argument("--n-floor", type=int, required=True, help="the unit's registered minimum n_trades")
    ap.add_argument("--rebalance-days", type=int, default=7)
    ap.add_argument("--fee-multiplier", type=float, default=1.0)
    ap.add_argument("--formation-days", type=int, default=28)
    ap.add_argument("--skip-days", type=int, default=0)
    ap.add_argument("--quantile", type=float, default=0.3333)
    ap.add_argument("--lookbacks", default="28,56,112")
    ap.add_argument("--vol-window", type=int, default=30)
    ap.add_argument("--target-vol", type=float, default=0.20)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.symbols is None:
        args.symbols = DEFAULT_XSEC_BASKET if args.mode == "xsec" else DEFAULT_TSMOM_SYMBOLS
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rec = run(args)
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("verdict", "read_state", "n", "note")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
