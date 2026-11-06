"""A corpus that already holds two rows for one measurement must not block every later merge.

Run 42140687327 (2026-11-06): the `corpus` job died with "merge produced 7 duplicate
measurement key(s)" -- squeeze_breakout_4h @ 2023-09-06, each cell stored twice (swept
2026-08-17 and again 2026-10-04). The merge only retired a stored row when a FRESH row
re-measured it, so a stored pair was never compared and the post-merge invariant refused
every run from then on.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "scripts/research/m20_corpus_extract.py"


def _load():
    spec = importlib.util.spec_from_file_location("m20_corpus_extract_sd", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["m20_corpus_extract_sd"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


E = _load()
STATUS_DOC = {"generated_at": "2026-11-06T00:00:00+00:00",
              "verdicts": {"other_leg": {"status": "data_missing"}}}


def _cell(run, net):
    return {"kind": "cell", "leg": "squeeze_breakout_4h", "cell": "stale8_lt0R",
            "split": "2023-09-06", "tp_cap_pct": 0.099, "run_id": run,
            "base_net_r_OOS": net}


def _run(tmp_path, stored):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "verdicts.json").write_text(json.dumps(STATUS_DOC))
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in stored))
    p = subprocess.run([sys.executable, str(SRC), "--in", str(tmp_path / "a"),
                        "--corpus", str(corpus)],
                       capture_output=True, text=True, timeout=300, cwd=REPO)
    return p, corpus


def test_the_fixture_really_is_a_stored_duplicate() -> None:
    a, b = _cell("old", 1.0), _cell("new", 2.0)
    assert E.measurement_key(a) == E.measurement_key(b)


def test_two_stored_rows_for_one_measurement_collapse_to_the_later_one(tmp_path) -> None:
    p, corpus = _run(tmp_path, [_cell("2026-08-17", 23.30), _cell("2026-10-04", 23.65)])
    assert p.returncode == 0, p.stderr
    assert "stored-duplicates-collapsed: 1" in p.stdout
    rows = [json.loads(x) for x in corpus.read_text().splitlines()]
    cells = [r for r in rows if r.get("kind") == "cell"]
    assert len(cells) == 1 and cells[0]["run_id"] == "2026-10-04"
    assert any(r.get("kind") == "leg_status" for r in rows)  # the fresh row still landed


def test_a_clean_corpus_reports_zero_collapsed(tmp_path) -> None:
    p, _ = _run(tmp_path, [_cell("2026-10-04", 23.65)])
    assert p.returncode == 0, p.stderr
    assert "stored-duplicates-collapsed: 0" in p.stdout
