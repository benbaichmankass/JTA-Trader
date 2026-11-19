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
