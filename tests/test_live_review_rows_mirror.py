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
    assert res["mirrored"] == 0 and res["skipped"][0]["why"].startswith("packet_sha: packet_sha does not match")


def test_schema_skips_do_not_fail_the_run_but_other_skips_do(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lrm, "ROOT", tmp_path)
    monkeypatch.setattr(lrm, "git_row_files", lambda ref, cwd=None: [])
    monkeypatch.setattr(lrm, "git_history", lambda ref, *a, **k: [])
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


# ---- LTR-ROWS-SWAP-TRUNCATION: per-row files, and a shrunken legacy file is refused -------------

def _files_branch(legacy_rows, row_files, cited):
    """The rows branch with a legacy reviews.jsonl AND per-row files comms/live_review/rows/<id>.json."""
    store = {lrm.REVIEWS: ("\n".join(legacy_rows) + "\n").encode()}
    for line in row_files:
        store[f"comms/live_review/rows/{json.loads(line)['review_id']}.json"] = json.dumps(json.loads(line), indent=1).encode()
    store.update({k: v.encode() for k, v in cited.items()})
    return store.get, sorted(p for p in store if p.startswith("comms/live_review/rows/"))


def test_a_per_row_file_mirrors_as_one_line_and_legacy_rows_still_mirror(tmp_path):
    a, b = row("LR-20261027T1600Z-pkg-A"), row("LR-20261027T1601Z-pkg-B")
    read, files = _files_branch([a], [b], {**cited_files("LR-20261027T1600Z-pkg-A"), **cited_files("LR-20261027T1601Z-pkg-B")})
    res = lrm.mirror(tmp_path, read, files, history=[])
    assert res["mirrored"] == 2 and not res["skipped"]
    lines = (tmp_path / lrm.REVIEWS).read_text().splitlines()
    assert [json.loads(x)["review_id"] for x in lines] == ["LR-20261027T1600Z-pkg-A", "LR-20261027T1601Z-pkg-B"]
    assert json.loads(lines[1]) == json.loads(b) and "\n" not in lines[1]
    assert lrm.mirror(tmp_path, read, files, history=[])["mirrored"] == 0


def test_a_shrunken_legacy_file_is_refused_and_per_row_files_still_mirror(tmp_path):
    full = [row(f"LR-20261027T15{i:02d}Z-pkg-{i}", packet=False, table=False) for i in range(26)]
    cut = full[:4] + [full[4][:40]]
    new = row("LR-20261027T1622Z-pkg-N", packet=False, table=False)
    read, files = _files_branch(cut, [new], {})
    res = lrm.mirror(tmp_path, read, files, history=[("\n".join(full) + "\n").encode()])
    assert res["review_ids"] == ["LR-20261027T1622Z-pkg-N"]
    hard = [x for x in res["skipped"] if x["why"].startswith("shrunk:")]
    assert len(hard) == 1 and "22 review_id(s)" in hard[0]["why"]


def test_unreadable_history_refuses_the_legacy_file(tmp_path):
    read, files = _files_branch([row("LR-20261027T1600Z-pkg-A", packet=False, table=False)], [], {})
    res = lrm.mirror(tmp_path, read, files, history_unreadable=True)
    assert res["mirrored"] == 0 and res["skipped"][0]["why"].startswith("shrunk: could not read")


def test_a_shrunken_tip_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lrm, "ROOT", tmp_path)
    full = [row(f"LR-20261027T15{i:02d}Z-pkg-{i}", packet=False, table=False) for i in range(3)]
    monkeypatch.setattr(lrm, "git_show", lambda ref, path, cwd=None: branch(full[:1], {})(path))
    monkeypatch.setattr(lrm, "git_row_files", lambda ref, cwd=None: [])
    monkeypatch.setattr(lrm, "git_history", lambda ref, *a, **k: [("\n".join(full) + "\n").encode()])
    assert lrm.main([]) == 1


# ── LTR-PACKET-ECHO: a packet_sha refusal is loud (one flag), a missing packet waits, killed rows are named ──
def test_a_packet_sha_mismatch_alerts_once_and_does_not_fail_every_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lrm, "ROOT", tmp_path)
    monkeypatch.setattr(lrm, "git_row_files", lambda ref, cwd=None: [])
    monkeypatch.setattr(lrm, "git_history", lambda ref, *a, **k: [])
    rid = "LR-20261027T1831Z-pkg-976b"
    read = branch([row(rid, True, False)], {f"{lrm.PACKETS}/{rid}.json": '{"p":9}'})  # re-typed: a key dropped
    monkeypatch.setattr(lrm, "git_show", lambda ref, path, cwd=None: read(path))
    gh_calls, posted = [], []

    def fake_gh(args):
        gh_calls.append(args)
        if args[0] == "api":
            return "".join(posted)
        posted.append(args[args.index("--body") + 1])
        return ""
    monkeypatch.setattr(lrm, "_gh", fake_gh)
    assert lrm.main(["--flag-pr", "17895"]) == 0           # refused, kept running, not red every hour
    err = capsys.readouterr().err
    assert f"::error::rows-branch row {rid} REFUSED" in err and "flag: flagged" in err
    assert len(posted) == 1 and rid in posted[0] and "<!-- ltr-mirror-refused " in posted[0]
    assert lrm.main(["--flag-pr", "17895"]) == 0
    assert "flag: already_flagged" in capsys.readouterr().err and len(posted) == 1   # ONE flag per row


def test_a_row_with_no_committed_packet_waits_and_mirrors_once_the_packet_lands(tmp_path):
    rid = "LR-20261027T1900Z-pkg-G"
    r = row(rid, True, False)
    res = lrm.mirror(tmp_path, branch([r], {}))
    assert res["mirrored"] == 0 and res["skipped"][0]["why"].startswith("cited file ") and "missing" in res["skipped"][0]["why"]
    assert lrm.alert_keys(res["skipped"]) == [(f"{rid}|cited_file", f"`{rid}`: {res['skipped'][0]['why']}")]
    res = lrm.mirror(tmp_path, branch([r], {f"{lrm.PACKETS}/{rid}.json": '{"p":1}'}))
    assert res["mirrored"] == 1 and res["skipped"] == []


def test_plan_flag_skips_keys_already_flagged_and_ignores_schema_refusals():
    sk = [{"review_id": "A", "why": "packet_sha: x"}, {"review_id": "B", "why": "schema: y"},
          {"review_id": "C", "why": "cited file z missing on the rows branch"}]
    assert [k for k, _ in lrm.plan_flag(sk, [])] == ["A|packet_sha", "C|cited_file"]
    assert [k for k, _ in lrm.plan_flag(sk, [{"keys": ["A|packet_sha"]}])] == ["C|cited_file"]


def test_the_legacy_wrong_package_row_is_killed_with_its_reason_not_schema_refused(tmp_path):
    rid = "LR-20261026T2311Z-pkg-6a8e3fb325464be3"
    bad = row(rid, False, False, order_package_id="pkg-465a5d7d27644027")
    (tmp_path / lrm.KILLED).parent.mkdir(parents=True)
    (tmp_path / lrm.KILLED).write_text((ROOT / lrm.KILLED).read_text())
    res = lrm.mirror(tmp_path, branch([bad, row("LR-20261026T1200Z-pkg-D", False, False)], {}))
    assert res["review_ids"] == ["LR-20261026T1200Z-pkg-D"] and res["skipped"] == []
    assert res["killed"][0]["review_id"] == rid and "superseded_by LR-20261026T2312Z-pkg-6a8e3fb325464be3" in res["killed"][0]["why"]


def test_every_killed_row_states_a_reason_and_what_supersedes_it():
    doc = json.loads((ROOT / lrm.KILLED).read_text())
    assert doc["killed"]
    for k in doc["killed"]:
        assert k["review_id"].startswith("LR-") and len(k["reason"]) > 40 and k["superseded_by"].startswith("LR-")
