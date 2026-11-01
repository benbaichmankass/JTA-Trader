"""CF-C1-HARNESS-HOOK: the harness grades each trade on the counterfactual arms (schema cf_trade/1) without changing any
pre-existing output. Golden = the emit file of scripts/backtest_trend.py on origin/main BEFORE this change, for the fixed
synthetic run below (tests/data/cf_c1_trend_fixture.csv, 41 trades)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_harness as ch  # noqa: E402

FIX = REPO / "tests" / "data" / "cf_c1_trend_fixture.csv"
GOLDEN = REPO / "tests" / "data" / "cf_c1_trend_emit_golden.jsonl"
ARGS = ["--data", str(FIX), "--timeframe", "1h", "--symbol", "BTCUSDT"]
KEYS = {"schema", "grader_schema_version", "trade_key", "status", "reason", "path", "cost", "arms", "random_control",
        "post_exit", "fidelity", "provenance"}


def _run(tmp_path, *flags):
    out = tmp_path / "e.jsonl"
    subprocess.run([sys.executable, str(REPO / "scripts/backtest_trend.py"), *ARGS, "--emit-trades", str(out), *flags],
                   check=True, capture_output=True, cwd=REPO)
    return out


def test_default_run_is_byte_identical_to_pre_change_output(tmp_path):
    assert _run(tmp_path).read_bytes() == GOLDEN.read_bytes()


def test_cf_only_adds_the_cf_key_and_every_row_matches_the_schema(tmp_path):
    rows = [json.loads(ln) for ln in _run(tmp_path, "--cf").read_text().splitlines()]
    gold = [json.loads(ln) for ln in GOLDEN.read_text().splitlines()]
    assert len(rows) == len(gold) == 41
    for r, g in zip(rows, gold):
        assert {k: v for k, v in r.items() if k != "cf"} == g
        c = r["cf"]
        assert KEYS <= set(c) and c["schema"] == "cf_trade/1" and c["grader_schema_version"] == 2
        assert c["status"] == "graded" and len(c["trade_key"]) == 40
        assert c["trade_key"] == ch.trade_key(r["strategy"], r["symbol"], r["entry_time"], r["direction"], r["sl"])
        assert c["arms"]["original_brackets"]["net_r"] is not None and len(c["arms"]["alt_brackets"]) == 19
        assert {"verdict", "r_diff", "resolved"} == set(c["post_exit"]["verdict"])
        assert c["fidelity"]["actual_net_r"] == pytest.approx(r["net_r"], abs=1e-4)   # quoted against the harness net_r
        assert c["fidelity"]["abs_gap_r"] < 0.05                                       # measured max 0.0122R on this run
        assert c["cost"] == {"basis": "full", "provenance": "ESTIMATED"} and c["provenance"] == "ESTIMATED"


def test_ungradable_rows_are_recorded_not_dropped():
    row = {"strategy": "s", "symbol": "X", "entry_time": "2024-01-01 00:00:00+00:00", "exit_time": "2024-01-02 00:00:00+00:00",
           "direction": "long", "entry": 100.0, "sl": 98.0, "net_r": 1.0}
    assert ch.cf_fields(row, [])["reason"] == "no_bars"
    assert ch.cf_fields({**row, "sl": 100.0}, [])["reason"] == "geometry_missing"
    assert ch.cf_fields({**row, "net_r": None}, [{"time": 0}])["reason"] == "row_incomplete"
    assert ch.cf_fields(row, [])["status"] == "could_not_grade"


def test_cf_summary_none_without_cf_and_counts_ungraded(tmp_path):
    assert ch.cf_summary([{"net_r": 1.0}]) is None
    rows = [json.loads(ln) for ln in _run(tmp_path, "--cf").read_text().splitlines()]
    rows.append({"net_r": 0.0, "cf": {"status": "could_not_grade", "reason": "no_bars"}})
    s = ch.cf_summary(rows)
    assert (s["n_rows"], s["n_graded"], s["n_could_not_grade"]) == (42, 41, 1)
    assert s["original_brackets"]["n"] == 41 and len(s["original_brackets"]["ci95_mean"]) == 2
    assert "sl1x_tp3R" in s["alt_brackets_mean_by_cell"] or s["alt_brackets_mean_by_cell"]
    assert s["fidelity_abs_gap_r"]["max"] < 0.05


def test_stage0_wrapper_appends_cf_for_trend_and_flags_no_cf(tmp_path):
    import harness_stage0 as h0
    cfg = h0.build_cfg("trend", "BTCUSDT", "1h", {})
    r = h0.run_cell("c", cfg, FIX, "1h", [], None, None, tmp_path, folds=3, timeout_s=300, cf=True)
    assert r["state"] == "measured" and "--cf" in r["argv"] and r["cf_summary"]["n_graded"] == r["summary"]["n"]
    r0 = h0.run_cell("c0", cfg, FIX, "1h", [], None, None, tmp_path, folds=3, timeout_s=300, cf=False)
    assert "--cf" not in r0["argv"] and "cf_summary" not in r0
    assert r0["summary"] == r["summary"]          # grade inputs unchanged by the grading
