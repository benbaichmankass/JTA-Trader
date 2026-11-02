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
    g = bvl.gap_stats(ts, 60)
    assert g == {"expected_rows": 5, "missing_bars": 2, "gaps": 1, "largest_gap_bars": 2}


def test_shard_partitions_exactly():
    items = [f"S{i}" for i in range(11)]
    parts = [bvl.shard(items, f"{i}/3") for i in range(3)]
    assert sorted(sum(parts, [])) == sorted(items)
    assert not set(parts[0]) & set(parts[1])


def test_symbols_from_config_all_vs_list():
    assert bvl.symbols_from_config("um_perp", "klines") is None  # all perps at 1m
    spot = bvl.symbols_from_config("spot", "klines")
    assert "BTCUSDT" in spot and len(spot) >= 10


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


def test_cboe_parse_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_get", lambda url, **k: b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.24,17.24,17.24,17.24\n01/03/1990,18.19,18.19,18.19,18.19\n")
    monkeypatch.setattr(fs, "_cfg", lambda: {"options_sources": {"cboe_iv_indices": {"symbols": ["VIX"], "licence": "x"}}})

    class A:
        out = str(tmp_path)
    assert fs.cmd_cboe(A) == 0
    e = json.loads((tmp_path / "_manifests" / "options-cboe.json").read_text())[0]
    assert e["rows"] == 2 and e["first"].startswith("1990-01-02") and e["path"] == "options/cboe_iv/1d/VIX.parquet"


def test_import_csv_partitions_by_symbol(tmp_path):
    csv = tmp_path / "vol.csv"
    csv.write_text("date,act_symbol,iv_current\n2019-02-11,SPY,0.15\n2019-02-12,SPY,0.16\n2019-02-11,QQQ,0.2\n")

    class A:
        out = str(tmp_path / "lake")
        kind = "volatility"
    A.csv = str(csv)
    assert fs.cmd_import_csv(A) == 0
    es = {e["symbol"]: e for e in json.loads((tmp_path / "lake" / "_manifests" / "dolthub-volatility.json").read_text())}
    assert es["SPY"]["rows"] == 2 and es["QQQ"]["rows"] == 1
    assert es["SPY"]["path"] == "options/dolthub_iv/1d/SPY.parquet"


# ---------------------------------------------------------------- finest-grain + automation (2026-11-01 v2)
import resample as rs  # noqa: E402
import validate as vd  # noqa: E402


def test_plan_months_incremental():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
    monthly = [f"x/S-1m-2025-{m:02d}.zip" for m in (11, 12)] + [f"x/S-1m-2026-{m:02d}.zip" for m in (7, 8, 9)]
    daily = [f"x/S-1m-2026-10-{d:02d}.zip" for d in (1, 2)]
    # first run: the closed year is ONE partition, the current year one per month
    assert set(bvl.plan_months(monthly, daily, {}, now=now)) == {"2025", "2026-07", "2026-08", "2026-09", "2026-10"}
    have = {"2025": {"src": "monthly"}, "2026-07": {"src": "monthly"}, "2026-08": {"src": "monthly"},
            "2026-09": {"src": "daily"}, "2026-10": {"src": "daily"}}
    plan = bvl.plan_months(monthly, daily, have, now=now)
    # 09 was daily-built and its monthly file now exists -> rebuilt from monthly; 10 is the open month -> rebuilt
    assert set(plan) == {"2026-09", "2026-10"} and plan["2026-09"][0] == "monthly" and plan["2026-10"][0] == "daily"


def test_plan_months_delisted_and_year_rollover():
    from datetime import datetime, timezone
    # a symbol delisted in 2022: its last year is not re-downloaded every day
    dead = [f"x/L-1m-2022-{m:02d}.zip" for m in (1, 2, 3)]
    assert bvl.plan_months(dead, [], {"2022": {"src": "monthly"}}, now=datetime(2026, 11, 1, tzinfo=timezone.utc)) == {}
    # first run of 2027: 2026's monthly partitions are compacted into one yearly file
    mon = [f"x/S-1m-2026-{m:02d}.zip" for m in range(1, 13)]
    have = {f"2026-{m:02d}": {"src": "monthly"} for m in range(1, 13)}
    plan = bvl.plan_months(mon, [], have, now=datetime(2027, 1, 2, tzinfo=timezone.utc))
    assert set(plan) == {"2026"} and len(plan["2026"][1]) == 12


def test_resample_is_exact_and_marks_partial_bars():
    ts = pd.date_range("2026-01-01 00:00", periods=7, freq="1min", tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": [1, 2, 3, 4, 5, 6, 7.0], "high": [2, 3, 9, 5, 6, 7, 8.0],
                       "low": [0.5, 1, 2, 3, 4, 5, 6.0], "close": [2, 3, 4, 5, 6, 7, 8.0], "volume": [1.0] * 7,
                       "trades": [1] * 7})
    d = rs.resample_frame(df, "1m", "5m")
    assert list(d["ts"]) == [ts[0], ts[5]]
    r0 = d.iloc[0]
    assert (r0.open, r0.high, r0.low, r0.close, r0.volume, r0.n_base, bool(r0.complete)) == (1, 9, 0.5, 6, 5, 5, True)
    assert d.iloc[1].n_base == 2 and not bool(d.iloc[1].complete)


def test_check_frame_flags_ohlc_violation_and_dups():
    ts = pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:01", "2026-01-01 00:01"], utc=True)
    df = pd.DataFrame({"ts": ts, "open": [1, 1, 1.0], "high": [0.5, 1, 1.0], "low": [0.4, 1, 1.0],
                       "close": [1, 1, 1.0], "volume": [1, 1, 1.0]})
    c = vd.check_frame(df, "1m")
    assert c["dup_ts"] == 1 and c["ohlc_violations"] == 1 and c["schema_missing"] == []
    assert vd.check_frame(df.drop(columns=["close"]), "1m")["schema_missing"] == ["close"]


def test_fold_counts_consecutive_failures_and_flags_once():
    prev = {"series": [{"series": "feed:crypto/um_perp/1m", "state": "fail", "consecutive_failures": 2}]}
    rec = vd.fold([{"series": "feed:crypto/um_perp/1m", "state": "fail", "checks": {}}], prev)
    assert rec[0]["consecutive_failures"] == 3 and rec[0]["flagged_at"] is None   # -> flagged this run
    prev2 = {"series": [{**rec[0], "flagged_at": "2026-11-01T00:00:00+00:00"}]}
    rec2 = vd.fold([{"series": "feed:crypto/um_perp/1m", "state": "fail", "checks": {}}], prev2)
    assert rec2[0]["flagged_at"]          # already flagged: no second flag for the same incident
    rec3 = vd.fold([{"series": "feed:crypto/um_perp/1m", "state": "ok", "checks": {}}], prev2)
    assert rec3[0]["consecutive_failures"] == 0 and rec3[0]["flagged_at"] is None  # recovered: re-armed


def test_feed_staleness():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    m = {"files": [{"asset_class": "crypto", "market": "um_perp", "tf": "1m", "symbol": "A", "last": "2026-10-31T23:59:00+00:00"},
                   {"asset_class": "crypto", "market": "um_perp", "tf": "1m", "symbol": "DEAD", "last": "2022-05-13T00:00:00+00:00"},
                   {"asset_class": "fx", "market": "fred", "tf": "1d", "symbol": "X", "last": "2026-09-01T00:00:00+00:00"}]}
    f = {r["series"]: r["state"] for r in vd.feed_staleness(m, now)}
    assert f["feed:crypto/um_perp/1m"] == "ok"      # the freshest series decides; a delisted one does not stale the feed
    assert f["feed:fx/fred/1d"] == "fail"


def test_merge_manifests_merges_partitions(tmp_path):
    prev = {"files": [{"asset_class": "crypto", "market": "um_perp", "tf": "1m", "symbol": "A",
                       "partitions": {"2026-09": {"rows": 10, "first": "2026-09-01T00:00:00+00:00",
                                                  "last": "2026-09-30T23:59:00+00:00", "path": "crypto/um_perp/1m/A/2026-09.parquet"}}}]}
    (tmp_path / "_manifests").mkdir()
    (tmp_path / "_manifests" / "x.json").write_text(json.dumps([{"asset_class": "crypto", "market": "um_perp", "tf": "1m",
        "symbol": "A", "partitions": {"2026-10": {"rows": 5, "first": "2026-10-01T00:00:00+00:00",
                                                  "last": "2026-10-31T23:59:00+00:00", "path": "crypto/um_perp/1m/A/2026-10.parquet"}}}]))
    m = hp.merge_manifests(tmp_path, prev)
    e = m["files"][0]
    assert set(e["partitions"]) == {"2026-09", "2026-10"} and e["rows"] == 15
    assert e["first"].startswith("2026-09-01") and e["last"].startswith("2026-10-31")


def _etf_month(root, sym, month, n=3):
    d = root / sym / "1m"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"timestamp": pd.date_range(f"{month}-02 14:30", periods=n, freq="1min", tz="UTC"),
                  "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10, "trade_count": 1,
                  "vwap": 1.0}).to_parquet(d / f"{month}.parquet")


def _frag(lake, prefix):
    fs = sorted((lake / "_manifests").glob(f"{prefix}-*.json"))
    return [e for f in fs for e in json.loads(f.read_text())]


def test_import_etf_monthly_store_to_yearly_lake_with_derived(tmp_path):
    store = tmp_path / "store"
    for m in ("2025-11", "2025-12", "2026-01"):
        _etf_month(store, "SPY", m)
    (store / "MANIFEST.json").write_text(json.dumps({"series": {"SPY/1m": {"status": "ok", "feed": "sip"}}}))

    class A:
        src = str(store)
        out = str(tmp_path / "lake")
        prev_manifest = str(tmp_path / "none.json")
    assert fs.cmd_import_etf(A) == 0
    e = _frag(tmp_path / "lake", "us_equity-alpaca")[0]
    assert e["feed"] == "sip" and set(e["partitions"]) == {"2025", "2026"} and e["partitions"]["2025"]["rows"] == 6
    assert (tmp_path / "lake" / "us_equity/alpaca/1m/SPY/2025.parquet").exists()
    assert {d["tf"] for d in _frag(tmp_path / "lake", "derived-us_equity")} >= {"5m", "1h", "1d"}


def test_import_etf_partial_tail_merges_never_shrinks(tmp_path, monkeypatch):
    # the lake already holds 2026 with Jan+Feb; the trainer tail supplies only Feb (revised) + Mar
    lake_old = tmp_path / "old"
    _etf_month(tmp_path / "seed", "SPY", "2026-01")
    _etf_month(tmp_path / "seed", "SPY", "2026-02")
    old = pd.concat([pd.read_parquet(f) for f in sorted((tmp_path / "seed/SPY/1m").glob("*.parquet"))]).rename(columns={"timestamp": "ts"})
    (lake_old / "us_equity/alpaca/1m/SPY").mkdir(parents=True)
    old.to_parquet(lake_old / "us_equity/alpaca/1m/SPY/2026.parquet")
    prev = {"files": [{"asset_class": "us_equity", "market": "alpaca", "tf": "1m", "symbol": "SPY",
                       "partitions": {"2026": {"path": "us_equity/alpaca/1m/SPY/2026.parquet", "rows": 6}}}]}
    (tmp_path / "prev.json").write_text(json.dumps(prev))
    monkeypatch.setattr(fs, "_lake_download", lambda rel: lake_old / rel)
    store = tmp_path / "store"
    _etf_month(store, "SPY", "2026-02", n=5)
    _etf_month(store, "SPY", "2026-03", n=2)

    class A:
        src = str(store)
        out = str(tmp_path / "lake")
        prev_manifest = str(tmp_path / "prev.json")
    assert fs.cmd_import_etf(A) == 0
    df = pd.read_parquet(tmp_path / "lake/us_equity/alpaca/1m/SPY/2026.parquet")
    by_m = df["ts"].dt.strftime("%Y-%m").value_counts().to_dict()
    assert by_m == {"2026-01": 3, "2026-02": 5, "2026-03": 2}   # Jan kept, Feb replaced, Mar added


def test_option_snapshots_merge_by_session(tmp_path, monkeypatch):
    lake_old = tmp_path / "old"
    p = lake_old / "options/alpaca_snapshot/1d/SPY/2026.parquet"
    p.parent.mkdir(parents=True)
    pd.DataFrame({"ts": pd.to_datetime(["2026-10-01 20:00"] * 2, utc=True), "session": ["2026-10-01"] * 2,
                  "contract": ["C1", "C2"]}).to_parquet(p)
    (tmp_path / "prev.json").write_text(json.dumps({"files": [{"asset_class": "options", "market": "alpaca_snapshot",
        "tf": "1d", "symbol": "SPY", "partitions": {"2026": {"path": "options/alpaca_snapshot/1d/SPY/2026.parquet"}}}]}))
    monkeypatch.setattr(fs, "_lake_download", lambda rel: lake_old / rel)
    d = tmp_path / "src/alpaca/SPY"
    d.mkdir(parents=True)
    pd.DataFrame({"ts": pd.to_datetime(["2026-10-02 20:00"] * 3, utc=True), "contract": ["C1", "C2", "C3"]}).to_parquet(d / "2026-10-02.parquet")

    class A:
        src = str(tmp_path / "src")
        out = str(tmp_path / "lake")
        prev_manifest = str(tmp_path / "prev.json")
    assert fs.cmd_import_option_snapshots(A) == 0
    df = pd.read_parquet(tmp_path / "lake/options/alpaca_snapshot/1d/SPY/2026.parquet")
    assert len(df) == 5 and df["session"].nunique() == 2   # 2 contracts kept from 10-01, 3 added for 10-02


def test_loader_reads_partitions_with_window(tmp_path, monkeypatch):
    base = tmp_path / "lake"
    parts = {}
    for m in ("2026-09", "2026-10"):
        p = base / "crypto/um_perp/1m/A" / f"{m}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = pd.date_range(f"{m}-01", periods=3, freq="1min", tz="UTC")
        pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}).to_parquet(p)
        parts[m] = {"rows": 3, "first": ts[0].isoformat(), "last": ts[-1].isoformat(), "path": str(p.relative_to(base))}
    (base / "MANIFEST.json").write_text(json.dumps({"files": [{"asset_class": "crypto", "market": "um_perp", "tf": "1m",
                                                               "symbol": "A", "rows": 6, "partitions": parts,
                                                               "first": parts["2026-09"]["first"], "last": parts["2026-10"]["last"]}]}))
    monkeypatch.setenv("LAKE_LOCAL_DIR", str(base))
    from ml.datasets import lake
    lake._MANIFEST_CACHE.clear()
    assert len(lake.load("crypto", "um_perp", "1m", ["A"])) == 6
    assert len(lake.load("crypto", "um_perp", "1m", ["A"], start="2026-10-01")) == 3
    assert len(lake.resample(lake.load("crypto", "um_perp", "1m", ["A"]), "2h")) == 2


def test_parse_kline_header_uses_count_column():
    raw = (b"open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
           b"1735689600000,1,2,0.5,1.5,10,1735689659999,15,7,4,6,0\n")
    df = bvl.parse_kline_csv(raw)
    assert int(df["trades"].iloc[0]) == 7


def test_derived_shared_file_and_loader_tf_filter(tmp_path, monkeypatch):
    base = tmp_path / "lake"
    p = base / "crypto/um_perp/1m/A/2025.parquet"
    p.parent.mkdir(parents=True)
    ts = pd.date_range("2025-01-01", periods=120, freq="1min", tz="UTC")
    pd.DataFrame({"ts": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}).to_parquet(p)
    ents = rs.run(base, "1m", ["5m", "1h"])
    assert {e["tf"] for e in ents} == {"5m", "1h"}
    assert len({pp["path"] for e in ents for pp in e["partitions"].values()}) == 1   # ONE derived file
    (base / "MANIFEST.json").write_text(json.dumps({"files": [hp._aggregate(e) for e in ents]}))
    monkeypatch.setenv("LAKE_LOCAL_DIR", str(base))
    from ml.datasets import lake
    lake._MANIFEST_CACHE.clear()
    assert len(lake.load("crypto", "um_perp", "1h", ["A"])) == 2
    assert len(lake.load("crypto", "um_perp", "5m", ["A"])) == 24


def test_year_partition_supersedes_months(tmp_path):
    prev = {"files": [{"asset_class": "crypto", "market": "um_perp", "tf": "1m", "symbol": "A", "partitions": {
        f"2026-{m:02d}": {"rows": 1, "first": f"2026-{m:02d}-01T00:00:00+00:00", "last": f"2026-{m:02d}-01T00:00:00+00:00",
                          "path": f"crypto/um_perp/1m/A/2026-{m:02d}.parquet"} for m in (11, 12)}}]}
    (tmp_path / "_manifests").mkdir()
    (tmp_path / "_manifests" / "x.json").write_text(json.dumps([{"asset_class": "crypto", "market": "um_perp", "tf": "1m",
        "symbol": "A", "partitions": {"2026": {"rows": 2, "first": "2026-11-01T00:00:00+00:00",
                                               "last": "2026-12-01T00:00:00+00:00", "path": "crypto/um_perp/1m/A/2026.parquet"}}}]))
    m = hp.merge_manifests(tmp_path, prev)
    assert set(m["files"][0]["partitions"]) == {"2026"}
    assert m["superseded"] == ["crypto/um_perp/1m/A/2026-11.parquet", "crypto/um_perp/1m/A/2026-12.parquet"]


def test_orderflow_from_aggtrades_exact_and_header_tolerant():
    import io
    rows = ["1,10.0,2.0,100,101,1735689600000,false", "2,11.0,1.0,102,102,1735689630000,true",
            "3,12.0,3.0,103,105,1735689660000,false"]
    for header in (False, True):
        txt = ("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n" if header else "") + "\n".join(rows) + "\n"
        d = bvl.orderflow_from_aggtrades(io.BytesIO(txt.encode()), chunksize=2)
        assert list(d["n_agg"]) == [2, 1] and list(d["n_trades"]) == [3, 3]
        r0 = d.iloc[0]
        assert (r0.buy_qty, r0.sell_qty, r0.signed_qty, r0.max_qty) == (2.0, 1.0, 1.0, 2.0)
        assert abs(r0.vwap - (10 * 2 + 11 * 1) / 3) < 1e-12


def test_traded_symbols_and_scoped_optional_streams():
    from pathlib import Path
    syms = bvl.traded_symbols()
    assert syms and all(s.endswith("USDT") for s in syms)
    d = hp.decide_optional(100 * 10**9, Path(ROOT / "config" / "data_universe.yaml"))
    # the traded-universe fallbacks fit the measured free allowance; the all-perp big streams do not
    assert {"bookDepth_traded", "aggTrades_traded"} <= set(d["enabled"])
    assert "bookDepth" in {x["stream"] for x in d["deferred"]}
