"""LTR-APPLY-AUTOFLOW (iv): the rows mirror live-review/rows -> main, by review_id."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lrm", ROOT / "scripts/ops/live_review_rows_mirror.py")
lrm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lrm)
rules = lrm.rules


def sha(content):
    return hashlib.sha256(json.dumps(json.loads(content), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def row(rid, packet=True, table=True, packet_content='{"p":1}', **over):
    """A schema-valid review (the checker's own GOOD_REVIEW) whose id names its package: ...-pkg-B -> pkg-B."""
    r = copy.deepcopy(rules.GOOD_REVIEW)
    r.update(review_id=rid, order_package_id="pkg-" + rid.split("-pkg-")[-1], reviewed_at="2026-10-26T12:00:00Z")
    r["packet_sha"] = sha(packet_content) if packet else None
    r["outcome_table_source"] = None
    r.update(over)
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
    main_line = row("LR-20261026T1200Z-pkg-A", packet=False, table=False)
    (tmp_path / lrm.REVIEWS).write_text(main_line + "\n")
    read = branch([main_line, row("LR-20261026T1200Z-pkg-B"), row("LR-20261026T1200Z-pkg-C", table=False, packet_content='{"p":2}')],
                  {**cited_files("LR-20261026T1200Z-pkg-B"), f"{lrm.PACKETS}/LR-20261026T1200Z-pkg-C.json": '{"p":2}'})
    res = lrm.mirror(tmp_path, read)
    assert res["mirrored"] == 2 and res["review_ids"] == ["LR-20261026T1200Z-pkg-B", "LR-20261026T1200Z-pkg-C"] and not res["skipped"]
    lines = (tmp_path / lrm.REVIEWS).read_text().splitlines()
    assert lines[0] == main_line and [json.loads(x)["review_id"] for x in lines] == ["LR-20261026T1200Z-pkg-A", "LR-20261026T1200Z-pkg-B", "LR-20261026T1200Z-pkg-C"]
    assert (tmp_path / lrm.PACKETS / "LR-20261026T1200Z-pkg-B.json").read_text() == '{"p":1}'
    assert (tmp_path / "comms/live_review/tables/LR-20261026T1200Z-pkg-B.json").exists()
    before = (tmp_path / lrm.REVIEWS).read_bytes()
    again = lrm.mirror(tmp_path, read)
    assert again["mirrored"] == 0 and (tmp_path / lrm.REVIEWS).read_bytes() == before


def test_main_rows_landed_by_pr_are_not_duplicated_whatever_the_order(tmp_path):
    (tmp_path / lrm.REVIEWS).parent.mkdir(parents=True)
    (tmp_path / lrm.REVIEWS).write_text(row("LR-20261026T1200Z-pkg-B", packet=False, table=False) + "\n")
    res = lrm.mirror(tmp_path, branch([row("LR-20261026T1200Z-pkg-A", False, False), row("LR-20261026T1200Z-pkg-B", False, False)], {}))
    ids = [json.loads(x)["review_id"] for x in (tmp_path / lrm.REVIEWS).read_text().splitlines()]
    assert res["mirrored"] == 1 and ids == ["LR-20261026T1200Z-pkg-B", "LR-20261026T1200Z-pkg-A"]


def test_a_differing_cited_file_is_never_overwritten(tmp_path):
    (tmp_path / lrm.PACKETS).mkdir(parents=True)
    (tmp_path / lrm.PACKETS / "LR-20261026T1200Z-pkg-B.json").write_text('{"other":1}')
    res = lrm.mirror(tmp_path, branch([row("LR-20261026T1200Z-pkg-B"), row("LR-20261026T1200Z-pkg-D", False, False)], cited_files("LR-20261026T1200Z-pkg-B")))
    assert res["review_ids"] == ["LR-20261026T1200Z-pkg-D"] and res["skipped"][0]["review_id"] == "LR-20261026T1200Z-pkg-B"
    assert (tmp_path / lrm.PACKETS / "LR-20261026T1200Z-pkg-B.json").read_text() == '{"other":1}'


def test_a_missing_cited_file_skips_the_row(tmp_path):
    res = lrm.mirror(tmp_path, branch([row("LR-20261026T1200Z-pkg-B")], {}))
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


def test_a_schema_invalid_row_is_skipped_visibly_and_later_rows_still_mirror(tmp_path):
    # LR-20261026T2311Z-pkg-6a8e...: id names one package, body is another's
    bad = row("LR-20261026T2311Z-pkg-6a8e", False, False, order_package_id="pkg-465a")
    res = lrm.mirror(tmp_path, branch([bad, row("LR-20261026T1200Z-pkg-D", False, False)], {}))
    assert res["review_ids"] == ["LR-20261026T1200Z-pkg-D"]
    assert res["skipped"][0]["review_id"] == "LR-20261026T2311Z-pkg-6a8e" and res["skipped"][0]["why"].startswith("schema: ")
    assert "order_package_id" in res["skipped"][0]["why"]


def test_a_money_row_the_checker_refuses_is_skipped(tmp_path):
    bad = row("LR-20261026T1200Z-pkg-E", False, False, recommendation={**rules.GOOD_REVIEW["recommendation"], "action": "no_recommendation",
                                                    "basis": "insufficient_n", "evidence_source": "none"},
              applied=False, reviewed_at="2026-10-26T13:00:00Z", apply_policy={"bound_r": 0.25, "within_bound": None, "tighten_r": None},
              shadow_policy={"bound_r": 0.5, "within_bound": None, "would_apply": None, "tighten_r": None})
    res = lrm.mirror(tmp_path, branch([bad], {}))
    assert res["mirrored"] == 0 and "insufficient_n is refused" in res["skipped"][0]["why"]


def test_a_packet_sha_that_does_not_match_its_packet_is_skipped(tmp_path):
    res = lrm.mirror(tmp_path, branch([row("LR-20261026T1200Z-pkg-F", True, False)], {f"{lrm.PACKETS}/LR-20261026T1200Z-pkg-F.json": '{"p":9}'}))
    assert res["mirrored"] == 0 and res["skipped"][0]["why"].startswith("schema: packet_sha")


def test_schema_skips_do_not_fail_the_run_but_other_skips_do(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lrm, "ROOT", tmp_path)
    bad = row("LR-20261026T2311Z-pkg-6a8e", False, False, order_package_id="pkg-465a")
    monkeypatch.setattr(lrm, "git_show", lambda ref, path, cwd=None: branch([bad], {})(path))
    assert lrm.main([]) == 0
    monkeypatch.setattr(lrm, "git_show", lambda ref, path, cwd=None: branch([row("LR-20261026T1200Z-pkg-B")], {})(path))
    assert lrm.main([]) == 1


def test_heartbeat_dispatches_both_mirrors_from_main_on_a_main_push():
    wf = yaml.safe_load((ROOT / ".github/workflows/branch-mirror-heartbeat.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert on["push"]["branches"] == ["main"] and "schedule" not in on
    assert wf["permissions"]["actions"] == "write"
    text = (ROOT / ".github/workflows/branch-mirror-heartbeat.yml").read_text()
    assert "desk-decisions-mirror.yml" in text and "live-review-rows-mirror.yml" in text
    assert 'gh workflow run "$wf"' in text and "--ref main" in text
