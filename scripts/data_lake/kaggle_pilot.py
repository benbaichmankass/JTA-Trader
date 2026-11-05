#!/usr/bin/env python3
# ruff: noqa: BLE001  (pilot measurement: failures are recorded in the output, never hidden)
# wiring: .github/workflows/hf-lake-kaggle-pilot.yml (stage / measure / verify; HF_TOKEN + KAGGLE_API_TOKEN from Actions secrets, never printed)
"""PILOT: can the FROZEN crypto 1m history of the HF lake live in a PRIVATE Kaggle dataset? (row HF-LAKE-STORAGE-403)

Operator decision 2026-11-05 ~14:51Z, verbatim: "Kaggle 1 GB pilot first (Rec.)". Existing Kaggle account only; nothing is
deleted from Hugging Face; this writes a ~1 GB private dataset ``metis-market-lake`` and a tiny private file-count probe.

    stage   --out DIR --target-gb 1.0 [--from-dir lake]  pick FROZEN partitions (closed months, never rewritten) from HF
                                                         (or from a local lake dir), tar them into shards + MANIFEST.json
    extra   --out DIR --from-dir lake --skip-names ...   a second, small shard set for the 2nd dataset version
    flat    --out DIR --n 120                            N small files at the TOP LEVEL for the file-count limit probe
    verify  --root DIR                                   re-hash every shard against MANIFEST.json, time the reads

Layout inside a shard: ``crypto/um_perp/1m/<SYMBOL>/<YYYY-MM>.parquet`` (the lake's own layout), so a reader that extracts a
shard sees exactly what ``ml/datasets/lake.py`` expects under LAKE_LOCAL_DIR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "crypto/um_perp/1m"
SHARD_BYTES = 250 * 10 ** 6


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_frozen_name(rel: str, now: datetime | None = None) -> bool:
    """A closed partition: YYYY-MM at least 2 full months old, or a closed year YYYY. The open and previous month are
    rewritten by the daily refresh, so they are never 'frozen'."""
    now = now or datetime.now(timezone.utc)
    stem = Path(rel).stem
    if len(stem) == 4 and stem.isdigit():
        return int(stem) < now.year
    if len(stem) == 7 and stem[4] == "-":
        y, m = int(stem[:4]), int(stem[5:])
        idx = y * 12 + (m - 1)
        return idx <= (now.year * 12 + now.month - 1) - 2
    return False


def list_hf_candidates(repo: str, token: str) -> list[dict]:
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    out = []
    for it in api.list_repo_tree(repo, path_in_repo=PREFIX, repo_type="dataset", recursive=True, expand=True):
        if it.__class__.__name__ != "RepoFile" or not it.path.endswith(".parquet"):
            continue
        size = int(getattr(getattr(it, "lfs", None), "size", None) or getattr(it, "size", 0) or 0)
        if is_frozen_name(it.path):
            out.append({"path": it.path, "bytes": size})
    return sorted(out, key=lambda e: e["path"])


def list_local_candidates(root: Path) -> list[dict]:
    out = []
    for p in sorted((root / PREFIX).rglob("*.parquet")):
        rel = p.relative_to(root).as_posix()
        if is_frozen_name(rel):
            out.append({"path": rel, "bytes": p.stat().st_size})
    return out


def pick(cands: list[dict], target_bytes: int, skip: set | None = None) -> list[dict]:
    """Deterministic, spread across symbols (round-robin by symbol) so the sample is not 1 symbol's whole history."""
    skip = skip or set()
    by_sym: dict[str, list[dict]] = {}
    for c in cands:
        if c["path"] in skip:
            continue
        by_sym.setdefault(c["path"].split("/")[-2], []).append(c)
    chosen, total, i = [], 0, 0
    syms = sorted(by_sym)
    while syms and total < target_bytes:
        s = syms[i % len(syms)]
        if by_sym[s]:
            c = by_sym[s].pop(0)
            chosen.append(c)
            total += c["bytes"]
        else:
            syms.remove(s)
            continue
        i += 1
    return chosen


def fetch(chosen: list[dict], dest: Path, repo: str, token: str, workers: int = 8) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import hf_hub_download
    t0 = time.time()

    def one(c: dict) -> None:
        lp = hf_hub_download(repo, c["path"], repo_type="dataset", token=token, local_dir=str(dest))
        c["got"] = os.path.getsize(lp)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, chosen))
    return {"files": len(chosen), "bytes": sum(c.get("got", 0) for c in chosen), "seconds": round(time.time() - t0, 1)}


def make_shards(src: Path, files: list[dict], out: Path, tag: str) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    shards, cur, cur_bytes, n = [], [], 0, 0

    def flush() -> None:
        nonlocal cur, cur_bytes, n
        if not cur:
            return
        name = f"{tag}-{n:03d}.tar"
        with tarfile.open(out / name, "w") as tf:  # parquet is already zstd-compressed: plain tar
            for c in cur:
                tf.add(src / c["path"], arcname=c["path"])
        shards.append({"path": name, "bytes": (out / name).stat().st_size, "sha256": sha256_file(out / name),
                       "n_partitions": len(cur), "member_bytes": sum(c.get("got") or c["bytes"] for c in cur),
                       "members": [c["path"] for c in cur]})
        cur, cur_bytes, n = [], 0, n + 1

    for c in sorted(files, key=lambda e: e["path"]):
        cur.append(c)
        cur_bytes += c.get("got") or c["bytes"]
        if cur_bytes >= SHARD_BYTES:
            flush()
    flush()
    return shards


def write_dataset_files(out: Path, username: str, shards: list[dict], note: str) -> None:
    man = {"schema": "metis-market-lake-pilot/v1", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": note, "prefix": PREFIX, "files": [{k: v for k, v in s.items() if k != "members"} for s in shards],
           "n_partitions": sum(s["n_partitions"] for s in shards)}
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": "metis-market-lake", "id": f"{username}/metis-market-lake",
        "licenses": [{"name": "other"}]}, indent=1))


def cmd_stage(a) -> int:
    out, work = Path(a.out), Path(a.out + "-work")
    target = int(a.target_gb * 10 ** 9)
    token = os.environ.get("HF_TOKEN", "")
    report: dict = {"source": None}
    if a.from_dir:
        cands = list_local_candidates(Path(a.from_dir))
        chosen = pick(cands, target)
        for c in chosen:
            c["got"] = c["bytes"]
        src = Path(a.from_dir)
        report["source"] = "local-dir"
    else:
        cands = list_hf_candidates(a.repo, token)
        chosen = pick(cands, target)
        report["fetch"] = fetch(chosen, work, a.repo, token)
        src = work
        report["source"] = "hf"
    report["frozen_candidates"] = {"files": len(cands), "bytes": sum(c["bytes"] for c in cands)}
    report["chosen"] = {"files": len(chosen), "bytes": sum(c.get("got") or c["bytes"] for c in chosen),
                        "symbols": len({c["path"].split("/")[-2] for c in chosen})}
    shards = make_shards(src, chosen, out, "crypto-um_perp-1m")
    write_dataset_files(out, a.username, shards, "pilot v1: frozen crypto 1m partitions, tar shards")
    (out.parent / (out.name + "-chosen.json")).write_text(json.dumps([c["path"] for c in chosen]))
    report["shards"] = {"n": len(shards), "bytes": sum(s["bytes"] for s in shards)}
    # the sharding arithmetic the operator asked for: what ~75-90 GB would need
    if report["frozen_candidates"]["files"]:
        avg = report["frozen_candidates"]["bytes"] / report["frozen_candidates"]["files"]
        report["projection"] = {"avg_partition_bytes": int(avg),
                                "shards_for_80GB_at_250MB": int(80e9 // SHARD_BYTES),
                                "partitions_for_80GB": int(80e9 // max(avg, 1))}
    print(json.dumps(report, indent=1))
    return 0


def cmd_extra(a) -> int:
    """A second dataset version: one more shard set (different partitions) added next to v1's shards."""
    out = Path(a.out)
    prev = set(json.loads(Path(a.prev_chosen).read_text())) if a.prev_chosen else set()
    if a.from_dir:
        cands = list_local_candidates(Path(a.from_dir))
        chosen = pick(cands, int(a.target_gb * 10 ** 9), skip=prev)
        for c in chosen:
            c["got"] = c["bytes"]
        src = Path(a.from_dir)
    else:
        token = os.environ.get("HF_TOKEN", "")
        chosen = pick(list_hf_candidates(a.repo, token), int(a.target_gb * 10 ** 9), skip=prev)
        fetch(chosen, Path(a.out + "-work"), a.repo, token)
        src = Path(a.out + "-work")
    shards = make_shards(src, chosen, out, "extra")
    man = json.loads((out / "MANIFEST.json").read_text())
    man["files"] += [{k: v for k, v in s.items() if k != "members"} for s in shards]
    man["note"] = "pilot v2: + extra shard(s)"
    man["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    print(json.dumps({"extra_shards": len(shards), "bytes": sum(s["bytes"] for s in shards)}))
    return 0


def cmd_flat(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(a.n):
        (out / f"probe-{i:04d}.txt").write_text(f"top-level file {i}\n")
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": "metis-market-lake-filecount-probe", "id": f"{a.username}/metis-market-lake-filecount-probe",
        "licenses": [{"name": "other"}]}, indent=1))
    print(json.dumps({"top_level_files": a.n}))
    return 0


def cmd_verify(a) -> int:
    root = Path(a.root)
    mans = sorted(root.rglob("MANIFEST.json"))
    if not mans:
        print(json.dumps({"ok": False, "why": "no MANIFEST.json"}))
        return 1
    base = mans[0].parent
    man = json.loads(mans[0].read_text())
    t0, nbytes, bad, mode = time.time(), 0, [], {"tar": 0, "extracted": 0}
    for f in man["files"]:
        p = base / f["path"]
        if p.is_file():  # shard kept as a tar
            mode["tar"] += 1
            if p.stat().st_size != f["bytes"] or sha256_file(p) != f["sha256"]:
                bad.append(f["path"])
            else:
                nbytes += f["bytes"]
        elif (base / p.stem).is_dir():  # Kaggle auto-unpacked the tar into a folder named after it (observed 2026-11-05)
            mode["extracted"] += 1
            n, tot = 0, 0
            for q in (base / p.stem).rglob("*"):
                if q.is_file():
                    n += 1
                    tot += len(q.read_bytes())  # a full read, as a trainer would
            if n != f.get("n_partitions") or tot != f.get("member_bytes"):
                bad.append(f"{f['path']}: extracted {n} files/{tot} B, manifest {f.get('n_partitions')}/{f.get('member_bytes')}")
            else:
                nbytes += tot
        else:
            bad.append(f["path"] + ": missing")
    dt = max(time.time() - t0, 1e-6)
    # read one parquet out of a shard the way a trainer would
    extracted = None
    try:
        t1 = time.time()
        pq = next(base.rglob("*.parquet"))
        data = pq.read_bytes()
        extracted = {"member": pq.relative_to(base).as_posix(), "bytes": len(data), "seconds": round(time.time() - t1, 3)}
    except Exception as e:
        extracted = {"error": str(e)[:200]}
    res = {"ok": not bad, "files": len(man["files"]), "bad": bad, "hashed_bytes": nbytes,
           "layout": mode, "hash_seconds": round(dt, 2), "hash_MBps": round(nbytes / 1e6 / dt, 1), "one_member_read": extracted,
           "dir": str(base)}
    print(json.dumps(res))
    if a.record:
        Path(a.record).write_text(json.dumps(res))
    return 0 if not bad else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["stage", "extra", "flat", "verify"])
    ap.add_argument("--out", default="stage")
    ap.add_argument("--repo", default="bentzbk/jta-market-lake")
    ap.add_argument("--username", default="")
    ap.add_argument("--target-gb", type=float, default=1.0)
    ap.add_argument("--from-dir", default="")
    ap.add_argument("--prev-chosen", default="")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--root", default="")
    ap.add_argument("--record", default="")
    a = ap.parse_args(argv)
    return {"stage": cmd_stage, "extra": cmd_extra, "flat": cmd_flat, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
