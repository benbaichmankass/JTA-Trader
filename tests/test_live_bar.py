"""The live bar (operator 2026-11-17): >= 20 confirmed-R trades, sum R > 0, one-sided 80% LCB > 0."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import live_bar as lb  # noqa: E402


def test_verdicts():
    assert lb.verdict([])["verdict"] == "no_data"
    assert lb.verdict([1.0] * 19)["verdict"] == "n_short"
    v = lb.verdict([1.0, -0.5] * 10 + [0.5])          # 21 trades, mean > 0, tight
    assert v["verdict"] == "pass" and v["n"] == 21 and v["lcb80"] > 0
    noisy = lb.verdict([3.0, -2.8] * 10)              # sum > 0 but the 80% bound is below zero
    assert noisy["sum_r"] > 0 and noisy["lcb80"] < 0 and noisy["verdict"] == "fail"
    assert lb.verdict([-1.0, 0.5] * 10)["verdict"] == "fail"


def test_only_confirmed_initial_counts_and_pools_by_leg():
    meta = {"risk_per_unit": 1.0}
    def t(i, pnl, cls, stop=99.0, pkg="p"):
        return {"id": i, "status": "closed", "pnl": pnl, "entry_price": 100.0, "stop_loss": stop, "take_profit_1": 103.0,
                "direction": "long", "qty": 1.0, "symbol": "SPY", "strategy_name": "leg_a", "account_id": cls,
                "account_class": "real_money" if cls == "live" else "paper", "order_package_id": pkg}
    trades = [t(1, 2.0, "live"), t(2, -1.0, "demo"), t(3, 5.0, "demo", pkg="nometa"), {"status": "open", "pnl": None}]
    out = lb.live_bar(trades, {"p": meta})
    leg = out["legs"]["leg_a"]
    # trade 3 has no declared initial risk -> its R basis is not declared_initial -> excluded
    assert leg["n"] == 2 and leg["verdict"] == "n_short"
    assert leg["stop_unmoved_subset"]["n"] == 2
    assert leg["pooled"]["real_money"] == 1 and leg["pooled"]["paper"] == 1
    assert abs(leg["sum_r"] - 1.0) < 1e-9


def test_a_trailed_winner_counts_but_is_not_in_the_stop_unmoved_subset():
    meta = {"risk_per_unit": 1.0}
    win = {"status": "closed", "pnl": 3.0, "entry_price": 100.0, "stop_loss": 101.5, "take_profit_1": 104.0,
           "direction": "long", "qty": 1.0, "symbol": "SPY", "strategy_name": "leg_b", "account_id": "a",
           "account_class": "paper", "order_package_id": "p"}   # stop trailed above entry: classify_r -> not confirmed_initial
    out = lb.live_bar([win], {"p": meta})["legs"]["leg_b"]
    assert out["n"] == 1 and abs(out["sum_r"] - 3.0) < 1e-9
    assert out["stop_unmoved_subset"]["n"] == 0


def test_write_latest_stamps_generated_at_and_writes_atomically(tmp_path):
    """LIVE-BAR-LADDER-FEED: the daily feed file carries generated_at (its freshness) and schema."""
    import json
    from datetime import datetime, timezone
    out = {"rule": {"min_n": 20}, "population": {"confirmed_r_trades": 0}, "legs": {}}
    p = lb.write_latest(out, tmp_path / "live_bar" / "latest.json",
                        now=datetime(2026, 11, 19, 5, 47, tzinfo=timezone.utc))
    doc = json.loads(p.read_text())
    assert doc["generated_at"] == "2026-11-19T05:47:00+00:00" and doc["schema"] == 1 and doc["legs"] == {}
    assert not list((tmp_path / "live_bar").glob("*.tmp"))
    assert out.get("generated_at") is None  # the caller's dict is not mutated


def test_cli_write_uses_saved_inputs(tmp_path):
    import json
    trades = tmp_path / "t.json"
    pk = tmp_path / "p.json"
    trades.write_text("[]")
    pk.write_text("[]")
    dest = tmp_path / "latest.json"
    assert lb.main(["--trades", str(trades), "--packages", str(pk), "--json", "--write", str(dest)]) == 0
    doc = json.loads(dest.read_text())
    assert doc["population"]["trades_read"] == 0 and "generated_at" in doc
