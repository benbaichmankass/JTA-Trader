"""MD-EXEC-DEV-TEST-TRADES (operator grant 2026-10-18): the mandate is recorded under ``mandates:``, every bound refuses,
the ticket writer writes a minimum-size long with a protective stop, the claim re-checks the bounds, and test trades
are excluded from the performance / soak readers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.prop import exec_test_trades as et
from src.prop import phone_executor as pe
from src.prop import prop_journal

TOKEN = "t" * 43
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    plat = tmp_path / "platforms.yaml"
    plat.write_text(yaml.safe_dump({"phone_accounts": {"breakout_2": {"platform": "breakout_phone", "instruments": {
        "ETHUSDT": {"venue": "ETHUSD", "qty_step": 0.01, "price_step": 0.01},
        "SOLUSDT": {"venue": "SOLUSD", "qty_step": 0.1, "price_step": 0.01}}}}}))
    monkeypatch.setattr(pe, "PLATFORMS_PATH", plat)
    acc = tmp_path / "accounts.yaml"
    acc.write_text(yaml.safe_dump({"accounts": {"breakout_2": {"mode": "live"}, "bybit_2": {"mode": "live"}}}))
    monkeypatch.setattr(pe, "ACCOUNTS_PATH", acc)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    monkeypatch.setattr(pe, "_unserved_dry_test_request", lambda acct: None)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: 2500.0)
    # the day loss is readable and small unless a test says otherwise
    monkeypatch.setattr(et, "_day_loss", lambda acct, now: {"loss_usd": 10.0, "limit_usd": 120.0, "fraction": 10 / 120,
                                                            "tripped": False})
    return tmp_path


def _dev() -> pe.PhoneDevice:
    return pe.authenticate("Bearer " + TOKEN)


def test_the_grant_is_recorded_under_mandates_with_the_operators_words():
    m = et.mandate(REPO)
    assert m is not None and m["granted_by"].startswith("operator") and m["granted_at"] == "2026-10-18"
    assert "That is a standing mandate" in m["source"]
    b = et.bounds(m)
    assert b["accounts"] == ["breakout_2", "tradeify_1", "velotrade_1"] and b["max_per_account_per_day"] == 6
    assert b["max_hold_min"] == 30 and b["day_loss_fraction_max"] == 0.5
    # the entry's own field names are read (PR #18936), with this module's names as aliases
    assert et.bounds({"bounds": {"max_hold_minutes": 10, "max_test_trades_per_account_per_utc_day": 2,
                                 "max_day_loss_fraction_of_daily_dd_switch_limit": 0.25}}) == {
        **et.DEFAULT_BOUNDS, "max_hold_min": 10, "max_per_account_per_day": 2, "day_loss_fraction_max": 0.25}
    assert et.bounds({"bounds": {"max_hold_min": 5}})["max_hold_min"] == 5 and et.bounds(None) == et.DEFAULT_BOUNDS


def test_a_proposed_or_absent_entry_grants_nothing(tmp_path: Path):
    root = tmp_path / "r"
    (root / "config").mkdir(parents=True)
    (root / "config" / "mandates.yaml").write_text(yaml.safe_dump({"mandates": [], "proposed": [{"id": et.MANDATE_ID}]}))
    assert et.mandate(root) is None
    v = et.check_bounds("breakout_2", "ETHUSDT", now=NOW, root=root)
    assert v["ok"] is False and v["refusals"][0].startswith("mandate_not_granted")
    assert et.write_ticket("breakout_2", "ETHUSDT", by="t", now=NOW, root=root)["ok"] is False
    assert prop_journal.list_tickets(account_id="breakout_2") == []


def test_every_bound_refuses(monkeypatch):
    assert et.check_bounds("bybit_2", "ETHUSDT", now=NOW)["refusals"][0].startswith("account_not_in_mandate")
    assert any(r.startswith("not_a_phone_account") for r in et.check_bounds("tradeify_1", "ETHUSDT", now=NOW)["refusals"])
    assert et.check_bounds("breakout_2", "BTCUSDT", now=NOW)["refusals"][0].startswith("symbol_not_declared")
    ok = et.check_bounds("breakout_2", "ETHUSDT", now=NOW)
    assert ok["ok"] is True and ok["qty"] == 0.01 and ok["count_today"] == 0
    # day loss: unreadable refuses (a null is not 0); past the bound refuses; tripped refuses
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": None, "limit_usd": None, "fraction": None})
    assert et.check_bounds("breakout_2", "ETHUSDT", now=NOW)["refusals"] == [
        "day_loss_unreadable: the daily-DD switch has no readable loss/limit for today (a null is not 0; never a test trade blind)"]
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 70.0, "limit_usd": 120.0, "fraction": 70 / 120, "tripped": False})
    assert et.check_bounds("breakout_2", "ETHUSDT", now=NOW)["refusals"][0].startswith("day_loss_past_bound")
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 1.0, "limit_usd": 120.0, "fraction": 1 / 120, "tripped": True})
    assert "tripped" in et.check_bounds("breakout_2", "ETHUSDT", now=NOW)["refusals"][0]
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 1.0, "limit_usd": 120.0, "fraction": 1 / 120, "tripped": False})
    # a strategy ticket on the same symbol (pending or placed) refuses; another symbol is clear
    prop_journal.record_ticket({"ticket_id": "T1", "account_id": "breakout_2", "strategy": "trend_donchian_eth_prop",
                                "symbol": "ETHUSDT", "direction": "short", "entry": 2500.0, "sl": 2550.0, "tp": 2300.0,
                                "qty": 0.5, "signal_time": NOW.isoformat(), "valid_until": NOW.isoformat(), "status": "placed"})
    v = et.check_bounds("breakout_2", "ETHUSDT", now=NOW)
    assert v["refusals"] == ["strategy_position_on_symbol: ticket T1 (trend_donchian_eth_prop, placed)"]
    assert et.check_bounds("breakout_2", "SOLUSDT", now=NOW)["ok"] is True
    # an open strategy FILL on the symbol refuses too
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": "T9", "symbol": "SOLUSDT", "direction": "long",
                              "qty": 1.0, "entry_price": 100.0, "status": "open", "reported_at": NOW.isoformat()})
    assert et.check_bounds("breakout_2", "SOLUSDT", now=NOW)["refusals"][0].startswith("strategy_position_on_symbol: open fill")


def test_daily_cap_counts_only_tickets_that_reached_the_venue(monkeypatch):
    # The journal stamps created_at from the wall clock while this test pins NOW; count_today only has a lower
    # bound, so from the day after NOW the "+1 day" probe counted the wall-clock tickets (red 2026-10-19). Pin the
    # journal clock too, so the test says the same thing on every date.
    monkeypatch.setattr(prop_journal, "_now_iso", lambda: NOW.isoformat())
    for i in range(6):
        r = et.write_ticket("breakout_2", "ETHUSDT", by="test", now=NOW + timedelta(minutes=i))
        assert r["ok"] is True, r
        prop_journal.set_ticket_status(r["ticket_id"], "refused" if i < 2 else "closed")
    assert et.count_today("breakout_2", NOW) == 4
    assert et.write_ticket("breakout_2", "ETHUSDT", by="test", now=NOW)["ok"] is True   # 5th that reached the venue
    assert et.count_today("breakout_2", NOW) == 5
    prop_journal.set_ticket_status(prop_journal.list_tickets(account_id="breakout_2", status="emitted")[0]["ticket_id"], "closed")
    r = et.write_ticket("breakout_2", "ETHUSDT", by="test", now=NOW)
    assert r["ok"] is True and et.count_today("breakout_2", NOW) == 6
    r = et.write_ticket("breakout_2", "ETHUSDT", by="test", now=NOW)
    assert r["ok"] is False and r["refusals"] == ["daily_cap: 6 test tickets today already (cap 6)"]
    assert et.count_today("breakout_2", NOW + timedelta(days=1)) == 0, "a new UTC day starts at 0"


def test_write_ticket_shape_min_size_protective_stop_and_the_claim_serves_it_live():
    r = et.write_ticket("breakout_2", "ETHUSDT", by="drill d1", now=NOW)
    assert r["ok"] is True and r["ticket_id"].startswith(et.TICKET_PREFIX)
    t = prop_journal.get_ticket(r["ticket_id"])
    assert (t["strategy"], t["direction"], t["qty"], t["status"]) == ("exec_test", "long", 0.01, "emitted")
    assert t["entry"] == 2505.0 and t["sl"] == pytest.approx(2479.95) and t["tp"] == pytest.approx(2555.1)
    assert t["sl"] < t["entry"] < t["tp"], "a protective stop below a long entry, a target above"
    m = t["meta"] if isinstance(t["meta"], dict) else json.loads(t["meta"])
    assert m["origin"] == "exec_test" and m["exec_test"]["mandate"] == et.MANDATE_ID and m["exec_test"]["by"] == "drill d1"
    assert m["exec_test"]["close_by"] == (NOW + timedelta(minutes=30)).isoformat()
    assert et.is_exec_test(t) and et.is_exec_test({"ticket_id": r["ticket_id"]}) and not et.is_exec_test({"strategy": "x"})
    c = pe.claim_next(_dev(), now=NOW + timedelta(seconds=30))
    assert c is not None and c["ticket_id"] == r["ticket_id"] and c["submit"] == "live", "a live account: the test trade is real"
    assert c["venue_symbol"] == "ETHUSD" and c["meta"]["origin"] == "exec_test"


def test_the_claim_rechecks_every_bound_and_refuses_a_ticket_the_bounds_no_longer_allow(monkeypatch):
    r = et.write_ticket("breakout_2", "ETHUSDT", by="drill", now=NOW)
    assert r["ok"] is True
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 90.0, "limit_usd": 120.0, "fraction": 0.75, "tripped": False})
    assert pe.claim_next(_dev(), now=NOW + timedelta(seconds=30)) is None
    t = prop_journal.get_ticket(r["ticket_id"])
    m = t["meta"] if isinstance(t["meta"], dict) else json.loads(t["meta"])
    assert t["status"] == "refused" and m["exec_test"]["refused_at_claim"][0].startswith("day_loss_past_bound")
    assert et.count_today("breakout_2", NOW) == 0, "a ticket refused at claim never reached the venue"


def test_overdue_lists_a_placed_test_trade_past_close_by_without_a_closed_fill():
    r = et.write_ticket("breakout_2", "ETHUSDT", by="drill", now=NOW)
    prop_journal.set_ticket_status(r["ticket_id"], "placed")
    assert et.overdue("breakout_2", NOW + timedelta(minutes=29)) == []
    late = et.overdue("breakout_2", NOW + timedelta(minutes=31))
    assert [t["ticket_id"] for t in late] == [r["ticket_id"]]
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": r["ticket_id"], "symbol": "ETHUSDT", "direction": "long",
                              "qty": 0.01, "entry_price": 2505.0, "exit_price": 2506.0, "status": "closed",
                              "reported_at": NOW.isoformat(), "closed_at": NOW.isoformat()})
    assert et.overdue("breakout_2", NOW + timedelta(minutes=31)) == []


def test_exclusion_drops_test_trades_from_performance_soak_and_review_readers():
    rows = [{"ticket_id": "exec-test-abc", "strategy": "exec_test"}, {"ticket_id": "T1", "strategy": "trend_donchian_eth_prop"},
            {"ticket_id": "T2", "meta": json.dumps({"origin": "exec_test"})}]
    assert [r["ticket_id"] for r in et.exclude_exec_test(rows)] == ["T1"]
    fills = [{"id": 1, "ticket_id": "exec-test-abc"}, {"id": 2, "ticket_id": "T1"}, {"id": 3, "ticket_id": None, "raw": json.dumps({"origin": "exec_test"})},
             {"id": 4, "ticket_id": None, "raw": "not json"}]
    assert [f["id"] for f in et.exclude_exec_test(fills, fills=True)] == [2, 4]
    # the real readers carry the exclusion (field beats comment)
    for rel in ("src/runtime/trades_snapshot.py", "src/prop/prop_overview.py", "scripts/ops/soak_state.py",
                "scripts/prop/trade_quality_review.py"):
        assert "exclude_exec_test" in (REPO / rel).read_text(), rel
    # end to end through the trades snapshot: a closed test fill in the window is not counted
    r = et.write_ticket("breakout_2", "ETHUSDT", by="drill", now=NOW)
    for tid, px in ((r["ticket_id"], 2506.0), ("T1", 2400.0)):
        prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": tid, "symbol": "ETHUSDT", "direction": "long",
                                  "qty": 0.01, "entry_price": 2505.0, "exit_price": px, "pnl": 1.0, "status": "closed",
                                  "reported_at": NOW.isoformat(), "closed_at": NOW.isoformat()})
    from src.runtime import trades_snapshot as ts
    data = ts.collect(NOW - timedelta(hours=1), NOW + timedelta(hours=1)) if hasattr(ts, "collect") else None
    if data is not None and "prop_closed" in data:
        assert [f["ticket_id"] for f in data["prop_closed"]] == ["T1"]
