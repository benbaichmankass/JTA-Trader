"""LTR-DIRECT-EVIDENCE-SOURCE (2026-11-15): a direct-POSTed row whose outcome table exists only on live-review/rows.

Reviewer 0920 POSTed two CLOSE rows directly (LR-20261115T1129Z-pkg-858c60dc674d418f ETH, -pkg-ec406687dc6d449f
SOL) after #26258. Both sat at ``could_not_look`` / exit 3, ``evidence_not_yet_at_ref``: a direct row carries no
pinned ref, so the dispatcher looked for the table only under --local-root and at HEAD, and the reviewer had
committed it to the rows branch. The dispatcher now reads such a table at the rows-branch tip.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.ops import live_review_dispatch as d
from tests.test_live_review_apply_exit2 import CLOSE_ROW, MEASURED, RID, TABLE, _pairs, direct  # noqa: F401


def _drop_local_table(direct):  # noqa: F811
    for root in d.LOCAL_ROOTS:
        p = root / TABLE
        if p.exists():
            p.unlink()


def test_a_direct_row_whose_table_is_only_on_the_rows_branch_applies_with_exit_0(direct, monkeypatch):  # noqa: F811
    _drop_local_table(direct)
    seen = []
    monkeypatch.setattr(d, "_rows_branch_text",
                        lambda path: (seen.append(path) or MEASURED, f"{d.ROWS_BRANCH}@{'ab' * 20}"))
    res = d.dispatch(RID, apply=True)
    assert res["exit"] == 0 and res["verdict"] == "dispatched", res
    assert seen == [TABLE]
    assert res["evidence_source"] == f"live-review/rows@{'ab' * 20}"
    ev = _pairs(direct["calls"][0])["--evidence"]
    assert Path(direct["repo"], ev).read_text() == MEASURED   # materialized into the checkout for the apply


def test_a_direct_row_whose_table_is_nowhere_still_waits_with_exit_3(direct, monkeypatch):  # noqa: F811
    _drop_local_table(direct)
    monkeypatch.setattr(d, "_rows_branch_text", lambda path: (None, "not_on_rows_branch@" + "ab" * 6))
    res = d.dispatch(RID, apply=True)
    assert res["exit"] == d.EXIT_UNREADABLE and res["verdict"] == "could_not_look", res
    assert res["detail"] == f"evidence_not_yet_at_ref:{TABLE}"
    assert res["evidence_source"].startswith("not_on_rows_branch@")
    assert direct["calls"] == []


def test_a_table_in_a_local_root_never_touches_the_rows_branch(direct, monkeypatch):  # noqa: F811
    monkeypatch.setattr(d, "_rows_branch_text", lambda path: (_ for _ in ()).throw(AssertionError("fetched")))
    res = d.dispatch(RID, apply=True)
    assert res["exit"] == 0 and "evidence_source" not in res


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_rows_branch_text_reads_the_fetched_tip(tmp_path, monkeypatch):
    origin, work, repo = tmp_path / "origin.git", tmp_path / "work", tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    (work / "README").write_text("main\n")
    for step in (("add", "README"), ("commit", "-qm", "main"), ("push", "-q", "origin", "HEAD:main")):
        _git(work, *step)
    _git(work, "checkout", "-qb", "live-review/rows")
    (work / TABLE).parent.mkdir(parents=True)
    (work / TABLE).write_text(json.dumps({"read_state": "measured"}) + "\n")
    _git(work, "add", TABLE)
    _git(work, "commit", "-qm", "table")
    _git(work, "push", "-q", "origin", "live-review/rows")
    tip = _git(work, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(origin), str(repo)], check=True, capture_output=True)
    monkeypatch.setattr(d, "_REPO_ROOT", str(repo))
    text, src = d._rows_branch_text(TABLE)
    assert json.loads(text) == {"read_state": "measured"} and src == f"live-review/rows@{tip}"
    assert d._rows_branch_text("comms/live_review/tables/LR-missing.json")[0] is None
    assert d._rows_branch_text("../etc/passwd") == (None, "unsafe_path")
