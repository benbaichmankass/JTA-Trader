"""Pure-function tests for the same-symbol head-to-head driver (the registered rule + the metric)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import same_symbol_head_to_head as h  # noqa: E402

T0 = datetime(2025, 3, 1, tzinfo=timezone.utc)


def trade(day, hold_days, pnl, risk=100.0, entry=100.0):
    # qty*|entry-sl| == risk
    return {"entry_ts": T0 + timedelta(days=day), "exit_ts": T0 + timedelta(days=day + hold_days),
            "qty": risk / 5.0, "entry": entry, "sl": entry - 5.0, "pnl": pnl}


def test_metric_net_r_and_capital_days():
    m = h.metric_from_trades([trade(0, 2, 200.0), trade(5, 3, -100.0)], "2025-01-01")
    assert m["n_oos"] == 2 and m["net_r"] == 1.0 and m["capital_days"] == 5.0
    assert m["net_r_per_capital_day"] == 0.2


def test_metric_excludes_pre_oos_and_zero_risk():
    m = h.metric_from_trades([trade(-100, 1, 999.0), dict(trade(0, 1, 5.0), sl=100.0)], "2025-03-01")
    assert m["n_oos"] == 0 and m["n_skipped_zero_risk"] == 1 and m["net_r_per_capital_day"] is None


def arm(n, v):
    return {"n_oos": n, "net_r_per_capital_day": v}


def test_together_must_strictly_beat_best_single():
    arms = {"solo:a": arm(30, 0.10), "solo:b": arm(30, 0.05), "together": arm(30, 0.10)}
    d = h.decide(arms, 20)
    assert d["verdict"] == "pass" and d["winner"] == "solo:a" and d["keep_legs"] == "a"
    arms["together"] = arm(30, 0.11)
    assert h.decide(arms, 20)["winner"] == "together"


def test_starved_arm_is_indeterminate_not_a_win():
    arms = {"solo:a": arm(30, 0.10), "solo:b": arm(3, 9.9), "together": arm(30, 0.2)}
    d = h.decide(arms, 20)
    assert d["verdict"] == "indeterminate" and d["winner"] is None and "solo:b" in d["reason"]


def test_none_metric_is_indeterminate():
    arms = {"solo:a": arm(30, 0.1), "solo:b": arm(30, None), "together": arm(30, 0.2)}
    assert h.decide(arms, 20)["verdict"] == "indeterminate"


def test_needs_together_and_two_solos():
    assert h.decide({"solo:a": arm(30, 1.0)}, 20)["verdict"] == "indeterminate"


def test_apply_cost_policy_sets_the_module_globals():
    bs = h._load_bs()
    bs.SLIPPAGE_BPS_ROUNDTRIP = 0.0
    pol = h.apply_cost_policy(bs, "ETHUSDT")
    assert bs.SLIPPAGE_BPS_ROUNDTRIP == pol["slippage_bps_roundtrip"] > 0
    assert bs.FUNDING_BPS_PER_WINDOW == pol["funding_bps_per_window"]


def test_xrp_legs_registered_in_roster():
    bs = h._load_bs()
    assert {"trend_donchian_xrp_4h", "xrp_pullback_2h", "trend_donchian_eth_4h", "trend_donchian_eth_prop"} <= set(bs.ROSTER)
