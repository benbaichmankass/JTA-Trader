"""hf_vectorized's HTF close/EMA attached to the 5m clock are CAUSAL (PI-20261120-7ITMUEB1-0006, ML-PRIMARY-14, 2026-11-20).

build_htf joins HTF bars onto 5m bars with a BACKWARD merge_asof, so the HTF frame must be stamped at its CLOSE
(_resample_close_stamped); an open-stamped HTF frame would let a 5m bar read the hour it sits inside. Perturb every bar
after a 5m bar: its attached HTF values must not change. The open-stamped build is the positive control.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hf_vectorized as hv  # noqa: E402


def _frame(n: int = 12 * 40, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + 0.1, "low": np.minimum(o, c) - 0.1,
                         "close": c, "volume": 1.0})


def _leaks() -> int:
    base = _frame()
    df5 = hv._resample(base, "5min")
    hc0, he0 = hv.build_htf(df5, base, 5, "1h")
    leaks = 0
    for k in range(120, len(base) - 13, 7):
        pert = base.copy()
        pert.loc[pert.index > k, ["open", "high", "low", "close"]] *= 1.5
        hc, he = hv.build_htf(hv._resample(pert, "5min"), pert, 5, "1h")
        if not (np.allclose(np.nan_to_num(hc0[k], nan=-1), np.nan_to_num(hc[k], nan=-1))
                and np.allclose(np.nan_to_num(he0[k], nan=-1), np.nan_to_num(he[k], nan=-1))):
            leaks += 1
    return leaks


def test_htf_never_reads_the_future():
    assert _leaks() == 0


def test_open_stamped_htf_is_the_positive_control(monkeypatch):
    monkeypatch.setattr(hv, "_resample_close_stamped", hv._resample)
    assert _leaks() > 0


def test_the_5m_clock_from_5m_data_is_identity():
    base = _frame()
    df5 = hv._resample(base, "5min")
    assert (df5["timestamp"].to_numpy() == base["timestamp"].to_numpy()).all()
    assert np.allclose(df5["close"].to_numpy(), base["close"].to_numpy())


def test_solo_sim_htf_uses_the_same_close_stamped_frame():
    """hf_vectorized._validate_A compares against hf_solo_sim: both HTF joins must stamp the same way."""
    import scripts.research.hf_solo_sim as sim
    base = _frame()
    a, b = hv._resample_close_stamped(base, "1h"), sim._resample_close_stamped(base, "1h")
    assert (a["timestamp"].to_numpy() == b["timestamp"].to_numpy()).all()
    assert np.allclose(a["close"].to_numpy(), b["close"].to_numpy())
    src = (REPO / "scripts" / "research" / "hf_solo_sim.py").read_text()
    assert "htf = _resample_close_stamped(base5m, htf_tf)" in src
