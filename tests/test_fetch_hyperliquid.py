"""HL-DATA-FETCHER: paging, the coin -> file mapping, and merge-append accrual (no network)."""
from __future__ import annotations

import csv

import pytest

from scripts.ops import fetch_hyperliquid as fh

H = 3_600_000
T0 = 1_762_000_000_000 - (1_762_000_000_000 % H)


def _fake_candles(n_total, page_size=3):
    bars = [{"t": T0 + i * H, "o": "1", "h": "2", "l": "0.5", "c": str(1 + i), "v": "10"} for i in range(n_total)]
    calls = []

    def post(body):
        calls.append(body)
        st = body["req"]["startTime"]
        return [b for b in bars if b["t"] >= st][:page_size]
    return post, calls


def test_candles_page_forward_until_the_api_runs_dry():
    post, calls = _fake_candles(7, page_size=3)
    rows = fh.fetch_candles("xyz:SILVER", "1h", T0, T0 + 100 * H, post=post, sleep=lambda s: None)
    assert [r["close"] for r in rows] == [str(1 + i) for i in range(7)]
    assert len(calls) == 4 and calls[0]["req"]["coin"] == "xyz:SILVER"     # 3 + 3 + 1, then an empty page


def test_funding_pages_and_keeps_the_hourly_rate():
    data = [{"time": T0 + i * H, "fundingRate": "0.0000125", "premium": "0.0001"} for i in range(5)]
    post = lambda b: [d for d in data if d["time"] >= b["startTime"]][:2]   # noqa: E731
    rows = fh.fetch_funding("BTC", T0, T0 + 10 * H, post=post, sleep=lambda s: None)
    assert len(rows) == 5 and rows[0]["funding_rate"] == "0.0000125"


def test_merge_write_accrues_and_never_truncates(tmp_path):
    p = tmp_path / "xyz_SILVER_1h.csv"
    post, _ = _fake_candles(5)
    first = fh.merge_write(p, fh.fetch_candles("xyz:SILVER", "1h", T0, T0 + 100 * H, post=post, sleep=lambda s: None),
                           fh.CANDLE_COLS)
    assert first == {"before": 0, "fetched": 5, "after": 5}
    later = [{"timestamp": fh._iso(T0 + 4 * H), "open": "9", "high": "9", "low": "9", "close": "9", "volume": "1"},
             {"timestamp": fh._iso(T0 + 5 * H), "open": "1", "high": "1", "low": "1", "close": "6", "volume": "1"}]
    second = fh.merge_write(p, later, fh.CANDLE_COLS)                        # the API window moved on: old rows stay
    assert second == {"before": 5, "fetched": 2, "after": 6}
    rows = list(csv.DictReader(p.open()))
    assert [r["close"] for r in rows] == ["1", "2", "3", "4", "9", "6"] and list(rows[0]) == list(fh.CANDLE_COLS)


def test_a_failing_page_raises_after_retries_and_leaves_the_file_alone(tmp_path, capsys, monkeypatch):
    p = tmp_path / "BTC_1h.csv"
    p.write_text("timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,1,1,1,1\n")

    def boom(body):
        raise OSError("down")
    monkeypatch.setattr(fh, "_post", boom)
    monkeypatch.setattr(fh.time, "sleep", lambda s: None)
    assert fh.main(["--coin", "BTC", "--out", str(tmp_path)]) == 1
    assert p.read_text().count("\n") == 2                                    # untouched
    assert '"error"' in capsys.readouterr().out


@pytest.mark.parametrize("coin,name", [("BTC", "BTC"), ("xyz:SILVER", "xyz_SILVER"), ("xyz:XYZ100", "xyz_XYZ100")])
def test_file_names_are_filesystem_safe(coin, name):
    assert fh.safe_name(coin) == name
