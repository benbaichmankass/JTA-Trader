"""checklist.py's "wrote" line names the store that took the write (2026-11-13, LTR-GRADER-COVERAGE triple note).

After the WSD-S4 freeze a row write goes to work_store.db and the row file is not touched; the old line printed
the file path, so a lane read an unchanged mtime as a silent no-op and re-ran `note --append`."""
from pathlib import Path

from scripts.ops import checklist as ck


def test_frozen_row_write_names_the_work_store(monkeypatch, tmp_path):
    monkeypatch.setattr(ck._store, "_frozen_canonical", lambda base: True)
    p = tmp_path / ck._store.STORE / "LTR-GRADER-COVERAGE.json"
    line = ck._wrote_line(p, tmp_path)
    assert "work store" in line and "NOT changed" in line
    assert "work.py get LTR-GRADER-COVERAGE" in line


def test_unfrozen_row_write_names_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ck._store, "_frozen_canonical", lambda base: False)
    p = tmp_path / ck._store.STORE / "A.json"
    assert ck._wrote_line(p, tmp_path) == f"checklist: wrote {Path(ck._store.STORE) / 'A.json'}"


def test_header_write_always_names_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ck._store, "_frozen_canonical", lambda base: True)
    p = tmp_path / ck._store.STORE / ck._store.HEADER
    assert "work store" not in ck._wrote_line(p, tmp_path)
