"""``AlpacaMarketData.get_bars_multi`` (row ML-EQ-ENTRY-TIMING): one multi-symbol request per chunk, every page read, a chunk with a failed page
dropped WHOLE (a symbol cut mid-page must not look complete), the shared non-blocking cooldown honoured, and frames identical to ``get_ohlcv``'s."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.exchange import alpaca_connector as AC  # noqa: E402


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


def test_pages_are_followed_and_frames_match_get_ohlcv(monkeypatch):
    pages = [
        {"bars": {"SPY": [_bar("2026-11-12T14:00:00Z", 1.0), _bar("2026-11-12T15:00:00Z", 2.0)]}, "next_page_token": "p2"},
        {"bars": {"SPY": [_bar("2026-11-12T16:00:00Z", 3.0)], "QQQ": [_bar("2026-11-12T15:00:00Z", 9.0)]}, "next_page_token": None},
    ]
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params)))
        return _Resp(pages[len(calls) - 1])
    monkeypatch.setattr(AC.requests, "get", fake_get)
    md = AC.AlpacaMarketData(api_key="k", api_secret="s", feed="sip")
    frames, states = md.get_bars_multi(["SPY", "QQQ", "NONE"], "1h", "2026-11-01T00:00:00Z")
    assert len(calls) == 2 and calls[0][0].endswith("/v2/stocks/bars") and calls[1][1]["page_token"] == "p2"
    p = calls[0][1]
    assert p["symbols"] == "SPY,QQQ,NONE" and p["feed"] == "sip" and p["adjustment"] == "split" and p["timeframe"] == "1Hour"
    assert states == {"SPY": "ok", "QQQ": "ok", "NONE": "empty"}
    assert list(frames["SPY"]["close"]) == [1.0, 2.0, 3.0]
    assert frames["SPY"].equals(AC._bars_frame(pages[0]["bars"]["SPY"] + pages[1]["bars"]["SPY"]))


def test_a_failed_later_page_drops_the_whole_chunk_and_chunks_are_independent(monkeypatch):
    n = {"c": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        n["c"] += 1
        if params["symbols"] == "A,B":
            if params.get("page_token"):
                return _Resp({}, status=400)
            return _Resp({"bars": {"A": [_bar("2026-11-12T15:00:00Z", 1.0)]}, "next_page_token": "x"})
        return _Resp({"bars": {"C": [_bar("2026-11-12T15:00:00Z", 5.0)]}, "next_page_token": None})
    monkeypatch.setattr(AC.requests, "get", fake_get)
    md = AC.AlpacaMarketData(api_key="k", api_secret="s", feed="sip")
    frames, states = md.get_bars_multi(["A", "B", "C"], "1h", "2026-11-01T00:00:00Z", chunk=2)
    assert states == {"A": "could_not_look", "B": "could_not_look", "C": "ok"}
    assert set(frames) == {"C"}


def test_rate_limit_starts_the_cooldown_and_never_sleeps(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({}, status=429)
    monkeypatch.setattr(AC.requests, "get", fake_get)
    monkeypatch.setattr(AC.time, "sleep", lambda *_a: (_ for _ in ()).throw(AssertionError("must not sleep")))
    md = AC.AlpacaMarketData(api_key="k", api_secret="s", feed="sip")
    frames, states = md.get_bars_multi(["A", "B"], "1h", "2026-11-01T00:00:00Z")
    assert frames == {} and states == {"A": "rate_limited", "B": "rate_limited"}
    assert AC._cooldown_remaining() > 0
    frames, states = md.get_bars_multi(["A"], "1h", "2026-11-01T00:00:00Z")   # during the cooldown: no call, named state
    assert states == {"A": "rate_limited"}
