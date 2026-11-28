"""twin_family_read.py: k-of-N sibling-symbol Stage-0 read (RESEARCH-NO-WAIT-FOR-DATA, 2026-11-28)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import twin_family_read  # noqa: E402


def test_self_test():
    twin_family_read.self_test()
