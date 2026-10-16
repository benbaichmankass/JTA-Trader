"""PAIRS-R-SCALE on the live pairs path: the R unit the executor sizes on.

``pairs_engine.entry_signal``'s ``risk = stop_z · std`` is taken over the
log-spread series. With ``hedge_beta: rolling`` that series uses a different β
on every bar, so β drift × the log-price level inflates the std and every leg
sized off it (``pairs_sizing.pair_notionals``: N_A = budget / risk) is
undersized by the same factor. ``fixed_beta_risk`` is the honest R unit.

What these tests pin:
  * ``hedge_beta: one`` — the two R units are the same number (GLD/GDX).
  * a planted rolling-β case — the ratio is far from 1, and is reported.
  * the SESSION venue (Alpaca) refuses to size on an inflated R unit
    (``skip_risk_scale``), end to end through ``run_pairs_tick``;
    the Bybit path keeps its behaviour and carries both R units on its soak rows.
  * every session-venue pair in the real ``config/pairs.yaml`` passes the check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.units.strategies import pairs_engine as pe  # noqa: E402
from src.units.strategies import pairs_executor as px  # noqa: E402
from src.units.strategies import pairs_venue as pv  # noqa: E402
from tests.test_pairs_alpaca_venue import (  # noqa: E402
    REG, _FakeAlpaca, _jammed, _session_env,
)


def _rolling_case(seed=7, n=600):
    """SOL/ETH-like 1h closes (log B ~ 7.8, the level that multiplies β drift)
    with a noisy relationship so a 15-bar rolling β wanders, cut at the FIRST
    bar the live engine itself enters on (no planted jam: a natural entry)."""
    rng = np.random.default_rng(seed)
    lb = np.cumsum(rng.normal(0, 0.006, n)) + np.log(2500.0)
    la = 1.1 * lb + rng.normal(0, 0.004, n) - 3.6
    ca, cb = list(np.exp(la)), list(np.exp(lb))
    p = _rolling_params()
    for k in range(p.lookback + 2, n):
        if pe.entry_signal(ca[:k], cb[:k], p) is not None:
            return ca[:k], cb[:k]
    raise AssertionError("fixture found no entry bar")


def _rolling_params():
    return pe.PairParams("SOLUSDT", "ETHUSDT", lookback=15, entry_z=2.0, exit_z=0.5,
                         stop_z=2.0, max_hold_bars=20, hedge_beta="rolling")


# ── pure engine ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", [1, 4, 9])
def test_hedge_one_risk_is_the_fixed_beta_risk(seed):
    ca, cb = _jammed(seed=seed, jam=0.15)
    sig = pe.entry_signal(ca, cb, pe.PairParams("GLD", "GDX", **REG))
    assert sig is not None
    rf = pe.fixed_beta_risk(ca, cb, pe.PairParams("GLD", "GDX", **REG), 1.0)
    assert rf == pytest.approx(sig["risk"], rel=1e-4)   # sig["risk"] is rounded to 6 dp
    assert abs(sig["risk_scale_ratio"] - 1.0) <= pe.RISK_SCALE_TOLERANCE


def test_fixed_beta_risk_uses_the_shift1_window_and_frozen_beta():
    ca, cb = _rolling_case()
    p = _rolling_params()
    beta = 1.1
    la, lb = np.log(ca), np.log(cb)
    n = len(la)
    want = p.stop_z * np.std(la[n - 1 - p.lookback:n - 1] - beta * lb[n - 1 - p.lookback:n - 1])
    assert pe.fixed_beta_risk(ca, cb, p, beta) == pytest.approx(want, rel=1e-12)
    # the jammed LAST bar is not in its own R unit (leakage-safe, like the harness)
    ca2 = list(ca)
    ca2[-1] *= 1.5
    assert pe.fixed_beta_risk(ca2, cb, p, beta) == pytest.approx(want, rel=1e-12)


def test_fixed_beta_risk_none_on_degenerate_input():
    p = _rolling_params()
    assert pe.fixed_beta_risk([1.0] * 5, [1.0] * 5, p, 1.0) is None          # too short
    assert pe.fixed_beta_risk([1.0] * 40, [2.0] * 40, p, 1.0) is None         # zero std
    assert pe.fixed_beta_risk([1.0] * 40, [2.0] * 39, p, 1.0) is None         # misaligned
    ca, cb = _rolling_case()
    assert pe.fixed_beta_risk(ca, cb, p, float("nan")) is None


def test_planted_rolling_beta_inflates_the_r_unit():
    ca, cb = _rolling_case()
    sig = pe.entry_signal(ca, cb, _rolling_params())
    assert sig is not None
    # β drift × log level ~7.8 inflates the rolling-β std far past the fixed-β one
    assert sig["risk_scale_ratio"] > 5.0, sig
    assert sig["risk_fixed_beta"] < sig["risk"]


# ── decide_pair ────────────────────────────────────────────────────────────

def _decide(ca, cb, params, **kw):
    return px.decide_pair(params, ca, cb, open_state=None, held_symbols=set(),
                          risk_budget_usd=1500.0, correlation_open=0,
                          min_leg_notional_usd=1.0, **kw)


def test_session_refuses_an_inflated_r_unit_and_sizes_nothing():
    ca, cb = _rolling_case()
    d = _decide(ca, cb, _rolling_params(), require_fixed_beta_risk=True, whole_units=True)
    assert d.event == "skip_risk_scale"
    assert d.legs == [] and d.close is False
    assert d.soak["risk_scale_ratio"] > 5.0
    assert d.soak["hedge_beta"] == "rolling"
    assert d.soak["risk_fixed_beta"] is not None


def test_bybit_path_unchanged_but_reports_both_r_units():
    ca, cb = _rolling_case()
    d = _decide(ca, cb, _rolling_params())
    assert d.event in ("open", "skip_size")
    assert d.soak["risk_scale_ratio"] > 5.0
    assert "risk_fixed_beta" in d.soak and "risk" in d.soak


def test_session_hedge_one_opens_sized_on_the_fixed_beta_r_unit():
    ca, cb = _jammed(jam=0.15)
    params = pe.PairParams("GLD", "GDX", **REG)
    d = _decide(ca, cb, params, require_fixed_beta_risk=True, whole_units=True,
                leg_tp="spread_target")
    assert d.event == "open", d.soak
    rf = pe.fixed_beta_risk(ca, cb, params, 1.0)
    # N_A = budget / risk, floored to whole shares: within one share of the honest size
    ideal_qa = 1500.0 / rf / ca[-1]
    assert ideal_qa - 1.0 < d.legs[0].qty <= ideal_qa
    assert abs(d.soak["risk_scale_ratio"] - 1.0) <= pe.RISK_SCALE_TOLERANCE


# ── end to end: run_pairs_tick on the session venue ────────────────────────

def test_tick_session_rolling_beta_pair_is_refused_before_any_leg(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca())
    ca, cb = _rolling_case()
    from tests.test_pairs_alpaca_venue import _stamps_ending
    stamps = _stamps_ending(len(ca))
    monkeypatch.setattr(pv, "fetch_leg_frame",
                        lambda sym, tf, lim, s: ((ca if sym == "GLD" else cb), stamps))
    monkeypatch.setattr(px, "_load_pairs_config", lambda path=None: {
        "account_id": "bybit_1", "pairs_risk_fraction": 1.0,
        "pairs": [{"name": "pairs_gld_gdx", "account_id": "alpaca_paper",
                   "symbol_a": "GLD", "symbol_b": "GDX", "execution": "live",
                   "timeframe": "1d", "leg_tp": "spread_target",
                   **{**REG, "lookback": 15, "hedge_beta": "rolling"}}],
    })
    px.run_pairs_tick({})
    assert [r["event"] for r in env["soak"]] == ["skip_risk_scale"], env["soak"]
    assert env["placed"] == []
    assert env["soak"][0]["account_id"] == "alpaca_paper"


def test_tick_session_hedge_one_still_opens(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca())
    px.run_pairs_tick({})
    assert [r["event"] for r in env["soak"]] == ["open"], env["soak"]
    assert abs(env["soak"][0]["risk_scale_ratio"] - 1.0) <= pe.RISK_SCALE_TOLERANCE


# ── the real config ────────────────────────────────────────────────────────

def test_every_session_venue_pair_in_config_sizes_on_the_fixed_beta_r_unit():
    """A session-venue pair whose hedge_beta is not ``one`` would be refused
    (skip_risk_scale) on every entry until PAIRS-R-SCALE's frozen-β engine lands
    — say so here, in CI, rather than as a soak that never trades."""
    pairs_cfg = yaml.safe_load((REPO_ROOT / "config/pairs.yaml").read_text())
    accounts = yaml.safe_load((REPO_ROOT / "config/accounts.yaml").read_text())
    accounts = accounts.get("accounts", accounts)
    default = pairs_cfg.get("account_id")
    session_pairs = []
    for pair in pairs_cfg.get("pairs") or []:
        acct = accounts.get(str(pair.get("account_id") or default)) or {}
        if pv.is_session_venue(acct):
            session_pairs.append(pair["name"])
            assert str(pair.get("hedge_beta", "rolling")) == "one", pair["name"]
    assert session_pairs, "probe found no session-venue pair; the check would be vacuous"
