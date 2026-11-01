"""`--adx-max` on backtest_ict_scalp.py (PI-20261101-HIPIPRHQ-0001).

RQ-20261031-7b6f-03/04/05 passed `--adx-max=40/50` to a harness that had no such flag, so every candidate arm died at argparse
(`harness_failed`, never a verdict). Locked here: (1) the flag is accepted, (2) default-off is byte-identical, (3) the ceiling
actually REMOVES signals (a flag that is accepted but ignored would pass a parse-only test), (4) an unreadable ADX is skipped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.backtest_ict_scalp as h


def _df(n=400, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.4, n))
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 1.0})


def _kw():
    return dict(cfg_overrides={}, timeframe="15m", symbol="SOLUSDT", warmup_bars=50, timeout_bars=12, cooldown_bars=3)


def _fake_pkg(monkeypatch):
    def pkg(cfg, candles_df=None):
        c = float(candles_df["close"].iloc[-1])
        return {"direction": "long", "entry": c, "sl": c - 1.0, "tp": c + 1.5, "confidence": 1.0}
    monkeypatch.setattr(h, "order_package", pkg)


def test_flag_is_accepted_by_the_parser():
    src = open(h.__file__).read()
    assert '"--adx-max"' in src


def test_default_off_equals_none(monkeypatch):
    _fake_pkg(monkeypatch)
    a = h.run_backtest(_df(), **_kw())
    b = h.run_backtest(_df(), adx_max=None, **_kw())
    assert a["total_trades"] == b["total_trades"] and a["total_trades"] > 0


def test_ceiling_removes_signals(monkeypatch):
    _fake_pkg(monkeypatch)
    base = h.run_backtest(_df(), **_kw())["total_trades"]
    zero = h.run_backtest(_df(), adx_max=0.0, **_kw())["total_trades"]     # ADX >= 0 always -> every signal skipped
    huge = h.run_backtest(_df(), adx_max=1000.0, **_kw())["total_trades"]  # ADX < 1000 always -> nothing skipped
    assert base > 0 and zero == 0 and huge == base


def test_unreadable_adx_is_skipped(monkeypatch):
    _fake_pkg(monkeypatch)
    import src.runtime.regime as rg
    monkeypatch.setattr(rg, "detect_regime", lambda *a, **k: {"adx": None})
    assert h.run_backtest(_df(), adx_max=50.0, **_kw())["total_trades"] == 0
