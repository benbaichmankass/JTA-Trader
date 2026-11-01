"""fetch_binance_vision_funding: parses the archive shape, refuses a gap, refuses an empty series."""
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import fetch_binance_vision_funding as f  # noqa: E402

CSV = "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.00037409\n1704096000000,8,0.00027213\n"


def _zip(text: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", text)
    return b.getvalue()


class _Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content


class _Sess:
    def __init__(self, codes):
        self.codes, self.urls = codes, []

    def get(self, url, timeout=0):
        self.urls.append(url)
        c = self.codes.get(url[-11:-4], 200)
        return _Resp(c, _zip(CSV) if c == 200 else b"")


def test_parse_shape():
    df = f.parse_month_csv(CSV)
    assert list(df.columns) == ["timestamp", "funding_rate"] and len(df) == 2
    assert df["funding_rate"].iloc[0] == pytest.approx(0.00037409)


def test_fetch_uses_complete_months_only_and_orders():
    s = _Sess({})
    now = datetime(2024, 3, 15, tzinfo=timezone.utc)
    df = f.fetch("BTCUSDT", 90, now=now, session=s)
    assert all("2024-03" not in u for u in s.urls)  # the partial current month is never requested
    assert df["timestamp"].is_monotonic_increasing and not df.empty


def test_missing_month_is_an_error_not_a_skip():
    s = _Sess({"2024-01": 404})
    with pytest.raises(RuntimeError, match="HTTP 404"):
        f.fetch("BTCUSDT", 90, now=datetime(2024, 3, 15, tzinfo=timezone.utc), session=s)
