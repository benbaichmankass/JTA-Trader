"""ALPACA-LIVE-MECHANICS (2026-11-06): the journal books Alpaca's FILL, not the package price.

MEASURED (broker order history vs journal, /api/diag/alpaca_order_history): 9 of 10
alpaca_paper brackets filled 2026-11-02..11-05 journaled an entry_price that was not
the venue's filled_avg_price, and the one real-money alpaca_live fill (IAUM, 2026-09-23)
journaled 43.48 against a 42.9086 fill. Alpaca P&L is local-compute from entry_price, so
every Alpaca P&L and R grade carried the entry slippage as an error.
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from src.units.accounts.alpaca_client import AlpacaClient
from src.units.accounts import execute as ex


def _client(monkeypatch, status_result):
    cli = AlpacaClient(api_key="k", api_secret="s", env="paper")

    def fake(method, path, json_body=None):
        if method == "POST":
            return {"retCode": 0, "result": {"id": "o1"}}
        return {"retCode": 0, "result": status_result}

    monkeypatch.setattr(cli, "_request", fake)
    monkeypatch.setenv("ALPACA_PLACE_CONFIRM_S", "1")
    return cli


_BRACKET = {"symbol": "IAUM", "side": "Buy", "qty": 2, "sl": 41.98, "tp": 47.78}


def test_full_fill_reports_venue_average(monkeypatch):
    cli = _client(monkeypatch, {"status": "filled", "filled_avg_price": "42.9086",
                                "filled_qty": "2"})
    out = cli.place(dict(_BRACKET))
    assert out["retCode"] == 0
    assert out["result"] == {"orderId": "o1", "avgPrice": 42.9086, "filledQty": 2.0}


def test_partial_fill_reports_no_average(monkeypatch):
    cli = _client(monkeypatch, {"status": "filled", "filled_avg_price": "42.9",
                                "filled_qty": "1"})
    assert cli.place(dict(_BRACKET))["result"] == {"orderId": "o1"}


def test_unusable_average_reports_none(monkeypatch):
    cli = _client(monkeypatch, {"status": "filled", "filled_avg_price": None,
                                "filled_qty": "2"})
    assert cli.place(dict(_BRACKET))["result"] == {"orderId": "o1"}


def test_confirm_disabled_reports_no_average(monkeypatch):
    cli = _client(monkeypatch, {"status": "filled", "filled_avg_price": "42.9",
                                "filled_qty": "2"})
    monkeypatch.setenv("ALPACA_PLACE_CONFIRM_S", "0")
    assert cli.place(dict(_BRACKET))["result"] == {"orderId": "o1"}


def test_submit_order_carries_fill_on_order_dict(monkeypatch):
    cli = _client(monkeypatch, {"status": "filled", "filled_avg_price": "42.9086",
                                "filled_qty": "2"})
    order = dict(_BRACKET)
    tid = ex._submit_order(cli, order, {"exchange": "alpaca", "account_id": "alpaca_live"})
    assert tid == "o1"
    assert order["venue_fill"] == {"avg_price": 42.9086, "filled_qty": 2.0,
                                   "source": "alpaca_order_status"}


def _pkg():
    return SimpleNamespace(symbol="IAUM", direction="long", entry=43.48, sl=41.98,
                           tp=47.78, strategy="iaum_pullback_1d", confidence=0.5,
                           meta={"order_package_id": "pkg-x"})


def _journal_row(tmp_path, monkeypatch, order, **kw):
    db = tmp_path / "tj.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db))
    cfg = {"exchange": "alpaca", "account_id": "alpaca_live",
           "account_class": "real_money", "mode": "live"}
    assert ex._log_trade_to_journal(_pkg(), cfg, order, trade_id="o1", **kw)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return dict(con.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone())


def test_journal_books_venue_fill_as_entry(tmp_path, monkeypatch):
    order = dict(_BRACKET, venue_fill={"avg_price": 42.9086, "filled_qty": 2.0,
                                       "source": "alpaca_order_status"})
    row = _journal_row(tmp_path, monkeypatch, order)
    assert row["entry_price"] == 42.9086
    notes = json.loads(row["notes"])
    assert notes["entry_price_source"] == "alpaca_order_status"
    assert notes["package_entry"] == 43.48


def test_journal_without_fill_keeps_package_entry(tmp_path, monkeypatch):
    row = _journal_row(tmp_path, monkeypatch, dict(_BRACKET))
    assert row["entry_price"] == 43.48
    assert "entry_price_source" not in json.loads(row["notes"])


def test_rejection_row_never_uses_fill(tmp_path, monkeypatch):
    order = dict(_BRACKET, venue_fill={"avg_price": 42.9, "source": "x"})
    row = _journal_row(tmp_path, monkeypatch, order, status="rejected", reason="r")
    assert row["entry_price"] == 43.48
