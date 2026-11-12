"""CF-B2 / CF-D2 / CF-D3: the live backfill, the option pricing and the book sim (pure parts; no network, no VM)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))
import cf_booksim as bs  # noqa: E402
import cf_bulk_live as bl  # noqa: E402
import cf_core  # noqa: E402
import cf_ltr_option_pricing as op  # noqa: E402

T0 = 1_792_000_000


def _bars(path, dur=300):
    return [{"time": T0 + i * dur, "open": o, "high": h, "low": lo, "close": c, "dur": dur} for i, (o, h, lo, c) in enumerate(path)]


def test_fetch_pages_pages_until_short_page_and_records_failures():
    calls = []

    def fetch(path):
        calls.append(path)
        off = int(path.rsplit("offset=", 1)[1])
        if off == 100:
            raise RuntimeError("boom")
        return [{"i": off + k} for k in range(100 if off < 200 else 30)]
    rows, failed = bl.fetch_pages("order_packages", 100, retries=1, fetch=fetch)
    assert failed == [100] and len(rows) == 100 + 30                # the failed page is named, not silently skipped
    assert len(calls) == 3


def test_classify_reasons():
    pk = {"order_package_id": "p", "strategy_name": "x", "symbol": "BTCUSDT"}
    leg = {"status": "closed", "closed_at": "2026-01-01T00:00:00Z", "entry_price": 1.0, "exit_price": 2.0}
    assert bl.classify(pk, [leg])[1] is None
    assert bl.classify(dict(pk, strategy_name="pairs_a"), [leg])[1] == "pairs_two_leg"
    assert bl.classify(pk, [dict(leg, status="rejected")])[1] == "no_filled_leg"
    assert bl.classify(pk, [dict(leg, exit_price=None)])[1] == "legs_not_closed"
    assert bl.classify(dict(pk, symbol="SPY"), [leg])[1] == "no_bars_non_crypto"


def test_fidelity_rule_and_indeterminate_below_min_n():
    recs = [{"strategy": "a", "fidelity": {"abs_gap_r": 0.01}} for _ in range(12)]
    f = bl.fidelity(recs)
    assert f["overall"]["verdict"] == "PASS" and f["per_leg"]["a"]["frac_within_tol"] == 1.0
    bad = [{"strategy": "b", "fidelity": {"abs_gap_r": 0.5}} for _ in range(12)]
    assert bl.fidelity(bad)["overall"]["verdict"] == "FAIL"
    assert bl.fidelity(recs[:3])["overall"]["verdict"] == "INDETERMINATE"
    assert bl.fidelity([{"strategy": "c", "fidelity": {"abs_gap_r": None}}])["overall"]["n_with_gap"] == 0


def test_population_counts_closed_and_every_closed_package_is_accounted_for():
    pk = [{"order_package_id": f"p{i}", "status": s} for i, s in enumerate(["closed", "closed", "orphaned", "rejected"])]
    tr = [{"order_package_id": "p0", "account_id": "a", "status": "closed"}]
    pop = bl.population(pk, tr)
    assert pop["closed_n"] == 2 and pop["by_status"]["orphaned"] == 1 and pop["closed_packages_by_account_with_a_closed_leg"] == {"a": 1}


def _review(open_r=1.5):
    return {"review_id": "LR-1", "order_package_id": "p", "leg": "x", "reviewed_at": "2026-10-10T00:00:00Z",
            "state": {"sl": 98.0, "tp": 106.0, "open_r": open_r}}


_PKG = {"order_package_id": "p", "direction": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0, "symbol": "BTCUSDT", "meta": {}}


def test_option_grid_is_state_derived_and_marks_inapplicable_cells():
    rv = _review(open_r=1.5)                                           # long, r=2, mark=103, stop 98
    assert op.option_for("close", rv, _PKG)[0] == {"action": "close"}
    assert op.option_for("partial_close_50", rv, _PKG)[0]["size_fraction"] == 0.5
    assert op.option_for("tighten_trail_1r", rv, _PKG)[0]["level"] == 101.0          # mark - 1R
    assert op.option_for("tighten_be", rv, _PKG)[0]["level"] == 100.0
    assert op.option_for("move_tp_extend_1r", rv, _PKG)[0]["level"] == 108.0
    assert op.option_for("move_tp_pullin_half", rv, _PKG)[0]["level"] == 104.5
    assert op.option_for("widen_sl_half_r", rv, _PKG)[0]["level"] == 97.0
    losing = _review(open_r=-0.5)                                      # mark 99: no break-even, trail 1R below mark is not tighter than stop
    assert op.option_for("tighten_be", losing, _PKG) == (None, "not_applicable:be_not_tighter_or_not_in_profit")
    assert op.option_for("tighten_trail_1r", losing, _PKG)[1] == "not_applicable:trail_not_tighter"
    assert op.option_for("close", {"review_id": "x", "state": {}}, _PKG) == (None, "review_state_missing")
    assert op.option_for("tighten_be", {"review_id": "x", "state": {}}, _PKG) == (None, "review_state_missing")


def test_option_pricing_without_a_package_is_a_recorded_state_not_a_drop():
    row = op.price_class("close", _review(), None, None, None)
    assert row["option_state"] == "could_not_price" and row["reason"] == "no_package_row"


def test_summary_point_estimate_sits_inside_its_ci_and_states_sum_to_the_grid():
    rows = [{"option_class": "close", "option_state": "priced", "delta_r": 0.1 * (i % 5), "order_package_id": f"p{i % 8}", "replay_fidelity": "replay_matches_realised"} for i in range(40)]
    rows += [{"option_class": "close", "option_state": "could_not_price", "reason": "no_candles", "order_package_id": "z"}]
    s = op.summarize(rows)["classes"]["close"]
    assert sum(s["states"].values()) == 41 and s["reaches_min_n"] is True
    lo, hi = s["priced"]["ci95"]
    assert lo <= s["priced"]["mean_delta_r"] <= hi


def test_engine_widen_stop_loosens_where_set_stop_only_tightens():
    bars = _bars([(100, 100.5, 99.5, 100.2), (100.2, 100.4, 98.7, 99.0), (99.0, 99.2, 98.0, 98.2), (98.2, 98.4, 96.0, 96.5)])
    kw = dict(side="long", entry_ref=100.0, r_dist=2.0, t_entry=T0, stop0=99.0, tp=110.0)
    tight = cf_core.simulate(bars, actions=[{"ts": T0, "kind": "set_stop", "level": 97.0}], **kw)
    wide = cf_core.simulate(bars, actions=[{"ts": T0, "kind": "widen_stop", "level": 97.0}], **kw)
    assert tight["fills"][0]["px"] == 99.0                              # set_stop refused to loosen: the 99 stop in force fills
    assert wide["fills"][0]["px"] == 97.0 and wide["fills"][0]["ts"] > tight["fills"][0]["ts"]


def _ctx():
    path = [(100, 100.5, 99.8, 100.4)] * 3 + [(104, 104.5, 103.5, 104.0)] * 3 + [(104, 104.2, 96, 97)] * 3
    return {"id": "p", "strategy": "x", "symbol": "BTCUSDT", "side": "long", "entry_ref": 100.0, "stop0": 98.0, "tp0": 112.0, "r": 2.0, "trail": None,
            "entry_fill": 100.0, "t_entry": T0, "t_close": T0 + 9 * 300, "H": 9 * 300.0, "bars": _bars(path),
            "cm": {"fee_bps": 0.0, "slip_exit_bps": 0.0, "fund_bps_window": 0.0, "fee_source": "t"}, "confidence": 1.0, "accounts": {"a": 1.0}}


def test_book_actions_are_causal_and_registered():
    c = _ctx()
    ta = bs.trigger_time(c)
    assert ta == T0 + 0.25 * 9 * 300
    b = bs._bar_at(c["bars"], ta)
    assert bs.action_for("tighten_sl", c, ta)["level"] == b["open"] - c["r"]
    assert bs.action_for("widen_sl", c, ta)["kind"] == "widen_stop" and bs.action_for("widen_sl", c, ta)["level"] == 97.0
    assert bs.action_for("close", c, ta)["frac"] == 1.0 and bs.action_for("partial_close", c, ta)["frac"] == 0.5
    assert bs.action_for("move_tp", dict(c, tp0=101.0), ta) is None       # not a pull-in: the TP in force is already nearer
    assert bs.action_for("close", c, T0 + 10 ** 7) is None                # no bar at/after ta: no action, never a guess


def test_close_beats_hold_when_the_path_later_collapses_and_hold_is_untouched():
    c = _ctx()
    hold, _ = bs.arm_outcome(c, None)
    closed, _ = bs.arm_outcome(c, bs.action_for("close", c, bs.trigger_time(c)))
    assert hold < 0 < closed or closed > hold                           # stop-out later vs exit at the 104 plateau


def test_random_trigger_never_looks_past_the_horizon():
    import random
    c = _ctx()
    rng = random.Random(1)
    ts = {bs.random_trigger(c, rng) for _ in range(200)}
    assert all(c["t_entry"] <= t < c["t_entry"] + c["H"] for t in ts)


def test_decision_requires_every_stage2_account_and_one_fail_is_a_fail():
    def acct(v):
        return {"grade": {"candidates": {cl: {"verdict": v, "label": v} for cl in bs.CLASSES}}}
    assert bs.decide({"bybit_2": acct("pass"), "bybit_portfolio": acct("pass"), "bybit_1": acct("fail")})["close"]["decision"] == "PASS"
    assert bs.decide({"bybit_2": acct("pass"), "bybit_portfolio": acct("fail"), "bybit_1": acct("pass")})["close"]["decision"] == "FAIL"
    assert bs.decide({"bybit_2": acct("pass"), "bybit_portfolio": acct("indeterminate")})["close"]["decision"] == "INDETERMINATE"


def test_book_uses_the_production_sizer_and_never_emits_balances():
    c = _ctx()
    rm, mt, _ = bs.make_sizer("bybit_2")
    out = {"p": {"hold": bs.arm_outcome(c, None)}}
    book = bs.run_book([c], out, "hold", rm=rm, market_type=mt, start=1000.0, dd_limit_pct=None)
    assert len(book) == 1 and set(book[0]) == {"entry_time", "exit_time", "net_r", "mfe_r", "order_package_id"}
    from src.core.coordinator import OrderPackage
    q = rm.position_size(OrderPackage(strategy="x", symbol="BTCUSDT", direction="long", entry=100.0, sl=98.0, tp=112.0, confidence=1.0), 1000.0,
                         market_type=mt, available_usd=1000.0, total_account_usd=1000.0)
    assert abs(book[0]["net_r"] - bs.arm_outcome(c, None)[0] * q * 2.0) < 1e-9
