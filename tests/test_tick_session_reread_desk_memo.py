"""TICK-SESSION-REREAD + claude_desk per-tick memo (Manager 26a rulings 2026-11-27 13:35Z).

Basis: 19 ticks after the 12:58Z restart (snapshot 13:29:56Z, before the US open).
- fetch.1d: 279 venue calls, ~5.4 s/tick. The 16 daily ETF legs re-read their 1d frame, bypassing
  the cache, on every tick. Before the open that re-read can only return the previous session's bar.
- claude_desk: 779 calls / 19 ticks, ~61 ms each, re-reading the config and the queue file.

What this pins:
1. Session closed: the bypass re-read happens at most once per 5 min per (venue, symbol, timeframe),
   with session_bar_not_published in between. A rate limit, NOT a gate.
2. The calendar says closed but the venue HAS published: the bar is picked up within 5 min.
3. Session open: the re-read runs on every tick, exactly as before.
4. An unreadable calendar reads OPEN (every-tick re-read), never a rate limit on a guess.
5. claude_desk: one tick's outputs are byte-equal with the memo on and off. Config and queue are read
   once per tick; the journal (consumed ids) is still read on every call.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import src.runtime.market_data as md
import src.runtime.strategy_signal_builders as sb
from src.runtime import tick_cost

DAY = 86400
# Alpaca 1d bars open at 05:00Z in November (EST).
FRI_OPEN = int(datetime(2026, 11, 27, 5, 0, tzinfo=timezone.utc).timestamp())
SAT_OPEN = FRI_OPEN + DAY
SAT_NOON = int(datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc).timestamp())   # US equity closed
MON_RTH = int(datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc).timestamp())    # US equity open


def _frame(last_open: int, n: int = 200) -> pd.DataFrame:
    opens = [last_open - DAY * (n - 1 - i) for i in range(n)]
    df = pd.DataFrame({"timestamp": opens, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                       "volume": 100.0})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


class _Venue:
    """Serves ``frames[i]`` on call i (the last repeats); counts venue calls."""
    def __init__(self, *frames):
        self.frames, self.calls = list(frames), 0

    def get_ohlcv(self, symbol, timeframe, limit=200):
        f = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return f.copy()


@pytest.fixture(autouse=True)
def _clean():
    md.reset_candle_cache()
    sb._SESSION_BAR_LOGGED.clear()
    sb._SESSION_REREAD_AT.clear()
    sb._DESK_TICK_MEMO.clear()
    yield
    md.reset_candle_cache()
    sb._SESSION_REREAD_AT.clear()
    sb._DESK_TICK_MEMO.clear()


def _tick(venue, now):
    # Each simulated tick starts with an empty candle cache. Real ticks are ~95 s apart and only the
    # bypass re-read matters here; this keeps the in-process TTL (real monotonic time) out of the test.
    md.reset_candle_cache()
    return sb._fetch_session_frame("gdx_pullback_1d", "GDX", "1d", venue, now=now)


# ------------------------------------------------------------------ 1. closed: rate-limited re-read

def test_closed_session_rereads_at_most_once_per_five_minutes():
    venue = _Venue(_frame(FRI_OPEN))           # the venue only ever has Friday's (closed) bar
    calls_after, skips = [], []
    for k in range(8):                          # 8 ticks, 95 s apart = 665 s
        _, skip = _tick(venue, SAT_NOON + 95 * k)
        skips.append(skip)
        calls_after.append(venue.calls)
    assert skips == ["session_bar_not_published"] * 8
    # Each tick makes one plain read. A bypass re-read is added at t=0, t=380 (first tick >= 300 s
    # after 0) and none after (760 > 665). Before: 2 calls per tick, 16 total.
    rereads = [calls_after[0] - 1] + [calls_after[i] - calls_after[i - 1] - 1 for i in range(1, 8)]
    assert rereads == [1, 0, 0, 0, 1, 0, 0, 0]
    assert venue.calls == 8 + 2


# ------------------------------------------------- 2. calendar says closed, venue has published

def test_published_bar_is_picked_up_within_five_minutes_even_when_the_calendar_reads_closed():
    # The venue publishes Saturday's bar right after the first re-read (a special open the calendar misses).
    fri, sat = _frame(FRI_OPEN), _frame(SAT_OPEN)
    venue = _Venue(fri, fri, sat)
    t0 = SAT_NOON
    _, skip0 = _tick(venue, t0)
    assert skip0 == "session_bar_not_published" and venue.calls == 2
    picked = None
    for k in range(1, 10):
        frame, skip = _tick(venue, t0 + 95 * k)
        if skip is None:
            picked = 95 * k
            assert int(frame["timestamp"].iloc[-1].timestamp()) == SAT_OPEN
            break
    assert picked is not None and picked <= sb._SESSION_REREAD_CLOSED_INTERVAL_S + 95


# ------------------------------------------------------------------- 3. open: unchanged behaviour

def test_open_session_rereads_on_every_tick_as_before():
    venue = _Venue(_frame(FRI_OPEN))           # Monday RTH, frame still ends on Friday's bar
    for k in range(5):
        _, skip = _tick(venue, MON_RTH + 95 * k)
        assert skip == "session_bar_not_published"
    assert venue.calls == 5 * 2 and sb._SESSION_REREAD_AT == {}


def test_current_frame_costs_no_reread_open_or_closed():
    for now, last in ((MON_RTH, MON_RTH - 10 * 3600), (SAT_NOON, SAT_OPEN)):
        venue = _Venue(_frame(last))
        frame, skip = _tick(venue, now)
        assert skip is None and venue.calls == 1


# ---------------------------------------------------- 4. unreadable calendar = open (fail-open)

def test_unreadable_calendar_never_rate_limits(monkeypatch):
    import src.runtime.market_hours as mh

    def _boom(*a, **k):
        raise RuntimeError("calendar unreadable")
    monkeypatch.setattr(mh, "is_market_open", _boom)
    venue = _Venue(_frame(FRI_OPEN))
    for k in range(4):
        _tick(venue, SAT_NOON + 95 * k)
    assert venue.calls == 4 * 2


def test_keys_are_per_symbol_and_timeframe():
    venue = _Venue(_frame(FRI_OPEN))
    md.reset_candle_cache()
    sb._fetch_session_frame("gdx_pullback_1d", "GDX", "1d", venue, now=SAT_NOON)
    md.reset_candle_cache()
    sb._fetch_session_frame("slv_pullback_1d", "SLV", "1d", venue, now=SAT_NOON + 10)
    assert venue.calls == 4                    # SLV is not throttled by GDX's re-read
    assert len(sb._SESSION_REREAD_AT) == 2


# ------------------------------------------------------- 5. claude_desk per-tick memo, byte-equal

def _desk_row(did, sym, at):
    p = {"symbol": sym, "venue_class": "crypto_perp", "side": "long", "timeframe": "15m",
         "horizon_bars": 8, "entry": {"type": "market", "level": 100.0, "good_till_bars": 4},
         "stop": {"level": 98.0, "basis": "swing_level"},
         "tp": {"level": 104.0, "basis": "measured_move", "p_hit": 0.42},
         "expected_r_net": 0.3, "thesis": "t", "novelty": "new", "onboarding": "in_universe"}
    return {"at": at.isoformat(), "decision_id": did, "intent_id": f"i-{did}", "packet_id": "pk",
            "packet_sha": "abc", "ref": "deadbeef", "proposal": p}


FROZEN = datetime.now(timezone.utc).replace(microsecond=0)

from src.units.strategies import claude_desk as _cd  # noqa: E402
_REAL_READ_QUEUE = _cd.read_queue   # captured once: a second _desk_seams must not wrap the first wrapper


def _desk_seams(monkeypatch, tmp_path, counts):
    import src.units.db.database as dbm
    import src.units.strategies as units
    from src.units.strategies import claude_desk as cd

    frozen = FROZEN

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(cd, "datetime", _FrozenDT)
    monkeypatch.setattr(sb, "datetime", _FrozenDT, raising=False)

    q = tmp_path / "accepted_proposals.jsonl"
    rows = [_desk_row("d-1", "BTCUSDT", frozen - timedelta(minutes=2)),
            _desk_row("d-2", "ETHUSDT", frozen - timedelta(minutes=1)),
            _desk_row("d-3", "SOLUSDT", frozen - timedelta(minutes=3))]
    q.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(cd, "queue_path", lambda: q)
    monkeypatch.setattr(cd, "ledger_path", lambda: tmp_path / "desk_leg.jsonl")
    real_read = _REAL_READ_QUEUE

    def _counted_read(path=None):
        if path is None:                       # the queue file (cd.record re-reads the LEDGER by path)
            counts["queue"] += 1
        return real_read(path)
    monkeypatch.setattr(cd, "read_queue", _counted_read)

    def _cfg(*a, **k):
        counts["config"] += 1
        return {"claude_desk": {"enabled": True, "confidence": 0.5}}
    monkeypatch.setattr(units, "load_strategy_config", _cfg)

    class _DB:
        def __init__(self, *a, **k):
            pass

        def get_order_packages_by_strategy(self, name, **k):
            counts["journal"] += 1
            return []
    monkeypatch.setattr(dbm, "Database", _DB)


SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT"]


def _run_tick(memo_on):
    if memo_on:
        tick_cost.begin_tick()
    try:
        return [json.dumps(sb.claude_desk_signal_builder({"SYMBOL": s}), sort_keys=True, default=str)
                for s in SYMS]
    finally:
        if memo_on:
            tick_cost._tick_start = None       # close the tick without persisting a tick_cost record


def test_desk_tick_outputs_are_byte_equal_with_memo_on_and_off(monkeypatch, tmp_path):
    off_counts = {"queue": 0, "config": 0, "journal": 0}
    _desk_seams(monkeypatch, tmp_path, off_counts)
    off = _run_tick(memo_on=False)
    on_counts = {"queue": 0, "config": 0, "journal": 0}
    _desk_seams(monkeypatch, tmp_path, on_counts)
    on = _run_tick(memo_on=True)
    assert on == off
    assert any('"side": "buy"' in s for s in on)          # the comparison covers real packages
    # 5 builder calls: queue and config reads drop from 5 to 1 each; the journal read does not.
    assert (off_counts["queue"], on_counts["queue"]) == (5, 1)
    assert (off_counts["config"], on_counts["config"]) == (5, 1)
    assert (off_counts["journal"], on_counts["journal"]) == (5, 5)   # consumed ids: still every call


def test_desk_memo_does_not_cross_ticks(monkeypatch, tmp_path):
    counts = {"queue": 0, "config": 0, "journal": 0}
    _desk_seams(monkeypatch, tmp_path, counts)
    _run_tick(memo_on=True)
    _run_tick(memo_on=True)
    assert counts["config"] == 2                           # one read per tick, never carried over
    assert len(sb._DESK_TICK_MEMO) == 2                    # only the latest tick's two entries kept
