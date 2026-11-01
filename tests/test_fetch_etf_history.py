"""fetch_etf_history / etf_history_verify: paging, split re-adjust refetch, shrink refusal, freshness. No network."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
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
        lo, hi = params["start"], params["end"]
        sel = [b for b in series if lo <= b["t"] <= hi]
        i = int(params.get("page_token", 0))
        nxt = str(i + page) if i + page < len(sel) else None
        return {"bars": {params["symbols"]: sel[i:i + page]}, "next_page_token": nxt}
    return get


def test_paging_and_incremental(tmp_path):
    s0 = datetime(2026, 10, 1, 14, tzinfo=UTC)
    allb = _bars(s0, 10)
    end = s0 + timedelta(days=2)
    r1 = f.update_symbol(fake_getter(allb[:7]), tmp_path, "SPY", "1h", "sip", s0, end, full=True)
    assert r1["rows"] == 7 and r1["feed"] == "sip"
    r2 = f.update_symbol(fake_getter(allb), tmp_path, "SPY", "1h", "sip", s0, end, full=False)
    assert r2["rows"] == 10 and r2["added"] == 3 and not r2["note"]
    assert f.read_bars(tmp_path, "SPY", "1h")["timestamp"].is_monotonic_increasing


def test_split_readjust_refetches(tmp_path):
    s0 = datetime(2026, 10, 1, 14, tzinfo=UTC)
    end = s0 + timedelta(days=2)
    f.update_symbol(fake_getter(_bars(s0, 5, 100.0)), tmp_path, "XLE", "1h", "iex", s0, end, full=True)
    r = f.update_symbol(fake_getter(_bars(s0, 8, 50.0)), tmp_path, "XLE", "1h", "iex", s0, end, full=False)
    assert "re-adjusted" in r["note"]
    assert f.read_bars(tmp_path, "XLE", "1h")["close"].eq(50.0).all()


def test_refuses_shrink(tmp_path):
    s0 = datetime(2026, 10, 1, 14, tzinfo=UTC)
    end = s0 + timedelta(days=2)
    f.update_symbol(fake_getter(_bars(s0, 6)), tmp_path, "GLD", "1h", "sip", s0, end, full=True)
    with pytest.raises(RuntimeError, match="shrinking"):
        f.update_symbol(fake_getter(_bars(s0, 2, 999.0)), tmp_path, "GLD", "1h", "sip", s0, end, full=False)


def test_freshness(tmp_path):
    now = datetime.now(UTC)
    f.update_symbol(fake_getter(_bars(now - timedelta(days=20), 5)), tmp_path, "SPY", "1h", "sip", now - timedelta(days=21), now, full=True)
    assert ver.main(["--root", str(tmp_path), "--symbols", "SPY", "--tfs", "1h"]) == 1  # last bar ~20d old -> stale
    f.update_symbol(fake_getter(_bars(now - timedelta(hours=5), 3)), tmp_path, "QQQ", "1h", "sip", now - timedelta(days=1), now, full=True)
    assert ver.main(["--root", str(tmp_path), "--symbols", "QQQ", "--tfs", "1h", "--ref", "QQQ"]) == 0
