"""ML-REAL-MONEY-OVERLAY shadow scoring: I7 -- shadow never changes an order.

Three layers: (1) the scorer returns None and touches no quantity; (2) at the coordinator call site its result
is never assigned (AST check, so a later edit that starts applying it fails here); (3) an artifact covering
nothing, a failing candle fetch or a short history all leave the record path inert and never raise.
"""
from __future__ import annotations

import ast
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import src.runtime.overlay_shadow as ovs
from src.runtime.overlay_features import FEATURES

REPO = Path(__file__).resolve().parents[1]


def _art(legs, tau=0.99):
    return {"features": list(FEATURES), "mean": [0.0] * len(FEATURES), "std": [1.0] * len(FEATURES),
            "coef": [0.0] * len(FEATURES), "intercept": 0.0, "tau": tau, "multiplier": 0.5,
            "legs_gate": legs, "family": "T", "rule": "RULE-ML-OVERLAY-NONINFERIOR-V2", "_file": "overlay_t.json"}


def _bars(n=450):
    rnd, c = random.Random(5), 100.0
    hi, lo, cl = [], [], []
    for _ in range(n):
        c *= math.exp(rnd.gauss(0, 0.01))
        cl.append(c), hi.append(c * 1.003), lo.append(c * 0.997)
    return {"high": hi, "low": lo, "close": cl}


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.paths.runtime_logs_dir", lambda: tmp_path)
    return tmp_path


def _pkg(strategy="leg_a", qty_meta=None):
    return SimpleNamespace(strategy=strategy, symbol="ETHUSDT", direction="long", entry=0.0,
                           meta=dict(qty_meta or {}), trace_id="t1")


def test_record_returns_none_and_logs_would_be_cut(logs, monkeypatch):
    b = _bars()
    monkeypatch.setattr(ovs, "_ARTIFACTS", {"leg_a": _art(["leg_a"])})
    monkeypatch.setattr(ovs, "_leg_bars", lambda s, y: (b, "4h", "2026-10-29 04:00"))
    pkg = _pkg()
    pkg.entry = b["close"][-1]
    assert ovs.record_overlay_shadow(pkg, "bybit_2") is None
    ovs.record_overlay_shadow(pkg, "bybit_portfolio")  # second account: scored once, logged twice
    rows = [json.loads(x) for x in (logs / "overlay_shadow.jsonl").read_text().splitlines()]
    assert [r["account"] for r in rows] == ["bybit_2", "bybit_portfolio"]
    assert rows[0]["action"] == "annotate" and rows[0]["would_be_multiplier"] == 0.5  # p=0.5 < tau
    assert rows[0]["entry_vs_bar_close_bps"] == 0.0
    assert pkg.meta["_overlay_shadow"]["would_be_multiplier"] == 0.5


def test_uncovered_leg_and_failures_are_inert(logs, monkeypatch):
    monkeypatch.setattr(ovs, "_ARTIFACTS", {"leg_a": _art(["leg_a"])})
    assert ovs.record_overlay_shadow(_pkg("other_leg"), "bybit_2") is None
    assert not (logs / "overlay_shadow.jsonl").exists()

    def boom(*_a):
        raise RuntimeError("venue down")
    monkeypatch.setattr(ovs, "_leg_bars", boom)
    assert ovs.score_package(_pkg())["action"] == "error"
    monkeypatch.setattr(ovs, "_leg_bars", lambda s, y: ({k: v[:50] for k, v in _bars().items()}, "4h", None))
    rec = ovs.score_package(_pkg())
    assert rec["action"] == "unscored" and rec["would_be_multiplier"] == 1.0


def test_artifact_loader_reads_gate_legs(tmp_path):
    (tmp_path / "overlay_td.json").write_text(json.dumps(_art(["a", "b"])))
    (tmp_path / "overlay_zz.json").write_text(json.dumps(_art(["b"])))
    got = ovs._load_artifacts(tmp_path)
    assert set(got) == {"a", "b"} and got["b"]["_file"] == "overlay_td.json"


def test_coordinator_never_applies_the_shadow_result():
    """I7 at the call site: every call of record_overlay_shadow in the coordinator is a bare expression
    statement -- never assigned, returned, passed on or used in arithmetic."""
    tree = ast.parse((REPO / "src/core/coordinator.py").read_text(encoding="utf-8"))
    calls, bare = 0, 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "record_overlay_shadow":
            calls += 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and \
                getattr(node.value.func, "id", getattr(node.value.func, "attr", "")) == "record_overlay_shadow":
            bare += 1
    assert calls >= 1, "the shadow scorer is not wired into the coordinator"
    assert calls == bare, "record_overlay_shadow's result is used somewhere: shadow must never change an order"


def test_closed_bar_trim_used(monkeypatch):
    """_leg_bars drops a still-forming last bar before the features read it."""
    now = pd.Timestamp("2026-10-29 06:30", tz="UTC")
    ts = pd.date_range(end=pd.Timestamp("2026-10-29 04:00", tz="UTC"), periods=300, freq="4h")
    df = pd.DataFrame({"timestamp": [int(t.timestamp() * 1000) for t in ts], "open": 1.0, "high": 1.0,
                       "low": 1.0, "close": range(300), "volume": 1.0})
    monkeypatch.setattr("src.runtime.market_data.fetch_candles", lambda *a, **k: df)
    monkeypatch.setattr("src.runtime.market_data.connector_for_symbol", lambda *a, **k: None)
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda: {"leg_a": {"timeframe": "4h"}})
    import time
    monkeypatch.setattr(time, "time", lambda: now.timestamp())
    bars, tf, _last = ovs._leg_bars("leg_a", "ETHUSDT")
    assert tf == "4h" and bars["close"][-1] == 298  # the 04:00 bar closes at 08:00 > now: dropped
