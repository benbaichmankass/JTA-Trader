"""TELEGRAM-TRIM (operator 2026-11-10): every TRADE UPDATED ping names WHAT MECHANISM made the
change (``Source: <label>``); prop_monitor pings are recorded, not sent; a testing-paper demo ping
no longer bypasses the trades policy. Notification text/routing only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from src.runtime import execution_diagnostics as ed
from src.runtime import telegram_channels, telegram_policy as tp
from src.runtime import trade_update_source as tus

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def captured(monkeypatch):
    got: List[dict] = []
    monkeypatch.setattr(ed, "enqueue_trade_update", lambda **kw: got.append(kw))
    return got


# ── the label helper ────────────────────────────────────────────────────────
def test_unknown_is_never_blank():
    for v in (None, "", "   "):
        assert tus.normalize(v) == "source unknown"
    assert tus.normalize("rule: trail\nx") == "rule: trail x"


@pytest.mark.parametrize("verdict,label", [
    ({"tp": 1.0, "tp_reason": "ml_first_passage: target 1 (+2.0R from entry)"}, "ML: TP revision (ml_first_passage)"),
    ({"tp": 1.0, "tp_reason": "tp_extend: target 1"}, "rule: tp_extend"),
    ({"action": "close", "reason": "exit_head"}, "ML: exit head"),
    ({"action": "close", "close_qty_pct": 0.5, "reason": "partial_tp1"}, "rule: partial_tp1"),
    ({"sl": 99.0}, "rule: strategy monitor (leg_x)"),
    (None, "rule: strategy monitor (leg_x)"),
])
def test_monitor_verdict_labels(verdict, label):
    assert tus.from_monitor_verdict(verdict, "leg_x") == label


# ── the body and the ledger ─────────────────────────────────────────────────
def _body(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path)
    monkeypatch.setenv("TELEGRAM_POLICY_CLAIMS_DIR", str(tmp_path / "claims"))
    path = ed.enqueue_trade_update(symbol="BTCUSDT", account="unclassified_acct", strategy="s",
                                   changes=["SL → 1"], **kw)
    return json.loads(path.read_text())["body"]


def test_ping_renders_the_source_line(tmp_path, monkeypatch):
    assert "Source" in (b := _body(tmp_path, monkeypatch, source="Claude live review (r1)"))
    assert "Claude live review (r1)" in b


def test_missing_source_renders_source_unknown(tmp_path, monkeypatch):
    assert "source unknown" in _body(tmp_path, monkeypatch)


def test_suppressed_update_records_the_source_in_the_ledger(tmp_path, monkeypatch):
    pol = {"trades": {"testing_paper": "suppress"}}
    rows = []
    monkeypatch.setattr(tp, "record_suppressed", lambda kind, text, **f: rows.append(f) or True)
    d = tp.should_send_trade("trade-update", "x", account="a", strategy="s", symbol="X",
                             source="rule: trail", policy=pol, accounts={"a": {"account_class": "paper"}})
    assert not d.send and rows[0]["source"] == "rule: trail"


# ── each caller passes its mechanism ────────────────────────────────────────
def test_live_review_apply_labels(captured):
    from scripts.ops import live_review_apply as lra
    from tests.test_live_review_apply import PKG, _intent
    lra._ping(PKG, "bybit_2", 0.21, _intent())
    lra._alert(PKG, "bybit_2", "refused")
    assert captured[0]["source"].startswith("Claude live review (") and "None" not in captured[0]["source"]
    assert captured[1]["source"].startswith("Claude live review")


def test_live_review_dispatch_label(captured):
    from scripts.ops import live_review_dispatch as d
    d._ping({"review_id": "rv9", "symbol": "X", "leg": "l", "accounts": ["a"]}, "why")
    assert captured[0]["source"] == "Claude live review (rv9)"


def test_amend_position_sl_label(captured):
    from scripts.ops import amend_position_sl as a
    a._ping({"symbol": "X", "account_id": "a", "strategy_name": "s"}, 1.0, 1)
    assert captured[0]["source"] == f"manual ({a.PROVENANCE})"


def test_directed_action_label(captured):
    from scripts.ops import directed_action as cli
    cli._ping({"id": "r1", "directed_by": "manager", "operator_quote": "q"},
              {"symbol": "X", "accounts": [], "strategy": "s"}, "applied")
    assert captured[0]["source"] == "manual (manager)"


def test_desk_label(captured):
    from scripts.ops import desk_intake as di
    di._flag("row failed")
    assert captured[0]["source"] == "desk"


def test_order_monitor_labels(monkeypatch):
    from src.runtime import order_monitor as om
    assert om._update_source({"tp": 1.0, "tp_reason": "ml_first_passage: t"}, "s") == "ML: TP revision (ml_first_passage)"
    assert om._update_source({"sl": 1.0}, "s") == "rule: strategy monitor (s)"
    assert om._update_source(object(), None) == "rule: strategy monitor"


# ── prop_monitor off; demo ping obeys the policy ────────────────────────────
def test_prop_monitor_is_recurring_off_and_not_an_alert():
    assert tp.recurring_off("prop_monitor")
    assert "prop_monitor" not in telegram_channels.UNMUTABLE
    for kept in ("prop_fill", "prop_ticket", "prop_alert"):
        assert not tp.recurring_off(kept)


def test_prop_monitor_send_is_recorded_not_sent(monkeypatch):
    rows = []
    monkeypatch.setattr(tp, "record_suppressed", lambda kind, text, **f: rows.append((kind, f)) or True)
    import src.runtime.notify as notify
    monkeypatch.setattr(notify, "send_telegram_direct",
                        lambda *a, **k: pytest.fail("prop_monitor must not reach Telegram"))
    assert telegram_channels.send("prop_monitor", "pulse") is False
    assert rows and rows[0][0] == "prop_monitor"


def test_demo_ping_for_testing_paper_is_suppressed(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path)
    monkeypatch.setenv("TELEGRAM_POLICY_CLAIMS_DIR", str(tmp_path / "claims"))
    monkeypatch.setattr(tp, "record_suppressed", lambda *a, **k: True)
    monkeypatch.setattr(tp, "account_class", lambda a, accts=None: tp.TESTING_PAPER)
    assert ed.enqueue_demo_trade_notification(account="bybit_1", strategy="s", symbol="X", side="buy",
                                              qty=1.0, status="submitted", detail="d") is None
    assert not list(tmp_path.glob("*.json"))


# ── muting is operator-only: the manager wake (TELEGRAM-TRIM 2026-11-10) ────
def test_suppressed_high_paper_flag_wakes_the_manager_and_routine_does_not(tmp_path, monkeypatch):
    from src.runtime import alerts_ledger as al
    monkeypatch.setenv("ALERTS_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    accts = {"p": {"account_class": "paper"}}
    pol = {"trades": {"testing_paper": "suppress", "bypass_priorities": ["high", "urgent"]}}
    for prio, kind in (("high", "trade-update"), ("normal", "trade-open"), ("normal", "trade-update")):
        d = tp.should_send_trade(kind, f"{prio} {kind}", account="p", strategy="s", symbol="X",
                                 priority=prio, policy=pol, accounts=accts)
        assert not d.send
    rows = al.read()["rows"]
    woke = {(r["kind"], r["priority"]): al.wakes_manager(r) for r in rows}
    assert woke[("trade-update", "high")] is True      # the flag reaches the manager path
    assert woke[("trade-open", "normal")] is False     # routine paper noise does not
    assert woke[("trade-update", "normal")] is False


def test_other_suppressed_rows_wake_rules():
    from src.runtime import alerts_ledger as al
    sup = "suppressed_by_policy"
    assert not al.wakes_manager(al.build_row("prop_monitor", "trades", "x", delivered=sup))
    assert not al.wakes_manager(al.build_row("trades_snapshot", "system", "x", delivered=sup))
    assert not al.wakes_manager(al.build_row("pr_merged", "manager", "x", delivered=sup))
    # a testing-paper rejection that went ledger_only (execution_alert, system, high) wakes
    assert al.wakes_manager(al.build_row("execution_alert", "system", "x", delivered=sup))
    # delivered trades rows still never wake
    assert not al.wakes_manager(al.build_row("trade-update", "trades", "x", priority="high", delivered="telegram_ok"))


def test_end_to_end_plan_alert_comment_includes_the_suppressed_high_paper_flag(tmp_path, monkeypatch):
    """The real consumer (attention_watch.plan_alert_comment) posts the suppressed high flag, not routine rows."""
    from datetime import datetime, timezone
    from scripts.ops import attention_watch as aw
    from src.runtime import alerts_ledger as al
    monkeypatch.setenv("ALERTS_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    accts = {"p": {"account_class": "paper"}}
    pol = {"trades": {"testing_paper": "suppress", "bypass_priorities": ["high"]}}
    tp.should_send_trade("trade-update", "FLAG not_applied", account="p", strategy="s", symbol="X",
                         priority="high", policy=pol, accounts=accts)
    tp.should_send_trade("trade-open", "ROUTINE open", account="p", strategy="s", symbol="Y",
                         priority="normal", policy=pol, accounts=accts)
    body, _state, summary = aw.plan_alert_comment(al.read()["rows"], {}, datetime.now(timezone.utc))
    assert body and "FLAG not_applied" in body and "ROUTINE open" not in body
    assert summary["posted_kinds"] == ["trade-update"]
