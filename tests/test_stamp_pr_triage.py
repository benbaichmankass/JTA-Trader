"""STAMP-PR-TRIAGE (PI-20261118-EFILLW47-0005): conflicted dispatch-stamp PRs are closed when moot, never landed when they would
drop a producer_failed unit, never touch another branch, and do nothing at all in a dry run."""
from datetime import datetime, timezone

from scripts.research import stamp_pr_triage as t

UNIT = "id: RQ-X\ncadence: {c}\nstatus: queued\n{stamp}\nrun: {{}}\n"


def _unit(cadence="once", stamp="last_dispatched_at: '2026-11-18T19:45:49+00:00'"):
    return UNIT.format(c=cadence, stamp=stamp)


def _file(uid, stamp):
    return {"filename": f"research/queue/{uid}.yaml", "patch": f"@@ -1 +1 @@\n+last_dispatched_at: '{stamp}'\n"}


def test_main_at_or_after_the_stamp_is_superseded():
    k, _ = t.classify_unit("2026-11-18T19:38:36+00:00", _unit("weekly"), None)
    assert k == t.SUPERSEDED


def test_a_cadence_once_unit_with_any_main_stamp_is_moot():
    k, _ = t.classify_unit("2026-11-18T20:06:09+00:00", _unit("once"), None)
    assert k == t.MOOT_ONCE


def test_a_recurring_unit_with_a_newer_stamp_must_be_landed():
    k, _ = t.classify_unit("2026-11-18T20:06:09+00:00", _unit("weekly"), None)
    assert k == t.NEEDS_LAND


def test_an_unstamped_producer_failed_unit_is_never_stamped():
    """THE EXCEPTION (abab-04 / abab-26, 2026-11-18): no stamp on main + producer_failed result = deliberately due for a re-run."""
    nostamp = "id: RQ-X\ncadence: once\nstatus: queued\nrun: {}\n"
    k, why = t.classify_unit("2026-11-18T19:45:56+00:00", nostamp, "producer_failed")
    assert k == t.KEEP_UNSTAMPED and "re-run" in why
    # the same stamp on an unstamped unit whose result was MEASURED matters: it is not the exception
    assert t.classify_unit("2026-11-18T19:45:56+00:00", nostamp, "measured")[0] == t.NEEDS_LAND
    # a null stamp with a re-arm comment counts as unstamped
    rearm = "id: RQ-X\ncadence: once\nlast_dispatched_at: null   # re-armed\n"
    assert t.classify_unit("2026-11-18T19:45:56+00:00", rearm, "producer_failed")[0] == t.KEEP_UNSTAMPED


def test_unreadable_inputs_are_could_not_look_never_close():
    assert t.classify_unit("garbage", _unit(), None)[0] == t.COULD_NOT_LOOK
    assert t.classify_unit("2026-11-18T19:45:56+00:00", None, None)[0] == t.COULD_NOT_LOOK


def _decide(files, mains, states=None):
    return t.decide_pr(files, lambda rel: mains.get(rel), lambda uid: (states or {}).get(uid))


def test_a_pr_whose_every_stamp_is_moot_closes_and_one_that_matters_lands():
    mains = {"research/queue/RQ-A.yaml": _unit("weekly", "last_dispatched_at: '2026-11-18T20:00:00+00:00'"),
             "research/queue/RQ-B.yaml": _unit("weekly", "last_dispatched_at: '2026-11-18T19:00:00+00:00'")}
    old = [_file("RQ-A", "2026-11-18T19:30:00+00:00")]
    assert _decide(old, mains)["action"] == "close"
    new = old + [_file("RQ-B", "2026-11-18T19:30:00+00:00")]
    d = _decide(new, mains)
    assert d["action"] == "land" and [u["kind"] for u in d["units"]] == [t.SUPERSEDED, t.NEEDS_LAND]


def test_a_pr_touching_a_non_stamp_path_is_left_alone():
    mains = {"research/queue/RQ-A.yaml": _unit()}
    files = [_file("RQ-A", "2026-11-18T19:30:00+00:00"), {"filename": "src/x.py", "patch": ""}]
    assert _decide(files, mains)["action"] == "leave"
    # the stamp branch's own landing/slot files are expected, not stray
    ok = [_file("RQ-A", "2026-11-18T19:30:00+00:00"), {"filename": ".github/merge-slots/a.json"},
          {"filename": ".github/pr-landing/a.json"}, {"filename": ".github/pr-automerge-requests/a.txt"}]
    assert _decide(ok, mains)["action"] == "close"


def test_set_stamp_resolves_to_main_text_with_the_max_stamp():
    base = _unit("weekly", "last_dispatched_at: '2026-11-18T19:00:00+00:00'  # re-armed")
    out = t.set_stamp(base, "2026-11-18T20:00:00+00:00")
    assert t.stamp_value(out) == "2026-11-18T20:00:00+00:00" and out.count("last_dispatched_at") == 1
    assert t.stamp_value(t.set_stamp("id: X\ncadence: once\n", "2026-11-18T20:00:00+00:00")) == "2026-11-18T20:00:00+00:00"


def _prs(monkeypatch, prs, dirty=True, files=None):
    def api(path):
        if path.endswith("/files?per_page=100"):
            return files
        if "/pulls/" in path:
            return {"mergeable_state": "dirty" if dirty else "clean"}
        return prs
    monkeypatch.setattr(t, "_api", api)


def _pr(n, ref, created="2026-11-18T19:00:00Z"):
    return {"number": n, "head": {"ref": ref}, "created_at": created}


def test_only_stamp_branches_are_considered_and_a_dry_run_effects_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_gh", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _unit("weekly", "last_dispatched_at: '2026-11-18T21:00:00+00:00'")))
    prs = [_pr(1, "automation/research-queue-stamp-9-1"), _pr(2, "automation/receipt-1"), _pr(3, "claude/some-lane")]
    _prs(monkeypatch, prs, files=[_file("RQ-A", "2026-11-18T19:30:00+00:00")])
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    lines = []
    rows = t.triage("o/r", live=False, land=False, min_age_min=30, now=now, out=lines.append)
    assert [r["pr"] for r in rows] == [1] and rows[0]["action"] == "close" and rows[0]["done"] is None
    assert calls == []                                    # dry run: no comment, no close


def test_live_closes_with_a_per_unit_comment_and_leaves_a_clean_pr(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_gh", lambda args, inp=None: calls.append((args, inp)) or "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _unit("weekly", "last_dispatched_at: '2026-11-18T21:00:00+00:00'")))
    _prs(monkeypatch, [_pr(1, "automation/research-queue-stamp-9-1")], files=[_file("RQ-A", "2026-11-18T19:30:00+00:00")])
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    rows = t.triage("o/r", live=True, land=False, min_age_min=30, now=now, out=lambda s: None)
    assert rows[0]["done"] == "closed"
    body = next(inp for a, inp in calls if "comment" in a)
    assert "RQ-A" in body and "superseded" in body and "Generated by [Claude Code]" in body
    assert any("close" in a for a, _ in calls)
    calls.clear()
    _prs(monkeypatch, [_pr(1, "automation/research-queue-stamp-9-1")], dirty=False, files=[])
    assert t.triage("o/r", live=True, land=False, min_age_min=30, now=now, out=lambda s: None) == [] and calls == []


def test_a_young_pr_and_an_unreadable_list_are_left_alone(monkeypatch):
    monkeypatch.setattr(t, "_gh", lambda *a, **k: "")
    now = datetime(2026, 11, 18, 19, 10, tzinfo=timezone.utc)
    _prs(monkeypatch, [_pr(1, "automation/research-queue-stamp-9-1", "2026-11-18T19:00:00Z")], files=[])
    assert t.triage("o/r", live=True, land=True, min_age_min=30, now=now, out=lambda s: None) == []
    monkeypatch.setattr(t, "_api", lambda p: None)
    assert t.triage("o/r", live=True, land=True, min_age_min=30, now=now, out=lambda s: None) == []


def test_land_needs_a_token_and_the_flag(monkeypatch):
    monkeypatch.setattr(t, "_gh", lambda *a, **k: "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _unit("weekly", "last_dispatched_at: '2026-11-18T19:00:00+00:00'")))
    pushed = []
    monkeypatch.setattr(t, "land_max", lambda *a, **k: pushed.append(a) or (True, "ok"))
    _prs(monkeypatch, [_pr(1, "automation/research-queue-stamp-9-1")], files=[_file("RQ-A", "2026-11-18T19:30:00+00:00")])
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    t.triage("o/r", live=True, land=False, min_age_min=30, now=now, token="tok", out=lambda s: None)
    t.triage("o/r", live=True, land=True, min_age_min=30, now=now, token="", out=lambda s: None)
    assert pushed == []                                   # no flag, or no token: never pushes
    rows = t.triage("o/r", live=True, land=True, min_age_min=30, now=now, token="tok", out=lambda s: None)
    assert len(pushed) == 1 and rows[0]["done"] == "landed"


# ── receipt PRs (2026-11-26: three watchdog incidents in one night, all the one shared receipt file) ──────────────────────────
RCPT = t.RECEIPT_PATH


def _rcpt_json(ts):
    return '{\n  "run_id": "1",\n  "timestamp": "%s",\n  "fired": "true"\n}\n' % ts


def _rcpt_file(ts):
    return {"filename": RCPT, "patch": '@@ -1,4 +1,4 @@\n-  "timestamp": "2026-11-18T00:00:00+00:00",\n+  "timestamp": "%s",\n' % ts}


def _rdecide(files, main_ts):
    return t.decide_receipt(files, lambda rel: _rcpt_json(main_ts) if rel == RCPT and main_ts else None)


def test_a_receipt_no_newer_than_main_is_superseded_and_closes():
    d = _rdecide([_rcpt_file("2026-11-18T19:00:00+00:00")], "2026-11-18T20:00:00+00:00")
    assert d["action"] == "close" and d["units"][0]["kind"] == t.SUPERSEDED
    assert _rdecide([_rcpt_file("2026-11-18T20:00:00+00:00")], "2026-11-18T20:00:00+00:00")["action"] == "close"   # equal: main wins


def test_a_receipt_newer_than_main_lands():
    d = _rdecide([_rcpt_file("2026-11-18T21:00:00+00:00")], "2026-11-18T20:00:00+00:00")
    assert d["action"] == "land" and d["units"][0]["kind"] == t.NEEDS_LAND and d["receipt"] is True


def test_a_receipt_pr_touching_another_path_or_with_an_unreadable_stamp_is_left_alone():
    ok = [_rcpt_file("2026-11-18T19:00:00+00:00"), {"filename": ".github/merge-slots/a.json"},
          {"filename": ".github/pr-landing/a.json"}, {"filename": ".github/pr-automerge-requests/a.txt"}]
    assert _rdecide(ok, "2026-11-18T20:00:00+00:00")["action"] == "close"          # its own landing files are not stray
    assert _rdecide(ok + [{"filename": "src/x.py", "patch": ""}], "2026-11-18T20:00:00+00:00")["action"] == "leave"
    assert _rdecide([{"filename": "docs/other.md"}], "2026-11-18T20:00:00+00:00")["action"] == "leave"   # no receipt file at all
    assert _rdecide([_rcpt_file("2026-11-18T19:00:00+00:00")], None)["action"] == "leave"                # main's receipt unreadable
    assert _rdecide([{"filename": RCPT, "patch": "@@ no timestamp line"}], "2026-11-18T20:00:00+00:00")["action"] == "leave"


def test_triage_closes_a_dirty_superseded_receipt_pr_and_lands_a_newer_one(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_gh", lambda args, inp=None: calls.append((args, inp)) or "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _rcpt_json("2026-11-18T20:00:00+00:00")))
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    ref = "automation/research-queue-receipt-9-1"
    _prs(monkeypatch, [_pr(1, ref)], files=[_rcpt_file("2026-11-18T19:00:00+00:00")])
    rows = t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    assert rows[0]["done"] == "closed" and any("close" in a for a, _ in calls)
    assert "receipt" in next(inp for a, inp in calls if "comment" in a)
    pushed = []
    monkeypatch.setattr(t, "land_max", lambda *a, **k: pushed.append(a) or (True, "ok"))
    calls.clear()
    _prs(monkeypatch, [_pr(2, ref)], files=[_rcpt_file("2026-11-18T22:00:00+00:00")])
    rows = t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    assert rows[0]["done"] == "landed" and len(pushed) == 1
    assert "this receipt kept (latest wins)" in next(inp for a, inp in calls if "comment" in a)
    # a dry run does nothing to a receipt PR either, and a clean one is left to auto-merge
    calls.clear()
    t.triage("o/r", live=False, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    _prs(monkeypatch, [_pr(3, ref)], dirty=False, files=[])
    assert t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None) == [] and calls == []


def test_the_workflow_passes_the_land_flag_and_a_ci_triggering_token_to_the_triage():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/research-watchdog.yml").read_text()
    step = wf.split("- name: Triage conflicted stamp PRs", 1)[1].split("- uses: actions/upload-artifact", 1)[0]
    assert "STAMP_TRIAGE_TOKEN: ${{ secrets.BRANCH_PROTECTION_TOKEN }}" in step     # a GITHUB_TOKEN push would not trigger CI
    assert 'LIVE="--live --land --min-age-min 10"' in step     # landing on, and acting well before the watchdog's 45-minute alarm


# ── grade PRs + the "unknown" re-read (2026-11-26, run 429 named #28990) ───────────────────────────────────────────────────────
def _qfile(uid):
    return {"filename": f"research/queue/{uid}.yaml", "patch": "@@ -1 +1 @@\n+grading: {}\n"}


def test_a_grade_pr_of_only_queue_edits_is_closed_and_anything_else_is_left():
    ok = [_qfile("RQ-A"), {"filename": ".github/merge-slots/a.json"}, {"filename": ".github/pr-landing/a.json"},
          {"filename": ".github/pr-automerge-requests/a.txt"}]
    assert t.decide_grade(ok)["action"] == "close"
    assert t.decide_grade(ok + [{"filename": "src/x.py"}])["action"] == "leave"
    assert t.decide_grade([{"filename": "docs/other.md"}])["action"] == "leave"          # no queue edit at all
    body = t.comment_body(t.decide_grade(ok), "closing")
    assert "re-derives every disposition from scratch" in body and "Generated by [Claude Code]" in body


def test_triage_closes_a_dirty_grade_pr_only_after_the_refresh_window(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_gh", lambda args, inp=None: calls.append((args, inp)) or "")
    ref = "automation/research-queue-grade-9-1"
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    _prs(monkeypatch, [_pr(1, ref, "2026-11-18T22:40:00Z")], files=[_qfile("RQ-A")])          # 20 min old: inside the 30 min window
    assert t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None) == [] and calls == []
    _prs(monkeypatch, [_pr(2, ref, "2026-11-18T22:20:00Z")], files=[_qfile("RQ-A")])          # 40 min old
    rows = t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    assert rows[0]["done"] == "closed" and any("close" in a for a, _ in calls)
    assert "grade family" in next(inp for a, inp in calls if "comment" in a)
    calls.clear()                                                                          # dry run and a stray path do nothing
    t.triage("o/r", live=False, land=False, min_age_min=10, now=now, out=lambda s: None)
    _prs(monkeypatch, [_pr(3, ref, "2026-11-18T22:00:00Z")], files=[_qfile("RQ-A"), {"filename": "src/x.py"}])
    rows = t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    assert rows[0]["action"] == "leave" and calls == []


def _seq_api(monkeypatch, prs, states, files):
    reads = []

    def api(path):
        if path.endswith("/files?per_page=100"):
            return files
        if "/pulls/" in path:
            reads.append(path)
            return {"mergeable_state": states[min(len(reads) - 1, len(states) - 1)]}
        return prs
    monkeypatch.setattr(t, "_api", api)
    return reads


def test_an_unknown_state_is_re_read_once_before_it_is_read_as_not_dirty(monkeypatch):
    calls, slept = [], []
    monkeypatch.setattr(t, "_gh", lambda args, inp=None: calls.append((args, inp)) or "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _unit("weekly", "last_dispatched_at: '2026-11-18T21:00:00+00:00'")))
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    ref = "automation/research-queue-stamp-9-1"
    reads = _seq_api(monkeypatch, [_pr(1, ref)], ["unknown", "dirty"], [_file("RQ-A", "2026-11-18T19:30:00+00:00")])
    rows = t.triage("o/r", live=True, land=False, min_age_min=10, now=now, out=lambda s: None, sleep=slept.append)
    assert len(reads) == 2 and slept == [t.UNKNOWN_RETRY_SLEEP_S] and rows[0]["done"] == "closed"
    calls.clear()
    slept.clear()
    reads = _seq_api(monkeypatch, [_pr(1, ref)], ["unknown"], [_file("RQ-A", "2026-11-18T19:30:00+00:00")])   # still unknown: ONE re-read, no loop
    assert t.triage("o/r", live=True, land=False, min_age_min=10, now=now, out=lambda s: None, sleep=slept.append) == []
    assert len(reads) == 2 and calls == []
    reads = _seq_api(monkeypatch, [_pr(1, ref)], ["clean"], [])                                                # a known state is read once, no sleep
    slept.clear()
    t.triage("o/r", live=True, land=False, min_age_min=10, now=now, out=lambda s: None, sleep=slept.append)
    assert len(reads) == 1 and slept == []


# ── land is shallow-safe and contained (2026-11-26, run 431: a depth-1 runner timed out fetching two histories and the TimeoutExpired
#    killed the whole triage run). Proven against a REAL local bare repo and a depth-1 "runner" clone, not mocks. ──────────────────────
import os  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

_GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
_BR = "automation/research-queue-stamp-9-1"


def _g(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True, text=True, env=_GIT_ENV).stdout


def _stamp_text(ts):
    return f"id: RQ-A\ncadence: weekly\nstatus: queued\nlast_dispatched_at: '{ts}'\nrun: {{}}\n"


@pytest.fixture
def repos(tmp_path):
    bare, work, runner = tmp_path / "remote.git", tmp_path / "work", tmp_path / "runner"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work.mkdir()
    _g(work, "init", "-q", "-b", "main")
    _g(work, "remote", "add", "origin", str(bare))
    (work / "research/queue").mkdir(parents=True)
    (work / "docs/claude/work").mkdir(parents=True)
    (work / "research/queue/RQ-A.yaml").write_text(_stamp_text("2026-11-18T19:00:00+00:00"))
    (work / t.RECEIPT_PATH).write_text(_rcpt_json("2026-11-18T19:00:00+00:00"))
    _g(work, "add", "-A"); _g(work, "commit", "-q", "-m", "c0"); _g(work, "push", "-q", "origin", "main")  # noqa: E702
    _g(work, "checkout", "-q", "-b", _BR)                                                     # the PR branch, cut from c0
    (work / "research/queue/RQ-A.yaml").write_text(_stamp_text("2026-11-18T21:00:00+00:00"))
    (work / t.RECEIPT_PATH).write_text(_rcpt_json("2026-11-18T22:00:00+00:00"))
    (work / ".github/pr-landing").mkdir(parents=True)
    (work / ".github/pr-landing/x.json").write_text('{"tier": 1}\n')
    _g(work, "add", "-A"); _g(work, "commit", "-q", "-m", "pr"); _g(work, "push", "-q", "origin", _BR)  # noqa: E702
    _g(work, "checkout", "-q", "main")                                                        # main moves on the SAME line: a real conflict
    (work / "research/queue/RQ-A.yaml").write_text(_stamp_text("2026-11-18T20:00:00+00:00"))
    (work / t.RECEIPT_PATH).write_text(_rcpt_json("2026-11-18T20:30:00+00:00"))
    (work / "docs/mainonly.md").write_text("only on main\n")
    _g(work, "add", "-A"); _g(work, "commit", "-q", "-m", "c1"); _g(work, "push", "-q", "origin", "main")  # noqa: E702
    subprocess.run(["git", "clone", "-q", "--depth=1", f"file://{bare}", str(runner)], check=True, env=_GIT_ENV)
    return bare, work, runner


def _unit_decision():
    return {"units": [{"unit": "RQ-A", "path": "research/queue/RQ-A.yaml", "stamp": "2026-11-18T21:00:00+00:00",
                       "main": "2026-11-18T20:00:00+00:00", "kind": t.NEEDS_LAND, "reason": ""}],
            "own": [".github/pr-landing/x.json"]}


def _mergeable_into_main(work, bare):
    _g(work, "fetch", "-q", "origin")
    _g(work, "checkout", "-q", "-B", "probe", f"origin/{_BR}")
    out = _g(work, "merge", "origin/main")                      # raises on any conflict
    _g(work, "checkout", "-q", "main")
    return out


def test_land_pushes_a_merge_commit_from_a_depth_one_clone_with_no_conflict_left(repos):
    bare, work, runner = repos
    assert (runner / ".git/shallow").exists()                     # the runner really is shallow
    ok, why = t.land_max("o/r", 1, _BR, _unit_decision(), "tok", repo_root=runner, remote_url=str(bare))
    assert ok, why
    _g(work, "fetch", "-q", "origin")
    assert len(_g(work, "rev-list", "--parents", "-n", "1", f"origin/{_BR}").split()) == 3       # commit + its two parents
    assert "last_dispatched_at: '2026-11-18T21:00:00+00:00'" in _g(work, "show", f"origin/{_BR}:research/queue/RQ-A.yaml")  # max wins
    assert _g(work, "show", f"origin/{_BR}:docs/mainonly.md") == "only on main\n"                # main's other content is in the tree
    assert _g(work, "show", f"origin/{_BR}:.github/pr-landing/x.json") == '{"tier": 1}\n'         # the PR's own landing file is kept
    assert "up to date" in _mergeable_into_main(work, bare).lower()                              # no conflict, nothing left to merge


def test_land_resolves_to_main_when_the_prs_stamp_is_older(repos):
    bare, work, runner = repos
    d = _unit_decision()
    d["units"][0]["stamp"] = "2026-11-18T19:30:00+00:00"          # the PR's stamp is OLDER than main's 20:00
    ok, why = t.land_max("o/r", 1, _BR, d, "tok", repo_root=runner, remote_url=str(bare))
    assert ok, why
    _g(work, "fetch", "-q", "origin")
    assert "last_dispatched_at: '2026-11-18T20:00:00+00:00'" in _g(work, "show", f"origin/{_BR}:research/queue/RQ-A.yaml")


def test_land_keeps_a_newer_receipt_as_a_whole_file(repos):
    bare, work, runner = repos
    # a receipt PR: the PR's receipt (22:00) is newer than main's (20:30) and is kept as a whole file
    rd = {"receipt": True, "own": [".github/pr-landing/x.json"],
          "units": [{"unit": "receipt", "path": t.RECEIPT_PATH, "stamp": "2026-11-18T22:00:00+00:00", "main": "2026-11-18T20:30:00+00:00",
                     "kind": t.NEEDS_LAND, "reason": ""}]}
    ok, why = t.land_max("o/r", 1, _BR, rd, "tok", repo_root=runner, remote_url=str(bare))
    assert ok, why
    _g(work, "fetch", "-q", "origin")
    assert t.receipt_stamp(_g(work, "show", f"origin/{_BR}:{t.RECEIPT_PATH}")) == "2026-11-18T22:00:00+00:00"
    assert "up to date" in _mergeable_into_main(work, bare).lower()


def test_land_never_raises_a_git_failure_or_timeout_is_a_false_result(repos, monkeypatch):
    bare, work, runner = repos
    ok, why = t.land_max("o/r", 1, _BR, _unit_decision(), "tok", repo_root=runner, remote_url=str(bare) + "-missing")
    assert ok is False and "fetch" in why
    real = subprocess.run

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git fetch", timeout=1)
    monkeypatch.setattr(t.subprocess, "run", slow)
    ok, why = t.land_max("o/r", 1, _BR, _unit_decision(), "tok", repo_root=runner, remote_url=str(bare))
    assert ok is False and "TimeoutExpired" in why
    monkeypatch.setattr(t.subprocess, "run", real)


def test_one_pr_whose_land_blows_up_does_not_stop_the_triage_of_the_next(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "_gh", lambda args, inp=None: calls.append((args, inp)) or "")
    monkeypatch.setattr(t, "main_reader", lambda *a, **k: (lambda rel: _unit("weekly", "last_dispatched_at: '2026-11-18T19:00:00+00:00'")
                                                          if rel.startswith("research/queue/") else _rcpt_json("2026-11-18T22:30:00+00:00")))

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git fetch", timeout=300)
    monkeypatch.setattr(t, "land_max", boom)
    files = {1: [_file("RQ-A", "2026-11-18T19:30:00+00:00")], 2: [_rcpt_file("2026-11-18T22:00:00+00:00")]}

    def api(path):
        if path.endswith("/files?per_page=100"):
            return files[int(path.split("/pulls/")[1].split("/")[0])]
        if "/pulls/" in path:
            return {"mergeable_state": "dirty"}
        return [_pr(1, "automation/research-queue-stamp-9-1"), _pr(2, "automation/research-queue-receipt-9-1")]
    monkeypatch.setattr(t, "_api", api)
    now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)
    rows = t.triage("o/r", live=True, land=True, min_age_min=10, now=now, token="tok", out=lambda s: None)
    assert [r["pr"] for r in rows] == [1, 2]                                   # PR 2 was still reached
    assert rows[0]["done"].startswith("land_failed") and "TimeoutExpired" in rows[0]["done"]
    assert rows[1]["done"] == "closed"                                         # its receipt is superseded by main's 22:30
