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


def test_basis_mismatch_is_ratio_spliced_with_sidecar(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv(data / "SPY_1d.csv", _days(25), 100.0)
    _lake(lake / "SPY/1d/v002/data.jsonl", _days(28), 90.0)  # adjusted basis, 10% lower
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    lines = (data / "SPY_1d.csv").read_text().splitlines()
    assert len(lines) == 1 + 28
    assert float(lines[-1].split(",")[4]) == 100.0  # 90 * (100/90): continuous with the file
    assert lines[-1].split(",")[5] == "5.0"  # volume untouched
    side = json.loads((data / "SPY_1d.csv.splice.json").read_text())["splices"][0]
    assert abs(side["ratio"] - 100 / 90) < 1e-9 and side["splice_day"] == "2026-01-25"
    assert side["lake_version"] == "v002" and abs(side["splice_return"]) < 1e-9


def test_splice_refused_when_ratio_out_of_range(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv(data / "SPY_1d.csv", _days(25), 100.0)
    _lake(lake / "SPY/1d/v002/data.jsonl", _days(28), 50.0)
    before = (data / "SPY_1d.csv").read_text()
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    assert (data / "SPY_1d.csv").read_text() == before
    assert not (data / "SPY_1d.csv.splice.json").exists()


def test_splice_refused_on_discontinuity(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    days = _days(25)
    (data / "SPY_1d.csv").write_text(HDR + "".join(
        f"{d} 00:00:00+00:00,1,1,1,{100.0 + 0.01 * i},5\n" for i, d in enumerate(days)))
    rows = [{"ts": f"{d}T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 90.0 + 0.01 * i, "volume": 5}
            for i, d in enumerate(days)]
    rows.append({"ts": "2026-01-26T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 99.0, "volume": 5})  # +10% gap after rescale
    p = lake / "SPY/1d/v002/data.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
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


def test_new_rows_mirror_the_file_timestamp_format(tmp_path):
    """Regression (2026-11-18 trainer apply): a date-only file got rows like
    '2026-11-16 00:00:00-07-07' because the date's '-MM-DD' tail was read as a UTC offset."""
    import pandas as pd
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    (data / "GC_F_1d.csv").write_text(HDR + "".join(f"{d},1,1,1,100.0,5\n" for d in _days(25)))
    (data / "ES_F_1d.csv").write_text(HDR + "".join(f"{d}T00:00:00Z,1,1,1,100.0,5\n" for d in _days(25)))
    (data / "HG_F_1d.csv").write_text(HDR + "".join(f"{d} 00:00:00-05:00,1,1,1,100.0,5\n" for d in _days(25)))
    for sym in ("MGC", "MES", "MHG"):
        _lake(lake / f"{sym}/1d/v002/data.jsonl", _days(28), 100.0)
    assert e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"]) == 0
    tails = {f: (data / f).read_text().splitlines()[-1].split(",")[0]
             for f in ("GC_F_1d.csv", "ES_F_1d.csv", "HG_F_1d.csv")}
    assert tails == {"GC_F_1d.csv": "2026-01-28", "ES_F_1d.csv": "2026-01-28T00:00:00Z",
                     "HG_F_1d.csv": "2026-01-28 00:00:00-05:00"}
    df = pd.read_csv(data / "GC_F_1d.csv")
    assert pd.to_datetime(df["timestamp"], errors="coerce").notna().all()
