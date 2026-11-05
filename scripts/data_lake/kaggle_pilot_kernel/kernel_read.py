"""Kaggle kernel body for hf-lake-kaggle-pilot.yml (HF-LAKE-STORAGE-403, 2026-11-05).

Static and reviewed; carries no secret. Internet off, CPU only. Measures how a Kaggle kernel READS the private pilot dataset
mounted under /kaggle/input: re-hashes every shard listed in MANIFEST.json (MB/s) and extracts one parquet member from a
shard the way a trainer would. Output: /kaggle/working/result.json.
"""
import glob
import hashlib
import json
import os
import tarfile
import time

mans = sorted(glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True))
res = {"ok": False, "why": "no MANIFEST.json under /kaggle/input"}
if mans:
    base = os.path.dirname(mans[0])
    with open(mans[0]) as mf:
        man = json.load(mf)
    t0, nbytes, bad = time.time(), 0, []
    for f in man["files"]:
        p = os.path.join(base, f["path"])
        h = hashlib.sha256()
        try:
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            bad.append(f["path"])
            continue
        if os.path.getsize(p) != f["bytes"] or h.hexdigest() != f["sha256"]:
            bad.append(f["path"])
        else:
            nbytes += f["bytes"]
    dt = max(time.time() - t0, 1e-6)
    one = None
    try:
        shard = min(glob.glob(os.path.join(base, "crypto-um_perp-1m-*.tar")))
        t1 = time.time()
        with tarfile.open(shard) as tf:
            m = next(x for x in tf.getmembers() if x.name.endswith(".parquet"))
            data = tf.extractfile(m).read()
        one = {"member": m.name, "bytes": len(data), "seconds": round(time.time() - t1, 3)}
    except Exception as e:  # noqa: BLE001
        one = {"error": str(e)[:200]}
    res = {"ok": not bad, "files": len(man["files"]), "bad": bad, "hashed_bytes": nbytes, "hash_seconds": round(dt, 2),
           "hash_MBps": round(nbytes / 1e6 / dt, 1), "one_member_read": one, "mount_dir": base,
           "listing": sorted(os.listdir(base))[:20]}
print(json.dumps(res))
with open("/kaggle/working/result.json", "w") as out:
    out.write(json.dumps(res))
