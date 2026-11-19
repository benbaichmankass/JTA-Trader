"""AUTOMATION-DATACOMMIT-CONFLICT: a conflicted stamp PR is refreshed or closed as superseded, never stranded."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import refresh_stamp_prs as rsp

UNIT = "id: RQ-T-01\nquestion: q\nlast_dispatched_at: {s}\n"


def _g(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def _repo(tmp_path, branch_stamp, main_stamp, main_extra="", branch_extra=""):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    w = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(origin), str(w)], check=True, capture_output=True)
    (w / "research" / "queue").mkdir(parents=True)
    f = w / "research" / "queue" / "RQ-T-01.yaml"
    f.write_text(UNIT.format(s="2026-11-19T08:00:00Z"))
    _g(w, "add", "-A")
    _g(w, "commit", "-qm", "base")
    _g(w, "push", "-q", "origin", "HEAD:main")
    _g(w, "checkout", "-qb", "automation/research-queue-stamp-1-1")
    f.write_text(UNIT.format(s=branch_stamp) + branch_extra)
    _g(w, "commit", "-qam", "stamp")
    _g(w, "push", "-q", "origin", "HEAD:automation/research-queue-stamp-1-1")
    _g(w, "checkout", "-q", "main")
    f.write_text(UNIT.format(s=main_stamp) + main_extra)
    _g(w, "commit", "-qam", "later stamp")
    _g(w, "push", "-q", "origin", "HEAD:main")
    return w


def test_branch_with_older_stamp_is_superseded(tmp_path):
    w = _repo(tmp_path, "2026-11-19T09:00:00Z", "2026-11-19T10:00:00Z")
    out, _ = rsp.refresh_branch(w, "automation/research-queue-stamp-1-1", push=False)
    assert out == "superseded"


def test_branch_with_newer_stamp_is_refreshed_and_pushed(tmp_path):
    w = _repo(tmp_path, "2026-11-19T11:00:00Z", "2026-11-19T10:00:00Z")
    out, detail = rsp.refresh_branch(w, "automation/research-queue-stamp-1-1", push=True)
    assert out == "refreshed" and "RQ-T-01.yaml" in detail
    _g(w, "fetch", "-q", "origin")
    # the pushed branch now merges cleanly into main and carries the newer stamp
    assert "2026-11-19T11:00:00Z" in _g(w, "show", "origin/automation/research-queue-stamp-1-1:research/queue/RQ-T-01.yaml")
    assert _g(w, "merge-base", "--is-ancestor", "origin/main", "origin/automation/research-queue-stamp-1-1") == ""


def test_a_non_stamp_conflict_is_refused_and_left_alone(tmp_path):
    """The BRANCH itself changed more than the stamp (and main edited the same place): not ours to guess."""
    w = _repo(tmp_path, "2026-11-19T11:00:00Z", "2026-11-19T10:00:00Z",
              main_extra="decision_rule: main-edit\n", branch_extra="decision_rule: branch-edit\n")
    before = _g(w, "rev-parse", "origin/automation/research-queue-stamp-1-1")
    out, _ = rsp.refresh_branch(w, "automation/research-queue-stamp-1-1", push=True)
    assert out == "not_stamp_only"
    _g(w, "fetch", "-q", "origin")
    assert _g(w, "rev-parse", "origin/automation/research-queue-stamp-1-1") == before
    assert _g(w, "status", "--porcelain") == ""


def test_a_stamp_only_branch_keeps_mains_other_edit_and_its_own_newer_stamp(tmp_path):
    """#27359 (2026-11-19, stranded 3 h): the branch changed ONLY last_dispatched_at; main also appended a block (a
    manager's `grading:`, a fixed run command) next to the stamp line, so git conflicts. Nothing the branch wrote is lost
    by taking main's text and the winning stamp."""
    w = _repo(tmp_path, "2026-11-19T11:00:00Z", "2026-11-19T10:00:00Z", main_extra="decision_rule: changed\n")
    out, detail = rsp.refresh_branch(w, "automation/research-queue-stamp-1-1", push=True)
    assert out == "refreshed" and "RQ-T-01.yaml" in detail
    _g(w, "fetch", "-q", "origin")
    merged = _g(w, "show", "origin/automation/research-queue-stamp-1-1:research/queue/RQ-T-01.yaml")
    assert "decision_rule: changed" in merged                 # main's edit survives
    assert "2026-11-19T11:00:00Z" in merged                   # the branch's newer stamp wins
    assert "2026-11-19T10:00:00Z" not in merged


def test_a_stamp_only_branch_with_an_older_stamp_is_superseded_even_when_main_edited_the_unit(tmp_path):
    w = _repo(tmp_path, "2026-11-19T09:00:00Z", "2026-11-19T10:00:00Z", main_extra="decision_rule: changed\n")
    out, _ = rsp.refresh_branch(w, "automation/research-queue-stamp-1-1", push=False)
    assert out == "superseded"


def test_the_dispatcher_runs_it_every_cycle():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/research-queue-dispatch.yml").read_text()
    assert "scripts/research/refresh_stamp_prs.py" in wf
