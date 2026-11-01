"""fetch_etf_history / etf_history_verify / data_universe: yearly store, paging, split re-adjust refetch, no_data, resume, verdicts. No network."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import data_universe as du  # noqa: E402
import etf_history_verify as ver  # noqa: E402
import fetch_etf_history as f  # noqa: E402

UTC = timezone.utc


def _bars(start, n, px=100.0, step=timedelta(hours=1)):
    return [{"t": (start + i * step).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": px, "h": px + 1, "l": px - 1, "c": px,
             "v": 10, "n": 1, "vw": px} for i in range(n)]


def fake_getter(series, page=3):
    """Serves `series` (list of bar dicts) in pages of `page`, honouring start/end/page_token."""
    def get(path, params):
        assert path == "/v2/stocks/bars" and params["adjustment"] == "split"
        sel = [b for b in series if params["start"] <= b["t"] <= params["end"]]
        i = int(params.get("page_token", 0))
        return {"bars": {params["symbols"]: sel[i:i + page]}, "next_page_token": str(i + page) if i + page < len(sel) else None}
    return get


def test_paging_year_split_and_incremental(tmp_path):
    s0 = datetime(2025, 12, 30, 14, tzinfo=UTC)  # crosses a year boundary
    allb = _bars(s0, 60, step=timedelta(hours=12))
    end = s0 + timedelta(days=40)
    r1 = f.update_symbol(fake_getter(allb[:40]), tmp_path, "SPY", "1h", "sip", s0, end, full=False)
    assert r1["status"] == "ok" and r1["rows"] == 40 and set(r1["years"]) == {"2025", "2026"}
    assert (tmp_path / "SPY" / "1h" / "2025.parquet").exists() and (tmp_path / "SPY" / "1h" / "2026.parquet").exists()
    r2 = f.update_symbol(fake_getter(allb), tmp_path, "SPY", "1h", "sip", s0, end, full=False, prior=r1)
    assert r2["rows"] == 60 and r2["added"] == 20 and not r2["note"] and r2["first"] == r1["first"]
    df = f.read_bars(tmp_path, "SPY", "1h")
    assert len(df) == 60 and df["timestamp"].is_monotonic_increasing
    assert len(f.read_bars(tmp_path, "SPY", "1h", start="2026-01-01")) == sum(1 for b in allb if b["t"] >= "2026-01-01")


def test_split_readjust_refetches(tmp_path):
    s0 = datetime(2026, 10, 1, 14, tzinfo=UTC)
    end = s0 + timedelta(days=5)
    r1 = f.update_symbol(fake_getter(_bars(s0, 5, 100.0)), tmp_path, "XLE", "1h", "iex", s0, end, full=False)
    r = f.update_symbol(fake_getter(_bars(s0, 8, 50.0)), tmp_path, "XLE", "1h", "iex", s0, end, full=False, prior=r1)
    assert "re-adjusted" in r["note"]
    assert f.read_bars(tmp_path, "XLE", "1h")["close"].eq(50.0).all() and r["rows"] == 8


def test_no_data_is_measured_not_an_error(tmp_path):
    s0 = datetime(2026, 10, 1, tzinfo=UTC)
    r = f.update_symbol(fake_getter([]), tmp_path, "DEADCO", "1h", "sip", s0, s0 + timedelta(days=3), full=False)
    assert r["status"] == "no_data" and r["rows"] == 0 and not (tmp_path / "DEADCO").exists()


def test_universe_loads_and_orders():
    u = du.load()
    syms = du.equity_symbols(u)
    assert syms[:3] == ["SPY", "QQQ", "IWM"] and len(syms) == len(set(syms)) and len(syms) > 700
    assert len(du.options_underlyings(u)) >= 50 and set(du.delisted_symbols(u)) <= set(syms)


def _manifest(entries):
    return {"series": entries}


def test_verify_verdicts():
    u = {"equities": {"core": ["SPY"], "etfs": {"x": ["QQQ", "TYPO"]}, "extra": [], "timeframes": ["1h"],
                      "sp500_membership": None}, "options": {}}
    now = datetime(2026, 11, 3, tzinfo=UTC)
    fresh = {"status": "ok", "rows": 10, "first": "2016-01-04T14:30:00Z", "last": "2026-11-02T20:00:00Z", "long_gaps": 0, "feed": "sip"}
    stale = dict(fresh, last="2026-09-01T20:00:00Z")
    man = _manifest({"SPY/1h": fresh, "QQQ/1h": stale, "TYPO/1h": {"status": "no_data", "rows": 0}})
    rows = {r["symbol"]: r for r in ver.classify(u, man, ["1h"], now, 5.0, progress=False)}
    assert rows["SPY"]["verdict"] == "ok" and not rows["SPY"]["red"] and rows["SPY"]["years"] > 10
    assert rows["QQQ"]["verdict"] == "STALE" and rows["QQQ"]["red"]
    assert rows["TYPO"]["verdict"] == "NO_DATA" and rows["TYPO"]["red"]  # an expected-live symbol the vendor does not serve
    gone = ver.classify(u, _manifest({}), ["1h"], now, 5.0, progress=True)
    assert all(r["verdict"] == "PENDING" and not r["red"] for r in gone)
    assert all(r["verdict"] == "MISSING" and r["red"] for r in ver.classify(u, _manifest({}), ["1h"], now, 5.0, progress=False))
