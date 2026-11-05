"""ML-ENTRY-EQUITY-NATIVE: the equity-native ENTRY harness (dev walk-forward + one confirming read). Offline, synthetic bars."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_entry_equity as Q  # noqa: E402


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_entry_equity.py"), "--self-test"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "self-test ok" in r.stdout, r.stdout + r.stderr


def test_no_crypto_feature_and_registered_grid():
    for cfg in Q.CONFIGS.values():
        assert not any(("btc" in f) or ("perp" in f) for f in cfg["features"]), cfg["features"]
    assert len(Q.CONFIGS) * len(Q.TAUS) == 12
    assert Q.TRAIN_END < Q.CONFIRM_START and Q.EMBARGO_DAYS >= 14


def test_pool_rule_is_the_registered_one():
    import ml_entry_alpaca_score as S
    assert S.POOL_RULE_SHA256 == "e9702661d1a596a0f7e84e632c0ca8b5c2743a728f02147477c003644a0858e2"
