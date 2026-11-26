"""ml_bakeoff raw_bars feature block + per-learner base_features override (RQ-20261126-9e73-01 / -02: the GRU on raw OHLCV windows)."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import ml_bakeoff as B  # noqa: E402


def _raw(path: Path, n=300, seed=0, start="2025-01-01"):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[100.0, c[:-1]] * np.exp(rng.normal(0, 0.001, n))
    h, lo = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    v = rng.uniform(100, 200, n)
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(json.dumps({"ts": ts[i].isoformat(), "open": o[i], "high": h[i], "low": lo[i], "close": c[i], "volume": v[i]}) + "\n")
    return ts, o, h, lo, c


def test_raw_bars_columns_are_causal_and_exact(tmp_path):
    p = tmp_path / "raw.jsonl"
    ts, o, h, lo, c = _raw(p)
    df = pd.DataFrame({"ts": ts[5:].astype(str)})          # a frame that starts later and is a subset of the raw bars
    out = B.block_raw_bars(df, {"path": str(p)})
    assert set(out) == {"raw_r1", "raw_hl", "raw_co", "raw_gap", "raw_lv"}
    i = 10                                                  # row 10 of df = raw bar 15
    assert math.isclose(out["raw_r1"][i], math.log(c[15] / c[14]), rel_tol=1e-9)
    assert math.isclose(out["raw_hl"][i], math.log(h[15] / lo[15]), rel_tol=1e-9)
    assert math.isclose(out["raw_co"][i], math.log(c[15] / o[15]), rel_tol=1e-9)
    assert math.isclose(out["raw_gap"][i], math.log(o[15] / c[14]), rel_tol=1e-9)
    assert np.isnan(out["raw_lv"][0])                       # 5 past bars < min_periods 10: no volume baseline yet


def test_raw_bars_pooled_entity_join_and_missing_entity_is_nan(tmp_path):
    for sym, seed in (("AAA", 1), ("BBB", 2)):
        _raw(tmp_path / f"{sym}.jsonl", seed=seed)
    ts = pd.date_range("2025-01-01", periods=300, freq="1h", tz="UTC")
    df = pd.DataFrame({"ts": list(ts[50:60].astype(str)) * 3, "symbol": ["AAA"] * 10 + ["BBB"] * 10 + ["ZZZ"] * 10})
    out = B.block_raw_bars(df, {"path": str(tmp_path / "{entity}.jsonl"), "entity_col": "symbol"})
    r1 = out["raw_r1"]
    assert np.isfinite(r1[:20]).all() and np.isnan(r1[20:]).all()
    assert not np.allclose(r1[:10], r1[10:20])             # different symbols, different returns: joined on (entity, ts)


def test_base_features_override_gives_a_learner_only_its_blocks(tmp_path):
    p = tmp_path / "raw.jsonl"
    ts, *_ = _raw(p, n=600)
    rng = np.random.default_rng(3)
    data = tmp_path / "feat.jsonl"
    with open(data, "w") as fh:
        for i, t in enumerate(ts):
            fh.write(json.dumps({"ts": t.isoformat(), "f1": float(rng.normal()), "y": ["a", "b"][i % 2]}) + "\n")
    spec = {"task": "classification", "metric": "logloss", "higher_is_better": False,
            "dataset": {"kind": "jsonl", "groups": {"G": {"path": str(data)}}, "ts_col": "ts", "target": "y", "features": ["f1"]},
            "cv": {"folds": 3, "embargo_rows": 2, "min_train_frac": 0.4}, "baseline": "lr", "controls": ["prior"], "candidates": ["lr_raw"],
            "learners": {"prior": {"kind": "prior"}, "lr": {"kind": "numpy_logit"},
                         "lr_raw": {"kind": "numpy_logit", "base_features": [], "feature_blocks": [{"kind": "raw_bars", "path": str(p)}]}}}
    gdata = B.load_groups(spec["dataset"])
    df = gdata["G"]
    df.attrs["group"] = "G"
    status = {n: B.probe_learner(ls["kind"], ls.get("params") or {}) for n, ls in spec["learners"].items()}
    res = B.run_group(df, spec, spec["learners"], "logloss", status)
    assert res["arms"]["lr"]["features"] == ["f1"]
    assert res["arms"]["lr_raw"]["features"] == ["raw_r1", "raw_hl", "raw_co", "raw_gap", "raw_lv"]
    assert res["arms"]["lr_raw"]["status"] == "ok"


def test_fmt_group_sym_token():
    df = pd.DataFrame({"ts": []})
    df.attrs["group"] = "BTCUSDT_1h"
    assert B._fmt("raw/{group_sym}/1h/{group}.jsonl", df) == "raw/BTCUSDT/1h/BTCUSDT_1h.jsonl"
