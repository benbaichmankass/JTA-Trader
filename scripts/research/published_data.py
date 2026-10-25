#!/usr/bin/env python3
# wiring: .github/workflows/research-script-run.yml (fetch step), scripts/research/kaggle_run.py + kaggle_unit/kernel_main.py (Kaggle mount)
"""ML-DATA-OFF-TRAINER (2026-10-13): make a unit's PUBLISHED dataset available to its run, off the trainer.

A unit that declares ``routing.published_data: metis-market-data`` reads its shards from the private Kaggle dataset the
exporter (``.github/workflows/ml-data-export-kaggle.yml``) maintains. On a GitHub runner this module downloads it,
re-hashes every file against MANIFEST.json, checks the unit's own dataset paths are in the allowlist, and exports
``ML_DATA_ROOT`` (the directory that contains ``datasets-out/``) for the NEXT step -- the unit's command, which runs
WITHOUT the Kaggle token (the token is in this step's environment only).

It also records, per dataset path the unit reads, the shard's last_ts and stale_days (``published-data.json`` beside the
run outputs): a result computed on a shard that ended months ago must say so, because the nightly shard is NOT
necessarily current (2026-10-13: BTC 15m ended 2026-02-01, SOL 15m 2023-08-12).

Tier-1 tooling. The token never leaves the environment of the step that calls ``fetch``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.research import market_data_export as mde  # noqa: E402
from scripts.research import compute_router as cr  # noqa: E402


def load_unit(unit: str, queue_dir: Optional[Path] = None) -> Dict[str, Any]:
    import yaml  # noqa: PLC0415
    p = (queue_dir or _REPO / "research" / "queue") / f"{unit}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def shard_facts(manifest_root: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Freshness of exactly the shards this unit reads, from the verified MANIFEST."""
    mpath = next(iter(sorted(manifest_root.rglob("MANIFEST.json"))), None)
    man = json.loads(mpath.read_text(encoding="utf-8")) if mpath else {"files": []}
    by_path = {f["path"]: f for f in man["files"]}
    withheld = {w["path"]: w.get("why") for w in man.get("withheld", [])}
    out = {}
    for p in cr.unit_dataset_paths(entry):
        f = by_path.get(p.lstrip("/"))
        out[p] = ({"rows": f.get("rows"), "first_ts": f.get("first_ts"), "last_ts": f.get("last_ts"),
                   "stale_days_at_export": f.get("stale_days")} if f else
                  ({"missing": True, "withheld": withheld[p.lstrip("/")]} if p.lstrip("/") in withheld else {"missing": True}))
    return {"manifest_generated_at": man.get("generated_at"), "shards": out}


def download_dataset(api: Any, user: str, slug: str, dest: Path) -> str:
    """Download + unzip the private dataset. Returns "" on success, else a scrubbed reason.

    First the CLI; if it fails (2026-10-14: the kaggle>=2.0 CLI answered 404 on DownloadDataset for a dataset the kernel
    mounts fine and `datasets status` reads), the python API, then the same call pinned to the latest version number."""
    ref = f"{user}/{slug}"
    notes = []

    def done() -> bool:
        return any(dest.rglob("MANIFEST.json"))

    r = subprocess.run(["kaggle", "datasets", "download", "-d", ref, "-p", str(dest), "--unzip", "-q"],
                       capture_output=True, text=True)
    if r.returncode == 0 and done():
        return ""
    notes.append("cli: " + (r.stderr or r.stdout)[-200:])
    try:
        api.dataset_download_files(ref, path=str(dest), unzip=True, quiet=True)
        if done():
            return ""
        notes.append("api: returned but no MANIFEST.json")
    except Exception as exc:  # allow-silent: the reason is appended to `notes` and returned to the caller, which prints it
        notes.append(f"api: {type(exc).__name__}: {str(exc)[-200:]}")
    try:
        ver = None
        owner = user
        for d in api.dataset_list(user=user, search=slug):
            if str(getattr(d, "ref", "")).endswith("/" + slug):
                owner = str(d.ref).split("/")[0]  # the owner slug as the listing spells it
                ver = getattr(d, "current_version_number", None) or getattr(d, "currentVersionNumber", None)
        notes.append(f"latest version: {ver}; owner slug same as token user: {owner == user}")
        if ver:
            # the dataset string is owner/slug/<version>; the CLI has no --version flag
            api.dataset_download_files(f"{owner}/{slug}/{ver}", path=str(dest), unzip=True, quiet=True)
            if done():
                return ""
            notes.append("api@version: returned but no MANIFEST.json")
    except Exception as exc:  # allow-silent: the reason is appended to `notes` and returned to the caller, which prints it
        notes.append(f"list: {type(exc).__name__}: {str(exc)[-200:]}")
    return " | ".join(notes).replace(user, "<user>")


def fetch(unit: str, dest: Path, *, out_dir: Optional[Path] = None, github_env: Optional[str] = None,
          queue_dir: Optional[Path] = None) -> int:
    entry = load_unit(unit, queue_dir)
    name = (entry.get("routing") or {}).get("published_data")
    if not name:
        print(f"{unit}: no routing.published_data -- nothing to fetch")
        return 0
    cfg = cr.load_config()
    problem = cr.published_problem(entry, cfg)
    if problem:
        print(f"REFUSED: {problem}", file=sys.stderr)
        return 3
    if not os.environ.get("KAGGLE_API_TOKEN"):
        print("REFUSED: KAGGLE_API_TOKEN is not set for this step -- cannot read the private dataset", file=sys.stderr)
        return 4
    slug = cfg["published_data"][name]["kaggle_dataset"]
    from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: PLC0415
    api = KaggleApi()
    api.authenticate()
    user = api.config_values.get("username", "")
    if not user:
        print("REFUSED: token did not resolve to a Kaggle user", file=sys.stderr)
        return 4
    print(f"::add-mask::{user}")
    dest.mkdir(parents=True, exist_ok=True)
    err = download_dataset(api, user, slug, dest)
    if err:
        print("download failed: " + err, file=sys.stderr)
        return 5
    v = mde.verify(dest)
    print("verify:", json.dumps({k: v[k] for k in ("ok", "files_ok", "stale_shards")} | {"bad": len(v.get("files_bad", []))}))
    if not v["ok"]:
        print("REFUSED: published copy does not match its MANIFEST", file=sys.stderr)
        return 6
    base = next(iter(sorted(dest.rglob("MANIFEST.json")))).parent
    facts = shard_facts(base, entry)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "published-data.json").write_text(json.dumps({"dataset": name, **facts}, indent=1) + "\n", encoding="utf-8")
    missing = [p for p, f in facts["shards"].items() if f.get("missing")]
    if missing:
        print(f"REFUSED: unit reads shard(s) absent from the published dataset: {missing}", file=sys.stderr)
        return 7
    for p, f in facts["shards"].items():
        print(f"shard {p}: last_ts={f.get('last_ts')} stale_days_at_export={f.get('stale_days_at_export')}")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"ML_DATA_ROOT={base}\n")
    print(f"ML_DATA_ROOT={base}")
    return 0


def _self_test() -> int:
    import tempfile
    entry = {"routing": {"published_data": "metis-market-data"},
             "ml_bakeoff": {"dataset": {"path": "datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl"}}}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, stage = td / "s", td / "o"
        d = src / "market_features/BTCUSDT/15m/v002"
        d.mkdir(parents=True)
        (d / "data.jsonl").write_text('{"ts":"2026-02-01T00:00:00Z","log_return":0.1}\n')
        (d / "metadata.json").write_text("{}")
        mde.build(src, stage, username="u")
        f = shard_facts(stage, entry)
        s = f["shards"]["datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl"]
        assert s["last_ts"] == "2026-02-01T00:00:00Z" and s["stale_days_at_export"] > 0, s
        missing = shard_facts(stage, {"ml_bakeoff": {"dataset": {"path": "datasets-out/market_features/SOLUSDT/15m/v002/data.jsonl"}}})
        assert missing["shards"]["datasets-out/market_features/SOLUSDT/15m/v002/data.jsonl"] == {"missing": True}
    print("published_data self-test OK")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("self-test")
    f = sub.add_parser("fetch")
    f.add_argument("--unit", required=True)
    f.add_argument("--dest", required=True)
    f.add_argument("--run-id", default="")
    f.add_argument("--github-env", default=os.environ.get("GITHUB_ENV", ""))
    d = sub.add_parser("download")
    d.add_argument("--dataset", required=True, help="dataset slug (owner = the token's user)")
    d.add_argument("--dest", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "download":
        from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: PLC0415
        api = KaggleApi()
        api.authenticate()
        user = api.config_values.get("username", "")
        if not user:
            print("token did not resolve to a Kaggle user", file=sys.stderr)
            return 4
        print(f"::add-mask::{user}")
        Path(a.dest).mkdir(parents=True, exist_ok=True)
        err = download_dataset(api, user, a.dataset, Path(a.dest))
        print("download failed: " + err if err else "download ok", file=sys.stderr if err else sys.stdout)
        return 5 if err else 0
    if a.cmd == "self-test":
        return _self_test()
    if a.cmd == "fetch":
        out = _REPO / "comms" / "research" / a.unit / a.run_id if a.run_id else None
        return fetch(a.unit, Path(a.dest), out_dir=out, github_env=a.github_env or None)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
