import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
from infra_runner_health import HOSTED, SELF_HOSTED, decide  # noqa: E402


def test_decide_table():
    assert decide(None, 0, None) == "noop"
    assert decide(None, 3, None) == "noop"
    assert decide(SELF_HOSTED, 0, None) == "fallback"
    assert decide(SELF_HOSTED, 2, None) == "noop"
    assert decide(HOSTED, 0, None) == "noop"
    assert decide(HOSTED, 1, None) == "resmoke"
    assert decide(HOSTED, 1, 10) == "noop"
    assert decide(HOSTED, 1, 90) == "resmoke"
    assert decide('["self-hosted", "jta-infra"]', 0, None) == "fallback"
