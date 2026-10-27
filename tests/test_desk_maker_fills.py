"""Tests for scripts/research/desk_maker_fills.py (lane DESK-MAKER-FILLS)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

_P = Path(__file__).resolve().parents[1] / "scripts" / "research" / "desk_maker_fills.py"
_spec = importlib.util.spec_from_file_location("desk_maker_fills", _P)
mf = importlib.util.module_from_spec(_spec)
sys.modules["desk_maker_fills"] = mf
_spec.loader.exec_module(mf)

DAY = date(2026, 1, 2)
D0 = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
TICK = 0.01


def _csv(rows, rpi=None):
    head = "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional,RPI"
    out = [head]
    for i, (t, side, px) in enumerate(rows):
        flag = "1" if rpi and i in rpi else "0"
        out.append(f"{t},TESTUSDT,{side},1,{px},ZeroPlusTick,id{i},0,1,{px},{flag}")
    return ("\n".join(out) + "\n").encode()


def test_parse_drops_rpi_and_sorts():
    p = mf.parse_prints(_csv([(D0 + 2, "Buy", 10.02), (D0 + 1, "Sell", 10.0), (D0 + 3, "Sell", 9.0)], rpi={2}))
    assert p.n_rpi_dropped == 1 and p.n_raw == 3
    assert list(p.ts) == [D0 + 1, D0 + 2]
    assert list(p.is_buy) == [False, True]


def test_infer_tick():
    assert mf.infer_tick(np.array([10.0, 10.01, 10.03, 10.01])) == pytest.approx(0.01)
    with pytest.raises(ValueError):
        mf.infer_tick(np.array([10.0, 10.0]))


def test_quote_at_one_tick_spread_from_aggressor_side():
    p = mf.parse_prints(_csv([(D0 + 1, "Sell", 10.0), (D0 + 2, "Buy", 10.05)]))
    assert mf.quote_at(p, D0 + 0.5, TICK) is None
    bid, ask, mid = mf.quote_at(p, D0 + 1.5, TICK)
    assert (bid, ask) == pytest.approx((10.0, 10.01)) and mid == pytest.approx(10.005)
    bid, ask, _ = mf.quote_at(p, D0 + 2, TICK)          # at-or-before is inclusive
    assert (bid, ask) == pytest.approx((10.04, 10.05))


def test_strict_fill_needs_trade_through_optimistic_takes_touch():
    p = mf.parse_prints(_csv([(D0 + 1, "Sell", 10.0), (D0 + 5, "Sell", 10.0), (D0 + 9, "Sell", 9.99)]))
    # long limit at 10.00: a print AT 10.00 fills only optimistically; 9.99 trades through.
    assert mf.first_fill(p, D0 + 1, D0 + 20, 10.0, TICK, True, strict=False) == D0 + 5
    assert mf.first_fill(p, D0 + 1, D0 + 20, 10.0, TICK, True, strict=True) == D0 + 9
    # window ends before the trade-through -> no strict fill; the print AT T is never counted.
    assert mf.first_fill(p, D0 + 1, D0 + 8, 10.0, TICK, True, strict=True) is None
    assert mf.first_fill(p, D0 + 5, D0 + 6, 10.0, TICK, True, strict=False) is None
    # short side mirrors
    q = mf.parse_prints(_csv([(D0 + 1, "Buy", 10.0), (D0 + 4, "Buy", 10.01)]))
    assert mf.first_fill(q, D0 + 1, D0 + 9, 10.0, TICK, False, strict=True) == D0 + 4


def _path(prices_by_min, start_side="Sell"):
    """One print per 30 s on hour 1, flat by default, overridden per minute offset."""
    rows = []
    T = D0 + 3600
    rows.append((T - 10, start_side, 10.0))
    for s in range(0, 3 * 3600, 30):
        m = s // 60
        px = prices_by_min.get(m, None)
        if px is None:
            continue
        rows.append((T + s + 1, "Sell" if px <= 10.0 else "Buy", px))
    return rows


def test_delta_F_filled_equals_spread_plus_fee_diff():
    # price dips one tick through 10.00 at minute 2, then back; ends far later so markouts exist.
    path = {m: 10.0 for m in range(0, 180)}
    path[2] = 9.99
    p = mf.parse_prints(_csv(_path(path)))
    rows = mf.decision_rows(p, "TESTUSDT", DAY, TICK, windows=(5,), offsets=(0,), markouts=(1,), hours=(1,))
    long = [r for r in rows if r["dir"] == 1][0]
    assert long["filled_strict"] is True
    expected = (10.01 - 10.0) / 10.005 * 1e4 + (mf.TAKER_FEE_BPS - mf.MAKER_FEE_BPS)
    assert long["delta_F_strict"] == pytest.approx(expected)


def test_delta_F_unfilled_pays_the_runaway():
    # price rises for a long: never trades through the bid -> fallback taker at T+5 min pays more.
    path = {m: 10.0 + 0.01 * (m + 1) for m in range(0, 180)}
    p = mf.parse_prints(_csv(_path(path)))
    rows = mf.decision_rows(p, "TESTUSDT", DAY, TICK, windows=(5,), offsets=(0,), markouts=(1,), hours=(1,))
    long = [r for r in rows if r["dir"] == 1][0]
    assert long["filled_strict"] is False and long["filled_optimistic"] is False
    # last print at or before T+5min is minute 4's (10.05, Buy) -> ask 10.05; taker ask_T was 10.01
    expected = (10.01 - 10.05) / 10.005 * 1e4
    assert long["delta_F_strict"] == pytest.approx(expected)
    short = [r for r in rows if r["dir"] == -1][0]
    assert short["filled_strict"] is True     # a short resting at the ask is filled by the rally


def test_skips_decision_without_room_for_markouts():
    p = mf.parse_prints(_csv([(D0 + 3500, "Sell", 10.0), (D0 + 3700, "Sell", 9.99)]))
    assert mf.decision_rows(p, "TESTUSDT", DAY, TICK, hours=(1,)) == []


def test_grade_verdicts():
    def mk(day, sym, d):
        return {"symbol": sym, "day": day, "W": mf.PRIMARY_W, "k": mf.PRIMARY_K, "delta_F_strict": d,
                "filled_strict": d > 0, "tick_bps": 1.0, "maker_markout_bps": {m: 0.0 for m in mf.MARKOUTS_MIN},
                "taker_markout_bps": {m: 0.0 for m in mf.MARKOUTS_MIN}, "fill_wait_s": 1.0, "trend_aligned": None}
    syms = list(mf.SYMBOLS)
    rng = np.random.default_rng(0)
    good = [mk(f"d{i}", s, 5.0 + rng.normal()) for i in range(35) for s in syms for _ in range(6)]
    g = mf.grade(good, syms, 35)
    assert g["verdict"] == "pass" and g["symbols_positive"] == 6
    bad = [dict(r, delta_F_strict=r["delta_F_strict"] - 4.0) for r in good]   # mean ~1 bps < X
    assert mf.grade(bad, syms, 35)["verdict"] == "fail"
    assert mf.grade(good, syms, 10)["verdict"] == "indeterminate"           # days below floor
    assert mf.grade(good[:100], syms, 35)["verdict"] == "indeterminate"     # rows below floor


def test_registered_sample_is_fixed_and_excludes_dev_day():
    days = mf.sample_days()
    assert len(days) == 40 and days[0] == date(2026, 10, 25) and days[-1] == date(2025, 11, 8)
    assert date(2026, 10, 26) not in days
