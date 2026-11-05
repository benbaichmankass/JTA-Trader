"""Kaggle kernel body for kaggle-backups.yml (KAGGLE-BACKUPS, 2026-11-05). Static and reviewed; carries no secret.

Compute angle of the Models pilot: can a Kaggle notebook LOAD the backed-up model files directly from /kaggle/input (no download,
internet off, CPU only)? Re-hashes every file in each MANIFEST.json found under /kaggle/input and json-loads each served
model.json. Output: /kaggle/working/result.json. This is a backup and compute surface; it is never a serving path.
"""
import glob
import hashlib
import json
import os
import time

t0 = time.time()
mans = sorted(glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True))
res = {"ok": False, "why": "no MANIFEST.json under /kaggle/input", "manifests": []}
tree = []
for root, _dirs, files in os.walk("/kaggle/input"):
    for name in files:
        tree.append(os.path.relpath(os.path.join(root, name), "/kaggle/input"))
    if len(tree) > 400:
        break
bad, ok, loaded = [], 0, []
for mp in mans:
    base = os.path.dirname(mp)
    with open(mp) as mf:
        man = json.load(mf)
    for f in man.get("files", []):
        p = os.path.join(base, f["path"])
        if not os.path.isfile(p):
            bad.append(p + ": missing")
            continue
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if os.path.getsize(p) != f["bytes"] or h.hexdigest() != f["sha256"]:
            bad.append(p + ": checksum mismatch")
        else:
            ok += 1
        if p.endswith("model.json"):
            t1 = time.time()
            try:
                with open(p) as jf:
                    obj = json.load(jf)
                loaded.append({"file": f["path"], "type": type(obj).__name__, "top_keys": sorted(obj)[:6] if isinstance(obj, dict) else None,
                               "load_seconds": round(time.time() - t1, 3)})
            except Exception as e:  # noqa: BLE001
                bad.append(p + ": json load failed " + str(e)[:80])
    res["manifests"].append({"manifest": os.path.relpath(mp, "/kaggle/input"), "files": len(man.get("files", []))})
res.update({"ok": bool(mans) and not bad, "files_ok": ok, "bad": bad[:20], "served_models_loaded": loaded,
            "seconds": round(time.time() - t0, 2), "tree_sample": tree[:12], "n_input_files": len(tree)})
print(json.dumps(res))
with open("/kaggle/working/result.json", "w") as out:
    out.write(json.dumps(res))
