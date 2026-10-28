"""Declared venue-wedged orders leave `orders` only when the symbol is confirmed flat; never silently."""
import textwrap

from src.runtime import venue_wedged_orders as vw

WEDGED = "2e843e04-5487-470c-a702-70e796fbd05e"
STOP = "891ddff0-b24d-4039-9322-8492bcd51e66"


def _cfg(tmp_path, body=None):
    p = tmp_path / "w.yaml"
    p.write_text(body or textwrap.dedent(f"""
        venue_wedged_orders:
          alpaca_paper:
            - {{order_id: {WEDGED}, symbol: GLD, reason: r, evidence: e, added: 2026-10-28}}
            - {{order_id: {STOP}, symbol: GLD, reason: r, evidence: e, added: 2026-10-28}}
    """))
    return p


ORDERS = [{"order_id": WEDGED, "symbol": "GLD"}, {"order_id": STOP, "symbol": "GLD"},
          {"order_id": "other", "symbol": "GLD"}, {"order_id": "q1", "symbol": "QQQ"}]


def test_flat_symbol_moves_declared_orders_to_the_visible_side_list(tmp_path):
    kept, ex = vw.partition("alpaca_paper", ORDERS, [{"symbol": "QQQ", "qty": 5.0}], _cfg(tmp_path))
    assert [o["order_id"] for o in ex] == [WEDGED, STOP]
    assert [o["order_id"] for o in kept] == ["other", "q1"]      # an unlisted GLD order stays flagged


def test_held_position_excludes_nothing(tmp_path):
    kept, ex = vw.partition("alpaca_paper", ORDERS, [{"symbol": "GLD", "qty": 39.0}], _cfg(tmp_path))
    assert ex == [] and kept == ORDERS


def test_unreadable_positions_exclude_nothing(tmp_path):
    kept, ex = vw.partition("alpaca_paper", ORDERS, None, _cfg(tmp_path))
    assert ex == [] and kept == ORDERS


def test_other_account_and_missing_config_exclude_nothing(tmp_path):
    assert vw.partition("alpaca_live", ORDERS, [], _cfg(tmp_path))[1] == []
    assert vw.partition("alpaca_paper", ORDERS, [], tmp_path / "absent.yaml")[1] == []


def test_symbol_mismatch_is_not_excluded(tmp_path):
    odd = [{"order_id": WEDGED, "symbol": "SPY"}]
    assert vw.partition("alpaca_paper", odd, [], _cfg(tmp_path))[1] == []


def test_shipped_config_declares_exactly_the_two_gld_orders():
    assert vw._declared("alpaca_paper") == {WEDGED: "GLD", STOP: "GLD"}
