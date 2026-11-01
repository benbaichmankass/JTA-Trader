"""MARKET-DATA-LAKE: fetch parsing, gap accounting, manifest merge, PIT liquidity floor, local-dir loader."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data_lake"))

import binance_vision_lake as bvl  # noqa: E402
import free_sources as fs  # noqa: E402
import hf_publish as hp  # noqa: E402

pytest.importorskip("pyarrow")


def _csv(rows, header=False, us=False):
    mult = 1000 if us else 1
    lines = []
    if header:
        lines.append(",".join(bvl.RAW_COLS))
    for t, c in rows:
        ms = int(pd.Timestamp(t, tz="UTC").value // 10**6) * mult
        lines.append(f"{ms},{c},{c + 1},{c - 1},{c},10,{ms + 59999},1000,5,4,400,0")
    return "\n".join(lines).encode()


@pytest.mark.parametrize("header,us", [(False, False), (True, False), (True, True)])
def test_parse_kline_csv_handles_header_and_microseconds(header, us):
    df = bvl.parse_kline_csv(_csv([("2025-02-01 00:00", 100.0), ("2025-02-01 01:00", 101.0)], header, us))
    assert list(df.columns) == bvl.OUT_COLS
    assert df["ts"].iloc[0] == pd.Timestamp("2025-02-01 00:00", tz="UTC")
    assert df["ts"].iloc[1] == pd.Timestamp("2025-02-01 01:00", tz="UTC")


def test_gap_stats_counts_missing_bars_without_patching():
    ts = pd.Series(pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 04:00"], utc=True))
    g = bvl.gap_stats(ts, "1h")
    assert g == {"expected_rows": 5, "missing_bars": 2, "gaps": 1, "largest_gap_bars": 2}


def test_shard_partitions_exactly():
    items = [f"S{i}" for i in range(11)]
    parts = [bvl.shard(items, f"{i}/3") for i in range(3)]
    assert sorted(sum(parts, [])) == sorted(items)
    assert not set(parts[0]) & set(parts[1])


def test_symbols_from_config_all_vs_list():
    assert bvl.symbols_from_config("um_perp", "1h") is None  # all
    one_m = bvl.symbols_from_config("um_perp", "1m")
    assert "BTCUSDT" in one_m and len(one_m) >= 10


def test_parse_nasdaqtraded_flags_etfs_and_drops_test_issues():
    txt = ("Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|"
           "Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\n"
           "Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N\n"
           "Y|AAPL|Apple Inc. - Common Stock|Q|Q|N|100|N|N||AAPL|N\n"
           "Y|ZZZT|Test Co|Q|Q|N|100|Y|N||ZZZT|N\n"
           "Y|ABCW|ABC Corp Warrant|Q|Q|N|100|N|N||ABCW|N\n"
           "File Creation Time: 1101202600:00|||||||||||\n")
    df = fs.parse_nasdaqtraded(txt)
    assert set(df["symbol"]) == {"SPY", "AAPL", "ABCW"}
    assert df.set_index("symbol").loc["SPY", "is_etf"]
    assert df.set_index("symbol").loc["AAPL", "is_common"]
    assert not df.set_index("symbol").loc["ABCW", "is_common"]


def _mini_lake(tmp_path: Path) -> Path:
    base = tmp_path / "lake"
    p = base / "crypto" / "um_perp" / "1h"
    p.mkdir(parents=True)
    ts = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    entries = []
    for sym, qv in (("AAAUSDT", 1e7), ("BBBUSDT", 1e3)):
        df = pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
                           "quote_volume": qv, "trades": 1, "taker_buy_volume": 0.5, "taker_buy_quote_volume": qv / 2})
        df.to_parquet(p / f"{sym}.parquet", index=False)
        entries.append({"asset_class": "crypto", "market": "um_perp", "tf": "1h", "symbol": sym, "rows": 48,
                        "first": ts[0].isoformat(), "last": ts[-1].isoformat(), "missing_bars": 0,
                        "path": f"crypto/um_perp/1h/{sym}.parquet", "bytes": 1})
    (base / "_manifests").mkdir()
    (base / "_manifests" / "crypto-um_perp-1h-0of1.json").write_text(json.dumps(entries))
    m = hp.merge_manifests(base)
    (base / "MANIFEST.json").write_text(json.dumps(m))
    return base


def test_manifest_merge_and_depth_table(tmp_path):
    base = _mini_lake(tmp_path)
    m = json.loads((base / "MANIFEST.json").read_text())
    assert len(m["files"]) == 2
    t = hp.depth_table(m)
    assert "| crypto | um_perp | 1h | 2 / 2 | 96 |" in t
    # a later shard manifest replaces, never duplicates, an earlier entry for the same file
    again = hp.merge_manifests(base, previous=m)
    assert len(again["files"]) == 2


def test_loader_reads_local_lake_and_pit_liquidity(tmp_path, monkeypatch):
    base = _mini_lake(tmp_path)
    monkeypatch.setenv("LAKE_LOCAL_DIR", str(base))
    from ml.datasets import lake
    lake._MANIFEST_CACHE.clear()
    assert lake.symbols("crypto", "um_perp", "1h") == ["AAAUSDT", "BBBUSDT"]
    df = lake.load("crypto", "um_perp", "1h", start="2024-01-02")
    assert df.groupby("symbol").size().to_dict() == {"AAAUSDT": 24, "BBBUSDT": 24}
    full = lake.load("crypto", "um_perp", "1h")
    m = lake.liquid_mask(full, adv_usd=5e6, window=20)
    a = m[full["symbol"] == "AAAUSDT"].reset_index(drop=True)
    # no lookahead: the first `window` bars have no full trailing window -> False
    assert not a.iloc[:20].any() and a.iloc[20:].all()
    assert not m[full["symbol"] == "BBBUSDT"].any()
    assert [s for s, _ in lake.iter_series("crypto", "um_perp", "1h")] == ["AAAUSDT", "BBBUSDT"]


def test_publish_refuses_public_repo(monkeypatch):
    class Info:
        private = False

    class Api:
        token = "x"

        def dataset_info(self, repo):
            return Info()

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "create_repo", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="PUBLIC"):
        hp.ensure_private_repo(Api(), "someone/repo")
