"""LTR-5: counterfactual replay (scripts/research/live_review_counterfactual.py) and the Live review grader."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(REPO / "scripts" / "research"))
cf = _load("live_review_counterfactual", "scripts/research/live_review_counterfactual.py")
gr = _load("live_review_grade", "scripts/ops/live_review_grade.py")
chk = _load("clrr_t", "scripts/ci/check_live_review_records.py")

T0 = 1_792_000_000          # review time (epoch s); bars below open at T0 + k*7200
H = 7200


def bars(*ohlc):
    return [{"time": T0 + i * H, "open": o, "high": h, "low": lo, "close": c} for i, (o, h, lo, c) in enumerate(ohlc)]


def pkg(**kw):
    p = {"order_package_id": "pkg-t", "symbol": "ADAUSDT", "direction": "short", "entry": 100.0, "sl": 101.0, "tp": 96.0,
         "created_at": "2026-10-20T00:00:00Z", "meta": {"timeframe": "2h", "atr": 0.5}}
    p.update(kw)
    return p


def review(action="tighten_sl", level=99.5, applied=False, **kw):
    r = {"review_id": "LR-20261026T0000Z-pkg-t", "order_package_id": "pkg-t", "trade_id": 1, "leg": "t_leg",
         "reviewed_at": cf._iso(T0), "applied": applied,
         "recommendation": {"action": action, "level": level, "basis": "table", "evidence_source": "table"},
         "state": {"sl": 101.0, "tp": 96.0, "peak_r": 0.9},
         "apply_policy": {"bound_r": 0.25, "within_bound": True, "tighten_r": -0.1},
         "shadow_policy": {"bound_r": 0.5, "within_bound": True, "would_apply": True, "tighten_r": -0.1}}
    r.update(kw)
    return r


def trade(gross_r, **kw):
    """A closed short, 1 unit, risk 1.0 => pnl in R. Costs come from the recorded legs only (broker)."""
    t = {"id": 1, "status": "closed", "symbol": "ADAUSDT", "direction": "short", "entry_price": 100.0, "stop_loss": 105.0,
         "position_size": 1.0, "pnl": gross_r, "fee_taker_usd": 0.02, "fee_maker_usd": 0.0, "funding_paid_usd": 0.0,
         "cost_source": "broker", "timestamp": "2026-10-20T00:00:00+00:00", "closed_at": cf._iso(T0 + 5 * H),
         "exit_reason": "tp"}
    t.update(kw)
    return t


def _slip_r():
    return cf.resolve_cost_policy("ADAUSDT")[0] * 100.0 / 1.0 / 1e4


def realised(gross_r):
    """pnl that makes the realised net equal the replay's net (replay adds policy slippage)."""
    return gross_r - _slip_r()


# ---- the replay primitive -------------------------------------------------------------------

def test_stop_checked_before_tp_in_the_same_bar():
    b = bars((100, 100.5, 95.0, 96))                      # touches 101? no; touches tp 96 only
    assert cf.replay(b, side="short", entry=100, r_dist=1, start_ts=T0, stop=101, tp=96, extreme_r0=0, trail_dist=None)["reason"] == "tp"
    b = bars((100, 101.5, 95.0, 96))                      # touches BOTH: stop wins
    r = cf.replay(b, side="short", entry=100, r_dist=1, start_ts=T0, stop=101, tp=96, extreme_r0=0, trail_dist=None)
    assert r["reason"] == "stop" and r["gross_r"] == -1.0


def test_gap_through_the_stop_fills_at_the_open():
    b = bars((103.0, 104, 102.5, 103))
    r = cf.replay(b, side="short", entry=100, r_dist=1, start_ts=T0, stop=101, tp=None, extreme_r0=0, trail_dist=None)
    assert r["gross_r"] == -3.0


def test_bar_in_progress_at_review_is_skipped():
    b = bars((100, 102, 99, 100), (100, 100.2, 99, 99))
    r = cf.replay(b, side="short", entry=100, r_dist=1, start_ts=T0 + 1, stop=101, tp=None, extreme_r0=0, trail_dist=None)
    assert r is None                                       # bar 0 (touches 102) opened before the review; bar 1 is quiet


def test_trail_only_tightens():
    b = bars((98, 98.2, 97, 97.5), (97.5, 99.9, 97.4, 99.5), (99.5, 100.9, 99, 100.5))
    r = cf.replay(b, side="short", entry=100, r_dist=1, start_ts=T0, stop=101, tp=None, extreme_r0=0, trail_dist=2.0)
    # extreme after bar0 = 97 -> trail stop 99; bar1 high 99.9 >= 99 -> stopped at 99 (+1R), not at 101
    assert r["gross_r"] == 1.0 and r["ts"] == T0 + H


# ---- one review -----------------------------------------------------------------------------

def test_unapplied_tighten_priced_as_cost_of_tightening():
    # price pops to 99.7 (tighten @99.5 is hit: +0.5R) then runs to the 96 target (+4R realised)
    b = bars((99.0, 99.7, 98.5, 99.0), (98.5, 98.6, 96.0, 96.0))
    r = cf.price_review(review(), pkg(), trade(realised(4.0)), b)
    assert r["state"] == "priced", r
    o = r["outcome"]
    assert o["replay_fidelity"] == "replay_matches_realised"
    assert o["net_r"] == o["cf_r"]                                       # unapplied: realised IS the hold path
    assert abs(o["rec_r"] - (0.5 - 0.02 - _slip_r())) < 1e-6
    assert o["delta_r"] < -3.0                                           # tightening threw away the move
    assert o["cf_r_shadow_0_5"] == o["rec_r"]                            # within the 0.5R shadow bound
    assert chk.row_problems(o, "outcomes", chk.json.loads(chk.SCHEMA.read_text())) == []


def test_applied_tighten_priced_against_the_hold_replay():
    # applied: realised exit was the tightened stop (+0.5R); untouched stop 101 is then hit (-1R) on the reversal
    b = bars((99.0, 99.7, 98.5, 99.0), (99.0, 101.5, 99.0, 101.0))
    tr = trade(realised(0.5), exit_reason="sl")
    r = cf.price_review(review(applied=True), pkg(), tr, b)
    assert r["state"] == "priced", r
    o = r["outcome"]
    assert o["replay_fidelity"] == "unvalidated" and abs(o["cf_r"] - (-1.0 - 0.02 - _slip_r())) < 1e-6
    assert o["delta_r"] > 1.4 and o["rec_r"] == o["net_r"]


def test_open_trade_is_pending_with_a_to_date_replay():
    b = bars((99.0, 99.7, 98.5, 99.0))
    r = cf.price_review(review(), pkg(), trade(None, status="open", pnl=None, closed_at=None), b)
    assert (r["state"], r["reason"]) == ("could_not_price", "trade_open")
    assert r["to_date"]["rec_exit"]["gross_r"] == 0.5 and r["to_date"]["hold_exit"] is None
    assert r["outcome"] is None


def test_replay_that_cannot_reproduce_the_realised_exit_is_not_priced():
    b = bars((99.0, 99.7, 98.5, 99.0), (98.5, 98.6, 96.0, 96.0))          # replay says +4R
    r = cf.price_review(review(), pkg(), trade(realised(1.0)), b)         # but the trade realised +1R
    assert (r["state"], r["reason"]) == ("could_not_price", "replay_mismatch")


def test_no_candles_and_no_package_are_named_reasons():
    assert cf.price_review(review(), pkg(), trade(1.0), None)["reason"] == "no_candles"
    assert cf.price_review(review(), None, trade(1.0), bars((1, 1, 1, 1)))["reason"] == "no_package_row"
    assert cf.price_review(review(level=None), pkg(), trade(1.0), bars((1, 1, 1, 1)))["reason"] == "tighten_level_missing"


def test_hold_call_is_not_a_priced_call_and_grades_zero_when_closed():
    rv = review(action="hold", level=None)
    closed = cf.price_review(rv, pkg(), trade(realised(2.0)), None)
    assert closed["state"] == "not_a_call" and closed["outcome"]["delta_r"] == 0.0
    assert closed["outcome"]["cf_r"] == closed["outcome"]["net_r"] and closed["outcome"]["cf_method"] == "no_path_change"
    open_ = cf.price_review(rv, pkg(), trade(None, status="open", pnl=None, closed_at=None), None)
    assert open_["state"] == "not_a_call" and open_["outcome"] is None


def test_net_r_uses_the_initial_stop_as_the_r_basis():
    # trades.stop_loss holds the TRAILED stop (105 here); the package's initial 1R (101) must be the basis
    r = cf.price_review(review(action="hold", level=None), pkg(), trade(2.0), None)
    assert abs(r["outcome"]["net_r"] - (2.0 - 0.02)) < 1e-9


def test_append_outcomes_is_idempotent(tmp_path):
    b = bars((99.0, 99.7, 98.5, 99.0), (98.5, 98.6, 96.0, 96.0))
    res = [cf.price_review(review(), pkg(), trade(realised(4.0)), b)]
    p = tmp_path / "outcomes.jsonl"
    assert cf.append_outcomes(res, p) == 1 and cf.append_outcomes(res, p) == 0


# ---- the grader -----------------------------------------------------------------------------

def _priced(i, delta, a, b, conf=None, src="table", applied=False):
    rv = review(review_id=f"LR-20261026T00{i:02d}Z-pkg-t", applied=applied,
                apply_policy={"bound_r": 0.25, "within_bound": a, "tighten_r": None},
                shadow_policy={"bound_r": 0.5, "within_bound": b, "would_apply": b, "tighten_r": None})
    rv["recommendation"]["judgement_confidence"] = conf
    rv["recommendation"]["evidence_source"] = src
    res = {"review_id": rv["review_id"], "order_package_id": "pkg-t", "action": "tighten_sl", "applied": applied,
           "state": "priced", "reason": None, "to_date": None, "leg": "t_leg",
           "outcome": {"delta_r": delta, "replay_fidelity": "replay_matches_realised"}}
    return rv, res


def test_q1_is_indeterminate_when_thin_and_names_the_population():
    pairs = [_priced(i, -0.3, False, True) for i in range(3)] + [_priced(9, -0.1, None, None)]
    rvs, res = [p[0] for p in pairs], [p[1] for p in pairs]
    g = gr.grade(rvs, res)["q1_policy_comparison"]
    assert g["verdict"] == "INDETERMINATE" and g["population"]["discordant"] == 3
    assert g["population"]["policy_undefined_judgement_or_thin"] == 1 and g["population"]["in_comparison"] == 3


def test_q1_calls_a_winner_only_with_enough_discordant_reviews():
    pairs = [_priced(i, d, False, True) for i, d in enumerate([0.3, 0.5, 0.4, 0.6, 0.2, 0.5, 0.4, 0.3, 0.6, 0.5, 0.4])]
    g = gr.grade([p[0] for p in pairs], [p[1] for p in pairs])["q1_policy_comparison"]
    assert g["verdict"] == "B_better" and g["population"]["discordant"] == 11
    mixed = [_priced(i, d, False, True) for i, d in enumerate([1, -1] * 6)]
    assert gr.grade([p[0] for p in mixed], [p[1] for p in mixed])["q1_policy_comparison"]["verdict"] == "INDETERMINATE"


def test_calibration_is_stratified_and_brier_is_computed():
    pairs = [_priced(1, 0.4, None, None, 0.8, "judgement"), _priced(2, -0.2, None, None, 0.8, "judgement"),
             _priced(3, 0.1, True, True, 0.5, "table")]
    c = gr.grade([p[0] for p in pairs], [p[1] for p in pairs])["calibration_by_evidence_source"]
    assert set(c) == {"judgement", "table"}
    assert c["judgement"]["n"] == 2 and abs(c["judgement"]["brier"] - ((0.2 ** 2 + 0.8 ** 2) / 2)) < 1e-4
    assert c["judgement"]["verdict"].startswith("INDETERMINATE")


def test_population_counts_and_reasons_and_touched():
    rvs = [review(review_id=f"LR-20261026T00{i:02d}Z-pkg-t") for i in range(3)]
    res = [{"review_id": rvs[0]["review_id"], "order_package_id": "pkg-t", "action": "tighten_sl", "applied": True,
            "state": "could_not_price", "reason": "trade_open", "to_date": None, "leg": "t"},
           {"review_id": rvs[1]["review_id"], "order_package_id": "pkg-t", "action": "tighten_sl", "applied": False,
            "state": "could_not_price", "reason": "no_candles", "to_date": None, "leg": "t"},
           {"review_id": rvs[2]["review_id"], "order_package_id": "pkg-t", "action": "hold", "applied": False,
            "state": "not_a_call", "reason": "no_path_change", "outcome": None, "to_date": None, "leg": "t"}]
    g = gr.grade(rvs, res)
    p = g["population"]
    assert (p["n_reviews"], p["n_packages"], p["n_altering_calls"], p["n_priced"], p["n_could_not_price"]) == (3, 1, 2, 0, 2)
    assert p["could_not_price_reasons"] == {"trade_open": 1, "no_candles": 1} and g["touched_packages"] == ["pkg-t"]
    assert "Live review" in gr.render(g, "test")


def test_alarm_needs_twenty_priced_applies():
    pairs = [_priced(i, -0.2, True, True, applied=True) for i in range(19)]
    g = gr.grade([p[0] for p in pairs], [p[1] for p in pairs])
    assert g["applied_alarm"]["proposes_recommend_mode"] is False
    pairs += [_priced(40, -0.2, True, True, applied=True)]
    g = gr.grade([p[0] for p in pairs], [p[1] for p in pairs])
    assert g["applied_alarm"]["proposes_recommend_mode"] is True


# ---- LTR-ALL-ACTIONS: every action class is graded hold-vs-action (MD-LIVE-TRADE-ACTIONS) -----------------

_RUN = ((99.0, 99.7, 98.5, 99.0), (98.5, 98.6, 96.0, 96.0))   # opens 99.0 (+1R), runs to the 96 target (+4R)


def _act(action, applied=False, **rec):
    rv = review(action=action, level=rec.pop("level", None), applied=applied)
    rv["recommendation"].update(rec)
    return cf.price_review(rv, pkg(), trade(realised(4.0)), bars(*_RUN))


def _cost():
    return 0.02 + _slip_r()


def test_every_new_action_class_is_altering_and_paired():
    for a in ("close", "partial_close", "move_tp", "widen_sl", "change_size", "add_entry"):
        assert a in cf.ALTERING and a in cf.PAIRED
    assert "tighten_sl" not in cf.PAIRED                       # the tighten method is unchanged


def test_close_is_priced_against_holding():
    r = _act("close")
    assert r["state"] == "priced", r
    o = r["outcome"]
    assert o["cf_method"] == "paired_replay_v1:close" and o["replay_fidelity"] == "replay_matches_realised"
    assert abs(o["delta_r"] - (1.0 - 4.0)) < 1e-6              # closing at 99.0 gave up the run to 96
    assert abs(o["rec_r"] - (o["cf_r"] + o["delta_r"])) < 1e-9
    assert chk.row_problems(o, "outcomes", chk.json.loads(chk.SCHEMA.read_text())) == []


def test_partial_close_scales_by_the_fraction():
    assert abs(_act("partial_close", size_fraction=0.5)["outcome"]["delta_r"] - (-1.5)) < 1e-6


def test_move_tp_replays_the_new_target():
    assert abs(_act("move_tp", level=98.0)["outcome"]["delta_r"] - (2.0 - 4.0)) < 1e-6


def test_widen_sl_that_is_never_reached_changes_nothing():
    assert abs(_act("widen_sl", level=102.0)["outcome"]["delta_r"]) < 1e-9


def test_size_up_rides_the_hold_path_and_pays_a_round_trip():
    d2 = _act("change_size", size_multiplier=2.0)["outcome"]["delta_r"]
    assert abs(d2 - (3.0 - _cost())) < 1e-6
    d_add = _act("add_entry", size_fraction=0.5)["outcome"]["delta_r"]
    assert abs(d_add - (0.5 * 3.0 - 0.5 * _cost())) < 1e-6


def test_size_down_is_a_partial_close():
    assert abs(_act("change_size", size_multiplier=0.5)["outcome"]["delta_r"] - (-1.5)) < 1e-6


def test_a_trade_action_without_its_target_is_named_not_priced():
    assert _act("move_tp")["reason"] == "move_tp_level_missing"
    assert _act("partial_close")["reason"] == "partial_close_size_fraction_missing"
    assert _act("change_size")["reason"] == "change_size_size_multiplier_missing"


def test_applied_close_uses_the_hold_replay_as_counterfactual():
    o = _act("close", applied=True)["outcome"]
    assert o["replay_fidelity"] == "unvalidated" and abs(o["delta_r"] + 3.0) < 1e-6


def test_every_new_class_gets_its_own_use_rule_and_calibration():
    rows = []
    for i, a in enumerate(("close", "move_tp")):
        rv = review(action=a, level=98.0 if a == "move_tp" else None)
        rv["review_id"] = f"LR-20261026T0000Z-pkg-{i}"
        rv["recommendation"].update(judgement_confidence=0.7, evidence_source="judgement")
        rows.append(rv)
    res = [cf.price_review(rv, pkg(), trade(realised(4.0)), bars(*_RUN)) for rv in rows]
    g = gr.grade(rows, res)
    assert set(g["use_rules"]) >= {"close", "partial_close", "move_tp", "widen_sl", "change_size", "add_entry"}
    assert g["use_rules"]["close"]["n"] == 1 and g["use_rules"]["close"]["verdict"].startswith("HOLD_SCOPE")
    assert "close/judgement" in g["calibration"] and "move_tp/judgement" in g["calibration"]
