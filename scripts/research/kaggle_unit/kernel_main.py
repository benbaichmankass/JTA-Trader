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

specs = sorted(glob.glob("/kaggle/input/**/spec.json", recursive=True))
if not specs:
    print("NO_SPEC: bundle dataset not mounted"); sys.exit(3)
spec = json.load(open(specs[-1]))
unit, run_id = str(spec.get("unit", "")), str(spec.get("run_id", ""))
if not re.fullmatch(r"RQ-\d{8}-(?:\d{3}|[0-9a-f]{4}-\d{2})", unit) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", run_id):
    print("BAD_SPEC", unit, run_id); sys.exit(4)
bundle = os.path.join(os.path.dirname(specs[-1]), "repo.tar.gz")
repo = "/tmp/repo"
shutil.rmtree(repo, ignore_errors=True)
os.makedirs(repo)
with tarfile.open(bundle) as tf:
    for m in tf.getmembers():           # no absolute paths / traversal out of the unpack dir
        if m.name.startswith("/") or ".." in m.name.split("/"):
            print("BAD_MEMBER", m.name); sys.exit(5)
    tf.extractall(repo)
print("== gpu:", subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False).stdout.strip())
env = dict(os.environ, PYTHONPATH=repo, GITHUB_SHA=str(spec.get("commit_sha", "")))
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
