"""exit_head_label_bakeoff FEATURE arms (lane ML-PRIMARY-17, 2026-11-20): the feature-family lever on the 1h donchian exit head."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "ml"))

import exit_head_label_bakeoff as B  # noqa: E402


def test_self_test_passes():
    assert B._self_test() == 0


def test_feature_arms_use_live_feature_columns():
    """Every column any arm trains on must be emitted by the live _feature_row, or the replay scores NaN (no parity)."""
    import train_exit_head as teh
    src = open(os.path.join(ROOT, "src", "runtime", "exit_head_shadow.py"), encoding="utf-8").read()
    for arm in B.FEATURE_ARMS:
        feats = B.arm_features(teh, arm)
        assert feats, arm
        assert len(feats) == len(set(feats)), arm
        for f in feats:
            assert f'"{f}"' in src, f"{arm}: {f} is not emitted by exit_head_shadow._feature_row"


def test_champion_and_label_arms_keep_shipped_features():
    import train_exit_head as teh
    assert B.arm_features(teh, B.CHAMPION) == list(teh.FEATURES)
    for arm in B.TARGETS:
        assert B.arm_features(teh, arm) == list(teh.FEATURES)


def test_unknown_feature_arm_is_refused():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/research/exit_head_label_bakeoff.py"),
                        "--feature-arms", "feat_nope", "--json", os.devnull], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0 and "unknown feature arm" in r.stderr


def test_arms_none_means_feature_arms_only():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/research/exit_head_label_bakeoff.py"),
                        "--arms", "none", "--json", os.devnull], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0 and "no arm to judge" in r.stderr
