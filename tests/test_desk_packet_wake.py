"""DESK-6B: the VM-side packet producer + wake poster (src/runtime/desk_packet_wake.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import desk_packet_wake as dw

NOW = datetime(2026, 10, 26, 16, 40, tzinfo=timezone.utc)  # hour 16 already has PID (cutoff 16:31)
PID = "DP-20261026T1631Z-scan-1h"


class Net:
    def __init__(self, built_ago=timedelta(minutes=4), markers=(), rows=(), ptr_code=200, rows_code=200, cm_code=200):
        built = NOW - built_ago
        self.ptr = {"packet_id": PID, "packet_sha": "a" * 64, "path": f"comms/desk/packets/{PID}.json",
                    "built_at": built.strftime("%Y-%m-%dT%H:%M:%SZ"), "info_cutoff_at": "2026-10-26T16:31:00Z"}
        self.markers, self.rows = list(markers), list(rows)
        self.ptr_code, self.rows_code, self.cm_code = ptr_code, rows_code, cm_code
        self.calls, self.posts, self.post_code = [], [], 201

    def fetch(self, url, auth):
        self.calls.append((url,))
        if "latest_scan" in url:
            return self.ptr_code, (self.ptr if self.ptr_code == 200 else None)
        return self.rows_code, ("\n".join(json.dumps(r) for r in self.rows) if self.rows_code == 200 else None)

    def http(self, method, url, body, auth):
        if method != "GET":
            self.posts.append((method, url, body))
            return self.post_code, {"html_url": "https://example/c/1"}
        bodies = [{"body": "x\n<!-- desk-wake " + json.dumps(m) + " -->"} for m in self.markers]
        return self.cm_code, (bodies if self.cm_code == 200 else None)


def posted(pid=PID, at=NOW - timedelta(minutes=3)):
    return {"kind": "desk-wake", "packet_id": pid, "commit": "c" * 40, "posted_at": at.isoformat()}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(dw, "_attempts", {})


def run(tmp_path, net, now=NOW, **kw):
    rec = dw.run_once(fetch=net.fetch, auth_fn=lambda: None, http=net.http, now_fn=lambda: now,
                      receipt=tmp_path / "r.json", pr_fn=lambda: 17895, **kw)
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


# ---- the producer: build -> land -> wake, one step -------------------------------

NEXT = datetime(2026, 10, 26, 17, 3, tzinfo=timezone.utc)  # hour 17 has no packet yet
PK = {"universe": [], "system_book": {"read_state": "read", "near_signals_read_state": "read", "items": []},
      "desk_book": {"read_state": "read", "items": []}}


def make_stage(tmp_path, pid="DP-20261026T1703Z-scan-1h"):
    st = tmp_path / "stage"
    (st / "comms/desk/packets").mkdir(parents=True, exist_ok=True)
    ptr = {"packet_id": pid, "packet_sha": "b" * 64, "built_at": "2026-10-26T17:03:30Z",
           "info_cutoff_at": "2026-10-26T17:03:00Z", "path": f"comms/desk/packets/{pid}.json"}
    (st / "comms/desk/latest_scan.json").write_text(json.dumps(ptr))
    (st / ptr["path"]).write_text(json.dumps(PK))
    return st


def produce(tmp_path, net, build=None, commit=None, now=NEXT, auth="Basic eA=="):
    stage = make_stage(tmp_path)
    return dw.run_once(fetch=net.fetch, auth_fn=lambda: auth, http=net.http, now_fn=lambda: now,
                       receipt=tmp_path / "r.json", pr_fn=lambda: 17895,
                       build_fn=build or (lambda n, t: (stage, None)),
                       commit_fn=commit or (lambda st, pid, a, h: ("c" * 40, None)))


def test_builds_lands_and_posts_one_wake_for_a_new_hour(tmp_path):
    net = Net()
    rec = produce(tmp_path, net)
    assert rec["state"] == "posted" and rec["producer"] == "vm" and rec["commit"] == "c" * 40
    assert len(net.posts) == 1
    m = dw.marker_module().parse_markers([{"body": json.loads(net.posts[0][2])["body"]}])[0]
    assert (m["packet_id"], m["commit"], m["bar"], m["poster"]) == ("DP-20261026T1703Z-scan-1h", "c" * 40,
                                                                  "2026-10-26T17:00:00Z", "vm")


def test_no_build_before_the_bar_has_closed_or_when_the_hour_has_a_packet(tmp_path):
    calls = []
    def build(n, t):
        calls.append(1)
        return None, "x"
    produce(tmp_path, Net(), build=build, now=datetime(2026, 10, 26, 17, 0, 20, tzinfo=timezone.utc))  # minute 0
    produce(tmp_path, Net(), build=build, now=NOW)  # hour 16 already has its packet
    assert calls == []


def test_a_marker_for_the_bar_from_the_fallback_stops_the_vm_building(tmp_path):
    calls = []
    fb = {"kind": "desk-wake", "packet_id": "DP-fallback", "bar": "2026-10-26T17:00:00Z",
          "posted_at": NEXT.isoformat()}
    produce(tmp_path, Net(markers=[fb]), build=lambda n, t: calls.append(1) or (None, "x"))
    assert calls == []


def test_failed_build_posts_no_wake_and_is_named(tmp_path):
    net = Net()
    rec = produce(tmp_path, net, build=lambda n, t: (None, "desk_scan_packet.py exit 1: REFUSED"))
    assert rec["state"] == "could_not_build" and "REFUSED" in rec["reason"] and net.posts == []


def test_refused_branch_write_posts_no_wake(tmp_path):
    net = Net()
    rec = produce(tmp_path, net, commit=lambda st, pid, a, h: (None, 403))
    assert rec["state"] == "could_not_commit" and rec["http_code"] == 403 and net.posts == []


def test_failed_comment_is_could_not_post_with_the_commit(tmp_path):
    net = Net()
    net.post_code = 500
    rec = produce(tmp_path, net)
    assert rec["state"] == "could_not_post" and rec["commit"] == "c" * 40


def test_build_attempts_are_bounded_per_bar(tmp_path):
    n = []
    for _ in range(dw.MAX_ATTEMPTS + 2):
        produce(tmp_path, Net(), build=lambda a, t: n.append(1) or (None, "boom"))
    assert len(n) == dw.MAX_ATTEMPTS


def test_no_credential_cannot_commit(tmp_path):
    assert produce(tmp_path, Net(), auth=None)["state"] == "could_not_commit"


def test_commit_packet_is_one_fast_forward_commit_never_forced(tmp_path):
    stage = make_stage(tmp_path)
    log = []
    def http(method, url, body, auth):
        log.append((method, url.split("/git/")[1], json.loads(body) if body else None))
        if method == "GET" and "/ref/" in url:
            return 200, {"object": {"sha": "h" * 40}}
        if method == "GET":
            return 200, {"tree": {"sha": "t" * 40}}
        if url.endswith("/blobs"):
            return 201, {"sha": f"b{len(log)}"}
        if url.endswith("/trees"):
            return 201, {"sha": "n" * 40}
        if url.endswith("/commits"):
            return 201, {"sha": "k" * 40}
        return 200, {}
    sha, code = dw.commit_packet(stage, "DP-20261026T1703Z-scan-1h", "Basic eA==", http)
    assert (sha, code) == ("k" * 40, None)
    patch = [e for e in log if e[0] == "PATCH"][0]
    assert patch[2] == {"sha": "k" * 40, "force": False} and patch[1] == "refs/heads/desk/decisions"
    tree = [e for e in log if e[1] == "trees"][0][2]
    assert sorted(e["path"] for e in tree["tree"]) == ["comms/desk/latest_scan.json",
                                                      "comms/desk/packets/DP-20261026T1703Z-scan-1h.json"]
    assert [e for e in log if e[1] == "commits" and e[0] == "POST"][0][2]["parents"] == ["h" * 40]


def test_commit_packet_retries_when_the_tip_moved_and_gives_up_on_other_errors(tmp_path):
    stage = make_stage(tmp_path)
    seq = {"patch": 0}
    def http(method, url, body, auth):
        if method == "GET" and "/ref/" in url:
            return 200, {"object": {"sha": "h" * 40}}
        if method == "GET":
            return 200, {"tree": {"sha": "t" * 40}}
        if method == "PATCH":
            seq["patch"] += 1
            return (422 if seq["patch"] == 1 else 200), {}
        return 201, {"sha": "x" * 40}
    assert dw.commit_packet(stage, "p", "a", http)[0] == "x" * 40 and seq["patch"] == 2
    assert dw.commit_packet(stage, "p", "a", lambda m, u, b, a: (403, None)) == (None, 403)


def test_kick_is_a_noop_off_the_live_trader():
    assert dw.kick() is False
