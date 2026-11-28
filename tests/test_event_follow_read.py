"""e44a-04 grader: the synthetic arms and (when the committed PPI bars are present) the exact PPI GDX reproduction."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

import event_follow_read as EF  # noqa: E402


def test_self_test():
    EF._self_test()


def test_cli_requires_arguments():
    import pytest
    with pytest.raises(SystemExit):
        EF.main([])
