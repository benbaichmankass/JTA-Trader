#!/usr/bin/env python3
# ruff: noqa: BLE001  (measurement is best-effort: each failure is recorded in the output, never hidden, never halts)
# wiring: .github/workflows/hf-lake-storage.yml (HF_TOKEN from Actions secrets, never printed)
"""Measure and squash the PRIVATE HF lake dataset so it stays under the free private-storage cap.

Row HF-LAKE-STORAGE-403 (lane HF-LAKE-SQUASH). Operator decision 2026-11-05: "Squash first, then free org".

    python3 scripts/data_lake/hf_storage.py measure            # account storage per private repo + lake current-revision vs total
    python3 scripts/data_lake/hf_storage.py squash             # measure -> super_squash_history -> measure -> verify MANIFEST.json (HTTP 200)
    python3 scripts/data_lake/hf_storage.py squash --if-over-gb 60   # retention: squash only when total storage exceeds this

HF keeps every historic LFS version of every file, so a manifest rewritten each refresh grows storage without bound.
`super_squash_history` removes that history (irreversible; the lake is rebuildable from source). Tags `vYYYYMMDD-HHMM`
pin old commits and would keep their blobs alive, so squash drops them and re-tags the squashed head.
Never creates accounts; never deletes a repo; the only removal is history via squash.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_publish import PLAN_PRIVATE_BYTES, _api, _repo_from_config


def current_revision_bytes(api, repo: str) -> dict:
    """Bytes of the files at HEAD (LFS size where present). A directory walk; population = every file in the tree."""
    n, total, top = 0, 0, {}
    for it in api.list_repo_tree(repo, repo_type="dataset", recursive=True, expand=True):
        if getattr(it, "path", None) is None or it.__class__.__name__ != "RepoFile":
            continue
        size = int(getattr(getattr(it, "lfs", None), "size", None) or getattr(it, "size", 0) or 0)
        n += 1
        total += size
        k = it.path.split("/", 1)[0]
        top[k] = top.get(k, 0) + size
    return {"files": n, "bytes": total, "top_level": dict(sorted(top.items(), key=lambda kv: -kv[1])[:12])}


def account_storage(api, who: dict) -> dict:
    user = who.get("name")
    out, total, errs = [], 0, 0
    for kind, lister, info in (("model", api.list_models, api.model_info), ("dataset", api.list_datasets, api.dataset_info),
                               ("space", api.list_spaces, api.space_info)):
        try:
            for r in lister(author=user, expand=["private"]):
                try:
                    u = int(getattr(info(r.id, expand=["usedStorage"]), "used_storage", 0) or 0)
                except Exception:
                    u, errs = None, errs + 1
                priv = bool(getattr(r, "private", False))
                if priv and u:
                    total += u
                out.append({"repo": r.id, "type": kind, "private": priv, "used_bytes": u})
        except Exception:
            errs += 1
    return {"user": user, "private_used_bytes": total, "repos": out, "measure_errors": errs}


def measure(api, repo: str) -> dict:
    who = api.whoami()
    plan = "pro" if who.get("isPro") else "free"
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "plan": plan,
           "allowance_bytes": PLAN_PRIVATE_BYTES[plan], "account": account_storage(api, who)}
    try:
        rec["lake_current_revision"] = current_revision_bytes(api, repo)
    except Exception as e:
        rec["lake_current_revision"] = {"error": str(e)[:300]}
    try:
        refs = api.list_repo_refs(repo, repo_type="dataset")
        rec["refs"] = {"branches": [b.name for b in refs.branches], "n_tags": len(refs.tags),
                       "n_converts": len(getattr(refs, "converts", []) or [])}
    except Exception as e:
        rec["refs"] = {"error": str(e)[:200]}
    try:
        rec["n_commits"] = len(list(api.list_repo_commits(repo, repo_type="dataset")))
    except Exception as e:
        rec["n_commits"] = f"error: {str(e)[:100]}"
    lake = next((r["used_bytes"] for r in rec["account"]["repos"] if r["repo"] == repo), None)
    rec["lake_total_used_bytes"] = lake
    cur = rec["lake_current_revision"].get("bytes")
    rec["history_overhead_bytes"] = (lake - cur) if (lake is not None and cur is not None) else None
    return rec


def verify_manifest(api, repo: str) -> dict:
    import urllib.error
    import urllib.request
    url = f"https://huggingface.co/datasets/{repo}/resolve/main/MANIFEST.json"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api.token}"}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"url": url, "http_status": r.status}
    except urllib.error.HTTPError as e:
        return {"url": url, "http_status": e.code}
    except Exception as e:
        return {"url": url, "http_status": None, "error": str(e)[:200]}


def cmd_measure(a) -> int:
    rec = measure(_api(), a.repo)
    print(json.dumps(rec, indent=1))
    used = rec["account"]["private_used_bytes"]
    if a.alert_over_gb and used >= a.alert_over_gb * 10 ** 9:
        # an annotation, never a halt: the pipeline keeps running (Prime Directive rule 7)
        print(f"::warning::HF private storage {used / 1e9:.1f} GB >= {a.alert_over_gb} GB of the {rec['allowance_bytes'] / 1e9:.0f} GB "
              f"allowance (history overhead {rec['history_overhead_bytes']} B): uploads will 403 at the cap; see row HF-LAKE-STORAGE-403")
    return 0


def cmd_squash(a) -> int:
    api = _api()
    before = measure(api, a.repo)
    print("BEFORE", json.dumps(before, indent=1))
    if a.if_over_gb:
        used = before["account"]["private_used_bytes"]
        if used < a.if_over_gb * 10 ** 9:
            print(f"retention: account private storage {used / 1e9:.1f} GB < {a.if_over_gb} GB threshold; no squash")
            return 0
    tags = []
    try:
        tags = [t.name for t in api.list_repo_refs(a.repo, repo_type="dataset").tags]
    except Exception as e:
        print(f"::warning::tags not listed: {str(e)[:200]}")
    api.super_squash_history(repo_id=a.repo, repo_type="dataset")
    print("squashed history of", a.repo)
    # tags pinned the pre-squash commits and keep their blobs alive: drop them, re-tag the squashed head
    for t in tags:
        try:
            api.delete_tag(a.repo, tag=t, repo_type="dataset")
        except Exception as e:
            print(f"::warning::tag {t} not deleted: {str(e)[:150]}")
    tag = "v" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    try:
        api.create_tag(a.repo, tag=tag, repo_type="dataset")
    except Exception as e:
        print(f"::warning::tag {tag} not created: {str(e)[:150]}")
    after = measure(api, a.repo)
    print("AFTER", json.dumps(after, indent=1))
    ver = verify_manifest(api, a.repo)
    print("VERIFY", json.dumps(ver))
    if a.record:
        with open(a.record, "w") as fh:
            json.dump({"before": before, "after": after, "verify": ver, "dropped_tags": len(tags)}, fh, indent=1)
    return 0 if ver.get("http_status") == 200 else 2


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["measure", "squash"])
    ap.add_argument("--repo", default=_repo_from_config())
    ap.add_argument("--alert-over-gb", type=float, default=0.0, help="measure: emit a ::warning:: at or above this many GB")
    ap.add_argument("--if-over-gb", type=float, default=0.0)
    ap.add_argument("--record", default="")
    a = ap.parse_args(argv)
    return {"measure": cmd_measure, "squash": cmd_squash}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
