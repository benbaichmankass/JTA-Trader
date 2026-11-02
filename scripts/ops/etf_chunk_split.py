#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml (chunk loop: split the series finished THIS run out of the runner store)
"""Move the series finished this run out of the runner's working store into a chunk directory.

The chunk loop fetches a few dozen series, then (1) hands the FINISHED ones to the lake publisher and (2) syncs a tail cache to the
trainer. The working store also holds the pulled tail partitions of series NOT yet reached, and those must stay put (a refresh that finds
no local files would re-fetch the whole history), so the finished ones are MOVED into ``chunk/`` and everything else is left alone.

    python3 scripts/ops/etf_chunk_split.py --store store --chunk chunk --since 2026-11-01T12:00:00Z

``chunk/`` receives <SYM>/<tf>/ for every manifest series whose ``fetched_at`` >= ``--since``, plus copies of MANIFEST.json and (if present)
corporate_actions.csv. Prints the number of series moved.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


def split(store: Path, chunk: Path, since: str) -> int:
    man = json.loads((store / "MANIFEST.json").read_text())
    moved = 0
    for key, rec in (man.get("series") or {}).items():
        if (rec.get("fetched_at") or "") < since:
            continue
        sym, tf = key.split("/", 1)
        src = store / sym / tf
        if not src.is_dir():
            continue
        dst = chunk / sym / tf
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
        moved += 1
    chunk.mkdir(parents=True, exist_ok=True)
    shutil.copy2(store / "MANIFEST.json", chunk / "MANIFEST.json")
    if (store / "corporate_actions.csv").exists():
        shutil.copy2(store / "corporate_actions.csv", chunk / "corporate_actions.csv")
    return moved


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default="store")
    ap.add_argument("--chunk", default="chunk")
    ap.add_argument("--since", required=True)
    a = ap.parse_args(argv)
    n = split(Path(a.store), Path(a.chunk), a.since)
    print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
