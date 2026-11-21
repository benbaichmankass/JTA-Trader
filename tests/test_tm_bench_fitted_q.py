"""tm_bench fitted-Q iteration (fqi_stop_value; lane ML-PRIMARY-17, 2026-11-20): the optimal-stopping backup is exact."""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research"))

tm = pytest.importorskip("tm_bench")


class _Memo:
    """A perfect fitter: predicts the training target for a seen row (rows are unique ids here)."""

    def __init__(self, X, y):
        self.m = {tuple(r): float(v) for r, v in zip(X, y)}

    def predict(self, X):
        return np.array([self.m[tuple(r)] for r in X])


def _ids(n, base):
    return np.array([[base + k] for k in range(n)], dtype=float)


def test_hold_value_equals_optimal_stopping_value_with_an_exact_fitter():
    c1 = np.array([0.1, -0.2, 0.5, 0.0])        # stop values relative to B0 on trade 1
    c2 = np.array([-0.3, -0.1, -0.4])            # never worth stopping on trade 2
    X1, X2 = _ids(4, 0), _ids(3, 100)
    qc, qh = tm.fqi_stop([X1, X2], [c1, c2], _Memo, iters=10)
    # Q_hold(s) = max(0, max_{s' > s} c(s')): the value of continuing optimally (holding to the end is B0 = 0)
    want1 = [0.5, 0.5, 0.0, 0.0]
    want2 = [0.0, 0.0, 0.0]
    assert np.allclose(qh.predict(X1), want1) and np.allclose(qh.predict(X2), want2)
    assert np.allclose(qc.predict(X1), c1)
    # the policy acts where stopping now beats continuing: only trade 1 at s=2 (0.5 > 0.0); s=0 (0.1 < 0.5) waits
    adv = qc.predict(X1) - qh.predict(X1)
    assert [i for i, a in enumerate(adv) if a > 0] == [2]


def test_iterations_propagate_one_step_per_sweep():
    c = np.array([0.0, 0.0, 0.0, 0.9])
    X = _ids(4, 0)
    _, qh1 = tm.fqi_stop([X], [c], _Memo, iters=1)
    _, qh3 = tm.fqi_stop([X], [c], _Memo, iters=3)
    assert np.allclose(qh1.predict(X), [0.0, 0.0, 0.9, 0.0])
    assert np.allclose(qh3.predict(X), [0.9, 0.9, 0.9, 0.0])


def test_nan_close_labels_are_zero_and_zero_iters_has_no_hold_head():
    c = np.array([np.nan, 0.2])
    qc, qh = tm.fqi_stop([_ids(2, 0)], [c], _Memo, iters=0)
    assert qh is None and np.allclose(qc.predict(_ids(2, 0)), [0.0, 0.2])


def test_learner_scores_offer_close_only():
    class _K:
        def __init__(self, v):
            self.v = v

        def predict(self, X):
            return np.full(len(X), self.v)
    sc = tm.learner_scores("fqi_stop_value", {"q_close": _K(0.3), "q_hold": _K(0.1)}, np.zeros((2, 3)), np.zeros(3))
    j = tm.ACTIONS.index("close")
    assert np.allclose(sc[:, j], 0.2) and np.all(np.isneginf(np.delete(sc, j, axis=1)))
    assert "fqi_stop_value" in tm.VALUE_LEARNERS


def test_fqi_requires_close_only_action_set():
    with pytest.raises(ValueError, match="optimal-STOPPING"):
        tm.score({"trades": []}, None, k=2, n_boot=10, draws=1, seed=1, cost=lambda s: (0.0, 0.0),
                 kinds=("fqi_stop_value",), checkins=("every_bar",), actions=["close", "partial_close_50"])
