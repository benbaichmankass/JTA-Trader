"""Kaggle kernel body for kaggle-backups.yml mode db (KAGGLE-BACKUPS, 2026-11-05). Static and reviewed; carries no secret.

Reads the private trade-journal snapshot dataset straight from /kaggle/input (internet off, CPU only): gunzips the .dat to the kernel's
working dir while hashing, compares the raw SHA-256 with MANIFEST.json, opens the database read-only, runs PRAGMA integrity_check and
compares every table's row count with the manifest. Prints counts only, NEVER row contents. Output: /kaggle/working/result.json.
"""
import glob
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import time

t0 = time.time()
res = {"ok": False, "why": "no MANIFEST.json under /kaggle/input"}
mans = sorted(glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True))
if mans:
    base = os.path.dirname(mans[0])
    with open(mans[0]) as mf:
        man = json.load(mf)
    dat = os.path.join(base, man["file"])
    raw = "/kaggle/working/snapshot.sqlite"
    h = hashlib.sha256()
    with gzip.open(dat, "rb") as fi, open(raw, "wb") as fo:
        for chunk in iter(lambda: fi.read(1 << 20), b""):
            h.update(chunk)
            fo.write(chunk)
    sha_ok = h.hexdigest() == man["raw_sha256"]
    con = sqlite3.connect("file:" + raw + "?mode=ro", uri=True)
    integrity = con.execute("pragma integrity_check").fetchone()[0]
    counts = {n: con.execute(f'select count(*) from "{n}"').fetchone()[0] for n in man["tables"]}
    con.close()
    os.remove(raw)
    res = {"ok": bool(sha_ok and integrity == "ok" and counts == man["tables"]), "raw_sha256_matches": sha_ok,
           "integrity": integrity, "tables_match": counts == man["tables"], "tables": len(counts), "rows": sum(counts.values()),
           "raw_bytes": man["raw_bytes"], "gz_bytes": os.path.getsize(dat), "seconds": round(time.time() - t0, 1),
           "mount_dir": base, "listing": sorted(os.listdir(base))}
print(json.dumps(res))
with open("/kaggle/working/result.json", "w") as out:
    out.write(json.dumps(res))
shutil.rmtree("/kaggle/working/__pycache__", ignore_errors=True)
