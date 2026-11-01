"""ml_entry_v2 (ENTRY v2 candidate, bybit_1 demo TESTING leg): cost gate, 4 ATR target, roster scope, served artifact."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from src.runtime import ml_decision_features as F
from src.units.strategies import ml_entry as M1
from src.units.strategies import ml_entry_v2 as M
from tests.test_ml_entry_adapter import _frame, _refs, _Stub

REPO = M.ARTIFACT.parents[3]


def _model(p_long, p_short, tau=0.078, gate=0.06, k=0.0007744467, tp=4.0):
    meta = {"features": F.FEATURES, "tau": tau, "model_id": "stub-v2",
            "bracket": {"sl_atr": 2.0, "tp_atr": tp, "atr_n": 14, "horizon_h": 24, "decision_every_h": 4}}
    if gate is not None:
        meta["cost_gate"] = {"max_cost_r": gate, "k_cost_x_atr": k, "input": "atr_pct"}
    return {"meta": meta, "long": _Stub(p_long), "short": _Stub(p_short)}


def test_cost_gate_estimate_and_refusal():
    row = {"atr_pct": 0.0129}                      # k / atr_pct = 0.0600 at the research constant
    assert M1.cost_r_estimate(_model(0, 0)["meta"], {"atr_pct": 0.02}) == pytest.approx(0.0007744467 / 0.02)
    assert M1.cost_r_estimate(_model(0, 0, gate=None)["meta"], row) is None          # a v1-style artifact has no gate
    assert M1.cost_r_estimate(_model(0, 0)["meta"], {"atr_pct": 0.0}) == float("inf")  # no range -> infinite cost -> gated
    df = _frame(2)
    atr_pct = float(F.decision_row("ETHUSDT", _refs() | {"ETHUSDT": df})["atr_pct"])
    k_pass = 0.06 * atr_pct * 0.5                  # estimate = 0.03 < 0.06 -> trades
    k_fail = 0.06 * atr_pct * 2.0                  # estimate = 0.12 > 0.06 -> gated even though the score clears tau
    ok = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.0, k=k_pass))
    assert ok["direction"] == "long" and ok["meta"]["cost_r_est"] == pytest.approx(0.03, rel=1e-3)
    with pytest.raises(ValueError, match="cost_gate"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.0, k=k_fail))
    with pytest.raises(ValueError, match="below_tau"):                      # below tau is still reported as such when not gated
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.01, 0.0, k=k_pass))


def test_bracket_is_sl2_tp4_and_package_meta_reports_it():
    df = _frame(2)
    pkg = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.0, gate=None))
    atr = F.atr_last(df)
    assert pkg["sl"] == pytest.approx(pkg["entry"] - 2.0 * atr) and pkg["tp"] == pytest.approx(pkg["entry"] + 4.0 * atr)
    assert pkg["confidence"] == M.NEUTRAL_CONFIDENCE == 1.0 and "4 x ATR14" in pkg["meta"]["tp_basis"]
    assert "cost_r_est" not in pkg["meta"]                                    # no gate -> v1-identical package meta


def test_v1_package_is_unchanged_by_the_gate_code():
    df = _frame(2)
    v1_model = {"meta": {"features": F.FEATURES, "tau": 0.1, "model_id": "stub",
                         "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_h": 24, "decision_every_h": 4}},
                "long": _Stub(0.3), "short": _Stub(0.05)}
    pkg = M1.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=v1_model)
    assert "cost_r_est" not in pkg["meta"] and pkg["meta"]["tp_basis"].startswith("3 x ATR14")


def test_roster_scope_is_bybit_1_demo_only():
    acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())
    accounts = acc.get("accounts", acc)
    holders = sorted(a for a, c in accounts.items() if isinstance(c, dict) and "ml_entry_v2" in (c.get("strategies") or []))
    assert holders == ["bybit_1"], holders
    assert accounts["bybit_1"].get("demo") is True
    strat = yaml.safe_load((REPO / "config/strategies.yaml").read_text())
    cfg = (strat.get("strategies") or strat)["ml_entry_v2"]
    assert cfg["symbols"] == ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"] and cfg["execution"] == "live"


def test_served_v2_artifact_loads_with_the_registered_numbers():
    pytest.importorskip("lightgbm")
    model = M.load_model()
    meta = model["meta"]
    assert meta["model_id"] == "ml-decision-entry-v2" and meta["features"] == F.FEATURES
    assert meta["bracket"]["tp_atr"] == 4.0 and meta["bracket"]["sl_atr"] == 2.0
    assert meta["cost_gate"]["max_cost_r"] == 0.06 and meta["cost_gate"]["input"] == "atr_pct"
    assert 0.0 < meta["tau"] < 0.1 and meta["w1_verdict"] == "fail"           # the failed W1 read travels with the artifact
    x = pd.DataFrame([[0.1] * len(F.FEATURES)], columns=F.FEATURES)
    assert np.isfinite(model["long"].predict(x)[0]) and np.isfinite(model["short"].predict(x)[0])


def test_monitor_never_raises_and_records_telemetry_under_its_own_name(monkeypatch):
    import src.runtime.position_telemetry as pt
    seen = {}
    monkeypatch.setattr(pt, "record_position_telemetry", lambda **kw: seen.update(kw))
    df = pd.DataFrame({"ts": pd.date_range("2026-11-01", periods=3, freq="h", tz="UTC"), "open": [1.0] * 3, "high": [1.1] * 3,
                       "low": [0.9] * 3, "close": [1.0, 1.0, 1.05], "volume": [1.0] * 3})
    M.monitor({}, df, {"direction": "long", "sl": 0.9, "tp": 1.2, "meta": {"atr14": 0.05}})
    assert seen.get("strategy") == "ml_entry_v2"
    assert M.monitor({}, None, None) is None
