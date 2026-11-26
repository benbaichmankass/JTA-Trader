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
    calls.clear(); slept.clear()
    reads = _seq_api(monkeypatch, [_pr(1, ref)], ["unknown"], [_file("RQ-A", "2026-11-18T19:30:00+00:00")])   # still unknown: ONE re-read, no loop
    assert t.triage("o/r", live=True, land=False, min_age_min=10, now=now, out=lambda s: None, sleep=slept.append) == []
    assert len(reads) == 2 and calls == []
    reads = _seq_api(monkeypatch, [_pr(1, ref)], ["clean"], [])                                                # a known state is read once, no sleep
    slept.clear()
    t.triage("o/r", live=True, land=False, min_age_min=10, now=now, out=lambda s: None, sleep=slept.append)
    assert len(reads) == 1 and slept == []
