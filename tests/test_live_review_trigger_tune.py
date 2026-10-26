"""Synthetic checks for scripts/research/live_review_trigger_tune.py (no corpus is read)."""
import math

import pandas as pd

from scripts.research import live_review_trigger_tune as T


def _path(closes, his, los=None, atr=1.0, net_r=0.0):
    n = len(closes)
    idx = list(pd.date_range("2026-01-01", periods=n, freq="2h", tz="UTC"))
    los = los or [c - 0.2 for c in closes]
    return {"idx": idx, "open": list(closes), "hi": list(his), "lo": list(los), "close": list(closes),
            "close_px": [100 + c for c in closes], "close_px_prev": [100.0] + [100 + c for c in closes[:-1]],
            "atr": [atr] * n, "atr_prev": [atr] * n, "atr_entry": atr, "r_dist": 1.0,
            "entry_ts": idx[0] - pd.Timedelta(hours=2), "exit_ts": idx[-1],
            "trade": {"net_r": net_r, "cost_fee_r": 0.0, "cost_slippage_r": 0.0, "cost_funding_r": 0.0,
                      "mfe_r": max(his)}}


def test_r_milestone_fires_once_per_level_and_giveback_after_peak():
    p = _path([0.5, 1.2, 1.1, 2.3, 1.2], [0.6, 1.3, 1.3, 2.4, 2.4])
    rb = T.review_bars(p, dict(T.DEFAULTS), tp_r=50.0, tf_h=2.0)
    evs = {j: e for j, e in rb}
    assert "r_milestone" in evs[1] and 2 not in evs          # +1R once; bar 2 is a repeat level
    assert "r_milestone" in evs[3]                            # +2R
    assert "giveback" in evs[4]                               # 1.2 back from 2.4 >= max(0.5, 0.72)


def test_off_values_silence_their_trigger():
    p = _path([0.5, 1.2, 2.3], [0.6, 1.3, 2.4])
    cfg = dict(T.DEFAULTS)
    cfg["r_milestone.first_r"] = math.inf
    cfg["new_peak.step_r"] = math.inf
    rb = T.review_bars(p, cfg, tp_r=50.0, tf_h=2.0)
    assert all("r_milestone" not in e for _, e in rb)


def test_swing_and_daily_floor():
    p = _path([0.0] * 12 + [3.0], [0.1] * 12 + [3.1], atr=1.0)
    rb = T.review_bars(p, dict(T.DEFAULTS), tp_r=50.0, tf_h=2.0)
    names = [e for _, es in rb for e in es]
    assert "swing" in names and "daily_floor" in names       # 24h at bar 11 (2h bars)


def test_replay_tightest_stop_and_recorded_exit_stands():
    p = _path([1.0, 2.0, 1.0, 0.5], [1.1, 2.1, 2.1, 2.1], los=[0.9, 1.9, 0.9, 0.4], net_r=0.3)
    assert T.replay(p, [], 1 / 1.5) == 0.3
    got = T.replay(p, [("r", 1.5, 1)], 1 / 1.5)               # stop +1.5R from bar 2; bar 2 opens 1.0 -> gap fill
    assert abs(got - 1.0) < 1e-9


def test_run_config_end_to_end_on_synthetic_legs():
    import random
    rnd = random.Random(7)
    paths = []
    for _ in range(60):
        c, closes, his = 0.0, [], []
        for _ in range(20):
            c += rnd.gauss(0.05, 0.6)
            closes.append(c)
            his.append(c + abs(rnd.gauss(0, 0.3)))
        paths.append(_path(closes, his, net_r=closes[-1]))
    legs = {"syn": {"paths": paths, "meta": {"atr_stop_mult": 1.5, "tp_r": 3.0, "timeframe": "2h"}}}
    res = T.run_config(legs, dict(T.DEFAULTS), 4, 0.05)
    tot = T.totals(res)
    assert tot["trades"] == sum(len(paths[i * 60 // 5:(i + 1) * 60 // 5]) for i in range(1, 5))
    assert tot["reviews"] > 0 and sum(tot["events"].values()) >= tot["reviews"]
    assert len(T.objective(res, 0.02, 4)) == 4
