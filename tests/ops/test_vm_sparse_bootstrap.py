"""vm-sparse-bootstrap (VM-SPARSE-SYNC, 2026-11-02): the one-time recovery that
runs on the full-disk live VM WITHOUT its on-disk scripts and WITHOUT a prior
fetch. Run here exactly as the workflow runs it: piped on stdin to `bash -s`,
with the sparse patterns base64-encoded, against a simulated VM clone that is a
FULL (non-partial) clone with the caches already checked out.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "vm_sparse_bootstrap.sh"
PATTERNS = REPO / "deploy" / "vm-sparse-checkout"

RUNTIME = [
    "src/main.py",
    "config/strategies.yaml",
    "comms/research/RQ-20261007-001/local-5fd0163ca/verdict.json",
    "comms/research/desk_edge/levers/bybit-fee-measured-2026-10-27.json",
    "comms/research/RQ-X/1/logs/cmd-0.log",
    "comms/research/RQ-X/1/arms/A__trades.jsonl",
    "data/not_research.csv",
]
CACHE = [
    "comms/research/RQ-20261101-a508-01/41357669686/streams/klines12/BTCUSDT.pkl",
    "comms/research/RQ-20261101-a508-01/41357669686/work/table.pkl",
    "comms/research/RQ-20261101-a508-01/41357669686/work/notes.json",
    "comms/research/RQ-Y/1/candles/ADA.csv",
    "comms/research/RQ-Y/1/feat.npz",
    "comms/research/RQ-Y/1/folds.json.gz",
    "comms/research/top_level.csv",
]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout


def _write(root: Path, rel: str, data: bytes = b"x\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _fakebin(tmp: Path) -> Path:
    b = tmp / "bin"
    b.mkdir()
    log = tmp / "systemctl.log"
    (b / "systemctl").write_text(
        f'#!/bin/sh\necho "$@" >> {log}\n'
        'case "$*" in "is-active --quiet ict-git-sync.timer") exit 0;; '
        '"is-active --quiet ict-git-sync.service") exit 3;; esac\nexit 0\n')
    (b / "sudo").write_text('#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n')
    for f in b.iterdir():
        f.chmod(0o755)
    return b


def _run(vm: Path, fakebin: Path, apply: bool) -> subprocess.CompletedProcess:
    env = {**os.environ, "REPO_DIR": str(vm), "PATH": f"{fakebin}:{os.environ['PATH']}",
           "ACTION_APPLY": "true" if apply else "",
           "SPARSE_PATTERNS_B64": base64.b64encode(PATTERNS.read_bytes()).decode()}
    with SCRIPT.open("rb") as fh:  # exactly how system-actions.yml runs it
        return subprocess.run(["bash", "-s"], stdin=fh, cwd="/", env=env,
                              capture_output=True, text=True)


@pytest.fixture()
def world(tmp_path: Path):
    origin, seed, vm = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "vm"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    for rel in RUNTIME + CACHE:
        _write(seed, rel)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c1 (#22365 shape: caches on main)")
    _git(seed, "remote", "add", "origin", origin.as_uri())
    _git(seed, "push", "-q", "origin", "main")
    _git(tmp_path, "clone", "-q", origin.as_uri(), str(vm))  # FULL clone = today's VM
    # main moves on (the VM never got it: its fetch died on a full disk)
    _write(seed, "deploy/vm-sparse-checkout", PATTERNS.read_bytes())
    _write(seed, "src/new_code.py")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "c2")
    _git(seed, "push", "-q", "origin", "main")
    # failed-fetch debris
    (vm / ".git/objects/pack/tmp_pack_ABC123").write_bytes(b"\0" * 4096)
    (vm / ".git/packed-refs.new").write_text("")
    return seed, vm, _fakebin(tmp_path), tmp_path / "systemctl.log"


def test_find_shapes_match_the_pattern_file():
    """The script's deletion set must be exactly the pattern file's exclusions."""
    text = SCRIPT.read_text()
    dirs = re.search(r"CACHE_DIRS=\(([^)]*)\)", text).group(1).split()
    exts = re.search(r"CACHE_EXTS=\(([^)]*)\)", text).group(1).split()
    excl = [ln.strip() for ln in PATTERNS.read_text().splitlines() if ln.startswith("!")]
    want_dirs = sorted(m.group(1) for ln in excl if (m := re.fullmatch(r"!/comms/research/\*\*/([^*./]+)/", ln)))
    want_exts = sorted(m.group(1) for ln in excl if (m := re.fullmatch(r"!/comms/research/\*\*/\*\.(\w+)", ln)))
    assert sorted(dirs) == want_dirs and sorted(exts) == want_exts
    assert len(want_dirs) + len(want_exts) == len(excl), "unparsed exclusion line"


def test_dry_run_changes_nothing(world):
    seed, vm, fakebin, log = world
    head = _git(vm, "rev-parse", "HEAD")
    r = _run(vm, fakebin, apply=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY-RUN" in r.stdout and "7 files" in r.stdout
    assert _git(vm, "rev-parse", "HEAD") == head
    for rel in CACHE:
        assert (vm / rel).exists()
    assert not log.exists() or "stop" not in log.read_text()


def test_apply_frees_caches_syncs_and_restores_timer(world):
    seed, vm, fakebin, log = world
    r = _run(vm, fakebin, apply=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(vm, "rev-parse", "HEAD") == _git(seed, "rev-parse", "HEAD")
    for rel in RUNTIME + ["src/new_code.py", "deploy/vm-sparse-checkout"]:
        assert (vm / rel).is_file(), rel
    for rel in CACHE:
        assert not (vm / rel).exists(), rel
    assert not (vm / ".git/objects/pack/tmp_pack_ABC123").exists()
    assert not (vm / ".git/packed-refs.new").exists()
    assert _git(vm, "config", "remote.origin.promisor").strip() == "true"
    assert _git(vm, "config", "remote.origin.partialclonefilter").strip() == "blob:limit=5m"
    assert _git(vm, "status", "--porcelain") == ""
    calls = log.read_text()
    assert "stop ict-git-sync.timer" in calls and "start ict-git-sync.timer" in calls
    assert "ict-trader" not in calls, "must never touch the trader"
    # idempotent second run
    r2 = _run(vm, fakebin, apply=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_apply_refuses_without_patterns(world):
    seed, vm, fakebin, log = world
    env = {**os.environ, "REPO_DIR": str(vm), "PATH": f"{fakebin}:{os.environ['PATH']}",
           "ACTION_APPLY": "true", "SPARSE_PATTERNS_B64": ""}
    with SCRIPT.open("rb") as fh:
        r = subprocess.run(["bash", "-s"], stdin=fh, env=env, capture_output=True, text=True)
    assert r.returncode == 2
    for rel in CACHE:
        assert (vm / rel).exists()


def _run_with_b64(vm: Path, fakebin: Path, b64: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "REPO_DIR": str(vm), "PATH": f"{fakebin}:{os.environ['PATH']}",
           "ACTION_APPLY": "true", "SPARSE_PATTERNS_B64": b64}
    with SCRIPT.open("rb") as fh:
        return subprocess.run(["bash", "-s"], stdin=fh, cwd="/", env=env,
                              capture_output=True, text=True)


def test_apply_refuses_a_pattern_file_without_the_root_line(world):
    """CI-SPARSE-BOOTSTRAP-FLAKE: the '/*' check is a bash match, not a pipe."""
    seed, vm, fakebin, log = world
    body = b"\n".join(ln for ln in PATTERNS.read_bytes().splitlines() if ln.strip() != b"/*") + b"\n"
    r = _run_with_b64(vm, fakebin, base64.b64encode(body).decode())
    assert r.returncode == 2 and "no '/*' line" in r.stderr, r.stderr
    for rel in CACHE:
        assert (vm / rel).exists()


def test_apply_refuses_undecodable_patterns(world):
    seed, vm, fakebin, log = world
    r = _run_with_b64(vm, fakebin, "!!!not-base64!!!")
    assert r.returncode == 2 and "not valid base64" in r.stderr, r.stderr


def test_repeated_applies_never_refuse_valid_patterns(world):
    """Five back-to-back applies with the real pattern file all succeed (the CI flake was run 2 refusing)."""
    seed, vm, fakebin, log = world
    for i in range(5):
        r = _run(vm, fakebin, apply=True)
        assert r.returncode == 0, f"run {i + 1}: {r.stdout}{r.stderr}"
