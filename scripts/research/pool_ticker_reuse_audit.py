#!/usr/bin/env python3
"""Ticker-reuse audit of the ml_entry_eq pool (row ML-ENTRY-EQ-CORP-EVENTS step (c), unit RQ-20261126-7c11-01).

Six pool symbols -- FB, INFO, NFX, ULTI, UN, SIX -- are ETFs in nasdaqtraded today, while in POOL_RULE's 2019-2020 dev window those tickers
belonged to companies (Facebook, IHS Markit, Newfield, Ultimate Software, Unilever NV, Six Flags). Two questions, read from Alpaca's own bars
(the same endpoint, adjustment=split, feed=sip, that the pool rule and the training table use):

  DEV     did the 2019-01-01..2020-12-31 1Day bars the liquidity screen scored exist under this ticker (i.e. the screen scored the OLD security)?
  TRAIN   do the ticker's 1Hour bars inside the models' training window 2021-01-01..2025-07-01 (train_end_exclusive of v1 / v2_struct /
          v3_struct_ens5) come from MORE THAN ONE security -- i.e. a run of bars, a gap >= GAP_DAYS calendar days, then another run (a
          delisting followed by a re-listing of the ticker)?

Positive control: META (Facebook renamed 2022-06-09) must show continuous daily bars over 2019-2025 if Alpaca maps history to the current
symbol; its result is reported so a null on FB reads correctly. Read-only (AlpacaReadOnly, GET-only allowlist); writes only under --out.

Verdict (registered in the unit): fail = >= 1 audited symbol has TRAIN contamination (two securities inside the training window);
pass = no symbol does and every symbol was read; indeterminate = a symbol could not be read; DEV findings are reported, never decide.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))

AUDIT = ["FB", "INFO", "NFX", "ULTI", "UN", "SIX"]
CONTROL = ["META"]
DEV = ("2019-01-01", "2021-01-01")
TRAIN = ("2021-01-01", "2025-07-01")
GAP_DAYS = 30


def runs(ts: pd.Series, gap_days: int = GAP_DAYS) -> List[Dict[str, Any]]:
    """Contiguous runs of bars separated by gaps >= gap_days calendar days."""
    if ts.empty:
        return []
    t = pd.to_datetime(ts, utc=True).sort_values().reset_index(drop=True)
    cut = t.diff() >= pd.Timedelta(days=gap_days)
    out, start = [], 0
    for i in list(cut[cut].index) + [len(t)]:
        seg = t.iloc[start:i]
        out.append({"first": str(seg.iloc[0]), "last": str(seg.iloc[-1]), "bars": int(len(seg))})
        start = i
    return out


def audit_symbol(sym: str, daily: List[dict], hourly: List[dict]) -> Dict[str, Any]:
    d = pd.DataFrame(daily or [])
    h = pd.DataFrame(hourly or [])
    rec: Dict[str, Any] = {"symbol": sym}
    if not d.empty:
        d["t"] = pd.to_datetime(d["t"], utc=True)
        dev = d[(d.t >= DEV[0]) & (d.t < DEV[1])]
        rec["dev_daily_bars"] = int(len(dev))
        rec["dev_median_dollar_volume"] = float((dev.c * dev.v).median()) if len(dev) else None
        rec["daily_runs"] = runs(d.t)
        rec["daily_close_by_run"] = [float(d[(d.t >= r["first"]) & (d.t <= r["last"])].c.median()) for r in rec["daily_runs"]]
    else:
        rec.update({"dev_daily_bars": 0, "dev_median_dollar_volume": None, "daily_runs": [], "daily_close_by_run": []})
    if not h.empty:
        h["t"] = pd.to_datetime(h["t"], utc=True)
        tr = h[(h.t >= TRAIN[0]) & (h.t < TRAIN[1])]
        rec["train_hourly_bars"] = int(len(tr))
        rec["train_runs"] = runs(tr.t)
    else:
        rec.update({"train_hourly_bars": 0, "train_runs": []})
    rec["dev_scored_old_security"] = rec["dev_daily_bars"] > 0
    rec["train_two_securities"] = len(rec["train_runs"]) >= 2
    return rec


def grade(recs: List[Dict[str, Any]], failed: List[str]) -> Dict[str, Any]:
    aud = [r for r in recs if r["symbol"] in AUDIT]
    bad = [r["symbol"] for r in aud if r["train_two_securities"]]
    dev = [r["symbol"] for r in aud if r["dev_scored_old_security"]]
    pre = [r["symbol"] for r in aud if r["train_hourly_bars"] and r["train_runs"]
           and r["train_runs"][0]["first"] < "2022-07-01"]   # training bars from before the ticker's 2025-26 ETF listing era
    if failed:
        v, note = "indeterminate", f"could not read {failed}"
    elif bad:
        v, note = "fail", f"two securities inside the training window under ticker(s) {bad}"
    else:
        v, note = "pass", "no audited ticker carries two securities inside the training window"
    note += f" | DEV window scored the old security for {dev or 'none'} | early (pre-2022-07) training bars for {pre or 'none'}"
    return {"verdict": v, "read_state": "measured" if not failed else "producer_failed" if len(failed) == len(AUDIT) else "measured",
            "n": len(aud), "population": f"ml_entry_eq pool tickers {AUDIT} (+ control {CONTROL}); Alpaca 1Day {DEV[0]}..2025-07-01 and "
            f"1Hour {TRAIN[0]}..{TRAIN[1]}, adjustment=split, feed=sip; gap rule >= {GAP_DAYS} days",
            "note": note, "measurement": {"records": recs},
            "records": [fanout_row(r, v) for r in recs]}


def fanout_row(rec: Dict[str, Any], verdict: str) -> Dict[str, Any]:
    """One E5 row per ticker: the emitter (research_result.py) refuses a measured row without verdict, population and an
    integer population.n (the 7c11-01 run 45763324547 could not land: its rows were the bare audit dicts). n = bars read for
    the ticker (dev 1Day + training 1Hour); the audit dict rides in the row's measurement."""
    return {"verdict": verdict, "read_state": "measured",
            "population": (f"{rec['symbol']}{' (control)' if rec['symbol'] in CONTROL else ''}: Alpaca 1Day bars {DEV[0]}..{DEV[1]} "
                           f"({rec['dev_daily_bars']}) + 1Hour bars {TRAIN[0]}..{TRAIN[1]} ({rec['train_hourly_bars']}), bars read"),
            "n": int(rec["dev_daily_bars"]) + int(rec["train_hourly_bars"]), "measurement": rec}


def self_test() -> None:
    a = [{"t": "2019-03-01T05:00:00Z", "c": 10, "v": 1e6}, {"t": "2019-03-04T05:00:00Z", "c": 10, "v": 1e6}]
    h1 = [{"t": "2021-02-01T15:00:00Z"}, {"t": "2021-02-01T16:00:00Z"}, {"t": "2025-06-26T15:00:00Z"}]
    r = audit_symbol("FB", a, h1)
    assert r["dev_scored_old_security"] and r["train_two_securities"] and len(r["train_runs"]) == 2, r
    r2 = audit_symbol("UN", [], [{"t": "2026-07-07T17:00:00Z"}])
    assert not r2["dev_scored_old_security"] and not r2["train_two_securities"] and r2["train_hourly_bars"] == 0
    g = grade([r, r2], [])
    assert g["verdict"] == "fail" and "FB" in g["note"], g
    assert all(x["verdict"] == "fail" and x["read_state"] == "measured" and isinstance(x["n"], int) and x["population"]
               for x in g["records"]), g["records"]
    assert grade([r2], [])["verdict"] == "pass"
    assert grade([r2], ["NFX"])["verdict"] == "indeterminate"
    print("SELF-TEST PASS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        from alpaca_readonly import AlpacaReadOnly
        client = AlpacaReadOnly.from_env()
    except Exception as exc:  # noqa: BLE001  # allow-silent: written as a producer_failed verdict
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
             "population": "ml_entry_eq pool ticker audit: NEVER MEASURED", "note": f"no Alpaca client: {type(exc).__name__}: {exc}"}
        (out / "verdict.json").write_text(json.dumps(v, indent=2) + "\n")
        return 0
    recs, failed = [], []
    for s in AUDIT + CONTROL:
        try:
            d = client.bars([s], "1Day", f"{DEV[0]}T00:00:00Z", f"{TRAIN[1]}T00:00:00Z").get(s, [])
            h = client.bars([s], "1Hour", f"{TRAIN[0]}T00:00:00Z", f"{TRAIN[1]}T00:00:00Z").get(s, [])
            recs.append(audit_symbol(s, d, h))
            print(json.dumps({k: recs[-1][k] for k in ("symbol", "dev_daily_bars", "train_hourly_bars", "train_runs")}), flush=True)
        except Exception as exc:  # noqa: BLE001  # allow-silent: the symbol is listed as unread and the verdict is indeterminate
            failed.append(s)
            print(f"{s}: {type(exc).__name__}: {exc}", file=sys.stderr)
    v = grade(recs, [f for f in failed if f in AUDIT])
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str, allow_nan=False) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
