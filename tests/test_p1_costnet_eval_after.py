"""p1_costnet_grade --eval-after: an out-of-time eval read keeps only rows the earlier read never saw.

WHY (RQ-20261119-2780-04 confirmation, PI-20261120-7ITMUEB1-0003, ML-PRIMARY-14 2026-11-20): the 2780-04 PASS read
all 698 measured rostered-paper rows of v024 at threshold 0.48; a confirmation must read rows entered AFTER that build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.ml.p1_costnet_grade import _after  # noqa: E402


def _rows():
    return [{"ts": "2026-11-19T23:00:00+00:00"}, {"ts": "2026-11-20T00:00:00Z"}, {"ts": "2026-11-21T05:00:00+00:00"},
            {"ts": "2026-12-01T00:00:00"}, {"ts": ""}, {}]


def test_off_is_unchanged():
    rows = _rows()
    kept, w = _after(rows, None)
    assert kept is rows and w is None


def test_strictly_after_naive_read_as_utc_and_bad_ts_counted():
    kept, w = _after(_rows(), "2026-11-20T00:00:00Z")
    assert [r["ts"] for r in kept] == ["2026-11-21T05:00:00+00:00", "2026-12-01T00:00:00"]
    assert w == {"after": "2026-11-20T00:00:00+00:00", "before": 6, "after_n": 2, "excluded_not_after": 2,
                 "excluded_unparsed_ts": 2}


def test_bad_cut_refused():
    with pytest.raises(SystemExit):
        _after(_rows(), "not-a-date")
