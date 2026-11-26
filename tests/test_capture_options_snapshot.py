"""capture_options_snapshot: OCC parse, slice to first N expiries, NaN-not-zero, idempotent day file, freshness. No network."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import capture_options_snapshot as c  # noqa: E402

TODAY = date(2026, 11, 2)


def _snap(iv=0.2, bid=1.0):
    return {"latestQuote": {"bp": bid, "ap": bid + 0.1, "bs": 1, "as": 2, "t": "2026-11-02T20:59:00Z"},
            "latestTrade": {"p": 1.05, "t": "2026-11-02T20:58:00Z"}, "impliedVolatility": iv,
            "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.2, "rho": 0.01} if iv else {}}


def getter(path, params):
    if "trades/latest" in path:
        return {"trade": {"p": 500.0}}
    snaps = {}
    for exp in ("261102", "261104", "261106", "261113"):  # 4 expiries -> only 3 kept
        snaps[f"SPY{exp}C00500000"] = _snap()
        snaps[f"SPY{exp}P00500000"] = _snap(iv=None)  # illiquid: no IV/greeks
    snaps["SPYW261102C00500000"] = _snap()  # different root: dropped
    return {"snapshots": snaps}


def test_parse_occ():
    p = c.parse_occ("SPY261102C00500000")
    assert p == {"root": "SPY", "expiry": date(2026, 11, 2), "cp": "C", "strike": 500.0}
    assert c.parse_occ("garbage") is None


def test_capture_slice_and_nan(tmp_path):
    rec = c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")
    assert rec["rows"] == 6 and rec["expiries"] == 3
    df = __import__("pandas").read_parquet(tmp_path / "SPY" / "2026-11-02.parquet")
    assert df["iv"].isna().sum() == 3 and (df["iv"].dropna() > 0).all()  # absent stays NaN, never 0
    c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")  # idempotent
    assert len(list((tmp_path / "SPY").glob("*.parquet"))) == 1


def test_verify_freshness(tmp_path):
    c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")
    assert c.verify(tmp_path, ["SPY"], 4.0, datetime(2026, 11, 4, tzinfo=timezone.utc)) == 0
    assert c.verify(tmp_path, ["SPY"], 4.0, datetime(2026, 11, 20, tzinfo=timezone.utc)) == 1
    assert c.verify(tmp_path, ["QQQ"], 4.0, datetime(2026, 11, 4, tzinfo=timezone.utc)) == 1


def test_cboe_source_zero_is_absent(tmp_path):
    j = {"timestamp": "2026-11-02 15:59:00", "data": {"current_price": 500.0, "options": [
        {"option": "B1SPY261102C00500000", "bid": 1.0, "ask": 1.1, "iv": 0.0, "open_interest": 7.0, "volume": 3.0, "delta": 0.5,
         "last_trade_price": 0.0, "last_trade_time": None},
        {"option": "SPY261104P00500000", "bid": 2.0, "ask": 2.1, "iv": 0.21, "open_interest": 9.0, "volume": 1.0, "delta": -0.5},
        {"option": "SPY261104C00900000", "bid": 0.0, "ask": 0.0, "iv": 0.0}]}}  # far OTM: dropped by moneyness
    rec = c.capture(lambda path, params: j, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", source="cboe")
    assert rec["rows"] == 2 and rec["feed"] == "cboe_delayed"
    df = __import__("pandas").read_parquet(tmp_path / "SPY" / "2026-11-02.parquet")
    assert df["iv"].isna().sum() == 1 and df["open_interest"].tolist() == [7.0, 9.0]


# ── option A probe (CBOE-OPTIONS-SOURCE-BLOCKED): the shapes open interest and volume must come from are MEASURED, never assumed ──
def _probe_get(path, params):
    if "trades/latest" in path:
        return {"trade": {"p": 500.0}}
    if "snapshots" in path:
        s = _snap()
        s["dailyBar"] = {"o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1, "v": 321, "n": 7, "vw": 1.05, "t": "2026-11-02T05:00:00Z"}
        return {"snapshots": {"SPY261102C00500000": s, "SPY261102P00500000": _snap(iv=None)}}
    if "bars" in path:
        return {"bars": {params["symbols"]: [{"t": "2026-11-02T05:00:00Z", "v": 321, "c": 1.1}]}}
    raise AssertionError(path)


def _probe_tget(path, params):
    assert path == "/v2/options/contracts" and params["underlying_symbols"] == "SPY"      # a listing GET, nothing else
    return {"option_contracts": [{"symbol": "SPY261102C00500000", "open_interest": "1234", "open_interest_date": "2026-11-01"},
                                 {"symbol": "SPY261102P00500000", "open_interest": None, "open_interest_date": None}],
            "next_page_token": None}


def test_probe_shapes_reports_where_volume_and_open_interest_live():
    rows = {r["shape"]: r for r in c.probe_shapes(_probe_get, _probe_tget, TODAY)}
    assert rows["snapshot"]["with_dailyBar"] == 1 and rows["snapshot"]["dailyBar"]["v"] == 321
    assert rows["contracts"]["n_page"] == 2 and rows["contracts"]["with_open_interest"] == 1
    assert rows["contracts"]["oi_dates"] == ["2026-11-01"] and "open_interest" in rows["contracts"]["keys"]
    assert rows["bars"]["newest"]["v"] == 321


def test_probe_shapes_never_raises_a_refused_call_is_a_finding():
    def boom(path, params):
        raise RuntimeError("HTTP 403 " + path)
    rows = {r["shape"]: r for r in c.probe_shapes(lambda p, q: {"trade": {"p": 500.0}} if "trades" in p else boom(p, q), boom, TODAY)}
    assert rows["snapshot"]["status"] == "error" and rows["contracts"]["status"] == "error" and "403" in rows["contracts"]["error"]
    assert "bars" not in rows                                                         # no symbol to ask about
