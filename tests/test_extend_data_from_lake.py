import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import extend_data_from_lake as e

HDR = "timestamp,open,high,low,close,volume\n"


def _csv(p, days, close):
    p.write_text(HDR + "".join(f"{d} 00:00:00+00:00,1,1,1,{close},5\n" for d in days))


def _lake(p, days, close):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps({"ts": f"{d}T00:00:00Z", "open": 1, "high": 1, "low": 1,
                                     "close": close, "volume": 5}) + "\n" for d in days))


def _days(n, start=1):
    return [f"2026-01-{i:02d}" for i in range(start, start + n)]


def test_extends_only_new_bars_and_keeps_old_rows(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv(data / "GC_F_1d.csv", _days(25), 100.0)
    _lake(lake / "MGC/1d/v002/data.jsonl", _days(28), 100.0)
    before = (data / "GC_F_1d.csv").read_text()
    assert e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"]) == 0
    after = (data / "GC_F_1d.csv").read_text()
    assert after.startswith(before) and after.count("\n") == before.count("\n") + 3
    assert not (data / "MGC_1d.csv").exists()  # proxy name, never the micro name


def test_basis_mismatch_is_refused_and_file_untouched(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv(data / "SPY_1d.csv", _days(25), 100.0)
    _lake(lake / "SPY/1d/v002/data.jsonl", _days(28), 90.0)
    before = (data / "SPY_1d.csv").read_text()
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    assert (data / "SPY_1d.csv").read_text() == before


def test_dry_run_default_writes_nothing(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv(data / "QQQ_1d.csv", _days(25), 100.0)
    _lake(lake / "QQQ/1d/v002/data.jsonl", _days(28), 100.0)
    before = (data / "QQQ_1d.csv").read_text()
    e.main(["--data-dir", str(data), "--lake", str(lake)])
    assert (data / "QQQ_1d.csv").read_text() == before
