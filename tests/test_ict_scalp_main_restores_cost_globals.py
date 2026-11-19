"""main() must not leak the cost globals it applies (PR #27149: a leaked venue-aware stack moved net_total_r
-14.7793 -> -17.1766 on identical trades). Locks: the five module globals are exactly restored after a main() call."""
from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.backtest_ict_scalp as h

_NAMES = ("FEE_BPS_ROUNDTRIP", "SLIPPAGE_BPS_ROUNDTRIP", "FUNDING_BPS_PER_WINDOW", "FUNDING_WINDOW_HOURS", "CONTRACT_COST")


def _csv(tmp_path):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.4, 400))
    ts = pd.date_range("2025-01-01", periods=400, freq="15min", tz="UTC")
    p = tmp_path / "c.csv"
    pd.DataFrame({"timestamp": ts, "open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 1.0}).to_csv(p, index=False)
    return str(p)


def test_main_restores_the_cost_globals(tmp_path, monkeypatch):
    for n, v in zip(_NAMES, (7.5, 0.0, 0.0, 8.0, None)):
        monkeypatch.setattr(h, n, v)
    before = {n: getattr(h, n) for n in _NAMES}
    rc = h.main(["backtest_ict_scalp", "--data", _csv(tmp_path), "--symbol", "BTCUSDT", "--ignore-yaml"])
    assert rc in (0, 1, 2)   # the restore must hold whatever the run does
    assert {n: getattr(h, n) for n in _NAMES} == before


def test_main_restores_even_when_it_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "CONTRACT_COST", None)
    rc = h.main(["backtest_ict_scalp", "--data", _csv(tmp_path), "--symbol", "MGC", "--contract-cost-usd-rt", "1.0"])
    assert rc == 2 and h.CONTRACT_COST is None
