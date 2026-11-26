"""ml_bakeoff POOLED mode (ML-GRU-POOLED-BP2, 2026-11-26): ``dataset.paths`` concatenates every glob match into one group,
``entity_col`` orders rows by (ts, entity), and torch_gru windows never span two entities."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))


def test_entity_windows_stay_inside_their_entity():
    import ml_bakeoff as B
    # interleaved rows of two entities in time order: A0 B0 A1 B1 A2 B2 ...; feature = entity*100 + its own step
    ent = np.array([0, 1] * 5)
    step = np.repeat(np.arange(5), 2)
    Z = (ent * 100 + step).astype(np.float32)[:, None]
    w = B.entity_windows(Z, ent, 3, np.arange(10))
    assert w.shape == (10, 3, 1)
    for i in range(10):
        vals = w[i, :, 0]
        assert set((vals // 100).astype(int)) == {ent[i]}, (i, vals)          # never another entity's row
        assert vals[-1] == Z[i, 0]                                              # the row itself is last
    assert list(w[0, :, 0]) == [0, 0, 0] and list(w[9, :, 0]) == [102, 103, 104]   # edge padding, then trailing steps


def test_entity_windows_single_entity_equals_the_plain_windows():
    import ml_bakeoff as B
    Z = np.arange(12, dtype=np.float32).reshape(6, 2)
    W = 4
    Zp = np.vstack([np.repeat(Z[:1], W - 1, axis=0), Z])
    plain = Zp[np.arange(6)[:, None] + np.arange(W)[None, :]]
    assert np.array_equal(B.entity_windows(Z, np.zeros(6, dtype=int), W, np.arange(6)), plain)
    assert np.array_equal(B.entity_windows(Z, np.zeros(6, dtype=int), W, np.arange(3, 6)), plain[3:])


def _shard(path: Path, sym: str, n: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for i in range(n):
            x = float(rng.normal())
            fh.write(json.dumps({"ts": f"2026-01-{1 + i // 24:02d}T{i % 24:02d}:00:00Z", "symbol": sym, "x0": x,
                                 "label": "hi" if x + 0.5 * rng.normal() > 0 else "lo"}) + "\n")


def test_pooled_paths_load_one_group_in_calendar_order(tmp_path, monkeypatch):
    import ml_bakeoff as B
    for i, sym in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT")):
        _shard(tmp_path / f"datasets-out/f/{sym}/1h/v102/data.jsonl", sym, 300, i)
    monkeypatch.setenv("ML_DATA_ROOT", str(tmp_path))
    ds = {"kind": "jsonl", "paths": "datasets-out/f/*/1h/v102/data.jsonl", "ts_col": "ts", "target": "label",
          "features": ["x0"], "entity_col": "symbol", "tail_rows": 200}
    g = B.load_groups(ds)
    assert list(g) == ["POOLED"] and len(g["POOLED"]) == 600 and g["POOLED"]["symbol"].nunique() == 3
    assert len(B.POOLED_FILES) == 3
    spec = {"task": "classification", "dataset": ds, "cv": {"folds": 3, "embargo_rows": 6, "min_train_frac": 0.4}}
    res = B.run_group(g["POOLED"], spec, {"prior": {"kind": "prior"}, "logit": {"kind": "numpy_logit"}}, "logloss",
                      {"prior": None, "logit": None})
    assert res["n_entities"] == 3 and res["n_rows"] == 600
    assert res["arms"]["logit"]["status"] == "ok" and len(res["arms"]["logit"]["windows"]["cv"]["fold_metric"]) == 3


def test_router_checks_pooled_paths_against_the_allowlist():
    from scripts.research import compute_router as cr
    entry = {"ml_bakeoff": {"dataset": {"paths": "datasets-out/market_features/*/1h/v102/data.jsonl"}}}
    assert cr.unit_dataset_paths(entry) == ["datasets-out/market_features/*/1h/v102/data.jsonl"]


def test_pooled_gru_runs_with_entity_windows():
    torch = pytest.importorskip("torch")  # noqa: F841
    import ml_bakeoff as B
    rng = np.random.default_rng(1)
    n = 600
    X = rng.normal(size=(n, 3))
    y = (X[:, 0] > 0).astype(int)
    ent = np.tile(np.arange(3), n // 3)
    p = B._fit_torch_gru(X[:450], y[:450], X[450:], 2,
                         {"window_bars": 4, "hidden": 8, "epochs": 2, "device": "cpu", "max_train_windows": 300,
                          "val_frac": 0.2, "patience": 1, "calibrate": "temperature",
                          "_entity_tr": ent[:450], "_entity_te": ent[450:]})
    assert p.shape == (150, 2) and np.allclose(p.sum(1), 1.0, atol=1e-5)
    assert B.TORCH_GRU_FIT_INFO[-1]["n_train"] + B.TORCH_GRU_FIT_INFO[-1]["n_val"] == 300
