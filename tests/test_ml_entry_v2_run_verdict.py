import json
import sys
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


def test_timeframe_result_maps_its_registered_word(tmp_path):
    cases = {"beats_1h": "pass", "viable_not_better": "no_action_warranted", "not_viable": "fail",
             "indeterminate": "indeterminate", "does_not_reproduce": "fail"}
    for word, want in cases.items():
        d = tmp_path / word
        d.mkdir()
        (d / "U_result.json").write_text(json.dumps(
            {"schema": "ml_entry_timeframe/1", "verdict": word, "gated_verdict": "indeterminate", "timeframe": "4h", "rows": 1234}))
        assert m.write_verdict("U", d)
        v = json.loads((d / "verdict.json").read_text())
        assert (v["verdict"], v["read_state"], v["n"]) == (want, "measured", 1234)


def test_timeframe_unknown_word_writes_nothing(tmp_path):
    (tmp_path / "U_result.json").write_text(json.dumps({"schema": "ml_entry_timeframe/1", "verdict": "weird"}))
    assert not m.write_verdict("U", tmp_path)


def test_timeframe_rows_dict_gives_an_integer_n(tmp_path):
    """The real ml_entry_timeframe/* shape: `rows` is {"<tf>/<scaling>": {"decision_rows": N}}. A null n with
    read_state=measured is inadmissible to research_result.py and lost b620..b626 (run 41566793018, 2026-11-03)."""
    (tmp_path / "U_result.json").write_text(json.dumps({
        "schema": "ml_entry_timeframe/1", "verdict": "does_not_reproduce", "timeframe": "1h",
        "rows": {"1h/bar": {"decision_rows": 1500, "symbols": 3}, "1h/clock": {"decision_rows": 800, "symbols": 3}}}))
    assert m.write_verdict("U", tmp_path)
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert v["n"] == 2300 and isinstance(v["n"], int)


def test_timeframe_rows_dict_without_counts_stays_null_not_invented(tmp_path):
    (tmp_path / "U_result.json").write_text(json.dumps({
        "schema": "ml_entry_timeframe/1", "verdict": "indeterminate", "timeframe": "1h", "rows": {"1h/bar": {"symbols": 3}}}))
    assert m.write_verdict("U", tmp_path)
    assert json.loads((tmp_path / "verdict.json").read_text())["n"] is None
