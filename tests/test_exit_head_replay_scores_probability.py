"""Regression: exit-head research replays must score P(class=1), never the class label.

train_exit_head.train_model() returns an sklearn LGBMClassifier; its .predict is the 0/1 label. Four replays fed that label to
would_exit_for(score < tau=0.10), so they fired whenever P < 0.5 instead of P < 0.10 (MEASURED 2026-11-18: aadc-12 fired on
16,739 of 18,649 trades). These tests pin the semantics and forbid the old pattern in every replay that trains through train_model.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "ml"), str(REPO / "scripts" / "research")]

REPLAYS = [
    "scripts/research/exit_head_label_bakeoff.py",
    "scripts/research/exit_head_eth_oos_control.py",
    "scripts/research/exit_head_walkforward_multifold.py",
    "scripts/research/volcomp_exit_head_bakeoff.py",
]


def test_classifier_predict_is_a_label_and_predict_proba_matches_the_served_booster():
    lgb = pytest.importorskip("lightgbm")
    rng = np.random.default_rng(7)
    X = rng.random((400, 3))
    y = (X[:, 0] + 0.3 * rng.random(400) > 0.65).astype(int)
    clf = lgb.LGBMClassifier(n_estimators=30, verbose=-1, random_state=7).fit(X, y)
    assert type(clf).__name__ == "LGBMClassifier"
    labels = {float(clf.predict(X[i:i + 1])[0]) for i in range(60)}
    assert labels <= {0.0, 1.0}, "precondition: .predict on the classifier IS the label"
    ps = [float(clf.predict_proba(X[i:i + 1])[0][1]) for i in range(60)]
    assert all(0.0 <= p <= 1.0 for p in ps) and len({round(p, 6) for p in ps}) > 2
    # the served artifact path (raw Booster from booster_txt) gives the same P as predict_proba
    assert float(clf.booster_.predict(X[:1])[0]) == pytest.approx(ps[0])


@pytest.mark.parametrize("path", REPLAYS)
def test_replays_do_not_score_the_class_label(path):
    src = (REPO / path).read_text(encoding="utf-8")
    assert ".predict_proba(vec)[0][1]" in src, f"{path} must score P(class=1) with predict_proba"
    assert not re.search(r"_b(ooster)?\.predict\(vec\)", src), f"{path} scores .predict(vec) = the class label"
