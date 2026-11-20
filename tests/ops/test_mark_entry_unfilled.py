"""mark-entry-unfilled (2026-11-20, trade 8034 / db-integrity INV-2): the planted-control self-test
must pass in CI, and the INV-2 checker must accept what the script writes."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import mark_entry_unfilled as meu


def test_self_test_passes():
    assert meu._self_test() == 0


def test_marker_is_the_provenance_constant():
    from src.runtime.provenance import UNMEASURED_MARKER
    assert meu.UNMEASURED == UNMEASURED_MARKER


def test_cli_refuses_without_named_targets(capsys):
    assert meu.main(["--reason", "x"]) == 2
    assert meu.main(["--trade-ids", "8034"]) == 2
    assert meu.main(["--trade-ids", "80a4", "--reason", "x"]) == 2
