"""NO-WAIT-HAND-BUILDS (602 twin): the wrapper keeps only config-exact legs and only trades BEFORE each leg's committed window."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

import m16_longhistory as LH  # noqa: E402


def test_self_test():
    LH._self_test()


def test_cli_requires_out_and_no_build_needs_a_dir(capsys):
    import pytest
    with pytest.raises(SystemExit):
        LH.main([])
    with pytest.raises(SystemExit):
        LH.main(["--out", "x", "--no-build"])
