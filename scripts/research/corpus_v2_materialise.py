#!/usr/bin/env python3
# wiring: .github/workflows/research-script-run.yml step "Materialise corpus v2" (units whose run.command reads corpus_v2/); lane TMBENCH-V2-TRAIN-INPUT
"""Put corpus v2 (the broad-paths 60-perp corpus, comms/research/broad_paths/<id>/manifest.json) on the runner and check it against its manifest.

Corpus v2's rows (trades.jsonl.gz, paths.jsonl.gz) are an Actions artifact, never the repo, and the artifact of the run that built it
(40999208713, `broad-paths-bp2-f4271084b120-data`, 90-day retention) is GONE: MEASURED 2026-11-12, the run is listed
(success, 2026-10-30) and its artifact list and a by-name search both return total_count 0, while the same query lists other runs'
artifacts. So this tool has two sources, in order:

  1. FETCH   the newest non-expired artifact named `broad-paths-<corpus_id>-data` of any run of this repo (the ambient token, read-only).
  2. REGENERATE  from the manifest alone: the universe is rebuilt from `hash_inputs` (its sha256 must reproduce `corpus_id`), the six shards
             run with `broad_paths_corpus.py` from a worktree at the manifest's `git_sha` (the config-exact harnesses and
             config/strategies.yaml of the run that built it; HEAD only if that sha cannot be checked out, and then said so),
             and the shards are merged exactly as the original merge job did.

Either way the result is verified, and the verification is written, never enforced here:
  * `trade_key_sha256` over the sorted trade_keys, and the trade count, against the manifest;
  * `materialise.json` beside the data: {corpus_id, state, source, expected / observed hash + count, match, ...}.
A mismatch does NOT stop anything (no halting; no new gate): `tm_bench --expect-train-corpus <id>` reads `materialise.json` and the
unit's own registered rule turns a non-matching train corpus into INDETERMINATE.

    python3 scripts/research/corpus_v2_materialise.py --manifest comms/research/broad_paths/bp2-f4271084b120/manifest.json --out corpus_v2
    python3 scripts/research/corpus_v2_materialise.py --self-test

Tier-1 research tooling: keyless public candles, the ambient read-only token, no VM, no order path, no Claude call.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research")]

SCHEMA = "corpus_v2_materialise/1"


def trade_key_hash(trades_gz: Path) -> Tuple[str, int]:
    """sha256 over the sorted trade_keys (each + newline) and the count: the definition of broad_paths_corpus.merge_shards."""
    keys = set()
    with gzip.open(trades_gz, "rt", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                keys.add(json.loads(ln)["trade_key"])
    h = hashlib.sha256()
    for k in sorted(keys):
        h.update(k.encode() + b"\n")
    return h.hexdigest(), len(keys)


def universe_from_manifest(man: Dict[str, Any]) -> Dict[str, Any]:
    """The shard stage's universe, rebuilt from the manifest (no S3 listing). The recomputed id must equal the manifest's."""
    import broad_paths_corpus as bp
    hi = man["hash_inputs"]
    cid, _ = bp.corpus_id(hi["symbols"], end=hi["end"])
    return {"corpus_id": man["corpus_id"], "recomputed_corpus_id": cid, "hash_inputs": hi, "census": man.get("census")}


def fetch_artifact(corpus_id: str, out: Path, repo: str, token: str) -> Dict[str, Any]:
    """Newest non-expired `broad-paths-<id>-data` artifact of this repo -> out/. Returns a record; never raises."""
    import requests
    name = f"broad-paths-{corpus_id}-data"
    rec: Dict[str, Any] = {"tried": "artifact", "artifact_name": name}
    try:
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/artifacts", params={"name": name, "per_page": 100},
                         headers=h, timeout=60)
        r.raise_for_status()
        arts = [a for a in r.json().get("artifacts", []) if not a.get("expired")]
        rec["n_listed_unexpired"] = len(arts)
        if not arts:
            return rec | {"found": False}
        a = max(arts, key=lambda x: x["created_at"])
        rec |= {"found": True, "run_id": (a.get("workflow_run") or {}).get("id"), "created_at": a["created_at"],
                "size_in_bytes": a.get("size_in_bytes")}
        z = requests.get(a["archive_download_url"], headers=h, timeout=900)
        z.raise_for_status()
        out.mkdir(parents=True, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(z.content)).extractall(out)
        return rec | {"downloaded": True}
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded in materialise.json with the cause; the regenerate path follows
        return rec | {"error": repr(exc)[-300:]}


def _git(*a: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=False)


def source_tree(sha: str, work: Path) -> Tuple[Path, Dict[str, Any]]:
    """A checkout of `sha` to run the shards from (its harnesses + config/strategies.yaml); HEAD, said so, if it cannot be had."""
    wt = work / "bp2_src"
    if sha:
        have = _git("cat-file", "-t", sha).stdout.strip() == "commit"
        if not have:
            _git("fetch", "--no-tags", "--depth", "1", "origin", sha)
            have = _git("cat-file", "-t", sha).stdout.strip() == "commit"
        if have and _git("worktree", "add", "--detach", str(wt), sha).returncode == 0:
            return wt, {"source_tree": "manifest git_sha", "git_sha": sha}
    return REPO, {"source_tree": "HEAD (manifest git_sha not checkable here)", "git_sha": _git("rev-parse", "HEAD").stdout.strip(),
                  "manifest_git_sha": sha}


def regenerate(man: Dict[str, Any], out: Path, work: Path, shards: int, parallel: int) -> Dict[str, Any]:
    uni = universe_from_manifest(man)
    rec: Dict[str, Any] = {"tried": "regenerate", "universe_id_reproduced": uni["recomputed_corpus_id"] == man["corpus_id"],
                           "recomputed_corpus_id": uni["recomputed_corpus_id"]}
    tree, trec = source_tree(man.get("git_sha") or "", work)
    rec |= trec
    up = work / "universe.json"
    up.write_text(json.dumps({k: uni[k] for k in ("corpus_id", "hash_inputs", "census")}))
    win = man["window"]
    script = tree / "scripts" / "research" / "broad_paths_corpus.py"
    sdirs = []
    procs: List[Tuple[int, subprocess.Popen, Any]] = []
    t0 = time.time()

    def launch(i: int) -> Tuple[int, subprocess.Popen, Any]:
        d = work / f"shard-{i}"
        sdirs.append(d)
        log = open(work / f"shard-{i}.log", "w")
        return i, subprocess.Popen([sys.executable, str(script), "shard", "--universe", str(up), "--shard", str(i), "--of", str(shards),
                                    "--out", str(d), "--start", win["start"], "--end", win["end"]], cwd=str(tree), stdout=log,
                                   stderr=subprocess.STDOUT), log

    todo, codes = list(range(shards)), {}
    while todo or procs:
        while todo and len(procs) < parallel:
            procs.append(launch(todo.pop(0)))
        time.sleep(5)
        for p in list(procs):
            if p[1].poll() is not None:
                p[2].close()
                codes[p[0]] = p[1].returncode
                procs.remove(p)
                print(f"shard {p[0]} exit {p[1].returncode} ({round(time.time() - t0)}s)", flush=True)
    rec |= {"shard_exit_codes": codes, "shard_seconds": round(time.time() - t0)}
    good = [d for d in sorted(sdirs) if (d / "shard_manifest.json").exists()]
    if not good:
        return rec | {"error": "no shard produced a shard_manifest.json"}
    r = subprocess.run([sys.executable, str(script), "merge", "--universe", str(up), "--shards", str(work), "--out", str(work / "merged"),
                        "--start", win["start"], "--end", win["end"], "--git-sha", str(rec.get("git_sha") or ""),
                        "--run-id", "regenerated"], cwd=str(tree), capture_output=True, text=True, check=False)
    rec["merge_exit"] = r.returncode
    if r.returncode != 0:
        return rec | {"error": "merge failed: " + (r.stderr or r.stdout)[-300:]}
    out.mkdir(parents=True, exist_ok=True)
    for f in ("trades.jsonl.gz", "paths.jsonl.gz"):
        shutil.copy2(work / "merged" / "data" / f, out / f)
    m2 = json.loads((work / "merged" / "manifest.json").read_text())
    return rec | {"could_not_run": m2["counts"]["symbol_leg_cells_could_not_run"], "cells_run": m2["counts"]["symbol_leg_cells_run"]}


def verify(man: Dict[str, Any], out: Path) -> Dict[str, Any]:
    tg, pg = out / "trades.jsonl.gz", out / "paths.jsonl.gz"
    if not (tg.exists() and pg.exists()):
        return {"present": False, "trade_key_sha256_match": False, "n_trades_match": False}
    h, n = trade_key_hash(tg)
    exp_n = (man.get("counts") or {}).get("trades_deduplicated")
    return {"present": True, "trade_key_sha256_expected": man.get("trade_key_sha256"), "trade_key_sha256_observed": h,
            "trade_key_sha256_match": h == man.get("trade_key_sha256"), "n_trades_expected": exp_n, "n_trades_observed": n,
            "n_trades_match": n == exp_n}


def materialise(man: Dict[str, Any], out: Path, *, repo: str, token: str, shards: int, parallel: int,
                fetch_fn=fetch_artifact, regen_fn=regenerate) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    state, ver = "none", {}
    if repo and token:
        a = fetch_fn(man["corpus_id"], out, repo, token)
        attempts.append(a)
        ver = verify(man, out)
        state = "artifact" if a.get("downloaded") and ver.get("trade_key_sha256_match") else "none"
        if a.get("downloaded") and not ver.get("trade_key_sha256_match"):
            attempts[-1]["rejected"] = "downloaded artifact does not match the manifest trade_key hash"
    else:
        attempts.append({"tried": "artifact", "skipped": "no GITHUB_REPOSITORY / GITHUB_TOKEN in the environment"})
    if state == "none":
        with tempfile.TemporaryDirectory(prefix="bp2_regen_") as w:
            attempts.append(regen_fn(man, out, Path(w), shards, parallel))
        ver = verify(man, out)
        state = "regenerated" if ver.get("present") else "none"
    return {"schema": SCHEMA, "corpus_id": man["corpus_id"], "state": state, "attempts": attempts, **ver,
            "manifest_git_sha": man.get("git_sha"), "manifest_run_id": man.get("run_id"),
            "population": f"corpus {man['corpus_id']}: {len(man['hash_inputs']['symbols'])} symbols x {len(man['hash_inputs']['legs'])} legs"}


def _self_test() -> int:
    import broad_paths_corpus as bp
    man = json.loads((REPO / "comms" / "research" / "broad_paths" / "bp2-f4271084b120" / "manifest.json").read_text())
    u = universe_from_manifest(man)
    assert u["recomputed_corpus_id"] == man["corpus_id"] == "bp2-f4271084b120", (u["recomputed_corpus_id"], man["corpus_id"])
    # the hash definition equals merge_shards' own (build two shards, merge them, compare)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i in (0, 1):
            d = td / f"s{i}"
            d.mkdir()
            rows = [{"trade_key": f"L|S|t{j}|long", "symbol": "S", "leg": "L"} for j in (0, 1, 2 + i)]
            with gzip.open(d / "trades.jsonl.gz", "wt") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
            with gzip.open(d / "paths.jsonl.gz", "wt") as f:
                f.writelines(json.dumps({"trade_key": r["trade_key"], "bar_index": 1}) + "\n" for r in rows)
            (d / "shard_manifest.json").write_text(json.dumps({"runs": [], "could_not_run": []}))
        m = bp.merge_shards([td / "s0", td / "s1"], td / "o")
        h, n = trade_key_hash(td / "o" / "trades.jsonl.gz")
        assert (h, n) == (m["trade_key_sha256"], 4), (h, n, m["trade_key_sha256"])
        fake = dict(man, trade_key_sha256=h, counts={"trades_deduplicated": 4})
        v = verify(fake, td / "o")
        assert v["trade_key_sha256_match"] and v["n_trades_match"], v
        v2 = verify(dict(fake, trade_key_sha256="0" * 64), td / "o")
        assert not v2["trade_key_sha256_match"] and v2["n_trades_match"], v2          # the check can say no
        assert verify(fake, td / "nothing")["present"] is False
        # order: a found, matching artifact is used and nothing is regenerated; a missing one falls through to regeneration
        calls = []

        def fetch_ok(cid, out, repo, token):  # inert: cid, repo, token — test stub mirroring fetch_artifact's signature
            shutil.copytree(td / "o", out, dirs_exist_ok=True)
            return {"found": True, "downloaded": True}

        def regen(*a, **k):
            calls.append("regen")
            return {}
        r = materialise(fake, td / "x1", repo="r", token="t", shards=1, parallel=1, fetch_fn=fetch_ok, regen_fn=regen)
        assert r["state"] == "artifact" and not calls and r["trade_key_sha256_match"], r
        r = materialise(fake, td / "x2", repo="r", token="t", shards=1, parallel=1, fetch_fn=lambda *a: {"found": False}, regen_fn=regen)
        assert calls == ["regen"] and r["state"] == "none" and r["trade_key_sha256_match"] is False, r
        # a downloaded artifact that does NOT match the manifest is rejected and regenerated, and the rejection is recorded
        calls.clear()
        bad = dict(fake, trade_key_sha256="1" * 64)
        r = materialise(bad, td / "x3", repo="r", token="t", shards=1, parallel=1, fetch_fn=fetch_ok, regen_fn=regen)
        assert calls == ["regen"] and "rejected" in r["attempts"][0], r
    print("self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shards", type=int, default=6, help="regenerate: shard count (content does not depend on it)")
    ap.add_argument("--parallel", type=int, default=3, help="regenerate: concurrent shard processes")
    a = ap.parse_args(argv)
    man = json.loads(Path(a.manifest).read_text())
    out = Path(a.out)
    rec = materialise(man, out, repo=os.environ.get("GITHUB_REPOSITORY", ""), token=os.environ.get("GITHUB_TOKEN", ""),
                      shards=a.shards, parallel=a.parallel)
    out.mkdir(parents=True, exist_ok=True)
    (out / "materialise.json").write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("corpus_id", "state", "trade_key_sha256_match", "n_trades_expected", "n_trades_observed")}))
    return 0   # never halts: the verdict is in materialise.json and the unit's registered rule reads it


if __name__ == "__main__":
    sys.exit(main())
