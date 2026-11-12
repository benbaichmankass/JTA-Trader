"""Operator gate decisions 2026-11-12 (decisions page, Gates tab), runtime half.

Record: ``comms/gates/gate_decisions_2026-11-12.json`` (branch gate-decisions,
commit a040d7aa0d). Each test proves the action now goes through, and the
positive controls prove the safety that remains still answers.

- GATE-BAR-DEBOUNCE: REMOVE
- GATE-REFUSAL-COOLDOWN: REMOVE
- GATE-EMPTY-SIZING-BRAKE: MAKE REPORT-ONLY
- GATE-STRATEGY-PAUSED-FLAG: REMOVE (intent layer; the legacy multiplexer is in
  tests/test_runtime_flags.py)
- GATE-MARKET-HOURS: MAKE REPORT-ONLY
- GATE-MULTI-ACCOUNT-DISPATCH-ENV: MAKE REPORT-ONLY (end to end in
  tests/test_e35_per_account_election.py)
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

if "matplotlib" not in sys.modules:
    _mpl_stub = types.ModuleType("matplotlib")
    _mpl_stub.pyplot = mock.MagicMock()
    sys.modules["matplotlib"] = _mpl_stub
    sys.modules["matplotlib.pyplot"] = mock.MagicMock()

import src.runtime.intent_multiplexer as im
import src.runtime.strategy_signal_builders as ssb
from src.runtime import (
    pipeline,
    runtime_flags,
)

REPO = Path(__file__).resolve().parents[1]
SIG = {"symbol": "ETHUSDT", "side": "buy", "entry_price": 100.0, "stop_loss": 95.0,
       "take_profit": 115.0, "meta": {"strategy_name": "s1", "entry_time": "12:00"}}


@pytest.fixture
def audit(monkeypatch):
    rows: list = []
    monkeypatch.setattr(pipeline, "log_signal", lambda r: rows.append(r))
    monkeypatch.setattr(pipeline, "_has_open_package_for_strategy", lambda s, symbol=None: None)
    monkeypatch.setattr(pipeline, "_same_bar_entry_for_strategy", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_recent_refusal_for_strategy", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_empty_sizing_refusal_for_signal", lambda *a, **k: None)
    return rows


def test_same_bar_repeat_now_dispatches_and_is_logged(audit, monkeypatch):
    monkeypatch.setattr(pipeline, "_same_bar_entry_for_strategy", lambda *a, **k: {
        "bar_seconds": 900, "order_package_id": "p1", "last_created_at": "t"})
    assert pipeline._monocle_gate(dict(SIG), {}) is None
    assert [r["event"] for r in audit] == ["same_bar_reentry_observed"]
    assert audit[0]["last_package_id"] == "p1"


def test_recent_refusal_now_dispatches_and_is_logged(audit, monkeypatch):
    monkeypatch.setattr(pipeline, "_recent_refusal_for_strategy", lambda *a, **k: {
        "order_package_id": "r1", "age_seconds": 12.0, "cooldown_seconds": 300})
    assert pipeline._monocle_gate(dict(SIG), {}) is None
    assert [r["event"] for r in audit] == ["recent_refusal_observed"]
    assert audit[0]["last_refused_package_id"] == "r1"


def test_empty_sizing_repeat_now_dispatches_and_names_its_cause(audit, monkeypatch):
    monkeypatch.setattr(pipeline, "_empty_sizing_refusal_for_signal", lambda *a, **k: {
        "order_package_id": "e1", "cause": "no_account_reached_sizer: 0 loaded",
        "signal_key": "k1", "refused_at": "t"})
    assert pipeline._monocle_gate(dict(SIG), {}) is None
    assert [r["event"] for r in audit] == ["empty_sizing_repeat_reported"]
    assert audit[0]["cause"] == "no_account_reached_sizer: 0 loaded"


def test_all_three_hit_at_once_still_dispatches(audit, monkeypatch):
    monkeypatch.setattr(pipeline, "_same_bar_entry_for_strategy", lambda *a, **k: {
        "bar_seconds": 900, "order_package_id": "p1", "last_created_at": "t"})
    monkeypatch.setattr(pipeline, "_recent_refusal_for_strategy", lambda *a, **k: {
        "order_package_id": "r1", "age_seconds": 12.0, "cooldown_seconds": 300})
    monkeypatch.setattr(pipeline, "_empty_sizing_refusal_for_signal", lambda *a, **k: {
        "order_package_id": "e1", "cause": "c", "signal_key": "k1", "refused_at": "t"})
    assert pipeline._monocle_gate(dict(SIG), {}) is None
    assert len(audit) == 3


def test_positive_control_open_package_still_skips(audit, monkeypatch):
    """The open-package gate is not part of these decisions and still refuses."""
    monkeypatch.setattr(pipeline, "_has_open_package_for_strategy",
                        lambda s, symbol=None: "open-pkg")
    out = pipeline._monocle_gate(dict(SIG), {})
    assert out["status"] == "skipped" and out["reason"] == "open_package_exists"


def test_removed_skip_reasons_are_gone_from_the_gate():
    """No return path of _monocle_gate can produce the three removed reasons."""
    src = Path(pipeline.__file__).read_text()
    fn = src[src.index("def _monocle_gate("):src.index("def _open_package_round(")]
    for reason in ('"same_bar_reentry_debounce"', '"recent_refusal_cooldown"',
                   '"empty_sizing_refused"'):
        assert reason not in fn, reason


# ── GATE-STRATEGY-PAUSED-FLAG: intent layer ───────────────────────────────

def test_paused_flag_no_longer_skips_in_the_intent_layer(tmp_path, monkeypatch):
    (tmp_path / "pause_s1").touch()
    monkeypatch.setattr(runtime_flags, "flags_dir", lambda: tmp_path)
    monkeypatch.setattr(im, "is_strategy_paused", runtime_flags.is_strategy_paused)
    assert runtime_flags.is_strategy_paused("s1") is True     # the flag is really there
    called = []

    def builder(settings):
        called.append("s1")
        return {"symbol": "ETHUSDT", "side": "none", "meta": {"strategy_name": "s1"}}
    im._collect_intents({"SYMBOL": "ETHUSDT"}, builders={"s1": builder},
                        strategies=["s1"], target_qty_hint=0.0)
    assert called == ["s1"]   # evaluated despite the pause flag


# ── GATE-MARKET-HOURS ─────────────────────────────────────────────────────

def test_no_builder_returns_on_a_closed_market_any_more():
    """Static: no ``return`` in the builders module carries the two closed-market reasons."""
    tree = ast.parse(Path(ssb.__file__).read_text())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            seg = ast.dump(node.value)
            if "us_market_closed" in seg or "fx_market_closed" in seg:
                hits.append(node.lineno)
    assert hits == []


def test_closed_us_market_builder_carries_on_to_its_data(monkeypatch):
    """spy_trend_long_1d with the market closed now proceeds past the market
    check: it reaches its candle fetch (stubbed to the session-bar skip, which
    is what comes back), and the market state is reported, not returned."""
    import src.runtime.market_hours as mh
    import src.units.strategies as strategies_mod
    monkeypatch.setattr(mh, "is_market_open", lambda cls, ts=None: False)
    monkeypatch.setattr(strategies_mod, "load_strategy_config",
                        lambda: {"spy_trend_long_1d": {"enabled": True, "timeframe": "1d"}})
    monkeypatch.setattr(ssb, "_build_killzone_exchange", lambda s: object())
    reached = []
    monkeypatch.setattr(ssb, "_fetch_session_frame",
                        lambda *a, **k: (reached.append(a[0]) or None, "session_bar_not_published"))
    reports = []
    monkeypatch.setattr(ssb, "log_signal", lambda r: reports.append(r))
    out = ssb.spy_trend_long_1d_signal_builder({"SYMBOL": "SPY"})
    assert reached == ["spy_trend_long_1d"]
    assert out["meta"]["reason"] == "session_bar_not_published"
    assert reports and reports[0]["event"] == "market_closed_report_only"
    assert reports[0]["cause"] == "us_market_closed"


def test_market_hours_check_itself_still_reads_closed():
    """Positive control: the check still runs and still says closed on a Saturday."""
    from datetime import datetime, timezone

    from src.runtime.market_hours import is_market_open
    sat = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
    assert is_market_open("us_equity", sat) is False
    assert is_market_open("fx", sat) is False
    assert is_market_open("crypto", sat) is True


# ── KEEP: GATE-EXECUTE-ZEROQTY-WHOLEUNIT still refuses ────────────────────

def test_positive_control_zero_qty_refusal_is_kept():
    src = (REPO / "src/units/accounts/execute.py").read_text()
    assert "GATE-EXECUTE-ZEROQTY-WHOLEUNIT: KEEP" in src
    assert "qty=0 after sizing" in src
