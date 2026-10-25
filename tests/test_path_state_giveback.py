"""path_state_giveback: per-bar state features use bars <= t only, and the grader separates a planted
path signal from stop-room mechanics (no network)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import path_state_giveback as psg  # noqa: E402


def _trade(n=14, c_step=0.2, exit_open=0.0, key="leg|SYM|2021-01-01 00:00:00+00:00|long"):
    rows, c, peak = [], 0.0, 0.0
    for b in range(1, n + 1):
        c += c_step
        peak = max(peak, c)
        last = b == n
        rows.append({"trade_key": key, "bar_offset": b, "c_r": c, "fav_r": c + 0.05, "adv_r": c - 0.05,
                     "open_r": exit_open if last else c, "peak_r": peak, "bars_since_peak": 0,
                     "atr_r": 0.5, "dist_to_stop_r": 2.0, "is_exit": last})
    return rows


def test_states_exclude_exit_bar_and_require_peak():
    st = psg.trade_states(_trade(), w=6, min_peak=1.0)
    assert st and all(s["bars_in"] < 14 for s in st)
    assert all(s["peak_r"] >= 1.0 for s in st)
    assert psg.trade_states(_trade(c_step=0.01), w=6, min_peak=1.0) == []


def test_features_do_not_read_the_future():
    a = _trade(exit_open=0.0)
    b = _trade(exit_open=3.0)           # different final outcome, identical bars before the exit
    sa, sb = psg.trade_states(a, 6, 1.0), psg.trade_states(b, 6, 1.0)
    for x, y in zip(sa, sb):
        for f in psg.FEATS + psg.BASE:
            assert x[f] == y[f]


def test_straight_path_has_er_one():
    st = psg.trade_states(_trade(), w=6, min_peak=1.0)
    assert abs(st[0]["er_w"] - 1.0) < 1e-9


def test_auc_orders_scores():
    y = np.array([0, 0, 1, 1])
    assert psg.auc(np.array([0.1, 0.2, 0.8, 0.9]), y) == 1.0
    assert psg.auc(np.array([0.9, 0.8, 0.2, 0.1]), y) == 0.0
