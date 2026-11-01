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


#: Private-storage allowance per plan, from https://huggingface.co/docs/hub/storage-limits ("Storage plans", read
#: 2026-11-01): free user 100 GB, PRO 1 TB (+ pay-as-you-go). The PLAN is measured from whoami (isPro); the USED
#: bytes are measured per private repo (usedStorage). The allowance itself is not exposed by the API.
PLAN_PRIVATE_BYTES = {"free": 100 * 10 ** 9, "pro": 1000 * 10 ** 9}


def measure_storage(api, who: Dict) -> Dict:
    plan = "pro" if who.get("isPro") else "free"
    user = who.get("name")
    used, repos, errs = 0, [], 0
    for kind, lister, info in (("model", api.list_models, api.model_info), ("dataset", api.list_datasets, api.dataset_info),
                               ("space", api.list_spaces, api.space_info)):
        try:
            for r in lister(author=user, expand=["private"]):
                if not getattr(r, "private", False):
                    continue
                try:
                    u = int(getattr(info(r.id, expand=["usedStorage"]), "used_storage", 0) or 0)
                except Exception:
                    u, errs = 0, errs + 1
                used += u
                repos.append({"repo": r.id, "type": kind, "used_bytes": u})
        except Exception:
            errs += 1
    quota = PLAN_PRIVATE_BYTES[plan]
    return {"plan": plan, "private_allowance_bytes": quota, "allowance_source": "huggingface.co/docs/hub/storage-limits",
            "private_used_bytes": used, "private_headroom_bytes": quota - used, "private_repos": repos,
            "measure_errors": errs}


def decide_optional(headroom: int, cfg_path: Path) -> Dict:
    """Optional streams land WITHOUT asking when they fit: walk config crypto.um_perp.optional_streams in order and
    enable each whose MEASURED projected bytes fit in the headroom left after the core lake's projected bytes."""
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text())
    core = int((cfg.get("storage") or {}).get("core_projected_bytes") or 0)
    left = headroom - core
    enabled, deferred = [], []
    for st, spec in ((cfg.get("crypto") or {}).get("um_perp", {}).get("optional_streams") or {}).items():
        b = int(spec.get("projected_bytes") or 0)
        if b and b <= left:
            enabled.append(st)
            left -= b
        else:
            deferred.append({"stream": st, "projected_bytes": b})
    return {"core_projected_bytes": core, "enabled": enabled, "deferred": deferred, "headroom_after_bytes": left}


def cmd_preflight(a) -> int:
    """Measure the token: whoami role, then a REAL write -- create the private dataset (idempotent) and upload one
    small marker file. A read-only token fails here, before any capture job spends an hour. Never prints the token."""
    api = _api()
    who = api.whoami()
    role = ((who.get("auth") or {}).get("accessToken") or {}).get("role", "unknown")
    at = (who.get("auth") or {}).get("accessToken") or {}
    fg = at.get("fineGrained") or {}
    scoped = [{"entity": (sc.get("entity") or {}).get("name"), "type": (sc.get("entity") or {}).get("type"),
               "permissions": sc.get("permissions")} for sc in (fg.get("scoped") or [])]
    rec = {"user": who.get("name"), "token_role": role, "token_name": at.get("displayName"),
           "fine_grained_global": fg.get("global"), "fine_grained_scoped": scoped, "repo": a.repo,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "write_test": None}
    try:
        ensure_private_repo(api, a.repo)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"preflight_at": rec["at"], "role": role}, fh)
        api.upload_file(path_or_fileobj=fh.name, path_in_repo="health/preflight.json", repo_id=a.repo,
                        repo_type="dataset", commit_message="lake: preflight write test")
        rec["write_test"] = "ok"
    except SystemExit:
        raise
    except Exception as e:
        rec["write_test"] = f"failed: {str(e)[:200]}"
    try:
        rec["storage"] = measure_storage(api, who)
        rec["optional_streams"] = decide_optional(rec["storage"]["private_headroom_bytes"],
                                                  REPO_ROOT / "config" / "data_universe.yaml")
    except Exception as e:
        rec["storage"] = {"error": str(e)[:200]}
        rec["optional_streams"] = {"enabled": [], "error": "storage not measured"}
    print(json.dumps(rec))
    if a.github_output:
        with open(a.github_output, "a") as fh:
            fh.write("optional=" + ",".join(rec["optional_streams"].get("enabled") or []) + "\n")
    if a.record:
        Path(a.record).write_text(json.dumps(rec, indent=1))
    if rec["write_test"] != "ok":
        print(f"::error::HF token cannot write to {a.repo} (role {role}): {rec['write_test']}")
        return 2
    print(f"ok: token role {role}; wrote health/preflight.json to private {a.repo}")
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


def _key(e: Dict) -> str:
    return f"{e.get('asset_class')}/{e.get('market')}/{e.get('tf')}/{e.get('symbol')}"


def _aggregate(e: Dict) -> Dict:
    parts = e.get("partitions") or {}
    if not parts:
        return e
    ps = [p for p in parts.values() if (p.get("rows") or 0) > 0]
    e["n_partitions"] = len(parts)
    e["rows"] = sum(int(p.get("rows") or 0) for p in ps)
    e["first"] = min((p["first"] for p in ps if p.get("first")), default=None)
    e["last"] = max((p["last"] for p in ps if p.get("last")), default=None)
    e["bytes"] = sum(int(p.get("bytes") or 0) for p in ps)
    e["missing_bars"] = sum(int(p.get("missing_bars") or 0) for p in ps)
    e["expected_rows"] = sum(int(p.get("expected_rows") or 0) for p in ps)
    e["frozen_months"] = sorted(m for m, p in parts.items() if p.get("frozen"))
    e["dir"] = "/".join(str(next(iter(parts.values())).get("path", "")).split("/")[:-1])
    return e


def merge_manifests(base: Path, previous: Optional[Dict] = None) -> Dict:
    """Fold this run's shard manifests into the previous lake manifest. Partitioned series merge PER MONTH (a refresh
    that rebuilt one month replaces only that month); single-file series are replaced whole."""
    files: Dict[str, Dict] = {}
    superseded: set = set()
    for e in (previous or {}).get("files", []):
        files[_key(e)] = e
    for p in sorted((base / "_manifests").glob("*.json")):
        for e in json.loads(p.read_text()):
            k = _key(e)
            old = files.get(k)
            if old is not None and (e.get("partitions") is not None or old.get("partitions")):
                merged = dict(old)
                merged.update({kk: vv for kk, vv in e.items() if kk != "partitions"})
                parts = {**(old.get("partitions") or {}), **(e.get("partitions") or {})}
                # a yearly partition (YYYY) supersedes that year's monthly ones (YYYY-MM): compaction at year close
                for yk in [pk for pk in (e.get("partitions") or {}) if len(pk) == 4]:
                    for mk in [pk for pk in parts if pk.startswith(yk + "-")]:
                        sp = parts.pop(mk).get("path")
                        if sp:
                            superseded.add(sp)
                merged["partitions"] = parts
                files[k] = merged
            else:
                files[k] = e
    out = [_aggregate(e) for e in files.values()]
    live = {p.get("path") for e in out for p in (e.get("partitions") or {}).values()} | {e.get("path") for e in out}
    return {"superseded": sorted(superseded - live), "n_files": len({x for x in live if x}), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": "market-data-lake/v2", "files": sorted(out, key=lambda e: (
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
    if a.previous and Path(a.previous).exists():
        previous = json.loads(Path(a.previous).read_text())
    if not a.local:
        api = _api()
        if previous is None:
            try:
                from huggingface_hub import hf_hub_download
                previous = json.loads(Path(hf_hub_download(a.repo, "MANIFEST.json", repo_type="dataset",
                                                           token=api.token)).read_text())
            except Exception:
                previous = None  # first run: no manifest yet
    m = merge_manifests(base, previous)
    superseded = m.pop("superseded", [])
    (base / "MANIFEST.json").write_text(json.dumps(m, indent=1))
    if m.get("n_files", 0) > 80000:
        print(f"::warning::lake holds {m['n_files']} files; HF recommends < 100k per repo -- compaction needed")
    table = depth_table(m)
    (base / "DEPTH.md").write_text(table + "\n")
    (base / "README.md").write_text(README.format(generated_at=m["generated_at"], table=table))
    print(table)
    if api is not None:
        ensure_private_repo(api, a.repo)
        for attempt in range(6):
            try:
                ci = api.upload_folder(repo_id=a.repo, repo_type="dataset", folder_path=str(base),
                                       allow_patterns=["MANIFEST.json", "README.md", "DEPTH.md", "health/*.json"],
                                       commit_message="lake: MANIFEST + depth table")
                if superseded:
                    from huggingface_hub import CommitOperationDelete
                    try:
                        api.create_commit(repo_id=a.repo, repo_type="dataset",
                                          operations=[CommitOperationDelete(path_in_repo=x) for x in superseded],
                                          commit_message=f"lake: prune {len(superseded)} superseded partitions")
                        print(f"pruned {len(superseded)} superseded partition files")
                    except Exception as e:
                        print(f"::warning::prune failed (retried next run): {str(e)[:200]}")
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


def cmd_pull(a) -> int:
    """Download small control files (MANIFEST.json, health/latest.json) into --dir; a missing file is not an error
    (first run). Refresh jobs use the manifest to rebuild only what changed."""
    api = _api()
    from huggingface_hub import hf_hub_download
    Path(a.dir).mkdir(parents=True, exist_ok=True)
    for f in [x for x in a.files.split(",") if x]:
        try:
            src = hf_hub_download(a.repo, f, repo_type="dataset", token=api.token)
            dst = Path(a.dir) / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(Path(src).read_bytes())
            print(f"pulled {f}")
        except Exception as e:
            print(f"absent {f}: {str(e)[:120]}")
    return 0


def cmd_depth(a) -> int:
    p = Path(a.dir) / "MANIFEST.json"
    m = json.loads(p.read_text()) if p.exists() else merge_manifests(Path(a.dir))
    print(depth_table(m))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["preflight", "upload", "manifest", "depth", "pull"])
    ap.add_argument("--files", default="MANIFEST.json,health/latest.json")
    ap.add_argument("--repo", default=_repo_from_config())
    ap.add_argument("--dir", default="lake")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--local", action="store_true", help="manifest: merge + render only, no HF read/write")
    ap.add_argument("--previous", default="", help="manifest: a previous MANIFEST.json on disk (else fetched from HF)")
    ap.add_argument("--record", default="", help="preflight: write the measured role/write-test JSON here")
    ap.add_argument("--github-output", default="", help="preflight: append optional=<streams> to this file")
    a = ap.parse_args(argv)
    return {"preflight": cmd_preflight, "upload": cmd_upload, "manifest": cmd_manifest, "depth": cmd_depth,
            "pull": cmd_pull}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
