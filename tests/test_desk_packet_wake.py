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
def _reset(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(dw, "_attempts", {})
    # The producer tests below model a wake on every bar; the cadence tests set their own N.
    cfg = tmp_path_factory.mktemp("cadence") / "desk_triggers.yaml"
    cfg.write_text("scan_wake_every_h: 1\n")
    monkeypatch.setattr(dw.marker_module(), "CONFIG", cfg)


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


def test_latency_is_never_negative():
    """MEASURED -59.8 s on 2026-10-28: built_at = max(clock, info_cutoff_at) can sit after the post."""
    t = NOW
    assert dw.latency_s(t, t + timedelta(seconds=59.8)) == 0.0
    assert dw.latency_s(t + timedelta(seconds=90), t) == 90.0
    assert dw.latency_s(None, t) is None and dw.latency_s(t, None) is None


def test_posted_marker_before_built_at_reads_zero_latency(tmp_path):
    rec = run(tmp_path, Net(built_ago=timedelta(minutes=4), markers=[posted(at=NOW - timedelta(minutes=5))]))
    assert rec["state"] == "posted" and rec["latency_s"] == 0.0


# ---- scan_wake_every_h: the packet lands every hour, the wake only on N-hour bars (operator 2026-10-30) -------

ODD = datetime(2026, 10, 26, 17, 3, tzinfo=timezone.utc)  # hour 17: odd -> no wake at every 2 h


@pytest.fixture
def every_2h(_reset):
    dw.marker_module().CONFIG.write_text("scan_wake_every_h: 2\n")


def test_cadence_wakes_even_utc_hours_only():
    mm = dw.marker_module()
    assert [h for h in range(24) if mm.wake_due(f"2026-10-26T{h:02d}:00:00Z", 2)] == list(range(0, 24, 2))
    assert all(mm.wake_due(f"2026-10-26T{h:02d}:00:00Z", 1) for h in range(24))


def test_cadence_is_read_live_from_config_and_a_fault_wakes_every_hour(tmp_path):
    mm = dw.marker_module()
    cfg = tmp_path / "c.yaml"
    cfg.write_text("scan_wake_every_h: 3\n")
    assert mm.scan_wake_every_h(cfg) == 3
    cfg.write_text("scan_wake_every_h: 4\n")
    assert mm.scan_wake_every_h(cfg) == 4
    cfg.write_text("scan_wake_every_h: 0\n")
    assert mm.scan_wake_every_h(cfg) == 1
    cfg.write_text(": : not yaml [")
    assert mm.scan_wake_every_h(cfg) == 1
    assert mm.scan_wake_every_h(tmp_path / "missing.yaml") == 1
    assert mm.scan_wake_every_h(mm.ROOT / "config" / "desk_triggers.yaml") == 2  # the shipped config


def test_odd_hour_lands_the_packet_but_posts_no_wake(tmp_path, every_2h):
    net = Net()
    committed = []
    rec = produce(tmp_path, net, now=ODD, commit=lambda st, pid, a, h: committed.append(pid) or ("c" * 40, None))
    assert committed == ["DP-20261026T1703Z-scan-1h"]  # the data is kept
    assert rec["state"] == "skipped_by_cadence" and rec["every_h"] == 2 and rec["bar"] == "2026-10-26T17:00:00Z"
    assert net.posts == []


def test_skipped_hour_is_not_wake_missing_on_later_passes(tmp_path, every_2h):
    def later(hour):  # the hour's packet landed at :31, nothing else since; the pass is 24 min later
        net = Net()
        net.ptr.update(info_cutoff_at=f"2026-10-26T{hour}:31:00Z", built_at=f"2026-10-26T{hour}:31:30Z")
        return run(tmp_path, net, now=datetime(2026, 10, 26, int(hour), 55, tzinfo=timezone.utc))
    rec = later("15")  # odd bar: no marker, no row, past the grace -> skipped by design
    assert rec["state"] == "skipped_by_cadence" and rec["bar"] == "2026-10-26T15:00:00Z"
    assert later("14")["state"] == "wake_missing"  # the same age on an even bar IS a missing wake


def test_workflow_post_step_skips_an_odd_bar(tmp_path, capsys, every_2h):
    mm = dw.marker_module()
    stage = make_stage(tmp_path)
    assert mm.main(["post", "--stage", str(stage), "--commit", "c" * 40]) == 0
    assert "skipped_by_cadence" in capsys.readouterr().out


# ---- TRIGGER-FIRST-REVIEWS (operator 2026-10-31): a scan wake bar wakes only on a material change ------------------

def _pk(open_ids=(), near=(), px=None, atr=2.0, near_read="read"):
    items = [{"order_package_id": i, "leg": "l", "symbol": "BTCUSDT", "status": "open", "bars_to_signal": None}
             for i in open_ids]
    items += [{"order_package_id": None, "leg": lg, "symbol": s, "side": "long", "status": "near_signal",
               "bars_to_signal": 1} for lg, s in near]
    uni = [{"symbol": s, "tier": "full", "last_close": p, "atr": atr} for s, p in (px or {"BTCUSDT": 100.0}).items()]
    return {"universe": uni, "system_book": {"read_state": "read", "near_signals_read_state": near_read, "items": items},
            "desk_book": {"read_state": "read", "items": []}}


@pytest.fixture
def gate_on(_reset):
    dw.marker_module().CONFIG.write_text("scan_wake_every_h: 1\nscan_wake_min_move_atr: 0.5\n")


def _fp(**kw):
    return dw.marker_module().packet_fingerprint(_pk(**kw))


def test_material_change_rules():
    mm = dw.marker_module()
    base = _fp(open_ids=["a"])
    assert mm.material_change(base, base, 0.5)[0] is False                       # identical: nothing new
    assert mm.material_change(_fp(open_ids=["a"], px={"BTCUSDT": 100.9}), base, 0.5)[0] is False   # 0.45 ATR
    wake, why = mm.material_change(_fp(open_ids=["a"], px={"BTCUSDT": 101.0}), base, 0.5)          # 0.5 ATR: at threshold
    assert wake and "moved 0.50 ATR" in why
    assert mm.material_change(_fp(open_ids=["a", "b"]), base, 0.5)[1].startswith("open-position change")
    assert mm.material_change(_fp(open_ids=["a"], near=[("x", "ETHUSDT")]), base, 0.5)[1].startswith("new near-signal")
    with_near = _fp(open_ids=["a"], near=[("x", "ETHUSDT")])
    assert mm.material_change(with_near, with_near, 0.5)[0] is False             # an already-woken near-signal is not new
    assert mm.material_change(base, None, 0.5)[0] and mm.material_change(base, base, None)[0]      # unknowns wake
    assert mm.material_change(_fp(open_ids=["a"], near_read="could_not_look"), base, 0.5)[0]        # unread book wakes
    assert mm.material_change(_fp(open_ids=["a"], atr=None), base, 0.5)[1].endswith("move unmeasurable")


def _woken_marker(fp, pid="DP-prev", bar="2026-10-26T16:00:00Z"):
    return dict(posted(pid, NEXT - timedelta(hours=1)), bar=bar, context={"fingerprint": fp})


def _produce_pk(tmp_path, net, pk):
    stage = make_stage(tmp_path)
    (stage / "comms/desk/packets/DP-20261026T1703Z-scan-1h.json").write_text(json.dumps(pk))
    return dw.run_once(fetch=net.fetch, auth_fn=lambda: "Basic eA==", http=net.http, now_fn=lambda: NEXT,
                       receipt=tmp_path / "r.json", pr_fn=lambda: 17895, build_fn=lambda n, t: (stage, None),
                       commit_fn=lambda st, pid, a, h: ("c" * 40, None))


def test_unchanged_packet_lands_but_posts_no_wake(tmp_path, gate_on):
    net = Net(markers=[_woken_marker(_fp(open_ids=["a"]))])
    rec = _produce_pk(tmp_path, net, _pk(open_ids=["a"], px={"BTCUSDT": 100.4}))
    assert rec["state"] == "skipped_nothing_new" and net.posts == [] and "nothing new" in rec["reason"]
    assert rec["last_skipped"]["packet_id"] == "DP-20261026T1703Z-scan-1h"


def test_changed_packet_still_wakes_and_carries_its_fingerprint(tmp_path, gate_on):
    net = Net(markers=[_woken_marker(_fp(open_ids=["a"]))])
    rec = _produce_pk(tmp_path, net, _pk(open_ids=["a"], px={"BTCUSDT": 101.5}))
    assert rec["state"] == "posted" and len(net.posts) == 1
    m = dw.marker_module().parse_markers([{"body": json.loads(net.posts[0][2])["body"]}])[0]
    assert m["context"]["fingerprint"]["px"] == {"BTCUSDT": 101.5}


def test_first_wake_with_no_prior_fingerprint_posts(tmp_path, gate_on):
    rec = _produce_pk(tmp_path, Net(markers=[posted("DP-old", NEXT - timedelta(hours=2))]), _pk(open_ids=["a"]))
    assert rec["state"] == "posted"                                               # an older marker without a fingerprint


def test_nothing_new_skip_is_not_reported_as_a_missing_wake_on_later_passes(tmp_path, gate_on):
    net = Net(markers=[_woken_marker(_fp(open_ids=["a"]))])
    _produce_pk(tmp_path, net, _pk(open_ids=["a"]))
    later = Net(markers=net.markers, built_ago=timedelta(minutes=30))
    later.ptr.update(packet_id="DP-20261026T1703Z-scan-1h", info_cutoff_at="2026-10-26T17:03:00Z",
                     built_at="2026-10-26T17:03:30Z")
    rec = dw.run_once(fetch=later.fetch, auth_fn=lambda: None, http=later.http,
                      now_fn=lambda: NEXT + timedelta(minutes=30), receipt=tmp_path / "r.json", pr_fn=lambda: 17895)
    assert rec["state"] == "skipped_nothing_new"


def test_workflow_post_step_skips_an_unchanged_packet(tmp_path, capsys, gate_on, monkeypatch):
    mm = dw.marker_module()
    stage = make_stage(tmp_path)
    (stage / "comms/desk/packets/DP-20261026T1703Z-scan-1h.json").write_text(json.dumps(_pk(open_ids=["a"])))
    body = mm.render_wake(dict(bar="2026-10-26T16:00:00Z", packet_id="DP-prev", packet_sha="x" * 64, path="p",
                               built_at="t", commit="c" * 40, poster="vm",
                               context=dict(open_positions=1, open_desk_proposals=0, near_signals=0, calendar_events=[],
                                            unread=[], fingerprint=_fp(open_ids=["a"]))), NOW)
    monkeypatch.setattr(mm, "_read_markers", lambda repo, pr: mm.parse_markers([{"body": body}]))
    monkeypatch.setattr("live_review_wake.ops_flags_pr", lambda: 17895, raising=False)
    assert mm.main(["post", "--stage", str(stage), "--commit", "c" * 40, "--pr", "17895", "--live"]) == 0
    assert "skipped_nothing_new" in capsys.readouterr().out
