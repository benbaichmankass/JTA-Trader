"""Causal structure detector: the no-lookahead contract (row STRUCTURE-EXITS-DEFAULT)."""
import numpy as np
import pytest

from src.runtime.structure_levels import (
    StructureLevels, levels_asof, structure_sl, structure_tp,
    SWING_HIGH,
)


def _walk(seed, m=400):
    r = np.random.default_rng(seed)
    c = 100 + np.cumsum(r.normal(0, 1, m))
    h = c + r.uniform(0.1, 1.5, m)
    lo = c - r.uniform(0.1, 1.5, m)
    return h, lo


def _key(levels):
    return [(lv_.kind, round(lv_.price, 9), lv_.formed_idx, lv_.confirmed_idx) for lv_ in levels]


@pytest.mark.parametrize("n", [2, 3, 5, 8])
def test_no_lookahead_truncation_equivalence(n):
    """Full-frame query at t == query on the frame truncated to bars 0..t, for every t."""
    h, lo = _walk(n)
    full = StructureLevels(h, lo, n)
    for t in range(0, len(h), 7):
        assert _key(full.levels_asof(t)) == _key(levels_asof(h, lo, t, n)), t


def test_future_bars_cannot_change_a_past_answer():
    h, lo = _walk(1)
    t = 200
    before = _key(StructureLevels(h, lo, 3).levels_asof(t))
    h2, lo2 = h.copy(), lo.copy()
    h2[t + 1:] += 500.0          # wildly different future
    lo2[t + 1:] -= 500.0
    assert _key(StructureLevels(h2, lo2, 3).levels_asof(t)) == before


def test_swing_confirmed_only_after_n_bars():
    h = [1, 2, 3, 9, 3, 2, 1, 2, 3, 2, 1.0]
    lo = [x - 0.5 for x in h]
    s = StructureLevels(h, lo, 3)
    assert [lv_.price for lv_ in s.levels_asof(5) if lv_.kind == SWING_HIGH] == []   # bar 3 pivot, known at 6
    assert [lv_.price for lv_ in s.levels_asof(6) if lv_.kind == SWING_HIGH] == [9]
    assert s.last_swing_high(5) is None and s.last_swing_high(6).formed_idx == 3


def test_fvg_unfilled_vs_filled_is_causal():
    # bars: 0,1,2 make a bullish gap (low[2]=10 > high[0]=5); bar 6 trades back to 10.
    h = [5, 8, 14, 13, 13, 12, 11, 12]
    lo = [4, 6, 10, 11, 11, 10.5, 9.5, 10.5]
    s = StructureLevels(h, lo, 2)
    up_to_5 = [lv_ for lv_ in s.levels_asof(5) if lv_.kind == "fvg_bull_edge"]
    assert len(up_to_5) == 1 and up_to_5[0].price == 10
    assert not [lv_ for lv_ in s.levels_asof(6) if lv_.kind == "fvg_bull_edge"]   # filled at bar 6
    # and a query at t=5 on the full frame still shows it unfilled (fill is in the future)
    assert [lv_ for lv_ in s.levels_asof(5) if lv_.kind == "fvg_bull_edge"]


def test_structure_sl_tp_long_and_short():
    h = [10, 11, 12, 15, 12, 11, 10, 11, 12, 11, 10, 11.0, 12, 13]
    lo = [9, 10, 11, 14, 11, 10, 8, 10, 11, 10, 9, 10.0, 11, 12]
    s = StructureLevels(h, lo, 2)
    t = len(h) - 1
    sl = structure_sl(s, t, entry=12.5, is_long=True, atr=1.0, atr_stop_dist=2.0)
    assert sl is not None and sl < 12.5 and 12.5 - sl <= 3.0 * 2.0 + 1e-9
    risk = 12.5 - sl
    tp = structure_tp(s, t, 12.5, True, risk, min_r=1.0, fvg=False)
    assert tp is None or tp >= 12.5 + risk
    # short side mirrors
    sl_s = structure_sl(s, t, entry=9.5, is_long=False, atr=1.0, atr_stop_dist=2.0)
    assert sl_s is None or sl_s > 9.5


def test_no_confirmed_swing_returns_none():
    s = StructureLevels([1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 4, 5], 3)
    assert structure_sl(s, 5, 6.0, True, 1.0, 2.0) is None


def test_bad_args():
    with pytest.raises(ValueError):
        StructureLevels([1, 2], [0, 1], 0)
    with pytest.raises(ValueError):
        StructureLevels([1, 2], [0], 2)
