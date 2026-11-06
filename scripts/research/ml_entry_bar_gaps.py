#!/usr/bin/env python3
# wiring: .github/workflows/ml-entry-retrain.yml (input mode=gaps); rows ML-ENTRY-RETRAIN-CADENCE
"""Where are the hourly bar holes in the ENTRY training klines, and does Binance's DAILY archive hold the hours the MONTHLY one lacks?

Tier 1 diagnostic (public Binance Vision archives only). Context: the 2026-11-06 grade run measured that the labelled table has no
decision rows on 2026-10-27 and 2026-10-28 for ANY symbol, so the retrain's training stops 2 days before its plan bound. A decision
needs 24 contiguous forward bars (``ml_decision_entry.label_symbol``), so a bar hole is the suspect. This script says which symbols
and which hours, and whether the daily archive has them.

  python3 scripts/research/ml_entry_bar_gaps.py --out DIR [--run-date YYYY-MM-DD] [--cache DIR] [--since YYYY-MM-DD]
  python3 scripts/research/ml_entry_bar_gaps.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_decision_entry as E  # noqa: E402
import ml_entry_retrain as R  # noqa: E402


def hourly_gaps(ts) -> list[dict]:
    """[{after, before, missing_hours}] for every step longer than 1 h in an hourly bar-open series."""
    import pandas as pd
    t = ts.reset_index(drop=True)
    d = t.diff()
    return [{"after": str(t[i - 1]), "before": str(t[i]), "missing_hours": int(d[i] / pd.Timedelta(hours=1)) - 1}
            for i in d[d > pd.Timedelta(hours=1)].index]


def _days(after: str, before: str) -> list[str]:
    import pandas as pd
    a, b = pd.Timestamp(after), pd.Timestamp(before)
    return sorted({(a + timedelta(hours=h)).strftime("%Y-%m-%d") for h in range(1, int((b - a) / pd.Timedelta(hours=1)))})


def run(a) -> int:
    import pandas as pd
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    run_date = date.fromisoformat(a.run_date) if a.run_date else datetime.now(timezone.utc).date()
    p = R.plan(run_date)
    syms = E.universe()
    rep = R.fetch_through(Path(a.cache), syms, p)
    since = pd.Timestamp(a.since, tz="UTC")
    per_sym, windows = {}, defaultdict(list)
    for s in syms:
        ts = pd.read_pickle(Path(a.cache) / f"{s}.pkl")["ts"]
        g = [x for x in hourly_gaps(ts[ts >= since]) if pd.Timestamp(x["before"]) >= since]
        per_sym[s] = g
        for x in g:
            windows[(x["after"], x["before"])].append(s)
    report = {"run_date": run_date.isoformat(), "since": a.since, "n_symbols": len(syms),
              "n_symbols_with_gaps": sum(1 for v in per_sym.values() if v),
              "latest_bar_by_symbol": {"min": min(v["last_bar"] for v in rep.values()), "max": max(v["last_bar"] for v in rep.values())},
              "gap_windows": [{"after": k[0], "before": k[1], "n_symbols": len(v), "symbols": sorted(v)[:8]}
                              for k, v in sorted(windows.items(), key=lambda kv: -len(kv[1]))]}
    # does the DAILY archive hold the hours the merged series lacks? (BTCUSDT, the first 6 distinct windows)
    checks = []
    for (after, before), v in list(sorted(windows.items(), key=lambda kv: -len(kv[1])))[:6]:
        sym = "BTCUSDT" if "BTCUSDT" in v else sorted(v)[0]
        miss = pd.date_range(pd.Timestamp(after) + pd.Timedelta(hours=1), pd.Timestamp(before) - pd.Timedelta(hours=1), freq="h")
        got = set()
        for day in _days(after, before):
            try:
                df = R._fetch_zip(f"{R.DAILY}/{sym}/1h/{sym}-1h-{day}.zip")
            except Exception as exc:  # noqa: BLE001  # allow-silent: recorded below as the daily file's state
                checks.append({"symbol": sym, "day": day, "daily_file": f"error {type(exc).__name__}"})
                continue
            if df is None:
                checks.append({"symbol": sym, "day": day, "daily_file": "404 absent"})
                continue
            tt = pd.to_datetime(pd.to_numeric(df["open_time"], errors="coerce").dropna().astype("int64"), unit="ms", utc=True)
            got |= set(tt)
            checks.append({"symbol": sym, "day": day, "daily_file": f"present, {len(tt)} bars"})
        report.setdefault("daily_covers", []).append(
            {"symbol": sym, "gap": [after, before], "missing_hours": len(miss), "daily_archive_has": int(sum(1 for m in miss if m in got))})
    report["daily_file_checks"] = checks
    monthly = R._fetch_zip(f"{E._BASE}/BTCUSDT/1h/BTCUSDT-1h-{p['last_complete_month']}.zip")
    if monthly is not None:
        mt = pd.to_datetime(pd.to_numeric(monthly["open_time"], errors="coerce").dropna().astype("int64"), unit="ms", utc=True)
        report["monthly_btc"] = {"month": p["last_complete_month"], "bars": int(len(mt)), "first": str(mt.min()), "last": str(mt.max()),
                                 "internal_gaps": hourly_gaps(mt.reset_index(drop=True))}
    else:
        report["monthly_btc"] = {"month": p["last_complete_month"], "state": "404 absent"}
    (out / "gaps_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(json.dumps({k: report[k] for k in ("n_symbols_with_gaps", "gap_windows", "daily_covers", "monthly_btc")}, indent=1, default=str)[:6000],
          flush=True)
    return 0


def _self_test() -> None:
    import pandas as pd
    t = pd.Series(pd.date_range("2026-10-27", periods=6, freq="h", tz="UTC")).drop([2, 3])
    g = hourly_gaps(t)
    assert g == [{"after": "2026-10-27 01:00:00+00:00", "before": "2026-10-27 04:00:00+00:00", "missing_hours": 2}], g
    assert hourly_gaps(pd.Series(pd.date_range("2026-10-27", periods=4, freq="h", tz="UTC"))) == []
    assert _days("2026-10-27 22:00:00+00:00", "2026-10-28 03:00:00+00:00") == ["2026-10-27", "2026-10-28"]
    print("ml_entry_bar_gaps self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/ml_entry_gaps_out")
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--run-date", default="")
    ap.add_argument("--since", default="2026-09-15")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
