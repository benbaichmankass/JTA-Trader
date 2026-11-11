#!/usr/bin/env python3
"""Print / JSON-emit the feature-catalog coverage diff (models and features missing from the catalog).

    python3 scripts/ops/feature_catalog_coverage.py [--json] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def build(root: Path = ROOT) -> dict:
    from src.runtime.feature_catalog_coverage import compute_coverage, load_catalog, load_disk_models

    catalog = load_catalog(root)
    disk, errors = load_disk_models(root)
    out = compute_coverage(catalog, disk)
    out.update({"catalog_generated": str(catalog.get("generated")), "read_errors": errors,
                "models_on_disk": [{k: m[k] for k in ("model_id", "stage", "path")} | {"n_features": len(m["features"])}
                                   for m in disk],
                "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = build()
    text = json.dumps(r, indent=2, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n")
    if a.json or a.out:
        if not a.out:
            print(text)
    else:
        print(f"models on disk {r['n_models_on_disk']} / in catalog {r['n_models_in_catalog']}")
        print("models missing from catalog:", r["models_missing_from_catalog"])
        for m, f in r["features_missing_per_model"].items():
            print(f"  {m}: {len(f)} missing: {f}")
        print(f"unused catalog inputs: {len(r['unused_catalog_inputs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
