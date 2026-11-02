"""ml_entry serve parity (RQ-20261101-c692-07): the Bybit frame builder keeps the bars it fetched.

Regression: under pandas 3 a ``unit="ms"`` datetime stays at millisecond resolution, so the old window filter
``ts.astype("int64") // 10**6 >= start_ms`` (written for ns) dropped every row and the trainer run compared n=0 bars
(issue #22152). The filter now compares timestamps.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("serve_parity", REPO / "scripts/research/ml_entry_serve_parity.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return {"result": {"list": self._rows}}


def test_bybit_1h_keeps_bars_inside_the_window(monkeypatch):
    m = _mod()
    h = 3_600_000
    start_ms = 1_792_454_400_000          # 2026-10-20 00:00Z
    end_ms = start_ms + 5 * h
    # Bybit returns newest first; one bar before the window must be dropped, five inside kept.
    rows = [[str(start_ms + k * h), "1", "2", "0.5", "1.5", "10", "15"] for k in range(4, -2, -1)]
    calls = []

    def fake_get(url, params=None):
        calls.append(params)
        return _Resp(rows if len(calls) == 1 else [])

    monkeypatch.setattr(m, "_get", fake_get)
    df = m.bybit_1h("BTCUSDT", start_ms, end_ms)
    assert len(df) == 5
    assert df.ts.iloc[0] == pd.Timestamp(start_ms, unit="ms", tz="UTC")
    assert df.ts.is_monotonic_increasing
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
