"""Train-vs-serve parity for the setup_candidates decision-time row (B2).

Plan docs/plans/ml-live-promotion-plan-2026-10-29.md § 1a (c) and § 3 P1 shadow
mechanics: every one of p2pool's 10 features must be present, non-default and
equal to the training value (|Δ| ≤ 1e-6) on identical bars, `vol_bucket`
included. This runs the dataset family's build and the live serve path
(`src.runtime.setup_features`) over the SAME recorded bars
(`tests/fixtures/ADAUSDT_2h_*.csv`, real exchange candles) and compares them
row by row, then shows a trained head scores the two rows identically.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("lightgbm")

from ml.datasets.families.setup_candidates import (  # noqa: E402
    SetupCandidatesBuilder,
    serve_spec_from_rows,
)
from ml.experiments.runner import _attach_serve_spec  # noqa: E402
from ml.predictors.lightgbm import LightGBMRegressionPredictor  # noqa: E402
from ml.trainers.lightgbm_regression import LightGBMRegressionTrainer  # noqa: E402
from src.runtime.advisory_sizing import _feature_row_from_pkg  # noqa: E402
from src.runtime.setup_features import (  # noqa: E402
    META_KEY,
    decision_features_block,
    row_for_predictor,
    setup_row,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/ADAUSDT_2h_2020-06-03_2026-10-15.csv"
SYMBOL, TF = "ADAUSDT", "2h"
N_BARS = 2500

def _p2pool_cfg() -> dict:
    """The p2pool manifest's trainer config (features, categoricals)."""
    yaml = pytest.importorskip("yaml")
    m = yaml.safe_load(
        (REPO / "ml/configs/setup-candidates-metalabel-p2pool-v1.yaml").read_text())
    return dict(m["trainer_config"])


def _recorded_bars() -> list[dict]:
    out = []
    with FIXTURE.open() as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            if i >= N_BARS:
                break
            dt = datetime.fromisoformat(r["timestamp"]).astimezone(timezone.utc)
            out.append({
                "ts": dt.isoformat().replace("+00:00", "Z"),  # market_raw's form
                "ms": int(dt.timestamp() * 1000),             # the live candle form
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            })
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    bars = _recorded_bars()
    ddir = tmp_path_factory.mktemp("mr") / "market_raw" / SYMBOL / TF / "v1"
    ddir.mkdir(parents=True)
    with (ddir / "data.jsonl").open("w") as fh:
        for b in bars:
            fh.write(json.dumps({
                "ts": b["ts"], "symbol": SYMBOL, "timeframe": TF, "source": "fixture",
                "open": b["open"], "high": b["high"], "low": b["low"],
                "close": b["close"], "volume": 1.0,
            }) + "\n")
    rows = list(SetupCandidatesBuilder().iter_rows(
        market_raw_path=ddir, cost_net=False))
    assert len(rows) >= 100, len(rows)
    return bars, rows


def _serve_frame(bars: list[dict], e: int) -> pd.DataFrame:
    """The live candles frame at decision time: closed bars ending on bar e,
    epoch-ms timestamps (the CCXT shape fetch_candles returns), 200 deep."""
    w = bars[max(0, e - 199): e + 1]
    return pd.DataFrame({
        "timestamp": [b["ms"] for b in w],
        "open": [b["open"] for b in w], "high": [b["high"] for b in w],
        "low": [b["low"] for b in w], "close": [b["close"] for b in w],
        "volume": [1.0] * len(w),
    })


def _serve_rows(bars, rows, spec):
    idx = {b["ts"]: i for i, b in enumerate(bars)}
    pairs = []
    for r in rows:
        e = idx[r["ts"]]
        block = decision_features_block(_serve_frame(bars, e), SYMBOL, TF)
        base = {"strategy_name": "x", "symbol": SYMBOL,
                "direction": "long" if r["direction"] == 1 else "short",
                "confidence": 0.5, "setup_type": "", "killzone": ""}
        served, state = setup_row(base, block, spec)
        assert state == "ok", (r["ts"], state, block.get("read_state"))
        pairs.append((r, served))
    return pairs


def test_every_p2pool_feature_equal_on_identical_bars(built):
    bars, rows = built
    cfg = _p2pool_cfg()
    feats = cfg["feature_columns"]
    cats = set(cfg["categorical_columns"])
    spec = serve_spec_from_rows(rows)
    assert spec is not None and SYMBOL in spec["vol_bucket_edges_by_symbol"]
    assert spec["timeframe_by_symbol"][SYMBOL] == [TF]
    pairs = _serve_rows(bars, rows, spec)
    assert len(pairs) == len(rows)
    for train, served in pairs:
        for f in feats:
            assert f in served, f"{f} absent from the served row"
            if f in cats:
                assert str(served[f]) == str(train[f]), (f, train["ts"], served[f], train[f])
            else:
                assert abs(float(served[f]) - float(train[f])) <= 1e-6, (
                    f, train["ts"], served[f], train[f])


def test_served_features_are_non_default(built):
    """Present is not enough: a constant-filled column passes equality on a
    constant train column. Every numeric feature varies, vol_bucket takes every
    trained bucket, both directions are served."""
    bars, rows = built
    cfg = _p2pool_cfg()
    spec = serve_spec_from_rows(rows)
    pairs = _serve_rows(bars, rows, spec)
    served = [s for _, s in pairs]
    assert {s["vol_bucket"] for s in served} == set(
        spec["vol_bucket_labels_by_symbol"][SYMBOL])
    assert {s["direction"] for s in served} == {1, -1}
    for f in cfg["feature_columns"]:
        if f == "symbol":  # one-symbol fixture: the served value is the trained one
            assert {s[f] for s in served} == {SYMBOL}
        elif f in cfg["categorical_columns"]:
            assert len({str(s[f]) for s in served}) >= 2, f
        else:
            vals = [float(s[f]) for s in served]
            assert all(math.isfinite(v) for v in vals), f
            assert len(set(vals)) > len(vals) // 2, f"{f} is near-constant"


def test_trained_head_scores_train_and_serve_rows_identically(built, tmp_path):
    """End to end: fit the p2pool trainer config, freeze the serve spec through
    the runner hook, reload through the live predictor, and score both rows."""
    bars, rows = built
    cfg = _p2pool_cfg()
    cfg["n_iter"] = 30
    cfg["lgbm_params"] = {**cfg.get("lgbm_params", {}), "min_data_in_leaf": 10}
    state = dict(LightGBMRegressionTrainer().fit(rows, cfg))
    (tmp_path / "metadata.json").write_text(json.dumps(
        {"build_params": {"vol_window_n": 20, "momentum_window": 10}}))
    manifest = SimpleNamespace(dataset=SimpleNamespace(family="setup_candidates"),
                               trainer_config=cfg)
    _attach_serve_spec(state, manifest, rows, tmp_path)
    assert state["serve_spec"]["family"] == "setup_candidates"
    pred = LightGBMRegressionPredictor(json.loads(json.dumps(state)))
    assert pred.serve_spec is not None
    pairs = _serve_rows(bars, rows, pred.serve_spec)
    diffs = [abs(pred.predict(t) - pred.predict(s)) for t, s in pairs]
    assert max(diffs) <= 1e-9
    # And the advisory path's row is that same served row.
    t, _s = pairs[-1]
    e = {b["ts"]: i for i, b in enumerate(bars)}[t["ts"]]
    pkg = SimpleNamespace(
        strategy="x", symbol=SYMBOL, confidence=0.5,
        direction="long" if t["direction"] == 1 else "short",
        meta={META_KEY: decision_features_block(_serve_frame(bars, e), SYMBOL, TF)},
    )
    row, st = _feature_row_from_pkg(pkg, pred)
    assert st == "ok"
    assert abs(pred.predict(row) - pred.predict(t)) <= 1e-9
    # The pre-B2 row (six trade-context fields) serves every candle feature dead.
    legacy, st0 = _feature_row_from_pkg(pkg)
    assert st0 is None
    assert not (set(cfg["feature_columns"]) - {"direction", "symbol"}) & set(legacy)


def test_head_without_spec_sees_the_row_unchanged():
    base = {"symbol": "BTCUSDT", "direction": "long"}
    p = SimpleNamespace(serve_spec=None, model_id="trade-outcome-x")
    row, state = row_for_predictor(p, base, {"read_state": "ok", "features": {"x": 1}})
    assert row is base and state is None


@pytest.mark.parametrize("block,why", [
    (None, "no_setup_features"),
    ({"read_state": "incomplete_window"}, "setup_features_incomplete_window"),
])
def test_refusal_is_named_and_serves_no_default(block, why):
    spec = {"vol_bucket_edges_by_symbol": {"BTCUSDT": [0.01]},
            "vol_bucket_labels_by_symbol": {"BTCUSDT": ["vol_b0", "vol_b1"]},
            "timeframe_by_symbol": {"BTCUSDT": ["1h"]}}
    row, state = setup_row({"symbol": "BTCUSDT", "direction": "long"}, block, spec)
    assert row is None and state == why


def test_timeframe_mismatch_is_refused(built):
    """A 4h leg's candles are not the 1h bars a 1h-built head trained on."""
    bars, rows = built
    spec = serve_spec_from_rows(rows)
    block = decision_features_block(_serve_frame(bars, 500), SYMBOL, "4h")
    row, state = setup_row({"symbol": SYMBOL, "direction": "long"}, block, spec)
    assert row is None and state == "timeframe_mismatch"
