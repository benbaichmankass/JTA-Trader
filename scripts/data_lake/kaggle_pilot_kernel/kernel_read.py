"""Kaggle kernel body for hf-lake-kaggle-pilot.yml (HF-LAKE-STORAGE-403, 2026-11-05).

Static and reviewed; carries no secret. Internet off, CPU only. Measures how a Kaggle kernel READS the private pilot dataset
mounted under /kaggle/input: re-hashes every shard listed in MANIFEST.json (MB/s) and extracts one parquet member from a
shard the way a trainer would. Output: /kaggle/working/result.json.
"""
import glob
import hashlib
import json
import os
import time

mans = sorted(glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True))
res = {"ok": False, "why": "no MANIFEST.json under /kaggle/input"}
if mans:
    base = os.path.dirname(mans[0])
    with open(mans[0]) as mf:
        man = json.load(mf)
    t0, nbytes, bad, layout = time.time(), 0, [], {"tar": 0, "extracted": 0}
    for f in man["files"]:
        p = os.path.join(base, f["path"])
        if os.path.isfile(p):
            layout["tar"] += 1
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if os.path.getsize(p) != f["bytes"] or h.hexdigest() != f["sha256"]:
                bad.append(f["path"])
            else:
                nbytes += f["bytes"]
        elif os.path.isdir(p[:-4]):  # Kaggle unpacks <shard>.tar into a folder <shard>/ (observed 2026-11-05)
            layout["extracted"] += 1
            n, tot = 0, 0
            for root, _dirs, files in os.walk(p[:-4]):
                for name in files:
                    with open(os.path.join(root, name), "rb") as fh:
                        tot += len(fh.read())
                    n += 1
            if n != f.get("n_partitions") or tot != f.get("member_bytes"):
                bad.append(f"{f['path']}: extracted {n} files/{tot} B, manifest {f.get('n_partitions')}/{f.get('member_bytes')}")
            else:
                nbytes += tot
        else:
            bad.append(f["path"] + ": missing")
    dt = max(time.time() - t0, 1e-6)
    one = None
    try:
        t1 = time.time()
        pq = None
        for root, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".parquet"):
                    pq = os.path.join(root, name)
                    break
            if pq:
                break
        with open(pq, "rb") as fh:
            data = fh.read()
        one = {"member": os.path.relpath(pq, base), "bytes": len(data), "seconds": round(time.time() - t1, 3)}
    except Exception as e:  # noqa: BLE001
        one = {"error": str(e)[:200]}
    res = {"ok": not bad, "files": len(man["files"]), "bad": bad, "hashed_bytes": nbytes, "layout": layout, "hash_seconds": round(dt, 2),
           "hash_MBps": round(nbytes / 1e6 / dt, 1), "one_member_read": one, "mount_dir": base,
           "listing": sorted(os.listdir(base))[:20]}
print(json.dumps(res))
with open("/kaggle/working/result.json", "w") as out:
    out.write(json.dumps(res))
