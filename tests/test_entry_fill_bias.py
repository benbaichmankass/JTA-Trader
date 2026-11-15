"""ENTRY-FILL-BIAS-30D: the pure parts of scripts/research/entry_fill_bias.py (overlap, sign of the R bias, counts)."""
import json

from scripts.research import entry_fill_bias as E


def _t(i, acct="bybit_2", sym="SOLUSDT", d="long", entry=100.0, sl=90.0, o="2026-11-01T00:00:00+00:00",
       c="2026-11-02T00:00:00+00:00", pkg=None):
    return {"id": i, "account_id": acct, "symbol": sym, "direction": d, "entry_price": entry, "stop_loss": sl,
            "timestamp": o, "closed_at": c, "status": "closed", "order_package_id": pkg}


def test_overlap_marks_only_rows_whose_lives_intersect_on_the_same_account_and_symbol():
    rows = [_t(1), _t(2, o="2026-11-01T12:00:00+00:00", c="2026-11-03T00:00:00+00:00"),
            _t(3, o="2026-11-05T00:00:00+00:00", c="2026-11-06T00:00:00+00:00"),
            _t(4, acct="bybit_1", o="2026-11-01T06:00:00+00:00")]          # other account: not an overlap
    assert E.overlap_ids(rows) == {1, 2}


def test_r_bias_sign_is_adverse_positive_for_both_sides_and_uses_the_declared_risk():
    trades = [_t(1, d="long", entry=100.0, pkg="p1"), _t(2, d="short", entry=100.0, sl=110.0, pkg=None)]
    pkgs = {"p1": {"meta": json.dumps({"risk_per_unit": 5.0})}}
    fills = {1: {"fill": 100.5, "read_state": "measured"},     # long filled 0.5 above plan: adverse, +0.1R (risk 5)
             2: {"fill": 99.0, "read_state": "measured"}}      # short filled 1.0 below plan: adverse, +0.1R (risk |100-110|)
    out = E.measure(trades, pkgs, fills, overlap=set())["bybit_2"]
    assert out["n_measured"] == 2 and out["risk_basis"] == {"declared_initial_risk": 1, "trade_stop_loss": 1}
    assert out["clean"]["r_bias_mean"] == 0.1 and out["clean"]["abs_bps_median"] == 75.0


def test_unread_and_unmatched_rows_are_counted_never_dropped():
    trades = [_t(1), _t(2), _t(3)]
    fills = {1: {"fill": None, "read_state": "unmatched"}, 2: {"fill": None, "read_state": "could_not_look"}}
    out = E.measure(trades, {}, fills, overlap=set())["bybit_2"]
    assert (out["n_closed"], out["n_measured"], out["n_unmatched"], out["n_could_not_look"]) == (3, 0, 1, 2)
    assert out["clean"]["n"] == 0 and out["clean"]["r_bias_mean"] is None   # null, never 0
