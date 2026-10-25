"""Fixture tests for scripts/research/news_veto_eval.py (RQ-20261009-902, Arm A join + grading)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import news_veto_eval as m  # noqa: E402


def _pkg(pid, adj, dec="neutral", strat="s", news=True):
    meta = {"news": {"adjustment": adj, "decision": dec, "item_count": 1}} if news else {}
    return {"order_package_id": pid, "strategy_name": strat, "created_at": f"2026-10-01T00:{pid[-2:]}:00+00:00",
            "meta": json.dumps(meta)}


def _trade(pid, pnl, status="closed", cost="estimate", symbol="BTCUSDT"):
    return {"order_package_id": pid, "status": status, "symbol": symbol, "direction": "long", "is_backtest": 0,
            "entry_price": 100.0, "stop_loss": 99.0, "position_size": 1.0, "pnl": pnl, "cost_source": cost,
            "fee_taker_usd": 0.0, "strategy_name": "s", "account_id": "a", "account_class": "paper"}


def test_spearman_perfect_and_constant():
    r = m.spearman_one_sided([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6], perms=500)
    assert r["rho"] == 1.0 and r["p_one_sided"] < 0.05
    assert m.spearman_one_sided([0, 0, 0, 0], [1, 2, 3, 4])["rho"] is None


def test_join_filters_and_drop_counts():
    pk = [_pkg("p01", 0.1), _pkg("p02", 0.2), _pkg("p03", 0.0, news=False), _pkg("p04", 0.3), _pkg("p05", 0.4)]
    tr = [_trade("p01", 1.0), _trade("p02", 1.0, status="open"), _trade("p03", 1.0),
          _trade("p04", 1.0, cost=None), _trade("p05", 1.0), _trade("p05", 9.0)]  # p05 duplicated -> once
    b = m.build_taken_rows(pk, tr)
    assert [r["order_package_id"] for r in b["rows"]] == ["p01", "p05"]
    assert b["dropped"]["not_closed"] == 1 and b["dropped"]["uncosted"] == 1
    assert b["packages_with_news_stamp"] == 4


def test_slippage_is_deducted_beyond_journal_cost():
    r = m.full_cost_net_r(_trade("p01", 1.0))
    assert r["net_R"] < r["net_R_journal_cost"] == 1.0


def _rows(adj_r):
    return [{"adjustment": a, "net_R": r, "decision": d, "strategy": "s", "symbol": "X", "direction": "long",
             "created_at": f"2026-10-01T00:{i:02d}", "account_class": "paper"}
            for i, (a, r, d) in enumerate(adj_r)]


def test_arm_a_insufficient_lead_and_graded():
    assert m.grade_arm_a(_rows([(0.1, 1.0, "boost")] * 10))["verdict"] == "INSUFFICIENT_BASE"
    lead = _rows([(i / 40, i / 40, "neutral") for i in range(30)])
    assert m.grade_arm_a(lead)["verdict"] == "LEAD_ONLY"
    good = _rows([(i / 100, i / 100, "boost" if i % 7 == 0 else "neutral") for i in range(60)])
    assert m.grade_arm_a(good)["verdict"] in {"PASS", "FAIL"}
    anti = _rows([(i / 100, -i / 100, "neutral") for i in range(60)])
    assert m.grade_arm_a(anti)["verdict"] == "FAIL"


def test_reduce_exceeding_boost_fails_even_with_positive_ic():
    rows = _rows([(i / 100, i / 100, "neutral") for i in range(60)])
    rows += _rows([(0.3, 5.0, "reduce")] * 3) + _rows([(0.35, -5.0, "boost")] * 3)
    assert m.grade_arm_a(rows)["verdict"] == "FAIL"


def test_implausible_r_excluded_and_reported():
    rows = _rows([(0.0, 0.1, "neutral")] * 30 + [(0.0, -2666.0, "neutral")])
    a = m.grade_arm_a(rows)
    assert a["n_distinct_taken_packages"] == 30
    assert a["implausible_risk_basis_excluded"]["n"] == 1


def test_arm_b_never_graded():
    b = m.grade_arm_b(13, "2026-06-11", "2026-10-12", 5)
    assert b["verdict"] == "UNDERPOWERED" and b["grade_attempted"] is False
    assert b["floor_reachable_upper_bound_date"] > "2026-10-12"
    assert m.grade_arm_b(None, None, None, None)["read_state"] == "could_not_look"


def test_g1_read_matches_registered_rule():
    assert m.g1_read({"verdict": "FAIL"}, {"verdict": "UNDERPOWERED"}) == "RETIRE_OR_REPLACE"
    assert m.g1_read({"verdict": "PASS"}, {"verdict": "UNDERPOWERED"}) == "OPEN"
    assert m.g1_read({"verdict": "PASS"}, {"verdict": "PASS"}) == "PASS"
    assert m.g1_read({"verdict": "LEAD_ONLY"}, {"verdict": "UNDERPOWERED"}) == "OPEN"
