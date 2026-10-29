"""DESK-V1-ALERTS: one operator ping per refused / rejected / expired claude_desk package, never a second."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.coordinator import OrderPackage, _emit_execution_failure_ping
from src.runtime import execution_diagnostics as ed
from src.units.accounts import execute as ex
from src.units.strategies import claude_desk as cd

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def pings(monkeypatch):
    sent = []
    monkeypatch.setattr(ed, "enqueue_execution_failure", lambda **kw: sent.append(kw))
    return sent


def _pkg(strategy="claude_desk"):
    return OrderPackage(strategy=strategy, symbol="BTCUSDT", direction="long", entry=100.0, sl=98.0, tp=104.0)


def _row(did="d-1", **entry):
    p = {"symbol": "BTCUSDT", "side": "long", "timeframe": "15m",
         "entry": {"type": "market", "level": 100.0, "good_till_bars": 1, **entry},
         "stop": {"level": 98.0}, "tp": {"level": 104.0}}
    return {"at": (NOW - timedelta(hours=2)).isoformat(), "decision_id": did, "proposal": p}


def test_expired_proposal_pings_once_across_repeated_ticks(tmp_path, pings):
    ledger = tmp_path / "leg.jsonl"
    for _ in range(3):  # the builder re-reports the same terminal outcome every tick
        cd.record([(_row(), cd.R_EXPIRED)], now=NOW, path=ledger)
    assert len(pings) == 1
    assert pings[0]["strategy"] == "claude_desk" and cd.R_EXPIRED in pings[0]["reason"] and "d-1" in pings[0]["reason"]


def test_refused_proposal_pings_once_per_decision(tmp_path, pings):
    cd.record([(_row("a"), "both_brackets_required:missing_tp"), (_row("b"), "bracket_geometry:x")], now=NOW,
              path=tmp_path / "leg.jsonl")
    assert len(pings) == 2


def test_rejected_desk_package_pings_once(pings):
    ex.log_rejection_to_journal(_pkg(), {"account_id": "bybit_1", "demo": True}, reason="insufficient margin",
                                status="exchange_rejected", sized_qty=0.01)
    assert len(pings) == 1 and pings[0]["account"] == "bybit_1" and pings[0]["demo"] is True
    assert pings[0]["reason"].startswith("exchange_rejected")


def test_other_strategies_dry_dispatch_and_expected_skips_do_not_ping(pings):
    cfg = {"account_id": "bybit_1"}
    ex.log_rejection_to_journal(_pkg("trend_donchian"), cfg, reason="x", status="rejected")
    ex.log_rejection_to_journal(_pkg(), cfg, reason="x", status="rejected", is_dry=True)
    assert pings == []


def test_coordinator_ping_skips_desk_so_a_refusal_is_not_pinged_twice(pings):
    _emit_execution_failure_ping(account="bybit_1", pkg=_pkg(), qty=0.01, reason="RiskBreach: x")
    assert pings == []
    _emit_execution_failure_ping(account="bybit_1", pkg=_pkg("trend_donchian"), qty=0.01, reason="RiskBreach: x")
    assert len(pings) == 1
