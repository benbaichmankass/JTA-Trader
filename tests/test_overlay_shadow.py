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


def test_committed_artifacts_are_reduce_only_and_carry_their_evidence():
    """Every committed overlay artifact is reduce-only, names its rule, and covers only legs in the roster."""
    import yaml
    roster = set()
    for acct in (yaml.safe_load((REPO / "config/accounts.yaml").read_text()).get("accounts") or {}).values():
        if isinstance(acct, dict):
            roster.update(acct.get("strategies") or [])
    arts = sorted((REPO / "ml/overlay").glob("overlay_*.json"))
    for p in arts:
        art = json.loads(p.read_text())
        assert 0.0 < float(art["multiplier"]) < 1.0, p.name
        assert art["rule"].startswith("RULE-ML-OVERLAY-NONINFERIOR-"), p.name
        assert set(art["legs_gate"]) <= roster, p.name
        assert len(art["coef"]) == len(art["features"]) == len(FEATURES) and art["features"] == list(FEATURES)


def test_apply_path_is_reduce_only_and_inert_by_default(monkeypatch, tmp_path):
    """Tier-3 apply path: default (no overlay_policy) leaves qty unchanged even when the shadow record would
    cut; mode reduce applies exactly the artifact multiplier; nothing ever upsizes."""
    pkg = _pkg()
    pkg.meta["_overlay_shadow"] = {"action": "annotate", "would_be_multiplier": 0.5}
    pol = tmp_path / "overlay_policy.yaml"
    pol.write_text("strategies: {other_leg: {mode: reduce}}\n")
    monkeypatch.setattr(ovs, "POLICY_PATH", pol)
    monkeypatch.setattr(ovs.overlay_policy_mode, "__defaults__", (pol,))
    assert ovs.apply_overlay_reduce(pkg, 10.0) == 10.0
    pol.write_text("strategies: {leg_a: {mode: reduce}}\n")
    assert ovs.apply_overlay_reduce(pkg, 10.0) == 5.0
    pkg.meta["_overlay_shadow"] = {"action": "annotate", "would_be_multiplier": 3.0}
    assert ovs.apply_overlay_reduce(pkg, 10.0) == 10.0
    for bad in ({"action": "unscored", "would_be_multiplier": 1.0}, {"action": "error"}, None):
        pkg.meta["_overlay_shadow"] = bad
        assert ovs.apply_overlay_reduce(pkg, 10.0) == 10.0


def test_reduce_policy_only_on_artifact_gate_legs():
    """a `reduce` entry in config/overlay_policy.yaml may only name a leg its committed artifact covers (otherwise the policy
    reads no score and is silently inert -- a config that claims an effect it cannot have)."""
    import yaml
    pol = yaml.safe_load((REPO / "config/overlay_policy.yaml").read_text())["strategies"]
    arts = {p.name: set(json.loads(p.read_text())["legs_gate"]) for p in (REPO / "ml/overlay").glob("overlay_*.json")}
    for leg, v in pol.items():
        if str(v.get("mode", "")).lower() == "reduce":
            assert leg in arts.get(v.get("artifact"), set()), (leg, v)


def test_committed_policy_forming_bar_legs_annotate_closed_bar_legs_reduce():
    """PI-20261030-XME2GXW7-0001 (operator 2026-10-30, "Annotate both out"): the two FORMING-bar legs read
    annotate from the committed policy (no size change even on a cutting score); the closed-bar legs keep reduce.
    All four stay artifact gate legs, so they are still scored and logged to overlay_shadow.jsonl."""
    gate = set(ovs._load_artifacts().get("trend_donchian_eth_4h", {}).get("legs_gate") or [])
    for leg in ("trend_donchian_eth_4h", "trend_donchian_sol_prop"):
        assert ovs.overlay_policy_mode(leg) == "annotate", leg
        assert leg in gate, leg
        pkg = SimpleNamespace(strategy=leg, meta={"_overlay_shadow": {"action": "annotate",
                                                                      "would_be_multiplier": 0.5}})
        assert ovs.apply_overlay_reduce(pkg, 10.0) == 10.0, leg
    for leg in ("trend_donchian_xrp_4h", "trend_donchian_eth_prop"):
        assert ovs.overlay_policy_mode(leg) == "reduce", leg
        pkg = SimpleNamespace(strategy=leg, meta={"_overlay_shadow": {"action": "annotate",
                                                                      "would_be_multiplier": 0.5}})
        assert ovs.apply_overlay_reduce(pkg, 10.0) == 5.0, leg
