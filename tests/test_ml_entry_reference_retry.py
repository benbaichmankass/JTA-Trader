"""ml_entry reference frames: a short set is retried on the next tick, never cached as final for the bar.

PI-20261106-5A1BGFHC-0003 (manager 2026-11-05b). Measured 2026-11-06 04:00:07Z: a Bybit retCode 10006 after ~6
reference fetches started the shared 15 s cooldown (#23580), the rest of the loop got None, and the 6-frame set
was cached for the whole decision bar -- the 04:02Z retry re-read it and ml_entry refused all five symbols
(reference_symbols:5<40). These pin: (1) a later call fetches ONLY the missing symbols and completes the set;
(2) while the cooldown runs the loop stops without calling the venue or burning a symbol's tries; (3) a symbol
that never returns is tried at most _ML_ENTRY_REF_MAX_TRIES times per bar; (4) a complete set is still fetched
once per (venue, bar); (5) a new bar starts clean."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from src.runtime import strategy_signal_builders as B

BAR = "2026-11-06T03:00:00+00:00"
SYMS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT"]


def _df(n: int = 300) -> pd.DataFrame:
    ts = pd.date_range(end=pd.Timestamp("2026-11-06 03:00", tz="UTC"), periods=n, freq="1h")
    c = 100 + np.arange(n, dtype=float)
    return pd.DataFrame({"timestamp": ts, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr("src.runtime.closed_bars.drop_forming_bar", lambda df, tf: df)
    B._ML_ENTRY_REF_CACHE.clear()
    yield
    B._ML_ENTRY_REF_CACHE.clear()


class _Venue:
    """fetch_candles stand-in: records asks; `down` = symbols that return None (a 10006 / empty read)."""

    def __init__(self):
        self.asked: list = []
        self.down: set = set()

    def __call__(self, symbol, timeframe, *, settings=None, limit, exchange_client=None, since=None,
                 bypass_cache=False):
        base = str(symbol).replace("/USDT:USDT", "USDT")
        self.asked.append(base)
        return None if base in self.down else _df()


def _install(monkeypatch, cooldown=lambda: False):
    import src.runtime.market_data as md
    v = _Venue()
    monkeypatch.setattr(md, "fetch_candles", v)
    monkeypatch.setattr(B, "_bybit_cooldown_active", cooldown)
    return v


def test_short_set_is_topped_up_on_the_next_call_fetching_only_the_missing(monkeypatch):
    v = _install(monkeypatch)
    v.down = {"LINKUSDT", "ADAUSDT", "SOLUSDT"}
    first = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert set(first) == {"BTCUSDT", "ETHUSDT", "XRPUSDT"} and v.asked == SYMS
    v.asked.clear()
    v.down = set()                                        # the venue recovered on the next tick
    second = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert v.asked == ["LINKUSDT", "ADAUSDT", "SOLUSDT"]  # only the missing ones -- no refetch of what it has
    assert set(second) == set(SYMS)
    v.asked.clear()
    B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert v.asked == []                                  # complete: cached for the bar, as before


def test_cooldown_stops_the_loop_without_a_venue_call_or_a_burned_try(monkeypatch):
    state = {"cool": False}
    v = _install(monkeypatch, cooldown=lambda: state["cool"])
    real = v.__call__

    def tripping(symbol, timeframe, **kw):            # the 3rd fetch trips the shared cooldown (as 04:00:07Z)
        out = real(symbol, timeframe, **kw)
        if len(v.asked) == 3:
            state["cool"] = True
            return None
        return out
    import src.runtime.market_data as md
    monkeypatch.setattr(md, "fetch_candles", tripping)
    got = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert v.asked == SYMS[:3] and set(got) == set(SYMS[:2])   # stopped at once: symbols 4-6 never asked
    slot = next(iter(B._ML_ENTRY_REF_CACHE.values()))
    assert slot["missing"] == SYMS[2:] and all(slot["tries"].get(s, 0) == 0 for s in SYMS[3:])
    v.asked.clear()
    B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")  # still cooling: no call at all
    assert v.asked == []
    state["cool"] = False
    monkeypatch.setattr(md, "fetch_candles", real)
    done = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert v.asked == SYMS[2:] and set(done) == set(SYMS)


def test_a_never_returning_symbol_is_tried_at_most_max_tries_per_bar(monkeypatch, caplog):
    v = _install(monkeypatch)
    v.down = {"LINKUSDT"}
    with caplog.at_level(logging.INFO, logger=B.logger.name):
        for _ in range(B._ML_ENTRY_REF_MAX_TRIES + 3):
            got = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    last = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ml_entry_refs ")][-1]
    assert last.endswith("gave_up=LINKUSDT")                 # the given-up symbols are NAMED (manager 08:16Z ask)
    assert v.asked.count("LINKUSDT") == B._ML_ENTRY_REF_MAX_TRIES
    assert set(got) == set(SYMS) - {"LINKUSDT"}
    assert all(v.asked.count(s) == 1 for s in SYMS if s != "LINKUSDT")


def test_the_cooldown_check_applies_only_to_a_bybit_reference_venue(monkeypatch):
    v = _install(monkeypatch, cooldown=lambda: True)
    got = B._ml_entry_reference_frames(["SPY", "QQQ"], BAR, object(), venue="alpaca", reference_venue="alpaca")
    assert v.asked == ["SPY", "QQQ"] and set(got) == {"SPY", "QQQ"}


def test_a_new_bar_starts_clean(monkeypatch):
    v = _install(monkeypatch)
    v.down = {"SOLUSDT"}
    B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    v.asked.clear()
    v.down = set()
    nxt = "2026-11-06T04:00:00+00:00"
    got = B._ml_entry_reference_frames(SYMS, nxt, None, venue="bybit")
    assert v.asked == SYMS and set(got) == set(SYMS)
    assert all(k[2] == nxt for k in B._ML_ENTRY_REF_CACHE)


def test_build_and_top_up_each_log_one_counts_line(monkeypatch, caplog):
    v = _install(monkeypatch)
    v.down = {"SOLUSDT"}
    with caplog.at_level(logging.INFO, logger=B.logger.name):
        B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
        v.down = set()
        B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
        B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")     # complete: silent
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ml_entry_refs ")]
    assert len(lines) == 2
    assert "have=5/6 fetched_now=6 retry_pending=1" in lines[0]
    assert "have=6/6 fetched_now=1 retry_pending=0" in lines[1]


def test_real_cooldown_probe_reads_the_bybit_connector(monkeypatch):
    import src.exchange.bybit_connector as bc
    monkeypatch.setattr(bc, "_cooldown_remaining", lambda: 7.0)
    assert B._bybit_cooldown_active() is True
    monkeypatch.setattr(bc, "_cooldown_remaining", lambda: 0.0)
    assert B._bybit_cooldown_active() is False


# ------------------------------------------------------------------ follow-up (08:00Z read, manager 2026-11-05b)
def test_two_slots_share_frames_fetched_this_bar(monkeypatch):
    """08:01:41/46Z: ml_entry's profile universe and ml_entry_v2's xs_reference each fetched the same 52 symbols."""
    v = _install(monkeypatch)
    B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    v.asked.clear()
    other = SYMS[:4] + ["DOTUSDT"]                      # a second universe overlapping the first
    got = B._ml_entry_reference_frames(other, BAR, None, venue="bybit")
    assert v.asked == ["DOTUSDT"] and set(got) == set(other)


def test_refs_pending_is_true_only_for_a_transiently_short_set(monkeypatch):
    short = B._RefFrames({"BTCUSDT": 1})
    short.retry_pending = 3
    assert B._ml_entry_refs_pending(short, {"min_reference_symbols": 40}) is True
    short.retry_pending = 0                             # every owed symbol fetched or out of tries: a real refusal
    assert B._ml_entry_refs_pending(short, {"min_reference_symbols": 40}) is False
    full = B._RefFrames({f"S{i}USDT": 1 for i in range(40)})
    full.retry_pending = 5                              # enough already: decide now, do not wait for stragglers
    assert B._ml_entry_refs_pending(full, {"min_reference_symbols": 40}) is False
    assert B._ml_entry_refs_pending({"BTCUSDT": 1}, {}) is False   # a plain dict carries no retry state


def test_cooldown_cut_set_reports_retry_pending(monkeypatch):
    v = _install(monkeypatch, cooldown=lambda: True)
    got = B._ml_entry_reference_frames(SYMS, BAR, None, venue="bybit")
    assert v.asked == [] and len(got) == 0 and got.retry_pending == len(SYMS)


def _stub_builder(monkeypatch, mod_name, refs):
    """Drive the real builder with every dependency stubbed except the pending branch under test."""
    import importlib
    import src.runtime.market_data as md
    import src.units.strategies as S
    mod = importlib.import_module(mod_name)
    name = mod.NAME
    monkeypatch.setattr(S, "load_strategy_config", lambda: {name: {"enabled": True, "symbols": ["ETHUSDT"]}})
    monkeypatch.setattr("src.config.symbol_sets.leg_symbols", lambda vcfg, *a, **k: ["ETHUSDT"])
    monkeypatch.setattr(B, "_closed_window_skip", lambda *a, **k: None)
    monkeypatch.setattr(B, "_build_killzone_exchange", lambda settings: object())
    monkeypatch.setattr(md, "fetch_candles", lambda *a, **k: _df(400))
    monkeypatch.setattr(B, "_publish_liquidity_state", lambda *a, **k: None)
    frame = _df(399).rename(columns={"timestamp": "ts"})
    monkeypatch.setattr(B, "_decision_frame", lambda raw, *a, **k: (frame, None))
    monkeypatch.setattr(B, "_ml_entry_frame", lambda f: f)
    model = {"meta": {"bracket": {"decision_every_h": 4}, "xs_reference": SYMS}}
    monkeypatch.setattr(mod, "load_model", lambda: model)
    monkeypatch.setattr(mod, "is_decision_bar", lambda *a, **k: True)
    monkeypatch.setattr("src.runtime.ml_entry_profile.resolve",
                        lambda vcfg, symbol, n: {"declared": False, "reference_venue": "bybit"})
    monkeypatch.setattr("src.runtime.ml_entry_profile.reference_universe", lambda prof, meta: list(SYMS))
    monkeypatch.setattr(B, "_ml_entry_reference_frames", lambda *a, **k: refs)
    recorded, packaged = [], []
    monkeypatch.setattr(B, "_record_closed_decision", lambda *a, **k: recorded.append(a[0]))

    def pkg(cfg, **k):
        packaged.append(cfg["symbol"])
        raise ValueError("reference_symbols:2<40")
    monkeypatch.setattr(mod, "order_package", pkg)
    monkeypatch.setattr(B, "log_signal", lambda *a, **k: None)
    builder = B.ml_entry_signal_builder if mod_name.endswith("ml_entry") else B.ml_entry_v2_signal_builder
    return builder, recorded, packaged


@pytest.mark.parametrize("mod_name", ["src.units.strategies.ml_entry", "src.units.strategies.ml_entry_v2"])
def test_a_pending_reference_set_does_not_consume_the_decision_bar(monkeypatch, mod_name):
    refs = B._RefFrames({"BTCUSDT": _df(), "ETHUSDT": _df()})
    refs.retry_pending = 58                             # 08:00:06Z: the cooldown cut the loop
    builder, recorded, packaged = _stub_builder(monkeypatch, mod_name, refs)
    out = builder({"SYMBOL": "ETHUSDT", "EXCHANGE": "bybit"})
    assert recorded == [] and packaged == []            # bar NOT consumed; the next tick decides it
    assert out["side"] == "none" and out["meta"]["reason"].startswith("reference_set_pending:2+58")


@pytest.mark.parametrize("mod_name", ["src.units.strategies.ml_entry", "src.units.strategies.ml_entry_v2"])
def test_a_short_set_with_nothing_owed_is_still_a_recorded_refusal(monkeypatch, mod_name):
    refs = B._RefFrames({"BTCUSDT": _df(), "ETHUSDT": _df()})
    refs.retry_pending = 0                              # tries exhausted: a genuine refusal, recorded as before
    builder, recorded, packaged = _stub_builder(monkeypatch, mod_name, refs)
    out = builder({"SYMBOL": "ETHUSDT", "EXCHANGE": "bybit"})
    assert packaged == ["ETHUSDT"] and len(recorded) == 1
    assert out["meta"]["reason"] == "reference_symbols:2<40"
