"""ML-PROP-ITERATE ledger emission + the gate's --arm-label input (lane PROP-STRUCT-EXITS-ML-LEDGERS)."""
import importlib.util
import sys
from pathlib import Path

RES = Path(__file__).resolve().parents[2] / "scripts" / "research"
sys.path.insert(0, str(RES))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, RES / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ledger_self_test():
    _load("ml_variant_ledger")._self_test()


def test_find_ledger_arm_label(tmp_path, monkeypatch):
    g = _load("ml_variant_prop_gate")
    monkeypatch.setattr(g, "REPO", tmp_path)
    d = tmp_path / "comms/research/RQ-X-01/123/arms"
    d.mkdir(parents=True)
    (d / "SW15__trades.jsonl").write_text("{}\n")
    assert g.find_ledger("RQ-X-01", "SW15") == d / "SW15__trades.jsonl"
    assert g.find_ledger("RQ-X-01", "NOPE") is None            # absent arm = None (graded INDETERMINATE), never a silent pass
    assert g.find_ledger("RQ-X-01") is None
