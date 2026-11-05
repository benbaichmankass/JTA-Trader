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


def list_local_candidates(root: Path, prefix: str = PREFIX) -> list[dict]:
    out = []
    for p in sorted((root / prefix).rglob("*.parquet")):
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
                       "members": [{"path": c["path"], "bytes": c.get("got") or c["bytes"],
                                    "sha256": sha256_file(src / c["path"])} for c in cur]})
        cur, cur_bytes, n = [], 0, n + 1

    for c in sorted(files, key=lambda e: e["path"]):
        cur.append(c)
        cur_bytes += c.get("got") or c["bytes"]
        if cur_bytes >= SHARD_BYTES:
            flush()
    flush()
    return shards


def write_dataset_files(out: Path, username: str, shards: list[dict], note: str, slug: str = "metis-market-lake",
                        extra: dict | None = None) -> None:
    man = {"schema": "metis-market-lake-pilot/v1", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": note, "prefix": PREFIX, "files": shards,
           "n_partitions": sum(s["n_partitions"] for s in shards)}
    man.update(extra or {})
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": slug, "id": f"{username}/{slug}", "licenses": [{"name": "other"}]}, indent=1))


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


def cmd_build_stage(a) -> int:
    """10 GB trial: build frozen crypto 1m partitions from data.binance.vision in small symbol batches, tar the frozen ones
    into shards straight away and delete the batch, so peak disk is (staged shards + one batch). HF is not read (its reads
    are refused at the cap). Symbols the 1 GB pilot already used are skipped, so the content is new."""
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import binance_vision_lake as bvl
    out, tmp = Path(a.out), Path(a.out + "-batch")
    out.mkdir(parents=True, exist_ok=True)
    target = int(a.target_gb * 10 ** 9)
    skip = set(a.skip_symbols.split(",")) if a.skip_symbols else set()
    syms = [x for x in (bvl.symbols_from_config("um_perp", "klines") or bvl.list_symbols("um_perp")) if x not in skip]
    shards: list[dict] = []
    staged, n_files, t0, used = 0, 0, time.time(), []
    for i in range(0, len(syms), a.batch):
        if staged >= target:
            break
        batch = syms[i:i + a.batch]
        shutil.rmtree(tmp, ignore_errors=True)
        rc = bvl.main(["--market", "um_perp", "--stream", "klines", "--out", str(tmp), "--symbols", ",".join(batch),
                       "--parallel", "4"])
        files = list_local_candidates(tmp)
        for c in files:
            c["got"] = c["bytes"]
        if files:
            idx = len(shards)
            made = make_shards(tmp, files, out, f"crypto-um_perp-1m-b{idx:03d}")
            shards += made
            staged += sum(m["bytes"] for m in made)
            n_files += len(files)
            used += batch
        print(json.dumps({"batch": i // a.batch, "rc": rc, "symbols": len(batch), "partitions": len(files),
                          "staged_bytes": staged, "shards": len(shards), "seconds": round(time.time() - t0)}), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    write_dataset_files(out, a.username, shards, f"10GB trial: {n_files} frozen partitions, {len(used)} symbols")
    print(json.dumps({"symbols": len(used), "partitions": n_files, "shards": len(shards), "staged_bytes": staged,
                      "top_level_entries": len(shards) + 2, "seconds": round(time.time() - t0)}))
    return 0


def cmd_plan(a) -> int:
    """Read-only: list the HF lake tree (listing still works at the cap), measure the FROZEN bytes per (market, label), and slice the
    frozen set by symbol into parts of at most --part-gb, each part one (market, stream) so a part is one builder invocation."""
    token = os.environ.get("HF_TOKEN", "")
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import binance_vision_lake as bvl
    label_stream = {v["label"]: k for k, v in bvl.STREAMS.items()}
    groups: dict[tuple, dict] = {}
    t0 = time.time()
    for it in api.list_repo_tree(a.repo, path_in_repo="crypto", repo_type="dataset", recursive=True, expand=True):
        if it.__class__.__name__ != "RepoFile" or not it.path.endswith(".parquet"):
            continue
        parts = it.path.split("/")
        if len(parts) != 5:
            continue
        _, market, label, sym, fn = parts
        size = int(getattr(getattr(it, "lfs", None), "size", None) or getattr(it, "size", 0) or 0)
        g = groups.setdefault((market, label), {"files": 0, "bytes": 0, "frozen_files": 0, "frozen_bytes": 0, "symbols": {}})
        g["files"] += 1
        g["bytes"] += size
        if is_frozen_name(fn):
            g["frozen_files"] += 1
            g["frozen_bytes"] += size
            sy = g["symbols"].setdefault(sym, [0, 0])
            sy[0] += 1
            sy[1] += size
    summary = {f"{m}/{lb}": {"files": g["files"], "bytes": g["bytes"], "frozen_files": g["frozen_files"],
                             "frozen_bytes": g["frozen_bytes"], "frozen_symbols": len(g["symbols"]),
                             "stream": label_stream.get(lb)} for (m, lb), g in sorted(groups.items())}
    cap = int(a.part_gb * 10 ** 9)
    parts = []
    for (market, label), g in sorted(groups.items()):
        stream = label_stream.get(label)
        if not stream or not g["symbols"]:
            continue
        cur, cur_b, cur_f = [], 0, 0
        for sym in sorted(g["symbols"]):
            nf, nb = g["symbols"][sym]
            # metrics are rebuilt from DAILY zips (~30x the downloads per month of a monthly stream): cap symbols per part so one runner
            # job cannot exceed its time limit
            if cur and (cur_b + nb > cap or (stream == "metrics" and len(cur) >= a.max_symbols_daily)):
                parts.append({"market": market, "label": label, "stream": stream, "symbols": cur,
                              "expected_partitions": cur_f, "expected_bytes": cur_b})
                cur, cur_b, cur_f = [], 0, 0
            cur.append(sym)
            cur_b += nb
            cur_f += nf
        if cur:
            parts.append({"market": market, "label": label, "stream": stream, "symbols": cur,
                          "expected_partitions": cur_f, "expected_bytes": cur_b})
    for i, pt in enumerate(parts):
        pt["part"] = f"p{i:03d}"
        pt["slug"] = f"metis-market-lake-p{i:03d}"
    plan = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "part_gb": a.part_gb,
            "listing_seconds": round(time.time() - t0), "summary": summary,
            "frozen_total_bytes": sum(v["frozen_bytes"] for v in summary.values()),
            "frozen_total_files": sum(v["frozen_files"] for v in summary.values()), "n_parts": len(parts),
            "plan_id": hashlib.sha256(json.dumps([[p["part"], p["market"], p["stream"], p["symbols"]] for p in parts]).encode()).hexdigest()[:16],
            "parts": parts}
    Path(a.out).write_text(json.dumps(plan))
    print(json.dumps({k: v for k, v in plan.items() if k != "parts"}, indent=1))
    print(json.dumps([{k: v for k, v in p.items() if k != "symbols"} | {"n_symbols": len(p["symbols"])} for p in parts]))
    return 0


def cmd_copy_part(a) -> int:
    """Build ONE planned part (market, stream, symbols) from data.binance.vision, keep only FROZEN partitions, shard them with
    per-member SHA-256, and check completeness against the HF listing (every expected frozen path present)."""
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import binance_vision_lake as bvl
    plan = json.loads(Path(a.plan).read_text())
    part = next(p for p in plan["parts"] if p["part"] == a.part)
    label = part["label"]
    prefix = f"crypto/{part['market']}/{label}"
    out, tmp = Path(a.out), Path(a.out + "-batch")
    out.mkdir(parents=True, exist_ok=True)
    syms = part["symbols"]
    shards: list[dict] = []
    have: set[str] = set()
    t0 = time.time()
    for i in range(0, len(syms), a.batch):
        batch = syms[i:i + a.batch]
        shutil.rmtree(tmp, ignore_errors=True)
        daily = part["stream"] == "metrics"
        rc = bvl.main(["--market", part["market"], "--stream", part["stream"], "--out", str(tmp), "--symbols", ",".join(batch),
                       "--parallel", "8" if daily else "4", "--workers", "12" if daily else "8"])
        files = list_local_candidates(tmp, prefix)
        for c in files:
            c["got"] = c["bytes"]
            have.add(c["path"])
        if files:
            shards += make_shards(tmp, files, out, f"{part['part']}-b{i // a.batch:03d}")
        print(json.dumps({"batch": i // a.batch, "rc": rc, "symbols": len(batch), "partitions": len(files),
                          "shards": len(shards), "seconds": round(time.time() - t0)}), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    rep = {"part": part["part"], "market": part["market"], "stream": part["stream"], "symbols": len(syms),
           "built_partitions": len(have), "built_bytes": sum(m["bytes"] for sh in shards for m in sh["members"]),
           "expected_partitions": part["expected_partitions"], "expected_hf_bytes": part["expected_bytes"],
           "shards": len(shards), "top_level_entries": len(shards) + 2, "seconds": round(time.time() - t0)}
    write_dataset_files(out, a.username, shards, f"cold lake {part['part']} plan {plan['plan_id']}: {len(have)} frozen partitions",
                        slug=part["slug"], extra={"part": part["part"], "plan_id": plan["plan_id"], "market": part["market"],
                                                  "stream": part["stream"], "symbols": syms,
                                                  "expected_partitions": part["expected_partitions"]})
    print(json.dumps(rep))
    Path(a.out + "-report.json").write_text(json.dumps(rep))
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
    man["files"] += shards
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
    level = {"member": 0, "count_and_bytes": 0}
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
            if f.get("members"):  # per-member SHA-256 (checksum level "member")
                level["member"] += 1
                for m in f["members"]:
                    q = base / p.stem / m["path"]
                    if q.is_file() and q.stat().st_size == m["bytes"] and sha256_file(q) == m["sha256"]:
                        n += 1
                        tot += m["bytes"]
                    else:
                        bad.append(f"{f['path']}: {m['path']} missing or checksum mismatch")
            else:  # legacy manifest: file count + exact byte total only
                level["count_and_bytes"] += 1
                for q in (base / p.stem).rglob("*"):
                    if q.is_file():
                        n += 1
                        tot += len(q.read_bytes())
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
    if a.expect_min_files and len(man["files"]) < a.expect_min_files:
        bad.append(f"stale or wrong dataset version: manifest lists {len(man['files'])} shards, expected at least {a.expect_min_files}")
    res = {"ok": not bad, "files": len(man["files"]), "note": man.get("note"), "bad": bad, "hashed_bytes": nbytes,
           "layout": mode, "checksum_level": level, "hash_seconds": round(dt, 2), "hash_MBps": round(nbytes / 1e6 / dt, 1), "one_member_read": extracted,
           "dir": str(base)}
    print(json.dumps(res))
    if a.record:
        Path(a.record).write_text(json.dumps(res))
    return 0 if not bad else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["stage", "extra", "flat", "verify", "build-stage", "plan", "copy-part"])
    ap.add_argument("--out", default="stage")
    ap.add_argument("--repo", default="bentzbk/jta-market-lake")
    ap.add_argument("--username", default="")
    ap.add_argument("--target-gb", type=float, default=1.0)
    ap.add_argument("--from-dir", default="")
    ap.add_argument("--prev-chosen", default="")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--expect-min-files", type=int, default=0)
    ap.add_argument("--part-gb", type=float, default=22.0)
    ap.add_argument("--max-symbols-daily", type=int, default=250)
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--part", default="")
    ap.add_argument("--skip-symbols", default="")
    ap.add_argument("--root", default="")
    ap.add_argument("--record", default="")
    a = ap.parse_args(argv)
    return {"stage": cmd_stage, "extra": cmd_extra, "flat": cmd_flat, "verify": cmd_verify,
            "build-stage": cmd_build_stage, "plan": cmd_plan, "copy-part": cmd_copy_part}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
