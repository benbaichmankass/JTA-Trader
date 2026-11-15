"""ml_entry_eq_struct trades its WHOLE tested population (row ML-ENTRY-EQ-STRUCT-FULL-POOL; operator 2026-11-11 ~09:20Z verbatim "regarding Alpaca, yes,
we want it to be trading everything it was trained on.").

Pins: (1) the leg's symbols ARE the artifact's pool_symbols minus the declared pool_exclude (no hand drift); (2) every one routes to Alpaca (an
unprofiled symbol falls back to the process EXCHANGE); (3) the batched pool scorer gives exactly the per-symbol answer; (4) the tick gives a pass only
to pool-only symbols that hold a package (no 171-pass fan-out) and never drops a symbol another source names; (5) the builder scores the pool once
per decision close."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.runtime import ml_entry_eq_features as F  # noqa: E402
from src.runtime import ml_pool_scoring as PS  # noqa: E402
from src.units.strategies import ml_entry_eq as L  # noqa: E402

ART = REPO / "ml" / "candidates" / "ml_entry_eq_v3_struct_ens5" / "model.json"
CFG = {"structure_exit": "pivot=5;sl_only", "artifact": "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json", "session": None}


def _strategies():
    c = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    return c.get("strategies") or c


def _snap(bar_close="2026-11-05T20:00:00+00:00", n=40, seed=0):
    import numpy as np
    rng = np.random.default_rng(seed)
    syms = {}
    for i in range(n):
        row = {k: float(rng.normal(0, 1)) for k in F.FEATURES_B}
        row.update({"hour": 20.0, "dow": 3.0, "atr14": 1.0 + i / 100, "close": 100.0 + i})
        syms[f"E{i}"] = row
    return {"schema": F.SCHEMA, "bar_close": bar_close, "pool_size": n, "covered": n, "symbols": syms}


def test_symbols_are_the_artifact_pool_minus_the_declared_exclusions():
    leg = _strategies()["ml_entry_eq_struct"]
    pool = json.loads(ART.read_text())["pool_symbols"]
    excl = leg.get("pool_exclude") or {}
    assert set(excl) == {"TQQQ", "GLD"} and all(str(v).strip() for v in excl.values())
    assert leg["symbols"] == [s for s in pool if s not in excl]
    assert len(leg["symbols"]) == 171 and leg["pool_scored"] is True
    assert pool == json.loads((REPO / "ml" / "candidates" / "ml_entry_eq_v1" / "model.json").read_text())["pool_symbols"]  # the refresher's pool


def test_every_pool_symbol_routes_to_alpaca():
    ins = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())["instruments"]
    pool = json.loads(ART.read_text())["pool_symbols"]
    bad = [s for s in pool if (ins.get(s) or {}).get("exchange") != "alpaca"]
    assert not bad, bad
    assert all(ins[s]["qty_step"] == 1 and ins[s]["min_qty"] == 1 for s in pool)   # whole shares (cash account)
    assert all(ins[s].get("asset_class") in ("equity", "bond", "commodity") for s in pool)


@pytest.mark.parametrize("cfg", [CFG, {"session": None}])
def test_batched_scores_equal_the_per_symbol_answer(cfg):
    model = L.load_model(L.artifact_path(cfg))
    snap = _snap()
    syms = list(snap["symbols"]) + ["NOT_IN_SNAPSHOT"]
    batch = L.score_pool(cfg, snap, syms, model)
    assert set(batch) == set(syms) and batch["NOT_IN_SNAPSHOT"] == "symbol_not_in_snapshot"
    for s in syms:
        try:
            one = L.order_package({"symbol": s, **cfg}, snap, model)
        except ValueError as exc:
            one = str(exc)
        if isinstance(one, dict):
            assert isinstance(batch[s], dict) and abs(batch[s]["meta"]["pred_net_r"] - one["meta"]["pred_net_r"]) < 1e-9
            assert (batch[s]["sl"], batch[s]["tp"], batch[s]["entry"]) == (one["sl"], one["tp"], one["entry"])
        else:
            assert batch[s] == one
        if isinstance(batch[s], dict):   # the batched prediction IS the single-row prediction
            row = {k: snap["symbols"][s][k] for k in F.FEATURES_B}
            assert abs(L.score(row, model) - batch[s]["meta"]["pred_net_r"]) < 1e-5
    with pytest.raises(ValueError, match="not_a_decision_bar"):
        L.score_pool(cfg, _snap("2026-11-05T19:00:00+00:00"), syms, model)


class _Acct:
    def __init__(self, name, exchange, strategies, symbols=None):
        self.name, self.exchange, self.strategies, self.symbols, self.configured = name, exchange, strategies, symbols, True


def test_tick_passes_only_pool_symbols_that_hold_a_package(monkeypatch):
    from src import main as M
    strats = {"ml_entry_eq_struct": {"enabled": True, "pool_scored": True, "symbols": ["SPY", "XLE", "XLF", "XLK"]},
              "tqqq_trend_long_1d": {"symbols": ["TQQQ"]}}
    monkeypatch.setattr("src.units.accounts.load_accounts", lambda *a, **k: [
        _Acct("alpaca_live", "alpaca", ["tqqq_trend_long_1d", "ml_entry_eq_struct"], ["SPY"])])
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda *a, **k: strats)
    monkeypatch.setattr(M, "load_strategies_cfg", lambda *a, **k: strats)
    seen_legs = []
    monkeypatch.setattr(PS, "picks", lambda cfg, legs=None: seen_legs.append(legs) or ["XLK", "SPY"])
    got = M._resolve_tick_symbols({"SYMBOL": "BTCUSDT"})
    assert got == ["BTCUSDT", "SPY", "TQQQ", "XLK"]           # XLE / XLF (no package) get no pass; SPY (declared) always ticks
    assert seen_legs == [["ml_entry_eq_struct"]]
    monkeypatch.setattr(PS, "picks", lambda cfg, legs=None: [])
    assert M._resolve_tick_symbols({"SYMBOL": "BTCUSDT"}) == ["BTCUSDT", "SPY", "TQQQ"]


def test_picks_are_ranked_and_skip_decided(monkeypatch, tmp_path):
    snap = _snap()
    p = tmp_path / "snap.json"
    F.write_snapshot(p, snap)
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(p))
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-05T20:05:00+00:00")))
    cfg = {"ml_entry_eq_struct": {"enabled": True, "pool_scored": True, "symbols": list(snap["symbols"]), **CFG}}
    PS._CACHE.clear()
    PS.decided_set("ml_entry_eq_struct").clear()
    res = PS.batch("ml_entry_eq_struct", cfg["ml_entry_eq_struct"], snap)
    want = sorted((s for s, v in res.items() if isinstance(v, dict)), key=lambda s: -res[s]["meta"]["pred_net_r"])
    got = PS.picks(cfg, legs=["ml_entry_eq_struct"])
    assert got == want
    if want:
        PS.decided_set("ml_entry_eq_struct").add((want[0], snap["bar_close"]))
        assert PS.picks(cfg, legs=["ml_entry_eq_struct"]) == want[1:]
    assert PS.picks(cfg, legs=["ml_entry_eq"]) == []
    PS.decided_set("ml_entry_eq_struct").clear()


def test_builder_scores_the_pool_once_per_close(monkeypatch, tmp_path):
    from src.runtime import strategy_signal_builders as B
    snap = _snap()
    p = tmp_path / "snap.json"
    F.write_snapshot(p, snap)
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(p))
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-05T20:05:00+00:00")))
    leg = {"enabled": True, "pool_scored": True, "symbols": list(snap["symbols"]), "max_snapshot_age_h": 4.0, **CFG}
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda *a, **k: {"ml_entry_eq_struct": leg})
    calls = []
    real = L.score_pool
    monkeypatch.setattr(L, "score_pool", lambda *a, **k: calls.append(1) or real(*a, **k))
    PS._CACHE.clear()
    B._ML_ENTRY_EQ_STRUCT_DECIDED.clear()
    out = [B.ml_entry_eq_struct_signal_builder({"SYMBOL": s}) for s in snap["symbols"]]
    assert len(calls) == 1 and len(out) == len(snap["symbols"])
    res = PS.batch("ml_entry_eq_struct", leg, snap)
    n_pkg = sum(isinstance(v, dict) for v in res.values())
    assert sum(1 for s in snap["symbols"] if (snap["symbols"][s] and (s, snap["bar_close"]) in B._ML_ENTRY_EQ_STRUCT_DECIDED)) == len(snap["symbols"])
    # a second tick on the same close re-emits nothing
    again = [B.ml_entry_eq_struct_signal_builder({"SYMBOL": s}) for s in snap["symbols"]]
    assert all("already_decided_this_bar" in json.dumps(x, default=str) for x in again)
    assert len(calls) == 1 and n_pkg >= 0
    B._ML_ENTRY_EQ_STRUCT_DECIDED.clear()


def test_refresher_archives_a_dated_copy_per_close(tmp_path):
    from src.runtime import ml_entry_eq_refresher as R
    live = tmp_path / "pool_snapshot.json"
    for i, bc in enumerate(["2026-11-05T16:00:00+00:00", "2026-11-05T20:00:00+00:00", "2026-11-06T16:00:00+00:00"]):
        snap = _snap(bc, n=3)
        F.write_snapshot(live, snap)
        R.archive_snapshot(live, snap, keep=2)
    got = sorted(p.name for p in (tmp_path / "history").glob("*.json"))
    assert got == ["20261105T2000Z.json", "20261106T1600Z.json"]          # bounded, oldest dropped
    back, why = F.read_snapshot(tmp_path / "history" / "20261106T1600Z.json", pd.Timestamp("2026-11-06T16:05:00+00:00"))
    assert why is None and back["bar_close"] == "2026-11-06T16:00:00+00:00"
    assert R.archive_snapshot(live, {"bar_close": None}) is None


def test_builder_audits_each_decided_no_package_close_once(monkeypatch, tmp_path):
    """ML-EQ-NOPKG-AUDIT: a refused symbol at a decision close writes ONE side-none audit row (with the reason and the close), so
    live-vs-replay parity can confirm it; a buy still writes its buy row; a repeat tick on the same close writes nothing."""
    from src.runtime import strategy_signal_builders as B
    snap = _snap()
    p = tmp_path / "snap.json"
    F.write_snapshot(p, snap)
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(p))
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-05T20:05:00+00:00")))
    leg = {"enabled": True, "pool_scored": True, "symbols": list(snap["symbols"]), "max_snapshot_age_h": 4.0, **CFG}
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda *a, **k: {"ml_entry_eq_struct": leg})
    logged = []
    monkeypatch.setattr(B, "log_signal", lambda rec: logged.append(rec))
    PS._CACHE.clear()
    B._ML_ENTRY_EQ_STRUCT_DECIDED.clear()
    for s in snap["symbols"]:
        B.ml_entry_eq_struct_signal_builder({"SYMBOL": s})
    res = PS.batch("ml_entry_eq_struct", leg, snap)
    evals = [r for r in logged if r.get("event") == "ml_entry_eq_struct_eval"]
    nones = [r for r in evals if r["side"] == "none"]
    buys = [r for r in evals if r["side"] == "buy"]
    assert len(buys) == sum(isinstance(v, dict) for v in res.values())
    assert nones and {r["symbol"] for r in nones} == {s for s, v in res.items() if isinstance(v, str)}
    assert all(r["reason"] and r["bar_close"] == str(snap["bar_close"]) for r in nones)
    n = len(logged)
    for s in snap["symbols"]:
        B.ml_entry_eq_struct_signal_builder({"SYMBOL": s})
    assert len(logged) == n
    B._ML_ENTRY_EQ_STRUCT_DECIDED.clear()
