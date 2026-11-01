#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml and options-snapshot-capture.yml (publish step; inert until repo variable MARKET_LAKE_HF_REPO is set)
"""Publish a pipeline's store folder to the market-data lake (a Hugging Face DATASET repo): the lake is the store, the trainer disk is a cache.

Add/replace only (never deletes remote files). HF de-duplicates by content hash, so re-sending an unchanged year file moves no bytes;
only the files a run touched (current/previous-year parquet + MANIFEST.json) actually upload. Layout under the repo is
``<prefix>/<same relative path as the local store>``, e.g. ``equities/bars/SPY/5m/2026.parquet`` and ``equities/bars/MANIFEST.json``.

The token is read from HF_TOKEN in the environment only. Contract with lane MARKET-DATA-LAKE: repo id, ``--prefix`` and the manifest are theirs
to define; this script is parameterised so changing them is a repository-variable edit, not code.

    HF_TOKEN=... python3 scripts/ops/publish_to_hf_lake.py --src store --repo <owner>/<dataset> --prefix equities/bars
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional


def publish(api: Any, src: Path, repo: str, prefix: str, message: str) -> int:
    files = [p for p in src.rglob("*") if p.is_file() and not p.name.endswith(".tmp")]
    if not files:
        print("nothing to publish")
        return 0
    api.upload_folder(folder_path=str(src), path_in_repo=prefix.strip("/"), repo_id=repo, repo_type="dataset",
                      commit_message=message, ignore_patterns=["*.tmp", "verify*.md", "probe.json"])
    print(f"published {len(files)} local file(s) from {src} to dataset {repo}:{prefix}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--repo", required=True, help="HF dataset repo id, e.g. owner/name")
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--message", default="pipeline publish")
    a = ap.parse_args(argv)
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        print("HF_TOKEN not set", file=sys.stderr)
        return 2
    from huggingface_hub import HfApi
    return publish(HfApi(token=tok), Path(a.src), a.repo, a.prefix, a.message)


if __name__ == "__main__":
    raise SystemExit(main())
