#!/usr/bin/env python3
# ruff: noqa: BLE001  (a stamp/flag failure is reported and never halts the backup run)
# wiring: .github/workflows/kaggle-backups.yml (stage / verify / stamp; KAGGLE_API_TOKEN + trainer SSH from Actions secrets, never printed)
"""Standing PRIVATE Kaggle backups (row KAGGLE-BACKUPS, lane HF-LAKE-SQUASH).

Operator decision 2026-11-05 ~17:02Z, verbatim: "Ok, let's also keep backups on kaggle (on private)".

    stage   --kind models --out DIR --served ml/served --registry DIR   copy-stage ml/served + the trainer registry-store
    scan    --root DIR                                                  fail closed if anything looks like a credential
    verify  --root DIR                                                  re-hash every file against MANIFEST.json
    stamp   --kind K --ok|--fail --details JSON --previous P --out O [--flag]
                                                                        write the freshness stamp the health review reads;
                                                                        ONE ops-flags/Telegram flag per incident, never a halt

Rules: COPY only (nothing is moved or deleted anywhere); NEVER credentials (env files, account keys, tokens); Kaggle is a
backup + compute surface and is NEVER read on the trade path (the trader and trainer keep their local copies as the source
of truth); retention deletes nothing without the operator's OK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

#: High-signal credential shapes. Anything matching refuses the backup (fail closed); a false positive costs one backup, a
#: miss would put a secret on a third-party service.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # Telegram bot token
    re.compile(r"(?i)[\"'](?:api[_-]?key|api[_-]?secret|secret[_-]?key|password|passwd|private[_-]?key|access[_-]?token)[\"']\s*:\s*[\"'][^\"']{8,}[\"']"),
]
#: Files that are credentials by NAME, whatever they contain.
SECRET_NAMES = re.compile(r"(?i)(^|/)(\.env[^/]*|.*\.pem|.*\.key|id_rsa[^/]*|.*credentials.*|.*secrets?\.(ya?ml|json))$")
TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".txt", ".md", ".csv", ".toml", ".ini", ".cfg", ".py", ".sh", ".log"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_tree(root: Path) -> list[dict]:
    """Return one finding per file that is a credential by name or content (text files only; binaries are matched by name)."""
    findings = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if SECRET_NAMES.search(rel):
            findings.append({"file": rel, "why": "credential-like file name"})
            continue
        if p.suffix.lower() in TEXT_SUFFIXES and p.stat().st_size <= 64 * 1024 * 1024:
            text = p.read_text(errors="ignore")
            for pat in SECRET_PATTERNS:
                if pat.search(text):
                    findings.append({"file": rel, "why": "matches " + pat.pattern[:40]})
                    break
    return findings


def write_manifest(root: Path, kind: str, note: str = "") -> dict:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.json":
            files.append({"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    man = {"schema": "kaggle-backup/v1", "kind": kind, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": note, "n_files": len(files), "bytes": sum(f["bytes"] for f in files), "files": files}
    (root / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    return man


def _pack(d: Path, kind: str, out: Path) -> None:
    """Replace directory `d` with `<kind>.tar` + MANIFEST.json (members carry bytes + sha256)."""
    members = [{"path": p.relative_to(d).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
               for p in sorted(d.rglob("*")) if p.is_file()]
    arch = out / f"{kind}.tar"
    with tarfile.open(arch, "w") as tf:
        for m in members:
            tf.add(d / m["path"], arcname=m["path"])
    shutil.rmtree(d)
    d.mkdir()
    shutil.move(str(arch), str(d / f"{kind}.tar"))
    man = {"schema": "kaggle-backup/v1", "kind": kind, "archive": f"{kind}.tar",
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_files": len(members),
           "bytes": sum(m["bytes"] for m in members), "files": members}
    (d / "MANIFEST.json").write_text(json.dumps(man, indent=1))


def cmd_stage(a) -> int:
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    if a.kind != "models":
        print(f"::error::unknown kind {a.kind}")
        return 2
    served, reg = out / "served", out / "registry-store"
    # ml/served: exactly the files the live trader loads (copy, never move)
    n_served = 0
    for src in sorted(Path(a.served).rglob("*")):
        if src.is_file():
            dst = served / src.relative_to(a.served)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_served += 1
    n_reg = 0
    if a.registry and Path(a.registry).is_dir():
        for src in sorted(Path(a.registry).rglob("*")):
            if src.is_file():
                dst = reg / src.relative_to(a.registry)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                n_reg += 1
    found = scan_tree(out)
    if found:
        print(json.dumps({"refused": True, "credential_findings": found[:20]}))
        shutil.rmtree(out, ignore_errors=True)  # a refused backup leaves nothing staged
        print("::error::credential-like content in the staging tree: backup REFUSED (nothing uploaded)")
        return 3
    # Both instances ship as ONE tar + MANIFEST.json (per-member SHA-256). Why: Kaggle Models refuse more than 50 files
    # ("The file count exceeds the maximum of 50", observed 2026-11-05 with 106 registry files) and `-r skip` ignores sub-directories
    # (ml/served is three model folders).
    for d, kind in ((served, "served"), (reg, "registry-store")):
        if d.is_dir():
            _pack(d, kind, out)
    print(json.dumps({"staged": True, "served_files": n_served, "registry_files": n_reg,
                      "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file())}))
    return 0


def cmd_scan(a) -> int:
    found = scan_tree(Path(a.root))
    print(json.dumps({"findings": found}))
    return 3 if found else 0


def _member_ok(path: Path, f: dict) -> bool:
    return path.is_file() and path.stat().st_size == f["bytes"] and sha256_file(path) == f["sha256"]


def cmd_verify(a) -> int:
    """Re-hash every file named in every MANIFEST.json under --root. A manifest with an "archive" is checked either from the
    tar (if Kaggle left it as a tar) or from the folder Kaggle unpacked it into (observed for dataset tars)."""
    import tempfile
    root = Path(a.root)
    bad, ok, n = [], 0, 0
    for man_p in sorted(root.rglob("MANIFEST.json")):
        man = json.loads(man_p.read_text())
        base = man_p.parent
        arch = man.get("archive")
        if arch:
            tmp = None
            tar_p = next(iter(sorted(base.rglob(arch))), None) if base.is_dir() else None
            if tar_p and tar_p.is_file():
                tmp = Path(tempfile.mkdtemp())
                with tarfile.open(tar_p) as tf:
                    tf.extractall(tmp, filter="data")
                src = tmp
            else:
                src = base / Path(arch).stem
            for f in man.get("files", []):
                n += 1
                if _member_ok(src / f["path"], f):
                    ok += 1
                else:
                    bad.append(f"{base.relative_to(root).as_posix()}/{arch}:{f['path']}")
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            continue
        for f in man.get("files", []):
            n += 1
            if _member_ok(base / f["path"], f):
                ok += 1
            else:
                bad.append((base / f["path"]).relative_to(root).as_posix())
    res = {"ok": n > 0 and not bad, "files": n, "verified": ok, "bad": bad[:20]}
    print(json.dumps(res))
    if a.record:
        Path(a.record).write_text(json.dumps(res))
    return 0 if res["ok"] else 1


FLAG_AFTER = 2  # consecutive failed backup RUNS (each already retried) before the one red flag


def _raise_flag(kind: str, stamp: dict) -> bool:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import yaml

        from scripts.research.research_watchdog import GhProbe
        cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "scripts/research/research_watchdog.yaml").read_text())
        pr = cfg["ops_flags"].get("pr_number")
        probe = GhProbe()
    except Exception as ex:
        print(f"::error::cannot load the ops-flags route: {ex}")
        return False
    text = (f"🔴 kaggle-backups `{kind}`: {stamp['consecutive_failures']} consecutive failed backup runs "
            f"(each retried). Backups keep trying; nothing halted. Last good: {stamp.get('last_ok_at')}. "
            f"Detail: {json.dumps(stamp.get('details'))[:400]}")
    posted = bool(pr) and probe.post_comment(int(pr), text + "\n\n<!-- kaggle-backups-flag -->")
    pinged = probe.ping(text[:3500])
    print(f"[kaggle-backup] flag: ops-flags comment={posted} telegram={pinged}")
    return bool(posted or pinged)


def cmd_stamp(a) -> int:
    """Freshness stamp the health review reads: comms/backups/kaggle_latest.json {kinds: {<kind>: {...}}}."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev = {}
    if a.previous and Path(a.previous).exists():
        try:
            prev = json.loads(Path(a.previous).read_text())
        except Exception:
            prev = {}
    kinds = dict(prev.get("kinds") or {})
    old = kinds.get(a.kind) or {}
    details = json.loads(a.details) if a.details else {}
    ok = bool(a.ok) and not a.fail
    st = {"last_attempt_at": now, "ok": ok, "details": details,
          "last_ok_at": now if ok else old.get("last_ok_at"),
          "consecutive_failures": 0 if ok else int(old.get("consecutive_failures") or 0) + 1,
          "flagged_at": None if ok else old.get("flagged_at"), "run_id": a.run_id}
    due = (not ok) and a.flag and st["consecutive_failures"] >= FLAG_AFTER and not st["flagged_at"]
    if due and _raise_flag(a.kind, st):
        st["flagged_at"] = now
    kinds[a.kind] = st
    out = {"schema": "kaggle-backup-stamp/v1", "generated_at": now, "kinds": kinds,
           "note": "read-state: a kind absent here has never run; ok=false with a recent last_ok_at is a failed ATTEMPT, not lost data"}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(st))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["stage", "scan", "verify", "stamp"])
    ap.add_argument("--kind", default="models")
    ap.add_argument("--out", default="stage")
    ap.add_argument("--served", default="ml/served")
    ap.add_argument("--registry", default="")
    ap.add_argument("--root", default="")
    ap.add_argument("--record", default="")
    ap.add_argument("--ok", action="store_true")
    ap.add_argument("--fail", action="store_true")
    ap.add_argument("--details", default="")
    ap.add_argument("--previous", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--flag", action="store_true")
    a = ap.parse_args(argv)
    return {"stage": cmd_stage, "scan": cmd_scan, "verify": cmd_verify, "stamp": cmd_stamp}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
