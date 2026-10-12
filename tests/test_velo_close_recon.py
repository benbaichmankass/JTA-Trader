"""VELO-CLOSE-RECON: velotrade_1 closes are reconciled from the venue's own
order history -- exit price, the reason BY ORDER IDENTITY (the ticket's own
``-S`` / ``-T`` bracket child filled), P&L computed from the fills -- and a close
whose exit could not be read is re-read every cycle, never written off, with
ONE red flag on a streak.

The history shape is the MEASURED one (system-action velotrade-trade-history-
read, issue #17505, 2026-10-11 05:57Z): orders[] with clientOrderId / type /
side / legs[].positionEffect and executions[] with lastPrice / lastQuantity /
transactionTime. Prices and sizes are ticket prop-manual-6fbebc711fa6's: BUY
3.44 ETHUSD at 2509.40 (2026-10-10 15:53:13Z), closed SELL 3.44 at 2499.37
(2026-10-11 03:52:42Z)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.prop import prop_executor as pe
from src.prop import prop_journal
from src.prop.platform.base import AccountSnapshot
from src.prop.platform.dxtrade_api import client_ids, trade_history_rows

UTC = timezone.utc
TID = "prop-manual-6fbebc711fa6"
IDS = client_ids(TID)
NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)


def _order(cid: str, typ: str, side: str, effect: str, px: Any, qty: Any, t: str, status="COMPLETED"):
    ex = [] if px is None else [{"lastPrice": px, "lastQuantity": qty, "transactionTime": t,
                                 "clientOrderId": cid, "status": status}]
    return {"clientOrderId": cid, "type": typ, "instrument": "ETHUSD", "side": side, "status": status,
            "finalStatus": True, "issueTime": t, "transactionTime": t,
            "legs": [{"positionEffect": effect, "instrument": "ETHUSD"}], "executions": ex}


ENTRY = _order(IDS["entry"], "LIMIT", "BUY", "OPEN", 2509.4, 3.44, "2026-10-10T15:53:13.540Z")
SL_FILL = _order(IDS["sl"], "STOP", "SELL", "CLOSE", 2499.37, 3.44, "2026-10-11T03:52:42.510Z")
TP_FILL = _order(IDS["tp"], "LIMIT", "SELL", "CLOSE", 2596.62, 3.44, "2026-10-11T03:52:42.510Z")
SL_CANCELED = _order(IDS["sl"], "STOP", "SELL", "CLOSE", None, None, "2026-10-11T03:52:42.600Z", "CANCELED")
TP_CANCELED = _order(IDS["tp"], "LIMIT", "SELL", "CLOSE", None, None, "2026-10-11T03:52:42.600Z", "CANCELED")
# An unrelated close (a Bulk Close of another ticket) in the same window.
OTHER = _order("other-ticket-S", "STOP", "SELL", "CLOSE", 2400.0, 3.44, "2026-10-11T03:50:00Z")

J = {"id": 7, "account_id": "velotrade_1", "symbol": "ETHUSDT", "direction": "long", "status": "filled",
     "ticket_id": TID, "qty": 3.44, "entry_price": 2509.4, "sl": 2495.08, "tp": 2596.62,
     "opened_at": "2026-10-10T15:53:13+00:00", "created_at": "2026-10-10T15:54:00+00:00"}


def _rows(*orders) -> List[Dict[str, Any]]:
    return trade_history_rows({"orders": list(orders)})


# ── the read: identity, reason, P&L ─────────────────────────────────────────


def test_rows_carry_our_client_id_and_order_type():
    rows = _rows(ENTRY, SL_FILL, SL_CANCELED)
    assert [(r["client_id"], r["order_type"], r["effect"]) for r in rows] == [
        (IDS["entry"], "limit", "opening"), (IDS["sl"], "stop", "closing")]


def test_closed_by_sl_is_named_by_identity_even_above_the_entry_stop():
    # 2499.37 is ABOVE the entry stop 2495.08: the price rule reads it "manual".
    # The ticket's own stop order filled, so it is the stop (a trailed one).
    assert pe.exit_reason("long", 2499.37, 2495.08, 2596.62) == "manual"
    hit, why = pe.venue_exit(J, _rows(OTHER, ENTRY, SL_FILL, TP_CANCELED), NOW, cvpp=1.0)
    assert why == "matched"
    assert hit["reason"] == "sl" and hit["exit_price"] == 2499.37
    assert hit["ts"] == datetime(2026, 10, 11, 3, 52, 42, 510000, tzinfo=UTC)
    assert hit["entry_fill"] == 2509.4
    assert hit["pnl"] == round((2499.37 - 2509.4) * 3.44, 2) == -34.5
    assert "identity" in hit["exit_source"] and "gross" in hit["pnl_basis"]


def test_closed_by_tp():
    hit, why = pe.venue_exit(J, _rows(ENTRY, TP_FILL, SL_CANCELED), NOW, cvpp=1.0)
    assert why == "matched" and hit["reason"] == "tp" and hit["exit_price"] == 2596.62
    assert hit["pnl"] == round((2596.62 - 2509.4) * 3.44, 2)


def test_short_pnl_sign_and_no_cvpp_means_no_pnl():
    js = {**J, "direction": "short"}
    buy_sl = _order(IDS["sl"], "STOP", "BUY", "CLOSE", 2520.0, 3.44, "2026-10-11T03:52:42Z")
    sell_entry = _order(IDS["entry"], "LIMIT", "SELL", "OPEN", 2509.4, 3.44, "2026-10-10T15:53:13Z")
    hit, _ = pe.venue_exit(js, _rows(sell_entry, buy_sl), NOW, cvpp=1.0)
    assert hit["reason"] == "sl" and hit["pnl"] == round((2509.4 - 2520.0) * 3.44, 2)
    hit, _ = pe.venue_exit(js, _rows(sell_entry, buy_sl), NOW, cvpp=None)
    assert hit["pnl"] is None and "not computable" in hit["pnl_basis"]


def test_partial_bracket_close_is_not_priced():
    half = _order(IDS["sl"], "STOP", "SELL", "CLOSE", 2499.37, 1.72, "2026-10-11T03:52:42Z")
    hit, why = pe.venue_exit(J, _rows(ENTRY, half), NOW, cvpp=1.0)
    assert hit is None and "partial" in why


def test_a_close_that_is_not_ours_falls_back_to_the_time_size_match():
    bulk = _order("x-Bulk", "MARKET", "SELL", "CLOSE", 2501.0, 3.44, "2026-10-11T03:52:42Z")
    hit, why = pe.venue_exit(J, _rows(ENTRY, bulk), NOW, cvpp=1.0)
    assert why == "matched" and hit["reason"] == "manual" and "inferred" in hit["exit_source"]


# ── the adapter: no period, non-200 raises ────────────────────────────────


class _T:
    def __init__(self, status, body):
        self.status, self.body, self.urls = status, body, []

    def __call__(self, method, url, data, headers, timeout):
        import json
        self.urls.append((method, url))
        return self.status, {}, json.dumps(self.body)


def _api_adapter(status, body):
    from src.prop.platform.dxtrade_api import DXtradeApiAdapter
    t = _T(status, body)
    a = DXtradeApiAdapter(transport=t, sleep=lambda s: None, base_url="https://dx.example/dxsca-web",
                          token="tok", account="default:ACCT1")
    return a, t


def test_read_trade_history_asks_for_no_period():
    # MEASURED #17505: period=today returned 0 orders two hours after a same-
    # UTC-day close; the unfiltered read returned it.
    a, t = _api_adapter(200, {"orders": [ENTRY, SL_FILL]})
    rows = a.read_trade_history(None)
    assert t.urls == [("GET", "https://dx.example/dxsca-web/accounts/default%3AACCT1/orders/history")]
    assert [r["client_id"] for r in rows] == [IDS["entry"], IDS["sl"]]


@pytest.mark.parametrize("status", [400, 401, 500, 0])
def test_non_200_history_raises(status):
    a, _ = _api_adapter(status, {"errorCode": "32", "description": "Incorrect request parameters"})
    with pytest.raises(RuntimeError):
        a.read_trade_history(None)


# ── the cycle: closed by SL / TP, unreadable, re-read, never written off ──


class Ad:
    platform = "dxtrade_api"

    def __init__(self, orders=None, status=200):
        self.orders, self.status, self.reads = list(orders or []), status, 0

    def read_account(self, page):
        return AccountSnapshot(balance=4955.98, equity=4955.98, unrealized=0.0, realized_today=None)

    def read_positions(self, page):
        return []

    def read_orders(self, page):
        return []

    def read_trade_history(self, page):
        self.reads += 1
        if self.status != 200:
            raise RuntimeError(f"trade history read failed {{'http': {self.status}}}")
        return _rows(*self.orders)


class Api:
    """The journal as the executor sees it over /api/bot/prop/*: a priced
    close of a ticket replaces its unpriced row (``insert_fill``)."""

    def __init__(self, fills):
        self.fills, self.posts = [dict(f) for f in fills], []

    def tickets(self, account_id):
        return []

    def open_fills(self, account_id):
        return pe.open_from_fills(self.fills)

    def unpriced_closes(self, account_id):
        return pe.unpriced_closes_from_fills(self.fills, account_id)

    def post_report(self, body):
        self.posts.append(body)
        if body.get("kind") == "fill" and body.get("status") == "closed":
            row = {**body, "id": len(self.fills) + 100, "symbol": "ETHUSDT",
                   "created_at": "2026-10-11T03:55:00+00:00", "updated_at": f"2026-10-11T04:{len(self.posts):02d}"}
            for i, f in enumerate(self.fills):
                if (f.get("ticket_id") == body["ticket_id"] and f.get("status") == "closed"
                        and f.get("exit_price") is None and body.get("exit_price") is not None):
                    self.fills[i] = {**f, **row, "id": f["id"]}
                    break
            else:
                self.fills.append(row)
        return {"ok": True}


def _setup(tmp_path):
    ledger = pe.IntentLedger(tmp_path / "ledger.jsonl")
    state = pe.ExecutorState(tmp_path)
    state.save({"day": pe.trading_day(NOW), "day_start_captured": 4999.97})
    cfg = pe.ExecutorConfig(account_id="velotrade_1", account_size_usd=5000.0, daily_loss_pct=0.04,
                            max_dd_pct=0.07, safety_margin_usd=5.0, risk_cap_usd=75.0, unconfirmed_reads=3,
                            symbols={"ETHUSDT": {"venue": "ETHUSD", "cvpp": 1.0, "lot_units": 1.0,
                                                 "min_lots": 0.01, "lot_step": 0.01}})
    return ledger, state, cfg


def _run(tmp_path, ad, api, n, setup=None):
    ledger, state, cfg = setup or _setup(tmp_path)
    out = []
    for _ in range(n):
        out.append(pe.run_cycle(adapter=ad, page=None, api=api, cfg=cfg, mode="live", ledger=ledger,
                                state=state, now=NOW))
    return out


def _closed(api):
    return [p for p in api.posts if p.get("status") == "closed"]


@pytest.mark.parametrize("fill,reason,px", [(SL_FILL, "sl", 2499.37), (TP_FILL, "tp", 2596.62)])
def test_cycle_reports_the_close_from_venue_fills(tmp_path, fill, reason, px):
    api = Api([J])
    _run(tmp_path, Ad([ENTRY, fill]), api, 3)
    closed = _closed(api)
    assert len(closed) == 1                                   # once: priced, nothing left to re-read
    c = closed[0]
    assert (c["reason"], c["exit_price"], c["ticket_id"]) == (reason, px, TID)
    assert c["pnl"] == round((px - 2509.4) * 3.44, 2) and c["closed_at"] == "2026-10-11T03:52:42.510000+00:00"


def test_unreadable_history_keeps_watching_one_red_flag_then_reprices(tmp_path):
    api = Api([J])
    ad = Ad([ENTRY, SL_FILL], status=500)
    setup = _setup(tmp_path)
    res = _run(tmp_path, ad, api, 6, setup)
    closed = _closed(api)
    # The position is gone from the terminal: the close is journaled (nothing
    # holds), unpriced and visibly so -- never with an invented price.
    assert len(closed) == 1 and closed[0]["reason"] == pe.CLOSE_UNREAD_REASON
    assert "exit_price" not in closed[0]
    # ...and re-read on every later cycle, never written off.
    assert ad.reads >= 4
    alerts = [a for r in res for a in r.alerts]
    assert sum("RED FLAG" in a and "exit still unread" in a for a in alerts) == 1
    assert sum(a.startswith("FAILED:") and "exit still unread" in a for a in alerts) == 1
    assert all(not r.halted or "exit" not in str(r.halted) for r in res)
    # The venue answers again: the close is re-reported priced and the journal
    # row is corrected in place (one closed row, not two).
    ad.status = 200
    res2 = _run(tmp_path, ad, api, 2, setup)
    priced = [p for p in _closed(api) if p.get("exit_price") is not None]
    assert len(priced) == 1 and priced[0]["reason"] == "sl" and priced[0]["pnl"] == -34.5
    assert priced[0]["repriced"]
    rows = [f for f in api.fills if f.get("status") == "closed"]
    assert len(rows) == 1 and rows[0]["exit_price"] == 2499.37
    assert any("RECOVERED" in a and "exit still unread" in a for r in res2 for a in r.alerts)


def test_a_close_written_off_before_the_fix_is_repriced_from_the_journal(tmp_path):
    # The live row: closed by the old path with the "not built" reason and no
    # exit. Nothing in executor state names it; the journal does.
    old = {"id": 8, "account_id": "velotrade_1", "symbol": "ETHUSDT", "direction": "long", "status": "closed",
           "ticket_id": TID, "qty": 3.44, "entry_price": 2509.4, "reason": pe.CLOSE_UNREAD_REASON,
           "exit_price": None, "pnl": None, "created_at": "2026-10-11T03:58:00+00:00"}
    api = Api([J, old])
    _run(tmp_path, Ad([ENTRY, SL_FILL]), api, 2)
    priced = _closed(api)
    assert len(priced) == 1 and (priced[0]["reason"], priced[0]["exit_price"], priced[0]["pnl"]) == ("sl", 2499.37, -34.5)
    assert priced[0]["opened_at"] == J["opened_at"]


def test_unpriced_list_is_scoped_to_this_executors_unread_closes():
    rows = [
        J,
        {"account_id": "velotrade_1", "status": "closed", "ticket_id": "a", "reason": pe.CLOSE_UNREAD_REASON},
        {"account_id": "velotrade_1", "status": "closed", "ticket_id": "b", "reason": "sl", "exit_price": 1.0},
        {"account_id": "velotrade_1", "status": "closed", "ticket_id": "c", "reason": "operator paste"},
        {"account_id": "breakout_1", "status": "closed", "ticket_id": "d", "reason": pe.CLOSE_UNREAD_REASON},
        {"account_id": "velotrade_1", "status": "closed", "ticket_id": None, "reason": pe.CLOSE_UNREAD_REASON},
    ]
    assert [r["ticket_id"] for r in pe.unpriced_closes_from_fills(rows, "velotrade_1")] == ["a"]


# ── the journal: a priced close corrects the unpriced row ────────────────


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db))
    return db


def test_priced_close_updates_the_unpriced_row_in_place(isolated_db):
    base = {"account_id": "velotrade_1", "ticket_id": TID, "symbol": "ETHUSDT", "direction": "long",
            "qty": 3.44, "entry_price": 2509.4, "status": "closed"}
    rid = prop_journal.insert_fill({**base, "reason": pe.CLOSE_UNREAD_REASON})
    rid2 = prop_journal.insert_fill({**base, "exit_price": 2499.37, "pnl": -34.5, "reason": "sl",
                                     "closed_at": "2026-10-11T03:52:42.510000+00:00"})
    rows = [r for r in prop_journal.list_fills(account_id="velotrade_1", limit=10) if r["status"] == "closed"]
    assert rid2 == rid and len(rows) == 1
    assert (rows[0]["exit_price"], rows[0]["pnl"], rows[0]["reason"]) == (2499.37, -34.5, "sl")
    # A second, different priced close of the same ticket is NOT folded in
    # (only an UNPRICED row is a correction target).
    prop_journal.insert_fill({**base, "exit_price": 2501.0, "pnl": -28.9, "reason": "manual"})
    assert len([r for r in prop_journal.list_fills(account_id="velotrade_1", limit=10)
                if r["status"] == "closed"]) == 2


def test_the_live_rows_are_repriced(tmp_path):
    # Verbatim shape of /api/bot/prop/fills?account_id=velotrade_1 (issue
    # #17512, 2026-10-11 06:05Z): fill 96 open (opened_at null, SL trailed to
    # 2499.69 by two amends), fill 97 the 03:58Z close written off unpriced.
    f96 = {"id": 96, "account_id": "velotrade_1", "ticket_id": TID, "symbol": "ETHUSDT", "direction": "long",
           "qty": 3.44, "entry_price": 2509.4, "exit_price": None, "pnl": None, "status": "open", "reason": None,
           "opened_at": None, "closed_at": None, "created_at": "2026-10-10T15:53:18.171137+00:00",
           "sl": 2499.69, "tp": 2596.62}
    f97 = {"id": 97, "account_id": "velotrade_1", "ticket_id": TID, "symbol": "ETHUSDT", "direction": "long",
           "qty": 3.44, "entry_price": 2509.4, "exit_price": None, "pnl": None, "status": "closed",
           "reason": pe.CLOSE_UNREAD_REASON, "opened_at": None, "closed_at": None,
           "created_at": "2026-10-11T03:58:08.857859+00:00", "sl": None, "tp": None}
    [j] = pe.unpriced_closes_from_fills([f97, f96], "velotrade_1")
    assert j["opened_at"] == f96["created_at"] and j["sl"] == 2499.69
    api = Api([f96, f97])
    _run(tmp_path, Ad([ENTRY, SL_FILL, TP_CANCELED]), api, 1)
    [c] = _closed(api)
    assert (c["reason"], c["exit_price"], c["pnl"], c["closed_at"]) == (
        "sl", 2499.37, -34.5, "2026-10-11T03:52:42.510000+00:00")
    assert [f["exit_price"] for f in api.fills if f["status"] == "closed"] == [2499.37]
