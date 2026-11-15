"""Non-blocking Bybit rate-limit cooldown (MECH-FOLLOWUPS-1105, manager 2026-11-05b).

``BybitConnector.get_ohlcv`` used to ``time.sleep(15)`` in the CALLER on a retCode 10006. The exit-evaluation pass
fetches candles for every open package through it, so 11 hits at the 00:00Z bar boundary left a live trade 115.3 s
without re-evaluation (PI-20261105-F2QX97PI-0001). It now starts a shared cooldown and returns None at once.

Three claims are proved here:
  1. a rate-limited ``get_ohlcv`` returns in ~1 s (never sleeps), the cooldown holds, expires, and fetches resume;
  2. EVERY strategy ``monitor()`` returns None for ``candles=None`` -- so a missing-candle pass skips the trail /
     structure step and emits no verdict;
  3. the exit loop with ``candles=None`` issues no close, no amend, no journal write: the venue SL/TP are untouched.
"""
from __future__ import annotations

import importlib
import pkgutil
import time
from unittest.mock import patch

import pytest

from src.exchange import bybit_connector as bc

RATE_LIMIT_ERR = ('bybit {"retCode":10006,"retMsg":"Too many visits. Exceeded the API Rate Limit.",'
                  '"result":{},"retExtInfo":{},"time":1793923205467}')


@pytest.fixture(autouse=True)
def _reset_cooldown():
    bc._rate_limited_until = 0.0
    bc._last_cooldown_start = 0.0
    bc._cooldown_streak = 0
    yield
    bc._rate_limited_until = 0.0
    bc._last_cooldown_start = 0.0
    bc._cooldown_streak = 0


def _connector():
    return bc.BybitConnector(api_key="k", api_secret="s", testnet=False)


def test_a_rate_limited_get_ohlcv_returns_fast_and_never_sleeps():
    c = _connector()
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)), \
            patch.object(bc.time, "sleep", side_effect=AssertionError("get_ohlcv must not sleep")):
        t0 = time.monotonic()
        assert c.get_ohlcv("BTCUSDT", "1h", 200) is None
        assert time.monotonic() - t0 < 1.0
    assert bc._cooldown_remaining() > 0.0


def test_while_cooling_down_the_exchange_is_not_called_at_all():
    c = _connector()
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)) as f:
        assert c.get_ohlcv("BTCUSDT", "1h", 200) is None
        assert f.call_count == 1
        for _ in range(5):
            assert c.get_ohlcv("ETHUSDT", "1h", 200) is None
        assert f.call_count == 1          # five more calls, zero more requests


def test_the_cooldown_is_shared_across_connector_instances():
    a, b = _connector(), _connector()
    with patch.object(a.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)), \
            patch.object(b.exchange, "fetch_ohlcv", return_value=[[1, 2, 3, 4, 5, 6]]) as fb:
        assert a.get_ohlcv("BTCUSDT", "1h", 10) is None
        assert b.get_ohlcv("SOLUSDT", "1h", 10) is None
        fb.assert_not_called()


def test_the_cooldown_expires_and_fetches_resume():
    c = _connector()
    rows = [[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 10.0]]
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=[Exception(RATE_LIMIT_ERR), rows]) as f:
        assert c.get_ohlcv("BTCUSDT", "1h", 10) is None
        assert c.get_ohlcv("BTCUSDT", "1h", 10) is None            # still cooling
        assert f.call_count == 1
        bc._rate_limited_until = time.monotonic() - 0.01             # the cooldown has run out
        df = c.get_ohlcv("BTCUSDT", "1h", 10)
        assert df is not None and len(df) == 1 and f.call_count == 2


def test_only_the_call_that_starts_a_cooldown_logs_it_and_the_line_names_the_thread(caplog):
    c = _connector()
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)), \
            caplog.at_level("WARNING", logger=bc.logger.name):
        c.get_ohlcv("BTCUSDT", "1h", 10)
        c.get_ohlcv("BTCUSDT", "1h", 10)
        c.get_ohlcv("BTCUSDT", "1h", 10)
    lines = [r.getMessage() for r in caplog.records if "rate limit" in r.getMessage()]
    assert len(lines) == 1 and "thread=MainThread" in lines[0] and "BTCUSDT" in lines[0]


# --- backoff (row VENUE-KLINE-RATE-LIMIT, 2026-11-13): short first cooldown, doubled per streak step, capped ----

def _hit(c, monkeypatch, at):
    """A 10006 at monotonic time *at*, with any running cooldown already expired."""
    monkeypatch.setattr(bc.time, "monotonic", lambda: at)
    bc._rate_limited_until = 0.0
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)):
        assert c.get_ohlcv("BTCUSDT", "1h", 10) is None
    return bc._rate_limited_until - at


def test_a_lone_10006_cools_down_for_the_short_base_not_15s(monkeypatch):
    assert _hit(_connector(), monkeypatch, 1000.0) == pytest.approx(bc.RATE_LIMIT_COOLDOWN_BASE_S)
    assert bc.RATE_LIMIT_COOLDOWN_BASE_S < bc.RATE_LIMIT_COOLDOWN_S


def test_repeated_10006s_within_the_window_double_and_cap_at_the_old_15s(monkeypatch):
    c = _connector()
    got = [_hit(c, monkeypatch, 1000.0 + 10.0 * i) for i in range(5)]   # 10 s apart: inside the 60 s window
    assert got == [pytest.approx(x) for x in (3.0, 6.0, 12.0, 15.0, 15.0)]


def test_a_quiet_gap_longer_than_the_window_resets_the_streak(monkeypatch):
    c = _connector()
    assert _hit(c, monkeypatch, 1000.0) == pytest.approx(3.0)
    assert _hit(c, monkeypatch, 1010.0) == pytest.approx(6.0)
    assert _hit(c, monkeypatch, 1010.0 + bc.RATE_LIMIT_STREAK_WINDOW_S + 1) == pytest.approx(3.0)


def test_a_10006_during_a_running_cooldown_does_not_extend_or_escalate_it(monkeypatch):
    c = _connector()
    monkeypatch.setattr(bc.time, "monotonic", lambda: 1000.0)
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception(RATE_LIMIT_ERR)):
        c.get_ohlcv("BTCUSDT", "1h", 10)
    until, streak = bc._rate_limited_until, bc._cooldown_streak
    assert not bc._start_cooldown()          # a concurrent caller hitting the same wall
    assert (bc._rate_limited_until, bc._cooldown_streak) == (until, streak)


def test_the_log_line_states_the_actual_cooldown_length_and_streak(monkeypatch, caplog):
    c = _connector()
    with caplog.at_level("WARNING", logger=bc.logger.name):
        _hit(c, monkeypatch, 1000.0)
        _hit(c, monkeypatch, 1005.0)
    lines = [r.getMessage() for r in caplog.records if "rate limit (retCode 10006)" in r.getMessage()]
    assert "None for 3 s" in lines[0] and "streak 0" in lines[0]
    assert "None for 6 s" in lines[1] and "streak 1" in lines[1]


def test_other_errors_do_not_start_a_cooldown():
    c = _connector()
    with patch.object(c.exchange, "fetch_ohlcv", side_effect=Exception("network down")):
        assert c.get_ohlcv("BTCUSDT", "1h", 10) is None
    assert bc._cooldown_remaining() == 0.0


# --- the protective-exit proof: no candles never moves a stop or closes a trade -------------------------------

def _monitor_modules():
    import src.units.strategies as S
    out = []
    for m in pkgutil.walk_packages(S.__path__, "src.units.strategies."):
        try:
            mod = importlib.import_module(m.name)
        except Exception:  # noqa: BLE001 -- an unimportable module has no monitor to grade
            continue
        if callable(getattr(mod, "monitor", None)):
            out.append(m.name)
    return sorted(out)


def test_denominator_the_monitor_walk_finds_the_known_strategies():
    names = _monitor_modules()
    assert len(names) >= 10 and any(n.endswith(".trend_donchian") for n in names), names


@pytest.mark.parametrize("direction", ["long", "short"])
def test_every_strategy_monitor_returns_none_for_no_candles(direction):
    pkg = {"order_package_id": "pkg-x", "strategy_name": "x", "symbol": "BTCUSDT", "direction": direction,
           "entry": 100.0, "sl": 95.0 if direction == "long" else 105.0, "tp": 110.0 if direction == "long" else 90.0,
           "status": "open", "created_at": "2026-10-01T00:00:00+00:00", "meta": {"timeframe": "1h", "atr": 2.0},
           "linked_trade_id": 1}
    verdicts = {}
    for name in _monitor_modules():
        mod = importlib.import_module(name)
        try:
            verdicts[name] = mod.monitor({}, None, dict(pkg))
        except Exception:  # noqa: BLE001 -- a raise is caught by _call_strategy_monitor and is "no verdict"
            verdicts[name] = None
    assert all(v is None for v in verdicts.values()), {k: v for k, v in verdicts.items() if v is not None}


def test_the_exit_loop_with_no_candles_issues_no_close_no_amend_and_no_journal_write(tmp_path, monkeypatch):
    from src.data_layer.database import Database
    from src.runtime import order_monitor as om

    db_path = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db_path))
    db = Database(db_path=str(db_path))
    for i, strat in enumerate(["vwap", "trend_donchian"]):
        db.insert_order_package({
            "order_package_id": f"pkg-nocandles-{i}", "strategy_name": strat, "symbol": "BTCUSDT",
            "direction": "long", "entry": 100.0, "sl": 98.0, "tp": 104.0, "confidence": 0.6,
            "meta": {"strategy_name": strat, "timeframe": "1h"}})
    before = {p["order_package_id"]: (p["sl"], p["tp"], p["status"])
              for s in ("vwap", "trend_donchian") for p in db.get_order_packages_by_strategy(s)}

    with patch.object(om, "_apply_update") as upd, \
            patch.object(om, "_send_close_to_exchange") as close, \
            patch.object(om, "_send_partial_close_to_exchange") as partial, \
            patch.object(om, "_send_modify_to_exchange") as modify:
        summaries = om.run_monitor_tick(strategies=["vwap", "trend_donchian"],
                                        ohlcv_fetcher=lambda sym, tf, sn=None: None)

    upd.assert_not_called()
    close.assert_not_called()
    partial.assert_not_called()
    modify.assert_not_called()
    for s in ("vwap", "trend_donchian"):
        assert summaries[s]["open"] == 1 and summaries[s]["no_change"] == 1
        assert summaries[s]["updated"] == 0 and summaries[s]["closed"] == 0
    after = {p["order_package_id"]: (p["sl"], p["tp"], p["status"])
             for s in ("vwap", "trend_donchian") for p in db.get_order_packages_by_strategy(s)}
    assert after == before
