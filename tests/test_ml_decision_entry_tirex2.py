"""TiRex-2 zero-shot forecast arm of ml_decision_entry.py lever-arms (RQ-20261128-e2c0-01).

The real forecaster is not installed in CI; these tests drive tirex2_features with a stand-in forecast_fn of TiRex-2's exact output
shape ([b, 9 quantiles, horizon] prices) and check the column maths, the point-in-time context, the budget cut and the bundle loader.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_decision_entry as M  # noqa: E402

LV = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])


def _cache(tmp_path, n=40):
    closes = 100.0 + np.arange(n, dtype=float)
    pd.DataFrame({"close": closes}).to_pickle(tmp_path / "AAA.pkl")
    return closes


def test_quantile_features_are_scale_free_and_exact():
    q = (100 * np.exp(0.01 + 0.02 * (LV - 0.5)))[None, :, None].repeat(24, axis=2)
    f1 = M.tirex2_quantile_features(q, np.array([100.0]))
    f2 = M.tirex2_quantile_features(q * 7.0, np.array([700.0]))
    assert np.allclose(f1, f2, atol=1e-6)
    assert abs(f1[0, 1] - 0.01) < 1e-6 and abs(f1[0, 3] - 0.016) < 1e-6 and abs(f1[0, 5] - 0.625) < 1e-4


def test_zero_spread_gives_nan_not_inf():
    f = M.tirex2_quantile_features(np.full((1, 9, 24), 50.0), np.array([50.0]))
    assert f[0, 3] == 0 and np.isnan(f[0, 4]) and np.isnan(f[0, 5])


def test_features_use_only_closes_up_to_the_row(tmp_path):
    closes = _cache(tmp_path)
    seen = []

    def fake(x):
        seen.append(x.copy())
        return np.repeat(x[:, -1][:, None, None], 9, axis=1).repeat(4, axis=2) * np.exp(0.01 * (LV - 0.5))[None, :, None]

    tab = pd.DataFrame({"symbol": ["AAA"] * 3, "i": [5, 20, 39]})
    x, info = M.tirex2_features(tmp_path, tab, forecast_fn=fake, context=10, horizon=4, hole_safe=False)
    assert info["rows_no_context"] == 1 and np.isnan(x[0]).all() and np.isfinite(x[1:]).all()
    ctx = np.concatenate(seen)
    assert ctx[0, -1] == closes[20] and ctx[1, -1] == closes[39] and ctx.shape[1] == 10


def test_budget_cut_reports_and_grades_nothing(tmp_path):
    _cache(tmp_path)
    tab = pd.DataFrame({"symbol": ["AAA"], "i": [30]})
    x, info = M.tirex2_features(tmp_path, tab, forecast_fn=lambda a: None, context=10, hole_safe=False, deadline=0.0)
    assert info["budget_cut"] and np.isnan(x).all()


def test_permutation_placebo_keeps_marginals():
    x = np.arange(30, dtype=float).reshape(10, 3)
    p = M.permute_within(x, np.random.default_rng(0))
    assert sorted(p[:, 2].tolist()) == x[:, 2].tolist() and not np.array_equal(p, x)


def test_model_dir_from_flat_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("TIREX2_MODEL_DIR", raising=False)
    monkeypatch.setenv("TIREX2_BUNDLE_DIR", str(tmp_path))
    (tmp_path / "tirex-2__config.json").write_text("{}")
    assert M.tirex2_model_dir() is None          # weights missing -> unavailable, never a half model dir
    (tmp_path / "tirex-2__model.safetensors").write_bytes(b"x")
    d = Path(M.tirex2_model_dir())
    assert (d / "config.json").exists() and (d / "model.safetensors").exists()
