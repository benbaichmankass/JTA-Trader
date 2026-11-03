import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
from infra_runner_health import HOSTED, SELF_HOSTED, decide  # noqa: E402


def test_disk_floor_falls_back_and_blocks_rearm():
    assert decide(SELF_HOSTED, 4, None, 0.0) == "fallback"     # the 2026-11-03 14:10Z incident: 100% full
    assert decide(SELF_HOSTED, 4, None, None) == "fallback"    # could not look is not "fine"
    assert decide(SELF_HOSTED, 4, None, 40.0) == "noop"
    assert decide(HOSTED, 4, None, 5.0) == "noop"              # never re-arm onto a full disk
    assert decide(HOSTED, 4, None, 40.0) == "resmoke"


def test_decide_table():
    assert decide(None, 0, None, 40.0) == "noop"
    assert decide(None, 3, None, 40.0) == "noop"
    assert decide(SELF_HOSTED, 0, None, 40.0) == "fallback"
    assert decide(SELF_HOSTED, 2, None, 40.0) == "noop"
    assert decide(HOSTED, 0, None, 40.0) == "noop"
    assert decide(HOSTED, 1, None, 40.0) == "resmoke"
    assert decide(HOSTED, 1, 10, 40.0) == "noop"
    assert decide(HOSTED, 1, 90, 40.0) == "resmoke"
    assert decide('["self-hosted", "jta-infra"]', 0, None, 40.0) == "fallback"
