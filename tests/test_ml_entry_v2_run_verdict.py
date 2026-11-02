import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_entry_v2_run as m


def _w(tmp_path, cells):
    (tmp_path / "x_result.json").write_text(json.dumps({"cells": cells}))


def test_all_no_win_is_fail_measured(tmp_path):
    _w(tmp_path, {"a": {"verdict": "base"}, "b": {"verdict": "no_win", "n": [10, 9]}})
    assert m.write_verdict("U", tmp_path)
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert (v["verdict"], v["read_state"], v["n"]) == ("fail", "measured", 10)


def test_a_win_is_pass_and_indeterminate_is_not_fail(tmp_path):
    _w(tmp_path, {"b": {"verdict": "win"}, "c": {"verdict": "no_win"}})
    m.write_verdict("U", tmp_path)
    assert json.loads((tmp_path / "verdict.json").read_text())["verdict"] == "pass"


def test_unknown_shape_writes_nothing(tmp_path):
    _w(tmp_path, {"b": {"verdict": "weird"}})
    assert not m.write_verdict("U", tmp_path)
    assert not (tmp_path / "verdict.json").exists()
