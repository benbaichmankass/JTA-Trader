"""VM-SPARSE-SYNC (2026-11-02): the live VM's sync must never check out bulk
research artefacts, and must still check out every path the runtime reads.

#22365 put 21.6 GB of research caches (comms/research/<unit>/<run>/streams/*.pkl)
on main; ict-git-sync's `git fetch` + `git reset --hard origin/main` filled the
VM's 45G disk and blinded the web API. This test extracts the REAL fetch/sparse/
reset block from scripts/deploy_pull_restart.sh (between its VM-SPARSE-SYNC
markers) and runs it in a simulated VM clone against a file:// origin, using the
REAL deploy/vm-sparse-checkout patterns.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "deploy_pull_restart.sh"
PATTERNS = REPO / "deploy" / "vm-sparse-checkout"

# Paths the VM runtime reads (grep of src/, scripts/ops/, config/ pointers,
# 2026-11-02) — every one MUST stay checked out.
RUNTIME_PATHS = [
    "src/main.py",
    "scripts/deploy_pull_restart.sh",
    "config/strategies.yaml",
    "research/queue/RQ-1.yaml",
    "docs/research/exit-refinement-coverage.json",
    "comms/live_review/row.json",
    "comms/research/RQ-20261007-001/local-5fd0163ca/verdict.json",
    "comms/research/desk_edge/levers/bybit-fee-measured-2026-10-27.json",
    "comms/research/soak_book_grade/2026-11-01.json",
    "comms/research/r3_cost_fidelity/2026-09-25.json",
    "comms/research/ltr_tighten_optimize/verdict.json",
    "comms/research/RQ-X/1/run-manifest.json",
    "comms/research/RQ-X/1/logs/cmd-0.log",
    "comms/research/RQ-X/1/arms/A__trades.jsonl",
    "comms/research/RQ-X/1/PREREGISTRATION.md",
    "data/not_research.csv",  # exclusions are scoped to comms/research only
]
# Bulk research artefacts — must NOT be on the VM's disk.
CACHE_PATHS = [
    "comms/research/RQ-20261101-a508-01/41357669686/streams/klines12/BTCUSDT.pkl",
    "comms/research/RQ-20261101-a508-01/41357669686/work/table.pkl",
    "comms/research/RQ-20261101-a508-01/41357669686/work/notes.json",
    "comms/research/RQ-20261014-d6e7-01/38663653665/candles/ADAUSDT_2h_378d.csv",
    "comms/research/RQ-Y/1/feat.npz",
    "comms/research/RQ-Y/1/folds.json.gz",
    "comms/research/RQ-Y/1/rows.parquet",
    "comms/research/RQ-Y/1/table.csv",
]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout


def _write(root: Path, rel: str, data: bytes | str = "x\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode() if isinstance(data, str) else data)


def _sync_block() -> str:
    text = SCRIPT.read_text()
    start = text.index("# >>> VM-SPARSE-SYNC begin")
    end = text.index("# <<< VM-SPARSE-SYNC end")
    return "set -euo pipefail\n" + text[start:end]


def _run_sync(vm: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", _sync_block()], cwd=vm, capture_output=True, text=True)


def _missing_objects(vm: Path) -> set[str]:
    out = _git(vm, "rev-list", "--objects", "--all", "--missing=print")
    return {line[1:].strip() for line in out.splitlines() if line.startswith("?")}


@pytest.fixture()
def world(tmp_path: Path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    vm = tmp_path / "vm"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    # Commit 1 = the pre-fix world: caches already on main, no sparse file,
    # VM is a FULL clone that already has them on disk (today's VM state).
    for rel in RUNTIME_PATHS + CACHE_PATHS:
        _write(seed, rel)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c1")
    _git(seed, "remote", "add", "origin", origin.as_uri())
    _git(seed, "push", "-q", "origin", "main")
    _git(tmp_path, "clone", "-q", origin.as_uri(), str(vm))
    for rel in CACHE_PATHS:
        assert (vm / rel).exists()
    return origin, seed, vm


def test_patterns_file_is_versioned_and_scoped():
    lines = [ln.strip() for ln in PATTERNS.read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines[0] == "/*", "first pattern must include everything"
    # LTR-GRADER-COVERAGE (b), 2026-11-14: the generated block may RE-INCLUDE exact committed candle files under
    # comms/research (tests/test_ltr_candle_allowlist.py pins them: each exists and is a .csv). Nothing else may.
    for ln in lines[1:]:
        assert ln.startswith("!/comms/research/") or (ln.startswith("/comms/research/") and ln.endswith(".csv")
                                                      and "*" not in ln), f"pattern escapes comms/research: {ln}"


def test_sparse_sync_removes_caches_keeps_runtime_and_is_idempotent(world):
    origin, seed, vm = world
    # Commit 2 = the fix lands: sparse file on main, plus a NEW 6 MB cache blob.
    _write(seed, "deploy/vm-sparse-checkout", PATTERNS.read_text())
    big_cache = "comms/research/RQ-Z/9/streams/klines12/ETHUSDT.pkl"
    _write(seed, big_cache, os.urandom(6 * 1024 * 1024))
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c2")
    _git(seed, "push", "-q", "origin", "main")
    big_oid = _git(seed, "rev-parse", f"HEAD:{big_cache}").strip()

    r = _run_sync(vm)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Sparse checkout patterns applied" in r.stdout
    assert _git(vm, "rev-parse", "HEAD") == _git(seed, "rev-parse", "HEAD")
    for rel in RUNTIME_PATHS + ["deploy/vm-sparse-checkout"]:
        assert (vm / rel).is_file(), f"runtime path missing on VM: {rel}"
    for rel in CACHE_PATHS + [big_cache]:
        assert not (vm / rel).exists(), f"cache checked out on VM: {rel}"
    # The blob filter kept the >5 MB cache out of .git entirely.
    assert big_oid in _missing_objects(vm)
    # The tree is clean (excluded entries are skip-worktree, not deletions).
    assert _git(vm, "status", "--porcelain") == ""

    # Idempotent: a second tick changes nothing and still succeeds.
    r2 = _run_sync(vm)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    for rel in RUNTIME_PATHS:
        assert (vm / rel).is_file()
    for rel in CACHE_PATHS + [big_cache]:
        assert not (vm / rel).exists()


def test_blob_filter_is_safe_with_reset_hard_for_needed_big_blobs(world):
    """A >limit blob the runtime DOES need is lazily fetched by reset --hard."""
    origin, seed, vm = world
    _write(seed, "deploy/vm-sparse-checkout", PATTERNS.read_text())
    big_runtime = "src/models/runtime_model.bin"
    payload = os.urandom(6 * 1024 * 1024)
    _write(seed, big_runtime, payload)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c2-big-runtime")
    _git(seed, "push", "-q", "origin", "main")

    r = _run_sync(vm)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (vm / big_runtime).read_bytes() == payload
    assert _git(vm, "status", "--porcelain") == ""


def test_missing_patterns_file_leaves_checkout_unchanged(world):
    """No sparse file on main -> a warning and a plain full sync, never a halt."""
    origin, seed, vm = world
    _write(seed, "src/new_runtime.py")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c2-no-sparse")
    _git(seed, "push", "-q", "origin", "main")
    r = _run_sync(vm)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "unreadable" in r.stdout
    assert (vm / "src/new_runtime.py").is_file()
