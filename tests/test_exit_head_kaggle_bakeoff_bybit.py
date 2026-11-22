"""Generalised exit_head_kaggle_bakeoff: bybit candle source + multi-symbol legs (RESEARCH-FILL-20261122)."""
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import exit_head_kaggle_bakeoff as K  # noqa: E402


def _synth(sym_seed: int, n=4000):
    rng = random.Random(sym_seed)
    px, t0, rows = 100.0, 1_600_000_000, []
    for i in range(n):
        o = px
        px = max(1.0, px * (1 + 0.004 * math.sin(i / 150.0) + rng.gauss(0, 0.006)))
        rows.append({"timestamp": (t0 + 3600 * i) * 1000, "open": o, "high": max(o, px) * 1.001,
                     "low": min(o, px) * 0.999, "close": px, "volume": 1000.0 + rng.random()})
    return rows


def test_bybit_source_multi_symbol_runs_and_writes_verdict(tmp_path, monkeypatch):
    import pandas as pd

    def fake_fetch(sym, dst, start, end=None):
        return K._csv_from_df(pd.DataFrame(_synth(abs(hash(sym)) % 1000)), dst)

    monkeypatch.setattr(K, "fetch_bybit_candles", fake_fetch)
    out = tmp_path / "o"
    rc = K.main(["--unit", "RQ-TEST", "--out", str(out), "--candle-source", "bybit",
                 "--legs", "trend_donchian:LINKUSDT,trend_donchian:XRPUSDT", "--arms", "none",
                 "--feature-arms", "feat_exh", "--num-folds", "2", "--registered-at", "2026-11-22",
                 "--rule-id", "RULE-TEST"])
    v = json.loads((out / "verdict.json").read_text())
    assert v["decision_rule"]["registered_at"] == "2026-11-22"
    assert "public Bybit 1h klines" in v["population"] or v.get("read_state") == "producer_failed"
    spans = v["measurement"]["published_shard_spans"]
    assert set(spans) == {"LINKUSDT", "XRPUSDT"} and all(x["read_state"] == "measured" for x in spans.values())
    # one emit file per (strategy, symbol): the same strategy on two symbols must not overwrite
    assert len(v["measurement"]["harness_legs"]) == 2
    assert isinstance(rc, int)


def test_fetch_failure_is_could_not_look_not_empty(tmp_path, monkeypatch):
    def boom(sym, dst, start, end=None):
        raise RuntimeError("no network")
    monkeypatch.setattr(K, "fetch_bybit_candles", boom)
    out = tmp_path / "o"
    rc = K.main(["--out", str(out), "--candle-source", "bybit", "--legs", "trend_donchian:LINKUSDT"])
    v = json.loads((out / "verdict.json").read_text())
    assert rc == 2 and v["read_state"] == "producer_failed"
    assert v["measurement"]["published_shard_spans"]["LINKUSDT"]["read_state"] == "could_not_look"
