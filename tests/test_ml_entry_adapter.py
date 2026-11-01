"""ml_entry adapter (row ML-ENTRY-LIVE-ADAPTER): serving features == research features, brackets and no-sizing invariants."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import ml_decision_features as F
from src.units.strategies import ml_entry as M

REPO = Path(__file__).resolve().parents[1]


def _harness():
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    spec = importlib.util.spec_from_file_location("ml_decision_entry", REPO / "scripts/research/ml_decision_entry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frame(seed: int, n: int = 400, end: str = "2026-01-01 03:00") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="1h")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1e3, 1e4, n)})


def test_features_match_research_harness():
    H = _harness()
    df = _frame(1)
    a = F.features_symbol(df).drop(columns=["ts"])
    b = H.features_symbol(df).drop(columns=["ts"])
    pd.testing.assert_frame_equal(a, b)
    assert F.FEATURES == H.FEATURES


def test_cross_sectional_context_matches_harness_pivot():
    frames = {"BTCUSDT": _frame(1), "ETHUSDT": _frame(2), "XRPUSDT": _frame(3)}
    row = F.decision_row("ETHUSDT", frames)
    assert row is not None and row["_n_reference"] == 3
    H = _harness()
    feats = {s: H.features_symbol(f) for s, f in frames.items()}
    r24 = pd.DataFrame({s: feats[s].set_index("ts")["ret24_raw"] for s in frames})
    v24 = pd.DataFrame({s: feats[s].set_index("ts")["vol24"] for s in frames})
    t = r24.index[-1]
    assert row["xs_rank_ret24"] == pytest.approx(r24.rank(axis=1, pct=True).loc[t, "ETHUSDT"])
    assert row["btc_ret24"] == pytest.approx(r24.loc[t, "BTCUSDT"])
    assert row["breadth_up24"] == pytest.approx(((r24 > 0).sum(axis=1) / r24.notna().sum(axis=1)).loc[t])
    assert row["rel_vol"] == pytest.approx(v24.loc[t, "ETHUSDT"] / v24.median(axis=1).loc[t])


class _Stub:
    def __init__(self, v):
        self.v = v

    def predict(self, x):
        return np.full(len(x), self.v)


def _model(p_long, p_short, tau=0.1):
    return {"meta": {"features": F.FEATURES, "tau": tau, "model_id": "stub",
                     "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_h": 24, "decision_every_h": 4}},
            "long": _Stub(p_long), "short": _Stub(p_short)}


def _refs():
    return {f"S{i}USDT": _frame(10 + i) for i in range(45)} | {"BTCUSDT": _frame(1)}


def test_order_package_brackets_and_no_sizing():
    df = _frame(2)  # last bar opens 03:00 -> closes 04:00, a decision bar
    pkg = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.05))
    atr = F.atr_last(df)
    assert pkg["direction"] == "long"
    assert pkg["sl"] == pytest.approx(pkg["entry"] - 2.0 * atr)
    assert pkg["tp"] == pytest.approx(pkg["entry"] + 3.0 * atr)
    assert pkg["confidence"] == M.NEUTRAL_CONFIDENCE == 1.0
    assert pkg["meta"]["max_hold_min"] == 24 * 60
    short = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.0, 0.4))
    assert short["direction"] == "short" and short["sl"] > short["entry"] > short["tp"]


def test_order_package_threads_the_declared_tp_revision():
    """ML-ENTRY-TP-REVISION: the leg's tp_revision declaration rides the package meta; undeclared = no revision."""
    df = _frame(2)
    on = M.order_package({"symbol": "ETHUSDT", "tp_revision": {"rule": M.TP_RULE}}, candles_df=df,
                         reference_frames=_refs(), model=_model(0.3, 0.05))
    assert on["meta"]["tp_revision"] == {"rule": M.TP_RULE}
    off = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.05))
    assert "tp_revision" not in off["meta"]


def test_refusals():
    df = _frame(2)
    with pytest.raises(ValueError, match="below_tau"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.05, 0.02))
    with pytest.raises(ValueError, match="not_a_decision_bar"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=_frame(2, end="2026-01-01 04:00"),
                        reference_frames=_refs(), model=_model(0.3, 0.0))
    with pytest.raises(ValueError, match="reference_symbols"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames={"BTCUSDT": _frame(1)},
                        model=_model(0.3, 0.0))


def test_monitor_time_stop():
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert M.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": old}})["action"] == "close"
    assert M.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": new}}) is None
    assert M.monitor({}, None, None) is None


def test_served_artifact_loads_and_predicts():
    pytest.importorskip("lightgbm")
    model = M.load_model()
    assert model["meta"]["features"] == F.FEATURES and model["meta"]["tau"] == 0.1
    x = pd.DataFrame([[0.1] * len(F.FEATURES)], columns=F.FEATURES)
    assert np.isfinite(model["long"].predict(x)[0]) and np.isfinite(model["short"].predict(x)[0])
