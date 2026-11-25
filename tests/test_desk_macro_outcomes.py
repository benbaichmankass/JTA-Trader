"""DESK-MACRO-DAILY grading adapter (scripts/ops/desk_macro_outcomes.py): replays each brief's shadow trades on daily bars with the
desk replayer, one row per brief x trade, could-not-look retried, never written as zero."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))


def test_desk_macro_outcomes_self_test():
    import desk_macro_outcomes as M
    assert M._self_test() == 0


def test_replay_is_the_desk_replayer_unchanged():
    src = (REPO / "scripts/ops/desk_macro_outcomes.py").read_text()
    assert "do.replay(p, cutoff, closed, do._cost_fn(sym))" in src
