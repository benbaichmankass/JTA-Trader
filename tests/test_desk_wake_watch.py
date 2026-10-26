"""DESK-6B: the VM-side desk-wake watch (src/runtime/desk_wake_watch.py): receipt + liveness, never a post."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import desk_wake_watch as dw

NOW = datetime(2026, 10, 26, 16, 40, tzinfo=timezone.utc)
PID = "DP-20261026T1631Z-scan-1h"


class Net:
    def __init__(self, built_ago=timedelta(minutes=4), markers=(), rows=(), ptr_code=200, rows_code=200, cm_code=200):
        built = NOW - built_ago
        self.ptr = {"packet_id": PID, "packet_sha": "a" * 64, "path": f"comms/desk/packets/{PID}.json",
                    "built_at": built.strftime("%Y-%m-%dT%H:%M:%SZ"), "info_cutoff_at": "2026-10-26T16:31:00Z"}
        self.markers, self.rows = list(markers), list(rows)
        self.ptr_code, self.rows_code, self.cm_code = ptr_code, rows_code, cm_code
        self.calls = []

    def fetch(self, url, auth):
        self.calls.append((url,))
        if "latest_scan" in url:
            return self.ptr_code, (self.ptr if self.ptr_code == 200 else None)
        return self.rows_code, ("\n".join(json.dumps(r) for r in self.rows) if self.rows_code == 200 else None)

    def http(self, method, url, body, auth):
        assert method == "GET", "the watch must never post"
        bodies = [{"body": "x\n<!-- desk-wake " + json.dumps(m) + " -->"} for m in self.markers]
        return self.cm_code, (bodies if self.cm_code == 200 else None)


def posted(pid=PID, at=NOW - timedelta(minutes=3)):
    return {"kind": "desk-wake", "packet_id": pid, "commit": "c" * 40, "posted_at": at.isoformat()}


def run(tmp_path, net, now=NOW):
    rec = dw.run_once(fetch=net.fetch, auth_fn=lambda: None, http=net.http, now_fn=lambda: now,
                      receipt=tmp_path / "r.json", pr_fn=lambda: 17895)
    assert json.loads((tmp_path / "r.json").read_text())["state"] == rec["state"]
    return rec


def test_posted_marker_for_the_packet_id(tmp_path):
    rec = run(tmp_path, Net(markers=[posted()]))
    assert rec["state"] == "posted" and rec["latency_s"] == 60.0 and rec["commit"] == "c" * 40
    assert rec["last_posted"]["packet_id"] == PID


def test_a_marker_for_another_packet_does_not_count(tmp_path):
    rec = run(tmp_path, Net(markers=[posted("DP-older")], built_ago=timedelta(minutes=2)))
    assert rec["state"] == "awaiting_wake"


def test_decision_row_means_the_wake_ran(tmp_path):
    assert run(tmp_path, Net(rows=[{"decision_id": "DD-1", "packet_id": PID}]))["state"] == "already_recorded"


def test_no_marker_inside_the_grace_is_awaiting_not_missing(tmp_path):
    assert run(tmp_path, Net(built_ago=timedelta(minutes=dw.WAKE_GRACE_MIN - 1)))["state"] == "awaiting_wake"


def test_no_marker_past_the_grace_is_a_named_missing_wake(tmp_path):
    rec = run(tmp_path, Net(built_ago=timedelta(minutes=dw.WAKE_GRACE_MIN + 5)))
    assert rec["state"] == "wake_missing" and PID in rec["reason"]


def test_failed_build_marker_is_reported(tmp_path):
    fail = {"kind": "could_not_build", "bar": "2026-10-26T17:00:00Z", "step": "Build the scan packet",
            "posted_at": (NOW - timedelta(minutes=1)).isoformat()}
    rec = run(tmp_path, Net(markers=[fail], built_ago=timedelta(minutes=40)))
    assert rec["state"] == "could_not_build" and rec["step"] == "Build the scan packet"


def test_stale_packet_without_a_failure_marker_is_could_not_look(tmp_path):
    rec = run(tmp_path, Net(built_ago=timedelta(minutes=dw.PACKET_MAX_AGE_MIN + 5), rows=[]))
    assert rec["state"] == "could_not_look" and rec["reason"].startswith("stale_packet")


@pytest.mark.parametrize("kw,frag", [(dict(ptr_code=404), "latest_scan"), (dict(rows_code=500), "decisions.jsonl"),
                                     (dict(cm_code=500), "comments unreadable")])
def test_unreadable_inputs_are_could_not_look(tmp_path, kw, frag):
    rec = run(tmp_path, Net(**kw))
    assert rec["state"] == "could_not_look" and frag in rec["reason"]


def test_last_posted_survives_a_later_look(tmp_path):
    run(tmp_path, Net(markers=[posted()]))
    rec = run(tmp_path, Net(built_ago=timedelta(minutes=1)), now=NOW + timedelta(minutes=30))
    assert rec["last_posted"]["packet_id"] == PID


def test_kick_is_a_noop_off_the_live_trader():
    assert dw.kick() is False
