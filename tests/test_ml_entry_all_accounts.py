"""ml_entry on every account by config (row ML-ENTRY-ALL-ACCOUNTS): one implementation, per-account profile.

Pins (a) the bybit path is unchanged (no profile declared on the live config, and the default profile decides exactly
what no profile decides), and (b) each of the five parametrised items: anchor, reference source + cache key, sides,
session-aware decision bars, cost basis -- plus the shared-symbol conflict rule."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.runtime import ml_decision_features as F
from src.runtime import ml_entry_profile as PR
from src.units.strategies import ml_entry as M

REPO = Path(__file__).resolve().parents[1]
BYBIT_SYMS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]


def _frame(seed: int, n: int = 400, end: str = "2026-01-01 03:00") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="1h")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1e3, 1e4, n)})


class _Stub:
    def __init__(self, v):
        self.v = v

    def predict(self, x):
        return np.full(len(x), self.v)


def _model(p_long, p_short, tau=0.1, cost_gate=None):
    meta = {"features": F.FEATURES, "tau": tau, "model_id": "stub",
            "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_h": 24, "decision_every_h": 4}}
    if cost_gate:
        meta["cost_gate"] = cost_gate
    return {"meta": meta, "long": _Stub(p_long), "short": _Stub(p_short)}


def _refs(end: str = "2026-01-01 03:00"):
    return {f"S{i}USDT": _frame(10 + i, end=end) for i in range(45)} | {"BTCUSDT": _frame(1, end=end)}


def _leg():
    return yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["ml_entry"]


def _pkg(cfg, model, df=None, refs=None):
    try:
        return M.order_package(cfg, candles_df=_frame(2) if df is None else df,
                               reference_frames=_refs() if refs is None else refs, model=model)
    except ValueError as exc:
        return str(exc).split(";feat=")[0]


# ------------------------------------------------------------------------------------------------ bybit parity
def test_live_config_declares_no_profile_for_the_bybit_symbols():
    """The real-money path: bybit_2 / bybit_portfolio's symbols resolve to the defaults, undeclared."""
    leg = _leg()
    for s in BYBIT_SYMS:
        p = PR.resolve(leg, s)
        assert p["declared"] is False and p["conflict"] is None, (s, p)
        assert (p["reference_venue"], p["reference_universe"], p["anchor"], p["session"], p["cost_basis"],
                p["side_filter"]) == ("bybit", None, None, None, None, "both")
        assert set(p["accounts"]) == {"bybit_2", "bybit_portfolio"}


@pytest.mark.parametrize("pl,ps", [(0.3, 0.1), (0.1, 0.3), (0.05, 0.02), (0.2, 0.2)])
def test_default_profile_decides_exactly_what_no_profile_decides(pl, ps):
    model = _model(pl, ps)
    base = {"symbol": "ETHUSDT"}
    prof = PR.resolve(_leg(), "ETHUSDT")
    assert _pkg(base, model) == _pkg({**base, "_profile": prof}, model)
    if isinstance(_pkg(base, model), dict):
        assert "account_profile" not in _pkg({**base, "_profile": prof}, model)["meta"]
        assert "candle_venue" not in _pkg({**base, "_profile": prof}, model)["meta"]


def test_default_decide_is_the_old_rule():
    row = {k: 0.0 for k in F.FEATURES} | {"atr_pct": 0.01}
    for pl, ps in [(0.3, 0.1), (0.1, 0.3), (0.2, 0.2), (0.05, 0.02)]:
        d = M.decide(row, _model(pl, ps))
        side = "long" if pl >= ps else "short"
        assert d["side"] == (side if max(pl, ps) > 0.1 else "none") and d["pred_net_r"] == max(pl, ps)


def test_anchor_default_is_btc_and_unchanged():
    frames = {"BTCUSDT": _frame(1), "ETHUSDT": _frame(2), "XRPUSDT": _frame(3)}
    assert F.decision_row("ETHUSDT", frames) == F.decision_row("ETHUSDT", frames, anchor="BTCUSDT")


# ------------------------------------------------------------------------------------------------ (1) anchor
def test_anchor_is_configurable():
    frames = {"ETHUSDT": _frame(2), "XRPUSDT": _frame(3), "SOLUSDT": _frame(4)}
    assert F.decision_row("XRPUSDT", frames) is None                       # no BTC: unformable under the default
    row = F.decision_row("XRPUSDT", frames, anchor="ETHUSDT")
    eth = F.features_symbol(frames["ETHUSDT"]).iloc[-1]
    assert row["btc_ret24"] == pytest.approx(eth["ret24_raw"]) and row["btc_vol24"] == pytest.approx(eth["vol24"])
    assert PR.anchor({"anchor": "ETHUSDT"}, {}) == "ETHUSDT"
    assert PR.anchor({}, {"xs_anchor": "SPY"}) == "SPY" and PR.anchor(None, {}) == "BTCUSDT"


# ------------------------------------------------------------------------------------------------ (4) sides
def test_long_only_profile_takes_long_when_it_clears_tau_even_if_short_is_larger():
    model = _model(0.2, 0.4)
    assert _pkg({"symbol": "ETHUSDT"}, model)["direction"] == "short"
    lo = {"symbol": "ETHUSDT", "_profile": {"side_filter": "long"}}
    assert _pkg(lo, model)["direction"] == "long"
    assert _pkg(lo, _model(0.05, 0.4)).startswith("below_tau:pred=0.0500")
    assert _pkg({"symbol": "ETHUSDT", "_profile": {"side_filter": "short"}}, _model(0.4, 0.2))["direction"] == "short"


def test_side_filter_resolves_through_the_shared_resolver_and_unions_across_accounts():
    leg = {"symbols": ["SPY"], "account_symbols": {"a": ["SPY"], "b": ["SPY"]},
           "account_profiles": {"a": {"side_filter": "long"}, "b": {"long_only": True}}}
    assert PR.resolve(leg, "SPY")["side_filter"] == "long"
    leg["account_profiles"]["b"] = {"side_filter": "short"}
    assert PR.resolve(leg, "SPY")["side_filter"] == "both"
    leg["account_profiles"] = {"a": {"side_filter": "long"}}            # b undeclared -> leg default "both"
    assert PR.resolve(leg, "SPY")["side_filter"] == "both"
    assert PR.resolve({**leg, "side_filter": "long"}, "SPY")["side_filter"] == "long"


# ------------------------------------------------------------------------------------------------ (3) session
def test_session_gates_decision_bars_on_market_hours():
    model = _model(0.3, 0.1)
    sess = {"symbol": "SPY", "_profile": {"session": "us_equity"}}

    def refs(end):
        return _refs(end) | {"BTCUSDT": _frame(1, end=end)}

    # Tue 2026-07-14: bar 15:00 closes 16:00 UTC (RTH 13:30-20:00 in DST); +24h is Wed 16:00 -> open
    end = "2026-07-14 15:00"
    assert isinstance(_pkg(sess, model, _frame(2, end=end), refs(end)), dict)
    # bar 19:00 closes 20:00 UTC = the session close: a market order cannot fill
    end = "2026-07-14 19:00"
    assert _pkg(sess, model, _frame(2, end=end), refs(end)) == "market_closed:us_equity"
    # Fri 2026-07-17 16:00 close: the 24h time stop lands on Saturday
    end = "2026-07-17 15:00"
    assert _pkg(sess, model, _frame(2, end=end), refs(end)) == "market_closes_before_max_hold:us_equity:1440m"
    assert PR.session_refusal(None, "SPY", pd.Timestamp("2026-07-18 12:00", tz="UTC"), 1440) is None   # 24/7


# ------------------------------------------------------------------------------------------------ (5) cost basis
def test_cost_basis_rederives_the_cost_gate_and_is_none_by_default():
    gate = {"max_cost_r": 0.06, "k_cost_x_atr": 0.0007744467196189296, "input": "atr_pct"}
    meta = _model(0.3, 0.1, cost_gate=gate)["meta"]
    row = {"atr_pct": 0.01}
    assert M.cost_r_estimate(meta, row) == pytest.approx(0.0007744467196189296 / 0.01)
    cb = {"fee_bps_rt": 0.0, "slippage_bps_rt": 5.0, "funding_bps_per_8h": 0.0}
    assert M.cost_r_estimate(meta, row, cb) == pytest.approx(5.0 / 1e4 / 2.0 / 0.01)
    assert M.cost_r_estimate(_model(0.3, 0.1)["meta"], row, cb) is None   # an ungated artifact never reports one


def test_cost_basis_rebases_pred_net_r_only_with_a_declared_artifact_basis():
    row = {k: 0.0 for k in F.FEATURES} | {"atr_pct": 0.005}
    model = _model(0.09, 0.0)
    cheap = {"fee_bps_rt": 0.0, "slippage_bps_rt": 3.0, "funding_bps_per_8h": 0.0}
    assert M.decide(row, model, cost_basis=cheap)["side"] == "none"       # no artifact basis: prediction as made
    d = M.decide(row, model, cost_basis={**cheap, "artifact_bps_rt": 17.0})
    # +17 bps - 3 bps at ATR 0.5% and a 2-ATR stop = +0.14 R
    assert d["pred_net_r"] == pytest.approx(0.09 + 14.0 / 1e4 / (2 * 0.005)) and d["side"] == "long"
    assert PR.total_bps_rt({"fee_bps_rt": 11, "slippage_bps_rt": 3, "funding_bps_per_8h": 1}, 24) == pytest.approx(17.0)


# ------------------------------------------------------------------------------------------------ conflicts + meta
def test_accounts_sharing_a_symbol_must_agree_or_the_decision_refuses():
    leg = {"symbols": ["SPY"], "account_symbols": {"a": ["SPY"], "b": ["SPY"]},
           "account_profiles": {"a": {"session": "us_equity"}, "b": {}}}
    p = PR.resolve(leg, "SPY")
    assert p["conflict"] == "session" and p["declared"] is True
    assert _pkg({"symbol": "ETHUSDT", "_profile": p}, _model(0.3, 0.1)) == "profile_conflict:session"
    leg["account_profiles"]["b"] = {"session": "us_equity"}
    assert PR.resolve(leg, "SPY")["conflict"] is None


def test_a_declared_profile_is_recorded_on_the_package():
    leg = {"symbols": ["ETHUSDT"], "account_symbols": {"x": ["ETHUSDT"]},
           "account_profiles": {"x": {"side_filter": "long", "cost_basis": {"fee_bps_rt": 1, "slippage_bps_rt": 2}}}}
    prof = PR.resolve(leg, "ETHUSDT")
    pkg = _pkg({"symbol": "ETHUSDT", "_profile": prof, "_candle_venue": "alpaca"}, _model(0.3, 0.1))
    ap = pkg["meta"]["account_profile"]
    assert ap["accounts"] == ["x"] and ap["side_filter"] == "long" and ap["anchor"] == "BTCUSDT"
    assert ap["cost_basis"] == {"fee_bps_rt": 1.0, "slippage_bps_rt": 2.0} and pkg["meta"]["candle_venue"] == "alpaca"


# ------------------------------------------------------------------------------------------------ (2) reference source
def _fake_fetch(calls):
    def fake(symbol, timeframe, *, settings=None, limit, exchange_client=None, since=None, bypass_cache=False):
        calls.append((symbol, exchange_client, (settings or {}).get("EXCHANGE")))
        return _frame(len(calls), n=300).rename(columns={"ts": "timestamp"})
    return fake


def test_reference_venue_is_independent_of_the_trading_venue(monkeypatch):
    import src.runtime.market_data as md
    from src.runtime import strategy_signal_builders as B
    calls = []
    monkeypatch.setattr(md, "fetch_candles", _fake_fetch(calls))
    monkeypatch.setattr("src.runtime.closed_bars.drop_forming_bar", lambda df, tf: df)
    B._ML_ENTRY_REF_CACHE.clear()
    own = object()
    B._ml_entry_reference_frames(["SPY", "QQQ"], "2026-07-14T15:00:00+00:00", own, venue="alpaca",
                                 reference_venue="alpaca")
    assert all(c is own and ex is None for _, c, ex in calls)              # the account IS the reference venue
    calls.clear()
    B._ml_entry_reference_frames(["BTCUSDT"], "2026-07-14T15:00:00+00:00", own, venue="bybit",
                                 reference_venue="binance")
    assert calls == [("BTCUSDT", None, "binance")]                         # a third venue: public client, not ours
    B._ML_ENTRY_REF_CACHE.clear()


def test_reference_cache_holds_one_slot_per_venue_so_alternating_symbols_do_not_refetch(monkeypatch):
    import src.runtime.market_data as md
    from src.runtime import strategy_signal_builders as B
    calls = []
    monkeypatch.setattr(md, "fetch_candles", _fake_fetch(calls))
    monkeypatch.setattr("src.runtime.closed_bars.drop_forming_bar", lambda df, tf: df)
    B._ML_ENTRY_REF_CACHE.clear()
    bar = "2026-01-30T15:00:00+00:00"
    for venue in ("bybit", "alpaca", "bybit", "alpaca"):
        B._ml_entry_reference_frames(["BTCUSDT", "ETHUSDT"], bar, object(), venue=venue)
    # One slot per venue, and since both slots read the SAME reference source (Bybit) the second slot reuses the
    # first one's frames (_ML_ENTRY_REF_FRAMES, PI-20261106-5A1BGFHC-0003): 2 symbols fetched once each, not 2x2.
    assert len(calls) == 2
    assert len(B._ML_ENTRY_REF_CACHE) == 2                                 # still one slot per venue
    B._ml_entry_reference_frames(["BTCUSDT", "ETHUSDT"], "2026-01-30T19:00:00+00:00", object(), venue="bybit")
    assert len(calls) == 4 and all(k[2] == "2026-01-30T19:00:00+00:00" for k in B._ML_ENTRY_REF_CACHE)
    B._ML_ENTRY_REF_CACHE.clear()


def test_tp_checkin_reads_the_own_frame_from_the_package_venue(monkeypatch):
    import src.runtime.market_data as md
    calls = []
    monkeypatch.setattr(md, "fetch_candles", _fake_fetch(calls))
    monkeypatch.setattr("src.runtime.closed_bars.drop_forming_bar", lambda df, tf: df)
    M._TP_FRAMES.clear()
    M._checkin_frames("SPY", "2026-01-01T03:00:00+00:00", ["BTCUSDT"], "alpaca")
    assert calls[0] == ("SPY", None, "alpaca") and calls[1] == ("BTC/USDT:USDT", None, "bybit")
    calls.clear()
    M._TP_FRAMES.clear()
    M._checkin_frames("ETHUSDT", "2026-01-01T03:00:00+00:00", ["BTCUSDT"])   # a bybit package: unchanged fetch
    assert calls[0] == ("ETH/USDT:USDT", None, None)
    M._TP_FRAMES.clear()
