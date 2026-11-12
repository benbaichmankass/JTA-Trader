"""PROP-SIZE-EXCEEDS-DD-CUSHION (2026-11-12): in-flight tickets reserve their risk at the stop in the cushion grade.

Incident: breakout_2 ml_entry ETH ``prop-manual-feb50ae29826`` (verified 08:03:20Z, resting limit journaled
``placed`` 08:03:40Z) and SOL ``prop-manual-f4c3fab02c11`` (verified 08:04:42Z) each graded against the whole
~$20.9 cushion, because ``compute_open_risk`` counts only open/filled positions. Both filled at 08:21Z: $34.86 to
the stops against $20.93 to the static floor.

The grade is the existing ``prop_risk_gate.grade_account_ticket_risk``; breach_guards semantics are unchanged
(``enforce`` refuses, ``report`` pings and proceeds).
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


def _cushion(monkeypatch, dd: float, state: str = "no_open_positions", open_loss: float = 0.0) -> None:
    """The snapshot side of the grade: ``dd`` to the static floor after open positions, freshness ok."""
    monkeypatch.setattr(prop_reconcile, "compute_rule_distance", lambda acct, status=None: {
        "status_freshness": "ok", "after_open_risk_state": state,
        "distance_to_dd_floor_after_open_risk_usd": dd, "distance_to_daily_loss_after_open_risk_usd": 150.0,
        "open_loss_to_stop_usd": open_loss})


def _guards(monkeypatch, mode: str) -> None:
    monkeypatch.setattr(prop_risk_gate, "breach_guards_for", lambda acct: mode)


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


# Each ticket risks 0.5 x (2500 - 2450) = $25 at the stop. A $40 cushion fits ONE of them, not two.

def test_two_tickets_verified_back_to_back_enforce_refuses_the_second(monkeypatch, _iso):
    _cushion(monkeypatch, 40.0)
    _guards(monkeypatch, "enforce")
    first = _claim_verify("a")
    assert first["ok"] is True and first["mode"] == "live"
    second = _claim_verify("b")
    assert second["ok"] is False
    why = " ".join(second["reasons"])
    assert "exceeds_cushion" in why and "$15.00" in why and "a" in why   # $40 - $25 reserved for "a"


def test_two_tickets_verified_back_to_back_report_pings_and_proceeds(monkeypatch, _iso):
    _cushion(monkeypatch, 40.0)
    _guards(monkeypatch, "report")
    assert _claim_verify("a")["ok"] is True
    second = _claim_verify("b")
    assert second["ok"] is True and second["mode"] == "live" and second["token"]
    ping = [m for m in _iso if "breach_guards=report" in m]
    assert ping and "exceeds_cushion" in ping[-1] and "in-flight ticket" in ping[-1] and " a" in ping[-1]


def test_redeemed_then_placed_keeps_the_reserve(monkeypatch, _iso):
    _cushion(monkeypatch, 40.0)
    _guards(monkeypatch, "enforce")
    v = _claim_verify("a")
    go = pe.redeem_go_token(_dev(), {"ticket_id": "a", "token": v["token"], "readback_sha256": v["readback_sha256"]})
    assert go["go"] is True
    assert prop_reconcile.compute_inflight_risk("breakout_2")["tickets"][0]["why"] == "claimed_go_redeemed"
    prop_journal.set_ticket_status("a", "placed", account_id="breakout_2")   # resting limit, not yet filled
    inf = prop_reconcile.compute_inflight_risk("breakout_2")
    assert inf["state"] == "measured" and inf["loss_to_stop_usd"] == 25.0 and inf["tickets"][0]["why"] == "placed"
    assert _claim_verify("b")["ok"] is False


def test_a_filled_ticket_is_not_double_counted(monkeypatch, _iso):
    _ticket("a", status="placed")
    assert prop_reconcile.compute_inflight_risk("breakout_2")["loss_to_stop_usd"] == 25.0
    # once a fill is journaled open, compute_open_risk carries it; the in-flight reserve drops it
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": "a", "symbol": "ETHUSDT",
                              "direction": "long", "status": "open", "qty": 0.5, "entry_price": 2500.0,
                              "sl": 2450.0})
    assert prop_reconcile.compute_inflight_risk("breakout_2")["state"] == "none"


def test_a_placed_report_fill_does_not_settle_the_ticket(monkeypatch, _iso):
    _ticket("a", status="placed")
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": "a", "symbol": "ETHUSDT",
                              "direction": "long", "status": "placed", "qty": 0.5, "entry_price": 2500.0,
                              "sl": 2450.0})
    assert prop_reconcile.compute_inflight_risk("breakout_2")["loss_to_stop_usd"] == 25.0


def test_the_graded_ticket_never_reserves_against_itself(monkeypatch, _iso):
    _ticket("a", status="placed")
    assert prop_reconcile.compute_inflight_risk("breakout_2", exclude_ticket_id="a")["state"] == "none"


def test_not_in_flight_expired_or_dry_or_refused_tokens_or_test_or_stale_placed(monkeypatch, _iso):
    now = datetime.now(timezone.utc)
    past, future = (now - timedelta(seconds=5)).isoformat(), (now + timedelta(seconds=25)).isoformat()
    _ticket("expired", status="claimed", meta={"phone": {"go": {"mode": "live", "used": False, "expires_at": past}}})
    _ticket("dry", status="claimed", meta={"phone": {"go": {"mode": "dry", "used": False, "expires_at": future}}})
    _ticket("refused", status="claimed", meta={"phone": {"go": {"mode": "live", "used": True, "go": False,
                                                                 "expires_at": future}}})
    _ticket("nogo", status="claimed", meta={"phone": {"device_id": "p1"}})
    _ticket("test", status="placed", meta={"test": True})
    _ticket("stale", status="placed", minutes=-(25 * 60))
    _ticket("emitted")
    assert prop_reconcile.compute_inflight_risk("breakout_2")["state"] == "none"
    _ticket("live", status="claimed", meta={"phone": {"go": {"mode": "live", "used": False, "expires_at": future,
                                                              "form": {"qty": 0.4, "price": 2500.0, "sl": 2450.0}}}})
    inf = prop_reconcile.compute_inflight_risk("breakout_2")
    # the verified FORM is what was submitted: 0.4 x 50, not the ticket's 0.5 x 50
    assert inf["state"] == "measured" and inf["loss_to_stop_usd"] == 20.0 and inf["tickets"][0]["why"] == "claimed_go_issued"


def test_an_in_flight_ticket_with_no_computable_risk_is_could_not_look(monkeypatch, _iso):
    _cushion(monkeypatch, 400.0)
    _ticket("a", status="placed", sl=None)
    assert prop_reconcile.compute_inflight_risk("breakout_2")["state"] == "risk_unknown"
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=5.0)
    assert g["state"] == prop_risk_gate.UNKNOWN and "in-flight" in g["reason"]


def test_an_unreadable_in_flight_read_is_could_not_look(monkeypatch, _iso):
    _cushion(monkeypatch, 400.0)

    def boom(*a, **k):
        raise RuntimeError("db locked")
    monkeypatch.setattr(prop_journal, "list_tickets", boom)
    assert prop_reconcile.compute_inflight_risk("breakout_2")["state"] == "unreadable"
    assert prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=5.0)["state"] == prop_risk_gate.UNKNOWN


def test_the_2026_11_12_incident_numbers_now_grade_exceeds(monkeypatch, _iso):
    # ETH resting limit 0.61 @ 2050.56, SL 2022.06 (form); SOL form 11.81 @ 82.96, SL 81.48; $20.93 to the floor.
    _cushion(monkeypatch, 20.93)
    _ticket("prop-manual-feb50ae29826", status="placed", entry=2050.56, sl=2022.0557142857142, qty=0.61394277,
            meta={"phone": {"go": {"mode": "live", "used": True, "go": True,
                                   "form": {"qty": 0.61, "price": 2050.56, "sl": 2022.06}}}})
    sol_risk = round(11.81 * (82.96 - 81.48), 6)
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=sol_risk,
                                                 exclude_ticket_id="prop-manual-f4c3fab02c11")
    assert g["state"] == prop_risk_gate.EXCEEDS
    assert abs(g["cushion_usd"] - (20.93 - 0.61 * 28.5)) < 1e-6          # $3.545 left, not $20.93
    assert g["inflight"]["tickets"][0]["ticket_id"] == "prop-manual-feb50ae29826"
    # Without the reserve (pre-fix) the same SOL risk graded WITHIN — the incident.
    assert prop_risk_gate.grade_ticket_risk(risk_usd=sol_risk, distance_to_dd_floor_usd=20.93,
                                            status_freshness="ok")["state"] == prop_risk_gate.WITHIN


def test_open_positions_and_in_flight_add(monkeypatch, _iso):
    _cushion(monkeypatch, 30.0, state="measured", open_loss=10.0)
    _ticket("a", status="placed")
    g = prop_risk_gate.grade_account_ticket_risk("breakout_2", risk_usd=4.0)
    assert g["state"] == prop_risk_gate.WITHIN and g["cushion_usd"] == 5.0 and g["open_loss_to_stop_usd"] == 35.0
