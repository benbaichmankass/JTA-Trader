"""AM-OPS-9: the work-store export runs the guards' own row checks before writing, holds a failing
row back (filed once), lets pre-cutover debt land, and the three guards skip that debt.

Gates this adds or changes: none added; narrows roadmap-map, soak-contract and claim-basis to skip rows
whose store updated_at <= export_base_at (pre-cutover debt, tracked on STORE-EXPORT-BACKFILL-258).

No network: the store API is mocked at ``work.http``.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts import check_claim_basis as cb
from scripts.ci import check_soak_contracts as sc
from scripts.ops import roadmap_map as rm
from scripts.ops import work as work_cli
from scripts.ops import work_export_cutover as cut

PAST, FUTURE = "2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"
NOW = "2026-11-20T10:00:00Z"
CHECKLIST = "docs/claude/work/checklist"
PIPE = "docs/claude/work/pipeline"


def _root(tmp_path: Path, base_at: str) -> Path:
    root = tmp_path / "repo"
    (root / CHECKLIST).mkdir(parents=True)
    (root / CHECKLIST / "_header.json").write_text(json.dumps({"items": None, cut.KEY: base_at}))
    return root


def _row(rid: str, note: str, state: str = "queued", updated_at: str = NOW) -> dict:
    return {"id": rid, "kind": "build", "title": f"row {rid}", "state": state, "owner": "manager",
            "roadmap": ["L-OPS"], "updated_at": updated_at, "extra": {"note": note}}


def _obs(oid: str, updated_at: str = NOW, observation: dict | None = None) -> dict:
    extra = {"observation": observation} if observation else None
    return {"id": oid, "kind": "observation", "title": f"check {oid}", "state": "queued", "owner": "manager",
            "next_action": "check_observation", "due_rule": {"kind": "date", "due_date": "2026-12-01"},
            "origin": {"kind": "audit", "ref": "r", "rerun": "x"}, "updated_at": updated_at, "extra": extra}


BAD_CLAIM = "the bad cells are 42.9% of the fleet"           # claim-basis: a number with no basis
GOOD_CLAIM = "the bad cells are 42.9% of the fleet (12 of 28 legs)"


def _rows_on_disk(root: Path) -> set[str]:
    return {p.stem for p in (root / CHECKLIST).glob("*.json") if not p.name.startswith("_")}


def _records_on_disk(root: Path) -> set[str]:
    d = root / PIPE
    return {json.loads(p.read_text())["id"] for p in d.glob("*.json")} if d.exists() else set()


# ── (a) a failing changed row is held back; a passing one is written ─────────────────────


def test_failing_row_and_record_held_back_passing_written(tmp_path):
    root = _root(tmp_path, PAST)
    items = [_row("R-GOOD", GOOD_CLAIM), _row("R-BAD", BAD_CLAIM),
             _obs("PI-BAD"),  # check_observation with no definition of done -> soak-contract
             _obs("PI-GOOD", observation={"what": "w", "how_to_check": "h", "due_by": "2026-12-01"})]
    out = work_cli.export_to_files(root, items)
    assert _rows_on_disk(root) == {"R-GOOD"}
    assert _records_on_disk(root) == {"PI-GOOD"}
    assert (out["rows_written"], out["rows_held"], out["records_written"], out["records_held"]) == (1, 1, 1, 1)
    held = {h["id"]: h for h in out["held"]}
    assert set(held) == {"R-BAD", "PI-BAD"}
    assert "NO parseable basis" in held["R-BAD"]["messages"][0]                # the guard's own message
    assert "definition of done" in held["PI-BAD"]["messages"][0]
    # the stamps side file names exactly the files written, with the store updated_at
    stamps = cut.load_stamps(root)
    assert set(stamps) == {f"{CHECKLIST}/R-GOOD.json"} | {k for k in stamps if k.startswith(PIPE)}
    assert len(stamps) == 2 and all(s["updated_at"] == NOW for s in stamps.values())


def test_held_row_is_retried_and_lands_once_fixed(tmp_path):
    root = _root(tmp_path, PAST)
    work_cli.export_to_files(root, [_row("R-BAD", BAD_CLAIM)])
    assert _rows_on_disk(root) == set()
    out = work_cli.export_to_files(root, [_row("R-BAD", GOOD_CLAIM)])          # fixed in the store
    assert _rows_on_disk(root) == {"R-BAD"} and out["rows_held"] == 0


def test_a_changed_existing_row_is_checked_against_its_file(tmp_path):
    """soak-contract: a row ENTERING landed_unproven without a contract/observation is held; the file
    keeps its previous content."""
    root = _root(tmp_path, PAST)
    work_cli.export_to_files(root, [_row("R-1", "plain")])
    before = (root / CHECKLIST / "R-1.json").read_text()
    out = work_cli.export_to_files(root, [_row("R-1", "plain", state="landed_unproven")])
    assert out["rows_held"] == 1 and "landed_unproven" in out["held"][0]["messages"][0]
    assert (root / CHECKLIST / "R-1.json").read_text() == before


def test_no_precheck_is_the_byte_exact_rollback(tmp_path):
    root = _root(tmp_path, PAST)
    out = work_cli.export_to_files(root, [_row("R-BAD", BAD_CLAIM)], precheck=False)
    assert _rows_on_disk(root) == {"R-BAD"} and out["held"] == []


# ── (b) a pre-cutover failing row is written ──────────────────────────────────────────────


def test_pre_cutover_failing_row_and_record_land(tmp_path):
    root = _root(tmp_path, "2026-11-19T22:30:00Z")
    items = [_row("R-OLD", BAD_CLAIM, updated_at="2026-11-19T22:30:00Z"),   # == cutover: exempt
             _obs("PI-OLD", updated_at="2026-11-15T00:00:00Z"),
             _row("R-NEW", BAD_CLAIM, updated_at="2026-11-19T22:30:01Z")]   # after: held
    out = work_cli.export_to_files(root, items)
    assert _rows_on_disk(root) == {"R-OLD"} and _records_on_disk(root) == {"PI-OLD"}
    assert out["exempt_failing_landed"] == 2 and [h["id"] for h in out["held"]] == ["R-NEW"]


# ── (c) one filing per held row; none while an open one exists ────────────────────────────


@pytest.fixture()
def api(monkeypatch):
    calls = []

    def fake_http(method, path, body=None, **kw):
        calls.append((method, path, body))
        return 201, {"item": dict(body or {}, version=1), "event": {"seq": len(calls)}}, {}
    monkeypatch.setattr(work_cli, "http", fake_http)
    return calls


def test_held_row_files_exactly_once(tmp_path, api):
    root = _root(tmp_path, PAST)
    items = [_row("R-BAD", BAD_CLAIM)]
    out = work_cli.export_to_files(root, items)
    f1 = work_cli.file_holds(out["held"], items, today=date(2026, 11, 20))
    assert len(api) == 1 and len(f1["filed"]) == 1
    method, path, body = api[0]
    assert (method, path) == ("POST", work_cli.API)
    assert body["kind"] == "observation" and body["title"].startswith(work_cli.hold_title("R-BAD"))
    assert "NO parseable basis" in body["title"] and "R-BAD" in body["title"]
    assert body["owner"] and body["roadmap"] == ["unmapped"] and body["roadmap_unmapped_reason"]
    assert body["due_rule"] == {"kind": "date", "due_date": "2026-11-22"}
    assert body["next_action"] == "check_observation"
    assert body["origin"]["kind"] == "audit" and body["origin"]["by"] == "work-export"
    assert body["origin"]["ref"] and body["origin"]["rerun"]
    # second run: the store now holds the open filing -> nothing filed
    filed_item = {**body, "state": "queued", "updated_at": NOW}
    out2 = work_cli.export_to_files(root, items + [filed_item])
    assert [h["id"] for h in out2["held"]] == ["R-BAD"]
    f2 = work_cli.file_holds(out2["held"], items + [filed_item], today=date(2026, 11, 21))
    assert len(api) == 1 and f2["filed"] == [] and f2["skipped_open"] == ["R-BAD"]
    # and the filing itself passes every guard row check, so it lands in that export
    assert out2["records_written"] == 1 and _records_on_disk(root) == {filed_item["id"]}


def test_a_closed_filing_does_not_suppress_a_new_one(tmp_path, api):
    held = [{"id": "R-BAD", "kind": "build", "messages": ["m"]}]
    closed = {"id": "X", "kind": "observation", "state": "done", "title": work_cli.hold_title("R-BAD") + " old"}
    assert len(work_cli.file_holds(held, [closed])["filed"]) == 1


def test_a_failed_filing_is_printed_never_raised(tmp_path, monkeypatch, capsys):
    def down(*a, **k):
        raise work_cli.Unreachable("store not reached: test")
    monkeypatch.setattr(work_cli, "http", down)
    res = work_cli.file_holds([{"id": "R-BAD", "kind": "build", "messages": ["m"]}], [])
    assert res["filed"] == [] and res["errors"][0]["for"] == "R-BAD"
    assert "FAILED" in capsys.readouterr().err


def test_cli_export_summary(tmp_path, api, monkeypatch, capsys):
    root = _root(tmp_path, PAST)
    monkeypatch.setattr(work_cli, "_all_items", lambda db: [_row("R-BAD", BAD_CLAIM), _row("R-OK", "plain")])
    monkeypatch.setattr(work_cli, "_header_meta", lambda db: {})
    assert work_cli.main(["export", "--to-files", "--root", str(root), "--run-ref", "run-1"]) == 0
    io = capsys.readouterr()
    assert "rows: 1 written, 0 unchanged, 1 held back" in io.err and "items filed: 1" in io.err
    assert json.loads(io.out)["filing"]["filed"][0]["for"] == "R-BAD"


# ── (d) each guard skips pre-cutover exported files, and still fails a post-cutover one ───


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _stamp(root: Path, rel: str, updated_at: str) -> None:
    sp = root / cut.STAMPS_REL
    d = json.loads(sp.read_text()) if sp.exists() else {"files": {}}
    d["files"][rel] = {"updated_at": updated_at, "sha256": cut.sha((root / rel).read_bytes())}
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(d))


@pytest.fixture()
def gitrepo(tmp_path):
    """A repo whose base commit holds one row; the head adds/changes rows and records."""
    root = _root(tmp_path, "2026-11-19T22:30:00Z")
    (root / CHECKLIST / "OLD.json").write_text(json.dumps({"id": "OLD", "title": "t", "state": "queued", "_seq": 500}))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_exempt_paths_needs_a_pre_cutover_stamp_and_unchanged_bytes(gitrepo):
    root = gitrepo
    rel = f"{CHECKLIST}/OLD.json"
    _stamp(root, rel, "2026-11-19T00:00:00Z")
    assert cut.exempt_paths(root) == {rel}
    (root / rel).write_text((root / rel).read_text() + " ")                     # a hand edit
    assert cut.exempt_paths(root) == set()
    _stamp(root, rel, "2026-11-20T00:00:00Z")                                  # post-cutover stamp
    assert cut.exempt_paths(root) == set()
    _stamp(root, rel, "2026-11-19T00:00:00Z")
    hdr = root / CHECKLIST / "_header.json"
    hdr.write_text(json.dumps({"items": None}))                                # no cutover key
    assert cut.exempt_paths(root) == set()


def test_roadmap_guard_skips_pre_cutover_row(gitrepo, monkeypatch):
    root = gitrepo
    monkeypatch.setattr(rm, "REPO", root)
    for rid, ts in (("OLD", "2026-11-19T00:00:00Z"), ("NEW", "2026-11-20T00:00:00Z")):
        rel = f"{CHECKLIST}/{rid}.json"
        (root / rel).write_text(json.dumps({"id": rid, "title": "t", "state": "done", "_seq": 500}))
        _stamp(root, rel, ts)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "export")
    spec = {"enforce_from_seq": 400}
    plain = rm.diff_problems(spec, *rm._diff_inputs("HEAD~1"))
    assert any("row OLD" in b for b in plain) and any("row NEW" in b for b in plain)   # no exemption
    got = rm.diff_problems(spec, *rm._diff_inputs("HEAD~1", cut.exempt_paths(root)))
    assert not any("row OLD" in b for b in got)                                         # pre-cutover: skipped
    assert any("row NEW" in b and "roadmap" in b for b in got)                          # post-cutover: still fails


def test_soak_guard_skips_pre_cutover_row_and_record(gitrepo, monkeypatch):
    root = gitrepo
    monkeypatch.setattr(sc, "REPO", root)
    (root / PIPE).mkdir(parents=True)
    for rid, ts in (("OLD", "2026-11-19T00:00:00Z"), ("NEW", "2026-11-20T00:00:00Z")):
        rel = f"{CHECKLIST}/{rid}.json"
        (root / rel).write_text(json.dumps({"id": rid, "title": "t", "state": "landed_unproven", "_seq": 500}))
        _stamp(root, rel, ts)
        prel = f"{PIPE}/2026-{rid}.json"
        (root / prel).write_text(json.dumps({"id": f"PI-{rid}", "next_action": "check_observation",
                                             "state": "queued"}))
        _stamp(root, prel, ts)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "export")
    plain = sc.diff_findings("HEAD~1", [])
    assert sum("OLD" in f for f in plain) == 2 and sum("NEW" in f for f in plain) == 2
    got = sc.diff_findings("HEAD~1", [], exempt=frozenset(cut.exempt_paths(root)))
    assert not any("OLD" in f for f in got)
    assert any("checklist row NEW" in f for f in got) and any("PI-NEW" in f for f in got)


def test_claim_basis_guard_skips_pre_cutover_row_and_record(gitrepo, monkeypatch):
    root = gitrepo
    (root / PIPE).mkdir(parents=True)
    for rid, ts in (("OLD", "2026-11-19T00:00:00Z"), ("NEW", "2026-11-20T00:00:00Z")):
        prel = f"{PIPE}/2026-{rid}.json"
        (root / prel).write_text(json.dumps({"id": f"PI-{rid}", "what": "slippage is 3.4% of gross"}))
        _stamp(root, prel, ts)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "export")
    monkeypatch.chdir(root)
    ex = frozenset(cut.exempt_paths(Path(".")))
    plain = cb.check_new_pipeline_rows("HEAD~1", PIPE)
    assert any("PI-OLD" in f for f in plain) and any("PI-NEW" in f for f in plain)
    got = cb.check_new_pipeline_rows("HEAD~1", PIPE, exempt=ex)
    assert not any("PI-OLD" in f for f in got) and any("PI-NEW" in f for f in got)
    # the checklist half: an exempt NEW row is skipped, a non-exempt one still fails
    head = json.dumps({"items": [{"id": "A", "title": BAD_CLAIM}, {"id": "B", "title": BAD_CLAIM}]})
    f = cb.check_new_rows("{}", head, cb.BACKLOGS[0], exempt_ids=frozenset({"A"}))
    assert len(f) == 1 and "'B'" in f[0]


# ── (e) the per-row predicates ARE the guards' diff logic ─────────────────────────────────


def test_predicates_match_the_guard_messages():
    spec = {"enforce_from_seq": 10}
    assert rm.row_problems(spec, "N1", {"id": "N1", "state": "queued"}, None, 20) == \
        rm.diff_problems(spec, {"N1": {"id": "N1", "state": "queued"}}, {}, {}, {}, {"N1": 20})
    assert rm.row_problems(spec, "N1", {"id": "N1", "state": "queued"}, None, 5) == []
    row = {"id": "Y", "state": "landed_unproven"}
    assert sc.row_findings(row, "queued", set()) and sc.row_findings(row, "landed_unproven", set()) == []
    assert sc.row_findings(row, None, {"Y"}) == []
    called = []
    item = {"id": "P", "next_action": "dispatch_lane"}
    assert sc.pipeline_item_findings(item, "n", set(), lambda: called.append(1)) == [] and called == []
    assert cb.new_row_failure("Z", {"title": BAD_CLAIM}, "p") == \
        cb.check_new_rows("{}", json.dumps({"items": [{"id": "Z", "title": BAD_CLAIM}]}), "p")[0]
    assert cb.new_row_failure("Z", {"title": GOOD_CLAIM}, "p") is None
