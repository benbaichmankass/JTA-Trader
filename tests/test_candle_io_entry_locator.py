"""candle_io: open-stamped resample_ohlcv + the causal entry-bar locator (PI-20261120-7ITMUEB1-0006, ML-PRIMARY-14).

resample_ohlcv now reproduces the native grid [T, T+rule) labelled T. Its regime-tagger consumers look up "the bar an
entry may read": with a ledger on the same grain the decision bar (closed at fill time) is right; with a FINER ledger
the bar an entry sits inside is still forming, so entry_bar_locator falls back to the last bar closed at/before the
entry for every trade. Positive control: the naive lookup reads the forming bar on a finer ledger.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from candle_io import entry_bar_locator, resample_ohlcv  # noqa: E402

H = pd.date_range("2026-01-05", periods=48, freq="1h", tz="UTC")


def test_resample_ohlcv_is_the_native_grid():
    ts = pd.date_range("2026-01-05", periods=36, freq="5min", tz="UTC")
    px = pd.Series(range(36), dtype=float) + 100
    df = pd.DataFrame({"timestamp": ts, "open": px, "high": px + 1, "low": px - 1, "close": px + 0.5})
    out = resample_ohlcv(df, "1h")
    assert list(out["timestamp"]) == list(ts[::12])
    assert (out["open"].iloc[0], out["close"].iloc[0], out["high"].iloc[0]) == (100.0, 111.5, 112.0)


def test_aligned_ledger_reads_its_own_decision_bar():
    entries = [H[5], H[9]]
    locate, mode = entry_bar_locator(H, entries)
    assert mode == "aligned" and [locate(e) for e in entries] == [5, 9]


def test_finer_ledger_never_reads_a_forming_bar():
    entries = [H[5] + pd.Timedelta("15min"), H[9]]          # one 15m-grid entry makes the ledger finer
    locate, mode = entry_bar_locator(H, entries)
    assert mode == "finer_ledger"
    got = [locate(e) for e in entries]
    assert got == [4, 8], got                                 # bar 4 closes at H[5] <= entry; bar 8 closes at H[9]
    for e, i in zip(entries, got):
        assert H[i] + pd.Timedelta("1h") <= e                 # causal: the read bar has closed


def test_naive_lookup_is_the_positive_control():
    e = H[5] + pd.Timedelta("15min")
    naive = int(H.searchsorted(e, side="right")) - 1
    assert H[naive] + pd.Timedelta("1h") > e                  # it reads the bar the entry sits inside


def test_empty_bars():
    locate, mode = entry_bar_locator([], [H[0]])
    assert mode == "empty" and locate(H[0]) == -1


def test_series_input_and_nat_entries():
    locate, mode = entry_bar_locator(pd.Series(H), [H[3], pd.NaT, None])
    assert mode == "aligned" and locate(H[3]) == 3
    assert np.isfinite(locate(H[3]))
