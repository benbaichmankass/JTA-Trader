"""LTR-1B B2b: the VM-side ltr-wake poster (src/runtime/live_review_wake_post.py)."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import live_review_wake_post as post

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SECRET = "ghp_" + "x" * 36
AUTH = "Basic " + base64.b64encode(f"x-access-token:{SECRET}".encode()).decode()


def due(acct="bybit_2", event="r_milestone", level=1):
    return {"read_state": "looked", "due_count": 1, "generated_at": NOW.isoformat(),
            "due": [{"order_package_id": "pkg-1", "leg": "ada_pullback_2h", "symbol": "ADAUSDT",
                     "account_id": acct, "telemetry_updated_at": NOW.isoformat(),
                     "events": [{"event": event, "level": level, "why": "x"}]}]}


class FakeHttp:
    """The PR comments API plus a tiny in-memory rows branch behind the contents + git data APIs."""

    def __init__(self, comments=None, get_code=200, post_code=201, branch=None, patch_code=200):
        self.comments, self.get_code, self.post_code = comments or [], get_code, post_code
        self.branch = dict(branch or {})  # path -> bytes at the rows-branch tip
        self.patch_code = patch_code
        self.calls = []
        self._blobs, self._trees, self._staged = {}, {}, None

    def __call__(self, method, url, body, auth):
        self.calls.append((method, url, body, auth))
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            if path not in self.branch:
                return 404, None
            return 200, {"encoding": "base64", "content": base64.b64encode(self.branch[path]).decode()}
        if "/git/" in url:
            doc = json.loads(body) if body else None
            if url.endswith("/git/ref/heads/live-review/rows"):
                return 200, {"object": {"sha": "tip0"}}
            if "/git/commits/" in url:
                return 200, {"tree": {"sha": "tree0"}}
            if url.endswith("/git/blobs"):
                sha = f"blob{len(self._blobs)}"
                self._blobs[sha] = base64.b64decode(doc["content"])
                return 201, {"sha": sha}
            if url.endswith("/git/trees"):
                self._trees["tree1"] = {e["path"]: self._blobs[e["sha"]] for e in doc["tree"]}
                return 201, {"sha": "tree1"}
            if url.endswith("/git/commits"):
                self._staged = self._trees[doc["tree"]]
                return 201, {"sha": "c" * 40}
            if method == "PATCH":
                assert doc["force"] is False
                if self.patch_code == 200:
                    self.branch.update(self._staged)
                return self.patch_code, None
        if method == "GET":
            return self.get_code, (self.comments if self.get_code == 200 else None)
        return self.post_code, ({"html_url": "https://example/c/1"} if self.post_code == 201 else None)

    @property
    def posts(self):
        return [c for c in self.calls if c[0] == "POST" and "/comments" in c[1]]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(post, "_cached_markers", [])
    monkeypatch.setattr(post, "_last_kick", float("-inf"))
    monkeypatch.setattr(post, "_evidence_backoff_until", float("-inf"))


PACKET = {"review_id": "LR-20261026T1200Z-pkg-1", "order_package_id": "pkg-1", "state": {"open_r": 1.2}}
TABLE = {"read_state": "measured", "options": []}


def _sha(pk):
    return hashlib.sha256(json.dumps(pk, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def built(pkg):
    pk = dict(PACKET, order_package_id=pkg)
    return {"state": "built", "packet": pk, "packet_sha": _sha(pk),
            "table_path": f"comms/live_review/tables/{PACKET['review_id']}.json", "table": TABLE}


def run(tmp_path, doc, http, auth=AUTH, now=NOW, build=built):
    rec = post.run_once(due_fn=lambda: doc, auth_fn=lambda: auth, http=http,
                        now_fn=lambda: now, receipt=tmp_path / "r.json", build_bundle=build)
    on_disk = json.loads((tmp_path / "r.json").read_text())
    assert on_disk["state"] == rec["state"]
    assert SECRET not in json.dumps(on_disk) and "Basic" not in json.dumps(on_disk)
    return rec


def test_posts_once_with_the_poller_marker_and_latency(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, due(), http)
    assert rec["state"] == "posted" and rec["http_code"] == 201 and rec["latency_s"] >= 0
    assert rec["entries"] == ["pkg-1|r_milestone|1"]
    body = json.loads(http.posts[0][2])["body"]
    marks = post.wake_module().parse_markers([{"body": body}])
    assert marks[0]["entries"][0]["poster"] == "vm"
    assert http.posts[0][3] == AUTH  # header sent as read, only in the request
    # the next pass sees its own marker: no second post, no GitHub call
    http2 = FakeHttp()
    assert run(tmp_path, due(), http2)["state"] == "already_posted" and http2.calls == []


def test_a_poller_posted_key_is_not_reposted(tmp_path):
    wake = post.wake_module()
    p = wake.plan(due(), [], wake.load_cfg(), NOW - timedelta(minutes=1))
    http = FakeHttp(comments=[{"body": wake.render(p, NOW - timedelta(minutes=1), "run")}])
    assert run(tmp_path, due(), http)["state"] == "already_posted" and http.posts == []


def test_unlisted_account_and_daily_floor_never_post(tmp_path):
    http = FakeHttp()
    assert run(tmp_path, due(acct="oanda_practice"), http)["state"] == "nothing_due"
    assert run(tmp_path, due(event="daily_floor", level="2026-10-26"), http)["state"] == "nothing_due"
    assert http.calls == []


def test_could_not_post_keeps_the_http_code(tmp_path):
    rec = run(tmp_path, due(), FakeHttp(post_code=403))
    assert rec["state"] == "could_not_post" and rec["http_code"] == 403


def test_marker_read_failure_never_posts(tmp_path):
    http = FakeHttp(get_code=502)
    rec = run(tmp_path, due(), http)
    assert rec["state"] == "could_not_post" and rec["http_code"] == 502 and http.posts == []


def test_no_credential_is_could_not_post(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, due(), http, auth=None)
    assert rec["state"] == "could_not_post" and rec["reason"].startswith("no_credential") and http.calls == []


def test_due_could_not_look_is_its_own_state(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, {"read_state": "could_not_look", "reason": "db", "due_count": None}, http)
    assert rec["state"] == "due_could_not_look" and http.calls == []


def test_read_auth_header_parses_the_bootstrap_value(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=f"AUTHORIZATION: basic {AUTH.split()[1]}\n")
    monkeypatch.setattr(post.subprocess, "run", fake_run)
    assert post.read_auth_header() == AUTH
    assert SECRET not in " ".join(seen["cmd"])  # never on a command line
    monkeypatch.setattr(post.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=""))
    assert post.read_auth_header() is None


def test_kick_is_live_trader_only_throttled_and_single_flight(monkeypatch):
    assert post.kick() is False  # pytest is not `python -m src.main`
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(5)
    monkeypatch.setattr(post, "run_once", slow)
    assert post.kick(force=True) is True
    assert started.wait(5)
    monkeypatch.setattr(post, "_last_kick", float("-inf"))
    assert post.kick(force=True) is False  # single-flight: lock held
    release.set()
    for _ in range(100):
        if not post._LOCK.locked():
            break
        threading.Event().wait(0.02)
    assert post.kick(force=True) is True  # lock released
    assert post.kick(force=True) is False  # throttled inside MIN_INTERVAL_S


def test_a_failing_pass_is_contained(monkeypatch, tmp_path):
    monkeypatch.setattr(post, "receipt_path", lambda: tmp_path / "r.json")
    monkeypatch.setattr(post, "run_once", lambda: 1 / 0)
    post._LOCK.acquire()
    post._run_locked()  # must not raise
    assert not post._LOCK.locked()
    assert json.loads((tmp_path / "r.json").read_text())["state"] == "could_not_post"


def test_telemetry_write_kicks_and_survives_a_broken_kick(monkeypatch):
    from src.runtime import position_telemetry as pt
    calls = []
    monkeypatch.setattr(pt, "build_record", lambda **kw: None)
    monkeypatch.setattr(post, "kick", lambda: calls.append(1))
    assert pt.record_position_telemetry() is None and calls == [1]
    monkeypatch.setattr(post, "kick", lambda: 1 / 0)
    assert pt.record_position_telemetry() is None


def test_the_packet_and_table_ride_the_comment(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, due(), http)
    assert rec["packet_states"] == {"pkg-1": "built"}
    body = json.loads(http.posts[0][2])["body"]
    m = post.wake_module().parse_markers([{"body": body}])[0]["entries"][0]
    assert m["review_id"] == PACKET["review_id"] and m["packet_sha"] == _sha(PACKET)
    blob = body.split("<!-- ltr-packet pkg-1 -->\n```json\n", 1)[1].split("\n```", 1)[0]
    doc = json.loads(blob)
    assert doc["packet"]["review_id"] == PACKET["review_id"] and doc["table"] == TABLE
    assert len(body) < post.wake_module().MAX_BODY_CHARS


def test_a_packet_that_cannot_be_built_still_wakes(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, due(), http, build=lambda pkg: {"state": "could_not_build", "reason": "diag exit 3"})
    assert rec["state"] == "posted" and rec["packet_states"] == {"pkg-1": "could_not_build"}
    m = post.wake_module().parse_markers([{"body": json.loads(http.posts[0][2])["body"]}])[0]["entries"][0]
    assert m["packet_reason"] == "diag exit 3" and "packet_sha" not in m


def test_an_oversized_packet_is_omitted_not_truncated(tmp_path):
    big = lambda pkg: dict(built(pkg), table={"blob": "x" * 70000})  # noqa: E731
    http = FakeHttp()
    rec = run(tmp_path, due(), http, build=big)
    body = json.loads(http.posts[0][2])["body"]
    assert rec["state"] == "posted" and "ltr-packet" not in body and len(body) < 65536
    m = post.wake_module().parse_markers([{"body": body}])[0]["entries"][0]
    assert m["packet_state"] == "omitted_too_large"


import pytest as _pytest  # noqa: E402


@_pytest.fixture(autouse=True)
def _isolated_first_proof(tmp_path, monkeypatch):
    from src.runtime import ltr_first_proof as _fp
    monkeypatch.setattr(_fp, "state_path", lambda: tmp_path / "ltr_first_proof.json")
    monkeypatch.setattr(_fp, "_committed_reviews", lambda: [])
    monkeypatch.setattr(_fp, "_send", lambda text: True)


# ── LTR-PACKET-ECHO: the packet + table reach live-review/rows by machine, before the wake ──────────────
_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lrm_echo", _ROOT / "scripts/ops/live_review_rows_mirror.py")
lrm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lrm)
PKT_PATH = f"comms/live_review/packets/{PACKET['review_id']}.json"
TBL_PATH = f"comms/live_review/tables/{PACKET['review_id']}.json"


def test_evidence_is_committed_byte_exact_before_the_comment(tmp_path):
    http = FakeHttp()
    rec = run(tmp_path, due(), http)
    assert rec["state"] == "posted" and rec["evidence"]["pkg-1"] == {"state": "committed", "commit": "c" * 40}
    i_patch = next(i for i, c in enumerate(http.calls) if c[0] == "PATCH")
    i_post = next(i for i, c in enumerate(http.calls) if c[0] == "POST" and "/comments" in c[1])
    assert i_patch < i_post  # the evidence lands before the wake exists
    assert set(http.branch) == {PKT_PATH, TBL_PATH}
    # the generator's on-disk format (live_review_packet.py --write) and a sha the validator accepts
    assert http.branch[PKT_PATH] == (json.dumps(dict(PACKET, order_package_id="pkg-1"), indent=1, sort_keys=True) + "\n").encode()
    assert lrm.rules.packet_blob_problems({"review_id": PACKET["review_id"], "packet_sha": _sha(PACKET)},
                                          http.branch[PKT_PATH]) == []
    m = post.wake_module().parse_markers([{"body": json.loads(http.posts[0][2])["body"]}])[0]["entries"][0]
    assert m["evidence_state"] == "committed" and m["evidence_commit"] == "c" * 40 and m["packet_state"] == "built"


def test_a_machine_written_packet_is_accepted_by_the_mirror(tmp_path):
    """The row a reviewer writes (copying packet_sha) mirrors against the packet the poster committed."""
    http = FakeHttp()
    run(tmp_path, due(), http)
    rid = PACKET["review_id"]
    r = dict(lrm.rules.GOOD_REVIEW, review_id=rid, order_package_id="pkg-1", reviewed_at="2026-10-26T12:00:00Z",
             packet_sha=_sha(PACKET), outcome_table_source=TBL_PATH)
    files = dict(http.branch)
    files[lrm.REVIEWS] = (json.dumps(r) + "\n").encode()
    res = lrm.mirror(tmp_path, files.get)
    assert res["mirrored"] == 1 and res["skipped"] == [] and res["review_ids"] == [rid]
    assert (tmp_path / PKT_PATH).read_bytes() == http.branch[PKT_PATH]


def test_evidence_already_on_the_branch_is_not_rewritten(tmp_path):
    first = FakeHttp()
    run(tmp_path, due(), first)
    post._cached_markers = []
    again = FakeHttp(branch=first.branch)
    rec = run(tmp_path, due(), again)
    assert rec["state"] == "posted" and rec["evidence"]["pkg-1"]["state"] == "exists"
    assert not [c for c in again.calls if c[0] == "PATCH"]


def test_a_conflicting_file_is_never_overwritten_and_no_block_rides(tmp_path):
    http = FakeHttp(branch={PKT_PATH: b'{"someone":"else"}\n'})
    rec = run(tmp_path, due(), http)
    assert rec["state"] == "posted" and rec["packet_states"] == {"pkg-1": "evidence_conflict"}
    assert http.branch[PKT_PATH] == b'{"someone":"else"}\n' and not [c for c in http.calls if c[0] == "PATCH"]
    body = json.loads(http.posts[0][2])["body"]
    assert "ltr-packet" not in body  # no reviewer is started on evidence the branch does not carry


def test_a_failed_evidence_commit_posts_nothing_and_backs_off(tmp_path):
    http = FakeHttp(patch_code=403)
    rec = run(tmp_path, due(), http)
    assert rec["state"] == "could_not_post" and rec["reason"].startswith("evidence_commit_failed")
    assert rec["http_code"] == 403 and http.posts == []
    # inside the backoff: no rebuild, no GitHub call; the Actions poller covers the window
    http2 = FakeHttp()
    built_calls = []
    rec2 = run(tmp_path, due(), http2, build=lambda pkg: built_calls.append(pkg) or built(pkg))
    assert rec2["state"] == "evidence_backoff" and built_calls == [] and http2.posts == []


def test_the_actions_poller_lands_evidence_and_marks_a_failure_loudly():
    wake = post.wake_module()
    p = wake.plan(due(), [], wake.load_cfg(), NOW)
    bundles = {"pkg-1": built("pkg-1")}
    ev = wake.land_evidence(p, bundles, "token x", FakeHttp(patch_code=500))
    assert ev["pkg-1"]["state"] == "could_not_commit" and ev["pkg-1"]["http_code"] == 500
    body = wake.render(p, NOW, "run", bundles)
    assert "ltr-packet" not in body and "**could_not_commit**" in body
    assert wake.parse_markers([{"body": body}])[0]["entries"][0]["packet_state"] == "could_not_commit"
