"""ml_learning_ledger: planted/clean pair + null-renders-dash (row ML-LEARNING-LEDGER)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("mll", Path(__file__).resolve().parents[1] / "scripts/ops/ml_learning_ledger.py")
mll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mll)


def test_planted_and_clean_pair():
    mll.self_test()


def test_could_not_look_is_null_not_zero():
    h = mll.cnl("why")
    assert h["value"] is None and mll.fmt(h) == "—" and h["read_state"] == "could_not_look"
