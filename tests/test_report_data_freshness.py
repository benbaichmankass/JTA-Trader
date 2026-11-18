import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import report_data_freshness as rdf

NOW = datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)


def _w(p, name, last):
    (p / name).write_text(f"timestamp,open,close\n2026-01-01 00:00:00+00:00,1,1\n{last},1,1\n")


def test_fresh_stale_unreadable_and_exit_zero(tmp_path, capsys):
    _w(tmp_path, "AAA_15m.csv", "2026-11-18 20:15:00+00:00")
    _w(tmp_path, "BBB_15m.csv", "2026-06-18 00:00:00+00:00")
    _w(tmp_path, "CCC_1d.csv", "2026-11-15T00:00:00Z")
    (tmp_path / "DDD_5m.csv").write_text("timestamp,open\n")
    by = {r["file"]: r for r in rdf.report(tmp_path, NOW)}
    assert by["AAA_15m.csv"]["stale"] is False
    assert by["BBB_15m.csv"]["stale"] is True
    assert by["CCC_1d.csv"]["stale"] is False
    assert by["DDD_5m.csv"]["read_state"] == "unreadable" and by["DDD_5m.csv"]["last_bar"] is None
    assert rdf.main(["--data-dir", str(tmp_path)]) == 0
