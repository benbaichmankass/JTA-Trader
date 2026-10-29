"""LTR-TIGHTEN-OPTIMIZE: the registered rule grid and the verdict rule (scripts/research/ltr_tighten_optimize.py)."""
from __future__ import annotations

import numpy as np

from scripts.research import ltr_tighten_optimize as m


def _st(**kw):
    st = {"close_r": 1.2, "stop_r": -1.0, "mfe_r": 1.5, "atr_px": 1.0, "risk_px": 2.0, "bars_held": 5,
          "ext_px": 103.0, "partial_taken": False}
    st.update(kw)
    return st


class _S:
    l = np.array([95.0, 97.0, 99.0, 100.5])  # noqa: E741  (the Series field name)
    h = np.array([101.0, 102.0, 103.0, 103.0])


def test_grid_is_the_registered_61_rules_with_hold_first():
    g = m.grid()
    assert len(g) == 61 and g[0] == ("hold", {})
    assert len({m.rule_name(f, p) for f, p in g}) == 61


def test_breakeven_arms_only_at_x_and_never_loosens():
    be = m.make_rule("breakeven", {"X": 1.0, "off": 0.0}, None, 1.0)
    assert be(0, 0, _st(close_r=0.9)) == {"action": "hold"}
    assert be(0, 0, _st(close_r=1.2)) == {"action": "tighten_sl", "level_r": 0.0}
    assert be(0, 0, _st(close_r=1.2, stop_r=0.2)) == {"action": "hold"}


def test_atr_trail_respects_min_gap():
    tr = m.make_rule("atr_trail", {"X": 1.0, "k": 1.0}, None, 1.0)
    assert tr(0, 0, _st()) == {"action": "tighten_sl", "level_r": 1.0}       # 1.5 - 1 x 1/2
    assert tr(0, 0, _st(close_r=1.05)) == {"action": "hold"}                   # 1.0 > 1.05 - 0.10


def test_structure_uses_the_n_bar_extreme_long():
    st = m.make_rule("structure", {"X": 1.0, "n": 2}, _S(), 1.0)
    # fill = 103 - 1.5 x 2 = 100; 2-bar low at j=3 is 99 -> -0.5 R
    assert st(0, 3, _st()) == {"action": "tighten_sl", "level_r": -0.5}


def test_losscut_and_giveback():
    lc = m.make_rule("losscut", {"Y": -0.5, "T": 4}, None, 1.0)
    assert lc(0, 0, _st(close_r=-0.6, bars_held=3)) == {"action": "hold"}
    assert lc(0, 0, _st(close_r=-0.6, bars_held=4)) == {"action": "close"}
    gb = m.make_rule("giveback", {"X": 1.0, "f": 0.5}, None, 1.0)
    assert gb(0, 0, _st()) == {"action": "tighten_sl", "level_r": 0.75}


def test_verdict_rule():
    assert m.verdict({"ci975": [0.01, 0.2]}, {"mean_dR": 0.02}, "ci975") == "pass"
    assert m.verdict({"ci975": [0.01, 0.2]}, {"mean_dR": -0.01}, "ci975") == "indeterminate"
    assert m.verdict({"ci975": [-0.2, -0.01]}, {"mean_dR": 0.5}, "ci975") == "fail"
    assert m.verdict({"ci975": [-0.1, 0.1]}, None, "ci975") == "indeterminate"


def test_maxdd():
    assert m._maxdd(np.array([1.0, -2.0, -1.0, 4.0])) == 3.0
    assert m._maxdd(np.array([])) is None
