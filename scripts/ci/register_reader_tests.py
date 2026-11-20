#!/usr/bin/env python3
"""Every test file that reads the work register: the export's validation set, DERIVED, not listed.

EXPORT-VALIDATION-GAP (2026-11-20). The first work-store export run (44648031388) validated its tree
with a hand-picked subset: five guards plus ``tests/test_checklist*.py tests/test_pipeline*.py
tests/test_work*.py``. Its bot PR (#27549) then went red in full CI on a guard (redate-guard) and a
test (``tests/console_connector/test_tabs.py``) that were outside that subset. A hand list goes stale
as soon as someone adds a reader. This script scans ``tests/`` for files that reference the register
(its paths, its loaders or its tools) and prints them, so ``.github/workflows/work-store-export.yml``
always runs every register-reading test.

Gates this adds or changes: none (it selects the tests a producer runs on its OWN output before
landing it; no merge-side block).

  python3 scripts/ci/register_reader_tests.py            # one path per line
  python3 scripts/ci/register_reader_tests.py --self-test
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List

REPO = Path(__file__).resolve().parents[2]

#: A test file reads the register when it names any of these. Paths and module names, not words:
#: a test that merely mentions "checklist" in prose is not selected.
MARKERS = (
    r"docs/claude/work",                 # the checklist / pipeline / export files themselves
    r"MANAGER-CHECKLIST",                # the generated register
    r"PIPELINE\.jsonl",                  # the retired intake name, still read by guards
    r"checklist_store",                  # src.runtime.checklist_store (the only reader)
    r"work_read",                        # src.runtime.work_read (store / export reader)
    r"work_store",                       # the store modules
    r"work_export",                      # the export cutover
    r"scripts[./]ops[./]pipeline",       # the pipeline module, by path or dotted import
    r"from scripts\.ops import pipeline",
    r"^import pipeline\b",               # tests that put scripts/ops on sys.path
    r"scripts[./]ops[./]checklist",      # the checklist CLI
    r"from scripts\.ops import checklist\b",
    r"console_connector",                # the console reads the register (inbox, work tabs)
    r"scripts[./]ops[./]work\b",         # the work CLI (export / store)
    r"from scripts\.ops import work\b",
)
_RX = re.compile("|".join(MARKERS), re.MULTILINE)


def register_reader_tests(root: Path = REPO) -> List[str]:
    """Repo-relative test files (``tests/**/test_*.py``) that reference the register, sorted."""
    out = []
    for p in sorted((root / "tests").rglob("test_*.py")):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _RX.search(text):
            out.append(p.relative_to(root).as_posix())
    return out


def _self_test() -> int:
    import tempfile
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok = ok and cond
        print(("  PASS  " if cond else "  FAIL  ") + label)

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "tests" / "sub").mkdir(parents=True)

        def put(rel: str, body: str) -> None:
            (root / rel).write_text(body, encoding="utf-8")
        put("tests/test_reads_files.py", 'P = "docs/claude/work/checklist"\n')
        put("tests/sub/test_console.py", "from src.console_connector import data\n")
        put("tests/test_pipeline_mod.py", "import pipeline\n")
        put("tests/test_dotted.py", "from scripts.ops import pipeline as pl\n")
        put("tests/test_prose_only.py", '"""the checklist is great"""\n')
        put("tests/test_unrelated.py", "def test_x():\n    assert 1\n")
        put("tests/helper_not_a_test.py", 'P = "docs/claude/work"\n')
        got = register_reader_tests(root)
        ck("selects a test naming the register's files", "tests/test_reads_files.py" in got)
        ck("selects a nested console_connector test", "tests/sub/test_console.py" in got)
        ck("selects a bare `import pipeline` test", "tests/test_pipeline_mod.py" in got)
        ck("selects a dotted pipeline import", "tests/test_dotted.py" in got)
        ck("does NOT select prose that only mentions 'checklist'", "tests/test_prose_only.py" not in got)
        ck("does NOT select an unrelated test", "tests/test_unrelated.py" not in got)
        ck("does NOT select a non-test helper file", "tests/helper_not_a_test.py" not in got)
    live = register_reader_tests(REPO)
    ck("the real set includes the inbox test that #27549 tripped",
       "tests/console_connector/test_tabs.py" in live)
    ck("the real set includes the old hand-picked subset (test_checklist*)",
       any(p.startswith("tests/test_checklist") for p in live))
    print("register-reader-tests self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.self_test:
        return _self_test()
    paths = register_reader_tests(REPO)
    if not paths:  # an empty selection would make the validation vacuous: say so, fail
        print("register-reader-tests: selected NO test files -- refusing an empty validation set",
              file=sys.stderr)
        return 2
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
