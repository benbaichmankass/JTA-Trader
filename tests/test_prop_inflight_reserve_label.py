"""AM-PROP-INFLIGHT-RESERVE: MAKE REPORT-ONLY (operator 2026-11-12, decisions page, Gates tab; record
comms/gates/gate_decisions_2026-11-12.json). Supersedes PR #25223.

The in-flight reserve (tickets verified / placed but not yet filled) is computed by
``prop_reconcile.compute_inflight_risk`` (ported from #25223) and carried on the cushion grade as a LABEL
(``grade["inflight"]``, with ``would_exceed``). It never changes the grade's state or distances, never refuses, and
an unreadable / risk_unknown reserve is never ``cushion_unknown``. The phone pings it; the submit proceeds.

Incident it exists for: breakout_2 ETH ``prop-manual-feb50ae29826`` (resting limit, journaled placed) and SOL
``prop-manual-f4c3fab02c11`` (verified 80 s later) each graded against the whole ~$20.9 cushion; both filled.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.prop import phone_executor as pe
from src.prop import prop_journal, prop_reconcile, prop_risk_gate

TOKEN = "t" * 43


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()},
    ]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: None)
    acc = tmp_path / "accounts.yaml"
    acc.write_text(yaml.safe_dump({"accounts": {"breakout_2": {"mode": "live"}}}))
    monkeypatch.setattr(pe, "ACCOUNTS_PATH", acc)
    sent: list = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: sent.append(m) or True)
    return sent


def _cushion(monkeypatch, dd: float) -> None:
    monkeypatch.setattr(prop_reconcile, "compute_rule_distance", lambda acct, status=None: {
        "status_freshness": "ok", "after_open_risk_state": "no_open_positions",
        "distance_to_dd_floor_after_open_risk_usd": dd, "distance_to_daily_loss_after_open_risk_usd": 150.0,
        "open_loss_to_stop_usd": 0.0})


def _dev() -> pe.PhoneDevice:
    return pe.authenticate("Bearer " + TOKEN)


def _ticket(tid: str, *, minutes: int = 10, status: str = "emitted", meta=None, **over) -> None:
    now = datetime.now(timezone.utc)
    t = {"ticket_id": tid, "account_id": "breakout_2", "strategy": "ml_entry", "symbol": "ETHUSDT",
         "direction": "long", "entry": 2500.0, "sl": 2450.0, "tp": 2700.0, "qty": 0.5,
         "valid_until": (now + timedelta(minutes=minutes)).isoformat(), "status": status, "meta": meta}
    t.update(over)
    prop_journal.record_ticket(t)


def _rb(tid: str) -> dict:
    return {"ticket_id": tid, "symbol": "ETHUSD", "side": "Buy", "order_type": "Limit", "price": "2,500.00",
            "qty": "0.50", "qty_unit": "ETH", "tp": "2700.00", "sl": "2450.00",
            "submit_label": "Long (buy) ETHUSD", "submit_disabled": "false", "tpsl": "true"}


def _claim_verify(tid: str) -> dict:
    _ticket(tid)
    assert pe.claim_next(_dev())["ticket_id"] == tid
    rb = _rb(tid)
    return pe.verify_readback(_dev(), {"ticket_id": tid, "readback": rb, "readback_sha256": pe.readback_hash(rb)})


# Each ticket risks 0.5 x (2500 - 2450) = $25 at the stop. A $40 cushion fits ONE of them alone, not two.

def test_two_tickets_back_to_back_the_second_is_pinged_and_proceeds(monkeypatch, _iso):
    _cushion(monkeypatch, 40.0)
    monkeypatch.setattr(prop_risk_gate, "breach_guards_for", lambda acct: "enforce")
    assert _claim_verify("a")["ok"] is True
    second = _claim_verify("b")
    assert second["ok"] is True and second["mode"] == "live" and second["token"]   # never refused
    ping = [m for m in _iso if "AM-PROP-INFLIGHT-RESERVE" in m]
    assert ping and "would pass the cushion" in ping[-1] and " a" in ping[-1]


def test_the_label_never_changes_the_grade(monkeypatch, _iso):
    _cushion(monkeypatch, 40.0)
    _ticket("a", status="placed")
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=25.0)
    assert g["state"] == prop_risk_gate.WITHIN and g["cushion_usd"] == 40.0       # not reduced by the reserve
    assert g["inflight"]["state"] == "measured" and g["inflight"]["loss_to_stop_usd"] == 25.0
    assert g["inflight"]["would_exceed"] is True


@pytest.mark.parametrize("how", ["risk_unknown", "unreadable"])
def test_an_unread_reserve_is_a_label_never_cushion_unknown(monkeypatch, _iso, how):
    _cushion(monkeypatch, 400.0)
    if how == "risk_unknown":
        _ticket("a", status="placed", sl=None)
    else:
        def boom(*a, **k):
            raise RuntimeError("db locked")
        monkeypatch.setattr(prop_journal, "list_tickets", boom)
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=5.0)
    assert g["state"] == prop_risk_gate.WITHIN and g["inflight"]["state"] == how


def test_the_graded_ticket_never_reserves_against_itself_and_fills_are_not_double_counted(monkeypatch, _iso):
    _ticket("a", status="placed")
    assert prop_reconcile.compute_inflight_risk("breakout_2", exclude_ticket_id="a")["state"] == "none"
    assert prop_reconcile.compute_inflight_risk("breakout_2")["loss_to_stop_usd"] == 25.0
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": "a", "symbol": "ETHUSDT",
                              "direction": "long", "status": "open", "qty": 0.5, "entry_price": 2500.0,
                              "sl": 2450.0})
    assert prop_reconcile.compute_inflight_risk("breakout_2")["state"] == "none"


def test_the_2026_11_12_incident_numbers_are_labelled_would_exceed(monkeypatch, _iso):
    _cushion(monkeypatch, 20.93)
    _ticket("prop-manual-feb50ae29826", status="placed", entry=2050.56, sl=2022.0557142857142, qty=0.61394277,
            meta={"phone": {"go": {"mode": "live", "used": True, "go": True,
                                   "form": {"qty": 0.61, "price": 2050.56, "sl": 2022.06}}}})
    sol_risk = round(11.81 * (82.96 - 81.48), 6)
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=sol_risk,
                                                 exclude_ticket_id="prop-manual-f4c3fab02c11")
    assert g["state"] == prop_risk_gate.WITHIN          # the decision is unchanged (report-only)
    assert g["inflight"]["would_exceed"] is True
    assert g["inflight"]["tickets"][0]["ticket_id"] == "prop-manual-feb50ae29826"
