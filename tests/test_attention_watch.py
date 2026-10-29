"""WORK-SYSTEM: the attention watch — digest, edge alerts, silence alarms."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.ops import attention_watch as a


@pytest.fixture(autouse=True)
def _isolate_due_seen(tmp_path, monkeypatch):
    # build() persists the live-review first-seen cache; never into the real runtime_logs.
    monkeypatch.setattr(a, "LR_DUE_SEEN", tmp_path / "lr_due_seen.json")


def test_self_test_passes():
    assert a._self_test() == 0


def _fake_send_ping(monkeypatch, enqueue):
    import sys
    import types
    mod = types.ModuleType("send_ping")
    mod.enqueue = enqueue
    # setitem, not setattr on an import path: the bare `send_ping` name is only
    # importable when scripts/ is on sys.path, which depends on test order.
    monkeypatch.setitem(sys.modules, "send_ping", mod)


def test_run_sends_through_claude_inbox_and_advances_state(tmp_path, monkeypatch):
    sent = []
    _fake_send_ping(monkeypatch, lambda body, priority="normal", target="trader":
                    sent.append((target, priority)))
    monkeypatch.setattr(a, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(a, "RECEIPT", tmp_path / "receipt.json")
    monkeypatch.setattr("scripts.ops.work_report.DIGEST_LOG", tmp_path / "digest_log.jsonl")
    assert a.run(digest_now=True) == 0
    assert sent and all(t == "claude" for t, _ in sent)
    assert (tmp_path / "state.json").exists() and (tmp_path / "receipt.json").exists()


def test_failed_send_does_not_advance_state(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("inbox gone")
    _fake_send_ping(monkeypatch, boom)
    monkeypatch.setattr(a, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(a, "RECEIPT", tmp_path / "receipt.json")
    assert a.run(digest_now=True) == 1
    assert not (tmp_path / "state.json").exists()


def test_work_report_self_test_passes():
    from scripts.ops import work_report
    assert work_report._self_test() == 0


def test_report_route_absent_then_present(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from scripts.ops import work_report
    from src.web.api.routers import work

    monkeypatch.setattr(work_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(work_report.read_latest, "__defaults__", (tmp_path,))
    monkeypatch.setattr(work_report.read_report, "__defaults__", (tmp_path,))
    out = work.get_work_report()
    assert out["present"] is False and out["readState"] == "absent"
    rep = work_report.generate(datetime(2026, 10, 5, 5, 30, tzinfo=timezone.utc))
    work_report.persist(rep, tmp_path)
    out = work.get_work_report()
    assert out["present"] is True and out["reportId"] == "WR-20261005-0530Z"
    assert work.get_work_report(report_id="WR-20261005-0530Z")["present"] is True
    assert all("trace" not in v for v in out["sections"].values())


def test_report_probe_breaches_when_absent_and_when_errored(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from scripts.ops import work_report
    monkeypatch.setattr(work_report.read_latest, "__defaults__", (tmp_path,))
    now = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)
    assert a.probe_report(now)["status"] == a.BREACHED
    rep = work_report.generate(datetime(2026, 10, 5, 5, 30, tzinfo=timezone.utc))
    rep["errored_sections"], rep["bytes"] = [], 10_000
    work_report.persist(rep, tmp_path)
    assert a.probe_report(now)["status"] == a.OK
    rep["errored_sections"] = ["soaks"]
    work_report.persist(rep, tmp_path)
    assert a.probe_report(now)["status"] == a.BREACHED
    # yesterday's report at 06:00 today = today's was not produced
    rep2 = work_report.generate(datetime(2026, 10, 4, 5, 30, tzinfo=timezone.utc))
    rep2["errored_sections"], rep2["bytes"] = [], 10_000
    (tmp_path / "latest.json").unlink()
    work_report.persist(rep2, tmp_path)
    assert a.probe_report(now)["status"] == a.BREACHED


def test_report_route_since_returns_sent_digest_blocks(tmp_path, monkeypatch):
    from scripts.ops import work_report
    from src.web.api.routers import work

    log = tmp_path / "digest_log.jsonl"
    monkeypatch.setattr(work_report, "DIGEST_LOG", log)
    monkeypatch.setattr(work_report.read_latest, "__defaults__", (tmp_path,))
    out = work.get_work_report(since="2026-10-05T00:00:00+00:00")
    assert out["digestLogState"] == "absent" and out["digestLog"] == []
    work_report.append_digest_log({"at": "2026-10-05T07:00:00+00:00", "new": ["🔕 x"]}, log)
    out = work.get_work_report(since="2026-10-05T06:00:00+00:00")
    assert out["digestLogState"] == "read" and out["digestLog"][0]["new"] == ["🔕 x"]
    assert "digestLog" not in work.get_work_report()


def test_prop_feed_probe_unknown_ok_then_breached(tmp_path, monkeypatch):
    """NO-HALT (2026-10-09): the feed never trips; the probe reads its backoff
    state. Could-not-look stays distinct from not-in-backoff."""
    from datetime import datetime, timezone
    now = datetime(2026, 10, 7, 21, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PROP_BROWSER_BASE", str(tmp_path / "missing"))
    assert a.probe_prop_feed(now)["status"] == a.UNKNOWN          # could not look != ok
    monkeypatch.setenv("PROP_BROWSER_BASE", str(tmp_path))
    assert a.probe_prop_feed(now)["status"] == a.OK
    d = tmp_path / "accounts" / "tradeify_1" / "feed"
    d.mkdir(parents=True)
    # A stale pre-NO-HALT marker is not a signal any more.
    (d / "tripped").write_text("2026-10-06T18:27:45Z rc=4 feasibility stop")
    assert a.probe_prop_feed(now)["status"] == a.OK
    st = d / "backoff"
    # Below the red-flag threshold: retrying normally, OK.
    st.write_text("consecutive_failures=1\nnext_attempt_at=0\nflagged=0\nreason=error\n")
    assert a.probe_prop_feed(now)["status"] == a.OK
    st.write_text("consecutive_failures=3\nflagged=1\nflagged_at=2026-10-07T20:00:00Z\n"
                  "next_attempt_at_utc=2026-10-07T21:05:00Z\nreason=3 consecutive failures\n")
    assert a.probe_prop_feed(now)["status"] == a.OK                # inside the grace
    st.write_text("consecutive_failures=9\nflagged=1\nflagged_at=2026-10-06T18:00:00Z\n"
                  "next_attempt_at_utc=2026-10-07T22:00:00Z\nreason=feasibility stop\n")
    r = a.probe_prop_feed(now)
    assert r["status"] == a.BREACHED and "tradeify_1" in r["detail"] and "reset-feed" in r["detail"]
    assert "retrying" in r["detail"]


def test_prop_feed_probe_unreadable_state_is_unknown_not_ok(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 7, 21, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PROP_BROWSER_BASE", str(tmp_path))
    # tradeify_1, not breakout_1: breakout_1 is retired (OPS-DECISIONS-1009) and a
    # retired account's feed state is skipped, never paged.
    (tmp_path / "accounts" / "tradeify_1" / "feed" / "backoff").mkdir(parents=True)  # a dir: read_text raises
    r = a.probe_prop_feed(now)
    assert r["status"] == a.UNKNOWN and "tradeify_1" in r["detail"]

# -- LTR-1B-ATTENTION-PROBE: live_review_due_stale ---------------------------------
NOW = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
TH = (120.0, 120.0)


def _row(rid, at):
    return json.dumps({"review_id": rid, "reviewed_at": at.strftime("%Y-%m-%dT%H:%M:%SZ")})


def _due(*pkgs):
    return {"read_state": "looked", "reason": None, "due_count": len(pkgs),
            "due": [{"order_package_id": p, "leg": "l", "account_id": "x",
                     "events": [{"event": "r_milestone", "level": 1.0}]} for p in pkgs]}


def _probe(tmp_path, due=None, branch="", main="", now=NOW, persist=True, refuses=lambda row: False):
    return a.probe_live_review_due_stale(
        now, due_doc=due if due is not None else _due(), branch_text=branch, main_text=main,
        seen_path=tmp_path / "seen.json", persist=persist, thresholds=TH, refuses=refuses)


def test_quiet_is_ok(tmp_path):
    r = _row("A", NOW - timedelta(hours=5))
    assert _probe(tmp_path, branch=r, main=r)["status"] == a.OK


def test_due_package_breaches_only_after_threshold(tmp_path):
    assert _probe(tmp_path, due=_due("p1"), now=NOW - timedelta(minutes=150))["status"] == a.OK
    assert _probe(tmp_path, due=_due("p1"), now=NOW - timedelta(minutes=60))["status"] == a.OK  # clock keeps first sight
    out = _probe(tmp_path, due=_due("p1"), now=NOW)
    assert out["status"] == a.BREACHED and "unreviewed" in out["detail"]


def test_due_clock_resets_when_package_is_reviewed(tmp_path):
    _probe(tmp_path, due=_due("p1"), now=NOW - timedelta(minutes=200))
    _probe(tmp_path, due=_due(), now=NOW - timedelta(minutes=100))      # reviewed: dropped from the cache
    assert _probe(tmp_path, due=_due("p1"), now=NOW)["status"] == a.OK  # a fresh due, a fresh clock


def test_rows_branch_ahead_past_gap_breaches(tmp_path):
    """The 2026-10-26 incident: branch has rows main never got."""
    old, new = _row("A", NOW - timedelta(hours=6)), _row("B", NOW - timedelta(hours=3))
    out = _probe(tmp_path, branch=old + "\n" + new, main=old)
    assert out["status"] == a.BREACHED and "mirror is stuck" in out["detail"]


def test_rows_branch_ahead_within_gap_is_ok(tmp_path):
    old, new = _row("A", NOW - timedelta(hours=6)), _row("B", NOW - timedelta(minutes=30))
    assert _probe(tmp_path, branch=old + "\n" + new, main=old)["status"] == a.OK


def test_unparseable_branch_line_does_not_hide_a_stuck_row(tmp_path):
    old = _row("A", NOW - timedelta(hours=4))
    out = _probe(tmp_path, branch="{not json\n" + old, main="")
    assert out["status"] == a.BREACHED


def test_route_could_not_look_is_unknown_not_ok(tmp_path):
    r = _row("A", NOW - timedelta(hours=5))
    out = _probe(tmp_path, due={"read_state": "could_not_look", "reason": "telemetry_table_absent",
                                "due_count": None, "due": []}, branch=r, main=r)
    assert out["status"] == a.UNKNOWN and "could_not_look" in out["detail"]


def test_rows_ref_missing_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_git", lambda *args: None)  # the watcher never fetched the ref
    r = a.probe_live_review_due_stale(NOW, due_doc=_due(), branch_text=None, main_text="",
                                      seen_path=tmp_path / "s.json", thresholds=TH, refuses=lambda row: False)
    assert r["status"] == a.UNKNOWN


def test_breach_wins_over_unknown(tmp_path):
    old = _row("A", NOW - timedelta(hours=4))
    out = _probe(tmp_path, due={"read_state": "could_not_look", "reason": "x", "due_count": None, "due": []},
                 branch=old, main="")
    assert out["status"] == a.BREACHED


def test_dry_run_does_not_write_the_cache(tmp_path):
    _probe(tmp_path, due=_due("p1"), persist=False)
    assert not (tmp_path / "seen.json").exists()


def test_unreadable_thresholds_is_unknown(tmp_path):
    assert a._lr_thresholds(tmp_path / "missing.yaml") is None
    assert a._lr_thresholds()  # the committed config carries watch:


def test_probe_is_registered_and_labelled():
    assert "live_review_due_stale" in a.PROBE_LABEL
    assert a.build(NOW, persist_seen=False)["probes"]["live_review_due_stale"]["status"] in (a.OK, a.BREACHED, a.UNKNOWN)


def test_schema_refused_row_ahead_of_main_is_not_counted(tmp_path):
    """The mirror skips a checker-refused row for good (MIRROR-STALL), so it is not a stall."""
    bad = _row("BAD", NOW - timedelta(hours=6))
    out = _probe(tmp_path, branch=bad, main="", refuses=lambda row: row["review_id"] == "BAD")
    assert out["status"] == a.OK and "1 schema-refused row excluded" in out["detail"]


def test_valid_lagging_row_still_breaches_beside_a_refused_one(tmp_path):
    bad, good = _row("BAD", NOW - timedelta(hours=6)), _row("GOOD", NOW - timedelta(hours=3))
    out = _probe(tmp_path, branch=bad + "\n" + good, main="", refuses=lambda row: row["review_id"] == "BAD")
    assert out["status"] == a.BREACHED and "GOOD" in out["detail"] and "1 schema-refused row excluded" in out["detail"]


def test_checker_not_importable_is_unknown_never_ok(tmp_path):
    r = _row("A", NOW - timedelta(hours=5))
    out = a.probe_live_review_due_stale(NOW, due_doc=_due(), branch_text=r, main_text="",
                                        seen_path=tmp_path / "s.json", thresholds=TH,
                                        refuses=None)
    # refuses=None means "load the real checker"; force the failure path directly
    assert a._lr_rows_clause(NOW, 120, r, "", None)[0] == a.UNKNOWN
    assert out["status"] in (a.OK, a.BREACHED, a.UNKNOWN)


def test_real_checker_refuses_the_incident_row_shape():
    refuses = a._lr_refuses()
    assert refuses is not None
    assert refuses({"review_id": "x", "reviewed_at": "2026-10-26T23:13:00Z"}) is True


# ── DESK-V1-ALERTS: desk_row_missing ─────────────────────────────────────────
_DNOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


def _desk_git(ptr, rows):
    def fake(*args):
        spec = args[-1]
        if spec.endswith(a.DESK_POINTER):
            return ptr
        if spec.endswith(a.DESK_DECISIONS):
            return rows
        return None
    return fake


def _ptr(minutes_ago, pid="DP-1"):
    return json.dumps({"packet_id": pid, "built_at": (_DNOW - timedelta(minutes=minutes_ago)).isoformat()})


def test_desk_row_missing_breaches_past_15_min_with_no_row(monkeypatch):
    monkeypatch.setattr(a, "_git", _desk_git(_ptr(16), json.dumps({"packet_id": "DP-0"}) + "\n"))
    p = a.probe_desk_row_missing(_DNOW)
    assert p["status"] == a.BREACHED and p["read_state"] == "read" and "DP-1" in p["detail"]


def test_desk_row_missing_ok_inside_window_or_with_row(monkeypatch):
    monkeypatch.setattr(a, "_git", _desk_git(_ptr(10), ""))
    assert a.probe_desk_row_missing(_DNOW)["status"] == a.OK
    monkeypatch.setattr(a, "_git", _desk_git(_ptr(300), json.dumps({"packet_id": "DP-1"}) + "\n"))
    assert a.probe_desk_row_missing(_DNOW)["status"] == a.OK


@pytest.mark.parametrize("ptr,rows", [(None, ""), (_ptr(60), None), ("{not json", ""),
                                      (json.dumps({"packet_id": "DP-1"}), "")])
def test_desk_row_missing_unreadable_is_unknown_never_ok(monkeypatch, ptr, rows):
    monkeypatch.setattr(a, "_git", _desk_git(ptr, rows))
    p = a.probe_desk_row_missing(_DNOW)
    assert p["status"] == a.UNKNOWN and p["read_state"] == "could_not_look"


def test_desk_row_missing_is_a_registered_probe():
    assert "desk_row_missing" in a.PROBE_LABEL
