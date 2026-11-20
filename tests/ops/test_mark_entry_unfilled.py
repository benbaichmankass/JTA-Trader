"""mark-entry-unfilled (2026-11-20, trade 8034 / db-integrity INV-2): the planted-control self-test
must pass in CI, and the INV-2 checker must accept what the script writes."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))

meu = importlib.import_module("mark_entry_unfilled")


def test_self_test_passes():
    assert meu._self_test() == 0


def test_marker_is_the_provenance_constant():
    from src.runtime.provenance import UNMEASURED_MARKER
    assert meu.UNMEASURED == UNMEASURED_MARKER


def test_cli_refuses_without_named_targets(capsys):
    assert meu.main(["--reason", "x"]) == 2
    assert meu.main(["--trade-ids", "8034"]) == 2
    assert meu.main(["--trade-ids", "80a4", "--reason", "x"]) == 2


def test_a_wrong_db_path_refuses_and_never_creates_a_file(tmp_path):
    """Issue #27636: the first live run opened a path that was not the journal, and a plain
    sqlite3.connect would have created an empty file there. mode=rw refuses instead."""
    missing = tmp_path / "nope.db"
    assert meu.main(["--db", str(missing), "--trade-ids", "8034", "--reason", "x"]) == 1
    assert not missing.exists()
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert meu.main(["--db", str(empty), "--trade-ids", "8034", "--reason", "x"]) == 1


def test_wrapper_resolves_the_db_after_loading_secrets_and_checks_it():
    text = (REPO / "scripts" / "ops" / "mark_entry_unfilled_action.sh").read_text()
    assert text.index("load_runtime_secrets\nDB_PATH=") >= 0
    assert "SELECT COUNT(*) FROM trades" in text
    assert text.count('--db "${DB_PATH}"') == 2
