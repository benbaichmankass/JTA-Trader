"""DESK-MACRO-DAILY prototype writer (scripts/ops/desk_macro_write.py): refusal rules + write-once, offline."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))


def test_desk_macro_write_self_test():
    import desk_macro_write as W
    assert W.self_test() == 0


def test_good_brief_validates_against_the_real_universe():
    import desk_macro_write as W
    uni, legs = W.desk_universe()
    pkt = W._pkt()
    assert W.problems(dict(W.GOOD, packet_sha=pkt["packet_sha"]), uni, legs, pkt) == []


def test_empty_trades_refused_unless_packet_prices_could_not_look():
    import desk_macro_write as W
    uni, legs = W.desk_universe()
    live, dead = W._pkt("measured"), W._pkt("could_not_look")
    empty = dict(W.GOOD, trades=[], no_trade_reason="nothing compelling")
    assert any("trades == [] is refused" in x for x in W.problems(dict(empty, packet_sha=live["packet_sha"]), uni, legs, live))
    assert W.problems(dict(empty, packet_sha=dead["packet_sha"]), uni, legs, dead) == []

