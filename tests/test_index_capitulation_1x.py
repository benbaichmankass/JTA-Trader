"""index_capitulation_1x (row INDEX-CAPIT-1X-LEG): the live port equals the harness, the package geometry is the spec's, the hold cap
closes on the 10th session, and the committed live-parity record covers every fixture trade for THIS module."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
LEG_DIR = REPO / "comms" / "research" / "INDEX-CAPIT-1X-LEG"

from src.units.strategies import index_capitulation_1x as L  # noqa: E402


def _harness():
    spec = importlib.util.spec_from_file_location("index_signal_etf_harness",
                                                  REPO / "scripts" / "research" / "index_signal_etf_harness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("index_signal_etf_harness", mod)
    spec.loader.exec_module(mod)
    return mod


def _walk(seed: int, n: int = 1500) -> pd.DataFrame:
    """A random walk with fat-tailed down days, so flushes and bounces occur often."""
    rng = np.random.default_rng(seed)
    r = rng.standard_t(3, n) * 0.012
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c},
                        index=pd.bdate_range("2012-01-02", periods=n))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_port_equals_harness_signals(seed):
    H = _harness()
    df = _walk(seed)
    a = [(s["i"], round(s["stop_idx"], 10)) for s in H.signals_capitulation_wide(df.open.values, df.high.values, df.low.values,
                                                                                df.close.values)]
    b = [(s["i"], round(s["stop"], 10)) for s in L.capitulation_signals(df.high.values, df.low.values, df.close.values)]
    assert len(a) > 10, "the generated frame must produce signals, or this test proves nothing"
    assert a == b


def test_comparison_can_see_a_difference():
    """Negative control: a different flush threshold must change the signal list on these frames."""
    H = _harness()
    diffs = 0
    for seed in (1, 2, 3):
        df = _walk(seed)
        a = [s["i"] for s in H.signals_capitulation_wide(df.open.values, df.high.values, df.low.values, df.close.values)]
        b = [s["i"] for s in L.capitulation_signals(df.high.values, df.low.values, df.close.values, flush_atr=1.3)]
        diffs += a != b
    assert diffs >= 1


def _frame_with_signal(seed: int = 3):
    """A generated frame truncated so its second-to-last row is a signal bar; the last row is the forming entry bar."""
    df = _walk(seed)
    sigs = L.capitulation_signals(df.high.values, df.low.values, df.close.values)
    for s in sigs:
        j = s["i"] + 1
        if j < len(df) and df.open.iloc[j] > s["stop"] and (df.open.iloc[j] - s["stop"]) / df.open.iloc[j] >= L.MIN_RISK_FRAC:
            f = df.iloc[max(0, j - 199):j + 1].copy()
            o = f.open.iloc[-1]
            f.iloc[-1, [1, 2, 3]] = [o, o, o]
            return f, s
    raise AssertionError("no tradeable signal in the generated frame")


def test_order_package_geometry():
    f, s = _frame_with_signal()
    pkg = L.order_package({"symbol": "EFA", "k_star": {"EFA": 2.5}}, f)
    entry = float(f.open.iloc[-1])
    assert pkg["direction"] == "long" and pkg["symbol"] == "EFA"
    assert pkg["entry"] == pytest.approx(entry)
    assert pkg["sl"] == pytest.approx(s["stop"])
    assert pkg["tp"] == pytest.approx(entry + 2.5 * (entry - s["stop"]))
    m = pkg["meta"]
    assert m["k_star"] == 2.5 and m["hold_cap_sessions"] == 10 and m["timeframe"] == "1d"
    assert m["entry_session"] == str(f.index[-1].date()) and m["signal_date"] == str(f.index[-2].date())


def test_no_k_star_refuses_and_never_50():
    f, _ = _frame_with_signal()
    with pytest.raises(ValueError, match="no_k_star"):
        L.order_package({"symbol": "EFA", "k_star": {}}, f)
    with pytest.raises(ValueError, match="k_star_out_of_range"):
        L.order_package({"symbol": "EFA", "k_star": {"EFA": 50.0}}, f)


def test_skips_match_the_spec():
    f, s = _frame_with_signal()
    g = f.copy()
    g.iloc[-1, [0, 1, 2, 3]] = [s["stop"] * 0.99] * 4          # the open gaps under the stop
    with pytest.raises(ValueError, match="stop_wrong_side_at_entry"):
        L.order_package({"symbol": "EFA", "k_star": {"EFA": 2.5}}, g)
    g.iloc[-1, [0, 1, 2, 3]] = [s["stop"] * 1.001] * 4         # risk 0.1% < 0.25%
    with pytest.raises(ValueError, match="risk_degenerate"):
        L.order_package({"symbol": "EFA", "k_star": {"EFA": 2.5}}, g)


def test_no_signal_when_the_last_closed_bar_is_not_a_signal_bar():
    f, _ = _frame_with_signal()
    with pytest.raises(ValueError, match="no_signal_on_last_closed_bar"):
        L.order_package({"symbol": "EFA", "k_star": {"EFA": 2.5}}, pd.concat([f, f.iloc[[-1]].set_axis(
            [f.index[-1] + pd.offsets.BDay(1)])]))


def _held_frame(entry: str, sessions: int) -> pd.DataFrame:
    idx = pd.bdate_range(entry, periods=sessions)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)


@pytest.mark.parametrize("sessions,et_hm,want", [
    (9, (15, 55), None),          # 9th session, near the close: hold
    (10, (12, 0), None),          # 10th session, midday: hold
    (10, (15, 51), "close"),      # 10th session, inside the last 10 minutes: close (the harness exits at this close)
    (11, (9, 45), "close"),       # a missed close: close at once in RTH
])
def test_monitor_hold_cap(monkeypatch, sessions, et_hm, want):
    # 2026-12-01 is outside the DST-month table: ET = UTC - 5
    now = datetime(2026, 12, 1 + 0, et_hm[0] + 5, et_hm[1], tzinfo=timezone.utc)
    monkeypatch.setattr(L, "_now", lambda: now)
    entry = (pd.Timestamp("2026-12-01") - pd.offsets.BDay(sessions - 1)).strftime("%Y-%m-%d")
    v = L.monitor({}, _held_frame(entry, sessions), {"meta": {"entry_session": entry, "hold_cap_sessions": 10}})
    assert (v or {}).get("action") == want


def test_monitor_never_acts_outside_rth(monkeypatch):
    monkeypatch.setattr(L, "_now", lambda: datetime(2026, 12, 1, 22, 0, tzinfo=timezone.utc))
    entry = (pd.Timestamp("2026-12-01") - pd.offsets.BDay(11)).strftime("%Y-%m-%d")
    assert L.monitor({}, _held_frame(entry, 12), {"meta": {"entry_session": entry}}) is None


def test_committed_live_parity_record_covers_every_fixture_trade_for_this_module():
    rec = json.loads((LEG_DIR / "live_parity.json").read_text())
    fx = json.loads((LEG_DIR / "parity_fixture.json").read_text())
    n_fx = sum(len(v["trades"]) for v in fx["tickers"].values())
    s = rec["summary"]
    assert s["pass"] is True and s["tickers_pass"] == s["tickers"] == len(fx["tickers"])
    assert s["matched"] == s["fixture_trades"] == s["hold_cap_ok"] == n_fx
    assert s["live_only"] == 0
    assert rec["fixture_sha1"] == hashlib.sha1((LEG_DIR / "parity_fixture.json").read_bytes()).hexdigest()
    assert rec["live_module_sha1"] == hashlib.sha1(
        (REPO / "src/units/strategies/index_capitulation_1x.py").read_bytes()).hexdigest(), \
        "the live module changed since the parity record: re-run scripts/research/index_capit_live_parity.py"


def test_config_matches_the_spec_and_is_wired():
    import yaml
    from src.runtime.intents import DEFAULT_PRIORITIES
    from src.runtime.intent_multiplexer import _default_intent_builders

    spec = json.loads((LEG_DIR / "spec.json").read_text())
    cfg = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"][L.NAME]
    assert sorted(cfg["symbols"]) == sorted(spec["population"])
    assert cfg["k_star"] == spec["k_star"]
    assert cfg["hold_cap_sessions"] == spec["hold_cap_sessions"] == L.HOLD_CAP_SESSIONS
    assert cfg["execution"] == "live" and cfg["enabled"] is True
    assert L.NAME in DEFAULT_PRIORITIES and L.NAME in _default_intent_builders()
    acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    assert L.NAME in acc["alpaca_live"]["strategies"] and L.NAME in acc["alpaca_portfolio"]["strategies"]
    assert L.NAME not in acc["alpaca_paper"]["strategies"]       # production: promotion MOVES a leg off general paper


def _builder_env(monkeypatch, frame, *, session="rth", taken=None):
    import src.runtime.strategy_signal_builders as B
    import src.runtime.market_hours as MH
    import src.runtime.strategy_monocle as SM
    import src.units.strategies as S

    cfg = {"enabled": True, "symbols": ["EFA"], "k_star": {"EFA": 2.5}, "hold_cap_sessions": 10, "confidence": 1.0}
    monkeypatch.setattr(S, "load_strategy_config", lambda *a, **k: {L.NAME: cfg})
    monkeypatch.setattr(MH, "us_equity_session", lambda *a, **k: session)
    monkeypatch.setattr(SM, "_same_bar_entry_for_strategy", lambda *a, **k: taken)
    monkeypatch.setattr(B, "_build_killzone_exchange", lambda settings: None)
    monkeypatch.setattr(B, "_fetch_session_frame", lambda *a, **k: (frame, None))
    for fn in ("_publish_liquidity_state", "_stamp_regime_on_meta", "_stamp_trend_align_on_signal"):
        monkeypatch.setattr(B, fn, lambda *a, **k: None)
    monkeypatch.setattr(B, "log_signal", lambda *a, **k: None)
    return B


def test_builder_emits_the_package_through_the_runtime_shape(monkeypatch):
    f, s = _frame_with_signal()
    B = _builder_env(monkeypatch, f)
    sig = B.index_capitulation_1x_signal_builder({"SYMBOL": "EFA"})
    assert sig["side"] == "buy" and sig["meta"]["strategy_name"] == L.NAME
    assert sig["stop_loss"] == pytest.approx(s["stop"]) and sig["take_profit"] > sig["entry_price"] > sig["stop_loss"]


def test_builder_takes_one_trade_per_signal(monkeypatch):
    f, _ = _frame_with_signal()
    B = _builder_env(monkeypatch, f, taken={"order_package_id": "pkg-1"})
    sig = B.index_capitulation_1x_signal_builder({"SYMBOL": "EFA"})
    assert sig["side"] == "none" and sig["meta"]["reason"].startswith("signal_already_entered")


@pytest.mark.parametrize("session", ["extended", "closed"])
def test_builder_enters_only_in_the_entry_session(monkeypatch, session):
    f, _ = _frame_with_signal()
    B = _builder_env(monkeypatch, f, session=session)
    sig = B.index_capitulation_1x_signal_builder({"SYMBOL": "EFA"})
    assert sig["side"] == "none" and sig["meta"]["reason"] == f"outside_entry_session:{session}"
