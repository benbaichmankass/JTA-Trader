"""DESK-MACRO v2 (b1): a ``limit`` desk/macro proposal is held by the claude_desk leg until the price reaches it inside the
bracket, then goes out as the existing market bracket; never touched within good_till_bars -> expired_unfilled."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.units.strategies import claude_desk as cd

AT = datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc)


def _row(side="long", level=36.8, stop=34.97, tp=39.55, tf="1d", gtb=3, did="DMB-X/T1"):
    return {"at": AT.isoformat(), "decision_id": did, "intent_id": "MI-X", "source": "desk_macro",
            "proposal": {"symbol": "SLV", "side": side, "timeframe": tf, "horizon_bars": 5,
                         "entry": {"type": "limit", "level": level, "good_till_bars": gtb},
                         "stop": {"level": stop, "basis": "atr"}, "tp": {"level": tp, "basis": "atr", "p_hit": 0.38}}}


def test_a_limit_proposal_is_valid_and_carries_its_limit():
    assert cd.proposal_problem(_row()["proposal"]) is None
    pkg = cd.order_package({}, _row())
    assert pkg["meta"]["entry_type"] == "limit" and pkg["meta"]["limit_level"] == 36.8 and pkg["meta"]["source"] == "desk_macro"
    assert cd.proposal_problem(dict(_row()["proposal"], entry={"type": "stop", "level": 36.8, "good_till_bars": 3})) \
        == f"{cd.R_ENTRY_TYPE}:stop"


def test_long_limit_waits_until_reached_then_enters_at_the_touch_price():
    pkg = cd.order_package({}, _row())
    out, why = cd.limit_touch(pkg, 37.20, AT)
    assert out is None and why.startswith(cd.R_LIMIT_WAIT) and "not reached" in why
    out, why = cd.limit_touch(pkg, 36.75, AT)
    assert why == "touched" and out["entry"] == 36.75 and out["sl"] == 34.97 and out["tp"] == 39.55
    assert out["meta"]["touch_price"] == 36.75 and abs(out["meta"]["risk_per_unit"] - (36.75 - 34.97)) < 1e-9


def test_short_limit_and_a_price_through_the_bracket_waits():
    pkg = cd.order_package({}, _row(side="short", level=100.0, stop=104.0, tp=94.0))
    assert cd.limit_touch(pkg, 99.0, AT)[0] is None                    # short: needs price >= 100
    assert cd.limit_touch(pkg, 100.5, AT)[1] == "touched"
    out, why = cd.limit_touch(pkg, 104.5, AT)                         # through the stop: never enter
    assert out is None and "outside bracket" in why
    long_pkg = cd.order_package({}, _row())
    assert "outside bracket" in cd.limit_touch(long_pkg, 34.5, AT)[1]  # long gapped below its stop
    assert cd.limit_touch(long_pkg, None, AT)[1].endswith("price_could_not_look")


def test_a_market_package_is_untouched():
    r = _row()
    r["proposal"]["entry"]["type"] = "market"
    pkg = cd.order_package({}, r)
    assert cd.limit_touch(pkg, 1.0, AT) == (pkg, "market")


def test_never_touched_limit_expires_unfilled_at_good_till_bars():
    rows = [_row(gtb=3)]
    pkg, terminal = cd.select(rows, symbol="SLV", consumed=set(), now=AT + timedelta(days=2, hours=23))
    assert pkg is not None and terminal == []                          # still alive: waits, not consumed
    pkg, terminal = cd.select(rows, symbol="SLV", consumed=set(), now=AT + timedelta(days=3))
    assert pkg is None and terminal and terminal[0][1] == cd.R_EXPIRED
