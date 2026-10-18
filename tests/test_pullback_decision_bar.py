"""decision_bar: closed|forming for the PULLBACK variant builder (DECISION-BAR-CLOSED-1018).

Until this change only _trend_donchian_variant_builder read ``decision_bar``; a
``decision_bar: closed`` line on xrp_pullback_2h / ada_pullback_2h would have been a
silent no-op. These tests mirror tests/test_donchian_decision_bar.py's builder tests
for _htf_pullback_variant_builder, and prove the default (forming) is byte-identical.
"""
import pandas as pd
import pytest

TF = "2h"
H2 = 2 * 3600
T0 = 1_800_000_000 - (1_800_000_000 % H2)  # a 2h boundary (epoch s)


def _frame(n=5, last_open=None):
    last_open = T0 + 10 * H2 if last_open is None else last_open
    ts = [last_open - (n - 1 - i) * H2 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.to_datetime(ts, unit="s", utc=True),
                         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})


def _builder_env(monkeypatch, decision_bar, now, frame=None):
    import src.runtime.market_data as md
    import src.runtime.strategy_signal_builders as sb
    import src.units.strategies as strategies
    monkeypatch.setattr("time.time", lambda: now)
    block = {"enabled": True, "symbols": ["XRPUSDT"], "timeframe": TF}
    if decision_bar is not None:
        block["decision_bar"] = decision_bar
    monkeypatch.setattr(strategies, "load_strategy_config", lambda: {"legP": block})
    monkeypatch.setattr(sb, "_build_killzone_exchange", lambda s: object())
    monkeypatch.setattr(sb, "_publish_liquidity_state", lambda *a, **k: None)
    calls = []

    def fake_fetch(symbol, timeframe, **kw):
        calls.append(kw)
        return frame                     # None -> RuntimeError after the fetch: enough to observe it
    monkeypatch.setattr(md, "fetch_candles", fake_fetch)
    return sb, calls


def test_closed_leg_fetches_uncached_inside_window(monkeypatch):
    sb, calls = _builder_env(monkeypatch, "closed", T0 + 10 * H2 + 90)
    with pytest.raises(RuntimeError):
        sb._htf_pullback_variant_builder("legP", {})
    assert calls == [{"limit": 200, "exchange_client": calls[0]["exchange_client"],
                      "bypass_cache": True}]


def test_closed_leg_does_not_fetch_outside_window(monkeypatch):
    sb, calls = _builder_env(monkeypatch, "closed", T0 + 10 * H2 + 3600)
    out = sb._htf_pullback_variant_builder("legP", {})
    assert calls == []                                    # no venue round-trip
    assert out["side"] == "none"
    assert out["meta"]["reason"] == "closed_bar_stale_skipped"


def test_closed_leg_waits_out_the_settle_seconds(monkeypatch):
    sb, calls = _builder_env(monkeypatch, "closed", T0 + 10 * H2 + 2)
    out = sb._htf_pullback_variant_builder("legP", {})
    assert calls == [] and out["meta"]["reason"] == "closed_bar_settling"
    from src.runtime import decision_bar_ledger
    assert decision_bar_ledger.get("legP") is None


@pytest.mark.parametrize("decision_bar", [None, "forming"])
def test_forming_leg_is_unchanged(monkeypatch, decision_bar):
    sb, calls = _builder_env(monkeypatch, decision_bar, T0 + 10 * H2 + 3600)
    with pytest.raises(RuntimeError):
        sb._htf_pullback_variant_builder("legP", {})
    assert len(calls) == 1 and "bypass_cache" not in calls[0]
    from src.runtime import decision_bar_ledger
    assert decision_bar_ledger.get("legP") is None        # forming legs never touch the ledger here


def test_closed_leg_decides_on_the_closed_bar_and_records_it(monkeypatch):
    """Inside the window, with the venue's frame ending in the forming bar: the unit sees
    the frame WITHOUT that row, and a clean no-signal is recorded as the bar's decision."""
    import src.units.strategies.htf_pullback_trend_2h as unit
    now = T0 + 11 * H2 + 90                                # 90 s into bar 11
    fetched = _frame(n=6, last_open=T0 + 11 * H2)           # ends in the forming bar 11
    sb, calls = _builder_env(monkeypatch, "closed", now, frame=fetched)
    seen = {}

    def fake_order_package(cfg, candles_df=None):
        seen["n"] = len(candles_df)
        seen["last_open"] = int(candles_df["timestamp"].iloc[-1].timestamp())
        raise ValueError("no setup")
    monkeypatch.setattr(unit, "order_package", fake_order_package)
    out = sb._htf_pullback_variant_builder("legP", {})
    assert out["side"] == "none" and out["meta"]["reason"] == "no setup"
    assert seen == {"n": 5, "last_open": T0 + 10 * H2}      # forming row dropped; closed bar 10 decided
    from src.runtime import decision_bar_ledger
    row = decision_bar_ledger.get("legP")
    assert row["bar_open"] == T0 + 10 * H2 and row["disposition"] == "evaluated"
    # the same bar is not evaluated twice
    out2 = sb._htf_pullback_variant_builder("legP", {})
    assert out2["meta"]["reason"] == "closed_bar_already_evaluated"
    assert seen["n"] == 5 and len(calls) == 1               # no second unit call, no second fetch


def test_forming_leg_sees_the_forming_bar(monkeypatch):
    import src.units.strategies.htf_pullback_trend_2h as unit
    now = T0 + 11 * H2 + 90
    fetched = _frame(n=6, last_open=T0 + 11 * H2)
    sb, _ = _builder_env(monkeypatch, None, now, frame=fetched)
    seen = {}

    def fake_order_package(cfg, candles_df=None):
        seen["n"] = len(candles_df)
        raise ValueError("no setup")
    monkeypatch.setattr(unit, "order_package", fake_order_package)
    sb._htf_pullback_variant_builder("legP", {})
    assert seen == {"n": 6}                                 # unchanged: the whole fetched frame
