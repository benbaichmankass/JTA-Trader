"""DESK-17 -- the claude_desk leg: an accepted desk proposal -> ONE order package, both brackets.

Covers the dispatch's three required behaviours (a proposal becomes one package with both brackets;
a proposal missing a bracket is refused; shadow sends nothing) plus consumption, expiry, the
fail-closed journal read, and the roster scope (bybit_1 only, execution: shadow).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.units.strategies import claude_desk as cd

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)


def _proposal(**over):
    p = {"symbol": "BTCUSDT", "venue_class": "crypto_perp", "side": "long", "timeframe": "15m",
         "horizon_bars": 8, "entry": {"type": "market", "level": 100.0, "good_till_bars": 4},
         "stop": {"level": 98.0, "basis": "swing_level"},
         "tp": {"level": 104.0, "basis": "measured_move", "p_hit": 0.42},
         "expected_r_net": 0.3, "thesis": "t", "novelty": "new", "onboarding": "in_universe"}
    p.update(over)
    return p


def _row(did="d-1", at=NOW - timedelta(minutes=5), **over):
    return {"at": at.isoformat(), "decision_id": did, "intent_id": f"i-{did}", "packet_id": "pk",
            "packet_sha": "abc", "ref": "deadbeef", "proposal": _proposal(**over)}


# ---------------------------------------------------------------- one proposal -> one package

def test_proposal_becomes_one_package_with_both_brackets():
    pkg = cd.order_package({"confidence": 0.5}, _row())
    assert (pkg["symbol"], pkg["direction"]) == ("BTCUSDT", "long")
    assert (pkg["entry"], pkg["sl"], pkg["tp"]) == (100.0, 98.0, 104.0)
    assert pkg["meta"]["decision_id"] == "d-1" and pkg["meta"]["signal_logic"] == "desk"
    assert pkg["meta"]["tp_basis"] == "measured_move" and pkg["meta"]["tp_p_hit"] == 0.42
    assert "qty" not in pkg and "size" not in pkg  # sizing is the RiskManager's


def test_short_geometry_accepted():
    pkg = cd.order_package({}, _row(side="short", stop={"level": 102.0, "basis": "swing_level"},
                                    tp={"level": 96.0, "basis": "measured_move", "p_hit": 0.4}))
    assert (pkg["direction"], pkg["sl"], pkg["tp"]) == ("short", 102.0, 96.0)
    assert pkg["confidence"] == 0.5


@pytest.mark.parametrize("over,why", [
    ({"tp": None}, "both_brackets_required:missing_tp"),
    ({"stop": {"basis": "swing_level"}}, "both_brackets_required:missing_stop"),
    ({"stop": None, "tp": None}, "both_brackets_required:missing_stop+tp"),
    ({"tp": {"level": float("nan"), "basis": "x", "p_hit": 0.1}}, "both_brackets_required:missing_tp"),
    ({"tp": {"level": 0, "basis": "x", "p_hit": 0.1}}, "both_brackets_required:missing_tp"),
])
def test_missing_bracket_is_refused(over, why):
    with pytest.raises(ValueError, match=why.replace("+", r"\+")):
        cd.order_package({}, _row(**over))
    pkg, terminal = cd.select([_row(**over)], symbol="BTCUSDT", consumed=set(), now=NOW)
    assert pkg is None and terminal and terminal[0][1] == why


@pytest.mark.parametrize("over,prefix", [
    ({"tp": {"level": 99.0, "basis": "x", "p_hit": 0.1}}, "bracket_geometry"),
    ({"side": "short"}, "bracket_geometry"),
    ({"entry": {"type": "limit", "level": 100.0, "good_till_bars": 4}}, "entry_type_unsupported:limit"),
    ({"side": "flat"}, "side_invalid"),
])
def test_incoherent_proposals_refused(over, prefix):
    assert cd.proposal_problem(_proposal(**over)).startswith(prefix)


def test_one_package_per_proposal_and_symbol_scope():
    rows = [_row("d-1"), _row("d-2"), _row("d-3", symbol="ETHUSDT")]
    pkg, terminal = cd.select(rows, symbol="BTCUSDT", consumed=set(), now=NOW)
    assert pkg["meta"]["decision_id"] == "d-1" and terminal == []
    pkg, _ = cd.select(rows, symbol="BTCUSDT", consumed={"d-1"}, now=NOW)
    assert pkg["meta"]["decision_id"] == "d-2"
    pkg, _ = cd.select(rows, symbol="BTCUSDT", consumed={"d-1", "d-2"}, now=NOW)
    assert pkg is None
    pkg, _ = cd.select(rows, symbol="eth/usdt", consumed=set(), now=NOW)
    assert pkg["meta"]["decision_id"] == "d-3"


def test_consumed_read_from_journal_meta():
    pkgs = [{"meta": json.dumps({"decision_id": "d-1"})}, {"meta": {"decision_id": "d-2"}},
            {"meta": "not json"}, {"meta": None}]
    assert cd.consumed_decision_ids(pkgs) == {"d-1", "d-2"}


def test_expiry_is_an_outcome():
    old = _row("d-old", at=NOW - timedelta(minutes=61))  # 4 x 15m = 60 min
    pkg, terminal = cd.select([old], symbol="BTCUSDT", consumed=set(), now=NOW)
    assert pkg is None and terminal[0][1] == "expired_unfilled"
    assert cd.expires_at(_row()) == NOW - timedelta(minutes=5) + timedelta(minutes=60)


def test_ledger_records_each_outcome_once(tmp_path):
    lp = tmp_path / "desk_leg.jsonl"
    out = [(_row("d-x"), "expired_unfilled")]
    assert cd.record(out, now=NOW, path=lp) == 1
    assert cd.record(out, now=NOW, path=lp) == 0
    assert json.loads(lp.read_text())["outcome"] == "expired_unfilled"


def test_monitor_never_acts():
    assert cd.monitor({}, None, {"sl": 1.0}) is None


# ---------------------------------------------------------------- the builder (I/O seams)

def _builder(monkeypatch, tmp_path, rows, *, cfg=None, pkgs=(), journal_raises=False):
    from src.runtime import strategy_signal_builders as ssb
    import src.units.strategies as units
    q = tmp_path / "accepted_proposals.jsonl"
    q.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(cd, "queue_path", lambda: q)
    monkeypatch.setattr(cd, "ledger_path", lambda: tmp_path / "desk_leg.jsonl")
    monkeypatch.setattr(units, "load_strategy_config",
                        lambda *a, **k: {"claude_desk": cfg if cfg is not None else {"enabled": True}})

    class _DB:
        def __init__(self, *a, **k):
            if journal_raises:
                raise OSError("locked")

        def get_order_packages_by_strategy(self, name, **k):
            assert name == "claude_desk"
            return list(pkgs)

    import src.units.db.database as dbm
    monkeypatch.setattr(dbm, "Database", _DB)
    return ssb.claude_desk_signal_builder


def test_builder_emits_one_actionable_signal(monkeypatch, tmp_path):
    b = _builder(monkeypatch, tmp_path, [_row(at=datetime.now(timezone.utc))])
    sig = b({"SYMBOL": "BTCUSDT"})
    assert sig["side"] == "buy" and sig["stop_loss"] == 98.0 and sig["take_profit"] == 104.0
    assert sig["meta"]["decision_id"] == "d-1" and sig["meta"]["strategy_name"] == "claude_desk"
    from src.runtime.intents import intent_from_signal
    intent = intent_from_signal(sig, strategy="claude_desk")
    assert (intent.side, intent.sl, intent.tp) == ("long", 98.0, 104.0)


def test_builder_consumed_disabled_and_failclosed(monkeypatch, tmp_path):
    fresh = [_row(at=datetime.now(timezone.utc))]
    assert _builder(monkeypatch, tmp_path, fresh, pkgs=[{"meta": json.dumps({"decision_id": "d-1"})}])(
        {"SYMBOL": "BTCUSDT"})["side"] == "none"
    assert _builder(monkeypatch, tmp_path, fresh, cfg={"enabled": False})({"SYMBOL": "BTCUSDT"})["meta"]["reason"] == "disabled"
    sig = _builder(monkeypatch, tmp_path, fresh, journal_raises=True)({"SYMBOL": "BTCUSDT"})
    assert sig["side"] == "none" and sig["meta"]["reason"].startswith("journal_unreadable")
    assert _builder(monkeypatch, tmp_path, [])({"SYMBOL": "BTCUSDT"})["side"] == "none"


def test_builder_refuses_bracketless_proposal(monkeypatch, tmp_path):
    b = _builder(monkeypatch, tmp_path, [_row(at=datetime.now(timezone.utc), tp=None)])
    assert b({"SYMBOL": "BTCUSDT"})["side"] == "none"
    led = [json.loads(x) for x in (tmp_path / "desk_leg.jsonl").read_text().splitlines()]
    assert led == [dict(led[0], outcome="both_brackets_required:missing_tp")]


# ---------------------------------------------------------------- shadow sends nothing

def test_live_on_the_demo_floor_through_the_existing_gate(monkeypatch):
    """DECIDED 2026-10-27 (operator popup "Yes, live on bybit_1 demo now (Recommended)"): the leg is
    execution: live and the coordinator's ordinary execution gate (the same resolution as every leg, no new
    order path) decides; a flip back to shadow is the revert. Which accounts may receive a desk package is
    decided upstream by desk intake's demo-floor gate (tests/test_desk_demo_flip.py)."""
    from src.strategy_registry import execution_mode
    assert execution_mode("claude_desk") == "live"
    import src.core.coordinator as coord
    src = Path(coord.__file__).read_text()
    assert 'execution_mode(str(pkg.strategy)) == "shadow"' in src and '_dry_cause = "execution:shadow"' in src


def test_registered_once_and_rostered_only_on_soak_accounts():
    from src.runtime.intent_multiplexer import _resolve_builders
    from src.runtime.intents import DEFAULT_PRIORITIES
    from src.runtime.pipeline import monitor_unit_for
    assert "claude_desk" in _resolve_builders() and DEFAULT_PRIORITIES["claude_desk"] == 0
    assert monitor_unit_for("claude_desk") == "claude_desk"
    strategies = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]
    assert strategies["claude_desk"]["execution"] == "live"  # bybit_1 demo only (desk intake's demo floor)
    # AVAXUSDT only: the one bybit_1 symbol no other leg shares (same-symbol-allocation-guard).
    assert strategies["claude_desk"]["symbols"] == ["AVAXUSDT"]
    assert "risk_pct" not in strategies["claude_desk"]
    accounts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    on = sorted(a for a, v in accounts.items() if "claude_desk" in (v.get("strategies") or []))
    assert on == ["bybit_1"]  # alpaca_paper deferred: row DESK-17B (cross-venue symbol scope)


def test_intake_sees_the_leg_rostered():
    from scripts.ops import desk_intake
    assert desk_intake._leg_rostered() is True
    assert desk_intake.DESK_LEG == cd.NAME
    assert cd.queue_path() == desk_intake.log_dir() / "accepted_proposals.jsonl"
