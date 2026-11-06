#!/usr/bin/env python3
# wiring: .github/workflows/kaggle-backups.yml (mode db: streamed to the trainer over SSH as `python3 - <args>`; nothing is installed there)
"""Consistent, compressed snapshot of ONE SQLite database, taken with the SQLite online-backup API. Runs ON THE TRAINER.

    python3 - --src data/trade_journal.db --out /tmp/tj-20261108 --need-free-gb 6   < trainer_db_snapshot.py

Writes <out>.sqlite.gz and prints ONE JSON line: raw/gz sizes and SHA-256, integrity_check, per-table row counts, source
mtime/size and how the source was opened. The source is opened READ-ONLY (`mode=ro`, else `immutable=1`, recorded); nothing
is written to the source. The raw copy is deleted as soon as it is compressed. Refuses (exit 3) when the disk cannot hold the
temporary raw copy. Never reads or prints row contents.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--need-free-gb", type=float, default=6.0)
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    if not os.path.isfile(src):
        print(json.dumps({"ok": False, "why": "source missing", "src": src}))
        return 2
    src_bytes = os.path.getsize(src)
    free = shutil.disk_usage(os.path.dirname(a.out) or "/tmp").free
    need = max(int(a.need_free_gb * 1e9), int(src_bytes * 1.5))
    if free < need:
        print(json.dumps({"ok": False, "why": "not enough free disk for the temporary raw copy", "free": free, "need": need}))
        return 3
    raw, gz = a.out + ".sqlite", a.out + ".sqlite.gz"
    for p in (raw, gz):
        if os.path.exists(p):
            os.remove(p)
    mode = "ro"
    try:
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        s.execute("select count(*) from sqlite_master").fetchone()
    except sqlite3.Error:
        mode = "immutable"
        s = sqlite3.connect(f"file:{src}?immutable=1", uri=True)
    d = sqlite3.connect(raw)
    try:
        s.backup(d)  # the online-backup API: a transactionally consistent copy
    finally:
        d.close()
        s.close()
    chk = sqlite3.connect(f"file:{raw}?mode=ro", uri=True)
    integrity = chk.execute("pragma integrity_check").fetchone()[0]
    tables = {}
    for (name,) in chk.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
        tables[name] = chk.execute(f'select count(*) from "{name}"').fetchone()[0]
    chk.close()
    raw_bytes, raw_sha = os.path.getsize(raw), sha256_file(raw)
    with open(raw, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
    os.remove(raw)
    print(json.dumps({"ok": integrity == "ok", "integrity": integrity, "read_mode": mode, "src": a.src, "src_bytes": src_bytes,
                      "src_mtime": int(os.path.getmtime(src)), "raw_bytes": raw_bytes, "raw_sha256": raw_sha,
                      "gz_path": gz, "gz_bytes": os.path.getsize(gz), "gz_sha256": sha256_file(gz), "tables": tables}))
    return 0 if integrity == "ok" else 4


if __name__ == "__main__":
    sys.exit(main())
