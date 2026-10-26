"""DESK-6: the VM-side desk-wake poster (src/runtime/desk_wake_post.py) and its gate."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import desk_wake_post as dw

# Monday 15:10Z: US equity cash session is open (DST months: 13:30-20:00 UTC).
MON = datetime(2026, 10, 26, 15, 10, tzinfo=timezone.utc)
# Saturday: equities and futures closed, crypto still trades.
SAT = datetime(2026, 10, 24, 12, 10, tzinfo=timezone.utc)
REAL_CALENDAR_EVENTS = dw._calendar_events
SECRET = "ghp_" + "x" * 36
AUTH = "Basic " + base64.b64encode(f"x-access-token:{SECRET}".encode()).decode()


def packet(venues=(("BTCUSDT", "bybit"),), items=(), near="read", desk=(), sb="read", db="read", cal=None):
    return {"universe": [{"symbol": s, "venue": v, "calendar": cal or {"read_state": "could_not_look", "events_next_bar": None}}
                         for s, v in venues],
            "system_book": {"read_state": sb, "near_signals_read_state": near, "items": None if sb != "read" else list(items)},
            "desk_book": {"read_state": db, "items": None if db != "read" else list(desk)}}


EQ = (("SPY", "alpaca"),)
OPEN_PKG = {"order_package_id": "p1", "leg": "x", "symbol": "SPY", "status": "open", "bars_to_signal": None}
NEAR = {"leg": "trend_x", "symbol": "SPY", "status": "near", "bars_to_signal": 1}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(dw, "_handled", {})
    monkeypatch.setattr(dw, "_cached_markers", [])
    monkeypatch.setattr(dw, "_last_kick", float("-inf"))
    monkeypatch.setattr(dw, "_calendar_events", lambda u, n: [])


def names(g):
    return [r["reason"] for r in g["reasons"]]


# ---- context is information, never a gate -------------------------------------

def test_context_counts_and_never_reads_unread_as_zero():
    c = dw.packet_context(packet(EQ, items=[OPEN_PKG, NEAR], desk=[{"decision_id": "d"}]), SAT)
    assert (c["open_positions"], c["near_signals"], c["open_desk_proposals"], c["unread"]) == (1, 1, 1, [])
    u = dw.packet_context(packet(EQ, sb="could_not_look", db="could_not_look"), SAT)
    assert u["open_positions"] is None and u["open_desk_proposals"] is None and u["near_signals"] is None
    assert u["unread"] == ["system_book", "desk_book"]
    n = dw.packet_context(packet(EQ, near="could_not_look"), SAT)
    assert n["near_signals"] is None and n["unread"] == ["near_signals"]


@pytest.mark.parametrize("bars,count", [(0, 1), (1, 1), (2, 0), (None, 0)])
def test_near_signal_count_is_within_one_bar(bars, count):
    assert dw.packet_context(packet(EQ, items=[dict(NEAR, bars_to_signal=bars)]), SAT)["near_signals"] == count


def test_calendar_events_are_recorded(monkeypatch):
    monkeypatch.setattr(dw, "_calendar_events", lambda u, n: ["SPY:fomc@x risk=0.80"])
    assert dw.packet_context(packet(EQ), SAT)["calendar_events"] == ["SPY:fomc@x risk=0.80"]


def test_packet_calendar_events_count():
    cal = {"read_state": "read", "events_next_bar": ["cpi"]}
    reasons = REAL_CALENDAR_EVENTS(packet(EQ, cal=cal)["universe"], SAT)
    assert reasons and "cpi" in reasons[0]


# ---- the pass -----------------------------------------------------------------

class Net:
    def __init__(self, pk, ptr_extra=None, comments=None, get_code=200, post_code=201, built_ago=timedelta(minutes=8),
                 now=MON, sha_ok=True, ptr_code=200, pk_code=200):
        built = now - built_ago
        self.ptr = {"packet_id": "DP-20261026T1503Z-scan-1h", "packet_sha": dw.packet_sha(pk) if sha_ok else "0" * 64,
                    "path": "comms/desk/packets/DP-x.json", "built_at": built.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "info_cutoff_at": (now - built_ago).strftime("%Y-%m-%dT%H:%M:%SZ"), **(ptr_extra or {})}
        self.pk, self.comments, self.get_code, self.post_code = pk, comments or [], get_code, post_code
        self.ptr_code, self.pk_code = ptr_code, pk_code
        self.calls = []

    def fetch(self, url, auth):
        self.calls.append(("GET", url))
        if "latest_scan" in url:
            return self.ptr_code, (self.ptr if self.ptr_code == 200 else None)
        return self.pk_code, (self.pk if self.pk_code == 200 else None)

    def http(self, method, url, body, auth):
        self.calls.append((method, url, body))
        if method == "GET":
            return self.get_code, (self.comments if self.get_code == 200 else None)
        return self.post_code, ({"html_url": "https://example/c/1"} if self.post_code == 201 else None)

    @property
    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def run(tmp_path, net, now=MON, auth=AUTH):
    rec = dw.run_once(fetch=net.fetch, auth_fn=lambda: auth, http=net.http, now_fn=lambda: now,
                      receipt=tmp_path / "r.json", pr_fn=lambda: 17895)
    on_disk = json.loads((tmp_path / "r.json").read_text())
    assert on_disk["state"] == rec["state"]
    assert SECRET not in json.dumps(on_disk) and "Basic" not in json.dumps(on_disk)
    return rec


def test_posts_one_marker_comment_with_bar_packet_and_context(tmp_path):
    net = Net(packet(EQ))
    rec = run(tmp_path, net)
    assert rec["state"] == "posted" and rec["context"]["unread"] == []
    assert len(net.posts) == 1
    body = json.loads(net.posts[0][2])["body"]
    m = dw.parse_markers([{"body": body}])[0]
    assert m["bar"] == "2026-10-26T15:00:00Z" and m["packet_id"] == net.ptr["packet_id"]
    assert m["packet_sha"] == net.ptr["packet_sha"] and m["context"]["open_positions"] == 0
    assert "Claude Code" in body and "trading-desk/SKILL.md" in body
    assert rec["last_post"]["comment_url"] == "https://example/c/1"


def test_wakes_every_bar_even_when_nothing_is_open_or_every_market_is_closed(tmp_path):
    net = Net(packet(EQ), now=SAT)
    rec = run(tmp_path, net, now=SAT)
    assert rec["state"] == "posted" and len(net.posts) == 1


def test_unread_books_still_post_and_say_so(tmp_path):
    net = Net(packet(EQ, sb="could_not_look", db="could_not_look"))
    rec = run(tmp_path, net)
    assert rec["state"] == "posted" and rec["context"]["unread"] == ["system_book", "desk_book"]


def test_missing_pointer_or_packet_is_could_not_look_never_a_silent_skip(tmp_path):
    for kw, frag in ((dict(ptr_code=404), "latest_scan unreadable"), (dict(pk_code=404), "unreadable (http 404)"),
                     (dict(sha_ok=False), "sha does not match")):
        net = Net(packet(EQ), **kw)
        rec = run(tmp_path, net)
        assert rec["state"] == "could_not_look" and frag in rec["reason"] and net.posts == []


def test_stale_packet_is_could_not_look(tmp_path):
    net = Net(packet(EQ), built_ago=timedelta(minutes=dw.PACKET_MAX_AGE_MIN + 5))
    rec = run(tmp_path, net)
    assert rec["state"] == "could_not_look" and rec["reason"].startswith("stale_packet") and net.posts == []


def test_dedupes_per_bar_across_markers(tmp_path):
    net = Net(packet(EQ))
    prior = {"body": "x\n<!-- desk-wake " + json.dumps({"bar": "2026-10-26T15:00:00Z", "packet_id": "other"}) + " -->"}
    net.comments = [prior]
    rec = run(tmp_path, net)
    assert rec["state"] == "already_posted" and net.posts == []


def test_second_pass_in_the_same_bar_does_not_repost_or_reread_comments(tmp_path):
    net = Net(packet(EQ))
    assert run(tmp_path, net)["state"] == "posted"
    n = len(net.calls)
    rec = run(tmp_path, net)
    assert rec["state"] == "already_posted" and len(net.posts) == 1
    assert [c for c in net.calls[n:] if c[0] == "GET" and "issues" in c[1]] == []
    assert rec["last_post"]["packet_id"] == net.ptr["packet_id"]  # evidence survives the later pass


def test_failed_post_is_retried_next_pass(tmp_path):
    net = Net(packet(EQ), post_code=500)
    assert run(tmp_path, net)["state"] == "could_not_post"
    net.post_code = 201
    assert run(tmp_path, net)["state"] == "posted"


def test_marker_read_failure_does_not_post(tmp_path):
    net = Net(packet(EQ), get_code=500)
    rec = run(tmp_path, net)
    assert rec["state"] == "could_not_post" and "dedupe unknown" in rec["reason"] and net.posts == []


def test_no_credential_is_could_not_post(tmp_path):
    net = Net(packet(EQ))
    rec = run(tmp_path, net, auth=None)
    assert rec["state"] == "could_not_post" and rec["reason"] == "no_credential_in_git_extraheader"


def test_kick_is_a_noop_off_the_live_trader():
    assert dw.kick() is False
