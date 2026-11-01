"""fetch_etf_history / etf_history_verify / data_universe: yearly store, paging, split re-adjust refetch, no_data, resume, verdicts. No network."""
import json
import sys

import pandas as pd
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


def test_paging_month_partitions_and_incremental(tmp_path):
    s0 = datetime(2026, 1, 30, 20, tzinfo=UTC)  # 1m bars cross a month boundary
    allb = _bars(s0, 3000, step=timedelta(minutes=1))
    end = s0 + timedelta(days=3)
    r1 = f.update_symbol(fake_getter(allb[:2000], page=700), tmp_path, "SPY", "1m", "sip", s0, end, full=False)
    assert r1["status"] == "ok" and r1["rows"] == 2000 and set(r1["years"]) == {"2026"}
    names = sorted(p.name for p in (tmp_path / "SPY" / "1m").glob("*.parquet"))
    assert names == ["2026-01.parquet", "2026-02.parquet"]
    r2 = f.update_symbol(fake_getter(allb, page=700), tmp_path, "SPY", "1m", "sip", s0, end, full=False, prior=r1)
    assert r2["rows"] == 3000 and r2["added"] == 1000 and not r2["note"] and r2["first"] == r1["first"]
    df = f.read_bars(tmp_path, "SPY", "1m")
    assert len(df) == 3000 and df["timestamp"].is_monotonic_increasing
    assert len(f.read_bars(tmp_path, "SPY", "1m", start="2026-02-01")) == sum(1 for b in allb if b["t"] >= "2026-02-01")


def test_derived_timeframes_come_from_the_1m_base(tmp_path):
    s0 = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)  # a session open: the first UTC-hour bar is partial (30 of 60 minutes)
    bars = _bars(s0, 90, step=timedelta(minutes=1))
    for i, b in enumerate(bars):
        b["h"], b["l"], b["v"], b["vw"] = 200.0 + i, 50.0 + i, 10, 100.0
    f.update_symbol(fake_getter(bars, page=1000), tmp_path, "QQQ", "1m", "sip", s0, s0 + timedelta(hours=3), full=False)
    h = f.read_bars(tmp_path, "QQQ", "1h")
    assert not (tmp_path / "QQQ" / "1h").exists()  # derived, never stored
    assert list(h["n_base"]) == [30, 60] and list(h["complete"]) == [False, True]
    assert h.loc[0, "high"] == 200.0 + 29 and h.loc[0, "low"] == 50.0 and h.loc[0, "volume"] == 300 and h.loc[0, "vwap"] == 100.0
    assert h["timestamp"].iloc[0] == pd.Timestamp("2026-03-02 14:00", tz="UTC")  # labelled at the bar OPEN, whole-UTC-hour aligned
    m5 = f.read_bars(tmp_path, "QQQ", "5m")
    assert m5["n_base"].eq(5).all() and m5["complete"].all() and len(m5) == 18


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
    u = {"us_equity_bars": {"core": ["SPY"], "etfs": {"x": ["QQQ", "TYPO"]}, "extra": [], "timeframes": ["1m"],
                      "sp500_membership": None}, "options": {}}
    now = datetime(2026, 11, 3, tzinfo=UTC)
    fresh = {"status": "ok", "rows": 10, "first": "2016-01-04T14:30:00Z", "last": "2026-11-02T20:00:00Z", "long_gaps": 0, "feed": "sip"}
    stale = dict(fresh, last="2026-09-01T20:00:00Z")
    man = _manifest({"SPY/1m": fresh, "QQQ/1m": stale, "TYPO/1m": {"status": "no_data", "rows": 0}})
    rows = {r["symbol"]: r for r in ver.classify(u, man, ["1m"], now, 5.0, progress=False)}
    assert rows["SPY"]["verdict"] == "ok" and not rows["SPY"]["red"] and rows["SPY"]["years"] > 10
    assert rows["QQQ"]["verdict"] == "STALE" and rows["QQQ"]["red"]
    assert rows["TYPO"]["verdict"] == "NO_DATA" and rows["TYPO"]["red"]  # an expected-live symbol the vendor does not serve
    gone = ver.classify(u, _manifest({}), ["1m"], now, 5.0, progress=True)
    assert all(r["verdict"] == "PENDING" and not r["red"] for r in gone)
    assert all(r["verdict"] == "MISSING" and r["red"] for r in ver.classify(u, _manifest({}), ["1m"], now, 5.0, progress=False))


def test_universe_snapshot_union(tmp_path):
    snap = tmp_path / "us_equity_2026-11-01.csv"
    snap.write_text("symbol,name\nSPY,x\nNEWETF,y\n\nZZZ,z\n")
    u = du.load()
    base = du.equity_symbols(u)
    withsnap = du.equity_symbols(u, snapshot=snap)
    assert withsnap[:len(base)] == base and withsnap[len(base):] == ["NEWETF", "ZZZ"]


def test_ended_series_is_not_repulled_daily(tmp_path):
    s0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    bars = _bars(s0, 30, step=timedelta(minutes=1))
    end = datetime(2026, 11, 1, tzinfo=UTC)
    r1 = f.update_symbol(fake_getter(bars), tmp_path, "OLDCO", "1m", "sip", s0, s0 + timedelta(days=1), full=False)
    import shutil
    shutil.rmtree(tmp_path / "OLDCO")  # as on a runner that pulled only the current/previous month
    r2 = f.update_symbol(fake_getter(bars), tmp_path, "OLDCO", "1m", "sip", s0, end, full=False, prior=r1)
    assert r2["note"].startswith("ended") and r2["rows"] == r1["rows"] and r2["added"] == 0 and not (tmp_path / "OLDCO").exists()


def test_chunk_split_moves_only_finished_series(tmp_path):
    import etf_chunk_split as cs

    store, chunk = tmp_path / "store", tmp_path / "chunk"
    for sym in ("DONE", "TODO"):
        (store / sym / "1m").mkdir(parents=True)
        (store / sym / "1m" / "2026-11.parquet").write_bytes(b"x")
    (store / "corporate_actions.csv").write_text("kind\n")
    (store / "MANIFEST.json").write_text(json.dumps({"series": {
        "DONE/1m": {"fetched_at": "2026-11-01T13:00:00Z"}, "TODO/1m": {"fetched_at": "2026-10-31T02:00:00Z"}}}))
    assert cs.split(store, chunk, "2026-11-01T12:00:00Z") == 1
    assert (chunk / "DONE" / "1m" / "2026-11.parquet").exists() and not (store / "DONE" / "1m").exists()
    assert (store / "TODO" / "1m" / "2026-11.parquet").exists() and not (chunk / "TODO").exists()  # untouched, still local
    assert (chunk / "MANIFEST.json").exists() and (chunk / "corporate_actions.csv").exists()
