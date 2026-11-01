#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (job kaggle-raw-tail: backfill + Sundays) -> private Kaggle dataset
"""RAW aggTrades (every aggregated trade, verbatim Binance archive zips) for the TRADED universe, trailing months, staged
for the private Kaggle dataset ``metis-aggtrades-tail`` -- the storage FALLBACK for a stream that does not fit the HF lake.

MEASURED 2026-11-01 (S3 listing): raw aggTrades are 1,154 GB zipped for all 1,056 perps and 129.8 GB for the 6 traded
perps; the trailing 3 months of the traded perps are 2.82 GB (12 months 17.4 GB). The HF lake keeps the FULL history as
1m order-flow bars (binance_vision_lake.py --stream aggTrades); this dataset keeps the raw ticks for the recent window,
where tick-level research (queue position, trade-size distributions, intrabar paths) needs them.

Files are copied byte-for-byte (sha256 checked against Binance's .CHECKSUM). MANIFEST.json lists every file. Kaggle
dataset versions are whole-dataset uploads, so the window is kept short; widening it is one config value
(config/data_universe.yaml crypto.um_perp.kaggle_raw_tail.months).

    python3 scripts/data_lake/kaggle_raw_tail.py --out stage --username <kaggle user>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_lake as bvl  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def wanted_keys(symbols: List[str], months: int, now: Optional[datetime] = None) -> List[str]:
    now = now or datetime.now(timezone.utc)
    keys: List[str] = []
    for sym in symbols:
        monthly = bvl.list_zips("{b}/monthly/aggTrades/{s}/", "um_perp", sym)
        keys += monthly[-months:]
        last_m = bvl._month_of(monthly[-1]) if monthly else ""
        keys += [k for k in bvl.list_zips("{b}/daily/aggTrades/{s}/", "um_perp", sym) if bvl._month_of(k) > last_m]
    return keys


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="stage")
    ap.add_argument("--username", required=True)
    ap.add_argument("--months", type=int, default=0)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((REPO / "config" / "data_universe.yaml").read_text())
    spec = cfg["crypto"]["um_perp"]["kaggle_raw_tail"]
    months = a.months or int(spec.get("months", 3))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = bvl.traded_symbols()
    files: List[Dict] = []
    errors: List[str] = []
    for key in wanted_keys(syms, months):
        # flat: `kaggle datasets version -r skip` ignores sub-directories; the Binance file name carries the symbol
        dst = out / key.rsplit("/", 1)[-1]
        try:
            sha = bvl._download_to_file(f"{bvl.FILES}/{key}", dst)
            try:
                want = bvl._get(f"{bvl.FILES}/{key}.CHECKSUM").decode().split()[0].strip().lower()
                chk = "ok" if want == sha else "MISMATCH"
            except Exception:
                chk = "no_checksum"
            if chk == "MISMATCH":
                dst.unlink()
                errors.append(f"{key}: sha256 mismatch (file dropped, retried next run)")
                continue
            files.append({"path": str(dst.relative_to(out)), "bytes": dst.stat().st_size, "sha256": sha, "checksum": chk})
        except Exception as ex:  # contained per file; the next run retries
            errors.append(f"{key}: {str(ex)[:150]}")
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbols": syms,
                "months": months, "source": "data.binance.vision futures/um aggTrades (verbatim zips)",
                "licence": "Binance ToU; private dataset only", "files": files, "errors": errors,
                "total_bytes": sum(f["bytes"] for f in files)}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": "metis aggtrades tail", "id": f"{a.username}/{spec.get('dataset', 'metis-aggtrades-tail')}",
        "licenses": [{"name": "other"}],
        "description": "PRIVATE. Raw Binance USD-M aggTrades (verbatim archive zips), traded symbols, trailing months. "
                       "Row MARKET-DATA-LAKE (JTA Trader). Binance ToU: never public."}, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"} | {"n_files": len(files)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
