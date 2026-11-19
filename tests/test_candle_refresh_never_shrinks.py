"""Plants the PI-20260929-FCJRWVAK-0002 defect: a 90-day pull over a
multi-year file must be refused; a refresh must only ever extend."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_backtest_candles as fbc  # noqa: E402
import refresh_candle_history as rch  # noqa: E402


def _frame(start, n):
    ts = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    px = 100.0 + pd.Series(range(n)).mul(0.37).mod(5).values  # moving series (MI-157 guard)
    return pd.DataFrame({"timestamp": ts, "open": px, "high": px + 0.1,
                         "low": px - 0.1, "close": px, "volume": 1.0})


def test_shorter_replacement_refused(tmp_path):
    p = tmp_path / "SOLUSDT_15m.csv"
    _frame("2024-01-01", 1000).to_csv(p, index=False)
    assert fbc.shrink_refusal(p, _frame("2024-01-05", 200)) is not None


def test_longer_or_equal_replacement_allowed(tmp_path):
    p = tmp_path / "SOLUSDT_15m.csv"
    _frame("2024-01-01", 1000).to_csv(p, index=False)
    assert fbc.shrink_refusal(p, _frame("2024-01-01", 1200)) is None
    assert fbc.shrink_refusal(tmp_path / "absent.csv", _frame("2024-01-01", 5)) is None


def test_main_refuses_and_leaves_file(tmp_path, monkeypatch):
    p = tmp_path / "SOLUSDT_15m.csv"
    _frame("2024-01-01", 1000).to_csv(p, index=False)
    before = p.read_bytes()
    short = _frame("2024-01-05", 50).to_dict("records")
    monkeypatch.setattr(fbc, "fetch_klines_binance_vision", lambda *a, **k: short)
    rc = fbc.main(["prog", "--symbol", "SOLUSDT", "--interval", "15", "--source",
                   "binance_vision", "--days", "3", "--output", str(p)])
    assert rc == 3 and p.read_bytes() == before


def test_merge_extend_appends_only_after_last():
    old = _frame("2024-01-01", 100)
    new = _frame("2024-01-01 12:00", 100)  # overlaps + extends
    out = rch.merge_extend(old, new)
    assert len(out) > len(old) and out["timestamp"].is_unique
    assert out.iloc[:100].equals(old)


# ---- review round (manager, 2026-09-30) ---------------------------------
from datetime import datetime, timezone  # noqa: E402


def _write(path, fmt_naive=False, n=90):
    df = _frame("2026-06-18 00:00", n)
    df["timestamp"] = [t.strftime("%Y-%m-%d %H:%M:%S") if fmt_naive else t.isoformat(sep=" ")
                       for t in df["timestamp"]]
    df.to_csv(path, index=False)


def _fake(monkeypatch, start, n):
    seen = {}
    def fake(sym, iv, s, e):
        seen["end_ms"] = e
        ts = pd.date_range(start, periods=n, freq="15min", tz="UTC")
        return [{"timestamp": t.to_pydatetime(), "open": 100.0 + i % 4, "high": 105.0, "low": 99.0,
                 "close": 100.0 + i % 4, "volume": 2.0}
                for i, t in enumerate(ts) if int(t.timestamp() * 1000) < e]
    monkeypatch.setattr(fbc, "fetch_klines", fake)
    return seen


def test_forming_bar_never_fetched_or_written(tmp_path, monkeypatch):
    p = tmp_path / "SOLUSDT_15m.csv"
    _write(p)
    seen = _fake(monkeypatch, "2026-06-19 07:00", 72)  # source would emit bars past 'now'
    now = datetime(2026, 6, 19, 23, 37, tzinfo=timezone.utc)
    rch.refresh_one(p, "SOLUSDT", "15", now)
    last = pd.read_csv(p)["timestamp"].iloc[-1]
    assert pd.Timestamp(last) == pd.Timestamp("2026-06-19 23:15", tz="UTC")  # 23:30 is forming
    assert seen["end_ms"] == int(datetime(2026, 6, 19, 23, 30, tzinfo=timezone.utc).timestamp() * 1000)


def test_naive_timestamp_file_stays_loadable(tmp_path, monkeypatch):
    p = tmp_path / "SOLUSDT_15m.csv"
    _write(p, fmt_naive=True, n=90)
    _fake(monkeypatch, "2026-06-19 00:00", 8)
    rch.refresh_one(p, "SOLUSDT", "15", datetime(2026, 6, 19, 6, 0, tzinfo=timezone.utc))
    df = pd.read_csv(p)
    assert len(df) > 90 and "+" not in df["timestamp"].iloc[-1]
    import candle_io
    assert len(candle_io.load_candles(str(p))) == len(df)


def test_mismatched_format_is_caught_and_original_untouched(tmp_path, monkeypatch):
    p = tmp_path / "SOLUSDT_15m.csv"
    _write(p, n=90)
    before = p.read_bytes()
    _fake(monkeypatch, "2026-06-19 00:00", 8)
    monkeypatch.setattr(rch, "ts_formatter", lambda s: (lambda t: t.strftime("%d/%m/%Y %H:%M")))
    try:
        rch.refresh_one(p, "SOLUSDT", "15", datetime(2026, 6, 19, 6, 0, tzinfo=timezone.utc))
        raise AssertionError("must refuse")
    except RuntimeError:
        pass
    assert p.read_bytes() == before and not (tmp_path / "SOLUSDT_15m.csv.tmp").exists()


def test_guard_fails_closed_on_unreadable_or_headerless(tmp_path):
    new = _frame("2024-01-01", 10)
    bad = tmp_path / "a.csv"
    bad.write_text("not,a,candle\n1,2,3\n")          # no timestamp column
    assert fbc.shrink_refusal(bad, new) is not None
    junk = tmp_path / "b.csv"
    junk.write_bytes(b"\x00\xff\xfe garbage")         # unreadable
    assert fbc.shrink_refusal(junk, new) is not None
    empty = tmp_path / "c.csv"
    empty.write_bytes(b"")                            # zero-byte: safe to replace
    assert fbc.shrink_refusal(empty, new) is None


def test_rate_limit_retries_are_bounded(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"retCode": 10006}
    monkeypatch.setattr(fbc.requests, "get", lambda *a, **k: R())
    slept = []
    monkeypatch.setattr(fbc.time, "sleep", lambda s: slept.append(s))
    try:
        fbc.fetch_klines("SOLUSDT", "15", 0, 10**13)
        raise AssertionError("must raise")
    except RuntimeError as exc:
        assert "10006" in str(exc)
    assert len(slept) == fbc._RATE_LIMIT_MAX_RETRIES


def test_flag_renamed_and_window_caller_passes_it():
    assert "--allow-window-replace" in (Path(__file__).resolve().parents[1] /
        "scripts/ops/vwap_backtest_sweep_action.sh").read_text()


def test_refresh_refuses_files_with_columns_it_cannot_fill():
    old = _frame("2024-01-01", 10)
    old["taker_buy_base"] = 1.0
    try:
        rch.merge_extend(old, _frame("2024-01-02", 10))
        raise AssertionError("must refuse")
    except RuntimeError as exc:
        assert "taker_buy_base" in str(exc)


def test_every_rolling_window_caller_opts_out_explicitly():
    root = Path(__file__).resolve().parents[1]
    for rel in ("scripts/ops/vwap_backtest_sweep_action.sh",
                ".github/workflows/vwap-backtest.yml",
                "scripts/prop/run_real_validation.sh"):
        text = (root / rel).read_text()
        import re
        assert re.search(r"fetch_backtest_candles\.py[^#]{0,400}--allow-window-replace", text), rel


# ---- TRAINER-INTRADAY-EQUITY-REFRESH (2026-11-19): file aliases + yfinance source --------------------
def test_parse_pair_forms(tmp_path):
    assert rch.parse_pair("SOLUSDT:15", tmp_path) == ("bybit", "SOLUSDT", "15", tmp_path / "SOLUSDT_15m.csv")
    assert rch.parse_pair("BTCUSDT:5=backtest_BTCUSDT_5m.csv", tmp_path) == (
        "bybit", "BTCUSDT", "5", tmp_path / "backtest_BTCUSDT_5m.csv")
    assert rch.parse_pair("yf:GC=F:60=GC_F_1h.csv", tmp_path) == ("yf", "GC=F", "60", tmp_path / "GC_F_1h.csv")
    import pytest
    with pytest.raises(ValueError):
        rch.parse_pair("SOLUSDT:7", tmp_path)


def test_btc_alias_extends_the_existing_backtest_file_in_its_own_spelling(tmp_path, monkeypatch):
    """No native BTCUSDT_5m.csv is created: the bars land in backtest_BTCUSDT_5m.csv, ISO-Z spelled like the file."""
    p = tmp_path / "backtest_BTCUSDT_5m.csv"
    ts = pd.date_range("2026-05-21 23:40", periods=4, freq="5min", tz="UTC")
    pd.DataFrame({"timestamp": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in ts], "open": 1.0, "high": 1.0,
                  "low": 1.0, "close": 1.0, "volume": 1.0}).to_csv(p, index=False)
    new = [{"timestamp": t.to_pydatetime(), "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}
           for t in pd.date_range("2026-05-21 23:55", periods=3, freq="5min", tz="UTC")]
    monkeypatch.setattr(rch.fbc, "fetch_klines", lambda *a, **k: new)
    assert rch.main(["--data-dir", str(tmp_path), "BTCUSDT:5=backtest_BTCUSDT_5m.csv"]) == 0
    out = pd.read_csv(p)
    assert len(out) == 6 and out["timestamp"].iloc[-1] == "2026-05-22T00:05:00Z"
    assert not (tmp_path / "BTCUSDT_5m.csv").exists()


def test_yfinance_source_extends_a_volumeless_file_and_drops_the_forming_bar(tmp_path, monkeypatch):
    p = tmp_path / "GC_F_1h.csv"
    ts = pd.date_range("2026-06-18 14:00", periods=3, freq="h", tz="UTC")
    pd.DataFrame({"timestamp": [t.isoformat(sep=" ") for t in ts], "open": 1.0, "high": 1.0, "low": 1.0,
                  "close": 1.0}).to_csv(p, index=False)
    now = datetime(2026, 6, 18, 19, 30, tzinfo=timezone.utc)
    calls = {}

    def fake_yf(ticker, interval, start_ms, end_ms):
        calls["args"] = (ticker, interval, start_ms, end_ms)
        return [{"timestamp": t.to_pydatetime(), "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 5.0}
                for t in pd.date_range("2026-06-18 17:00", periods=2, freq="h", tz="UTC")]
    monkeypatch.setitem(rch.SOURCES, "yf", fake_yf)
    msg = rch.refresh_one(p, "GC=F", "60", now, source="yf")
    out = pd.read_csv(p)
    assert list(out.columns) == ["timestamp", "open", "high", "low", "close"]      # no volume column invented
    assert out["timestamp"].iloc[-1] == "2026-06-18 18:00:00+00:00" and len(out) == 5, msg
    assert calls["args"][0] == "GC=F" and calls["args"][3] == int(datetime(2026, 6, 18, 19, tzinfo=timezone.utc).timestamp() * 1000)


def test_yfinance_alias_refuses_to_create(tmp_path, capsys):
    assert rch.main(["--data-dir", str(tmp_path), "yf:GC=F:60=GC_F_1h.csv"]) == 1
    assert "MISSING" in capsys.readouterr().err


def test_dukascopy_source_keeps_only_closed_rth_bars(tmp_path, monkeypatch):
    import types
    p = tmp_path / "SPY_1h.csv"
    ts = pd.date_range("2026-11-17 18:00", periods=2, freq="h", tz="UTC")
    pd.DataFrame({"timestamp": [t.isoformat(sep=" ") for t in ts], "open": 1.0, "high": 1.0, "low": 1.0,
                  "close": 1.0, "volume": 1.0}).to_csv(p, index=False)
    hours = pd.date_range("2026-11-18 13:00", periods=10, freq="h", tz="UTC")     # 13:00..22:00
    frame = pd.DataFrame({"timestamp": hours, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 3.0})
    import fetch_dukascopy_ohlcv as fd
    monkeypatch.setattr(fd, "fetch", lambda inst, s, e, iv: frame[(frame.timestamp >= s) & (frame.timestamp < e)])
    now = datetime(2026, 11, 18, 20, 30, tzinfo=timezone.utc)
    rch.refresh_one(p, "INSTRUMENT_ETF_CFD_US_SPY_US_USD", "60", now, source="dk")
    out = pd.read_csv(p)
    added = list(out["timestamp"].iloc[2:])
    # November = standard time: cash session 14:30-21:00 UTC -> hour bars 15:00..20:00; 20:00 is still forming at 20:30
    assert added == [f"2026-11-18 {h:02d}:00:00+00:00" for h in range(15, 20)], added
