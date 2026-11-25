"""Tests for scripts/research/regime_r2_family_router.py (REGIME-PROGRAM R2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

import regime_r2_family_router as R  # noqa: E402


def test_family_of():
    assert R.family_of("trend_donchian_eth_4h") == "trend_donchian"
    assert R.family_of("htf_pullback_trend_2h") == "htf_pullback"
    assert R.family_of("ict_scalp") is None


def test_features_are_causal():
    tr = R._synthetic(persistent=True)
    S, N = R.weekly_books(tr)
    f = R.features(S, N)
    b = S.columns[1]
    w = S.index[40]
    row = f[(f.book == b) & (f.week == w)].iloc[0]
    assert abs(row.m1 - S[b].iloc[39] / N[b].iloc[39]) < 1e-9
    assert row.y_sum == S[b].iloc[40]


def test_verdict_mapping():
    assert R.unit_verdict({"persist": "pass", "logit": "fail"}) == "pass"
    assert R.unit_verdict({"persist": "fail", "logit": "fail"}) == "fail"
    assert R.unit_verdict({"persist": "indeterminate", "logit": "fail"}) == "indeterminate"


def test_self_test_passes():
    assert R._self_test() == 0
