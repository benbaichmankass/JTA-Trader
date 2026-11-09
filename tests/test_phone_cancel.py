"""PHONE-ENTRY-CANCEL: the server half of the phone's stale-entry cancel (src/prop/phone_cancel.py).

One request per ticket, only for a PLACED entry that is past valid_until, whose package is closed, or that a newer
same-strategy ticket waits on; served only to an app that declares "cancel"; reported placed/cancelled/not_found/
ambiguous/refused. Only cancelled / not_found end it; every failure backs off, flags once, never stops."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.prop import phone_cancel as pc
from src.prop import phone_executor as pe
from src.prop import prop_journal

TOKEN = "t" * 43
SIG = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
VU = SIG + timedelta(minutes=52)                   # 01:52Z, like prop-manual-c1391d5720b1
NOW = datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc)


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
    sent: list = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: sent.append(m) or True)
    return sent


def _dev() -> pe.PhoneDevice:
    return pe.authenticate("Bearer " + TOKEN)


def _t(tid="C1", *, status="placed", meta=None, direction="short", qty=0.3936, entry=2193.86, vu=VU, pkg=None):
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": "breakout_2", "strategy": "trend_donchian_eth_4h", "symbol": "ETHUSDT",
        "direction": direction, "entry": entry, "sl": 2260.0, "tp": 2000.0, "qty": qty,
        "signal_time": SIG.isoformat(), "valid_until": vu.isoformat() if vu else None, "status": status,
        "order_package_id": pkg, "meta": meta})


def _c(tid="C1"):
    return (prop_journal.get_ticket(tid)["meta"] or {}).get(pc.KEY) or {}


def test_expired_placed_entry_is_planned_with_its_four_facts():
    _t()
    assert pc.plan_cancels("breakout_2", now=NOW) == 1
    c = _c()
    assert c["status"] == "emitted" and c["reason"] == "expired"
    assert c["spec"]["side"] == "sell" and c["spec"]["price"] == 2193.86 and c["spec"]["venue_symbol"] == "ETHUSD"
    assert c["spec"]["qty"] == pytest.approx(0.3936, abs=0.01)


def test_not_planned_when_unexpired_unplaced_filled_or_test():
    _t("A", vu=NOW + timedelta(hours=1))
    _t("B", status="emitted")
    _t("F", status="filled")
    _t("T", meta={"test": True})
    _t("X", meta={"origin": "exec_test"})
    assert pc.plan_cancels("breakout_2", now=NOW) == 0
    assert all(not _c(t) for t in "ABFTX")


def test_closed_package_makes_an_unexpired_entry_eligible():
    _t("P", vu=NOW + timedelta(hours=1), pkg="PKG1")
    conn = prop_journal._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS order_packages (order_package_id TEXT PRIMARY KEY, status TEXT, close_reason TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO order_packages VALUES ('PKG1','closed','strategy_exit','2026-11-09T02:35:00Z')")
    conn.commit()
    conn.close()
    assert pc.plan_cancels("breakout_2", now=NOW) == 1
    assert _c("P")["reason"] == "package_closed"


def test_superseded_entry_is_eligible_only_while_the_newer_ticket_is_valid():
    _t("O", vu=NOW + timedelta(hours=1))
    cand = {"supersede": {"blocked_by": "O", "valid_until": (NOW + timedelta(minutes=30)).isoformat()}}
    _t("N", status="suppressed", meta=cand, vu=NOW + timedelta(minutes=30))
    assert pc.plan_cancels("breakout_2", now=NOW) == 1 and _c("O")["reason"] == "superseded"


def test_unreadable_spec_plans_nothing():
    _t(qty=0.0)
    assert pc.plan_cancels("breakout_2", now=NOW) == 0


def test_claim_serves_cancel_only_to_an_app_that_accepts_it():
    _t()
    assert pe.claim_next(_dev(), now=NOW) is None                      # old app
    assert pe.claim_next(_dev(), now=NOW, accepts=("amend",)) is None   # amend-only app
    assert pe.pending_count(_dev(), now=NOW, accepts=("cancel",)) == 1
    got = pe.claim_next(_dev(), now=NOW, accepts=("cancel",))
    assert got["kind"] == "cancel" and got["ticket_id"] == "C1" and got["spec"]["side"] == "sell"
    assert _c()["status"] == "claimed"
    assert pe.claim_next(_dev(), now=NOW, accepts=("cancel",)) is None  # one claim only


def test_reason_is_rechecked_at_claim():
    _t()
    pc.plan_cancels("breakout_2", now=NOW)
    prop_journal.set_ticket_status("C1", "filled", account_id="breakout_2")
    assert pc.claim_cancel(_dev(), now=NOW) is None


def _rep(body, now=NOW):
    """The report at an explicit time (record_report itself uses the wall clock, which would make backoff tests drift)."""
    return pc.record_cancel_result(_dev(), body, now=now)


def _claim():
    _t()
    return pe.claim_next(_dev(), now=NOW, accepts=("cancel",))


def test_cancelled_closes_the_ticket_as_skipped(_iso):
    g = _claim()
    out = pe.record_report(_dev(), {"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": "cancelled"})
    assert out["ok"] and prop_journal.get_ticket("C1")["status"] == "skipped" and _c()["status"] == "cancelled"
    assert any("CANCELLED" in m for m in _iso)
    assert pe.claim_next(_dev(), now=NOW + timedelta(hours=1), accepts=("cancel",)) is None


def test_not_found_closes_as_skipped_and_asks_to_check_for_a_position(_iso):
    g = _claim()
    pe.record_report(_dev(), {"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": "not_found"})
    assert prop_journal.get_ticket("C1")["status"] == "skipped"
    assert any("CHECK the terminal for a position" in m for m in _iso)


@pytest.mark.parametrize("res", ["placed", "ambiguous", "refused"])
def test_failures_keep_the_ticket_placed_and_back_off(res):
    g = _claim()
    _rep({"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": res, "reason": "x"})
    assert prop_journal.get_ticket("C1")["status"] == "placed" and _c()["status"] == "failed" and _c()["attempts"] == 1
    assert pc.plan_cancels("breakout_2", now=NOW + timedelta(minutes=1)) == 0       # backing off
    assert pc.plan_cancels("breakout_2", now=NOW + timedelta(minutes=11)) == 1      # retried
    assert _c()["id"].endswith("-c2")


def test_one_flag_after_three_failures_and_it_never_stops(_iso):
    _t()
    t = NOW
    for _ in range(4):
        g = None
        pc.plan_cancels("breakout_2", now=t)
        g = pe.claim_next(_dev(), now=t, accepts=("cancel",))
        assert g is not None
        _rep({"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": "ambiguous"}, now=t)
        t += timedelta(hours=7)
    assert sum("failed 3 times" in m for m in _iso) == 1 and prop_journal.get_ticket("C1")["status"] == "placed"
    assert pc.plan_cancels("breakout_2", now=t) == 1                                # still trying


def test_unreported_claim_is_rearmed_after_the_watchdog():
    _claim()
    assert pc.plan_cancels("breakout_2", now=NOW + timedelta(seconds=60)) == 0 and _c()["status"] == "claimed"
    pc.plan_cancels("breakout_2", now=NOW + timedelta(seconds=200))
    assert _c()["status"] == "failed" and _c()["last_result"] == "unreported"


def test_a_stale_or_wrong_report_is_refused():
    g = _claim()
    bad = pe.record_report(_dev(), {"kind": "cancel_result", "ticket_id": "C1", "cancel_id": "other", "result": "cancelled"})
    assert not bad["ok"] and prop_journal.get_ticket("C1")["status"] == "placed"
    with pytest.raises(ValueError):
        pe.record_report(_dev(), {"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": "closed_it"})


def test_the_router_accepts_the_cancel_capability():
    from src.web.api.routers import prop as router
    assert router._accepts(["amend", "cancel", "junk"]) == ("amend", "cancel")
