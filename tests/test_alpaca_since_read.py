"""CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (AM-UI 2026-11-12 Q10 option (b)): an optional historical ``since`` read on
``AlpacaMarketData.get_ohlcv``, isolated from the shared rate-limit cooldown, and paced in the snapshot builder."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.exchange import alpaca_connector as AC
from src.runtime import trade_snapshot_builder as tsb


def _bar(t, c):
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 10}


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.headers = body, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


@pytest.fixture(autouse=True)
def _no_cooldown(monkeypatch):
    monkeypatch.setitem(AC._cooldown, "until", 0.0)


def _md():
    return AC.AlpacaMarketData(api_key="k", api_secret="s", feed="sip")


def test_a_call_without_since_sends_exactly_the_old_request(monkeypatch):
    """Pinned: the no-since call's request params are the pre-change ones (desc, lookback start, no since key)."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(dict(params))
        return _Resp({"bars": [_bar("2026-11-12T15:00:00Z", 2.0), _bar("2026-11-12T14:00:00Z", 1.0)],
                      "next_page_token": None})
    monkeypatch.setattr(AC.requests, "get", fake_get)
    monkeypatch.setattr(AC, "_lookback_start", lambda tf_key, limit: "2026-10-01T00:00:00Z")
    df = _md().get_ohlcv("SPY", "1h", limit=2)
    assert calls == [{"timeframe": "1Hour", "limit": 2, "start": "2026-10-01T00:00:00Z", "adjustment": "split",
                      "feed": "sip", "sort": "desc"}]
    assert list(df["close"]) == [1.0, 2.0]


def test_since_reads_forward_from_the_instant_and_pages(monkeypatch):
    since_ms = int(datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)
    pages = [{"bars": [_bar("2026-06-01T13:30:00Z", 1.0)], "next_page_token": "p2"},
             {"bars": [_bar("2026-06-01T14:30:00Z", 2.0)], "next_page_token": None}]
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(dict(params))
        return _Resp(pages[len(calls) - 1])
    monkeypatch.setattr(AC.requests, "get", fake_get)
    df = _md().get_ohlcv("SPY", "1h", limit=5, since=since_ms)
    assert calls[0]["start"] == "2026-06-01T13:30:00Z" and calls[0]["sort"] == "asc"
    assert calls[1]["page_token"] == "p2" and list(df["close"]) == [1.0, 2.0]


def test_a_429_on_a_since_read_never_starts_the_shared_cooldown(monkeypatch):
    monkeypatch.setattr(AC.requests, "get", lambda *a, **k: _Resp({}, status=429))
    assert _md().get_ohlcv("SPY", "1h", limit=5, since=1_700_000_000_000) is None
    assert AC._cooldown_remaining() == 0.0
    # positive control: the same 429 on a normal read DOES start it
    assert _md().get_ohlcv("SPY", "1h", limit=5) is None
    assert AC._cooldown_remaining() > 0.0


def test_a_since_read_honours_a_running_cooldown(monkeypatch):
    called = []
    monkeypatch.setattr(AC.requests, "get", lambda *a, **k: called.append(1) or _Resp({"bars": []}))
    monkeypatch.setitem(AC._cooldown, "until", AC._now() + 30)
    assert _md().get_ohlcv("SPY", "1h", limit=5, since=1_700_000_000_000) is None
    assert called == []


def test_builder_paces_alpaca_since_reads(monkeypatch):
    """Two back-to-back since reads: the second waits on the BUILDER thread (sleep), not inside the executor."""
    import concurrent.futures as cf

    from src.web.api.routers import candles as cr

    clock = {"t": 1000.0}
    slept = []
    monkeypatch.setattr(tsb, "_mono", lambda: clock["t"])
    monkeypatch.setattr(tsb, "_sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setitem(tsb._alpaca_since_last, "at", None)
    md = _md()
    monkeypatch.setattr(cr, "_settings", lambda: {})
    monkeypatch.setattr(cr, "_connector", lambda symbol, settings: md)
    monkeypatch.setattr(cr, "_FETCH_EXECUTOR", cf.ThreadPoolExecutor(max_workers=1))
    venue = []

    def fake_fetch(symbol, interval, **kw):
        venue.append(kw.get("since"))
        return None
    import src.runtime.market_data as mdmod
    monkeypatch.setattr(mdmod, "fetch_candles", fake_fetch)
    tsb.web_api_fetch("SPY", "1h", 1_700_000_000_000, 10)
    tsb.web_api_fetch("SPY", "1h", 1_700_000_000_000, 10)
    assert len(venue) == 2 and len(slept) == 1 and slept[0] >= tsb.ALPACA_SINCE_MIN_INTERVAL_S
    # a recent (no-since) read is never paced
    tsb.web_api_fetch("SPY", "1h", None, 10)
    assert len(slept) == 1 and len(venue) == 3
