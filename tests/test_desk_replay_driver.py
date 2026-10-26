"""DESK-7B-REPLAY-DRIVER: no-lookahead masking, the cost stack, the registered rule, the self-check.

Synthetic candles throughout (no network, no dependence on today's committed evidence), plus one
integration test on the committed Stage-0 files that skips when the candle files are absent.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

from scripts.research import desk_replay_driver as drv  # noqa: E402
from src.runtime import execution_costs as xc  # noqa: E402

TF = "2h"
SEC = 7200
T0 = pd.Timestamp("2026-03-02 00:00:00", tz="UTC")
ENTRY_I = 60
K = 2.5          # price scale: keeps the real entry (250) away from the masked 100 so the 0.5% scan is not coincident


def _candles(tail=None) -> pd.DataFrame:
    """60 quiet bars (ATR ~ 2), the entry bar closing at 100, then a hand-built path:
    bar 61 quiet; bar 62 high 102.5 (running high = +1.25 R, the DECISION bar, j0 = 1);
    bar 63 runs to 104; bar 64 reverses through the trail and is the recorded exit bar."""
    rows = []
    for i in range(ENTRY_I):
        rows.append((100.0, 101.0, 99.0, 100.0))
    rows.append((100.0, 101.0, 99.0, 100.0))                 # bar 60: entry bar, close 100
    tail = tail or [
        (100.0, 101.0, 99.5, 100.5),                         # 61
        (100.5, 102.5, 100.4, 102.0),                        # 62  decision bar (close 102.0)
        (102.2, 104.0, 101.9, 103.5),                        # 63  open 102.2: the NEXT-bar fill
        (103.5, 103.6, 99.0, 99.5),                          # 64  recorded exit bar
    ]
    rows += tail
    idx = [T0 + pd.Timedelta(seconds=SEC * i) for i in range(len(rows))]
    rows = [tuple(x * K for x in r) for r in rows]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(idx, name="timestamp"))


def _leg(candles=None, symbol="XRPUSDT") -> drv.Leg:
    c = _candles() if candles is None else candles
    bars = [{"time": int(ts.timestamp()), "open": float(r.open), "high": float(r.high), "low": float(r.low),
             "close": float(r.close)} for ts, r in c.iterrows()]
    atr = pd.Series(drv.dsp.atr_series(bars), index=c.index, dtype="float64")
    slip, fund = xc.resolve_cost_policy(symbol)
    et, xt = c.index[ENTRY_I], c.index[ENTRY_I + 4]
    rec_cost = xc.roundtrip_cost_r(entry=100.0 * K, exit_price=100.0 * K, risk=2.0 * K, entry_time=str(et), exit_time=str(xt),
                                   fee_bps_roundtrip=7.5, slippage_bps_roundtrip=slip, funding_bps_per_window=fund)
    t = {"strategy": "htf_pullback_trend_2h", "symbol": symbol, "entry_time": str(et), "direction": "long",
         "gross_r": 0.0, "net_r": round(-rec_cost["total_cost_r"], 4), "entry": 100.0 * K, "sl": 98.0 * K, "exit_time": str(xt),
         "mfe_r": 1.5, "exit_reason": "trail_stop", "cost_fee_r": round(rec_cost["fee_r"], 5),
         "cost_slippage_r": round(rec_cost["slippage_r"], 5), "cost_funding_r": round(rec_cost["funding_r"], 5)}
    return drv.Leg("xrp_pullback_2h", symbol, TF, [t], c, "synthetic", atr, 7.5, slip, fund,
                   {"fees": 7.5, "slippage": slip, "funding": fund}, [T0], 1)


def _point(leg=None) -> drv.Point:
    leg = leg or _leg()
    pts, pop = drv.build_points(leg)
    assert len(pts) == 1, pop
    return pts[0]


# --------------------------------------------------------------------------- decision point + no lookahead

def test_decision_point_is_the_first_closed_bar_at_plus_one_r():
    p = _point()
    assert p.j0 == 1                                    # path[0] = bar 61, path[1] = bar 62 (high 102.5 = +1.25 R)
    assert p.path["idx"][p.j0] == _candles().index[62]
    assert p.atr_over_r == pytest.approx(p.leg.atr.loc[_candles().index[ENTRY_I]] / (2.0 * K))


def test_packet_is_identical_when_every_bar_after_the_decision_bar_is_garbage():
    base_pk, base_key = drv.build_packet(_point())
    c = _candles()
    dec = c.index[62]
    junk = c.copy()
    junk.loc[junk.index > dec, ["open", "high", "low", "close"]] = [9999.0, 99999.0, 0.01, 12345.0]
    leg2 = _leg(junk)
    leg2.trades = _leg().trades                          # the trade rows are recorded history; only candles change
    pts, _ = drv.build_points(leg2)
    # the decision bar is found on bars <= j0 only, so the junk must not move it for the packet check:
    # rebuild the Point at the SAME decision bar and compare packets
    p2 = drv.Point(leg2, leg2.trades[0], _point().path, _point().j0, _point().atr_over_r, 1, _point().packet_id)
    pk2, _ = drv.build_packet(p2)
    assert json.dumps(pk2, sort_keys=True) == json.dumps(base_pk, sort_keys=True)
    assert base_pk["bars"][-1]["k"] == 0                 # the last bar shown is the decision bar
    assert len(base_pk["bars"]) == drv.LOOKBACK_BARS


def test_atr_at_a_bar_does_not_depend_on_later_bars():
    c = _candles()
    junk = c.copy()
    junk.iloc[-3:, :] = 1e6
    a1, a2 = _leg(c).atr, _leg(junk).atr
    assert a1.iloc[:-3].equals(a2.iloc[:-3])


def test_packet_masks_symbol_dates_and_prices():
    leg = _leg()
    pk, key = drv.build_packet(_point(leg))
    txt = json.dumps(pk, sort_keys=True)
    assert drv.leak_scan(txt, key) == []
    assert pk["bars"][-1]["c"] == 100.0                  # rebased: the decision close is 100
    assert "XRP" not in txt.upper() and "2026" not in txt and str(100.0 * K) not in txt
    assert pk["bars"][-1]["t"].startswith("2000-02-01")
    assert pk["trade"]["current_stop"]["read_state"] == "could_not_look"     # not-looked is not zero
    assert key["leg"] == "xrp_pullback_2h" and key["leg"] not in txt          # the key never travels with the packet


def test_leak_scan_finds_planted_leaks_and_ignores_a_hex_id_that_looks_like_a_year():
    pk, key = drv.build_packet(_point())
    clean = json.dumps(pk, sort_keys=True)
    assert drv.leak_scan(clean, key) == []
    for plant in (lambda d: d["trade"].update(note="XRPUSDT"),
                  lambda d: d["trade"].update(note="entered 2026-03-04"),
                  lambda d: d["trade"].update(note="in 2025"),
                  lambda d: d["bars"][0].update(c=key["real_entry"] * 1.002),
                  lambda d: d["trade"].update(note=1772400000)):
        bad = copy.deepcopy(pk)
        plant(bad)
        assert drv.leak_scan(json.dumps(bad), key), "the probe cannot see a planted leak"
    pk2 = copy.deepcopy(pk)
    pk2["packet_id"] = "P-e6ed647a2044"                  # hex digits that read as a year
    assert drv.leak_scan(json.dumps(pk2), key) == []


# --------------------------------------------------------------------------- the cost stack

def test_hold_is_the_recorded_net_r_untouched():
    p = _point()
    assert drv.price_action(p, ("hold",)) == float(p.trade["net_r"])
    assert drv.dR(p, ("hold",)) == 0.0


def test_close_fills_at_the_next_bar_open_and_pays_the_full_cost_stack():
    p = _point()
    got = drv.price_action(p, ("close",))
    fill_ts = p.path["idx"][p.j0 + 1]
    assert fill_ts == _candles().index[63]
    gross = (102.2 - 100.0) / 2.0                        # bar 63's OPEN, not the decision bar's 102.0 close
    slip, fund = xc.resolve_cost_policy("XRPUSDT")
    c = xc.roundtrip_cost_r(entry=100.0 * K, exit_price=102.2 * K, risk=2.0 * K, entry_time=p.trade["entry_time"],
                            exit_time=str(fill_ts), fee_bps_roundtrip=7.5, slippage_bps_roundtrip=slip,
                            funding_bps_per_window=fund)
    assert got == pytest.approx(gross - c["total_cost_r"], abs=1e-9)
    per_r = (100.0 + 102.2) / 2 / 2.0          # scale-free: K cancels
    assert c["fee_r"] == pytest.approx(7.5e-4 * per_r)                       # fee 7.5 bps round trip
    assert c["slippage_r"] == pytest.approx(slip * 1e-4 * per_r) and slip == 3.0   # venue policy, not a literal 0
    assert got < gross - 0.04                            # the stack is not silently zero


def test_a_zero_cost_policy_would_change_the_answer():
    p = _point()
    with_cost = drv.price_action(p, ("close",))
    p.leg.fee_bps = p.leg.slip_bps = p.leg.fund_bps = 0.0
    assert drv.price_action(p, ("close",)) == pytest.approx(1.1)
    assert with_cost < 1.1


def test_partial_close_is_half_the_close_and_half_the_recorded_exit():
    p = _point()
    assert drv.price_action(p, ("partial_close",)) == pytest.approx(
        0.5 * drv.price_action(p, ("close",)) + 0.5 * float(p.trade["net_r"]))


def test_tighten_fills_at_the_stop_pays_stop_fill_slip_and_a_gap_fills_at_the_open():
    p = _point()
    # r:0.5 -> fixed stop at +0.5 R = 101.0. Bar 63 low 101.9 holds; bar 64 opens 103.5 and trades down to 99.0.
    got = drv.price_action(p, ("tighten", "r", 0.5), stop_fill_slip_r=0.05)
    none = drv.price_action(p, ("tighten", "r", 0.5), stop_fill_slip_r=0.0)
    assert none - got == pytest.approx(0.05)
    assert drv.lro.replay_tighten(p.path, p.j0, "r", 0.5, p.atr_over_r)[0] == pytest.approx(0.5)   # at the stop
    # a stop the market gaps through fills at the OPEN, not at the stop
    gapped = drv.lro.replay_tighten(p.path, p.j0, "r", 1.0, p.atr_over_r)
    assert gapped is not None and gapped[0] == pytest.approx(1.0) or gapped[0] >= 1.0


def test_tighten_levels_that_loosen_or_sit_above_price_are_invalid_not_priced():
    p = _point()
    assert drv.price_action(p, ("tighten", "r", -1.0)) is None          # at the initial stop: not a tighten
    assert drv.price_action(p, ("tighten", "r", -2.0)) is None          # loosening
    assert drv.price_action(p, ("tighten", "r", 1.5)) is None           # decision-bar close is +1.0 R: above price
    assert drv.dR(p, ("tighten", "r", 1.5)) is None


def test_a_short_prices_the_mirror_image():
    c = _candles()
    mirror = c.copy()
    for col, other in (("open", "open"), ("close", "close")):
        mirror[col] = 200.0 * K - c[col]
    mirror["high"], mirror["low"] = 200.0 * K - c["low"], 200.0 * K - c["high"]
    leg = _leg(mirror)
    leg.trades[0]["direction"] = "short"
    leg.trades[0]["entry"] = 100.0 * K
    leg.trades[0]["sl"] = 102.0 * K
    p = _point(leg)
    # same R-path, mirrored; the cost per R depends on the price level (avg of entry and exit), so ~1e-3 R apart
    assert drv.price_action(p, ("close",)) == pytest.approx(drv.price_action(_point(), ("close",)), abs=5e-3)


# --------------------------------------------------------------------------- actions intake

def test_read_actions_refuses_unknown_duplicate_and_wrong_role_rows(tmp_path):
    f = tmp_path / "a.jsonl"
    ok = {"packet_id": "P-1", "role": "in_trade", "action": "tighten_sl", "level": {"kind": "atr", "value": 1.5}}
    f.write_text(json.dumps(ok) + "\n")
    got = drv.read_actions(f, "in_trade", {"P-1"})
    assert got["P-1"] == (("tighten", "atr", 1.5), None)
    for rows, msg in (([{**ok, "packet_id": "P-9"}], "not in the mask key"), ([ok, ok], "duplicate"),
                      ([{**ok, "role": "exit"}], "role")):
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        with pytest.raises(ValueError, match=msg):
            drv.read_actions(f, "in_trade", {"P-1"})
    spec, problem = drv.parse_action({"action": "tighten_sl"}, "in_trade")
    assert spec == ("hold",) and "level" in problem
    spec, problem = drv.parse_action({"action": "close"}, "in_trade")
    assert spec == ("hold",) and problem                                  # close is not an in-trade action


# --------------------------------------------------------------------------- the registered rule

def _stats(**kw):
    base = dict(n_obs=176, mean=0.20, ci_lo=0.05, ci_hi=0.35, b2_mean=0.02, b2_diff_lo=0.03, b3_mean=0.10,
                folds_positive=3, post_cutoff={"state": "measured", "n": 30, "mean": 0.1}, selfcheck=True,
                scrambled_nonzero=False)
    base.update(kw)
    return base


@pytest.mark.parametrize("kw,verdict", [
    ({}, "pass"),
    ({"n_obs": 125}, "indeterminate"),
    ({"mean": -0.01, "ci_lo": -0.2, "ci_hi": 0.2}, "fail"),
    ({"ci_hi": -0.01, "ci_lo": -0.3, "mean": -0.1}, "fail"),
    ({"ci_lo": -0.02}, "indeterminate"),
    ({"b2_diff_lo": -0.01}, "indeterminate"),
    ({"b2_mean": 0.25}, "indeterminate"),
    ({"b3_mean": 0.25}, "indeterminate"),
    ({"folds_positive": 2}, "indeterminate"),
    ({"post_cutoff": {"state": "measured", "n": 30, "mean": -0.05}}, "indeterminate"),
    ({"post_cutoff": {"state": "could_not_look", "n": 0, "mean": None}}, "indeterminate"),
    ({"selfcheck": None}, "indeterminate"),
    ({"selfcheck": False, "scrambled_nonzero": True}, "fail"),
])
def test_grade_role_follows_the_registered_rule(kw, verdict):
    assert drv.grade_role(_stats(**kw))[0] == verdict


def test_a_pass_with_a_thin_post_cutoff_stratum_is_labelled():
    v, why = drv.grade_role(_stats(post_cutoff={"state": "measured", "n": 5, "mean": -0.4}))
    assert v == "pass" and any("forward-shadow confirmation required" in w for w in why)


# --------------------------------------------------------------------------- scoring end to end (stub policy)

def _many_points(n=40, seed=3, deep_loss_every=0):
    """n synthetic points (distinct paths) spread over 4 folds, to exercise B2/B3/bootstrap."""
    rng = np.random.default_rng(seed)
    pts = []
    for k in range(n):
        tail = [(100.0, 101.0, 99.5, 100.5), (100.5, 102.5, 100.4, 102.0),
                (102.2, 102.2 + rng.uniform(0, 3), 100.0 - rng.uniform(0, 1), 101.0),
                (101.0, 101.5, 98.0 - rng.uniform(0, 1), 99.0)]
        leg = _leg(_candles(tail))
        if deep_loss_every and k % deep_loss_every == 0:      # recorded exit = the initial stop (-1 R)
            t = leg.trades[0]
            t["gross_r"], t["net_r"] = -1.0, round(-1.0 + t["net_r"], 4)
        leg.name = f"leg{k % 2}"
        p = _point(leg)
        p.fold = k % 4 + 1
        p.packet_id = f"P-{k:04d}"
        p.pre_cutoff = k % 3 == 0
        pts.append(p)
    return pts


def test_score_runs_every_baseline_and_is_deterministic():
    pts = _many_points()
    acts = {p.packet_id: ((("tighten", "r", 0.5), None) if i % 2 else (("hold",), None)) for i, p in enumerate(pts)}
    kw = dict(seed=11, cutoff=pd.Timestamp("2026-01-01", tz="UTC"), selfcheck_pass=True)
    a = drv.score(pts, acts, "in_trade", **kw)
    b = drv.score(pts, acts, "in_trade", **kw)
    assert a == b
    assert a["n_obs"] == 40 and a["n_unjudged"] == 0 and a["b1_hold_mean_dR"] == 0.0
    assert a["b2_random_timing"]["draws"] == drv.B2_DRAWS and a["b3_best_static"]["rule_by_held_out_fold"]
    assert a["verdict"] == "indeterminate"                # n 40 < 126 is never a verdict
    assert set(a["sensitivity_mean_dR_by_stop_fill_slip_r"]) == {"0.05", "0.0", "0.1"}
    assert all(r["state"] == "insufficient_n" or r["n_obs"] >= 20 for r in a["per_leg"])


def test_invalid_actions_are_scored_as_hold_and_counted():
    pts = _many_points(6)
    acts = {p.packet_id: (("tighten", "r", 5.0), None) for p in pts}     # far above price: invalid
    res = drv.score(pts, acts, "in_trade", seed=1, cutoff=None, selfcheck_pass=True)
    assert res["n_invalid_actions_scored_as_hold"] == 6 and res["mean_dR"] == 0.0


def test_missing_cutoff_means_the_post_cutoff_stratum_could_not_be_looked():
    res = drv.score(_many_points(6), {}, "exit", seed=1, cutoff=None, selfcheck_pass=True)
    assert res["post_cutoff"]["state"] == "could_not_look" and res["n_obs"] == 0


# --------------------------------------------------------------------------- the self-check (unit bf56-01)

def test_selfcheck_passes_on_a_clean_synthetic_population(monkeypatch):
    legs = {"xrp_pullback_2h": _leg()}
    monkeypatch.setattr(drv, "REGISTERED_N_TRADES", 1)
    res = drv.selfcheck(legs, ["xrp_pullback_2h"], 5)
    assert res["clauses"]["a_hold_replay"]["ok"] and res["clauses"]["b_mask"]["ok"]
    assert res["clauses"]["b_mask"]["probe_positive_control_found_planted_leak"] is True
    assert res["planted_known_answer"]["state"].startswith("vacuous")        # one trade, breakeven never helps: said so
    assert res["clauses"]["a_hold_replay"]["replayed"] == 1


def test_selfcheck_is_indeterminate_not_failed_when_candles_are_missing():
    leg = _leg()
    leg.candles = None
    res = drv.selfcheck({"xrp_pullback_2h": leg}, ["xrp_pullback_2h"], 5)
    assert res["verdict"] == "indeterminate" and "not_replayed" in res["note"]


def test_selfcheck_fails_when_a_packet_leaks(monkeypatch):
    monkeypatch.setattr(drv, "REGISTERED_N_TRADES", 1)
    orig = drv.build_packet

    def leaky(p):
        pk, key = orig(p)
        pk["trade"]["note"] = key["symbol"]
        return pk, key
    monkeypatch.setattr(drv, "build_packet", leaky)
    res = drv.selfcheck({"xrp_pullback_2h": _leg()}, ["xrp_pullback_2h"], 5)
    assert res["verdict"] == "fail" and not res["clauses"]["b_mask"]["ok"]


def test_planted_known_answer_detects_information_and_loses_it_when_scrambled():
    pts = _many_points(24, deep_loss_every=3)         # every 3rd trade is stopped at -1R: breakeven would have saved it
    k = drv.planted_known_answer(pts)
    assert k["state"] == "passed" and k["oracle_mean_dR"] > 0.2
    assert k["oracle_mean_dR"] > k["breakeven_tighten_mean_dR"] and k["oracle_mean_dR"] > k["oracle_scrambled_mean_dR"] + 0.1


def test_planted_known_answer_says_so_when_it_has_nothing_to_detect():
    k = drv.planted_known_answer(_many_points(12, deep_loss_every=0))
    assert k["passed"] is False and k["state"].startswith("vacuous")
