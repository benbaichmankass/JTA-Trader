"""REGIME-PROGRAM R1 (scripts/research/regime_persistence.py): bootstrap CI and the registered verdict."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_regime_persistence_self_test():
    import regime_persistence as P
    P._self_test()
