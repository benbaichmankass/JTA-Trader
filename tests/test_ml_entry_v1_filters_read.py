"""ML-BAR-ONE-READ reader for the frozen ENTRY v1 (RQ-20261115-a474-04): filter masks and the registered rule."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]


def test_self_test():
    p = REPO / "scripts" / "research" / "ml_entry_v1_filters_read.py"
    spec = importlib.util.spec_from_file_location("ml_entry_v1_filters_read", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._self_test()
