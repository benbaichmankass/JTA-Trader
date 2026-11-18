import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import refresh_funding_history as r

NOW = datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)


def _ts(day, hour):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def test_extends_with_the_files_own_spelling_and_keeps_old_rows(tmp_path):
    p = tmp_path / "funding_BTCUSDT.csv"
    p.write_text("timestamp,funding_rate\n2026-11-16 00:00:00+00:00,0.0001\n2026-11-16 08:00:00+00:00,0.0002\n")
    before = p.read_text()
    def fake(symbol, start_ms, end_ms):
        return [{"timestamp": _ts(16, 8), "funding_rate": 0.0002},  # duplicate, dropped
                {"timestamp": _ts(16, 16), "funding_rate": 0.0003},
                {"timestamp": _ts(17, 0), "funding_rate": 0.0004}]

    msg = r.refresh_one(p, "BTCUSDT", NOW, fetch=fake)
    after = p.read_text()
    assert after.startswith(before) and after.count("\n") == before.count("\n") + 2
    assert "2026-11-17 00:00:00+00:00,0.0004" in after and "rows" in msg


def _none(*args):
    return []


def test_wrong_header_is_refused_and_untouched(tmp_path):
    p = tmp_path / "funding_ETHUSDT.csv"
    p.write_text("ts,rate\n1,2\n")
    assert "REFUSED" in r.refresh_one(p, "ETHUSDT", NOW, fetch=_none)
    assert p.read_text() == "ts,rate\n1,2\n"


def test_missing_file_is_not_created(tmp_path):
    assert r.main(["--data-dir", str(tmp_path), "XRPUSDT"]) == 1
    assert not (tmp_path / "funding_XRPUSDT.csv").exists()


def test_unrecognised_spelling_is_refused_via_main(tmp_path, capsys):
    p = tmp_path / "funding_SOLUSDT.csv"
    p.write_text("timestamp,funding_rate\n2026/11/16,0.0001\n2026/11/17,0.0002\n")
    before = p.read_text()
    assert r.main(["--data-dir", str(tmp_path), "SOLUSDT"]) == 1  # FAILED is reported, rc 1
    assert p.read_text() == before


def test_iso_z_spelling_is_reproduced(tmp_path):
    p = tmp_path / "funding_ETHUSDT.csv"
    p.write_text("timestamp,funding_rate\n2026-11-16T00:00:00Z,0.0001\n2026-11-16T08:00:00Z,0.0002\n")
    def fake(symbol, start_ms, end_ms):
        return [{"timestamp": _ts(16, 16), "funding_rate": 0.0003}]

    r.refresh_one(p, "ETHUSDT", NOW, fetch=fake)
    assert p.read_text().splitlines()[-1] == "2026-11-16T16:00:00Z,0.0003"
