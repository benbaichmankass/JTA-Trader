"""CF-INSIGHTS: arm_set="extended" adds arms and context without touching the standard record; every arm's R is at constant money risk."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))
import cf_core  # noqa: E402
import cf_harness  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

T0 = 1_792_000_000
# long, entry 100, stop 99 => 1 R = 1.00 price; ATR 0.5
PKG = {"order_package_id": "pkg-x", "strategy_name": "s", "symbol": "ADAUSDT", "direction": "long", "entry": 100.0, "sl": 99.0, "tp": 110.0,
       "exit_plan": '{"stop": {"price": 99.0}}', "meta": {"atr": 0.5, "trail_mult": 100.0}}     # trail so wide it never binds


def _bars(closes):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else 100.0
        out.append({"time": T0 + 900 * i, "open": o, "high": max(o, c) + 0.05, "low": min(o, c) - 0.05, "close": c, "volume": 1.0, "dur": 900})
    return out


def _leg(exit_px):
    return [{"id": 1, "account_id": "a", "account_class": "paper", "status": "closed", "position_size": 1.0, "entry_price": 100.0, "exit_price": exit_px,
             "exit_reason": "x", "pnl": exit_px - 100.0, "timestamp": lrc._iso(T0), "closed_at": lrc._iso(T0 + 900 * 10), "fee_taker_usd": 0.0, "cost_source": None}]


def _grade(closes, **kw):
    return cf_core.grade_package(PKG, _leg(closes[-1]), _bars(closes), [], [], {}, {}, n_random=3, **kw)


def _arm(rec, aid, key="arms"):
    return next(a for a in rec[key] if a["arm_id"] == aid)


def test_arm_r_is_at_constant_money_risk_not_in_the_original_unit():
    up = [100.0, 100.5, 101.0, 102.0, 103.5, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0]     # +4 original R
    rec = _grade(up)
    wide_tp = _arm(rec, "alt_sl1.5x_tp2R")           # stop 1.5 away, TP 2 R of ITS OWN distance = 3.0 away
    assert wide_tp["gross_r"] == 2.0                  # 3.0 price / 1.5 own risk: 2R of the SAME dollars risked, not 3 original R
    down = [100.0, 99.8, 99.0, 98.0, 97.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0, 96.0]
    stopped = _arm(_grade(down), "alt_sl1.5x_tp2R")   # stop 1.5 away exits at -1.5 price = exactly -1 of its own R, not -1.5
    assert round(stopped["gross_r"], 3) == -1.0


def test_standard_record_is_unchanged_and_extended_only_adds_a_separate_block():
    up = [100.0, 100.8, 101.2, 101.0, 100.6, 100.2, 100.0, 99.9, 99.9, 99.9, 99.9, 99.9]
    std, ext = _grade(up), _grade(up, arm_set="extended")
    assert "ext_arms" not in std and "context" not in std
    assert std["arms"] == ext["arms"] and std["post_exit"] == ext["post_exit"] and std["fidelity"] == ext["fidelity"]
    ids = {a["arm_id"] for a in ext["ext_arms"]}
    assert {"ext_sl2x_tp3R", "ext_sl3x_tp6R", "ext_sl2.5x_notp", "ext_trail_0.75x", "ext_runner_50pct_at_1R", "ext_timestop_8bars",
            "ext_stopto_0R_at_0.5R", "ext_delay_1bar", "ext_delay_3bar", "ext_limit_0.25atr", "ext_limit_0.5atr"} <= ids
    c = ext["context"]
    assert c["atr_pct"] == 0.005 and c["risk_pct"] == 0.01 and 0 <= c["hour_utc"] <= 23 and 0 <= c["dow"] <= 6
    assert c["mfe_pre_r"] is not None and c["bars_held"] > 0


def test_runner_banks_a_partial_at_its_trigger_and_the_rest_keeps_running():
    up = [100.0, 100.6, 101.2, 101.5, 101.0, 100.4, 100.3, 100.3, 100.3, 100.3, 100.3, 100.3]
    ext = _grade(up, arm_set="extended")
    r = _arm(ext, "ext_runner_50pct_at_1R", "ext_arms")
    reasons = [f["reason"] for f in r["exit"]["fills"]]
    assert "partial" in reasons and r["exit"]["fills"][0]["frac"] == 0.5 and r["exit"]["fills"][0]["px"] == 101.0


def test_limit_entry_is_unfilled_when_price_never_pulls_back_and_filled_when_it_does():
    rising = [100.0, 100.4, 100.9, 101.3, 101.6, 101.8, 101.8, 101.8, 101.8, 101.8, 101.8, 101.8]
    r = _arm(_grade(rising, arm_set="extended"), "ext_limit_0.5atr", "ext_arms")
    assert r["filled"] is False and r["net_r"] is None                       # an unfilled limit is "no trade", never 0
    dip = [100.0, 99.6, 99.9, 100.6, 101.2, 101.6, 101.8, 101.8, 101.8, 101.8, 101.8, 101.8]
    f = _arm(_grade(dip, arm_set="extended"), "ext_limit_0.25atr", "ext_arms")
    assert f["filled"] is True and f["net_r"] is not None


def test_entry_arms_keep_the_bracket_distances_so_r_cannot_blow_up():
    # price gaps DOWN to just above the original stop at the delayed open: with a fixed stop PRICE the risk distance would collapse to 0.02
    # and R would explode; with fixed distances R stays bounded in the original unit.
    closes = [100.0, 99.02, 99.02, 99.5, 100.0, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5]
    d1 = _arm(_grade(closes, arm_set="extended"), "ext_delay_1bar", "ext_arms")
    assert d1["filled"] is True and abs(d1["net_r"]) < 5.0


def test_entry_at_bar_close_stops_the_signal_bar_leaking_into_the_replay_and_the_entry_arms():
    # the signal bar (time T0) dips to 98.5 BEFORE it closes at 100 (the harness entry price); the following bars only rise
    bars = [{"time": T0, "open": 99.0, "high": 100.2, "low": 98.5, "close": 100.0, "volume": 1.0, "dur": 900}]
    bars += [{"time": T0 + 900 * i, "open": 100.0 + 0.3 * i, "high": 100.4 + 0.3 * i, "low": 99.9 + 0.3 * i, "close": 100.2 + 0.3 * i, "volume": 1.0, "dur": 900}
             for i in range(1, 14)]
    trade = {"strategy": "s", "symbol": "ADAUSDT", "direction": "long", "entry_time": lrc._iso(T0), "exit_time": lrc._iso(T0 + 900 * 12), "entry": 100.0,
             "sl": 99.0, "exit_price": 103.0, "exit_reason": "timeout", "net_r": 2.9, "cost_fee_r": 0.0, "cost_funding_r": 0.0}
    cfg = {"timeframe": "15m", "max_hold_bars": 12}
    meta = {"atr": 0.5, "trail_mult": 100.0}
    leak = cf_harness.cf_fields(trade, bars, horizon_cfg=cfg, leg_meta=meta, n_random=3, arm_set="extended")
    ok = cf_harness.cf_fields(trade, bars, horizon_cfg=cfg, leg_meta=meta, n_random=3, arm_set="extended", entry_at_bar_close=True)
    assert leak["extended"]["ext_limit_0.5atr"] is not None          # default: fills on the signal bar's pre-entry low (the lookahead)
    assert ok["extended"]["ext_limit_0.5atr"] is None                # fixed: the order exists only after the close, price never dips afterwards
