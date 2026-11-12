"""ml_entry_eq leg (spec docs/research/ml-entry-eq-serve-spec-2026-11-06.md): the COMMITTED booster reproduces the harness predictions in the parity
fixture; the signal path is snapshot-only and refuses with named reasons; the refresher is the only pool fetcher; the exit path never touches pool code."""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.runtime import ml_entry_eq_features as F  # noqa: E402
from src.runtime import ml_entry_eq_refresher as R  # noqa: E402
from src.units.strategies import ml_entry_eq as L  # noqa: E402

FIX = json.loads((REPO / "ml" / "candidates" / "ml_entry_eq_v1" / "parity_fixture.json").read_text())


def test_committed_booster_reproduces_the_harness_predictions():
    model = L.load_model()
    assert model["meta"]["features"] == F.FEATURES_B and model["meta"]["model_id"] == FIX["model_id"]
    import hashlib
    art = json.loads(L.ARTIFACT.read_text())
    assert hashlib.sha256(art["booster_txt"]["long"].encode()).hexdigest() == model["meta"]["booster_sha256"]
    rows = FIX["rows"]
    assert len(rows) >= 50
    for r in rows:
        x = {k: r[k] for k in F.FEATURES_B}
        assert abs(L.score(x, model) - float(r["pred"])) < 1e-9, r


def _snap(bar_close="2026-11-05T20:00:00+00:00", n=173, pred_features=None):
    syms = {f"E{i}": {**{k: 0.0 for k in F.FEATURES_B}, "atr14": 1.0, "close": 100.0} for i in range(n)}
    return {"schema": F.SCHEMA, "bar_close": bar_close, "pool_size": 173, "covered": n, "symbols": syms}


def test_non_decision_close_and_unknown_symbol_are_named_refusals():
    with pytest.raises(ValueError, match="not_a_decision_bar"):
        L.order_package({"symbol": "E0", "session": None}, _snap("2026-11-05T19:00:00+00:00"))
    with pytest.raises(ValueError, match="symbol_not_in_snapshot"):
        L.order_package({"symbol": "ZZZ", "session": None}, _snap())


def test_a_prediction_above_tau_builds_the_fixed_bracket(monkeypatch):
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.5] * len(rows))
    pkg = L.order_package({"symbol": "E0", "session": None}, _snap())
    assert pkg["direction"] == "long" and pkg["sl"] == 98.0 and pkg["tp"] == 103.0 and pkg["meta"]["max_hold_min"] == 24 * 60
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.1] * len(rows))
    with pytest.raises(ValueError, match="below_tau"):
        L.order_package({"symbol": "E0", "session": None}, _snap())


def test_builder_refuses_stale_missing_and_incomplete_snapshots(tmp_path, monkeypatch):
    from src.runtime import strategy_signal_builders as B
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(tmp_path / "s.json"))
    sig = B.ml_entry_eq_signal_builder({"SYMBOL": "E0"})
    assert sig["side"] == "none" and sig["meta"]["reason"] == F.REFUSE_MISSING
    F.write_snapshot(tmp_path / "s.json", _snap("2020-01-01T20:00:00+00:00"))
    assert B.ml_entry_eq_signal_builder({"SYMBOL": "E0"})["meta"]["reason"] == F.REFUSE_STALE
    now = pd.Timestamp.now(tz="UTC").floor("h")
    F.write_snapshot(tmp_path / "s.json", _snap(now.isoformat(), n=10))
    assert B.ml_entry_eq_signal_builder({"SYMBOL": "E0"})["meta"]["reason"] == F.REFUSE_INCOMPLETE


def test_refresher_pass_is_paced_per_symbol_and_writes_one_snapshot(tmp_path):
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    import ml_entry_equity as Q
    bars = Q._synthetic_bars(n_days=420)
    pool = [f"E{i}" for i in range(8)]
    calls, sleeps = [], []

    def fetch(s):
        calls.append(s)
        d = bars[s][["ts", "open", "high", "low", "close", "volume"]].rename(columns={"ts": "timestamp"})
        return d if s != "E3" else None                        # E3: a rate_limited read -> missing from THIS pass

    now = pd.Timestamp(bars["E0"].close_ts.iloc[-1]) + pd.Timedelta(minutes=5)
    res = R.refresh_once(pool + ["SPY"], lambda s: fetch(s) if s != "SPY" else fetch("E0"), now, tmp_path / "s.json", sleep=sleeps.append, pace_s=0.6)
    assert len(calls) == 9 and len(sleeps) == 8 and set(sleeps) == {0.6}      # exactly one call per symbol, paced; no per-call retry loop
    assert res["wrote"] and "E3" in res["missing"] and res["covered"] == 8
    snap = json.loads((tmp_path / "s.json").read_text())
    assert snap["covered"] == 8 and snap["feed"] == "sip" and "E3" not in snap["symbols"]
    # a retry in the same close fetches ONLY the missing symbol
    have = {}
    calls.clear()
    R.refresh_once(pool, fetch, now, tmp_path / "s.json", sleep=lambda x: None, have=have)
    calls.clear()
    R.refresh_once(pool, fetch, now, tmp_path / "s.json", sleep=lambda x: None, have=have)
    assert calls == ["E3"]


def test_exit_path_and_tick_never_make_pool_requests():
    om = (REPO / "src" / "runtime" / "order_monitor.py").read_text()
    assert not re.search(r"ml_entry_eq", om), "order_monitor must not import or call the pool snapshot / refresher"
    unit = (REPO / "src" / "units" / "strategies" / "ml_entry_eq.py").read_text()
    assert "fetch_candles" not in unit and "get_ohlcv" not in unit and "requests" not in unit
    b = (REPO / "src" / "runtime" / "strategy_signal_builders.py").read_text()
    body = b[b.index("def ml_entry_eq_signal_builder"):]
    assert "fetch_candles" not in body and "get_ohlcv" not in body
    cfg = __import__("yaml").safe_load((REPO / "config" / "accounts.yaml").read_text())
    rost = [a for a, v in cfg["accounts"].items() if "ml_entry_eq" in (v.get("strategies") or [])]
    assert rost == ["alpaca_paper"], rost


def test_monitor_is_a_time_stop_only():
    old = {"meta": {"max_hold_min": 1440, "entry_time": "2020-01-01T20:00:00+00:00"}}
    assert L.monitor({}, None, old)["action"] == "close"
    assert L.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": pd.Timestamp.now(tz="UTC").isoformat()}}) is None
