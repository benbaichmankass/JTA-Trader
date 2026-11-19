"""manager-scope-guard: a work-store EXPORT commit is not a dispatch act.

The case, 2026-11-19: lane AM-OPS-7 (session_01AFoLuHfPPZwEceiXaCGZfL) ran
`scripts/ops/work.py export --to-files` as a dry run on its own branch
(496dfe54de). The export re-emitted rows whose `lane` names other sessions; the
dispatch reader in scripts/ci/check_manager_scope.py read that as AM-OPS-7
handing work out, admitted it to the manager roster, and R2 failed its PRs
#27299, #27308 and #27313 on ops tooling and tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))

import check_manager_scope as g  # noqa: E402

LANE = "session_01AFoLuHfPPZwEceiXaCGZfL"   # the real lane id from the case
OTHER_A = "session_01SELFTESTWORKER20000"
OTHER_B = "session_01SELFTESTMANAGER2000"


def _rows(root: Path, rows, frozen: bool) -> None:
    head = {"schema_version": 2, "items": None}
    if frozen:
        head[g.FROZEN_KEY] = {"at": "2026-11-07T00:00:00Z"}
    g._write(root, g.STORE_HEADER_REL, json.dumps(head, indent=2) + "\n")
    for rid, lane in rows:
        g._write(root, f"{g.STORE_REL}/{rid}.json", json.dumps(
            {"id": rid, "title": "t", "state": "in_flight", "owner": "manager",
             "lane": lane}, indent=2) + "\n")


@pytest.fixture()
def export_repo(tmp_path):
    root = g._fixture(tmp_path)
    g._archive_lease(root)
    _rows(root, [("X0", None)], frozen=True)
    g._commit(root, "WSD-S4: freeze register files", OTHER_B,
              when="2026-09-03T08:00:00+00:00")
    g._branch(root, "am-ops-7/intraday-refresh")
    _rows(root, [("X0", None), ("X1", OTHER_A), ("X2", OTHER_B)], frozen=True)
    g._commit(root, "DRY RUN (not for merge): work-store export --to-files", LANE)
    g._write(root, "scripts/ops/refresh_candle_history.py", "y = 1\n")
    g._write(root, "tests/test_candle_refresh_never_shrinks.py", "z = 1\n")
    g._write(root, "deploy/trainer/ict-candle-refresh.service", "[Unit]\n")
    g._commit(root, "trainer: extend the frozen files in place", LANE)
    return root


def test_frozen_key_matches_work_read():
    from src.runtime import work_read
    assert g.FROZEN_KEY == work_read.FROZEN_KEY
    assert g.STORE_HEADER_REL == f"{work_read.CHECKLIST_STORE.as_posix()}/{work_read.HEADER}"


def test_lane_running_an_export_is_not_a_manager(export_repo):
    holders, _w, sources, notes = g.manager_roster(export_repo)
    assert LANE not in holders
    assert ("dispatch", g.CHECKLIST_REL, g.SRC_EXPORT_ONLY, 0) in sources
    assert any("NOT dispatch evidence" in n and LANE in n for n in notes)

    st, fails, notes = g.check(export_repo, "main", branch="am-ops-7/intraday-refresh")
    assert fails == []
    assert st == "no_manager_commits"
    assert g.exit_code(st, fails) == 0
    assert any("CANNOT SEE A MANAGER WHO STARTED AFTER" in n for n in notes)


def test_the_plant_bites_the_old_reader(export_repo, monkeypatch):
    """Without the export rule the same fixture reproduces the CI failure."""
    monkeypatch.setattr(g, "is_export_commit", lambda *a, **k: False)
    holders, *_ = g.manager_roster(export_repo)
    assert LANE in holders
    st, fails, _ = g.check(export_repo, "main", branch="am-ops-7/intraday-refresh")
    assert st == "violation"
    joined = "\n".join(fails)
    assert "ops tooling" in joined and "test authoring" in joined


def test_pre_freeze_row_dispatch_still_admits(tmp_path):
    root = g._fixture(tmp_path)
    g._archive_lease(root)
    _rows(root, [("X0", None)], frozen=False)
    g._commit(root, "cutover", OTHER_A)
    _rows(root, [("X0", None), ("X1", OTHER_A)], frozen=False)
    g._commit(root, "manager: dispatch X1", OTHER_B)
    holders, _w, sources, _n = g.manager_roster(root)
    assert OTHER_B in holders
    assert ("dispatch", g.CHECKLIST_REL, g.SRC_LIVE, 1) in sources


def test_unparseable_header_is_not_an_excuse(tmp_path):
    root = g._fixture(tmp_path)
    g._archive_lease(root)
    g._write(root, g.STORE_HEADER_REL, "{not json\n")
    g._write(root, f"{g.STORE_REL}/X1.json",
             json.dumps({"id": "X1", "lane": OTHER_A}, indent=2) + "\n")
    g._commit(root, "manager: dispatch X1", OTHER_B)
    holders, _w, _s, notes = g.manager_roster(root)
    assert OTHER_B in holders
    assert any("could not be parsed" in n for n in notes)
