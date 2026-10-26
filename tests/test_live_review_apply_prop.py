"""LTR-6R: the prop VM and phone executors of the live-review apply path, end to
end on a real (temporary) ``prop_tickets`` table — the operator's 2026-10-25
apply scope is ALL accounts, so the prop paths must be ready, not just Bybit.

* prop VM: ``_exec_prop_vm`` writes ``meta.sl_floor``, reads it back, the
  ``/api/bot/prop/tickets`` projection carries it as ``sl_floor`` (what the VM
  executor reads), and ``prop_trail.plan_trail`` tightens TO it.
* phone: ``_exec_phone`` → ``request_sl_tighten`` emits one ``kind: sl`` amend
  in the one-slot channel, reads it back, and the phone's claim serves it.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from scripts.ops import live_review_apply as lra
from src.prop import phone_executor as pe
from src.prop import phone_trail as ptr
from src.prop import prop_journal
from src.prop import prop_trail
from src.runtime import live_review_intent as lri

TOKEN = "t" * 43
SIG = datetime(2026, 10, 25, 10, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    acc = tmp_path / "accounts.yaml"
    acc.write_text(yaml.safe_dump({"accounts": {"breakout_2": {"mode": "live"}}}))
    monkeypatch.setattr(pe, "ACCOUNTS_PATH", acc)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    monkeypatch.setattr(pe, "_unserved_dry_test_request", lambda acct: None)
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: True)
    monkeypatch.setattr(prop_journal, "_prop_scope", lambda acct: set())   # sidecar-only ticket view


def _ticket(tid, account, *, status="filled", sl=2550.0, meta=None):
    prop_journal.ensure_tables()
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": account, "strategy": "trend_donchian_eth_prop", "symbol": "ETHUSDT",
        "direction": "short", "entry": 2500.0, "sl": sl, "tp": 2200.0, "qty": 0.5,
        "signal_time": SIG.isoformat(), "valid_until": (SIG + timedelta(minutes=10)).isoformat(),
        "status": status, "meta": meta, "order_package_id": "pkg-P"})
    return {"row": {"ticket_id": tid, "account_id": account}}


def _intent(**kw):
    base = dict(order_package_id="pkg-P", action="tighten_sl", direction="short", review_id="LR-20261025T1900Z-P",
                new_sl=2530.0, mark=2490.0, atr=20.0, bar_ts="2026-10-25T18:00:00Z", mandate=lri.MANDATE_ID,
                basis=lri.BASIS_TABLE, mechanics_verdict="match", expected_cost_r=-0.1, worst_case_delta_r=0.4)
    base.update(kw)
    return lri.LiveReviewIntent(**base)


# ------------------------------------------------------------------ prop VM

def test_prop_vm_floor_is_written_read_back_projected_and_trailed_to():
    leg = _ticket("V1", "tradeify_1")
    res = lra._exec_prop_vm(leg, 2530.0, _intent())
    assert res["result"] == lra.X_APPLIED
    assert lri.sl_floor_from(prop_journal.get_ticket("V1")["meta"]) == 2530.0
    # what the VM executor reads (/api/bot/prop/tickets)
    row = {r["ticket_id"]: r for r in prop_journal.list_outbound_tickets(account_id="tradeify_1")}["V1"]
    assert row["sl_floor"] == 2530.0
    # ...and the prop trail tightens TO it (replay alone would not: flat bars)
    bars = pd.DataFrame([{"timestamp": SIG + timedelta(hours=1 + i), "open": 2495, "high": 2500, "low": 2490,
                          "close": 2495} for i in range(4)])
    plan = prop_trail.plan_trail(leg={"trail_mult": 3.5, "atr_stop_mult": 2.5, "timeframe": "1h"},
                                 direction="short", entry=2500.0, initial_sl=2550.0, signal_time=SIG,
                                 resting_sl=2550.0, candles=bars, now=SIG + timedelta(hours=6),
                                 sl_floor=row["sl_floor"])
    assert plan.action == "tighten" and plan.sl == pytest.approx(2530.0)


def test_prop_vm_refuses_a_ticket_that_is_no_longer_open_and_cannot_look_at_a_missing_one():
    assert lra._exec_prop_vm(_ticket("V2", "velotrade_1", status="closed"), 2530.0, _intent())["result"] \
        == lra.X_REFUSED
    assert lra._exec_prop_vm({"row": {"ticket_id": "nope", "account_id": "velotrade_1"}}, 2530.0,
                             _intent())["result"] == lra.X_COULD_NOT_LOOK


# -------------------------------------------------------------------- phone

def test_phone_tighten_is_emitted_read_back_and_served_to_the_phone():
    leg = _ticket("B1", "breakout_2", status="placed")
    res = lra._exec_phone(leg, 2530.0, _intent())
    assert res["result"] == lra.X_APPLIED and res["amend_id"] == "B1#a1"
    meta = prop_journal.get_ticket("B1")["meta"]
    assert meta["sl_floor"]["level"] == pytest.approx(2530.0)
    am = meta[ptr.KEY]["amend"]
    assert (am["kind"], am["status"], am["sl"], am["tp"]) == ("sl", "emitted", pytest.approx(2530.0), 2200.0)
    claim = ptr.claim_amend(pe.authenticate("Bearer " + TOKEN))
    assert claim and claim["amend_id"] == "B1#a1" and claim["sl"] == pytest.approx(2530.0)


def test_phone_refuses_a_loosen_and_an_outstanding_slot_still_records_the_floor():
    _ticket("B2", "breakout_2", status="placed")
    loose = lra._exec_phone({"row": {"ticket_id": "B2", "account_id": "breakout_2"}}, 2560.0, _intent())
    assert loose["result"] == lra.X_REFUSED and "does not tighten" in loose["detail"]
    assert lra._exec_phone({"row": {"ticket_id": "B2", "account_id": "breakout_2"}}, 2530.0,
                           _intent())["result"] == lra.X_APPLIED
    busy = lra._exec_phone({"row": {"ticket_id": "B2", "account_id": "breakout_2"}}, 2520.0, _intent())
    assert busy["result"] == lra.X_REFUSED and busy["floor_recorded"] is True
    assert lri.sl_floor_from(prop_journal.get_ticket("B2")["meta"]) == pytest.approx(2520.0)
