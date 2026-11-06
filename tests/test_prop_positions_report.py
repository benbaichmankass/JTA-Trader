"""AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE: the DXtrade writers post the venue Positions read in the consumer
shape (positions_state + positions in units, bot symbols) that INV-PROP-POSITIONS and live_review_packet read."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from src.prop.platform.base import Position
from src.prop.positions_report import positions_fields

REPO = Path(__file__).resolve().parents[1]
SYMS = {"ETHUSDT": {"venue": "ETHUSD", "lot_units": 1}, "BTCUSDT": {"venue": "BTCUSD", "lot_units": 0.01}}


def test_none_is_not_read_never_flat():
    assert positions_fields(None, SYMS) == {"positions_state": "not_read"}


def test_empty_list_is_a_clean_flat_read():
    f = positions_fields([], SYMS)
    assert f["positions_state"] == "read" and f["positions"] == [] and f["positions_count"] == 0


def test_lots_become_units_and_venue_symbols_become_bot_symbols():
    f = positions_fields([Position(symbol="BTCUSD", side="short", quantity=3.0, entry_price=70000.0),
                          {"symbol": "eth/usd", "side": "buy", "quantity": 0.72}], SYMS)
    assert f["positions_state"] == "read"
    assert [(p["symbol"], p["direction"], p["qty"]) for p in f["positions"]] == [("BTCUSDT", "short", 0.03),
                                                                               ("ETHUSDT", "long", 0.72)]


def test_unsizable_rows_withhold_the_list():
    for rows, want in (([Position(symbol="ETHUSD", side=None, quantity=1.0)], "side_unread"),
                       ([Position(symbol="ETHUSD", side="long", quantity=None)], "qty_unread"),
                       ([Position(symbol="DOGEUSD", side="long", quantity=5.0)], "qty_unread")):
        f = positions_fields(rows, SYMS)
        assert f["positions_state"] == want and "positions" not in f, rows
    # routing not loadable: a non-empty read cannot be sized, a flat one still can
    assert positions_fields([Position(symbol="ETHUSD", side="long", quantity=1.0)], None)["positions_state"] == "qty_unread"
    assert positions_fields([], None)["positions_state"] == "read"


def test_feed_status_report_carries_the_positions_read():
    spec = importlib.util.spec_from_file_location("blc", REPO / "scripts" / "prop" / "breakout_login_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.account_symbols = lambda _a: SYMS
    rep = mod.build_status_report("tradeify_1", {"balance": 1.0, "equity": 1.0},
                                  positions=[Position(symbol="ETHUSD", side="long", quantity=0.72).as_dict()], orders=[])
    assert rep["source"] == "breakout_login_check" and rep["open_positions"][0]["symbol"] == "ETHUSD"
    assert rep["positions_state"] == "read" and rep["positions"][0]["qty"] == 0.72
    assert mod.build_status_report("tradeify_1", {"balance": 1.0}, positions=None)["positions_state"] == "not_read"
