"""RQ-NEW-UNIT-SELF-LAND (2026-11-07): a NEW research/queue unit self-lands as a pre-run
registration; an edit to an existing unit, a dispatched unit, a unit with a result, or a
unit without a pre-registered rule stays held (check_pr_landing.new_unit_registration_violation).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))

import check_pr_landing as g  # noqa: E402

UNIT = (
    "id: RQ-20310101-001\n"
    "status: queued\n"
    "cadence: once\n"
    "decision_rule:\n"
    "  id: R1\n"
    "  registered_before_run: true\n"
)


def _git(r: Path, *a: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(r),
                   check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    (r / "research/queue").mkdir(parents=True)
    (r / "research/queue/README.md").write_text("x")
    (r / "research/queue/RQ-20300101-001.yaml").write_text(UNIT.replace("20310101", "20300101"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "claude/lane")
    return r


def _commit(r: Path, rel: str, text: str) -> None:
    p = r / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")


def test_a_new_pre_registered_unit_self_lands(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "research/queue/RQ-20310101-001.yaml", UNIT)
    assert g.unvouched_paths(r, "main", ["research/queue/RQ-20310101-001.yaml"]) == []


def test_editing_an_existing_unit_rule_stays_held(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/RQ-20300101-001.yaml"
    _commit(r, p, (r / p).read_text().replace("id: R1", "id: R2"))
    assert g.unvouched_paths(r, "main", [p]) == [p]


def test_a_new_unit_without_a_pre_registered_rule_is_held(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/RQ-20310101-001.yaml"
    _commit(r, p, UNIT.replace("  registered_before_run: true\n", ""))
    assert g.unvouched_paths(r, "main", [p]) == [p]
    assert "registered_before_run" in g.stamp_only_violation(r, "main", p)


def test_a_new_unit_already_dispatched_is_held(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/RQ-20310101-001.yaml"
    _commit(r, p, UNIT + "last_dispatched_at: '2031-01-01T00:00:00+00:00'\n")
    assert g.unvouched_paths(r, "main", [p]) == [p]


def test_a_new_unit_whose_result_already_exists_is_held(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "research/results/RQ-20310101-001/1.jsonl", '{"verdict":"pass"}\n')
    p = "research/queue/RQ-20310101-001.yaml"
    _commit(r, p, UNIT)
    assert g.unvouched_paths(r, "main", [p]) == [p]
    assert "already exists" in g.stamp_only_violation(r, "main", p)


def test_id_must_match_the_file_stem(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/RQ-20310101-002.yaml"
    _commit(r, p, UNIT)
    assert g.unvouched_paths(r, "main", [p]) == [p]


def test_a_new_file_under_blocked_is_held(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/blocked/RQ-20310101-001.yaml"
    _commit(r, p, UNIT)
    assert g.unvouched_paths(r, "main", [p]) == [p]


def test_a_new_unit_that_does_not_parse_is_held(tmp_path):
    r = _repo(tmp_path)
    p = "research/queue/RQ-20310101-001.yaml"
    _commit(r, p, "id: [unclosed\n")
    assert g.unvouched_paths(r, "main", [p]) == [p]
