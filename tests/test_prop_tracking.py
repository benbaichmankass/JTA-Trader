"""PROP-TRACKING (operator 2026-10-12, verbatim: "we need to be able to track the prop trades - no upnl isn't a
solution to the issue"): the phone executor's Positions / Closed orders reads are stored, the account uPnL is the
venue's own per-position figures (MEASURED), the journal is reconciled against the venue list (close with the
reported exit / closed_unpriced; unconfirmed open + one alert), and a labelled mark ESTIMATE fills the gap until the
new APK reports. Real journal DB in tmp; no network (mark feed and Telegram stubbed)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.prop import phone_executor as pe
from src.prop import phone_reconcile as rc
from src.prop import prop_journal
from src.prop import prop_overview as po

TOKEN = "t" * 43
ACCTS = {"breakout_2": {"account_class": "prop", "mode": "live"}}


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: None)
    sent: list = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: sent.append(m) or True)
    monkeypatch.setattr("src.prop.breakout_notify.emit_prop_fill", lambda f, **k: {"push": False, "telegram": False})
    monkeypatch.setattr("src.runtime.local_pnl.last_mark_price", lambda *a, **k: None)
    return sent


def _dev():
    return pe.authenticate("Bearer " + TOKEN)


def _open(tid: str, symbol="ETHUSDT", direction="long", qty=1.1758, entry=2527.8, sl=2506.54, tp=2655.38,
          minutes_ago=60, status="open"):
    from src.prop.prop_report import ingest_report
    return ingest_report({"kind": "fill", "status": status, "account_id": "breakout_2", "ticket_id": tid,
                          "symbol": symbol, "direction": direction, "qty": qty, "entry_price": entry, "sl": sl,
                          "tp": tp, "opened_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()})["id"]


def _status(positions, state="read", closed=None, **over):
    body = {"kind": "account_status", "equity": 5032.26, "balance": None, "equity_label": "portfolio",
            "positions_state": state}
    if positions is not None:
        body["positions"] = positions
    if closed is not None:
        body["closed_orders"] = closed
    body.update(over)
    return pe.record_report(_dev(), body)


ETH = {"symbol": "ETH", "side": "long", "qty": 1.1758, "entry": 2527.8, "mark": 2554.4, "upnl": 31.27}
SOL = {"symbol": "SOL", "side": "long", "qty": 17.26, "entry": 111.16, "mark": 112.3, "upnl": 19.67}


def _open_ids():
    fills = prop_journal.list_fills(account_id="breakout_2", limit=500)
    return sorted(f["id"] for f in po.split_fills(fills)[0])


# ---- ingest: storage + account uPnL ----

def test_clean_positions_read_is_stored_and_account_upnl_is_the_venue_sum():
    r = _status([ETH, SOL])
    row = prop_journal.latest_account_status("breakout_2")
    raw = json.loads(row["raw"])
    assert row["unrealized"] == 50.94 and raw["unrealized_source"] == "positions_sum"
    assert raw["provenance"] == "MEASURED" and raw["positions_state"] == "read"
    assert [(p["symbol"], p["direction"], p["upnl"]) for p in raw["positions"]] == [("ETHUSDT", "long", 31.27),
                                                                                   ("SOLUSDT", "long", 19.67)]
    assert r["reconcile"]["unconfirmed"] == ["ETHUSDT long", "SOLUSDT long"]   # no journal rows yet


def test_flat_read_is_measured_zero_and_partial_upnl_is_absent_not_summed():
    _status([])
    assert prop_journal.latest_account_status("breakout_2")["unrealized"] == 0.0
    _status([ETH, {**SOL, "upnl": None}])
    assert prop_journal.latest_account_status("breakout_2")["unrealized"] is None


def test_terminal_panel_unrealized_wins_and_equity_minus_balance_only_for_a_true_equity_label():
    _status([ETH], unrealized=40.0)
    raw = json.loads(prop_journal.latest_account_status("breakout_2")["raw"])
    assert raw["unrealized"] == 40.0 and raw["unrealized_source"] == "terminal_panel"
    _status(None, state="no_table", balance=5000.0, equity=5050.0, equity_label="equity")
    assert prop_journal.latest_account_status("breakout_2")["unrealized"] == 50.0
    _status(None, state="no_table", balance=5000.0, equity=5050.0, equity_label="portfolio")
    assert prop_journal.latest_account_status("breakout_2")["unrealized"] is None   # Portfolio != equity (unverified)


def test_unclean_read_stores_only_its_state_and_reconciles_nothing(env):
    jid = _open("prop-manual-x", minutes_ago=600)
    for st in ("no_table", "unparsed", "empty_unconfirmed", "count_mismatch"):
        r = _status([], state=st)
        raw = json.loads(prop_journal.latest_account_status("breakout_2")["raw"])
        assert raw["positions_state"] == st and "positions" not in raw and "reconcile" not in r
    assert _open_ids() == [jid] and env == []


@pytest.mark.parametrize("bad", [[{"symbol": "ETH", "qty": 1.0}], [{"symbol": "ETH", "side": "long", "qty": 0}],
                                 [{"symbol": "ETH", "side": "long", "qty": "1"}], "x", [1]])
def test_structurally_bad_positions_refuse_the_report(bad):
    with pytest.raises(ValueError):
        _status(bad)


def test_positions_miss_event_is_quiet_scrubbed_and_kept(env):
    pe.record_event(_dev(), {"event": "positions_miss", "reason": "no_table",
                             "headers": ["Symbol", "Size ####"], "controls": ["Positions", "https://x.y/z"]})
    d = pe.last_positions_diag("breakout_2")
    assert d["state"] == "no_table" and d["headers"] == ["Symbol", "Size"] and "https" not in json.dumps(d)
    assert env == []


# ---- reconcile ----

def test_matching_positions_change_nothing():
    a, b = _open("prop-manual-f79"), _open("prop-manual-903", symbol="SOLUSDT", qty=17.26, entry=111.16)
    r = _status([ETH, SOL])
    assert r["reconcile"]["matched"] == 2 and _open_ids() == sorted([a, b])


def test_absent_row_closes_only_after_two_reads_a_minute_apart_with_the_venue_exit(monkeypatch, env):
    jid = _open("prop-manual-f79")
    t0 = datetime.now(timezone.utc)
    tp_fill = {"symbol": "ETH", "side": "short", "qty": 1.1758, "price": 2655.4, "pnl": 150.03,
               "type": "Take profit", "status": "Filled", "time": "2026-10-12 12:01:05"}
    entry_fill = {"symbol": "ETH", "side": "long", "qty": 1.1758, "price": 2527.8, "status": "Filled"}
    monkeypatch.setattr(rc, "_now", lambda: t0)
    r1 = _status([], closed=[tp_fill, entry_fill])
    assert r1["reconcile"]["pending_close"] == [str(jid)] and _open_ids() == [jid]
    monkeypatch.setattr(rc, "_now", lambda: t0 + timedelta(seconds=30))
    _status([], closed=[tp_fill, entry_fill])
    assert _open_ids() == [jid]                        # two reads but < 60 s apart: still open
    monkeypatch.setattr(rc, "_now", lambda: t0 + timedelta(seconds=90))
    r3 = _status([], closed=[tp_fill, entry_fill])
    assert r3["reconcile"]["closed"] == [{"id": str(jid), "exit": 2655.4, "reason": "tp"}]
    assert _open_ids() == []
    close = [f for f in prop_journal.list_fills(account_id="breakout_2") if f["status"] == "closed"][0]
    assert (close["exit_price"], close["pnl"], close["ticket_id"]) == (2655.4, 150.03, "prop-manual-f79")
    assert json.loads(close["raw"])["provenance"] == rc.MEASURED
    assert env == []                                   # a priced close is the normal prop_closed notification


def test_a_present_read_resets_the_absence_count(monkeypatch):
    jid = _open("prop-manual-f79")
    t0 = datetime.now(timezone.utc)
    for i, pos in enumerate(([], [ETH], [])):
        monkeypatch.setattr(rc, "_now", lambda i=i: t0 + timedelta(seconds=90 * i))
        _status(pos)
    assert _open_ids() == [jid]


def test_absent_row_without_a_unique_exit_is_closed_unpriced_and_pinged(monkeypatch, env):
    jid = _open("prop-manual-f79")
    t0 = datetime.now(timezone.utc)
    for i in range(2):
        monkeypatch.setattr(rc, "_now", lambda i=i: t0 + timedelta(seconds=90 * i))
        r = _status([], closed=[])
    assert r["reconcile"]["closed_unpriced"] == [str(jid)] and _open_ids() == []
    close = [f for f in prop_journal.list_fills(account_id="breakout_2") if f["status"] == "closed"][0]
    assert close["exit_price"] is None and close["pnl"] is None and close["reason"] == "closed_unpriced"
    assert json.loads(close["raw"])["provenance"] == rc.UNVERIFIED
    assert len(env) == 1 and "without an exit price" in env[0]


def test_a_freshly_journaled_row_is_never_closed():
    jid = _open("prop-manual-new", minutes_ago=0)
    t0 = datetime.now(timezone.utc)
    rc.reconcile("breakout_2", [], [], now=t0)
    rc.reconcile("breakout_2", [], [], now=t0 + timedelta(seconds=61))
    assert _open_ids() == [jid]


def test_venue_position_without_a_journal_row_is_journaled_unconfirmed_once(env):
    _status([SOL])
    _status([SOL])
    rows = [f for f in prop_journal.list_fills(account_id="breakout_2") if f["status"] == "open"]
    assert len(rows) == 1
    assert rows[0]["ticket_id"] == "venue-breakout_2-SOLUSDT-long-111.16" and rows[0]["reason"].startswith("unconfirmed")
    assert (rows[0]["qty"], rows[0]["entry_price"]) == (17.26, 111.16)
    assert len(env) == 1 and "UNCONFIRMED" in env[0]


def test_a_placed_working_order_on_the_venue_list_becomes_open_on_its_ticket(env):
    _open("prop-manual-lim", status="placed")
    r = _status([ETH])
    assert r["reconcile"]["opened"] == ["ETHUSDT long"] and r["reconcile"]["unconfirmed"] == []
    rows = [f for f in prop_journal.list_fills(account_id="breakout_2") if f["status"] == "open"]
    assert [(f["ticket_id"], f["sl"], f["tp"]) for f in rows] == [("prop-manual-lim", 2506.54, 2655.38)]
    assert env == []


def test_an_undeclared_instrument_is_flagged_once_and_never_journaled(env):
    _status([{"symbol": "DOGE", "side": "long", "qty": 10.0, "entry": 0.1}])
    _status([{"symbol": "DOGE", "side": "long", "qty": 10.0, "entry": 0.1}])
    assert prop_journal.list_fills(account_id="breakout_2") == []
    assert len(env) == 1 and "DOGE" in env[0]


# ---- overview ----

def _overview():
    return po.build_overview("7d", accounts=ACCTS)


def test_overview_per_trade_upnl_is_the_venue_position_measured():
    _open("prop-manual-f79")
    _open("prop-manual-903", symbol="SOLUSDT", qty=17.26, entry=111.16)
    _status([ETH, SOL])
    o = _overview()
    by = {t["symbol"]: t for t in o["open_trades"]}
    assert (by["ETHUSDT"]["unrealized_pnl"], by["ETHUSDT"]["unrealized_provenance"],
            by["ETHUSDT"]["unrealized_state"]) == (31.27, "measured", "venue_position")
    assert by["SOLUSDT"]["unrealized_pnl"] == 19.67
    acct = o["equity"]["accounts"][0]
    assert (acct["unrealized"], acct["unrealized_state"], acct["venue_open_positions"]) == (50.94, "venue_snapshot", 2)
    assert o["unrealized_pnl"] == 50.94


def test_overview_mark_estimate_is_labelled_and_kept_out_of_the_measured_total(monkeypatch):
    _open("prop-manual-f79")
    _open("prop-manual-903", symbol="SOLUSDT", qty=17.26, entry=111.16)
    _status(None, state="not_read")                    # today's APK: equity only
    marks = {"ETHUSDT": 2554.4, "SOLUSDT": 110.0}
    monkeypatch.setattr("src.runtime.local_pnl.last_mark_price", lambda s, **k: marks[s])
    o = _overview()
    by = {t["symbol"]: t for t in o["open_trades"]}
    assert (by["ETHUSDT"]["unrealized_pnl"], by["ETHUSDT"]["unrealized_provenance"],
            by["ETHUSDT"]["unrealized_state"]) == (round((2554.4 - 2527.8) * 1.1758, 2), "estimated", "mark_estimate")
    assert by["SOLUSDT"]["unrealized_pnl"] == round((110.0 - 111.16) * 17.26, 2)   # a loss stays negative
    acct = o["equity"]["accounts"][0]
    est = round(by["ETHUSDT"]["unrealized_pnl"] + by["SOLUSDT"]["unrealized_pnl"], 2)
    assert (acct["unrealized"], acct["unrealized_state"], acct["unrealized_provenance"]) == (est, "mark_estimate", "estimated")
    assert o["unrealized_pnl"] is None                 # an estimate never enters the measured total
    assert o["unrealized_pnl_incl_estimates"] == est and o["unrealized"]["accounts_estimated"] == 1


def test_short_mark_estimate_sign_and_no_mark_is_not_reported(monkeypatch):
    _open("prop-manual-s", direction="short", qty=2.0, entry=100.0)
    _status(None, state="not_read")
    monkeypatch.setattr("src.runtime.local_pnl.last_mark_price", lambda s, **k: 90.0)
    assert _overview()["open_trades"][0]["unrealized_pnl"] == 20.0
    monkeypatch.setattr("src.runtime.local_pnl.last_mark_price", lambda s, **k: None)
    o = _overview()
    assert (o["open_trades"][0]["unrealized_pnl"], o["open_trades"][0]["unrealized_state"]) == (None, "not_reported")
    assert o["equity"]["accounts"][0]["unrealized_state"] == "not_reported"
