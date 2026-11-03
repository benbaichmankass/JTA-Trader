"""NETTED-SLICES: per-trade admission + sizing of a slice (positions.admit_slice)."""
from __future__ import annotations

import pytest

from src.runtime.positions import admit_slice

CFG = {"account_id": "bybit_1", "exchange": "bybit", "position_model": "slices"}


def _slice(strategy, direction, qty, entry=100.0, sl=95.0):
    return {"strategy_name": strategy, "direction": direction, "position_size": qty,
            "entry_price": entry, "stop_loss": sl}


def _admit(slices, positions, *, strategy="b", direction="long", meta=None,
           sized=2.0, dry=False, mode="partial", hedge=False, budget=1.0):
    return admit_slice(
        account_id="bybit_1", account_cfg=CFG, strategy=strategy, symbol="ETHUSDT",
        direction=direction, entry=100.0, sl=95.0 if direction == "long" else 105.0,
        meta=meta, sized_qty=sized, dry=dry,
        slices_reader=lambda a, s: slices,
        positions_reader=lambda cfg: positions,
        tpsl_mode_fn=lambda: mode,
        hedge_fn=lambda a, s: hedge,
        budget_trades=budget,
    )


def _pos(net):
    if net == 0:
        return []
    return [{"symbol": "ETHUSDT", "side": "Buy" if net > 0 else "Sell", "size": abs(net)}]


def test_flat_book_first_slice_gets_its_weighted_share():
    meta = {"slice_allocation": {"bybit_1": {"weight": 0.6, "contenders": ["a", "b"]}}}
    out = _admit([], _pos(0), meta=meta)
    assert out["ok"] and out["qty"] == pytest.approx(1.2)
    assert out["own_signed"] == 0.0


def test_second_strategy_same_side_is_admitted_not_noop():
    # the old account-net delta read this as `noop at_target`
    book = [_slice("a", "long", 1.0, sl=100.0)]  # a's stop at BE -> holds no risk
    out = _admit(book, _pos(1.0))
    assert out["ok"] and out["qty"] == pytest.approx(2.0)


def test_held_risk_of_other_strategies_shrinks_the_slice():
    book = [_slice("a", "long", 1.0)]  # 5 at risk of a 10 budget
    out = _admit(book, _pos(1.0))
    assert out["ok"] and out["qty"] == pytest.approx(1.0)


def test_budget_exhausted_is_refused():
    out = _admit([_slice("a", "long", 2.0)], _pos(2.0))
    assert not out["ok"] and out["reason"] == "slice_budget_exhausted"


def test_same_strategy_holding_a_slice_returns_its_own_qty_for_the_guard():
    out = _admit([_slice("b", "long", 1.0)], _pos(1.0))
    assert out["ok"] and out["own_signed"] == pytest.approx(1.0)
    assert out["detail"]["admission"] == "own_slice_open"


def test_opposite_slice_refused_on_a_one_way_book():
    out = _admit([_slice("a", "long", 1.0, sl=100.0)], _pos(1.0), direction="short")
    assert not out["ok"] and out["reason"] == "opposite_slice_one_way_book"


def test_opposite_slice_admitted_on_a_hedge_book():
    out = _admit([_slice("a", "long", 1.0, sl=100.0)], _pos(1.0), direction="short", hedge=True)
    assert out["ok"] and out["qty"] == pytest.approx(2.0)


def test_concurrent_slice_requires_partial_tpsl():
    out = _admit([_slice("a", "long", 1.0, sl=100.0)], _pos(1.0), mode="full")
    assert not out["ok"] and out["reason"] == "slice_requires_partial_tpsl"
    # a FLAT book does not need partial mode (a single bracket is the slice's)
    assert _admit([], _pos(0), mode="full")["ok"]


def test_divergent_and_unreadable_books_refuse_the_add():
    book = [_slice("a", "long", 1.0, sl=100.0)]
    div = _admit(book, _pos(0.4))
    assert not div["ok"] and div["reason"] == "slice_ledger_divergent"
    unr = _admit(book, None)
    assert not unr["ok"] and unr["reason"] == "slice_ledger_venue_unreadable"
    jr = _admit(None, _pos(0))
    assert not jr["ok"] and jr["reason"] == "slice_ledger_unreadable"


def test_dry_account_skips_the_venue_read():
    out = _admit([_slice("a", "long", 1.0, sl=100.0)], None, dry=True)
    assert out["ok"] and out["detail"]["reconcile"] == "skipped_dry"


def test_unmeasurable_other_slice_refuses():
    out = _admit([_slice("a", "long", 1.0, sl=None)], _pos(1.0))
    assert not out["ok"] and out["reason"] == "slice_risk_unmeasurable"


def test_contenders_do_not_count_against_each_other():
    # a and b contend this tick; a's slice landed first in the same tick.
    meta = {"slice_allocation": {"bybit_1": {"weight": 0.5, "contenders": ["a", "b"]}}}
    out = _admit([_slice("a", "long", 1.0)], _pos(1.0), meta=meta)
    assert out["ok"] and out["qty"] == pytest.approx(1.0)  # 0.5 of the full budget


# --- ADMISSION-JOURNAL-LAG-RACE: re-read once when the venue is flatter ---------

def _lagged(first, later, positions, **kw):
    """Journal reader that returns *first* on call 1 and *later* afterwards."""
    calls = {"n": 0, "slept": []}

    def reader(a, s):
        calls["n"] += 1
        return first if calls["n"] == 1 else later

    out = admit_slice(
        account_id="bybit_1", account_cfg=CFG, strategy=kw.get("strategy", "b"),
        symbol="ETHUSDT", direction=kw.get("direction", "long"), entry=100.0,
        sl=95.0 if kw.get("direction", "long") == "long" else 105.0, meta=None,
        sized_qty=2.0, dry=False, slices_reader=reader,
        positions_reader=lambda cfg: positions, tpsl_mode_fn=lambda: "partial",
        hedge_fn=lambda a, s: True, budget_trades=1.0,
        sleep_fn=calls["slept"].append)
    return out, calls


def test_close_landing_between_reads_is_admitted():
    stale = [_slice("a", "short", 1.0, sl=100.0)]
    out, calls = _lagged(stale, [], _pos(0))
    assert out["ok"], out
    assert calls["n"] == 2 and len(calls["slept"]) == 1
    assert out["detail"]["lag_recheck"]["resolved"] is True


def test_persistent_divergence_is_still_refused():
    stale = [_slice("a", "long", 1.0, sl=100.0)]
    out, calls = _lagged(stale, stale, _pos(0.4))
    assert not out["ok"] and out["reason"] == "slice_ledger_divergent"
    assert calls["n"] == 2 and len(calls["slept"]) == 1  # exactly one re-read


def test_venue_larger_than_ledger_is_refused_without_reread():
    book = [_slice("a", "long", 1.0, sl=100.0)]
    out, calls = _lagged(book, [], _pos(2.0))
    assert not out["ok"] and out["reason"] == "slice_ledger_divergent"
    assert calls["n"] == 1 and calls["slept"] == []


def test_opposite_sign_venue_is_refused_without_reread():
    book = [_slice("a", "long", 1.0, sl=100.0)]
    out, calls = _lagged(book, [], _pos(-0.5))
    assert not out["ok"] and calls["n"] == 1 and calls["slept"] == []
