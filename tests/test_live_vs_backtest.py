"""scripts/research/live_vs_backtest.py -- the live-vs-backtest first step."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops")):
    if p not in sys.path:
        sys.path.insert(0, p)

import live_vs_backtest as lvb  # noqa: E402

# Backtest corpus: mean +0.5R, sd ~1; 60 trades, deterministic.
BT = [(-1.0 if i % 3 == 0 else 1.0) + (0.0 if i % 2 else 0.5) for i in range(60)]


def _root(tmp_path, leg="leg_a", xs=BT, with_run=True):
    (tmp_path / "comms/strategy_evidence/runs").mkdir(parents=True)
    run = "comms/strategy_evidence/runs/leg_a__trades.jsonl"
    if with_run:
        (tmp_path / run).write_text("\n".join(json.dumps({"net_r": x}) for x in xs))
    (tmp_path / f"comms/strategy_evidence/{leg}.json").write_text(
        json.dumps({"strategy": leg, "source_run": run, "fidelity": "faithful"}))
    return tmp_path


def _row(total_r, n=20):
    return {"name": "leg_a", "trades": n, "rTradeCount": n, "totalR": total_r,
            "totalPnlMeasured": 1.0, "pnlCoverage": 1.0}


def test_verdict_flips_with_live_r(tmp_path):
    root = _root(tmp_path)
    res = {r: lvb.check_leg("leg_a", "realMoney", _row(r), root, draws=4000)["verdict"]
           for r in (-30.0, 10.0, 80.0)}
    assert res == {-30.0: lvb.BELOW, 10.0: lvb.CONSISTENT, 80.0: lvb.ABOVE}


def test_band_and_percentile_are_reported(tmp_path):
    r = lvb.check_leg("leg_a", "realMoney", _row(10.0), _root(tmp_path), draws=4000)
    assert r["p5"] < r["p50"] < r["p95"] and r["n"] == 20
    assert 5.0 <= r["live_percentile"] <= 95.0 and r["backtest_n"] == 60


def test_deterministic_for_fixed_seed(tmp_path):
    root = _root(tmp_path)
    a = lvb.check_leg("leg_a", "realMoney", _row(3.0), root, draws=2000)
    b = lvb.check_leg("leg_a", "realMoney", _row(3.0), root, draws=2000)
    assert a == b


def test_no_backtest_record_and_missing_source_run(tmp_path):
    assert lvb.check_leg("nope", "realMoney", _row(1.0), tmp_path)["verdict"] == lvb.NO_BACKTEST
    root = _root(tmp_path, with_run=False)
    r = lvb.check_leg("leg_a", "realMoney", _row(1.0), root)
    assert r["verdict"] == lvb.NO_BACKTEST and "not a committed file" in r["why"]


def test_too_few_backtest_rows_is_no_backtest(tmp_path):
    root = _root(tmp_path, xs=[1.0])
    assert lvb.check_leg("leg_a", "realMoney", _row(1.0), root)["verdict"] == lvb.NO_BACKTEST


def test_no_live_trades_is_not_a_verdict(tmp_path):
    root = _root(tmp_path)
    assert lvb.check_leg("leg_a", "mirror", None, root)["verdict"] == lvb.NO_LIVE
    assert lvb.check_leg("leg_a", "mirror", {"rTradeCount": 0, "totalR": None}, root)["verdict"] == lvb.NO_LIVE


def test_thin_n_is_insufficient_and_flags_worse_than_worst(tmp_path):
    root = _root(tmp_path)
    r = lvb.check_leg("leg_a", "realMoney", _row(-1.5, n=1), root, draws=2000)
    assert r["verdict"] == lvb.THIN and r["worse_than_worst_bt_trade"] is True
    r = lvb.check_leg("leg_a", "realMoney", _row(-0.5, n=1), root, draws=2000)
    assert r["verdict"] == lvb.THIN and r["worse_than_worst_bt_trade"] is False


def test_run_reads_both_books_from_payload(tmp_path):
    root = _root(tmp_path)
    side = {"perStrategy": {"leg_a": {"last": {"perStrategy": [_row(-30.0)]}}}}
    recent = {"realMoney": side, "mirror": {"perStrategy": {}}}
    rows = lvb.run(recent, [("acct", "leg_a")], root, draws=2000)
    assert [(r["book"], r["verdict"]) for r in rows] == [("realMoney", lvb.BELOW),
                                                         ("mirror", lvb.NO_LIVE)]


def test_real_corpus_loads_for_stage2_legs():
    """Reads the repo's own committed evidence (not a fixture)."""
    bt = lvb.load_backtest_r("xrp_pullback_2h")
    assert len(bt["xs"]) >= 30 and bt["why"] is None
