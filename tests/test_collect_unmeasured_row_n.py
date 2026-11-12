"""AUD-20261019-RESEARCH-SLO-RED (2026-11-12): per-row records the desk drivers wrote were refused by research_result,
so whole runs never landed (RQ-20261026-bf56-02/-03, -e535-03). The collector normalizes them; clean rows pass untouched."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.research import collect_runner_results as c


def _write(tmp: Path, rows) -> dict:
    f = tmp / "records.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"records_file": str(f), "verdict": "fail", "read_state": "measured"}


def _rows(rec: dict):
    return [json.loads(ln) for ln in Path(rec["records_file"]).read_text().splitlines() if ln.strip()]


def test_no_data_row_with_a_count_lands_with_n_null_and_the_count_in_population(tmp_path):
    rec = _write(tmp_path, [{"leg": "a", "population": "a in_trade", "n": 31, "verdict": "fail", "read_state": "measured"},
                            {"leg": "b", "population": "b in_trade", "n": 15, "verdict": "not_applicable",
                             "read_state": "no_data"}])
    out = _rows(c._null_unmeasured_row_n(tmp_path, rec))
    assert out[0] == {"leg": "a", "population": "a in_trade", "n": 31, "verdict": "fail", "read_state": "measured"}
    assert out[1]["n"] is None and "15 observation(s)" in out[1]["population"]


def test_measured_row_with_not_applicable_takes_the_run_verdict(tmp_path):
    rec = _write(tmp_path, [{"leg": "a", "population": "a", "n": 31, "verdict": "not_applicable", "read_state": "measured"}])
    assert _rows(c._null_unmeasured_row_n(tmp_path, rec))[0]["verdict"] == "fail"


def test_clean_rows_are_untouched(tmp_path):
    rec = _write(tmp_path, [{"leg": "a", "population": "a", "n": None, "verdict": "not_applicable", "read_state": "no_data"}])
    assert c._null_unmeasured_row_n(tmp_path, rec) is rec
