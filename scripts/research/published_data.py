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
import re
import subprocess
import sys
import zipfile
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


def fetch_manifests(api: Any, user: str, spec: Dict[str, Any], dest: Path, name: str, *,
                    out_dir: Optional[Path] = None, github_env: Optional[str] = None) -> int:
    """`fetch: manifest_only` (the lake mirror metis-market-lake-pNNN): download ONLY each part's MANIFEST.json, never the shards.

    Nothing is re-hashed (there is no shard on disk to hash). FAILS CLOSED: if any part's manifest cannot be read the step refuses,
    because a partial read would silently undercount what the lake holds. Parts are found by listing the token user's datasets
    and keeping slugs that match ``<prefix>NNN`` exactly, so a probe or pilot dataset with the same stem is never counted."""
    prefix = spec["kaggle_dataset_prefix"]
    pat = re.compile("^" + re.escape(prefix) + r"\d{3}$")
    found: Dict[str, str] = {}
    # The lake parts are PRIVATE datasets. Kaggle's `user=` listing is the public view of a user's datasets, so it never
    # shows them (MEASURED 2026-11-09, run 42562200115: "0 part(s) listed"); `mine=True` lists the token owner's OWN datasets,
    # private included. Try `mine` first and fall back to the public listing, stopping at the first that lists any part.
    # Kaggle's `search=` is a word search, not a prefix match, so the prefix-scoped query can list nothing while the parts exist
    # (run 42572391629 listed 0 with mine=True). Last resort per listing: no search, every dataset, filtered by the exact pattern here.
    seen: Dict[str, int] = {}
    for kwargs in ({"mine": True}, {"user": user}):
        for search in (prefix, ""):
            n_seen = 0
            for page in range(1, 11):
                batch = list(api.dataset_list(search=search, page=page, **kwargs) or [])
                if not batch:
                    break
                n_seen += len(batch)
                for d in batch:
                    ref = str(getattr(d, "ref", ""))
                    if pat.match(ref.split("/")[-1]):
                        found[ref.split("/")[-1]] = ref
            seen[f"{next(iter(kwargs))}:{'prefix' if search else 'all'}"] = n_seen
            if found:
                break
        if found:
            break
    if not found:
        print(f"listing diagnostic (datasets seen per query, none matched {prefix}NNN): {seen}", file=sys.stderr)
    got: Dict[str, Any] = {}
    failed: Dict[str, str] = {}
    for slug, ref in sorted(found.items()):
        d = dest / slug
        d.mkdir(parents=True, exist_ok=True)
        try:
            api.dataset_download_file(ref, "MANIFEST.json", path=str(d), force=True, quiet=True)
        except Exception as exc:  # allow-silent: recorded in `failed`, which makes the step refuse below
            failed[slug] = f"{type(exc).__name__}: {str(exc)[-120:]}".replace(user, "<user>")
            continue
        z = d / "MANIFEST.json.zip"
        if z.is_file():
            with zipfile.ZipFile(z) as zf:
                zf.extract("MANIFEST.json", d)
        mp = d / "MANIFEST.json"
        try:
            man = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failed[slug] = f"unreadable manifest after download: {type(exc).__name__}"
            continue
        got[slug] = {"n_partitions": man.get("n_partitions"), "n_shards": len(man.get("files") or []),
                     "generated_at": man.get("generated_at"), "schema": man.get("schema")}
    facts = {"dataset": name, "fetch": "manifest_only", "parts": got, "failed": failed, "n_parts_found": len(found)}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "published-data.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf-8")
    if not found or failed:
        print(f"REFUSED: manifest-only fetch incomplete: {len(found)} part(s) listed, {len(got)} read, failed {sorted(failed)}", file=sys.stderr)
        return 5
    env = spec.get("env") or "LAKE_MANIFEST_ROOT"
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"{env}={dest}\n")
    print(f"{env}={dest}  ({len(got)} part manifests, {sum(v['n_partitions'] or 0 for v in got.values())} partitions)")
    return 0


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
    spec = cfg["published_data"][name]
    slug = spec.get("kaggle_dataset")
    from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: PLC0415
    api = KaggleApi()
    api.authenticate()
    user = api.config_values.get("username", "")
    if not user:
        print("REFUSED: token did not resolve to a Kaggle user", file=sys.stderr)
        return 4
    print(f"::add-mask::{user}")
    dest.mkdir(parents=True, exist_ok=True)
    if spec.get("fetch") == "manifest_only":
        return fetch_manifests(api, user, spec, dest, name, out_dir=out_dir, github_env=github_env)
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


def _self_test_manifest_only() -> int:
    import tempfile

    class _D:
        def __init__(self, ref: str) -> None:
            self.ref = ref

    class _Api:
        """Behaves like the real service: PRIVATE parts are visible only to the owner's own listing (`mine=True`); the public
        `user=` listing shows only public datasets (here the decoys). `public_parts` makes the public listing carry the parts too."""
        def __init__(self, bad: Optional[str] = None, empty: bool = False, mine_empty: bool = False, public_parts: bool = False, word_search: bool = False) -> None:
            self.word_search = word_search
            self.bad = bad
            self.empty = empty
            self.mine_empty = mine_empty
            self.public_parts = public_parts
            self.asked: list = []
            self.listed: list = []

        def dataset_list(self, user: str = "", search: str = "", page: int = 1, mine: bool = False):
            assert search in ("metis-market-lake-p", ""), search                        # prefix-scoped first, then the unscoped last resort
            self.listed.append(("mine" if mine else "user", user, page))
            decoys = [_D("u/metis-market-lake-filecount-probe"), _D("u/metis-market-lake-p0000")]
            parts = [_D("u/metis-market-lake-p000"), _D("u/metis-market-lake-p001")]
            if page > 1 or self.empty:
                return []
            if self.word_search and search:      # Kaggle's search is a word match: a prefix finds nothing, only the unscoped list shows the parts
                return []
            if mine:
                assert user == "", user                                                 # `mine` replaces the user filter, never combined with it
                return decoys if self.mine_empty else parts + decoys
            assert user == "u", user                                                    # the public listing must be scoped to the token user
            return parts + decoys if self.public_parts else decoys

        def dataset_download_file(self, ref: str, file_name: str, path: str = "", force: bool = False, quiet: bool = True) -> None:
            assert force is True and quiet is True, (force, quiet)   # a stale cached manifest must never be reused
            self.asked.append((ref, file_name))
            if self.bad and ref.endswith(self.bad):
                raise RuntimeError("404 for u")
            man = json.dumps({"schema": "metis-market-lake-pilot/v1", "generated_at": "2026-11-06T00:00:00+00:00",
                              "n_partitions": 10 if ref.endswith("p000") else 5, "files": [{"path": "a.tar"}, {"path": "b.tar"}]})
            if ref.endswith("p001"):    # Kaggle sometimes serves the single file zipped
                with zipfile.ZipFile(Path(path) / "MANIFEST.json.zip", "w") as zf:
                    zf.writestr("MANIFEST.json", man)
            else:
                (Path(path) / "MANIFEST.json").write_text(man)

    spec = {"kaggle_dataset_prefix": "metis-market-lake-p", "fetch": "manifest_only", "env": "LAKE_MANIFEST_ROOT"}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        env = td / "env"
        api = _Api()
        assert fetch_manifests(api, "u", spec, td / "d", "metis-market-lake", out_dir=td / "o", github_env=str(env)) == 0
        assert sorted(r for r, _ in api.asked) == ["u/metis-market-lake-p000", "u/metis-market-lake-p001"], api.asked
        assert all(f == "MANIFEST.json" for _, f in api.asked), "only the manifest may be downloaded"
        facts = json.loads((td / "o" / "published-data.json").read_text())
        assert facts["parts"]["metis-market-lake-p000"]["n_partitions"] == 10 and facts["parts"]["metis-market-lake-p001"]["n_partitions"] == 5
        assert facts["failed"] == {} and env.read_text().startswith("LAKE_MANIFEST_ROOT=")
        bad = _Api(bad="p001")                                   # one part unreadable -> the step refuses, never a partial read
        assert fetch_manifests(bad, "u", spec, td / "d2", "metis-market-lake", out_dir=td / "o2") == 5
        assert "metis-market-lake-p001" in json.loads((td / "o2" / "published-data.json").read_text())["failed"]

        assert fetch_manifests(_Api(empty=True), "u", spec, td / "d3", "metis-market-lake") == 5     # nothing listed is a refusal, not an empty lake
        assert api.listed[0][0] == "mine", api.listed                       # the owner's own listing is asked FIRST (the private parts live there)
        fb = _Api(mine_empty=True, public_parts=True)                       # fallback: nothing private listed, the public listing has the parts
        assert fetch_manifests(fb, "u", spec, td / "d4", "metis-market-lake") == 0, "the public listing is the fallback"
        kinds = [k for i, (k, _, _) in enumerate(fb.listed) if i == 0 or fb.listed[i - 1][0] != k]
        assert kinds == ["mine", "user"], fb.listed
        pub_only = _Api(mine_empty=True)                                    # THE 2026-11-09 FAILURE: private parts invisible to a public-only listing
        assert fetch_manifests(pub_only, "u", spec, td / "d5", "metis-market-lake") == 5, "a listing that cannot see the parts must refuse"
        ws = _Api(word_search=True)                                         # THE 2026-11-09 06:21Z FAILURE: mine=True + prefix search listed 0
        assert fetch_manifests(ws, "u", spec, td / "d6", "metis-market-lake") == 0, "the unscoped listing must find the parts"
        assert [x[0] for x in ws.listed][:2] == ["mine", "mine"], ws.listed  # prefix-scoped first, then unscoped, same (owner's) listing
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
    _self_test_manifest_only()
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
