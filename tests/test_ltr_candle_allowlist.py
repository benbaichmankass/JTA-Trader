"""LTR-GRADER-COVERAGE option (b): the VM sparse checkout re-includes exactly the committed candle files the live-review
pricer selects for live legs, so the reviewer prices them on the VM with no network."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ops import ltr_candle_allowlist as A  # noqa: E402


def _block_paths() -> list:
    text = A.PATTERNS.read_text(encoding="utf-8")
    assert A.BEGIN in text and A.END in text, "the generated block is missing from deploy/vm-sparse-checkout"
    block = text.split(A.BEGIN, 1)[1].split(A.END, 1)[0]
    return [ln.strip()[1:] for ln in block.splitlines() if ln.strip().startswith("/")]


def test_every_reinclude_is_an_existing_committed_csv_under_research():
    paths = _block_paths()
    assert paths, "no candle file is re-included"
    for rel in paths:
        assert rel.startswith("comms/research/") and rel.endswith(".csv") and "*" not in rel, rel
        assert (ROOT / rel).is_file(), f"re-included file is not in the repo: {rel}"


def test_block_comes_after_the_exclusions_it_overrides():
    lines = [ln.strip() for ln in A.PATTERNS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    begin = lines.index(A.BEGIN)
    last_exclusion = max(i for i, ln in enumerate(lines) if ln.startswith("!/comms/research/"))
    assert begin > last_exclusion, "a re-include must follow the exclusions (last matching pattern wins)"


def test_apply_block_is_idempotent():
    text = A.PATTERNS.read_text(encoding="utf-8")
    block = text.split(A.BEGIN, 1)[1].split(A.END, 1)[0]
    rebuilt = A.apply_block(text, A.BEGIN + block + A.END + "\n")
    assert A.apply_block(rebuilt, A.BEGIN + block + A.END + "\n") == rebuilt


def test_real_sparse_checkout_keeps_the_reincluded_file_and_drops_its_sibling(tmp_path):
    """Positive and negative control on REAL git with the REAL pattern file."""
    keep = _block_paths()[0]
    sibling = str(Path(keep).with_name("ZZZUSDT_1h_9d.csv"))
    src = tmp_path / "src"
    for rel, body in ((keep, "keep\n"), (sibling, "drop\n"), ("other/x.txt", "x\n")):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(body)

    def git(*a, cwd):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                       env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    git("init", "-q", "-b", "main", cwd=src)
    git("add", "-A", cwd=src)
    git("commit", "-qm", "seed", cwd=src)
    vm = tmp_path / "vm"
    git("clone", "-q", "--no-checkout", str(src), str(vm), cwd=tmp_path)
    git("config", "core.sparseCheckout", "true", cwd=vm)
    git("config", "core.sparseCheckoutCone", "false", cwd=vm)
    (vm / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (vm / ".git" / "info" / "sparse-checkout").write_text(A.PATTERNS.read_text(encoding="utf-8"))
    git("checkout", "-q", "main", cwd=vm)
    assert (vm / keep).is_file(), "the re-included candle file was not checked out"
    assert not (vm / sibling).exists(), "a non-listed candle file leaked past the exclusion"
    assert (vm / "other" / "x.txt").is_file()
