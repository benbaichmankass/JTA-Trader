"""Read-only Alpaca data client (ML-ENTRY-ALL-ACCOUNTS, RQ-20261104-a41f-01): the allowlist, paper-key preference and 429 back-off
are enforced in code (operator 2026-11-05 ~10:05Z: pull broker data for testing "as long as it doesn't interfere with trading")."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import alpaca_readonly as AR  # noqa: E402


class _R:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._b, self.headers, self.text = code, body or {}, headers or {}, "x"

    def json(self):
        return self._b


class _S:
    def __init__(self, seq):
        self.seq, self.urls = list(seq), []

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        return self.seq.pop(0)


def _client(seq, sleeps):
    return AR.AlpacaReadOnly("K", "S", session=_S(seq), sleep=sleeps.append, min_interval=0)


@pytest.mark.parametrize("method,url", [
    ("POST", "https://paper-api.alpaca.markets/v2/orders"), ("DELETE", "https://data.alpaca.markets/v2/stocks/bars"),
    ("GET", "https://paper-api.alpaca.markets/v2/orders"), ("GET", "https://api.alpaca.markets/v2/account"),
    ("GET", "https://api.alpaca.markets/v2/positions"), ("GET", "https://paper-api.alpaca.markets/v2/account"),
    ("GET", "http://data.alpaca.markets/v2/stocks/bars"), ("GET", "https://evil.example/v2/assets"),
    ("GET", "https://data.alpaca.markets/v2/stocks/bars/latest"), ("GET", "https://stream.data.alpaca.markets/v2/sip"),
])
def test_anything_off_the_allowlist_raises(method, url):
    with pytest.raises(AR.ReadOnlyViolation):
        AR.check_request(method, url)


def test_allowlist_is_exactly_bars_and_assets():
    assert AR.ALLOWED == {("data.alpaca.markets", "/v2/stocks/bars"), ("paper-api.alpaca.markets", "/v2/assets")}
    AR.check_request("GET", "https://data.alpaca.markets/v2/stocks/bars")
    AR.check_request("GET", "https://paper-api.alpaca.markets/v2/assets")


def test_get_refuses_an_off_list_endpoint_before_any_socket():
    s = _S([])
    c = AR.AlpacaReadOnly("K", "S", session=s, sleep=lambda x: None)
    with pytest.raises(AR.ReadOnlyViolation):
        c.get("paper-api.alpaca.markets", "/v2/orders")
    assert s.urls == []


def test_429_backs_off_then_succeeds_honouring_retry_after():
    sl = []
    c = _client([_R(429, headers={"Retry-After": "7"}), _R(429), _R(200, {"bars": {"SPY": [{"t": "x"}]}})], sl)
    assert c.bars(["SPY"], "1Hour", "2021-01-01T00:00:00Z", "2021-02-01T00:00:00Z") == {"SPY": [{"t": "x"}]}
    assert 7.0 in sl and 2.0 in sl and c.n_429 == 2


def test_persistent_429_raises_without_leaking_the_key():
    c = _client([_R(429)] * 3, [])
    c.max_retries = 3
    with pytest.raises(RuntimeError) as e:
        c.assets()
    assert "K" != str(e.value) and "S\"" not in str(e.value)


def test_pagination_collects_all_pages():
    sl = []
    c = _client([_R(200, {"bars": {"A": [1]}, "next_page_token": "t"}), _R(200, {"bars": {"A": [2], "B": [3]}})], sl)
    assert c.bars(["A", "B"], "1Day", "s", "e") == {"A": [1, 2], "B": [3]}


def test_paper_key_preferred_over_live(monkeypatch):
    for k, v in (("ALPACA_API_KEY_ID", "p"), ("ALPACA_API_SECRET_KEY", "ps"), ("ALPACA_API_KEY_ID_LIVE", "l"),
                 ("ALPACA_API_SECRET_KEY_LIVE", "ls")):
        monkeypatch.setenv(k, v)
    assert AR.AlpacaReadOnly.from_env().key_kind == "paper"
    monkeypatch.delenv("ALPACA_API_KEY_ID")
    assert AR.AlpacaReadOnly.from_env().key_kind == "live"
    monkeypatch.delenv("ALPACA_API_KEY_ID_LIVE")
    with pytest.raises(RuntimeError):
        AR.AlpacaReadOnly.from_env()
