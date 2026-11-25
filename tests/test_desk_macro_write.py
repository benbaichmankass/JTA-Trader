"""DESK-MACRO-DAILY prototype writer (scripts/ops/desk_macro_write.py): refusal rules + write-once, offline."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))


def test_desk_macro_write_self_test():
    import desk_macro_write as W
    assert W.self_test() == 0


def test_good_brief_validates_against_the_real_universe():
    import desk_macro_write as W
    uni, legs = W.desk_universe()
    assert W.problems(W.GOOD, uni, legs) == []
