"""pbo_cscv.py: noise -> PBO ~1/2, a planted edge -> PBO ~0; series files merge on the week key; a shared config must agree."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import pbo_cscv  # noqa: E402


def test_self_test():
    pbo_cscv.self_test()


def test_load_series_merges_and_refuses_a_disagreeing_shared_column(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"weeks": ["2025-W01", "2025-W02"], "matrix": {"base": [1.0, 2.0], "arm1": [0.5, 0.0]}}))
    b.write_text(json.dumps({"weeks": ["2025-W01", "2025-W02"], "matrix": {"base": [1.0, 2.0], "arm2": [0.0, 3.0]}}))
    weeks, m = pbo_cscv.load_series([str(a), str(b)])
    assert weeks == ["2025-W01", "2025-W02"] and sorted(m) == ["arm1", "arm2", "base"]
    b.write_text(json.dumps({"weeks": ["2025-W01"], "matrix": {"base": [9.0]}}))
    with pytest.raises(ValueError):
        pbo_cscv.load_series([str(a), str(b)])
