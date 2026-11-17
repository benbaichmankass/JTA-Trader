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


def test_threads_share_one_pacing_clock():
    import threading
    sl = []
    c = AR.AlpacaReadOnly("K", "S", session=_S([_R(200, {"bars": {}}) for _ in range(8)]), sleep=sl.append, min_interval=0.5)
    ts = [threading.Thread(target=lambda: c.get("data.alpaca.markets", "/v2/stocks/bars", {})) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert c.calls == 8
    # slots are handed out 0.5s apart on ONE clock: the 8 waits are spread over >= 7 * 0.5s, never 8 simultaneous calls
    assert max(sl) >= 3.0 and len(sl) >= 7, sl


# ── RUNNER-ALPACA-BARS-THROTTLE (2026-11-17): RQ-20261108-98e3-15 died twice at symbol 22/25 of 173 with ~30% of calls throttled ──
def test_a_long_429_storm_is_ridden_out_instead_of_killing_the_run():
    """Before: 8 attempts (~3 min of waiting) then RuntimeError. A bucket shared with other jobs stays throttled longer than that."""
    sl = []
    c = AR.AlpacaReadOnly("K", "S", session=_S([_R(429)] * 15 + [_R(200, {"bars": {"SPY": [1]}})]), sleep=sl.append, min_interval=0)
    assert AR.AlpacaReadOnly("K", "S", session=object()).max_retries == 20
    assert c.bars(["SPY"], "1Hour", "s", "e") == {"SPY": [1]} and c.n_429 == 15
    assert max(sl) == 60.0                                     # the per-wait cap is unchanged


def test_a_storm_that_never_ends_still_raises_after_max_retries_without_leaking_the_key():
    """Negative control: the retry budget is bounded, so a dead endpoint is a loud failure, not an infinite loop."""
    c = AR.AlpacaReadOnly("K", "S", session=_S([_R(429)] * 25), sleep=lambda x: None, min_interval=0)
    with pytest.raises(RuntimeError, match="still throttled/unavailable after 20 attempts") as e:
        c.assets()
    assert "S\"" not in str(e.value)


def test_pacing_widens_on_429_is_capped_and_decays_back_to_the_floor():
    c = AR.AlpacaReadOnly("K", "S", session=_S([_R(429)] * 3 + [_R(200, {"bars": {}})] * 400), sleep=lambda x: None, min_interval=0.4,
                          max_interval=1.0)
    c.get("data.alpaca.markets", "/v2/stocks/bars", {})
    assert 0.9 < c._interval <= 1.0                            # 0.4 -> 0.6 -> 0.9 -> 1.0 (capped), then one good call took 2% off
    for _ in range(399):
        c.get("data.alpaca.markets", "/v2/stocks/bars", {})
    assert c._interval == pytest.approx(0.4)                   # never below the configured floor
