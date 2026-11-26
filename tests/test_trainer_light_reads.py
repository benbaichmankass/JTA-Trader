"""Row TRAINER-LIGHT-READS: the weekly registry feature pre-flight (RQ-20261126-f17a-01) and the weekly vol-head label audit
(RQ-20261126-f17a-02) -- dataset resolution, the label metrics, and verdict mapping (self-tests), plus empty-registry handling."""
import json

from scripts.research import registry_feature_preflight as P
from scripts.research import vol_head_label_audit as V


def test_self_tests():
    P.self_test()
    V.self_test()


def test_empty_registry_is_no_data_not_a_pass(tmp_path):
    reg = tmp_path / "reg"
    reg.mkdir()
    for mod, out in ((P, tmp_path / "p"), (V, tmp_path / "v")):
        assert mod.main(["--out", str(out), "--registry-root", str(reg)]) == 0
        v = json.loads((out / "verdict.json").read_text())
        assert v["verdict"] in ("indeterminate", "not_applicable") and v["read_state"] in ("no_data", "producer_failed")
