"""DESK-AM-REFOCUS: the pre-registered forward grade (RULE-DESK-AM-JUDGEMENT-V1), pure parts."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("damg", REPO / "scripts/research/desk_am_judgement_grade.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["damg"] = G
_spec.loader.exec_module(G)


def _bars(rows, t0=0, step=3600):
    return [{"time": t0 + i * step, "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(rows)]


FC = {"target_px": 110.0, "invalidation_px": 95.0, "horizon_bars": 3, "timeframe": "1h", "p_target": 0.5}


def test_forecast_hit_miss_expired_and_unresolved():
    assert G.forecast_outcome(FC, _bars([(100, 105, 99, 104), (104, 111, 103, 110), (110, 112, 109, 111)]), 0) == "hit"
    assert G.forecast_outcome(FC, _bars([(100, 101, 94, 96)]), 0) == "miss"
    # both levels inside one bar: invalidation first (pessimistic)
    assert G.forecast_outcome(FC, _bars([(100, 111, 94, 100)]), 0) == "miss"
    flat = [(100, 101, 99, 100)] * 4
    assert G.forecast_outcome(FC, _bars(flat), 0) == "expired"
    assert G.forecast_outcome(FC, _bars(flat[:2]), 0) is None          # horizon not covered yet
    short = dict(FC, target_px=90.0, invalidation_px=105.0)
    assert G.forecast_outcome(short, _bars([(100, 101, 89, 90)]), 0) == "hit"


def test_mechanical_rule_is_breakeven_only_when_in_profit_with_the_stop_behind_entry():
    pkg = {"direction": "long", "entry": "100"}
    r = {"state": {"sl": 95.0, "open_r": 0.8}, "recommendation": {"action": "close"}, "applied": True}
    m = G.mechanical_review(r, pkg)
    assert m["recommendation"]["action"] == "tighten_sl" and m["recommendation"]["level"] == 100.0 and m["applied"] is False
    assert G.mechanical_review(dict(r, state={"sl": 101.0, "open_r": 0.8}), pkg)["recommendation"]["action"] == "hold"
    assert G.mechanical_review(dict(r, state={"sl": 95.0, "open_r": -0.2}), pkg)["recommendation"]["action"] == "hold"


def test_verdict_accrues_below_the_floor_and_needs_both_comparators_to_pass():
    few = {f"p{i}": {"d_hold": 0.5, "d_mech": 0.5} for i in range(5)}
    assert G.verdict(few)["verdict"] == "accruing"
    good = {f"p{i}": {"d_hold": 0.3 + 0.01 * (i % 3), "d_mech": 0.1} for i in range(30)}
    assert G.verdict(good)["verdict"] == "pass"
    vs_mech_loses = {k: dict(v, d_mech=-0.1) for k, v in good.items()}
    assert G.verdict(vs_mech_loses)["verdict"] == "indeterminate"
    bad = {f"p{i}": {"d_hold": -0.2, "d_mech": -0.2} for i in range(30)}
    assert G.verdict(bad)["verdict"] == "fail"
    assert G.verdict({})["verdict"] == "accruing"
