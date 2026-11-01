#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (publish step; HF_TOKEN from Actions secrets, never printed)
"""Publish a built lake directory to the PRIVATE Hugging Face dataset, then (re)write MANIFEST.json + README.md.

Row MARKET-DATA-LAKE; design docs/data/market-data-lake.md.

    python3 scripts/data_lake/hf_publish.py preflight                      # token present? write scope? repo private?
    python3 scripts/data_lake/hf_publish.py upload   --dir lake --prefix crypto/um_perp/1h
    python3 scripts/data_lake/hf_publish.py manifest --dir lake            # merge _manifests/*.json into MANIFEST.json
    python3 scripts/data_lake/hf_publish.py depth    --dir lake            # print the depth table (markdown)

* The repo is created PRIVATE and the script REFUSES to upload to a repo that reports public (a public mirror of
  Binance / Yahoo data would breach their terms).
* Versioning: every upload is an HF commit; `manifest` also tags the commit `vYYYYMMDD-HHMM` so a training run can pin
  the exact data it read (`ml/datasets/lake.py --revision`).
* Uploads are add/replace only; nothing is deleted from the dataset by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPO = os.environ.get("LAKE_HF_REPO", "bentzbk/jta-market-lake")


def _repo_from_config() -> str:
    try:
        import yaml
        return (yaml.safe_load((REPO_ROOT / "config" / "data_universe.yaml").read_text())
                .get("storage", {}).get("hf_dataset") or DEFAULT_REPO)
    except Exception:
        return DEFAULT_REPO


def _api():
    from huggingface_hub import HfApi
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not tok:
        raise SystemExit("HF_TOKEN is not set (Actions secret HF_TOKEN, a WRITE-scoped token for the bentzbk account)")
    return HfApi(token=tok)


def ensure_private_repo(api, repo: str) -> None:
    from huggingface_hub import create_repo
    create_repo(repo, repo_type="dataset", private=True, exist_ok=True, token=api.token)
    info = api.dataset_info(repo)
    if not getattr(info, "private", False):
        raise SystemExit(f"REFUSING: {repo} reports PUBLIC; the lake holds no-open-licence data and must be private")


def cmd_preflight(a) -> int:
    api = _api()
    who = api.whoami()
    role = ((who.get("auth") or {}).get("accessToken") or {}).get("role", "unknown")
    print(json.dumps({"user": who.get("name"), "token_role": role, "repo": a.repo}))
    if role not in ("write", "fineGrained", "admin"):
        print(f"::error::HF token role is '{role}'; the lake needs a WRITE token")
        return 2
    ensure_private_repo(api, a.repo)
    print(f"ok: {a.repo} exists and is private")
    return 0


def cmd_upload(a) -> int:
    api = _api()
    ensure_private_repo(api, a.repo)
    base = Path(a.dir)
    src = base / a.prefix if a.prefix else base
    if not src.exists():
        print(f"nothing to upload under {src}")
        return 0
    patterns = ["*.parquet", "*.csv", "*.json"]
    for attempt in range(6):  # concurrent shard commits can race; retried, never halted
        try:
            api.upload_folder(repo_id=a.repo, repo_type="dataset", folder_path=str(src),
                              path_in_repo=a.prefix or None, allow_patterns=patterns,
                              commit_message=f"lake: {a.prefix or 'all'} ({a.note or 'market-data-lake'})")
            print(f"uploaded {src} -> {a.repo}/{a.prefix}")
            return 0
        except Exception as e:
            print(f"upload attempt {attempt + 1} failed: {str(e)[:300]}")
            time.sleep(min(120, 10 * 2 ** attempt))
    print("::error::upload failed after retries")
    return 1


def merge_manifests(base: Path, previous: Optional[Dict] = None) -> Dict:
    files: Dict[str, Dict] = {}
    if previous:
        for e in previous.get("files", []):
            files[e.get("path") or f"{e.get('asset_class')}/{e.get('market')}/{e.get('tf')}/{e.get('symbol')}"] = e
    for p in sorted((base / "_manifests").glob("*.json")):
        for e in json.loads(p.read_text()):
            key = e.get("path") or f"{e.get('asset_class')}/{e.get('market')}/{e.get('tf')}/{e.get('symbol')}"
            files[key] = e
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": "market-data-lake/v1", "files": sorted(files.values(), key=lambda e: (
                str(e.get("asset_class")), str(e.get("market")), str(e.get("tf")), str(e.get("symbol"))))}


def depth_table(manifest: Dict) -> str:
    groups: Dict[tuple, List[Dict]] = defaultdict(list)
    for e in manifest["files"]:
        groups[(e.get("asset_class"), e.get("market"), e.get("tf"))].append(e)
    lines = ["| asset class | market | tf | series ok / total | rows | earliest first bar | latest last bar | "
             "median span (days) | missing bars | bytes |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(groups, key=lambda t: tuple(str(x) for x in t)):
        es = groups[k]
        ok = [e for e in es if (e.get("rows") or 0) > 0]
        spans = sorted((datetime.fromisoformat(e["last"]) - datetime.fromisoformat(e["first"])).days
                       for e in ok if e.get("first") and e.get("last"))
        med = spans[len(spans) // 2] if spans else None
        lines.append("| {} | {} | {} | {} / {} | {:,} | {} | {} | {} | {:,} | {:,} |".format(
            k[0], k[1], k[2], len(ok), len(es), sum(int(e.get("rows") or 0) for e in es),
            min((e["first"] for e in ok if e.get("first")), default="—")[:10],
            max((e["last"] for e in ok if e.get("last")), default="—")[:10],
            med if med is not None else "—", sum(int(e.get("missing_bars") or 0) for e in ok),
            sum(int(e.get("bytes") or 0) for e in ok)))
    return "\n".join(lines)


README = """---
license: other
license_name: mixed-source-terms
pretty_name: JTA market data lake
viewer: false
---
# JTA market data lake (PRIVATE)

Market data only, for research and model training; not financial advice. Built by
`scripts/data_lake/*` in the JTA Trader repo (row MARKET-DATA-LAKE; design `docs/data/market-data-lake.md`).

Layout: `<asset_class>/<market>/<tf>/<SYMBOL>.parquet`, bars stamped at bar OPEN (UTC), no forward fill;
gaps are counted in `MANIFEST.json`, never patched. Universe snapshots: `universe/<asset>/<date>.csv`.

Source terms vary per file (`MANIFEST.json` -> `licence`): Binance ToU, Yahoo ToS and others carry no open
licence, so this dataset must stay private.

## Depth (generated {generated_at})

{table}
"""


def cmd_manifest(a) -> int:
    base = Path(a.dir)
    previous = None
    api = None
    if not a.local:
        api = _api()
        try:
            from huggingface_hub import hf_hub_download
            previous = json.loads(Path(hf_hub_download(a.repo, "MANIFEST.json", repo_type="dataset",
                                                       token=api.token)).read_text())
        except Exception:
            previous = None
    m = merge_manifests(base, previous)
    (base / "MANIFEST.json").write_text(json.dumps(m, indent=1))
    table = depth_table(m)
    (base / "DEPTH.md").write_text(table + "\n")
    (base / "README.md").write_text(README.format(generated_at=m["generated_at"], table=table))
    print(table)
    if api is not None:
        ensure_private_repo(api, a.repo)
        for attempt in range(6):
            try:
                ci = api.upload_folder(repo_id=a.repo, repo_type="dataset", folder_path=str(base),
                                       allow_patterns=["MANIFEST.json", "README.md", "DEPTH.md"],
                                       commit_message="lake: MANIFEST + depth table")
                tag = "v" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
                try:
                    api.create_tag(a.repo, tag=tag, repo_type="dataset", revision=getattr(ci, "oid", None))
                except Exception as e:
                    print(f"tag {tag} not created: {str(e)[:200]}")
                print(f"published MANIFEST ({len(m['files'])} files), tag {tag}")
                return 0
            except Exception as e:
                print(f"manifest upload attempt {attempt + 1} failed: {str(e)[:300]}")
                time.sleep(min(120, 10 * 2 ** attempt))
        return 1
    return 0


def cmd_depth(a) -> int:
    p = Path(a.dir) / "MANIFEST.json"
    m = json.loads(p.read_text()) if p.exists() else merge_manifests(Path(a.dir))
    print(depth_table(m))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["preflight", "upload", "manifest", "depth"])
    ap.add_argument("--repo", default=_repo_from_config())
    ap.add_argument("--dir", default="lake")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--local", action="store_true", help="manifest: merge + render only, no HF read/write")
    a = ap.parse_args(argv)
    return {"preflight": cmd_preflight, "upload": cmd_upload, "manifest": cmd_manifest, "depth": cmd_depth}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
