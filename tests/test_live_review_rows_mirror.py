"""LTR-APPLY-AUTOFLOW (iv): the rows mirror live-review/rows -> main, by review_id."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lrm", ROOT / "scripts/ops/live_review_rows_mirror.py")
lrm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lrm)


def row(rid, packet=True, table=True):
    r = {"review_id": rid, "reviewed_at": "2026-10-26T12:00:00Z"}
    if packet:
        r["packet_sha"] = "a" * 64
    if table:
        r["outcome_table_source"] = f"comms/live_review/tables/{rid}.json"
    return json.dumps(r, separators=(",", ":"))


def branch(rows, files):
    store = {lrm.REVIEWS: ("\n".join(rows) + "\n").encode(), **{k: v.encode() for k, v in files.items()}}
    return store.get


def cited_files(rid):
    return {f"{lrm.PACKETS}/{rid}.json": '{"p":1}', f"comms/live_review/tables/{rid}.json": '{"t":1}'}


def test_copies_only_new_rows_and_their_files_and_rerun_is_a_noop(tmp_path):
    (tmp_path / lrm.REVIEWS).parent.mkdir(parents=True)
    main_line = row("LR-A", packet=False, table=False)
    (tmp_path / lrm.REVIEWS).write_text(main_line + "\n")
    read = branch([main_line, row("LR-B"), row("LR-C", table=False)],
                  {**cited_files("LR-B"), f"{lrm.PACKETS}/LR-C.json": '{"p":2}'})
    res = lrm.mirror(tmp_path, read)
    assert res["mirrored"] == 2 and res["review_ids"] == ["LR-B", "LR-C"] and not res["skipped"]
    lines = (tmp_path / lrm.REVIEWS).read_text().splitlines()
    assert lines[0] == main_line and [json.loads(x)["review_id"] for x in lines] == ["LR-A", "LR-B", "LR-C"]
    assert (tmp_path / lrm.PACKETS / "LR-B.json").read_text() == '{"p":1}'
    assert (tmp_path / "comms/live_review/tables/LR-B.json").exists()
    before = (tmp_path / lrm.REVIEWS).read_bytes()
    again = lrm.mirror(tmp_path, read)
    assert again["mirrored"] == 0 and (tmp_path / lrm.REVIEWS).read_bytes() == before


def test_main_rows_landed_by_pr_are_not_duplicated_whatever_the_order(tmp_path):
    (tmp_path / lrm.REVIEWS).parent.mkdir(parents=True)
    (tmp_path / lrm.REVIEWS).write_text(row("LR-B", packet=False, table=False) + "\n")
    res = lrm.mirror(tmp_path, branch([row("LR-A", False, False), row("LR-B", False, False)], {}))
    ids = [json.loads(x)["review_id"] for x in (tmp_path / lrm.REVIEWS).read_text().splitlines()]
    assert res["mirrored"] == 1 and ids == ["LR-B", "LR-A"]


def test_a_differing_cited_file_is_never_overwritten(tmp_path):
    (tmp_path / lrm.PACKETS).mkdir(parents=True)
    (tmp_path / lrm.PACKETS / "LR-B.json").write_text('{"other":1}')
    res = lrm.mirror(tmp_path, branch([row("LR-B"), row("LR-D", False, False)], cited_files("LR-B")))
    assert res["review_ids"] == ["LR-D"] and res["skipped"][0]["review_id"] == "LR-B"
    assert (tmp_path / lrm.PACKETS / "LR-B.json").read_text() == '{"other":1}'


def test_a_missing_cited_file_skips_the_row(tmp_path):
    res = lrm.mirror(tmp_path, branch([row("LR-B")], {}))
    assert res["mirrored"] == 0 and "missing" in res["skipped"][0]["why"]


def test_unreadable_rows_branch_is_could_not_look(tmp_path):
    assert lrm.mirror(tmp_path, lambda p: None)["state"] == "could_not_look"


def test_cited_paths_stay_inside_live_review():
    assert lrm.cited(json.dumps({"review_id": "x", "outcome_table_source": "../etc/passwd"})) == []
    assert lrm.cited(json.dumps({"review_id": "x", "outcome_table_source": "config/mandates.yaml"})) == []


def test_workflow_triggers_on_the_rows_branch_and_lands_one_pr():
    wf = yaml.safe_load((ROOT / ".github/workflows/live-review-rows-mirror.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert on["push"]["branches"] == ["live-review/rows"]
    assert wf["concurrency"]["cancel-in-progress"] is False
    steps = wf["jobs"]["mirror"]["steps"]
    land = [s for s in steps if s.get("uses") == "./.github/actions/commit-to-main"]
    assert len(land) == 1 and land[0]["with"]["verify-merged"] == "true"
