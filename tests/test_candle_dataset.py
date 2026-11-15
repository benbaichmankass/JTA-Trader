"""KAGGLE-CANDLES: the published candle dataset -- build/serve round trip, coverage, and the router's use of it."""
import json

import pandas as pd

from scripts.research import candle_dataset as cd
from scripts.research import compute_router as cr

KEY = ("binance", "ETHUSDT", "240")


def _unit(leg="eth_pullback_2h", days=100, extra=()):
    return {"id": "RQ-T", "status": "queued", "compute": "cpu_light",
            "routing": {"est_minutes": 40, "why_runner": "Fetches keyless public candles for a pinned window"},
            "run": {"command": ["python3", "scripts/research/exit_lever_ablation.py", "--leg", leg, "--days", str(days), *extra]}}


def _frame(n=400):
    ts = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0})


def test_serve_round_trip_and_slice(tmp_path, monkeypatch):
    info = cd._write_csv_gz(_frame(), tmp_path / cd.file_name(KEY))
    man = {"dataset": cd.DATASET_SLUG, "generated_at": "x", "days_built": 100, "counts": {"ok": 1, "failed": 0},
           "feeds": {cd.feed_id(KEY): {"status": "ok", "file": cd.file_name(KEY), "days_built": 100, **info}}}
    (tmp_path / cd.MANIFEST_NAME).write_text(json.dumps(man))
    out = tmp_path / "o.csv"
    assert cd.serve(KEY, 30, str(out), root=str(tmp_path))
    got = pd.read_csv(out)
    assert list(got.columns) == cd.CSV_COLS and 170 <= len(got) <= 190          # 30 d of 4h bars
    assert not cd.serve(KEY, 500, str(tmp_path / "n.csv"), root=str(tmp_path))     # asks for more history than built -> network
    assert not cd.serve(("binance", "XRPUSDT", "240"), 30, str(tmp_path / "n.csv"), root=str(tmp_path))
    assert not cd.serve(KEY, 30, str(tmp_path / "n.csv"), root=str(tmp_path / "missing"))


def test_serve_survives_kaggle_extracting_the_gz(tmp_path):
    info = cd._write_csv_gz(_frame(), tmp_path / cd.file_name(KEY))
    (tmp_path / cd.file_name(KEY)).rename(tmp_path / "x.gz")
    import gzip
    import shutil
    with gzip.open(tmp_path / "x.gz", "rb") as a, open(tmp_path / cd.file_name(KEY)[:-3], "wb") as b:
        shutil.copyfileobj(a, b)
    (tmp_path / cd.MANIFEST_NAME).write_text(json.dumps({"feeds": {cd.feed_id(KEY): {"status": "ok", "file": cd.file_name(KEY), "days_built": 100, **info}}}))
    assert cd.serve(KEY, 30, str(tmp_path / "o.csv"), root=str(tmp_path))


def test_serve_survives_kaggle_extracting_into_a_directory(tmp_path):
    """5e01-02/03/04 died on IsADirectoryError: the extracted name was a directory holding the csv."""
    info = cd._write_csv_gz(_frame(), tmp_path / cd.file_name(KEY))
    gz = tmp_path / cd.file_name(KEY)
    d = tmp_path / cd.file_name(KEY)[:-3]
    d.mkdir()
    gz.rename(d / "c.csv.gz")
    (tmp_path / cd.MANIFEST_NAME).write_text(json.dumps({"feeds": {cd.feed_id(KEY): {"status": "ok", "file": cd.file_name(KEY), "days_built": 100, **info}}}))
    assert cd.serve(KEY, 30, str(tmp_path / "o.csv"), root=str(tmp_path))
    d2 = tmp_path / "empty"
    d2.mkdir()


def _cov(status="ok", days=2330, key=("binance", "ETHUSDT", "120")):
    return {"feeds": {cd.feed_id(key): {"status": status, "days_built": days, "rows": 1, "last_ts": "t"}}}


def test_covers_checks_feed_status_and_days():
    u = _unit()
    assert cd.covers(u, _cov())[0]
    assert not cd.covers(u, _cov(status="failed"))[0]
    assert not cd.covers(u, _cov(days=10))[0]
    assert not cd.covers(u, {})[0]
    assert not cd.covers({**u, "run": {"command": ["python3", "other.py"]}}, _cov())[0]
    assert not cd.covers(_unit(extra=("--data-csv", "x.csv")), _cov())[0]


def test_router_releases_covered_unit_to_kaggle_cpu(monkeypatch):
    cfg = cr.load_config()
    u = _unit()
    monkeypatch.setattr(cd, "load_coverage", lambda p=None: {})        # hermetic: never the committed coverage.json
    assert cr.runner_only_reason(u)
    assert cr.class_backends("cpu_light", u, cfg) == ["github_runner"]
    monkeypatch.setattr(cd, "load_coverage", lambda p=None: _cov())
    assert cr.runner_only_reason(u) is None
    assert cr.class_backends("cpu_light", u, cfg)[0] == "kaggle_cpu"
    u["routing"]["needs_secrets"] = True                  # an explicit secret/internet need still pins the runner
    assert cr.runner_only_reason(u)


def test_build_records_failure_and_continues(tmp_path, monkeypatch):
    def fake(key, days, out):
        if key[1] == "BADUSDT":
            raise RuntimeError("boom")
        _frame().to_csv(out, index=False)
        return pd.read_csv(out)
    monkeypatch.setattr(cd, "_from_network", fake)
    man = cd.build(tmp_path, {KEY: 50, ("binance", "BADUSDT", "240"): 50}, use_lake=False)
    assert man["counts"] == {"ok": 1, "failed": 1}
    rec = cd.coverage_record(man)
    assert rec["feeds"][cd.feed_id(("binance", "BADUSDT", "240"))]["status"] == "failed"
    assert (tmp_path / cd.MANIFEST_NAME).is_file()


def test_strategies_is_parsed_once_per_file_version(tmp_path, monkeypatch):
    """RQ-DISPATCHER-ONLY-FULL-SCAN: the dispatcher calls `_strategies()` once per queue unit; re-parsing the YAML each time
    cost ~97% of a single-unit dry run (71 s). Same file version -> one parse; an edited file -> re-read."""
    import yaml
    from scripts.research import candle_dataset as cd

    (tmp_path / "config").mkdir()
    f = tmp_path / "config" / "strategies.yaml"
    f.write_text("strategies:\n  a: {timeframe: '15'}\n", encoding="utf-8")
    monkeypatch.setattr(cd, "_REPO", tmp_path)
    cd._STRATEGIES_CACHE.clear()
    calls = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert cd._strategies() == {"a": {"timeframe": "15"}}
    assert cd._strategies() is cd._strategies()
    assert len(calls) == 1
    f.write_text("strategies:\n  b: {timeframe: '60'}\n  c: {}\n", encoding="utf-8")
    assert set(cd._strategies()) == {"b", "c"} and len(calls) == 2
    cd._STRATEGIES_CACHE.clear()
