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
    monkeypatch.setattr(pc, "_bars_fn", lambda sym, since, now: [])   # no network: price path reads "unread"
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


def test_not_found_without_evidence_keeps_the_ticket_placed_and_asks_to_check(_iso):
    """PHONE-CANCEL-FILLED-AS-SKIPPED: not_found means the order is gone, not that it never filled. With no clean
    Positions read and no readable price path the ticket stays placed (in the risk book) and is re-checked."""
    g = _claim()
    out = pe.record_report(_dev(), {"kind": "cancel_result", "ticket_id": "C1", "cancel_id": g["cancel_id"], "result": "not_found"})
    assert out["verdict"] == "unverified"
    assert prop_journal.get_ticket("C1")["status"] == "placed"
    assert _c()["status"] == "not_found" and _c()["verify"] == "pending"
    assert sum("cannot yet tell whether it FILLED" in m for m in _iso) == 1
    assert pe.claim_next(_dev(), now=NOW + timedelta(hours=1), accepts=("cancel",)) is None   # never re-cancelled


# ---- c54b reproduction: breakout_2 ETH long prop-manual-c54b2229aa1c, 2026-11-11 (numbers from the incident record)
C54 = "prop-manual-c54b2229aa1c"
C54_PLACED = datetime(2026, 11, 11, 20, 4, 53, tzinfo=timezone.utc)
C54_VU = datetime(2026, 11, 11, 21, 3, tzinfo=timezone.utc)
C54_CANCEL = datetime(2026, 11, 11, 21, 6, tzinfo=timezone.utc)
C54_LIMIT, C54_SL, C54_TP = 2077.57, 2043.70, 2128.37


def _c54_bars(sym, since, now):
    """5m ETH bars: 20:00 bar above the limit; the 20:05 bar trades 2076.84 (through 2077.57); later bars hold above
    the stop until the 23:10 bar (L 2035.83 < SL 2043.70); TP never reached."""
    out, t = [], datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
    while t <= now:
        if t == datetime(2026, 11, 11, 20, 5, tzinfo=timezone.utc):
            hi, lo = 2081.0, 2076.84
        elif t == datetime(2026, 11, 11, 23, 10, tzinfo=timezone.utc):
            hi, lo = 2050.0, 2035.83
        elif t < datetime(2026, 11, 11, 20, 5, tzinfo=timezone.utc):
            hi, lo = 2084.0, 2079.0
        else:
            hi, lo = 2090.0, 2060.0
        if t >= since:
            out.append((t, hi, lo))
        t += timedelta(minutes=5)
    return out


def _c54_setup():
    prop_journal.record_ticket({
        "ticket_id": C54, "account_id": "breakout_2", "strategy": "breakout_2", "symbol": "ETHUSDT",
        "direction": "long", "entry": C54_LIMIT, "sl": C54_SL, "tp": C54_TP, "qty": 0.51,
        "signal_time": (C54_PLACED - timedelta(minutes=5)).isoformat(), "valid_until": C54_VU.isoformat(),
        "status": "placed", "meta": None})
    from src.prop.prop_report import ingest_report
    # the phone's confirmed placed fill (fill 244; "entry" key, priced since #25089)
    ingest_report({"kind": "fill", "status": "placed", "account_id": "breakout_2", "ticket_id": C54, "symbol": "ETHUSDT",
                   "direction": "long", "qty": 0.51, "entry": C54_LIMIT, "sl": C54_SL, "tp": C54_TP,
                   "placed_at": C54_PLACED.isoformat(), "source": "phone_executor"})
    assert prop_journal.get_ticket(C54)["status"] == "placed"
    pc.plan_cancels("breakout_2", now=C54_CANCEL)
    g = pe.claim_next(_dev(), now=C54_CANCEL, accepts=("cancel",))
    assert g is not None and g["ticket_id"] == C54
    return g


def test_c54b_filled_limit_is_not_skipped_and_its_stop_out_is_recorded(_iso, monkeypatch):
    """The incident: positions reads were all no_table, the cancel found no open order. The price traded through the
    limit after placement, so the ticket is FILLED (ESTIMATED), stays in the risk book, and fill_inference records the
    23:10Z stop-out from the candles."""
    from src.prop import fill_inference as fi
    from src.prop.prop_overview import split_fills
    monkeypatch.setattr(pc, "_bars_fn", _c54_bars)
    g = _c54_setup()
    out = pc.record_cancel_result(_dev(), {"kind": "cancel_result", "ticket_id": C54, "cancel_id": g["cancel_id"],
                                           "result": "not_found"}, now=C54_CANCEL + timedelta(seconds=30))
    assert out["verdict"] == "filled_estimated"
    assert prop_journal.get_ticket(C54)["status"] == "filled"            # NOT skipped: still in the risk book
    open_rows, _ = split_fills(prop_journal.list_fills(account_id="breakout_2"))
    row = next(f for f in open_rows if f.get("ticket_id") == C54)
    assert row["entry_price"] == C54_LIMIT and fi.is_inferred(row)
    assert any("journaled as FILLED" in m for m in _iso)
    # the later close is recorded (the existing fill_inference pass, now that the ticket carries an open row)
    res = fi.infer("breakout_2", now=datetime(2026, 11, 12, 2, 30, tzinfo=timezone.utc), bars_fn=_c54_bars)
    assert C54 in res["closed"]
    _, closed_rows = split_fills(prop_journal.list_fills(account_id="breakout_2"))
    close = next(f for f in closed_rows if f.get("ticket_id") == C54)
    assert close["exit_price"] == C54_SL and close["closed_at"].startswith("2026-11-11T23:10")
    assert prop_journal.get_ticket(C54)["status"] == "closed"


def _snap(at, positions):
    """A clean phone Positions read stored at ``at`` (insert_account_status stamps the wall clock, so write directly)."""
    import json
    conn = prop_journal._connect()
    prop_journal.ensure_tables(conn)
    raw = {"kind": "account_status", "account_id": "breakout_2", "positions_state": "read", "positions": positions,
           "closed_orders": [], "source": "phone_executor"}
    conn.execute("INSERT INTO prop_account_status (account_id, balance, equity, reported_at, raw, created_at) "
                 "VALUES (?,?,?,?,?,?)", ("breakout_2", 50000.0, 50000.0, at.isoformat(), json.dumps(raw), at.isoformat()))
    conn.commit()
    conn.close()


def test_not_found_with_the_position_on_the_venue_journals_it_open_measured(_iso):
    g = _c54_setup()
    _snap(C54_CANCEL + timedelta(minutes=2),
          [{"symbol": "ETHUSDT", "venue_symbol": "ETHUSD", "direction": "long", "qty": 0.5, "entry": 2077.1}])
    out = pc.record_cancel_result(_dev(), {"kind": "cancel_result", "ticket_id": C54, "cancel_id": g["cancel_id"],
                                           "result": "not_found"}, now=C54_CANCEL + timedelta(minutes=3))
    assert out["verdict"] == "filled_venue"
    assert prop_journal.get_ticket(C54)["status"] == "filled"
    from src.prop.prop_overview import split_fills
    open_rows, _ = split_fills(prop_journal.list_fills(account_id="breakout_2"))
    row = next(f for f in open_rows if f.get("ticket_id") == C54)
    assert row["entry_price"] == 2077.1 and row["qty"] == 0.5


def test_not_found_when_price_never_reached_the_limit_is_skipped(_iso, monkeypatch):
    monkeypatch.setattr(pc, "_bars_fn", lambda sym, since, now: [
        (since + timedelta(minutes=5 * i), 2090.0, 2080.0) for i in range(int((now - since).total_seconds() // 300) + 1)])
    g = _c54_setup()
    out = pc.record_cancel_result(_dev(), {"kind": "cancel_result", "ticket_id": C54, "cancel_id": g["cancel_id"],
                                           "result": "not_found"}, now=C54_CANCEL + timedelta(seconds=30))
    assert out["verdict"] == "never_filled"
    assert prop_journal.get_ticket(C54)["status"] == "skipped"
    assert any("it never filled" in m for m in _iso)


def test_flat_read_after_the_cancel_with_price_through_stays_placed(_iso, monkeypatch):
    """Filled-and-closed, or the feed disagrees with the venue: never guessed, never skipped."""
    monkeypatch.setattr(pc, "_bars_fn", _c54_bars)
    g = _c54_setup()
    _snap(C54_CANCEL + timedelta(minutes=2), [])
    out = pc.record_cancel_result(_dev(), {"kind": "cancel_result", "ticket_id": C54, "cancel_id": g["cancel_id"],
                                           "result": "not_found"}, now=C54_CANCEL + timedelta(minutes=3))
    assert out["verdict"] == "unverified" and prop_journal.get_ticket(C54)["status"] == "placed"


def test_unverified_not_found_is_rechecked_and_resolves_when_evidence_arrives(_iso):
    g = _c54_setup()
    t = C54_CANCEL + timedelta(seconds=30)
    out = pc.record_cancel_result(_dev(), {"kind": "cancel_result", "ticket_id": C54, "cancel_id": g["cancel_id"],
                                           "result": "not_found"}, now=t)
    assert out["verdict"] == "unverified" and prop_journal.get_ticket(C54)["status"] == "placed"
    pc.plan_cancels("breakout_2", now=t + timedelta(minutes=1))          # throttled: nothing new
    assert _c(C54)["checks"] == 1
    _snap(t + timedelta(minutes=5),
          [{"symbol": "ETHUSDT", "venue_symbol": "ETHUSD", "direction": "long", "qty": 0.51, "entry": 2077.57}])
    pc.plan_cancels("breakout_2", now=t + timedelta(minutes=11))
    assert prop_journal.get_ticket(C54)["status"] == "filled" and _c(C54)["verify"] == "done"
    assert _c(C54)["position_check"]["verdict"] == "filled_venue"
    assert sum("cannot yet tell" in m for m in _iso) == 1                 # ONE alert, not one per re-check


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
