"""Tests for scripts/research/ibs_meta_label.py (RQ-20261112-3c8f-03 instrument)."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

pd = pytest.importorskip("pandas")
pytest.importorskip("lightgbm")

import ibs_meta_label as m  # noqa: E402


def _bars(seed: int, n: int = 3000):
    rng = random.Random(seed)
    t0 = pd.Timestamp("2010-01-04", tz="UTC")
    c, out = 100.0, []
    for i in range(n):
        o = c * (1 + rng.gauss(0, 0.002))
        c2 = o * (1 + rng.gauss(0, 0.01))
        h, lo = max(o, c2) * (1 + abs(rng.gauss(0, 0.004))), min(o, c2) * (1 - abs(rng.gauss(0, 0.004)))
        out.append({"ts": t0 + pd.Timedelta(days=i), "o": o, "h": h, "l": lo, "c": c2})
        c = c2
    return out


def test_self_test_passes():
    assert m._self_test()


def test_end_to_end_synthetic_random_walk_has_no_edge_to_select():
    series = {"SPY": _bars(1), "TLT": _bars(2)}
    rows = m.build_candidates(series, {"SPY": 5.0, "TLT": 5.0}, "SPY")
    assert rows and all(set(m.FEATURES) <= set(r) for r in rows)
    scored = m.walk_forward(rows, [2014, 2015, 2016, 2017], purge_days=5, seed=1)
    g = m.grade(scored, delta_bar=0.02, n_floor=50, year_majority=0.5, boot=200, seed=1)
    assert g["read_state"] == "measured"
    assert g["verdict"] in ("fail", "indeterminate")  # a random walk carries nothing to select on


def test_features_use_only_past_bars():
    b = _bars(3, 400)
    f1 = m.bar_features(b)
    b2 = [dict(x) for x in b]
    b2[-1]["c"] *= 1.5  # change only the LAST bar
    f2 = m.bar_features(b2)
    k = str(b[-2]["ts"])
    assert f1[k] == f2[k]
