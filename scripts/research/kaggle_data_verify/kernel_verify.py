"""Kaggle kernel body for ml-data-export-kaggle.yml (ML-DATA-OFF-TRAINER, 2026-10-13).

Proof that the PRIVATE dataset `metis-market-data` is readable from inside a Kaggle kernel (internet off, CPU only,
no GPU quota spent) and equals what the exporter staged: re-hashes every file listed in MANIFEST.json. Static and
reviewed; carries no secret and no unit command. Output: /kaggle/working/result.json.
"""
import glob
import hashlib
import json
import os

mans = sorted(glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True))
res = {"ok": False, "why": "no MANIFEST.json under /kaggle/input", "files_ok": 0, "files_bad": []}
if mans:
    base = os.path.dirname(mans[0])
    man = json.load(open(mans[0]))
    bad, ok = [], 0
    for f in man["files"]:
        p = os.path.join(base, f["path"])
        if not os.path.isfile(p):
            bad.append({"path": f["path"], "why": "missing"})
            continue
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if os.path.getsize(p) != f["bytes"] or h.hexdigest() != f["sha256"]:
            bad.append({"path": f["path"], "why": "checksum/size mismatch"})
        else:
            ok += 1
    res = {"ok": not bad, "files_ok": ok, "files_bad": bad, "mount_dir": base,
           "stale_shards": man.get("stale_shards", []), "generated_at": man.get("generated_at")}
print(json.dumps(res))
open("/kaggle/working/result.json", "w").write(json.dumps(res))
