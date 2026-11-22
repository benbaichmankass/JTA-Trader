import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import d5_aggregator_arms as D  # noqa: E402

DFLT = {"w1": ("2024-10-01", "2025-10-01"), "w2": ("2025-10-01", "2026-10-01")}


def test_default_is_census():
    assert D.resolve_windows({}, None, DFLT) == DFLT


def test_unit_windows_sorted_by_date():
    u = {"arms_on": {"windows": {"late": ["2023-10-01", "2024-10-01"], "early": ["2022-10-01", "2023-10-01"]}}}
    assert list(D.resolve_windows(u, None, DFLT)) == ["early", "late"]


def test_cli_beats_unit():
    u = {"arms_on": {"windows": {"a": ["2022-01-01", "2023-01-01"], "b": ["2023-01-01", "2024-01-01"]}}}
    r = D.resolve_windows(u, "x=2020-01-01:2021-01-01,y=2021-01-01:2022-01-01", DFLT)
    assert list(r) == ["x", "y"]


@pytest.mark.parametrize("bad", ["a=2021-01-01:2022-01-01", "a=2021-01-01:2022-06-01,b=2022-01-01:2023-01-01", "x"])
def test_bad_windows_refused(bad):
    with pytest.raises(ValueError):
        D.resolve_windows({}, bad, DFLT)
