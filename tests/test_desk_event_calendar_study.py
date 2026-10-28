import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import desk_event_calendar_study as m  # noqa: E402


def test_verdict_branches():
    assert m.verdict(50, 5, 5, 20, True) == "insufficient_n"
    assert m.verdict(500, 1, 1, 20, True) == "candidate"
    assert m.verdict(500, 1, 1, 20, False) == "inconclusive"
    assert m.verdict(500, -3, -3, 10, True) == "no_edge"


def test_entry_is_after_known_at_plus_latency():
    t = np.arange(0, 3000, 300)
    assert t[m.entry_ix(t, 600)] == 900  # known_at + one 5m bar


def test_fwd_gross_signed():
    o = np.array([100.0, 101.0, 102.0])
    assert round(m.fwd_gross(o, 0, 2, -1), 1) == -200.0
    assert np.isnan(m.fwd_gross(o, 2, 1, 1))
