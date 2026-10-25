#!/usr/bin/env python3
"""Consistent, verified, compressed snapshot of one SQLite DB (runs ON the live VM).

JOURNAL-OFFVM-BACKUP. Piped over ssh by .github/workflows/journal-offvm-backup.yml
(`ssh host python3 - ARGS < this_file`) so it does not depend on the VM's clone
being up to date. Stdlib only.

READ-ONLY on the live DB: it is opened `mode=ro` and copied with SQLite's online
backup API (`pages=-1`, one read transaction) -- never a raw cp of a WAL DB.
The snapshot is integrity-checked, row-counted (counts only, no contents),
gzipped, and hashed. Prints ONE JSON line on stdout; nothing else.
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys


def _counts(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--counts-only", action="store_true",
                    help="read-only table row counts of --db; no snapshot")
    a = ap.parse_args()

    if not os.path.exists(a.db):
        print(json.dumps({"label": a.label, "state": "absent"}))
        return 0
    if a.counts_only:
        print(json.dumps({"label": a.label, "counts": _counts(a.db)}))
        return 0
    os.makedirs(a.out_dir, mode=0o700, exist_ok=True)
    snap = os.path.join(a.out_dir, f"{a.label}.snap.db")
    gz = os.path.join(a.out_dir, f"{a.label}.db.gz")
    for p in (snap, gz):
        if os.path.exists(p):
            os.remove(p)

    src = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    dst = sqlite3.connect(snap)
    src.backup(dst, pages=-1)
    dst.close()
    src.close()

    chk = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    integrity = [r[0] for r in chk.execute("PRAGMA integrity_check")]
    chk.close()
    ok = integrity == ["ok"]
    out = {"label": a.label, "state": "ok" if ok else "integrity_failed",
           "integrity": "ok" if ok else integrity[:3]}
    if ok:
        out["counts"] = _counts(snap)
        out["raw_bytes"] = os.path.getsize(snap)
        with open(snap, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
        h = hashlib.sha256()
        with open(gz, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        out["gz_bytes"] = os.path.getsize(gz)
        out["sha256"] = h.hexdigest()
        out["gz_path"] = gz
    for extra in (snap, snap + "-wal", snap + "-shm"):
        if os.path.exists(extra):
            os.remove(extra)
    print(json.dumps(out))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
