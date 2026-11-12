"""PNL-GROSS-VS-VENUE-6817: the venue's net closed P&L is ``pnl`` (operator decision w11).

decision: 2026-11-12 operator decisions page w11 "Yes: store the venue's net closed P&L where
trusted"; note "Store the venue's always, it is the single source of truth and if we have a gap
we need to understand why".

Shapes from the 2026-11-12 measurement: bybit_1 trade 6817 (XRPUSDT long 74160, journal gross
-786.096, venue closed_pnl -888.3026); a bybit_2 ml_entry close whose pnl was already the venue
net figure but whose net R was costed twice.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from src.runtime import order_monitor as om
from src.runtime import venue_pnl as vp
from src.runtime.net_r_label import _NET_PNL_BASES, net_r_for_trade
from src.units.db.database import _migrate_add_pnl_basis


def _db(tmp_path):
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, pnl_percent REAL, notes TEXT, "
        "setup_type TEXT, status TEXT, is_backtest INTEGER, created_at TEXT, closed_at TEXT, "
        "sl_order_id TEXT, tp_order_id TEXT, broker_order_id TEXT, fee_taker_usd REAL, "
        "fee_maker_usd REAL, funding_paid_usd REAL, stop_loss REAL)")
    assert _migrate_add_pnl_basis(c.cursor()) is True
    assert _migrate_add_pnl_basis(c.cursor()) is False, "idempotent"
    c.commit()
    c.close()

    class _D:
        def connect(self):
            k = sqlite3.connect(path)
            k.row_factory = sqlite3.Row
            return k
    return _D(), path


def _add(path, **kw):
    now = _dt.datetime.now(_dt.timezone.utc)
    row = dict(id=6817, account_id="bybit_1", symbol="XRPUSDT", direction="long",
               position_size=74160.0, entry_price=1.2582, exit_price=1.2476, pnl=-786.096,
               notes=json.dumps({"exit_price_source": "exchange_fill", "pnl_source": "local_compute"}),
               setup_type="ict_scalp_xrp_15m", status="closed", is_backtest=0,
               created_at=(now - _dt.timedelta(hours=30)).isoformat(),
               closed_at=(now - _dt.timedelta(hours=28)).isoformat(),
               sl_order_id="e043d46b", tp_order_id="9826d97e", broker_order_id=None,
               fee_taker_usd=102.64, fee_maker_usd=None, funding_paid_usd=None, stop_loss=1.2400)
    row.update(kw)
    c = sqlite3.connect(path)
    c.execute(f"INSERT INTO trades ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
              list(row.values()))
    c.commit()
    c.close()
    return row


def _get(path, tid):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone())
    c.close()
    return r, json.loads(r["notes"] or "{}")


CFGS = {"bybit_1": {"account_id": "bybit_1", "exchange": "bybit", "demo": True},
        "bybit_2": {"account_id": "bybit_2", "exchange": "bybit", "demo": False},
        "alpaca_paper": {"account_id": "alpaca_paper", "exchange": "alpaca"}}


def _reader(records, calls=None, state="rows_returned"):
    def read(cfg, *, symbol, start_ms, end_ms):
        if calls is not None:
            calls.append((cfg["account_id"], symbol))
        return {"query_state": state, "records": records}
    return read


def test_demo_row_stores_the_venue_net_figure_and_keeps_ours_beside_it(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path)
    closed_ms = om._isoformat_to_ms(row["closed_at"])
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3026",
           "updated_time": str(closed_ms + 5000)}
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([rec]))
    assert s["venue_net"] == 1
    r, n = _get(path, 6817)
    assert r["pnl"] == pytest.approx(-888.3026)
    assert r["pnl_basis"] == "venue_net"
    # ours: (1.2476 - 1.2582) * 74160 - 102.64 = -888.736
    assert r["pnl_computed"] == pytest.approx(-888.736, abs=1e-3)
    assert r["pnl_gap_usd"] == pytest.approx(-888.3026 + 888.736, abs=1e-3)
    assert not vp.is_gap(r["pnl"], r["pnl_computed"]), "0.43 USD is inside 1% of 888"
    assert n["venue_pnl_match"] == "order_id" and n["pnl_source"] == "bybit_closed_pnl"
    assert n["pnl_source_prior"] == "local_compute"


def test_a_netting_gap_is_recorded_not_reconciled(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path)
    closed_ms = om._isoformat_to_ms(row["closed_at"])
    # venue averaged the entry with a sibling: a much worse closed_pnl than ours
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-1500.0",
           "updated_time": str(closed_ms)}
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([rec]))
    r, _ = _get(path, 6817)
    assert r["pnl"] == -1500.0, "the venue's figure is stored even when it disagrees"
    assert s["gaps"] == 1 and vp.is_gap(r["pnl"], r["pnl_computed"])


def test_qty_time_match_when_no_order_id_and_ambiguity_refuses(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path, sl_order_id=None, tp_order_id=None)
    t = om._isoformat_to_ms(row["closed_at"])
    one = {"order_id": "x1", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3", "updated_time": str(t)}
    assert vp.match_venue_record([one], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell")[1] == "qty_time"
    two = dict(one, order_id="x2")
    assert vp.match_venue_record([one, two], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell") == (None, "ambiguous")
    wrong_side = dict(one, side="Buy")
    assert vp.match_venue_record([wrong_side], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell") == (None, "none")


def test_unmatched_is_retried_then_recorded_after_24h(tmp_path):
    db, path = _db(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    _add(path, id=1, closed_at=(now - _dt.timedelta(hours=2)).isoformat())
    _add(path, id=2, closed_at=(now - _dt.timedelta(hours=30)).isoformat())
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([]))
    assert s["retry"] == 1 and s["unmatched"] == 1
    assert _get(path, 1)[0]["pnl_basis"] is None
    r2, n2 = _get(path, 2)
    assert r2["pnl_basis"] == "venue_unmatched" and r2["pnl"] == -786.096, "nothing invented"


def test_a_failed_read_writes_nothing(tmp_path):
    db, path = _db(tmp_path)
    _add(path)
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=lambda *a, **k: None)
    assert s["retry"] == 1 and _get(path, 6817)[0]["pnl_basis"] is None


def test_alpaca_fill_exit_is_venue_fills_net_and_estimates_are_marked(tmp_path):
    db, path = _db(tmp_path)
    _add(path, id=10, account_id="alpaca_paper", symbol="IWM", direction="long", position_size=2275,
         entry_price=283.68, exit_price=279.450338, pnl=-9622.48, fee_taker_usd=0.0,
         notes=json.dumps({"exit_price_source": "broker_leg_fill"}))
    _add(path, id=11, account_id="alpaca_paper", symbol="SPY", direction="long", position_size=1,
         entry_price=700, exit_price=701, pnl=1.0,
         notes=json.dumps({"exit_price_source": "candle_at_close"}))
    calls = []
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([], calls))
    assert calls == [], "no Bybit read for an Alpaca row"
    assert _get(path, 10)[0]["pnl_basis"] == "venue_fills_net"
    assert _get(path, 11)[0]["pnl_basis"] == "computed_estimate"


def test_net_r_does_not_cost_a_venue_net_row_twice():
    # bybit_2 ml_entry trade 7079: pnl -2.602 is the venue's net figure, taker fee 0.1677 recorded
    base = {"id": 7079, "pnl": -2.602, "fee_taker_usd": 0.16769423, "cost_source": "broker",
            "entry_price": 1.10, "stop_loss": 1.08, "position_size": 100, "contract_value_usd": 1.0}
    old = net_r_for_trade(base)
    new = net_r_for_trade(dict(base, pnl_basis="venue_net"))
    assert new["net_pnl_usd"] == pytest.approx(-2.602)
    assert old["net_pnl_usd"] == pytest.approx(-2.602 - 0.16769423), "unclassified rows unchanged"
    assert net_r_for_trade(dict(base, pnl_basis="computed_estimate"))["net_pnl_usd"] == \
        pytest.approx(old["net_pnl_usd"])


def test_net_bases_agree():
    assert _NET_PNL_BASES == vp.NET_BASES


def test_gap_report_lists_gaps_and_unmatched(tmp_path):
    from scripts.ops.venue_pnl_gaps import find_items
    rows = [
        {"id": 1, "status": "closed", "account_id": "bybit_1", "pnl_basis": "venue_net",
         "pnl": -1500.0, "pnl_computed": -888.7, "pnl_gap_usd": -611.3},
        {"id": 2, "status": "closed", "account_id": "bybit_1", "pnl_basis": "venue_net",
         "pnl": -888.3, "pnl_computed": -888.7, "pnl_gap_usd": 0.4},
        {"id": 3, "status": "closed", "account_id": "bybit_2", "pnl_basis": "venue_unmatched", "pnl": 1.0},
        {"id": 4, "status": "closed", "account_id": "bybit_1", "pnl_basis": None, "pnl": 5.0},
    ]
    out = find_items(rows)
    assert out["n_gap"] == 1 and out["n_unmatched"] == 1 and out["n_classified"] == 3
