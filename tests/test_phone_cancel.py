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


# ---------------------------------------------------------------- close / reduce (the general action channel)
def _held(tid="H1", status="filled"):
    _t(tid, status=status, vu=NOW - timedelta(hours=1))


def _xc(tid="H1"):
    return (prop_journal.get_ticket(tid)["meta"] or {}).get(pc.CLOSE_KEY) or {}


def _rx(body, now=NOW):
    return pc.record_close_result(_dev(), body, now=now)


def test_close_request_is_for_a_named_open_ticket_only():
    _held()
    r = pc.request_close("breakout_2", "H1", reason="review R1", now=NOW)
    assert r["ok"] and r["action"] == "close" and _xc()["spec"]["side"] == "short" and _xc()["spec"]["fraction"] is None
    assert not pc.request_close("breakout_2", "H1", now=NOW)["ok"]                 # one outstanding slot
    assert not pc.request_close("breakout_2", "nope", now=NOW)["ok"]
    _t("E1", status="emitted")
    assert "no position" in pc.request_close("breakout_2", "E1", now=NOW)["why"]
    _t("T1", status="filled", meta={"test": True})
    assert not pc.request_close("breakout_2", "T1", now=NOW)["ok"]
    assert not pc.request_close("breakout_2", "H1", fraction=1.5, now=NOW)["ok"]


def test_reduce_carries_its_fraction():
    _held()
    r = pc.request_close("breakout_2", "H1", fraction=0.5, now=NOW)
    assert r["action"] == "reduce" and _xc()["spec"]["fraction"] == 0.5


def test_close_is_served_only_to_an_app_that_declares_it_and_ends_on_done():
    _held()
    pc.request_close("breakout_2", "H1", now=NOW)
    assert pe.claim_next(_dev(), now=NOW, accepts=("cancel",)) is None
    assert pe.pending_count(_dev(), now=NOW, accepts=("close",)) == 1
    g = pe.claim_next(_dev(), now=NOW, accepts=("close",))
    assert g["kind"] == "close" and g["action"] == "close" and g["spec"]["venue_symbol"] == "ETHUSD"
    out = _rx({"ticket_id": "H1", "close_id": g["close_id"], "result": "done", "reason": "gone"})
    assert out["ok"] and _xc()["status"] == "done"
    assert pe.claim_next(_dev(), now=NOW + timedelta(hours=9), accepts=("close",)) is None


@pytest.mark.parametrize("res", ["failed", "ambiguous"])
def test_a_failed_close_backs_off_and_is_retried_never_dropped(res, _iso):
    _held()
    pc.request_close("breakout_2", "H1", now=NOW)
    t = NOW
    for i in range(4):
        pc.plan_closes("breakout_2", now=t)
        g = pe.claim_next(_dev(), now=t, accepts=("close",))
        assert g is not None, i
        _rx({"ticket_id": "H1", "close_id": g["close_id"], "result": res, "reason": "x"}, now=t)
        assert pc.plan_closes("breakout_2", now=t + timedelta(minutes=1)) == 0   # backing off
        t += timedelta(hours=7)
    assert sum("failed 3 times" in m for m in _iso) == 1                       # ONE flag
    assert pc.plan_closes("breakout_2", now=t) == 1                            # still trying


def test_not_found_ends_and_asks_to_check(_iso):
    _held()
    pc.request_close("breakout_2", "H1", now=NOW)
    g = pe.claim_next(_dev(), now=NOW, accepts=("close",))
    _rx({"ticket_id": "H1", "close_id": g["close_id"], "result": "not_found"})
    assert _xc()["status"] == "not_found" and any("NO matching position" in m for m in _iso)


def test_unreported_close_claim_is_rearmed():
    _held()
    pc.request_close("breakout_2", "H1", now=NOW)
    pe.claim_next(_dev(), now=NOW, accepts=("close",))
    pc.plan_closes("breakout_2", now=NOW + timedelta(seconds=200))
    assert _xc()["status"] == "failed" and _xc()["last_result"] == "unreported"


def test_live_review_close_reaches_the_phone_like_a_vm_account():
    from scripts.ops import live_review_apply as lra
    from src.runtime import live_review_intent as lri
    assert {"close", "reduce"} <= lra.ACTION_PATHS["phone"]
    _held()
    leg = {"row": prop_journal.get_ticket("H1")}
    intent = lri.LiveReviewIntent.__new__(lri.LiveReviewIntent)
    for k, v in {"action": "close", "mandate": "MD-TRADE-DESK", "review_id": "R1", "size_fraction": None}.items():
        object.__setattr__(intent, k, v) if hasattr(intent, "__dataclass_fields__") else setattr(intent, k, v)
    out = lra._exec_phone_close(leg, "close", intent)
    assert out["result"] == lra.X_APPLIED and _xc()["status"] == "emitted"
    out2 = lra._exec_phone_close(leg, "close", intent)
    assert out2["result"] == lra.X_REFUSED                                       # not duplicated
