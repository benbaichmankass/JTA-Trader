"""ML-REAL-MONEY-OVERLAY: the overlay feature row is point-in-time and the multiplier is reduce-only."""
from __future__ import annotations

import math
import random

from src.runtime.overlay_features import FEATURES, MIN_BARS, decision_features, overlay_multiplier, score_overlay


def _bars(n: int, seed: int = 3) -> dict[str, list[float]]:
    rnd = random.Random(seed)
    c, out = 100.0, {"high": [], "low": [], "close": []}
    for _ in range(n):
        c *= math.exp(rnd.gauss(0, 0.01))
        out["close"].append(c)
        out["high"].append(c * (1 + abs(rnd.gauss(0, 0.004))))
        out["low"].append(c * (1 - abs(rnd.gauss(0, 0.004))))
    return out


def _head(b: dict[str, list[float]], k: int) -> dict[str, list[float]]:
    return {key: v[:k] for key, v in b.items()}


def test_short_history_is_unscored():
    assert decision_features(_head(_bars(MIN_BARS), MIN_BARS - 1), "long") is None
    assert overlay_multiplier({"multiplier": 0.5, "tau": 1.0}, None) == 1.0


def test_row_reads_only_bars_up_to_the_decision_bar():
    b = _bars(900)
    at = decision_features(_head(b, 600), "long")
    # Changing every bar AFTER the decision bar must not move the row.
    future = {k: v[:600] + [x * 3.0 for x in v[600:]] for k, v in b.items()}
    assert decision_features(_head(future, 600), "long") == at
    assert set(at) == set(FEATURES)
    assert all(math.isfinite(v) for v in at.values())


def test_direction_flips_signed_features():
    b = _head(_bars(700), 700)
    lo, sh = decision_features(b, "long"), decision_features(b, "short")
    for f in ("ret20_signed", "ret5_signed", "dist_ma50_signed"):
        assert math.isclose(lo[f], -sh[f], rel_tol=1e-12)
    assert math.isclose(lo["range_pos20_signed"], 1.0 - sh["range_pos20_signed"], rel_tol=1e-12)
    assert lo["adx14"] == sh["adx14"] and lo["atr_pct"] == sh["atr_pct"]


def test_multiplier_is_reduce_only_and_never_upsizes():
    row = decision_features(_head(_bars(700), 700), "long")
    base = {"features": list(FEATURES), "mean": [0.0] * len(FEATURES), "std": [1.0] * len(FEATURES),
            "coef": [0.0] * len(FEATURES), "intercept": 0.0}
    assert score_overlay(base, row) == 0.5
    assert overlay_multiplier({**base, "tau": 0.6, "multiplier": 0.5}, row) == 0.5
    assert overlay_multiplier({**base, "tau": 0.4, "multiplier": 0.5}, row) == 1.0
    # A malformed artifact can never upsize: the multiplier is clamped to [0, 1].
    assert overlay_multiplier({**base, "tau": 0.6, "multiplier": 3.0}, row) == 1.0
