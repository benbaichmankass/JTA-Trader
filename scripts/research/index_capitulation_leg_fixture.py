#!/usr/bin/env python3
# wiring: manual-only - INDEX-CAPIT-1X-LEG leg spec + parity fixture (manager 2026-11-24); evidence RQ-20261124-1e06-06 / -08; python3 scripts/research/index_capitulation_leg_fixture.py --out DIR
"""Leg spec + parity fixture for the index capitulation 1x leg (row INDEX-CAPIT-1X-LEG), generated FROM the evidence harness so the wiring lane
can prove parity against the exact functions that produced RQ-20261124-1e06-06 (run 45506679715) and -08 (run 45509974875).

Writes (Tier-1 research tooling; reads public yfinance daily bars, writes only under --out):
  spec.json            the population (18 tickers), the signal / stop / TP / hold rules with the harness constants, each ticker's K* as the
                       landed verdict recorded it (calibrated on that ticker's first 60% of no-TP trades)
  parity_fixture.json  EVERY harness trade per ticker over the evidence window (signal date, entry date, entry = next open, stop, TP = entry +
                       K* x risk, exit, exit reason, bars, gross / net R), recomputed here with the verdict's K*; plus a per-ticker check that the
                       recomputed net R equals the landed verdict's net R (the fixture is only trusted when it reproduces the record)
  total_return.json    the distributions caveat (manager 2026-11-24): the same trades re-simulated on yfinance auto_adjust=True (dividend-adjusted)
                       bars; per ticker full-sample and out-of-sample (post K* boundary) net R, price vs total return. A read, not a gate.

    python3 scripts/research/index_capitulation_leg_fixture.py --out comms/research/INDEX-CAPIT-1X-LEG [--cache DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import index_signal_etf_harness as H  # noqa: E402

VERDICTS = {"RQ-20261124-1e06-06": REPO / "comms/research/RQ-20261124-1e06-06/45506679715/verdict.json",
            "RQ-20261124-1e06-08": REPO / "comms/research/RQ-20261124-1e06-08/45509974875/verdict.json"}
FAMILY = "capitulation_wide"


def k_stars() -> Dict[str, Dict[str, Any]]:
    out = {}
    for unit, p in VERDICTS.items():
        v = json.loads(p.read_text())
        for pair, d in v["measurement"]["pairs"].items():
            t = pair.split("->")[0]
            out[t] = {"unit": unit, "k_star": d["tp_calibration"].get("k_star"), "is_boundary": d["tp_calibration"].get("is_boundary"),
                      "record_net_r": d["net_r"], "record_n": d["n"], "record_oos_net_r": (d.get("oos") or {}).get("net_r")}
    return out


def fetch_tr(ticker: str, start: str, end: str) -> pd.DataFrame:
    """auto_adjust=True daily bars (dividends and splits folded into OHLC): the total-return series."""
    import yfinance as yf
    df = yf.download(ticker, start=start, end=(pd.Timestamp(end) + pd.Timedelta(days=3)).strftime("%Y-%m-%d"), interval="1d",
                     auto_adjust=True, progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="first")].sort_index().dropna()
    return df[df.index <= pd.Timestamp(end)]


def run(out: Path, cache: Path | None) -> Dict[str, Any]:
    ks = k_stars()
    cap = H.HOLD_CAP[FAMILY]
    fixture, tr_read = {}, {}
    for t, meta in sorted(ks.items()):
        px = H.fetch_daily(t, H.WINDOW_START, H.WINDOW_END, cache)
        f = H.build_frame(px, px)
        f = f[(f.index >= pd.Timestamp(H.WINDOW_START)) & (f.index <= pd.Timestamp(H.WINDOW_END))]
        sigs = H.index_signals(f, FAMILY)
        g = H.simulate(f, sigs, 1.0, cap, H.SLIP_BPS_SIDE, meta["k_star"])
        trades = g["trades"]
        for tr in trades:
            tr["tp"] = round(tr["entry"] + meta["k_star"] * tr["risk"], 4) if meta["k_star"] else None
            tr["stop"] = round(tr["entry"] - tr["risk"], 4)
        net = round(sum(x["net_r"] for x in trades), 4)
        fixture[t] = {"k_star": meta["k_star"], "n": len(trades), "net_r": net, "record_net_r": meta["record_net_r"], "record_n": meta["record_n"],
                      "reproduces_record": abs(net - meta["record_net_r"]) < 0.05 and len(trades) == meta["record_n"], "skips": g["skips"],
                      "trades": trades}
        # total-return read on the same signal dates' rules (signals recomputed on the adjusted series: adjustment is multiplicative per day)
        try:
            tx = fetch_tr(t, H.WINDOW_START, H.WINDOW_END)
            ft = H.build_frame(tx, tx)
            gt = H.simulate(ft, H.index_signals(ft, FAMILY), 1.0, cap, H.SLIP_BPS_SIDE, meta["k_star"])
            b = meta["is_boundary"]
            tr_read[t] = {"price_net_r": net, "total_net_r": round(sum(x["net_r"] for x in gt["trades"]), 4), "n_price": len(trades),
                          "n_total": len(gt["trades"]),
                          "price_oos_net_r": round(sum(x["net_r"] for x in trades if b and x["entry_date"] > b), 4),
                          "total_oos_net_r": round(sum(x["net_r"] for x in gt["trades"] if b and x["entry_date"] > b), 4)}
        except Exception as e:  # noqa: BLE001  # allow-silent: the total-return read is recorded per ticker as read_state could_not_look with the reason, never a zero
            tr_read[t] = {"read_state": "could_not_look", "reason": f"{type(e).__name__}: {e}"[:200]}
    spec = {"leg": "index_capitulation_1x", "row": "INDEX-CAPIT-1X-LEG", "evidence": {u: str(p.relative_to(REPO)) for u, p in VERDICTS.items()},
            "population": sorted(ks), "execution": "long only, 1x: the index ETF itself (signal and execution on the same ticker)",
            "bars": "daily, yfinance auto_adjust=False (split-adjusted price return) in the evidence; see total_return.json",
            "signal": {"flush": f"close <= mean(close, {H.FLUSH_MEAN}) - {H.FLUSH_ATR_WIDE} x ATR{H.ATR_LEN} AND low < min(low of the prior {H.DONCHIAN} bars)",
                       "trigger": f"the first up-close (close > previous close) within {H.FLUSH_UP_WINDOW} sessions after the flush bar",
                       "decision": "at the signal bar's close; order for the NEXT session's open"},
            "entry": "next session open (signal bar i -> entry bar i+1); a signal while in a position on the ticker is ignored",
            "stop": "lowest low from the flush bar through the signal bar (index level = ETF level at 1x); skip if the stop is not below the entry open or "
                    f"risk < {H.MIN_RISK_FRAC:.2%} of entry",
            "take_profit": "entry + K* x risk, K* per ticker below (TP doctrine: calibrated on the first 60% of that ticker's no-TP trades, never 50)",
            "fills": "stop / TP tested on the ETF's own daily high/low; a gap through a level fills at the open; stop and TP in one bar -> stop first",
            "hold_cap_sessions": cap, "cost_model": f"{H.SLIP_BPS_SIDE} bps slippage per side, no commission, ETF price series (expense embedded)",
            "k_star": {t: ks[t]["k_star"] for t in sorted(ks)},
            "caveats": ["price return in the evidence (distributions not added back): total_return.json reads the effect",
                        "fresh POPULATION confirmation, shared time window 2010-06-01..2026-10-22",
                        "per-ticker out-of-sample is mixed; the evidence is the POOLED rule, per-ticker results never gate"]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(json.dumps(spec, indent=1) + "\n")
    (out / "parity_fixture.json").write_text(json.dumps({"schema": "index_capit_parity/1", "family": FAMILY, "tickers": fixture}, indent=1, default=str) + "\n")
    (out / "total_return.json").write_text(json.dumps({"schema": "index_capit_total_return/1", "read_state": "measured", "tickers": tr_read,
                                                       "note": "auto_adjust=True re-simulation with the same rules and each ticker's verdict K*"}, indent=1) + "\n")
    return {"reproduces": {t: fixture[t]["reproduces_record"] for t in fixture}, "total_return": tr_read}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="")
    a = ap.parse_args(argv)
    r = run(Path(a.out), Path(a.cache) if a.cache else None)
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
