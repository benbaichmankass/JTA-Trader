"""CF-B1: the bulk runner is deterministic, idempotent, resumable and counts what it cannot grade."""
import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_bulk  # noqa: E402

T0 = 1_700_000_000.0


def _bars(n=400, step=3600.0):
    out, px = [], 100.0
    for i in range(n):
        px *= 1.0 + 0.002 * (1 if (i // 7) % 2 == 0 else -1)
        out.append({"time": T0 + i * step, "open": px, "high": px * 1.004, "low": px * 0.996, "close": px, "dur": step})
    return out


def _fetcher(symbol, tf, t0, t1):
    return _bars()


def _iso(t):
    import datetime as d
    return d.datetime.fromtimestamp(t, d.timezone.utc).isoformat(sep=" ")


def _row(i, symbol="BTCUSDT", strategy="trend_donchian"):
    et = T0 + (10 + i * 2) * 3600
    return {"strategy": strategy, "symbol": symbol, "entry_time": _iso(et), "exit_time": _iso(et + 5 * 3600), "direction": "long",
            "entry": 100.0 + i * 0.01, "sl": 98.0, "net_r": 0.5, "gross_r": 0.55, "cost_fee_r": 0.02, "cost_funding_r": 0.0, "exit_reason": "stop"}


def _corpus(tmp_path):
    d = tmp_path / "comms" / "research" / "RQ-X" / "1" / "cells"
    d.mkdir(parents=True)
    rows = [_row(i) for i in range(30)]
    (d / "trend_BTCUSDT_1h_B__trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows + rows[:5]) + "\n")      # 5 duplicates
    rows2 = [{k: v for k, v in _row(i).items() if k != "symbol"} for i in range(4)]
    (d / "nosym__trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows2) + "\n")
    (d / "empty__trades.jsonl").write_text("")
    return tmp_path


def test_timeframe_resolution():
    assert cf_bulk.resolve_timeframe("a/trend_ETHUSDT_2h_LONG__trades.jsonl", "x") == ("2h", None)
    assert cf_bulk.resolve_timeframe("a/B__trades.jsonl", "htf_pullback_trend_2h") == ("2h", None)
    assert cf_bulk.resolve_timeframe("a/B__trades.jsonl", "trend_donchian") == (None, "timeframe_unresolved")
    assert cf_bulk.resolve_timeframe("a/trend_ADAUSDT_1w_W5__trades.jsonl", "x")[1] == "timeframe_unsupported"


def test_population_counts_and_dedupe(tmp_path):
    root = _corpus(tmp_path)
    jobs, c = cf_bulk.load_jobs(cf_bulk.discover(root), root)
    assert c["rows"] == 39 and c["files"] == 3 and c["files_empty"] == 1
    assert len(jobs) == 34 and c["distinct_jobs"] == 34            # 30 + 4 symbol-less; 5 duplicates collapsed
    shards, chunks = cf_bulk.plan_shards(jobs, 20000)
    assert sum(s["n_jobs"] for s in shards) == 34
    assert {s["symbol"] for s in shards} == {"BTCUSDT", "UNKNOWN"}


def test_shard_idempotent_and_reduce(tmp_path):
    root = _corpus(tmp_path / "c")
    jobs, _ = cf_bulk.load_jobs(cf_bulk.discover(root), root)
    shards, chunks = cf_bulk.plan_shards(jobs, 20000)
    out = tmp_path / "out"
    metas = [cf_bulk.run_shard(s, chunks, jobs, out, n_random=20, fetcher=_fetcher) for s in shards]
    by = {m["symbol"]: m for m in metas}
    assert by["BTCUSDT"]["n_graded"] == 30 and by["BTCUSDT"]["state"] == "done"
    assert by["UNKNOWN"]["could_not_grade"] == {"symbol_unresolved": 4}
    again = cf_bulk.run_shard(shards[0], chunks, jobs, out, n_random=20, fetcher=_fetcher)
    assert again["skipped"] is True
    rec = json.loads(gzip.open(out / "shards" / f"{by['BTCUSDT']['shard_id']}.jsonl.gz", "rt").readline())
    assert rec["cf"]["schema"] == "cf_trade/1" and rec["cf"]["status"] == "graded" and rec["cf"]["provenance"] == "ESTIMATED"
    plan = {"run_id": "t", "input": {}, "shards": shards}
    res = cf_bulk.reduce_run(out, plan)
    assert res["manifest"]["n_graded"] == 30 and res["manifest"]["could_not_grade_by_reason"] == {"symbol_unresolved": 4}
    assert res["summary"]["legs"]["trend_donchian|BTCUSDT"]["bt"]["verdict"] == "INDETERMINATE"      # n=30 < 100
    plan["shards"].append({**shards[0], "shard_id": "ghost"})
    assert cf_bulk.reduce_run(out, plan)["manifest"]["shards_missing"] == ["ghost"]


def test_failed_fetch_is_recorded_not_raised(tmp_path):
    root = _corpus(tmp_path / "c")
    jobs, _ = cf_bulk.load_jobs(cf_bulk.discover(root), root)
    shards, chunks = cf_bulk.plan_shards(jobs, 20000)
    s = next(x for x in shards if x["symbol"] == "BTCUSDT")

    def boom(*a):
        raise OSError("net down")
    m = cf_bulk.run_shard(s, chunks, jobs, tmp_path / "o", n_random=5, fetcher=boom)
    assert m["state"] == "fetch_failed" and m["could_not_grade"] == {"no_bars": 30}
    assert not (tmp_path / "o" / "shards" / f"{s['shard_id']}.meta.json").exists()          # not "done": a re-run retries it
