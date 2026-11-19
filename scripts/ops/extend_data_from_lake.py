#!/usr/bin/env python3
# wiring: manual-only - dispatched through the trainer-vm-diag relay first as a dry run; wired into deploy/trainer/ict-candle-refresh.service only after the dry run shows which files pass the basis check.
"""Extend trainer ``data/<NAME>_1d.csv`` forward from the maintained lake.

PI-20261118-MANAYJZO-0002 (manager-approved split, 2026-11-18): the daily
``build_trainer_datasets.sh`` already owns ``datasets-out/market_raw/<SYM>/1d``
for 16 symbols, so ``data/``'s stale 1d files are extended from it rather than
by a second fetcher.

Rules (all enforced, none advisory):
  * extend-only: rows strictly after the file's last timestamp; never edits or
    drops a row; refuses a shrinking write; atomic replace.
  * NAME MAP carries the proxy, never the micro name: lake MGC/MHG/MES hold
    GC=F/HG=F/ES=F bars (see market_raw_to_csv.py), so they extend
    GC_F/HG_F/ES_F, never ``MGC_1d.csv``.
  * BASIS CHECK before any append: on the overlapping timestamps the lake close
    is compared with the file's close (median relative difference, at least
    --min-overlap bars). At or under --tol (default 2e-3) the lake is the same
    basis and rows are appended as they are (``extend``). Over it, the lake is a
    different price basis (it is rebuilt from yfinance and is usually
    dividend-adjusted), and the appended OHLC are RATIO-SPLICED: scaled by
    file_close/lake_close at the last common date, volume untouched
    (``splice``; manager decision 2026-11-18, no special cases per symbol).
    Every splice (a) writes ``<file>.splice.json`` (date, ratio, lake source and
    version; appended to on each splice) so a spliced file never looks native,
    (b) is re-checked: the return across the splice day must sit within
    --max-sigma standard deviations of the file's own daily returns, else the
    file is left untouched, and (c) is refused when the ratio is outside
    [0.8, 1.2] or the file has no common date with the lake.
  * report-only default: ``--apply`` is required to write.

    python3 scripts/ops/extend_data_from_lake.py --data-dir data \
        --lake datasets-out/market_raw [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# lake symbol -> data/ file stem. Micro symbols map to the proxy's own name.
NAME_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "GLD": "GLD", "TLT": "TLT", "IWM": "IWM",
    "SLV": "SLV", "IEF": "IEF", "TQQQ": "TQQQ", "QLD": "QLD",
    "IAUM": "IAUM",
    # SPDR renamed SPLG -> SPYM; the lake builds SPYM, the trainer file is still data/SPLG_1d.csv (and no
    # SPYM_1d.csv exists), so neither old key matched and SPLG froze at 2026-07-02. The basis check below
    # still decides extend vs splice (TRAINER-1D-STALE-ROSTERED, 2026-11-19).
    "SPYM": "SPLG",
    # never built before 2026-11-19 (TRAINER-1D-STALE-ROSTERED): GDX/SCHA/USO are rostered leg symbols.
    "GDX": "GDX", "SCHA": "SCHA", "USO": "USO", "DBC": "DBC", "DBA": "DBA", "UNG": "UNG",
    "MGC": "GC_F", "MHG": "HG_F", "MES": "ES_F",
}
_BASE = ["timestamp", "open", "high", "low", "close", "volume"]


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_TZ = re.compile(r"^\d{4}-\d{2}-\d{2}([T ])\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$")


def day_spelling(sample: str):
    """f(day 'YYYY-MM-DD') -> a timestamp spelled exactly like ``sample`` (the file's last row).

    Handles date-only, 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DDTHH:MM:SSZ' and '+HH:MM' spellings.
    Any other spelling raises: the tool refuses to guess (a wrong guess writes rows the
    canonical loaders silently drop). 2026-11-18 defect: a date-only sample '2026-07-07'
    was read as carrying a '-07-07' timezone suffix.
    """
    sample = sample.strip().strip('"')
    if _DATE_ONLY.match(sample):
        return lambda day: day
    m = _TIME_TZ.match(sample)
    if not m:
        raise ValueError(f"unrecognised timestamp spelling {sample!r}")
    sep, tz = m.group(1), m.group(2) or ""
    return lambda day: f"{day}{sep}00:00:00{tz}"


def _day(ts: str) -> str:
    return ts.strip().strip('"')[:10]


def read_lake(path: Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path) as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    return lines[0].split(","), [ln.split(",") for ln in lines[1:]]


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def plan_one(csv_path: Path, lake_rows: list[dict], tol: float, min_overlap: int,
             max_sigma: float = 4.0):
    """Return (state, detail, new_lines|None, splice|None). Never raises on a data problem."""
    header, rows = read_csv_rows(csv_path)
    if header != _BASE:
        return "refused_columns", f"header {header} is not {_BASE}", None, None
    if not rows:
        return "refused_empty", "file has no rows", None, None
    try:
        fmt = day_spelling(rows[-1][0])
    except ValueError as exc:
        return "refused_timestamp_spelling", str(exc), None, None
    last_day = _day(rows[-1][0])
    by_day = {_day(r["ts"]): r for r in lake_rows}
    diffs = []
    common = []
    for r in rows[-400:]:
        lr = by_day.get(_day(r[0]))
        if lr is not None and float(r[4]) != 0 and float(lr["close"]) != 0:
            diffs.append(abs(float(lr["close"]) - float(r[4])) / abs(float(r[4])))
            common.append((_day(r[0]), float(r[4]), float(lr["close"])))
    if len(diffs) < min_overlap:
        return ("refused_no_overlap",
                f"{len(diffs)} overlapping bars < {min_overlap}; basis cannot be verified", None, None)
    med = statistics.median(diffs)
    ratio, splice = 1.0, None
    if med > tol:
        cday, fclose, lclose = common[-1]
        ratio = fclose / lclose
        if not 0.8 <= ratio <= 1.2:
            return "refused_ratio_out_of_range", f"splice ratio {ratio:.4f} outside [0.8, 1.2]", None, None
        splice = {"splice_day": cday, "ratio": ratio, "median_close_diff_before": med,
                  "overlap_bars": len(diffs), "rule": "ratio = file_close/lake_close at the last common date; OHLC scaled, volume unchanged"}

    add, add_close = [], []
    for d in sorted(by_day):
        if d > last_day:
            r = by_day[d]
            o, h, lo, c = (repr(float(r[k]) * ratio) for k in ("open", "high", "low", "close"))
            add.append(",".join([fmt(d), o, h, lo, c, repr(float(r["volume"]))]))
            add_close.append(float(c))
    if not add:
        return "current", f"no lake bars after {last_day}", None, None
    if splice:
        file_closes = [float(r[4]) for r in rows[-400:]]
        rets = _returns(file_closes)
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        jump = add_close[0] / file_closes[-1] - 1
        splice.update(splice_return=jump, file_daily_return_sd=sd, max_sigma=max_sigma,
                      first_appended_day=add[0][:10], last_appended_day=add[-1][:10], bars_appended=len(add))
        if sd > 0 and abs(jump) > max_sigma * sd:
            return ("refused_splice_discontinuity",
                    f"return across splice {jump:+.4f} exceeds {max_sigma} x file sd {sd:.4f}", None, None)
        detail = (f"{len(add)} bars {last_day} -> {add[-1][:10]}; ratio {ratio:.5f}, splice return {jump:+.4f} "
                  f"(file sd {sd:.4f}), median diff before {med:.5f} over {len(diffs)} bars")
        return "splice", detail, add, splice
    return ("extend", f"{len(add)} bars {last_day} -> {add[-1][:10]}; basis median diff {med:.5f} over {len(diffs)} bars",
            add, None)


def write_sidecar(csv_path: Path, lake_src: Path, version: str, splice: dict) -> None:
    side = csv_path.with_name(csv_path.name + ".splice.json")
    hist = json.loads(side.read_text())["splices"] if side.exists() else []
    hist.append({**splice, "lake_source": str(lake_src), "lake_version": version,
                 "file": csv_path.name, "spliced_at": datetime.now(timezone.utc).isoformat()})
    tmp = side.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"splices": hist}, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, side)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--lake", default="datasets-out/market_raw")
    ap.add_argument("--version", default="v002")
    ap.add_argument("--tol", type=float, default=2e-3)
    ap.add_argument("--min-overlap", type=int, default=20)
    ap.add_argument("--max-sigma", type=float, default=4.0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    rc = 0
    for lake_sym, stem in NAME_MAP.items():
        csv_path = Path(args.data_dir) / f"{stem}_1d.csv"
        src = Path(args.lake) / lake_sym / "1d" / args.version / "data.jsonl"
        if not src.exists() or not csv_path.exists():
            print(f"{lake_sym}->{csv_path.name}: SKIP lake={src.exists()} csv={csv_path.exists()} (extends, never creates)")
            continue
        try:
            state, detail, add, splice = plan_one(csv_path, read_lake(src), args.tol, args.min_overlap, args.max_sigma)
        except Exception as exc:  # noqa: BLE001 - one bad file must not block the others
            print(f"{lake_sym}->{csv_path.name}: FAILED {exc}", file=sys.stderr)
            rc = 1
            continue
        print(f"{lake_sym}->{csv_path.name}: {state}: {detail}")
        if state in ("extend", "splice") and args.apply:
            before = csv_path.read_text()
            tmp = csv_path.with_suffix(".csv.tmp")
            tmp.write_text(before if before.endswith("\n") else before + "\n")
            with open(tmp, "a") as fh:
                fh.write("\n".join(add) + "\n")
            if tmp.stat().st_size < len(before.encode()):
                tmp.unlink()
                raise RuntimeError("refusing a shrinking write")
            os.replace(tmp, csv_path)
            if splice:
                write_sidecar(csv_path, src, args.version, splice)
    return rc


if __name__ == "__main__":
    sys.exit(main())
