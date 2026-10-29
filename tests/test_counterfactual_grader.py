"""TRADE-COUNTERFACTUAL-GRADER: the replay engine and one graded record (scripts/research/counterfactual_grader.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
spec = importlib.util.spec_from_file_location("counterfactual_grader", REPO / "scripts/research/counterfactual_grader.py")
cg = importlib.util.module_from_spec(spec)
sys.modules["counterfactual_grader"] = cg
spec.loader.exec_module(cg)

T0 = 1_792_000_000


def b(i, o, h, lo, c, dur=60):
    return {"time": T0 + i * dur, "open": o, "high": h, "low": lo, "close": c, "dur": dur}


def sim(bars, **kw):
    base = dict(side="short", entry_ref=100.0, r_dist=1.0, t_entry=T0, stop0=101.0, tp=96.0)
    base.update(kw)
    return cg.simulate(bars, **base)


def test_a_touch_is_not_a_fill_but_a_trade_through_is():
    out = sim([b(0, 100, 101.0, 99.5, 100), b(1, 100, 101.2, 99.8, 101)])
    assert out["fills"][0]["reason"] == "stop" and out["fills"][0]["ts"] == T0 + 60          # bar 0 only touched 101.0


def test_gap_through_the_stop_fills_at_the_open_and_tp_fills_at_its_price():
    assert sim([b(0, 102, 102.5, 101.5, 102)])["fills"][0]["px"] == 102                      # short gap up: open
    f = sim([b(0, 100, 100.2, 95.0, 96)])["fills"][0]
    assert f["reason"] == "tp" and f["px"] == 96.0


def test_stop_is_checked_before_tp_inside_one_bar():
    f = sim([b(0, 100, 101.5, 95.0, 98)])["fills"][0]
    assert f["reason"] == "stop"


def test_timed_stop_move_only_tightens_and_binds_from_the_next_bar_open():
    acts = [{"ts": T0 + 60, "kind": "set_stop", "level": 100.0}, {"ts": T0 + 60, "kind": "set_stop", "level": 102.0}]  # 2nd is looser
    out = sim([b(0, 99.5, 99.8, 99.0, 99.2), b(1, 99.2, 100.4, 99.0, 100.2)], actions=acts)
    assert out["fills"][0]["px"] == 100.0 and out["fills"][0]["ts"] == T0 + 60


def test_rule_triggers_on_the_extreme_and_takes_effect_next_bar():
    bars = [b(0, 100, 100.1, 98.9, 99.0), b(1, 99.0, 100.2, 98.9, 100.1)]    # +1.1R in bar 0, BE hit in bar 1
    out = sim(bars, rules=[{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0}])
    assert out["fills"][0]["reason"] == "stop" and out["fills"][0]["px"] == 100.0
    same_bar = sim([b(0, 100, 100.3, 98.9, 100.2)], rules=[{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0}])
    assert same_bar["fills"][0]["reason"] == "open_at_data_end"                  # not applied inside the bar that triggered it


def test_partial_close_then_remainder_rides_and_unresolved_is_flagged():
    out = sim([b(0, 99, 99.5, 98.5, 99), b(1, 99, 99.5, 98.5, 99)], actions=[{"ts": T0, "kind": "close", "frac": 0.5}])
    assert [f["reason"] for f in out["fills"]] == ["close", "open_at_data_end"] and out["resolved"] is False
    assert abs(sum(f["frac"] for f in out["fills"]) - 1.0) < 1e-9


def test_stitch_uses_the_finest_series_and_never_overlaps():
    s = {"15m": [{"time": T0 + i * 900, "open": 1, "high": 1, "low": 1, "close": 1} for i in range(8)],
         "5m": [{"time": T0 + 3600 + i * 300, "open": 1, "high": 1, "low": 1, "close": 1} for i in range(24)],
         "1m": [{"time": T0 + 7200 + i * 60, "open": 1, "high": 1, "low": 1, "close": 1} for i in range(120)]}
    path = cg.stitch_bars(s, T0)
    assert [x["dur"] for x in path[:5]] == [900, 900, 900, 900, 300]
    assert all(path[i]["time"] + path[i]["dur"] <= path[i + 1]["time"] for i in range(len(path) - 1))
    assert path[-1]["dur"] == 60


def test_net_of_charges_fee_exit_slippage_and_funding_and_no_slippage_on_a_tp_limit():
    cm = {"fee_bps": 10.0, "slip_exit_bps": 2.0, "fund_bps_window": 1.0}
    stop = {"fills": [{"frac": 1.0, "px": 99.0, "ts": T0 + 28800, "reason": "stop"}]}
    n = cg.net_of(stop, side="short", entry_fill=100.0, r_dist=1.0, t_entry=T0, cm=cm)
    per_bp = 100.0 / 1.0 / 1e4
    assert abs(n["gross_r"] - 1.0) < 1e-9 and abs(n["cost_r"]["fee"] - 10 * per_bp) < 1e-9
    assert abs(n["cost_r"]["slip"] - 2 * per_bp) < 1e-9 and abs(n["cost_r"]["funding"] - 1 * per_bp) < 1e-9
    tp = {"fills": [{"frac": 1.0, "px": 96.0, "ts": T0, "reason": "tp"}]}
    assert cg.net_of(tp, side="short", entry_fill=100.0, r_dist=1.0, t_entry=T0, cm=cm)["cost_r"]["slip"] == 0.0


def _pkg():
    return {"order_package_id": "pkg-x", "strategy_name": "s", "symbol": "ADAUSDT", "direction": "short", "entry": 100.0, "sl": 100.0,
            "tp": 96.0, "exit_plan": '{"stop": {"price": 101.0}}', "meta": {"atr": 0.5, "trail_mult": 5.0}}


def _trade(i, acct, cls, qty, exit_px, pnl, reason="sl", closed="2026-10-20T01:00:00+00:00"):
    return {"id": i, "account_id": acct, "account_class": cls, "status": "closed", "position_size": qty, "entry_price": 100.0,
            "exit_price": exit_px, "exit_reason": reason, "pnl": pnl, "timestamp": cg.lrc._iso(T0), "closed_at": closed,
            "fee_taker_usd": 0.0, "cost_source": None}


def test_grade_package_one_record_per_package_with_every_arm_family_and_the_initial_stop_as_r_unit():
    bars = [b(i, 100 - 0.05 * i, 100 - 0.05 * i + 0.1, 100 - 0.05 * i - 0.1, 100 - 0.05 * i, dur=900) for i in range(60)]
    legs = [_trade(1, "bybit_2", "real_money", 10.0, 99.0, 9.5), _trade(2, "bybit_portfolio", "paper", 1000.0, 99.0, None)]
    acts = [{"ts_epoch": T0 + 3600, "kind": "set_stop", "level": 100.0, "source": "operator", "time_provenance": "ESTIMATED"}]
    rec = cg.grade_package(_pkg(), legs, bars, [], acts, {"bybit_2": 200.0, "bybit_portfolio": None}, {}, n_random=20)
    assert rec["status"] == "graded" and rec["bracket"]["r_dist"] == 1.0                  # R from exit_plan, not the moved sl
    fams = {a["family"] for a in rec["arms"]}
    assert {"actual", "baseline", "entry_brackets", "alt_brackets", "less_management", "more_management"} <= fams
    assert rec["random_control"]["n"] == 20
    ids = [a["arm_id"] for a in rec["arms"]]
    assert len(ids) == len(set(ids))
    pa = rec["arms"][0]["per_account"]
    assert pa["bybit_2"]["pnl_usd"] == 9.5 and pa["bybit_portfolio"]["pct_of_account"] is None   # null, never 0


def test_a_package_with_an_open_leg_is_not_graded():
    legs = [dict(_trade(1, "bybit_2", "real_money", 10.0, None, None), status="open", closed_at=None)]
    assert cg.grade_package(_pkg(), legs, [b(0, 1, 1, 1, 1)], [], [], {}, {})["reason"] == "not_all_legs_closed"


# ---- GRADER-POST-EXIT-HORIZON: what happened after the real exit
T_CLOSE = T0 + 3600 + 400              # inside bar 4 (900s bars)
HORIZON = {"seconds": 3 * 3600.0, "hours": 3.0, "source": "test", "timeframe": "15m"}


def _post(path_after, *, exit_px, reason, pnl):
    """Short from 100, stop 101, TP 96; four quiet bars, then bar 4 (the exit bar), then ``path_after`` bars."""
    bars = [b(i, 100, 100.3, 99.8, 100, dur=900) for i in range(4)]
    bars.append(b(4, 100, 101.1 if reason == "sl" else 100.5, 99.9, 100.2, dur=900))
    bars += [b(5 + i, *ohlc, dur=900) for i, ohlc in enumerate(path_after)]
    leg = _trade(1, "bybit_2", "real_money", 10.0, exit_px, pnl, reason=reason, closed=cg.lrc._iso(T_CLOSE))
    return cg.grade_package(_pkg(), [leg], bars, [], [], {"bybit_2": 200.0}, {}, n_random=5, horizon=HORIZON)


def _falling():
    return [(100.2 - 0.4 * i, 100.3 - 0.4 * i, 100.0 - 0.5 * i, 100.0 - 0.45 * i) for i in range(12)]


def test_price_came_back_after_the_stop_is_exited_early_and_a_1_25x_stop_survives_to_tp():
    rec = _post(_falling(), exit_px=101.0, reason="sl", pnl=-10.0)     # spike to 101.1 stopped us at -1R, then it fell
    po = rec["post_exit"]
    assert po["verdict"]["verdict"] == "exited_early" and po["verdict"]["resolved"] is True and po["verdict"]["r_diff"] >= 1.0
    w = {x["arm_id"]: x for x in po["wider_sl_arms"]}
    assert w["alt_sl1.25x_tp3R"]["survived"] is True and w["alt_sl1.25x_tp3R"]["net_r"] > 2.0
    assert po["mfe_r"] > 5.0 and po["tp_reach"]["reached"] is True and po["tp_reach"]["bars"] >= 1


def test_price_kept_going_against_us_after_an_early_close_is_exit_saved_r():
    rising = [(100.6 + 0.2 * i, 100.8 + 0.3 * i, 100.5 + 0.2 * i, 100.7 + 0.25 * i) for i in range(12)]
    rec = _post(rising, exit_px=100.4, reason="close", pnl=-4.0)       # closed at -0.4R; holding to the stop is -1R
    v = rec["post_exit"]["verdict"]
    assert v["verdict"] == "exit_saved_r" and v["resolved"] is True and v["r_diff"] <= -0.5
    assert all(x["survived"] is False for x in rec["post_exit"]["wider_sl_arms"])
    assert rec["post_exit"]["tp_reach"]["reached"] is False             # whole horizon observed: genuinely never


def test_an_arm_still_open_at_the_horizon_stays_unresolved_and_is_never_a_measured_number():
    drift = [(100.0, 100.3, 99.7, 100.0)] * 12
    rec = _post(drift, exit_px=100.4, reason="close", pnl=-4.0)
    po = rec["post_exit"]
    assert po["horizon_reached"] is True and po["verdict"]["verdict"] is None and po["verdict"]["resolved"] is False
    assert po["verdict"]["n_unresolved"] > 0 and po["verdict"]["r_diff"] is None
    assert all(x["resolved"] is False and x["net_r"] is None and x["marked_net_r_unresolved"] is not None for x in po["wider_sl_arms"])
    assert all(x["provenance"] == "unverified" for x in po["wider_sl_arms"])


def test_bars_stop_at_the_horizon_and_a_short_path_is_not_horizon_reached():
    rec = _post(_falling()[:3], exit_px=101.0, reason="sl", pnl=-10.0)
    assert rec["post_exit"]["horizon_reached"] is False and rec["post_exit"]["tp_reach"]["reached"] in (True, None)


def test_horizon_prefers_the_legs_max_hold_else_the_timeframe_default():
    assert cg.resolve_horizon({}, {"timeframe": "15m", "max_hold_hours": 5})["source"] == "config.max_hold_hours"
    h = cg.resolve_horizon({}, {"timeframe": "2h"})
    assert h["source"] == "default_by_timeframe" and h["hours"] == 144.0
    assert cg.resolve_horizon({}, {})["source"] == "default_unknown_timeframe"


def test_a_package_is_graded_only_once_its_horizon_has_passed_then_regraded_if_the_record_predates_it(tmp_path):
    pkg = {"strategy_name": "nope", "timeframe": "15m"}
    legs = [{"closed_at": cg.lrc._iso(T0)}]
    rec = tmp_path / "r.json"
    h_end = T0 + 48 * 3600
    assert cg.due_for_grading(rec, pkg, legs, h_end - 60) is False
    assert cg.due_for_grading(rec, pkg, legs, h_end + 60) is True                  # no record yet
    rec.write_text('{"schema_version": 2, "graded_at": "%s"}' % cg.lrc._iso(T0 + 1380))
    assert cg.due_for_grading(rec, pkg, legs, h_end + 60) is True                  # graded 23 min after the close
    rec.write_text('{"schema_version": 2, "graded_at": "%s"}' % cg.lrc._iso(h_end + 5))
    assert cg.due_for_grading(rec, pkg, legs, h_end + 60) is False
