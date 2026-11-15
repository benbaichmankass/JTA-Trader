"""D5 concurrency census (RQ-20261114-82fd-02): overlap counting and the registered materiality rule."""
import importlib.util
from pathlib import Path


def _mod():
    p = Path(__file__).resolve().parents[1] / "scripts" / "research" / "d5_concurrency_census.py"
    spec = importlib.util.spec_from_file_location("d5_concurrency_census", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_self_test():
    _mod()._self_test()


def test_pointer_v0_self_test_covers_bar0():
    p = Path(__file__).resolve().parents[1] / "scripts" / "research" / "ml_entry_tp_revision.py"
    import sys
    sys.path[:0] = [str(p.parents[2]), str(p.parent)]
    spec = importlib.util.spec_from_file_location("ml_entry_tp_revision", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._self_test()
    assert m.PV0_CHECKINS[0] == 0 and m.PV0_RANDOM_DRAWS >= 100


def test_aggregator_arms_self_test():
    p = Path(__file__).resolve().parents[1] / "scripts" / "research" / "d5_aggregator_arms.py"
    spec = importlib.util.spec_from_file_location("d5_aggregator_arms", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._self_test()
