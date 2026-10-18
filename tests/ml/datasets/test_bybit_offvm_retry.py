"""The Bybit off-VM kline adapter retries Bybit's server-side transients.

MEASURED on the trainer (runtime_logs/trainer/dataset_builds.jsonl via
trainer-vm-diag #18882, read 2026-10-18): 12 ``market_raw`` build failures
between 2026-10-13 and 2026-10-18, every one
``ccxt.base.errors.ExchangeError: bybit {"retCode":10016,"retMsg":"svc error:
Get kline failed", ...}`` and every one on the FIRST attempt -- the retry loop
matched transient ccxt *class names* only, and 10016 arrives as a plain
``ExchangeError``. These tests pin: (a) a 10016 page is retried and the shard
completes; (b) a non-transient ``ExchangeError`` still raises first time;
(c) a transient that never clears gives up after the retry budget rather than
looping forever. ``time.sleep`` is patched so the suite stays fast.
"""
from __future__ import annotations

import pytest

from ml.datasets.adapters import BybitOffvmMarketRawAdapter
from ml.datasets.adapters import bybit_offvm as mod
from ml.datasets.adapters.bybit_offvm import OFFVM_ENV, _is_transient, _iso_to_ms


class _ExchangeError(Exception):
    """Stand-in for ``ccxt.base.errors.ExchangeError`` (ccxt is not a CI dep)."""


class _NetworkError(Exception):
    pass


_RET_10016 = ('bybit {"retCode":10016,"retMsg":"svc error: Get kline failed",'
              '"result":{},"retExtInfo":{},"time":1792281986933}')
_RET_10001 = 'bybit {"retCode":10001,"retMsg":"params error: symbol invalid","result":{}}'


class _FlakyExchange:
    """Replays a script of pages / exceptions, in order, one per fetch call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def fetch_ohlcv(self, symbol, *, timeframe, since, limit):
        self.calls += 1
        item = self._script.pop(0) if self._script else []
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    return slept


def _run(monkeypatch, fake, end="2025-01-01T02:00:00Z"):
    monkeypatch.setenv(OFFVM_ENV, "1")
    monkeypatch.setattr(BybitOffvmMarketRawAdapter, "_build_exchange",
                        classmethod(lambda cls, **kw: fake))
    return list(BybitOffvmMarketRawAdapter().iter_bars(
        symbol="BTCUSDT", timeframe="1h",
        start="2025-01-01T00:00:00Z", end=end))


def _bars(start_hour: int, n: int):
    return [[_iso_to_ms("2025-01-01T00:00:00Z") + (start_hour + i) * 3_600_000, 1, 2, 0, 1.5, 10]
            for i in range(n)]


def test_is_transient_classifies_bybit_ret_codes_and_ccxt_classes():
    assert _is_transient(_ExchangeError(_RET_10016))
    assert _is_transient(_ExchangeError('bybit {"retCode": 10002, "retMsg": "timeout"}'))
    assert _is_transient(_NetworkError("boom"))
    assert not _is_transient(_ExchangeError(_RET_10001))
    assert not _is_transient(ValueError("programming error"))


def test_ret_code_10016_is_retried_and_the_shard_completes(monkeypatch, no_sleep):
    page = [
        [_iso_to_ms("2025-01-01T00:00:00Z"), 1, 2, 0, 1.5, 10],
        [_iso_to_ms("2025-01-01T01:00:00Z"), 1.5, 2.5, 1, 2, 20],
    ]
    fake = _FlakyExchange([_ExchangeError(_RET_10016), _ExchangeError(_RET_10016), page])
    rows = _run(monkeypatch, fake)
    assert [r["ts"] for r in rows] == ["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"]
    assert fake.calls == 3
    assert no_sleep == [1, 2]   # exponential backoff, attempt-indexed


def test_non_transient_exchange_error_raises_on_first_attempt(monkeypatch, no_sleep):
    fake = _FlakyExchange([_ExchangeError(_RET_10001)])
    with pytest.raises(_ExchangeError):
        _run(monkeypatch, fake)
    assert fake.calls == 1
    assert no_sleep == []


def test_transient_that_never_clears_gives_up_after_the_budget(monkeypatch, no_sleep):
    fake = _FlakyExchange([_ExchangeError(_RET_10016)] * (mod._MAX_ATTEMPTS + 3))
    with pytest.raises(_ExchangeError):
        _run(monkeypatch, fake)
    assert fake.calls == mod._MAX_ATTEMPTS
    assert len(no_sleep) == mod._MAX_ATTEMPTS - 1


# ── empty pages (ML-SHARD-TRUNCATED) ────────────────────────────────────────
def test_empty_page_mid_history_is_refetched_and_the_fetch_continues(monkeypatch, no_sleep):
    """MEASURED 2026-10-18 (trainer-vm-diag #18889): BTCUSDT 1h cut at 27,000 rows (2024-11-15), ETHUSDT 1h at
    24,000, BTCUSDT 5m at 105,000 -- exact page multiples, rebuilt that way nightly -- because one empty page made
    the loop `break` and the builder wrote the prefix as an `ok` shard."""
    page_a, page_b = _bars(0, 2), _bars(2, 2)
    fake = _FlakyExchange([page_a, [], [], page_b])     # two transient empties, then data resumes
    rows = _run(monkeypatch, fake, end="2025-01-01T04:00:00Z")
    assert [r["ts"][11:13] for r in rows] == ["00", "01", "02", "03"]
    assert fake.calls == 4       # the window ends on page_b's last bar: no further fetch
    assert len(no_sleep) == 2    # the two re-fetches backed off


def test_persistent_empty_page_is_stepped_past_not_treated_as_end(monkeypatch, no_sleep):
    # 3 retries exhausted -> step one page (1000 bars) forward; data there -> continue
    page_far = [[_iso_to_ms("2025-01-01T00:00:00Z") + 1000 * 3_600_000 + i * 3_600_000, 1, 2, 0, 1.5, 10]
                for i in range(2)]
    fake = _FlakyExchange([_bars(0, 1), [], [], [], [], page_far])
    end = "2025-02-11T18:00:00Z"   # 1000 h + 2 bars after start
    rows = _run(monkeypatch, fake, end=end)
    # bar 0 + the bar at the stepped-to cursor (1001 h); the 1000 h bar sits before the advanced cursor and is
    # dropped by the pre-existing pre-window filter -- the point is that the fetch CONTINUED past the gap
    assert [r["ts"] for r in rows] == ["2025-01-01T00:00:00Z", "2025-02-11T17:00:00Z"]
    assert fake.calls == 6


def test_fetch_that_ends_far_before_end_raises_instead_of_writing_a_prefix(monkeypatch, no_sleep):
    # exchange answers one page then nothing for ever: never an `ok` shard
    fake = _FlakyExchange([_bars(0, 2)] + [[]] * 200)
    with pytest.raises(RuntimeError, match="truncated shard"):
        _run(monkeypatch, fake, end="2025-12-31T00:00:00Z")
