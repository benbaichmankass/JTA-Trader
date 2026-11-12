"""Claim-time re-check of the opposite-direction guard (manager 2026-11-09): a phone ticket is claimed minutes after emission, and a position another leg holds
can open in between. The exact incident: ml_entry SOL LONG vs an open trend SOL SHORT on breakout_2 (04:02Z); the phone filled the buy form and only the read-back
``cushion_unknown`` gate stopped it."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.prop import phone_executor as pe
from src.prop import prop_journal

TOKEN = "t" * 43


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: None)
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: True)


def _dev() -> pe.PhoneDevice:
    return pe.authenticate("Bearer " + TOKEN)


def _ml_long(tid: str = "prop-manual-baafc9daacf1") -> None:
    now = datetime.now(timezone.utc)
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": "breakout_2", "strategy": "ml_entry", "symbol": "SOLUSDT", "direction": "long",
        "entry": 87.43, "sl": 85.08, "tp": 90.95, "qty": 7.45, "risk_usd": 17.5,
        "valid_until": (now + timedelta(minutes=30)).isoformat(), "status": "emitted"})


def _trend_short(tid: str = "prop-manual-ed6dc04db93b", strategy: str = "trend_donchian_sol_4h") -> None:
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": "breakout_2", "strategy": strategy, "symbol": "SOLUSDT", "direction": "short",
        "entry": 87.64, "sl": 91.0, "tp": 80.0, "qty": 6.82, "status": "placed"})
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": tid, "symbol": "SOLUSDT", "direction": "short", "qty": 6.82,
                              "entry_price": 87.64, "status": "open", "external_order_id": f"inferred-{tid}"})


def _status(tid: str) -> str:
    return next(t["status"] for t in prop_journal.list_tickets(account_id="breakout_2", limit=50) if t["ticket_id"] == tid)


def test_negative_control_with_no_opposite_position_the_ticket_is_claimed():
    _ml_long()
    got = pe.claim_next(_dev())
    assert got and got["ticket_id"] == "prop-manual-baafc9daacf1" and got["status"] == "claimed"


def test_the_incident_shape_is_now_served_and_the_opposite_position_is_recorded():
    # AM-PROP-CLAIM-TIME-BLOCKS: REMOVE (operator 2026-11-12: "this is managed at the strategy/risk manager level").
    # The claim-time re-check still runs and is recorded on the ticket, but the ticket is SERVED.
    _ml_long()                      # emitted first ...
    _trend_short()                  # ... then the trend short is on the books
    got = pe.claim_next(_dev())
    assert got and got["ticket_id"] == "prop-manual-baafc9daacf1" and got["status"] == "claimed"
    obs = got["meta"]["claim_observed"]
    assert "trend_donchian_sol_4h" in json.dumps(obs) and "served" in obs["action"]


def test_the_same_leg_reversal_is_still_claimed():
    _ml_long()
    _trend_short(strategy="ml_entry")
    assert (pe.claim_next(_dev()) or {}).get("ticket_id") == "prop-manual-baafc9daacf1"


def test_another_still_emitted_opposite_ticket_does_not_block_the_claim():
    _ml_long()
    now = datetime.now(timezone.utc)
    prop_journal.record_ticket({
        "ticket_id": "prop-manual-dddddddddddd", "account_id": "breakout_2", "strategy": "trend_donchian_sol_4h", "symbol": "SOLUSDT",
        "direction": "short", "entry": 87.6, "sl": 91.0, "tp": 80.0, "valid_until": (now + timedelta(minutes=30)).isoformat(), "status": "emitted"})
    got = pe.claim_next(_dev())
    assert got and got["ticket_id"] in ("prop-manual-baafc9daacf1", "prop-manual-dddddddddddd")


def test_an_unreadable_journal_defers_the_claim_without_killing_the_ticket(monkeypatch):
    from src.prop import breakout_executor as BE

    _ml_long()
    monkeypatch.setattr(BE, "_opposite_direction_block_reason",
                        lambda *a, **k: "opposite_check_unreadable: RuntimeError")
    # AM-PROP-CLAIM-TIME-BLOCKS removed 2026-11-12: an unreadable re-check no longer defers; it is recorded and served
    got = pe.claim_next(_dev())
    assert got and got["meta"]["claim_observed"]["opposite_direction"].startswith("opposite_check_unreadable")
    assert _status("prop-manual-baafc9daacf1") == "claimed"
