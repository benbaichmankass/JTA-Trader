"""PAIRS-R-SCALE on the live pairs path: the R unit the executor sizes on.

``pairs_engine.entry_signal``'s ``risk = stop_z · std`` is taken over the
log-spread series. With ``hedge_beta: rolling`` that series uses a different β
on every bar, so β drift × the log-price level inflates the std and every leg
sized off it (``pairs_sizing.pair_notionals``: N_A = budget / risk) is
undersized by the same factor. ``fixed_beta_risk`` is the honest R unit.

What these tests pin:
  * ``hedge_beta: one`` — the two R units are the same number (GLD/GDX).
  * a planted rolling-β case — the engine now freezes β at entry: it sizes and
    stops on the fixed-β R unit (ratio 1) and still reports the inflated
    rolling-β one (``risk_rolling_beta``), so the correction stays measured.
  * the exits, the reversion target and the open-state stamp/rebuild carry and
    use β_entry; a legacy stamp without it exits on its own rolling basis.
  * LIVE = HARNESS: a bar-by-bar replay of the engine reproduces
    ``scripts/backtest_pairs.py``'s trades exactly on rolling-β fixtures
    (entry bar, direction, outcome, R unit, gross R).
  * the SESSION venue's ``skip_risk_scale`` refusal still fires on an inflated
    ratio, and a rolling-β pair there is no longer refused.
  * every session-venue pair in the real ``config/pairs.yaml`` passes the check.
"""
from __future__ import annotations

import importlib.util
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

_SPEC = importlib.util.spec_from_file_location(
    "backtest_pairs_rs", str(REPO_ROOT / "scripts" / "backtest_pairs.py"))
bp = importlib.util.module_from_spec(_SPEC)
sys.modules["backtest_pairs_rs"] = bp
_SPEC.loader.exec_module(bp)  # type: ignore[union-attr]


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


def test_planted_rolling_beta_sizes_on_the_fixed_beta_r_unit():
    ca, cb = _rolling_case()
    p = _rolling_params()
    sig = pe.entry_signal(ca, cb, p)
    assert sig is not None
    rf = pe.fixed_beta_risk(ca, cb, p, sig["beta_entry"])
    assert sig["risk"] == pytest.approx(rf, rel=1e-4)
    assert sig["risk_scale_ratio"] == pytest.approx(1.0, abs=1e-4)
    # the stop is one fixed-β R unit from the entry spread
    sgn = -1.0 if sig["direction"] == "long_spread" else 1.0
    assert sig["stop_spread"] == pytest.approx(sig["entry_spread"] + sgn * rf, abs=2e-6)
    # β drift × log level ~7.8 still inflates the rolling-β R unit, now reported only
    assert sig["risk_rolling_beta"] / sig["risk"] > 5.0, sig
    assert sig["beta_entry"] == pytest.approx(sig["beta"], abs=1e-6)


def test_hedge_one_signal_carries_no_beta_entry():
    ca, cb = _jammed(jam=0.15)
    sig = pe.entry_signal(ca, cb, pe.PairParams("GLD", "GDX", **REG))
    assert sig["beta_entry"] is None
    assert sig["risk"] == pytest.approx(sig["risk_rolling_beta"], rel=1e-9)


# ── exits / target on the fixed-β spread ────────────────────────────────────

def _fixed_spread(ca, cb, beta, j):
    return float(np.log(ca[j]) - beta * np.log(cb[j]))


def test_exit_stop_is_read_on_the_fixed_beta_spread():
    ca, cb = _rolling_case()
    p = _rolling_params()
    beta = 1.1
    s_now = _fixed_spread(ca, cb, beta, len(ca) - 1)
    # a long_spread whose fixed-β stop sits just above the current fixed-β spread
    pos = pe.OpenPair("long_spread", s_now + 0.01, s_now + 1e-6, 1, beta_entry=beta)
    assert pe.exit_signal(ca, cb, p, pos)["outcome"] == "stop"
    # ...and just below it: no stop (the fixed-β spread, not the rolling one, decides)
    pos = pe.OpenPair("long_spread", s_now + 0.01, s_now - 1e-6, 1, beta_entry=beta)
    ex = pe.exit_signal(ca, cb, p, pos)
    assert ex is None or ex["outcome"] != "stop"


def test_exit_revert_uses_the_fixed_beta_z():
    ca, cb = _rolling_case()
    p = _rolling_params()
    beta = 1.1
    n = len(ca)
    sj, zj = pe.fixed_beta_bar(ca, cb, beta, n - 1, p.lookback)
    w = np.log(ca[n - 1 - p.lookback:n - 1]) - beta * np.log(cb[n - 1 - p.lookback:n - 1])
    assert zj == pytest.approx((sj - w.mean()) / w.std(ddof=0), rel=1e-9)
    loose = pe.PairParams(**{**p.__dict__, "exit_z": abs(zj) + 1e-6})
    pos = pe.OpenPair("short_spread", sj, sj + 10.0, 1, beta_entry=beta)
    assert pe.exit_signal(ca, cb, loose, pos)["outcome"] == "revert"
    tight = pe.PairParams(**{**p.__dict__, "exit_z": abs(zj) - 1e-6})
    assert pe.exit_signal(ca, cb, tight, pos) is None


def test_legacy_open_state_without_beta_entry_keeps_the_rolling_basis():
    ca, cb = _rolling_case()
    p = _rolling_params()
    spread, _, _, _ = pe.compute_spread_z(ca, cb, p.lookback, "rolling")
    s_roll = float(spread[-1])
    pos = pe.OpenPair("long_spread", s_roll + 0.01, s_roll + 1e-6, 1)   # beta_entry None
    assert pe.exit_signal(ca, cb, p, pos)["outcome"] == "stop"


def test_reversion_target_on_the_fixed_beta_window():
    ca, cb = _rolling_case()
    p = _rolling_params()
    beta = 1.1
    n = len(ca)
    tgt = pe.reversion_target_spread(ca, cb, p, "long_spread", beta_entry=beta)
    w = np.log(ca[n - p.lookback:]) - beta * np.log(cb[n - p.lookback:])
    assert tgt["beta"] == beta
    assert tgt["spread_now"] == pytest.approx(_fixed_spread(ca, cb, beta, n - 1), rel=1e-12)
    assert tgt["target_spread"] == pytest.approx(w.mean() - p.exit_z * w.std(ddof=0), rel=1e-9)


# ── LIVE = HARNESS on rolling-β fixtures ────────────────────────────────────

def _rolling_series(seed, n=2500):
    rng = np.random.default_rng(seed)
    lb = np.cumsum(rng.normal(0, 0.006, n)) + np.log(2500.0)
    la = 1.1 * lb + rng.normal(0, 0.004, n) - 3.6
    return np.exp(la), np.exp(lb)


def _replay(ca, cb, p, cooldown_bars=1):
    out, n, i = [], len(ca), p.lookback + 1
    while i < n - 1:
        sig = pe.entry_signal(ca[:i + 1], cb[:i + 1], p)
        if sig is None:
            i += 1
            continue
        outcome, exit_idx = "timeout", min(i + p.max_hold_bars, n - 1)
        exit_spread = None
        for j in range(i + 1, min(i + p.max_hold_bars + 1, n)):
            ex = pe.exit_signal(ca[:j + 1], cb[:j + 1], p, pe.OpenPair(
                sig["direction"], sig["entry_spread"], sig["stop_spread"], j - i,
                beta_entry=sig["beta_entry"]))
            if ex is not None:
                outcome, exit_idx, exit_spread = ex["outcome"], j, ex.get("exit_spread")
                break
        if exit_spread is None:
            exit_spread = pe.fixed_beta_bar(ca, cb, sig["beta_entry"], exit_idx, p.lookback)[0]
        sgn = 1.0 if sig["direction"] == "long_spread" else -1.0
        out.append((i, sig["direction"], outcome, sig["risk"],
                    (exit_spread - sig["entry_spread"]) * sgn / sig["risk"]))
        i = exit_idx + 1 + cooldown_bars
    return out


@pytest.mark.parametrize("seed", [3, 17])
def test_live_engine_equals_harness_on_rolling_beta_fixtures(seed):
    import pandas as pd
    ca, cb = _rolling_series(seed)
    p = _rolling_params()
    ts = pd.date_range("2026-01-01", periods=len(ca), freq="1h", tz="UTC")
    m = pd.DataFrame({"timestamp": ts, "close_a": ca, "close_b": cb})
    rows = []
    bp.run_backtest(m, lookback=p.lookback, entry_z=p.entry_z, exit_z=p.exit_z,
                    stop_z=p.stop_z, max_hold_bars=p.max_hold_bars, cooldown_bars=1,
                    hedge_beta="rolling", timeframe="1h", pair="A/B", collect_rows=rows)
    eng = _replay(ca, cb, p)
    assert len(rows) >= 30
    assert len(eng) == len(rows)
    idx = {t: k for k, t in enumerate(ts)}
    for e, h in zip(eng, rows):
        assert e[0] == idx[h["entry_time"]]
        assert (e[1], e[2]) == (h["direction"], h["outcome"])
        assert e[3] == pytest.approx(h["risk_spread"], abs=1e-6)   # sig risk is 6 dp
        assert e[4] == pytest.approx(h["gross_r"], abs=2e-3)
        # the harness R unit is the fixed-β one, not the rolling-β std
        assert h["risk_spread"] == pytest.approx(
            pe.fixed_beta_risk(ca[:e[0] + 1], cb[:e[0] + 1], p, h["beta"]), rel=1e-9)


def test_harness_cost_in_r_is_charged_on_the_fixed_beta_unit():
    """PAIRS-R-SCALE's self-test clause: on a planted rolling-β case the harness's
    cost in R is the fixed-β figure (2 legs × fee / fixed-β risk), not a figure
    deflated by the β-drift-inflated rolling-β std."""
    import pandas as pd
    ca, cb = _rolling_series(5)
    p = _rolling_params()
    m = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=len(ca), freq="1h",
                                                 tz="UTC"), "close_a": ca, "close_b": cb})
    rows = []
    bp.run_backtest(m, lookback=p.lookback, entry_z=p.entry_z, exit_z=p.exit_z,
                    stop_z=p.stop_z, max_hold_bars=p.max_hold_bars, cooldown_bars=1,
                    hedge_beta="rolling", timeframe="1h", pair="A/B", collect_rows=rows)
    fee = 2.0 * bp.FEE_BPS_ROUNDTRIP / 10_000.0
    spread, _, std, _ = pe.compute_spread_z(ca, cb, p.lookback, "rolling")
    ts = list(m["timestamp"])
    for r in rows[:20]:
        k = ts.index(r["entry_time"])
        fixed = pe.fixed_beta_risk(ca[:k + 1], cb[:k + 1], p, r["beta"])
        assert fee / r["risk_spread"] == pytest.approx(fee / fixed, rel=0.10)
        assert p.stop_z * std[k] / fixed > 5.0      # the rolling-β unit it replaced


# ── decide_pair ────────────────────────────────────────────────────────────

def _decide(ca, cb, params, **kw):
    return px.decide_pair(params, ca, cb, open_state=None, held_symbols=set(),
                          risk_budget_usd=1500.0, correlation_open=0,
                          min_leg_notional_usd=1.0, **kw)


def test_session_refuses_an_inflated_r_unit_and_sizes_nothing(monkeypatch):
    """The non-recurrence check still bites if an inflated R unit ever comes back."""
    ca, cb = _rolling_case()
    real = pe.entry_signal

    def inflated(a, b, params):
        sig = dict(real(a, b, params))
        sig["risk_scale_ratio"] = 87.0
        return sig

    monkeypatch.setattr(pe, "entry_signal", inflated)
    d = _decide(ca, cb, _rolling_params(), require_fixed_beta_risk=True, whole_units=True)
    assert d.event == "skip_risk_scale"
    assert d.legs == [] and d.close is False
    assert d.soak["hedge_beta"] == "rolling"


def test_session_rolling_beta_pair_is_no_longer_refused():
    ca, cb = _rolling_case()
    d = _decide(ca, cb, _rolling_params(), require_fixed_beta_risk=True)
    assert d.event != "skip_risk_scale", d.soak


def test_bybit_path_sizes_on_the_fixed_beta_r_unit_and_stamps_beta_entry():
    ca, cb = _rolling_case()
    p = _rolling_params()
    d = _decide(ca, cb, p)
    assert d.event == "open", d.soak
    sig = pe.entry_signal(ca, cb, p)
    rf = pe.fixed_beta_risk(ca, cb, p, sig["beta_entry"])
    assert d.legs[0].qty == pytest.approx(1500.0 / rf / ca[-1], rel=1e-4)
    assert d.soak["risk_scale_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert d.soak["risk_rolling_beta"] / d.soak["risk"] > 5.0
    assert d.soak["beta_entry"] == sig["beta_entry"]


def test_open_state_round_trips_beta_entry():
    meta = {"pair_direction": "long_spread", "entry_spread": -0.1, "stop_spread": -0.2,
            "opened_at_utc": "2026-10-16T00:00:00+00:00", "bar_seconds": 3600}
    assert px._open_pair_from_meta(meta).beta_entry is None          # legacy stamp
    assert px._open_pair_from_meta({**meta, "beta_entry": 1.07}).beta_entry == 1.07


def test_rebuild_from_legs_uses_the_fixed_beta_r_unit():
    from datetime import datetime, timedelta, timezone
    ca, cb = (list(x[:300]) for x in _rolling_series(3))
    p = _rolling_params()
    held = 3
    opened = (datetime.now(timezone.utc) - timedelta(hours=held, minutes=10)).isoformat()
    rows = ({"id": 1, "direction": "long", "entry_price": ca[-1 - held], "timestamp": opened},
            {"id": 2, "direction": "short", "entry_price": cb[-1 - held], "timestamp": opened})
    kind, op, meta, _ = px._rebuild_open_state_from_legs(p, rows, ca, cb, 3600)
    assert kind == "rebuilt_full"
    k = len(ca) - 1 - held
    _, _, _, beta = pe.compute_spread_z(ca, cb, p.lookback, "rolling")
    assert op.beta_entry == pytest.approx(float(beta[k]))
    rf = pe.fixed_beta_risk(ca[:k + 1], cb[:k + 1], p, float(beta[k]))
    assert op.entry_spread - op.stop_spread == pytest.approx(rf, rel=1e-9)
    assert meta["beta_entry"] == pytest.approx(float(beta[k]), abs=1e-6)


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

def test_tick_session_rolling_beta_pair_is_not_refused(tmp_path, monkeypatch):
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
    events = [r["event"] for r in env["soak"]]
    assert len(events) == 1 and events[0] != "skip_risk_scale", env["soak"]
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
