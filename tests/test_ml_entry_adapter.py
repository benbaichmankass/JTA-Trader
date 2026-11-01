"""ml_entry adapter (row ML-ENTRY-LIVE-ADAPTER): serving features == research features, brackets and no-sizing invariants."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import ml_decision_features as F
from src.units.strategies import ml_entry as M

REPO = Path(__file__).resolve().parents[1]


def _harness():
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    spec = importlib.util.spec_from_file_location("ml_decision_entry", REPO / "scripts/research/ml_decision_entry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frame(seed: int, n: int = 400, end: str = "2026-01-01 03:00") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="1h")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1e3, 1e4, n)})


def test_features_match_research_harness():
    H = _harness()
    df = _frame(1)
    a = F.features_symbol(df).drop(columns=["ts"])
    b = H.features_symbol(df).drop(columns=["ts"])
    pd.testing.assert_frame_equal(a, b)
    assert F.FEATURES == H.FEATURES


def test_cross_sectional_context_matches_harness_pivot():
    frames = {"BTCUSDT": _frame(1), "ETHUSDT": _frame(2), "XRPUSDT": _frame(3)}
    row = F.decision_row("ETHUSDT", frames)
    assert row is not None and row["_n_reference"] == 3
    H = _harness()
    feats = {s: H.features_symbol(f) for s, f in frames.items()}
    r24 = pd.DataFrame({s: feats[s].set_index("ts")["ret24_raw"] for s in frames})
    v24 = pd.DataFrame({s: feats[s].set_index("ts")["vol24"] for s in frames})
    t = r24.index[-1]
    assert row["xs_rank_ret24"] == pytest.approx(r24.rank(axis=1, pct=True).loc[t, "ETHUSDT"])
    assert row["btc_ret24"] == pytest.approx(r24.loc[t, "BTCUSDT"])
    assert row["breadth_up24"] == pytest.approx(((r24 > 0).sum(axis=1) / r24.notna().sum(axis=1)).loc[t])
    assert row["rel_vol"] == pytest.approx(v24.loc[t, "ETHUSDT"] / v24.median(axis=1).loc[t])


class _Stub:
    def __init__(self, v):
        self.v = v

    def predict(self, x):
        return np.full(len(x), self.v)


def _model(p_long, p_short, tau=0.1):
    return {"meta": {"features": F.FEATURES, "tau": tau, "model_id": "stub",
                     "bracket": {"sl_atr": 2.0, "tp_atr": 3.0, "atr_n": 14, "horizon_h": 24, "decision_every_h": 4}},
            "long": _Stub(p_long), "short": _Stub(p_short)}


def _refs():
    return {f"S{i}USDT": _frame(10 + i) for i in range(45)} | {"BTCUSDT": _frame(1)}


def test_order_package_brackets_and_no_sizing():
    df = _frame(2)  # last bar opens 03:00 -> closes 04:00, a decision bar
    pkg = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.3, 0.05))
    atr = F.atr_last(df)
    assert pkg["direction"] == "long"
    assert pkg["sl"] == pytest.approx(pkg["entry"] - 2.0 * atr)
    assert pkg["tp"] == pytest.approx(pkg["entry"] + 3.0 * atr)
    assert pkg["confidence"] == M.NEUTRAL_CONFIDENCE == 1.0
    assert pkg["meta"]["max_hold_min"] == 24 * 60
    short = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.0, 0.4))
    assert short["direction"] == "short" and short["sl"] > short["entry"] > short["tp"]


def test_refusals():
    df = _frame(2)
    with pytest.raises(ValueError, match="below_tau"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.05, 0.02))
    with pytest.raises(ValueError, match="not_a_decision_bar"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=_frame(2, end="2026-01-01 04:00"),
                        reference_frames=_refs(), model=_model(0.3, 0.0))
    with pytest.raises(ValueError, match="reference_symbols"):
        M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames={"BTCUSDT": _frame(1)},
                        model=_model(0.3, 0.0))


def test_monitor_time_stop():
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert M.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": old}})["action"] == "close"
    assert M.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": new}}) is None
    assert M.monitor({}, None, None) is None


def test_served_artifact_loads_and_predicts():
    pytest.importorskip("lightgbm")
    model = M.load_model()
    assert model["meta"]["features"] == F.FEATURES and model["meta"]["tau"] == 0.1
    x = pd.DataFrame([[0.1] * len(F.FEATURES)], columns=F.FEATURES)
    assert np.isfinite(model["long"].predict(x)[0]) and np.isfinite(model["short"].predict(x)[0])


def test_monitor_records_peak_r_telemetry_and_never_raises(monkeypatch):
    """ml_entry is on a real-money roster, so its monitor carries the M31 peak-R hook (observe-only)."""
    import src.runtime.position_telemetry as pt
    import src.units.strategies.ml_entry as me
    seen = {}
    monkeypatch.setattr(pt, "record_position_telemetry", lambda **kw: seen.update(kw))
    df = pd.DataFrame({"ts": pd.date_range("2026-11-01", periods=3, freq="h", tz="UTC"),
                       "open": [1.0, 1.0, 1.0], "high": [1.1, 1.1, 1.1], "low": [0.9, 0.9, 0.9],
                       "close": [1.0, 1.0, 1.05], "volume": [1.0, 1.0, 1.0]})
    pkg = {"direction": "long", "sl": 0.9, "tp": 1.2, "meta": {"atr14": 0.05}}
    me.monitor({}, df, pkg)
    assert seen.get("strategy") == "ml_entry" and seen.get("current_price") == 1.05 and seen.get("atr") == 0.05
    monkeypatch.setattr(pt, "record_position_telemetry", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    me.monitor({}, df, pkg)  # a telemetry failure never reaches the exit path


# ── alpaca_paper (row ALPACA-LIVE-ACTIVITY-ML; operator 2026-11-01 "Paper now, v2 for live (Rec.)") ────────────


def _rth_frame(seed: int, sessions: int = 70, end_day: str = "2026-01-30") -> pd.DataFrame:
    """Alpaca-shaped 1h ETF bars: ts = bar OPEN on the clock hour, 14:00..20:00 UTC (no overnight bars)."""
    days = pd.bdate_range(end=end_day, periods=sessions, tz="UTC")
    ts = pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in days for h in range(14, 21)])
    rng = np.random.default_rng(seed)
    n = len(ts)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998,
                         "close": c, "volume": rng.uniform(1e5, 1e6, n)})


def test_an_outside_symbol_is_aligned_as_of_its_close_and_ranked_with_itself_inserted():
    """An ETF bar opening 15:00 closes 16:00: the perps are read at their bar that closed 16:00 (opened 15:00), even
    though the perp frames run on (24/7) past it. Rank = the ETF inserted among the references; breadth / median vol
    are the references' (the definition RQ-20261101-bdc2-01 scored)."""
    etf = _rth_frame(9)
    etf = etf[etf["ts"] <= pd.Timestamp("2026-01-30 15:00", tz="UTC")].reset_index(drop=True)
    perps = {s: _frame(i, n=800, end="2026-01-31 03:00") for i, s in enumerate(["BTCUSDT", "ETHUSDT", "XRPUSDT"], 1)}
    row = F.decision_row("SPY", {**perps, "SPY": etf}, reference=list(perps))
    assert row is not None and row["_n_reference"] == 4
    close = etf["ts"].iloc[-1] + pd.Timedelta(hours=1)
    cut = {s: f[f["ts"] + pd.Timedelta(hours=1) <= close] for s, f in perps.items()}
    assert all(c["ts"].iloc[-1] == pd.Timestamp("2026-01-30 15:00", tz="UTC") for c in cut.values())
    ff = {s: F.features_symbol(c.iloc[-200:].reset_index(drop=True)).iloc[-1] for s, c in cut.items()}
    own = F.features_symbol(etf).iloc[-1]
    rv = pd.Series({**{s: f["ret24_raw"] for s, f in ff.items()}, "SPY": own["ret24_raw"]})
    assert row["xs_rank_ret24"] == pytest.approx(rv.rank(pct=True)["SPY"])
    assert row["btc_ret24"] == pytest.approx(ff["BTCUSDT"]["ret24_raw"])
    refs = pd.Series({s: f["ret24_raw"] for s, f in ff.items()})
    assert row["breadth_up24"] == pytest.approx(float((refs > 0).mean()))
    assert row["rel_vol"] == pytest.approx(own["vol24"] / pd.Series({s: f["vol24"] for s, f in ff.items()}).median())


def test_a_stale_reference_is_skipped_not_read():
    etf = _rth_frame(9)
    etf = etf[etf["ts"] <= pd.Timestamp("2026-01-30 15:00", tz="UTC")].reset_index(drop=True)
    fresh = {s: _frame(i, n=800, end="2026-01-31 03:00") for i, s in enumerate(["BTCUSDT", "ETHUSDT"], 1)}
    stale = _frame(3, n=800, end="2026-01-29 03:00")       # last bar a day before the decision
    row = F.decision_row("SPY", {**fresh, "XRPUSDT": stale, "SPY": etf}, reference=[*fresh, "XRPUSDT"])
    assert row is not None and row["_n_reference"] == 3     # BTC, ETH + SPY itself; XRP skipped


def test_a_perp_row_is_unchanged_by_the_as_of_rule():
    """Equal-timestamp perps (the bybit_2 case): the as-of rule reads exactly the bars the old equality rule read."""
    frames = {"BTCUSDT": _frame(1), "ETHUSDT": _frame(2), "XRPUSDT": _frame(3)}
    assert F.decision_row("ETHUSDT", frames) == F.decision_row("ETHUSDT", frames, reference=list(frames))


def test_reference_perps_come_from_bybit_public_data_on_an_alpaca_account(monkeypatch):
    import src.runtime.market_data as md
    from src.runtime import strategy_signal_builders as B
    calls = []

    def fake_fetch(symbol, timeframe, *, settings=None, limit, exchange_client=None, since=None, bypass_cache=False):
        calls.append((symbol, exchange_client, (settings or {}).get("EXCHANGE")))
        f = _frame(len(calls), n=300).rename(columns={"ts": "timestamp"})
        return f
    monkeypatch.setattr(md, "fetch_candles", fake_fetch)
    monkeypatch.setattr("src.runtime.closed_bars.drop_forming_bar", lambda df, tf: df)
    B._ML_ENTRY_REF_CACHE.clear()
    alpaca_client = object()
    frames = B._ml_entry_reference_frames(["BTCUSDT", "ETHUSDT"], "2026-01-30T15:00:00+00:00", alpaca_client,
                                          venue="alpaca")
    assert set(frames) == {"BTCUSDT", "ETHUSDT"}
    assert all(client is None and ex == "bybit" for _, client, ex in calls), calls   # never the Alpaca client
    n = len(calls)
    B._ml_entry_reference_frames(["BTCUSDT", "ETHUSDT"], "2026-01-30T15:00:00+00:00", alpaca_client, venue="alpaca")
    assert len(calls) == n                                                          # cached per (venue, bar)
    bybit_client = object()
    B._ml_entry_reference_frames(["BTCUSDT"], "2026-01-30T15:00:00+00:00", bybit_client, venue="bybit")
    assert calls[-1][1] is bybit_client                                             # a Bybit account reuses its client
    B._ML_ENTRY_REF_CACHE.clear()


def test_alpaca_bars_carry_bar_open_timestamps(monkeypatch):
    """GOLIVE lane's condition: the live decision clock assumes ts = bar OPEN. Alpaca's `t` is the bar START; the
    connector keeps it and the ml_entry frame keeps it, so a bar opening 15:00 UTC closes 16:00 = a decision bar."""
    from src.exchange import alpaca_connector as A
    from src.runtime import strategy_signal_builders as B

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"bars": [{"t": "2026-01-30T15:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},
                             {"t": "2026-01-30T14:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.0, "v": 10}]}
    monkeypatch.setattr(A.requests, "get", lambda *a, **k: _Resp())
    df = A.AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1h", limit=2)
    fr = B._ml_entry_frame(df)
    assert list(fr["ts"]) == [pd.Timestamp("2026-01-30 14:00", tz="UTC"), pd.Timestamp("2026-01-30 15:00", tz="UTC")]
    assert M.is_decision_bar(fr["ts"].iloc[-1], 4) and not M.is_decision_bar(fr["ts"].iloc[0], 4)


def test_ml_entry_scope_on_alpaca_paper_is_etfs_only():
    import yaml
    from src.config.symbol_sets import leg_symbols
    cfg = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["ml_entry"]
    paper = leg_symbols(cfg, "alpaca_paper")
    assert paper and not any(s.endswith("USDT") for s in paper) and "GLD" not in paper
    assert leg_symbols(cfg, "bybit_2") == ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
    accts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    assert "ml_entry" in accts["alpaca_paper"]["strategies"]
    assert "ml_entry" not in (accts["alpaca_live"].get("strategies") or [])        # no real-money ML on Alpaca


def test_ml_entry_is_an_exclusive_hold_leg_on_a_non_slice_book():
    """alpaca_paper has no slice support: ml_entry enters only a flat symbol and other legs wait while it holds
    (claude_desk's rule, now a named set). The desk's own reasons are unchanged."""
    from src.units.strategies import claude_desk as cd
    assert "ml_entry" in cd.EXCLUSIVE_HOLD_LEGS and cd.NAME in cd.EXCLUSIVE_HOLD_LEGS
    r = cd.exclusive_hold_refusal
    assert r("ml_entry", 0.0, None, exclusive="ml_entry") is None
    assert r("ml_entry", 2.0, None, exclusive="ml_entry") == "ml_entry_symbol_held:net_qty=2.0"
    assert r("spy_trend_long_1d", 0.0, True, exclusive="ml_entry") == "symbol_held_by_ml_entry_leg"
    assert r("spy_trend_long_1d", 0.0, None, exclusive="ml_entry") == "symbol_held_by_ml_entry_leg:unreadable"
    assert r("spy_trend_long_1d", 5.0, False, exclusive="ml_entry") is None
    assert r("claude_desk", 3.0, None).startswith(cd.R_DESK_HELD)        # desk default unchanged
    src = (REPO / "src/core/coordinator.py").read_text()
    assert "for _ex in _cd.EXCLUSIVE_HOLD_LEGS:" in src and "exclusive=_ex" in src
