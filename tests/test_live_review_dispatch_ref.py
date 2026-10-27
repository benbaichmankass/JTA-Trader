"""Pinned-ref dispatch (operator 2026-10-26: rows branch + pinned commit).

The dispatcher reads the row at ``--ref <sha>``, fetched itself, and only when
the sha is on main or live-review/rows. Everything after the read is unchanged.
"""
from __future__ import annotations

import json
import subprocess

from scripts.ops import live_review_dispatch as d
from tests.test_live_review_dispatch import APPLIED_WB, RID, TABLE_ROW, world  # noqa: F401

SHA = "a" * 40


def _fake_git(monkeypatch, *, fetch_rc=0, on=("live-review/rows",)):
    def git(*args, timeout=60):
        if args[0] == "fetch":
            return fetch_rc, ""
        if args[0] == "merge-base":
            return (0 if any(args[-1].endswith(b) for b in on) else 1), ""
        return 1, ""
    monkeypatch.setattr(d, "_git", git)


def test_a_sha_on_neither_branch_is_refused_and_nothing_is_sent(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch, on=())
    out = d.dispatch(RID, apply=True, ref=SHA)
    assert out["exit"] == d.EXIT_REFUSED and "ref_not_on_main_or_rows_branch" in out["detail"]
    assert world["calls"] == []


def test_not_a_full_sha_is_refused(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch)
    assert d.dispatch(RID, apply=True, ref="main")["exit"] == d.EXIT_REFUSED


def test_fetch_failure_is_could_not_look(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch, fetch_rc=1)
    assert d.dispatch(RID, apply=True, ref=SHA)["exit"] == d.EXIT_UNREADABLE


def test_a_row_missing_at_the_sha_is_exit_3(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch)
    world["files"][d.REVIEWS_PATH] = ""
    out = d.dispatch(RID, apply=True, ref=SHA)
    assert out["exit"] == d.EXIT_UNREADABLE and world["calls"] == []


def test_the_row_is_read_at_the_ref_not_head(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch)
    seen = []
    files = world["files"]
    monkeypatch.setattr(d, "_committed_text", lambda path, ref="HEAD": (seen.append(ref), files.get(path))[1])
    world["writeback"] = APPLIED_WB
    assert d.dispatch(RID, apply=True, ref=SHA)["exit"] == 0
    assert seen and set(seen) == {SHA}


def test_a_per_row_file_at_the_ref_is_read_and_applied_once(world, monkeypatch):  # noqa: F811
    """LTR-ROWS-SWAP-TRUNCATION: the reviewer's create-only comms/live_review/rows/<id>.json."""
    _fake_git(monkeypatch)
    files = world["files"]
    files["comms/live_review/rows/" + RID + ".json"] = files[d.REVIEWS_PATH].strip().splitlines()[-1]
    files[d.REVIEWS_PATH] = ""
    world["writeback"] = APPLIED_WB
    assert d.dispatch(RID, apply=True, ref=SHA)["exit"] == 0
    assert d.dispatch(RID, apply=True, ref=SHA)["verdict"] == "refused" and len(world["calls"]) == 1


def test_a_per_row_file_named_for_another_review_is_not_read(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch)
    files = world["files"]
    files["comms/live_review/rows/" + RID + ".json"] = '{"review_id": "LR-someone-else"}'
    out = d.dispatch(RID, apply=True, ref=SHA)
    assert out["exit"] == d.EXIT_UNREADABLE and "not a valid row" in out["detail"] and world["calls"] == []


def test_a_duplicate_review_id_via_ref_is_refused(world, monkeypatch):  # noqa: F811
    _fake_git(monkeypatch)
    world["writeback"] = APPLIED_WB
    assert d.dispatch(RID, apply=True, ref=SHA)["exit"] == 0
    again = d.dispatch(RID, apply=True, ref=SHA)
    assert again["verdict"] == "refused" and "duplicate_review_id" in again["detail"]
    assert len(world["calls"]) == 1


def _sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def test_verify_ref_against_real_git(tmp_path, monkeypatch):
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    _sh(tmp_path, "init", "-q", "-b", "main", str(origin))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _sh(origin, "config", k, v)
    (origin / "f").write_text("1")
    _sh(origin, "add", "f")
    _sh(origin, "commit", "-qm", "m1")
    _sh(origin, "checkout", "-qb", "live-review/rows")
    (origin / "f").write_text(json.dumps(TABLE_ROW))
    _sh(origin, "commit", "-qam", "row")
    rows_sha = _sh(origin, "rev-parse", "HEAD")
    _sh(origin, "checkout", "-qb", "side", "main")
    (origin / "g").write_text("x")
    _sh(origin, "add", "g")
    _sh(origin, "commit", "-qm", "side")
    side_sha = _sh(origin, "rev-parse", "HEAD")
    _sh(origin, "checkout", "-q", "main")
    _sh(tmp_path, "clone", "-q", str(origin), str(clone))
    monkeypatch.setattr(d, "_REPO_ROOT", str(clone))
    assert d.verify_ref(rows_sha) == (None, "reachable_from:live-review/rows")
    assert d.verify_ref(side_sha)[0] == "refused"   # exists upstream, but on neither branch
