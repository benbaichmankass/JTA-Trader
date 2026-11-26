"""torch_gru early stopping + temperature calibration (RQ-20261126-9e72-01, the re-open of 9e71-01): opt-in params; on a target
with NO signal a calibrated GRU must land near the class-prior log-loss, where the uncalibrated long-trained one over-commits."""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
torch = pytest.importorskip("torch")


def _logloss(p, y):
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1.0))))


def test_calibrated_gru_does_not_lose_to_the_prior_on_noise():
    import ml_bakeoff as B
    rng = np.random.default_rng(0)
    X = rng.normal(size=(3000, 6)).astype(float)
    y = (rng.random(3000) < 0.3).astype(int)                      # pure noise, 30% class 1
    Xtr, ytr, Xte, yte = X[:2400], y[:2400], X[2400:], y[2400:]
    prior = np.tile(np.bincount(ytr, minlength=2) / len(ytr), (len(yte), 1))
    base = dict(window_bars=8, hidden=32, layers=1, batch_size=128, seed=0, device="cpu")
    raw = B._fit_torch_gru(Xtr, ytr, Xte, 2, dict(base, epochs=40))
    cal = B._fit_torch_gru(Xtr, ytr, Xte, 2, dict(base, epochs=40, val_frac=0.2, patience=3, calibrate="temperature"))
    l_prior, l_raw, l_cal = _logloss(prior, yte), _logloss(raw, yte), _logloss(cal, yte)
    assert l_cal <= l_prior + 0.02, (l_prior, l_cal)
    assert l_cal < l_raw, (l_raw, l_cal)
    info = B.TORCH_GRU_FIT_INFO[-1]
    assert info["temperature"] > 0 and info["n_val"] == 480 and info["epochs_run"] <= 40


def test_gru_rejects_calibration_without_a_validation_split():
    import ml_bakeoff as B
    X = np.zeros((100, 3))
    y = np.zeros(100, dtype=int)
    with pytest.raises(B.Unavailable):
        B._fit_torch_gru(X, y, X, 2, {"calibrate": "temperature", "device": "cpu"})
