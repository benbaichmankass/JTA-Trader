"""ML-SL-ONLY-STRUCTURE-ARM (RQ-20261103-5e04-01): the harness arm equals the LIVE verdict source.

Pins, on recorded ADA bars resampled to 1h-like spacing (the fixture's 2h bars, used as-is: the arm is
timeframe-agnostic, it steps whatever bars it is given):
1. PARITY: structure_sl_path's stop for walk bar j equals what structure_exit_live.replay computes on the
   GROWING frame that ends at the close of bar i + j - 1 (exactly what the live ml_entry monitor sees then);
2. CAUSAL: mutating every bar after i + j - 1 never changes the stop resting in bar j;
3. tighten-only and never looser than the entry stop;
4. walk(): no sl_path -> byte-identical to the fixed-stop walk; with sl_path, a stop crossing the close
   exits at that close (live structure_sl_cross), and the TP chooser still moves the TP.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import structure_exit_live as sxl

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "ADAUSDT_2h_2020-06-03_2026-10-15.csv"


def _harness():
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    spec = importlib.util.spec_from_file_location("ml_entry_tp_revision",
                                                  REPO / "scripts/research/ml_entry_tp_revision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HM = _harness()


@pytest.fixture(scope="module")
def bars() -> pd.DataFrame:
    return pd.read_csv(FIX, nrows=6000)


def _arrays(df):
    return (df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float),
            df["close"].to_numpy(float))


def _cases(df):
    _, hi, lo, cl = _arrays(df)
    for i in range(700, 5500, 173):
        atr = sxl._atr_at(hi, lo, cl, i)
        for side in (1, -1):
            yield i, side, float(cl[i]), atr


def test_parity_with_live_replay_on_growing_frames(bars):
    _, hi, lo, cl = _arrays(bars)
    moved = 0
    for i, side, entry, atr in _cases(bars):
        path = HM.structure_sl_path(hi, lo, cl, i, entry, atr, side, "pivot=5")
        entry_sl = entry - side * HM.E.SL_ATR * atr
        a = max(0, i - HM.STRUCT_LOOKBACK)
        params = sxl.declared({"structure_exit": "pivot=5"})  # replay's SL path is the same in sl_only mode
        for j in range(1, HM.H + 1):
            k = i + j - 1
            live = sxl.replay(highs=hi[a:k + 1], lows=lo[a:k + 1], closes=cl[a:k + 1], entry_idx=i - a,
                              entry=entry, is_long=side > 0, entry_sl=entry_sl, atr=atr, params=params)
            assert path[j] == pytest.approx(live["sl"], abs=1e-12), (i, side, j)
        moved += path[-1] != entry_sl
    assert moved > 0, "no trade's stop ever moved: the parity probe is vacuous"


def test_future_bars_never_change_the_resting_stop(bars):
    _, hi, lo, cl = _arrays(bars)
    for i, side, entry, atr in list(_cases(bars))[:12]:
        base = HM.structure_sl_path(hi, lo, cl, i, entry, atr, side, "pivot=5")
        for j in (1, 5, 12, HM.H):
            k = i + j - 1
            h2, l2, c2 = hi.copy(), lo.copy(), cl.copy()
            h2[k + 1:] *= 1.37
            l2[k + 1:] *= 0.61
            c2[k + 1:] *= 0.9
            assert HM.structure_sl_path(h2, l2, c2, i, entry, atr, side, "pivot=5")[j] == base[j]


def test_tighten_only_never_looser_than_entry_stop(bars):
    _, hi, lo, cl = _arrays(bars)
    for i, side, entry, atr in _cases(bars):
        path = HM.structure_sl_path(hi, lo, cl, i, entry, atr, side, "pivot=5")[1:]
        entry_sl = entry - side * HM.E.SL_ATR * atr
        prev = entry_sl
        for sl in path:
            assert side * (sl - prev) >= -1e-12 and side * (sl - entry_sl) >= -1e-12
            prev = sl


def test_bad_spec_refused():
    with pytest.raises(ValueError):
        HM.structure_sl_path(np.ones(10), np.ones(10), np.ones(10), 5, 1.0, 0.1, 1, "atr=3")


def test_walk_without_path_is_the_fixed_stop_walk(bars):
    for i, side, entry, atr in list(_cases(bars))[:20]:
        Ob, Hh, L, C = HM.windows(bars, np.array([i]))
        e = Ob[0][0]
        a = HM.walk(Ob[0], Hh[0], L[0], C[0], e, atr, side, None)
        flat = [None] + [e - side * HM.E.SL_ATR * atr] * HM.H
        b = HM.walk(Ob[0], Hh[0], L[0], C[0], e, atr, side, None, None, flat)
        assert a[:3] == b[:3]


def test_walk_structure_cross_exits_at_close_and_tp_still_moves():
    H = HM.H
    Ob = np.full(H, 100.0)
    Hh = np.full(H, 100.5)
    L = np.full(H, 99.5)
    C = np.full(H, 100.0)
    atr = 1.0
    path = [None, 98.0, 98.0] + [100.2] * (H - 2)          # after bar 2 closes the stop is above the close (100)
    px, j, reason, _ = HM.walk(Ob, Hh, L, C, 100.0, atr, 1, None, None, path)
    assert (px, j, reason) == (100.0, 2, 1)
    moved = []
    def chooser(jc, q):
        moved.append(jc)
        return q + 1 if q + 1 < len(HM.GRID) else None
    path = [None] + [98.0] * H
    HM.walk(Ob, Hh, L, C, 100.0, atr, 1, chooser, None, path)
    assert moved and moved[0] == HM.CHECKINS[0]
