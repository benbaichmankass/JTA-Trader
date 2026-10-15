"""live_vs_backtest_verdict: pure grading + the verdict.json shape the collector accepts."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]

import live_vs_backtest_verdict as v  # noqa: E402


def _row(verdict, n=16, book="realMoney"):
    return {"book": book, "leg": "x", "verdict": verdict, "r_trades": n, "live_r": -8.8, "live_percentile": 3.4}


def test_below_backtest_is_fail_measured():
    g = v.grade([_row("BELOW_BACKTEST"), _row("CONSISTENT", book="mirror")])
    assert (g["verdict"], g["read_state"], g["n"]) == ("fail", "measured", 16)


def test_consistent_is_pass_and_thin_is_indeterminate():
    assert v.grade([_row("CONSISTENT")])["verdict"] == "pass"
    assert v.grade([_row("BELOW_BACKTEST", n=2)])["verdict"] == "indeterminate"


def test_no_real_money_row_is_could_not_look():
    g = v.grade([])
    assert (g["verdict"], g["read_state"], g["n"]) == ("not_applicable", "no_data", None)


def test_unreadable_payload_writes_a_contract_verdict(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text(json.dumps({"error": "x"}))
    assert v.main(["--leg", "xrp_pullback_2h", "--recent-json", str(bad), "--out", str(tmp_path / "o")]) == 0
    d = json.loads((tmp_path / "o" / "verdict.json").read_text())
    assert d["read_state"] == "no_data" and d["verdict"] == "not_applicable" and d["n"] is None and d["population"]
