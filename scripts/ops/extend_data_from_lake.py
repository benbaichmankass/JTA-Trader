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
    must match the file's close (median relative difference <= --tol, default
    2e-3, at least --min-overlap bars). The lake is rebuilt from yfinance and may
    be dividend-adjusted, so two different price bases would splice into one
    series. A failing file is REPORTED and left untouched, never forced.
  * report-only default: ``--apply`` is required to write.

    python3 scripts/ops/extend_data_from_lake.py --data-dir data \
        --lake datasets-out/market_raw [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

# lake symbol -> data/ file stem. Micro symbols map to the proxy's own name.
NAME_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "GLD": "GLD", "TLT": "TLT", "IWM": "IWM",
    "SLV": "SLV", "IEF": "IEF", "TQQQ": "TQQQ", "QLD": "QLD", "SPYM": "SPYM",
    "IAUM": "IAUM", "SPLG": "SPLG",
    "MGC": "GC_F", "MHG": "HG_F", "MES": "ES_F",
}
_BASE = ["timestamp", "open", "high", "low", "close", "volume"]


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


def plan_one(name: str, csv_path: Path, lake_rows: list[dict], tol: float, min_overlap: int):
    """Return (state, detail, new_lines|None). Never raises on a data problem."""
    header, rows = read_csv_rows(csv_path)
    if header != _BASE:
        return "refused_columns", f"header {header} is not {_BASE}", None
    if not rows:
        return "refused_empty", "file has no rows", None
    last_day = _day(rows[-1][0])
    by_day = {_day(r["ts"]): r for r in lake_rows}
    diffs = []
    for r in rows[-400:]:
        lr = by_day.get(_day(r[0]))
        if lr is not None and float(r[4]) != 0:
            diffs.append(abs(float(lr["close"]) - float(r[4])) / abs(float(r[4])))
    if len(diffs) < min_overlap:
        return "refused_no_overlap", f"{len(diffs)} overlapping bars < {min_overlap}; basis cannot be verified", None
    med = statistics.median(diffs)
    if med > tol:
        return "refused_basis_mismatch", f"median close diff {med:.5f} > tol {tol} over {len(diffs)} bars", None
    sample = rows[-1][0]
    sep = "T" if "T" in sample else " "
    tz = "Z" if sample.endswith("Z") else (sample[-6:] if len(sample) > 6 and sample[-6] in "+-" else "")

    def fmt(day: str) -> str:
        return f"{day}{sep}00:00:00{tz}"

    add = []
    for d in sorted(by_day):
        if d > last_day:
            r = by_day[d]
            add.append(",".join([fmt(d), repr(float(r["open"])), repr(float(r["high"])),
                                 repr(float(r["low"])), repr(float(r["close"])), repr(float(r["volume"]))]))
    if not add:
        return "current", f"no lake bars after {last_day}", None
    return "extend", f"{len(add)} bars {last_day} -> {add[-1][:10]}; basis median diff {med:.5f} over {len(diffs)} bars", add


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--lake", default="datasets-out/market_raw")
    ap.add_argument("--version", default="v002")
    ap.add_argument("--tol", type=float, default=2e-3)
    ap.add_argument("--min-overlap", type=int, default=20)
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
            state, detail, add = plan_one(stem, csv_path, read_lake(src), args.tol, args.min_overlap)
        except Exception as exc:  # noqa: BLE001 - one bad file must not block the others
            print(f"{lake_sym}->{csv_path.name}: FAILED {exc}", file=sys.stderr)
            rc = 1
            continue
        print(f"{lake_sym}->{csv_path.name}: {state}: {detail}")
        if state == "extend" and args.apply:
            before = csv_path.read_text()
            tmp = csv_path.with_suffix(".csv.tmp")
            tmp.write_text(before if before.endswith("\n") else before + "\n")
            with open(tmp, "a") as fh:
                fh.write("\n".join(add) + "\n")
            if tmp.stat().st_size < len(before.encode()):
                tmp.unlink()
                raise RuntimeError("refusing a shrinking write")
            os.replace(tmp, csv_path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
