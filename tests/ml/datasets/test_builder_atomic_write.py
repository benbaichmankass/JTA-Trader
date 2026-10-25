"""ml/datasets/builder.py writes data.jsonl atomically (ML-SHARD-TRUNCATED, 2026-10-18).

MEASURED 2026-10-13 on the trainer: BTCUSDT 15m data.jsonl held 151,000 rows beside a metadata.json saying
175,296 -- a fetch that died mid-stream had overwritten the previous shard with a prefix. The builder now
streams into `data.jsonl.tmp` and renames on success, so a failed build leaves the previous shard untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.datasets.adapters import CsvMarketRawAdapter
from ml.datasets.families.market_raw import MarketRawBuilder

_CSV = "ts,open,high,low,close,volume\n2026-05-01T00:00:00Z,1,2,0,1.5,10\n2026-05-01T01:00:00Z,1.5,2.5,1,2,20\n"


def _build(tmp_path: Path, csv_path: Path, **kw):
    return MarketRawBuilder().build(
        output_dir=tmp_path / "out", version="v001", source="csv", symbol_scope="BTCUSDT", timeframe="1h",
        adapter="csv", csv_path=csv_path, symbol="BTCUSDT", **kw)


def test_failed_rebuild_leaves_the_previous_shard_intact(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(_CSV, encoding="utf-8")
    paths = _build(tmp_path, csv_path)
    before = paths.data.read_text(encoding="utf-8")
    assert before.count("\n") == 2

    def boom(self, **kw):
        yield {"ts": "2026-05-02T00:00:00Z", "symbol": "BTCUSDT", "timeframe": "1h", "open": 1.0,
               "high": 2.0, "low": 0.0, "close": 1.0, "volume": 1.0, "source": "csv"}
        raise RuntimeError("fetch died on page 2")

    monkeypatch.setattr(CsvMarketRawAdapter, "iter_bars", boom)
    with pytest.raises(RuntimeError, match="page 2"):
        _build(tmp_path, csv_path, overwrite=True)
    assert paths.data.read_text(encoding="utf-8") == before
    assert not paths.data.with_name("data.jsonl.tmp").exists()
    # the previous build's metadata still describes the file that is there
    assert json.loads((paths.root / "metadata.json").read_text())["row_count"] == 2
