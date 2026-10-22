"""Kaggle kernel body for research-script-run-kaggle.yml (RESEARCH-ROUTER, 2026-10-13).

Static and reviewed -- it is NOT generated per run and carries no unit command. The runner ships the repo as
a private dataset bundle (repo.tar.gz + spec.json = {unit, run_id}); this file unpacks it OUTSIDE
/kaggle/working (so the kernel output stays small) and runs the SAME brain every other runner uses:

    python3 scripts/research/script_run.py --unit <unit> --run-id <run_id> --run

which re-applies the allowlist (only scripts/research/*.py / scripts/backtest*.py, no shell) and writes
comms/research/<unit>/<run_id>/{run-manifest.json,verdict.json,logs/}. That directory is copied to
/kaggle/working/result/, which `kaggle kernels output` returns to the workflow. Internet is off; public data
only; no secret ever enters the kernel.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

# Injected per run by kaggle_run.bundle() (this file is pushed fresh with every run; the dataset it mounts may not be).
# None = not injected (a bare copy of this file): no staleness check.
EXPECTED = None  # BUNDLE-INJECTED


def _is_spec(path):
    try:
        d = json.load(open(path))
    except (OSError, ValueError):
        return False
    return isinstance(d, dict) and "unit" in d and "run_id" in d


# the extracted repo tree may hold other spec.json files: take the shallowest one that carries a unit and a run_id
specs = sorted((p for p in glob.glob("/kaggle/input/**/spec.json", recursive=True) if _is_spec(p)),
               key=lambda p: (p.count("/"), p), reverse=True)
if not specs:
    print("NO_SPEC: bundle dataset not mounted")
    sys.exit(3)
spec = json.load(open(specs[-1]))
unit, run_id = str(spec.get("unit", "")), str(spec.get("run_id", ""))
if not re.fullmatch(r"RQ-\d{8}-(?:\d{3}|[0-9a-f]{4}-\d{2})", unit) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", run_id):
    print("BAD_SPEC", unit, run_id)
    sys.exit(4)
if EXPECTED and (unit, run_id) != (EXPECTED["unit"], EXPECTED["run_id"]):
    # STALE DATASET MOUNT (observed 2026-10-13, runs 38419107113 and 38449812952): the kernel started on the PREVIOUS
    # dataset version, so it would execute -- and file under this run -- the wrong spec. Do not run; say so; the
    # runner sees the marker, waits and re-pushes the kernel (which re-mounts the latest version).
    print("STALE_SPEC: mounted", unit, run_id, "expected", EXPECTED["unit"], EXPECTED["run_id"])
    os.makedirs("/kaggle/working/result", exist_ok=True)
    open("/kaggle/working/result/kernel-exit.json", "w").write(json.dumps(
        {"stale_spec": True, "mounted": {"unit": unit, "run_id": run_id}, "expected": EXPECTED}))
    sys.exit(0)
bundle_dir = os.path.dirname(specs[-1])
bundle = os.path.join(bundle_dir, "repo.tar.gz")
repo = "/tmp/repo"
shutil.rmtree(repo, ignore_errors=True)
os.makedirs(repo)
if os.path.exists(bundle):
    with tarfile.open(bundle) as tf:
        for m in tf.getmembers():           # no absolute paths / traversal out of the unpack dir
            if m.name.startswith("/") or ".." in m.name.split("/"):
                print("BAD_MEMBER", m.name)
                sys.exit(5)
        tf.extractall(repo)
else:
    # OBSERVED 2026-10-13 (run 38396963370): Kaggle auto-extracts an uploaded .tar.gz, so the dataset mount holds the
    # repo tree itself, not repo.tar.gz. Find the tree by its anchor file rather than assuming a layout.
    hits = sorted(glob.glob(os.path.join(bundle_dir, "**", "scripts", "research", "script_run.py"), recursive=True))
    if not hits:
        print("NO_BUNDLE: neither repo.tar.gz nor a scripts/research/script_run.py under", bundle_dir)
        print(sorted(os.listdir(bundle_dir))[:40])
        sys.exit(6)
    root = os.path.dirname(os.path.dirname(os.path.dirname(hits[0])))
    shutil.rmtree(repo, ignore_errors=True)
    shutil.copytree(root, repo)
print("== gpu:", subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False).stdout.strip()
      if shutil.which("nvidia-smi") else "none (CPU kernel)")
env = dict(os.environ, PYTHONPATH=repo, GITHUB_SHA=str(spec.get("commit_sha", "")))
# ML-DATA-OFF-TRAINER: a unit with routing.published_data has the private market-data dataset mounted too; the dir that
# holds its MANIFEST.json is the one that CONTAINS datasets-out/, which is what ml_bakeoff resolves relative paths from.
_pub = sorted(m for m in glob.glob("/kaggle/input/**/MANIFEST.json", recursive=True)
              if os.path.isdir(os.path.join(os.path.dirname(m), "datasets-out")))
if _pub:
    env["ML_DATA_ROOT"] = os.path.dirname(_pub[0])
    print("== ML_DATA_ROOT:", env["ML_DATA_ROOT"])
# ML-NONGBDT-RUNNERS: learner wheels shipped in the bundle (internet is off). Installed --no-deps/--no-index so nothing the
# Kaggle image already pins can move; a wheel that cannot install is reported by the probe line, never a halt.
_wh = sorted(glob.glob(os.path.join(bundle_dir, "*.whl")))
if _wh:
    _r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-index", "--no-deps", *_wh],
                        capture_output=True, text=True, check=False)
    print("== learner wheels:", len(_wh), "pip rc", _r.returncode, (_r.stderr or "")[-400:])
if os.path.exists(os.path.join(repo, "scripts", "research", "probe_learners.py")):
    subprocess.run([sys.executable, "scripts/research/probe_learners.py", "--backend", "kaggle"], cwd=repo, env=env, check=False)
rc = subprocess.run([sys.executable, "scripts/research/script_run.py", "--unit", unit, "--run-id", run_id, "--run"],
                    cwd=repo, env=env).returncode
print("== script_run exit:", rc)
src = os.path.join(repo, "comms", "research", unit, run_id)
dst = "/kaggle/working/result"
shutil.rmtree(dst, ignore_errors=True)
if os.path.isdir(src):
    shutil.copytree(src, dst)
else:
    os.makedirs(dst)
open(os.path.join(dst, "kernel-exit.json"), "w").write(json.dumps({"script_run_exit": rc}))
