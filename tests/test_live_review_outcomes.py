"""LTR-0: conditional outcome table for an open trade (scripts/research/live_review_outcomes.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("live_review_outcomes", REPO / "scripts/research/live_review_outcomes.py")
lro = importlib.util.module_from_spec(_spec)
sys.modules["live_review_outcomes"] = lro
_spec.loader.exec_module(lro)

T0 = pd.Timestamp("2026-01-01 00:00", tz="UTC")


def _candles(bars):
    """bars: (open, high, low, close) per 2h bar, bar 0 = entry bar."""
    idx = [T0 + pd.Timedelta(hours=2 * i) for i in range(len(bars))]
    return pd.DataFrame(bars, index=pd.DatetimeIndex(idx, name="timestamp"),
                        columns=["open", "high", "low", "close"])


def _short(net_r, exit_i, mfe_r, **extra):
    """A short at 100 with 1R = 1.0 (sl 101). Costs: fee .03, slip .01, funding .04 over its life."""
    t = {"symbol": "ADAUSDT", "direction": "short", "entry": 100.0, "sl": 101.0, "mfe_r": mfe_r,
         "entry_time": str(T0), "exit_time": str(T0 + pd.Timedelta(hours=2 * exit_i)),
         "net_r": net_r, "cost_fee_r": 0.03, "cost_slippage_r": 0.01, "cost_funding_r": 0.04}
    t.update(extra)
    return t


# short, 1R = 1.0, entry ATR = 1R / atr_stop_mult(2) = 0.5 price units
# bar1 low 96 -> 4R MFE; bar2 rebounds to 98 (2R); bar3 high 100.5 (stop out at orig trail).
BARS = [(100, 100, 100, 100), (100, 100.2, 96, 96.5), (96.5, 98.5, 96.4, 98), (98, 100.5, 97.9, 100.4)]


def _one(**kw):
    return lro.build_table([_short(-0.5, 3, 4.0)], _candles(BARS), side="short", open_r=3.8,
                           peak_r=4.0, bars_held=1, atr_stop_mult=2.0, n_floor=1, **kw)


def test_tighten_replays_and_applies_full_cost_stack():
    res = _one(tighten=["atr:1.0"])            # stop = ext - 1.0*0.5/1.0 R = 4.0 - 0.5 = +3.5R... 
    hold, tight = res["options"]
    assert hold["mean_r"] == -0.5                      # HOLD = the recorded net_r, untouched
    # ATR 1.0 -> 0.5 R behind the 4R extreme -> stop at +3.5R; bar2 favourable low is -2.0R... hit at bar2
    # gross +3.5 (stop price), minus fee .03 + slip .01 + funding .04 * (bars 2 / 3)
    expected = 3.5 - 0.03 - 0.01 - 0.04 * (2 / 3)
    assert tight["mean_r"] == pytest.approx(expected, abs=1e-3)
    assert tight["ev_cost_r"] == pytest.approx(-0.5 - expected, abs=1e-3)
    assert tight["mean_r"] < 3.5                       # net is below gross: the cost stack is applied


def test_stop_fill_slip_charges_the_tighten_only():
    base = _one(tighten=["atr:1.0"])["options"]
    slip = _one(tighten=["atr:1.0"], stop_fill_slip_r=0.1)["options"]
    assert slip[0]["mean_r"] == base[0]["mean_r"]
    assert slip[1]["mean_r"] == pytest.approx(base[1]["mean_r"] - 0.1, abs=1e-3)


def test_policy_cost_fallback_when_record_has_no_cost_columns():
    t = {k: v for k, v in _short(-0.5, 3, 4.0).items() if not k.startswith("cost_")}
    fee, slip, fund, src = lro.trade_costs(t, r_dist=1.0)
    assert src == "policy" and fee > 0 and slip > 0 and fund > 0


def test_recorded_exit_stands_when_tighten_never_hit():
    # a stop 1.0 ATR behind a 4R extreme is never touched if price keeps running
    bars = [(100, 100, 100, 100), (100, 100, 95, 95.2), (95.2, 95.2, 93, 93.2)]
    res = lro.build_table([_short(4.1, 2, 7.0)], _candles(bars), side="short", open_r=4.5, peak_r=4.0,
                          bars_held=1, atr_stop_mult=2.0, n_floor=1, tighten=["atr:1.0"])
    assert res["options"][1]["mean_r"] == res["options"][0]["mean_r"] == 4.1


def test_insufficient_n_is_null_not_zero():
    res = lro.build_table([_short(-0.5, 3, 4.0)], _candles(BARS), side="short", open_r=3.8,
                          peak_r=4.0, bars_held=1, atr_stop_mult=2.0, tighten=["atr:1.0"])  # floor 20
    for o in res["options"]:
        assert o["state"] == "insufficient_n" and o["n"] == 1
        assert o["mean_r"] is None and o["worst_r"] is None and o["sd_r"] is None
    assert res["options"][1]["ev_cost_r"] is None and res["read_state"] == "insufficient_n"


def test_no_candles_is_could_not_look():
    res = lro.build_table([_short(-0.5, 3, 4.0)], None, side="short", open_r=3.8, peak_r=4.0,
                          bars_held=1, atr_stop_mult=2.0, n_floor=1, tighten=["atr:1.0"])
    assert res["options"][0]["state"] == "measured"        # hold needs no path
    assert res["options"][1]["state"] == "could_not_look" and res["options"][1]["mean_r"] is None


def test_invalid_level_stop_not_behind_mark():
    res = lro.build_table([_short(-0.5, 3, 4.0)], _candles(BARS), side="short", open_r=3.0,
                          peak_r=4.0, bars_held=1, atr_stop_mult=2.0, n_floor=1, tighten=["atr:1.0"])
    assert res["options"][1]["state"] == "invalid_level"    # stop +3.5R is above open +3.0R


def test_population_is_accounted():
    trades = [_short(-0.5, 3, 4.0), _short(1.0, 3, 1.0), dict(_short(-0.5, 3, 4.0), direction="long")]
    res = lro.build_table(trades, _candles(BARS), side="short", open_r=3.8, peak_r=4.0, bars_held=1,
                          atr_stop_mult=2.0, n_floor=1, tighten=[])
    p = res["population"]
    assert (p["corpus_trades"], p["never_reached_peak"], p["side_excluded"], p["comparable"]) == (3, 1, 1, 1)


def test_bounds_flags():
    res = _one(tighten=["atr:1.0"])
    assert res["options"][1]["within_auto_bound"] is False or res["options"][1]["within_auto_bound"] is True
    o = res["options"][1]
    assert o["within_shadow_bound"] == (o["ev_cost_r"] <= 0.5)
    assert o["within_auto_bound"] == (o["ev_cost_r"] <= 0.25)


def test_committed_ada_corpus_stage0_trades_are_found_and_replay():
    """Real committed records: the leg's 61 Stage-0 trades + committed 2h candles (no network)."""
    trades, src = lro.load_trades("ada_pullback_2h")
    assert len(trades) == 61 and src.endswith("ada_pullback_2h__trades.jsonl")
    cpath = lro.find_candles("ADAUSDT", "2h")
    assert cpath, "committed ADAUSDT 2h candles"
    res = lro.build_table(trades, lro.load_candles(cpath), side=None, open_r=3.44, peak_r=3.4,
                          bars_held=17, atr_stop_mult=1.5, tighten=["atr:1.5"])
    assert res["population"]["comparable"] == 7 and res["population"]["mfe_replay_mismatch"] == 0
    assert res["read_state"] == "insufficient_n"             # n=7 < 20: never a number from 7 trades
    assert all(o["mean_r"] is None for o in res["options"])
    floor5 = lro.build_table(trades, lro.load_candles(cpath), side=None, open_r=3.44, peak_r=3.4,
                             bars_held=17, atr_stop_mult=1.5, tighten=["atr:1.5"], n_floor=5)
    hold, tight = floor5["options"]
    assert hold["worst_r"] < tight["worst_r"]                # tightening removes the giveback tail
    assert tight["ev_cost_r"] is not None


PARITY = REPO / "tests/fixtures/ada_pullback_2h_eba2_03_trades.jsonl"
PARITY_CANDLES = REPO / "tests/fixtures/ADAUSDT_2h_2020-06-03_2026-10-15.csv"


def _parity_table():
    import json
    trades = [json.loads(ln) for ln in PARITY.read_text().splitlines() if ln.strip()]
    return lro.build_table(trades, lro.load_candles(str(PARITY_CANDLES)), side=None,
                           open_r=3.44, peak_r=3.4, bars_held=17, atr_stop_mult=1.5, tighten=["atr:1.5"])


def test_ada_case_parity_hold_n32_319():
    """eba2-03 arm A (402 trades, committed) on full-window Binance-vision 2h candles: HOLD reproduces."""
    res = _parity_table()
    assert res["population"]["corpus_trades"] == 402 and res["population"]["no_candles"] == 0
    hold = res["options"][0]
    assert hold["n"] == 32 and round(hold["mean_r"], 2) == 3.19


@pytest.mark.xfail(strict=True, reason=(
    "LTR-0 finding: the TIGHTEN half of the ADA hand calc (+2.96, PR #19891) does NOT reproduce with "
    "atr:1.5 at atr_stop_mult 1.5: the tool gives +2.87 (n=32). The hand calc's tighten parameters are "
    "not recorded; +2.96 is hit only by other settings (e.g. atr:1.0 @ stop mult 1.5 = 2.958). The "
    "assertion is NOT loosened; strict xfail flips red if the tool ever produces 2.96 here."))
def test_ada_case_parity_tighten_296():
    assert round(_parity_table()["options"][1]["mean_r"], 2) == 2.96
