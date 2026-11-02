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
