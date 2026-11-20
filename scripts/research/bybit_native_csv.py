#!/usr/bin/env python3
"""Build a leg's BYBIT-native candle CSV from the trainer's resident Bybit linear files, open-stamped to a timeframe.

WHY (VENUE-GAP-20261120, manager 2026-11-20 03:52Z). Stage-0 evidence was built on Binance-vision USD-M candles; the
fleet measurement (comms/research/VENUE-GAP-20261120/record.json) found the same argv on the trainer's Bybit linear
bars earns a trade-weighted 0.0185 R/trade less (21 legs). New crypto Stage-0 units for legs that trade on Bybit use
the Bybit files as primary corpus. Most harness CLIs and ``exit_lever_ablation.py`` already take ``--data-csv``; this
script is the first command of such a unit: it writes the CSV, the next command reads it.

Resolution is ``m20_fleet_exit_sweep.resolve_data`` (finest file <= the timeframe) and aggregation is
``backtest_data_source.resample_open_stamped`` (label/closed left: the native exchange grid). A same-grain file is
copied unchanged. Writes ``<out-csv>`` plus a provenance JSON (source file, venue, span, bars; ``--provenance``, default beside the CSV).
Exit 2 and no CSV when no Bybit file covers the symbol: the next command then fails loudly on the missing path.

Research only (Tier 1): reads ``--data-dir``, writes ``--out-csv``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def build(symbol: str, timeframe: str, data_dir: Path, out_csv: Path, since: str | None = None,
          provenance: Path | None = None) -> dict[str, Any]:
    import pandas as pd
    from m20_fleet_exit_sweep import resolve_data

    from scripts.ops.backtest_data_source import resample_open_stamped
    path, proxy, resample = resolve_data(symbol, timeframe, data_dir)
    if not path:
        return {"ok": False, "why": f"no Bybit file for {symbol} at or below {timeframe} under {data_dir}"}
    d = pd.read_csv(path)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp")
    if since:
        d = d[d["timestamp"] >= pd.Timestamp(since, tz="UTC")]
    d = resample_open_stamped(d, timeframe if resample else None)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(out_csv, index=False)
    prov = {"ok": True, "symbol": symbol, "timeframe": timeframe, "source_file": Path(path).name,
            "venue": "bybit_linear (trainer data/, refreshed by deploy/trainer/ict-candle-refresh)",
            "proxy": bool(proxy), "resampled_from_finer": bool(resample), "grid": "open-stamped (label/closed left)",
            "bars": len(d), "first": str(d["timestamp"].min()) if len(d) else None,
            "last": str(d["timestamp"].max()) if len(d) else None, "out_csv": str(out_csv)}
    pp = Path(provenance) if provenance else Path(str(out_csv) + ".provenance.json")
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(json.dumps(prov, indent=1) + "\n")
    return prov


def _self_test() -> int:
    import tempfile

    import pandas as pd
    fails = []

    def chk(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        ts = pd.date_range("2026-01-01", periods=36, freq="5min", tz="UTC")
        px = pd.Series(range(36), dtype=float) + 100
        pd.DataFrame({"timestamp": ts, "open": px, "high": px + 1, "low": px - 1, "close": px + .5,
                      "volume": 1.0}).to_csv(t / "SOLUSDT_5m.csv", index=False)
        p = build("SOLUSDT", "1h", t, t / "out" / "sol_1h.csv")
        out = pd.read_csv(t / "out" / "sol_1h.csv")
        chk("5m -> 1h gives 3 open-stamped bars", p["ok"] and len(out) == 3)
        chk("first bar stamped at its first sub-bar", str(pd.Timestamp(out.timestamp[0])) == str(ts[0]))
        chk("OHLCV aggregated", (out.open[0], out.high[0], out.low[0], out.close[0], out.volume[0]) == (100, 112, 99, 111.5, 12))
        chk("provenance written", json.loads((t / "out" / "sol_1h.csv.provenance.json").read_text())["bars"] == 3)
        p5 = build("SOLUSDT", "5m", t, t / "out" / "sol_5m.csv")
        chk("same grain copied unchanged", p5["ok"] and p5["bars"] == 36 and not p5["resampled_from_finer"])
        ps = build("SOLUSDT", "1h", t, t / "out" / "s.csv", since="2026-01-01 01:00")
        chk("--since trims before aggregation", ps["bars"] == 2)
        build("SOLUSDT", "1h", t, t / "out" / "q.csv", provenance=t / "o2" / "prov.json")
        chk("--provenance path honoured", (t / "o2" / "prov.json").exists())
        chk("missing symbol refused", not build("DOGEUSDT", "1h", t, t / "out" / "d.csv")["ok"]
            and not (t / "out" / "d.csv").exists())
    print("bybit_native_csv self-test:", "OK" if not fails else f"FAILED {fails}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--symbol")
    ap.add_argument("--timeframe")
    ap.add_argument("--data-dir", default="data", help="the trainer's resident Bybit files (default: ./data)")
    ap.add_argument("--out-csv")
    ap.add_argument("--since", default=None, help="drop source rows before this ISO time (optional)")
    ap.add_argument("--provenance", default=None,
                    help="where to write the provenance JSON (default <out-csv>.provenance.json); a unit points it at "
                         "{out_dir} and keeps the CSV itself out of the committed outputs")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.symbol and a.timeframe and a.out_csv):
        ap.error("--symbol, --timeframe and --out-csv are required")
    p = build(a.symbol, a.timeframe, Path(a.data_dir), Path(a.out_csv), a.since, a.provenance)
    print(json.dumps(p))
    return 0 if p["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
