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


def _csv_spelled(p, days, close, spell):
    p.write_text(HDR + "".join(f"{spell(d)},1,1,1,{close},5\n" for d in days))


def _first_fields(path):
    return [ln.split(",")[0] for ln in path.read_text().splitlines()[1:]]


def test_date_only_files_get_date_only_rows(tmp_path):
    # 2026-11-18 regression: '2026-07-07' was misread as carrying a '-07-07' timezone.
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv_spelled(data / "GLD_1d.csv", _days(25), 100.0, lambda d: d)
    _lake(lake / "GLD/1d/v002/data.jsonl", _days(28), 100.0)
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    ts = _first_fields(data / "GLD_1d.csv")
    assert ts[-3:] == ["2026-01-26", "2026-01-27", "2026-01-28"]
    assert all(len(t) == 10 for t in ts)


def test_iso_z_and_offset_spellings_are_reproduced(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv_spelled(data / "QQQ_1d.csv", _days(25), 100.0, lambda d: f"{d}T00:00:00Z")
    _csv_spelled(data / "SLV_1d.csv", _days(25), 100.0, lambda d: f"{d} 00:00:00+00:00")
    _lake(lake / "QQQ/1d/v002/data.jsonl", _days(27), 100.0)
    _lake(lake / "SLV/1d/v002/data.jsonl", _days(27), 100.0)
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    assert _first_fields(data / "QQQ_1d.csv")[-1] == "2026-01-27T00:00:00Z"
    assert _first_fields(data / "SLV_1d.csv")[-1] == "2026-01-27 00:00:00+00:00"


def test_unrecognised_spelling_is_refused_untouched(tmp_path):
    data, lake = tmp_path / "data", tmp_path / "lake"
    data.mkdir()
    _csv_spelled(data / "TLT_1d.csv", _days(25), 100.0, lambda d: d.replace("-", "/"))
    _lake(lake / "TLT/1d/v002/data.jsonl", _days(27), 100.0)
    before = (data / "TLT_1d.csv").read_text()
    e.main(["--data-dir", str(data), "--lake", str(lake), "--apply"])
    assert (data / "TLT_1d.csv").read_text() == before
    state = e.plan_one(data / "TLT_1d.csv", e.read_lake(lake / "TLT/1d/v002/data.jsonl"), 2e-3, 20)[0]
    assert state == "refused_timestamp_spelling"
