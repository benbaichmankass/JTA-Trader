"""scripts/ml/p1_costnet_grade.py helpers: (a) recompute on a re-chosen eval
population, the frozen strategy list, the deflated (b) percentile and the
paper / strategy-filtered (e) basis counts (RQ-20261119-3e98-01)."""
from __future__ import annotations

import sqlite3

import pytest

from scripts.ml import p1_costnet_grade as g


def _rp(pairs, basis="realized"):
    return [({"label_cost_basis": basis}, p) for p in pairs]


def test_recompute_matches_cost_gate_semantics():
    # take-all mean = (1 - 1 + 2 - 2) / 4 = 0; taken = {+1, +2} -> value 3/4
    res = g._recompute_cost_gate(_rp([(True, 1.0), (False, -1.0), (True, 2.0), (False, -2.0)]))
    assert res["passed"] is True
    assert res["value_r"] == pytest.approx(0.75)
    assert res["take_all_r"] == pytest.approx(0.0)
    assert res["matched_random_r"] == pytest.approx(0.0)
    assert res["n_taken"] == 2


def test_recompute_fails_when_take_none_is_best():
    res = g._recompute_cost_gate(_rp([(True, -1.0), (False, -1.0)]))
    assert res["passed"] is False
    assert res["reason"].startswith("does_not_beat_take_none")


def test_recompute_refuses_gross_rows():
    res = g._recompute_cost_gate(_rp([(True, 1.0)], basis="gross"))
    assert res["passed"] is False and res["reason"].startswith("eval_not_cost_net")


def test_recompute_empty():
    assert g._recompute_cost_gate([])["reason"] == "no_scored_eval_rows"


def test_load_strategies_formats(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("# frozen 2026-11-19\ntrend_donchian\n\nsqueeze_breakout_4h  # 4h\n")
    assert g._load_strategies(str(p)) == {"trend_donchian", "squeeze_breakout_4h"}
    y = tmp_path / "s.yaml"
    y.write_text("- a\n- b\n")
    assert g._load_strategies(str(y)) == {"a", "b"}
    assert g._load_strategies(None) is None


def test_bootstrap_deflated_percentile_is_lower():
    pairs = [(i % 3 == 0, (-1.0) ** i * (i % 7) / 3.0) for i in range(300)]
    std = g._bootstrap_lb(pairs, n_boot=2000)
    defl = g._bootstrap_lb(pairs, n_boot=2000, lb_pct=0.833)
    assert defl["lb95"] < std["lb95"]
    assert defl["ub95"] > std["ub95"]
    assert std["lb_pct"] == 2.5 and defl["lb_pct"] == 0.833


def _journal(path):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, timestamp TEXT, "
        "status TEXT, pnl REAL, pnl_percent REAL, is_backtest INT, is_demo INT, account_class TEXT, "
        "strategy_name TEXT)")
    rows = [
        (0, "BTCUSDT", "buy", "2026-01-01T01:00:00+00:00", "closed", 1.0, 0.01, 0, 0, "real_money", "vwap"),
        (1, "BTCUSDT", "buy", "2026-01-01T02:00:00+00:00", "closed", 1.0, 0.01, 0, 1, "paper", "trend_donchian"),
        (2, "BTCUSDT", "buy", "2026-01-01T03:00:00+00:00", "closed", -1.0, -0.01, 0, 1, "paper", "vwap"),
    ]
    conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_basis_counts_split_real_paper_and_filter(tmp_path):
    db = tmp_path / "j.db"
    _journal(db)
    real = g._journal_basis_counts(db, ["BTCUSDT"])
    paper = g._journal_basis_counts(db, ["BTCUSDT"], paper=True)
    paper_f = g._journal_basis_counts(db, ["BTCUSDT"], paper=True, strategies={"trend_donchian"})
    assert sum(real["BTCUSDT"].values()) == 1
    assert sum(paper["BTCUSDT"].values()) == 2
    assert sum(paper_f["BTCUSDT"].values()) == 1
