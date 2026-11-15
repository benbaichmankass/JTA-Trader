"""WSD-S3-CLI-OUTBOX: scripts/ops/work.py against the REAL work_items router (FastAPI TestClient
mounted behind urllib), plus the outbox round trip and the drainer's trust rule."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from scripts.ops import work as cli

TOKEN = "t" * 32


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """Route the CLI's urllib calls into the real app."""
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "w.db"))
    monkeypatch.setenv("WORK_STORE_TOKEN", TOKEN)
    from src.web.api.main import app
    client = TestClient(app)
    calls = []

    class Resp(io.BytesIO):
        def __init__(self, status, body, headers):
            super().__init__(body)
            self.status, self.headers = status, headers

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        headers = dict(req.header_items())
        calls.append((req.get_method(), "/" + path, headers))
        r = client.request(req.get_method(), "/" + path, content=req.data, headers=headers)
        if r.status_code >= 400:
            raise urllib.error.HTTPError(req.full_url, r.status_code, "x", r.headers, io.BytesIO(r.content))
        return Resp(r.status_code, r.content, dict(r.headers))

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    return calls


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, (json.loads(out.out) if out.out.strip() else None), out.err


ADD = ["add", "WSD-CLI-1", "--kind", "build", "--title", "cli test", "--field", "roadmap=[\"L-OPS\"]",
       "--field", "due_rule={\"kind\":\"date\",\"due_date\":\"2026-11-09\"}", "--by", "test"]


def test_direct_add_set_note_close_reopen_history(api, capsys):
    rc, out, _ = _run(capsys, "--via", "direct", *ADD, "--op-id", "op-1")
    assert rc == 0 and out["via"] == "direct" and out["item"]["version"] == 1
    # the token travels in the dedicated header, never Authorization
    assert api[-1][2].get("X-work-store-token") == TOKEN and "Authorization" not in api[-1][2]
    rc, out, _ = _run(capsys, "--via", "direct", *ADD, "--op-id", "op-1")
    assert rc == 0 and out["replayed"] is True  # the same op_id is a no-op
    assert _run(capsys, "set", "WSD-CLI-1", "state=in_flight", "tier=1", "--by", "t")[1]["item"]["tier"] == 1
    assert _run(capsys, "note", "WSD-CLI-1", "a note", "--by", "t")[1]["item"]["version"] == 3
    assert _run(capsys, "close", "WSD-CLI-1", "--reason", "finished", "--by", "t")[1]["item"]["state"] == "done"
    item = _run(capsys, "reopen", "WSD-CLI-1", "--by", "t")[1]["item"]
    assert item["state"] == "queued" and item["terminal_reason"] is None
    hist = _run(capsys, "history", "WSD-CLI-1")[1]
    assert [e["op"] for e in hist["events"]] == ["create", "set", "note", "close", "set"] and hist["chain"]["ok"]


def test_a_409_is_reread_and_reapplied_once(api, capsys, monkeypatch):
    _run(capsys, "--via", "direct", *ADD)
    real = cli.get_item
    stale = {"n": 0}

    def get_stale(item_id):
        it = real(item_id)
        if stale["n"] == 0:
            stale["n"] += 1
            it = dict(it, version=it["version"] - 1 if it["version"] > 1 else 99)
        return it

    monkeypatch.setattr(cli, "get_item", get_stale)
    rc, out, _ = _run(capsys, "set", "WSD-CLI-1", "lane=x", "--by", "t")
    assert rc == 0 and out["item"]["lane"] == "x"


def test_refusal_is_the_answer_not_rerouted(api, capsys):
    rc, out, err = _run(capsys, "add", "BAD", "--kind", "build", "--title", "x", "--field", "due_at=\"2026-01-01\"",
                        "--by", "t")
    assert rc == 2 and out is None and "422" in err


def test_unreachable_falls_back_to_outbox_in_auto_only(monkeypatch, capsys):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(cli.urllib.request, "urlopen", boom)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    rc, out, _ = _run(capsys, *ADD)
    assert rc == 0 and out["via"] == "outbox" and out["posted"] is False and "connection refused" in out["direct_error"]
    o = cli.parse_outbox_comment(out["comment_body"])
    assert o["op"] == "create" and o["id"] == "WSD-CLI-1" and o["op_id"] == out["op_id"]
    rc, _, err = _run(capsys, "--via", "direct", *ADD)
    assert rc == 3 and "not reached" in err


def test_gateway_502_is_unreached_but_503_is_an_answer(monkeypatch):
    for code, unreached in ((502, True), (504, True), (503, False)):
        def fail(req, timeout=None, code=code):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b'{"detail":"d"}'))
        monkeypatch.setattr(cli.urllib.request, "urlopen", fail)
        if unreached:
            with pytest.raises(cli.Unreachable):
                cli.http("GET", "/x")
        else:
            assert cli.http("GET", "/x")[0] == 503


def test_outbox_comment_round_trip_and_malformed():
    o = cli.make_op("note", "R-1", {"text": "hi"}, "s", "op-9")
    assert cli.parse_outbox_comment(cli.outbox_comment(o)) == o
    assert cli.parse_outbox_comment("no marker here") is None
    with pytest.raises(cli.WorkError):
        cli.parse_outbox_comment(cli.OUTBOX_MARK + '\n```json\n{"op": "delete", "id": "x"}\n```')


def test_drain_applies_trusted_once_and_skips_untrusted(api, monkeypatch):
    ok = cli.make_op("create", "WSD-OUT-1", {"id": "WSD-OUT-1", "kind": "build", "title": "via outbox",
                                             "roadmap": ["L-OPS"], "due_rule": {"due_date": "2026-11-09"}}, "s", "op-out-1")
    evil = cli.make_op("create", "EVIL", {"id": "EVIL", "kind": "build", "title": "x"}, "s", "op-evil")
    comments = [
        {"id": 1, "body": cli.outbox_comment(ok), "author_association": "OWNER", "reactions": {"total_count": 0}},
        {"id": 2, "body": cli.outbox_comment(evil), "author_association": "NONE", "reactions": {"total_count": 0}},
        {"id": 3, "body": "chatter", "author_association": "OWNER", "reactions": {"total_count": 0}},
    ]
    posted = []

    def fake_gh(method, url, body=None):
        if method == "GET" and "/comments?" in url:
            return comments
        if method == "GET" and url.endswith("/reactions?per_page=100"):
            return [{"content": "rocket", "user": {"type": "Bot"}}]
        posted.append((method, url, body))
        if url.endswith("/reactions"):
            next(c for c in comments if f"/comments/{c['id']}/" in url)["reactions"]["total_count"] = 1
        return {}

    monkeypatch.setattr(cli, "_gh", fake_gh)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    out = cli.drain(7)
    assert [a["id"] for a in out["applied"]] == ["WSD-OUT-1"] and out["skipped_untrusted"] == 1
    assert ("POST", "https://api.github.com/repos/o/r/issues/comments/1/reactions", {"content": "rocket"}) in posted
    out2 = cli.drain(7)  # the rocket marks it done: a second drain applies nothing
    assert out2["applied"] == [] and out2["already_done"] == 1


# ── WORK-SET-ROUTE-TRAP: a set that gives an observation an owner/parent also routes it ──────────


def _obs(legacy="queued", **kw):
    return {"id": "PI-X", "kind": "observation", "extra": {"_legacy_state": legacy, "_source": "pipeline",
                                                           "_absent": ["tier"]}, **kw}


def test_route_fields_flips_legacy_state_on_parent_and_keeps_extra():
    out = cli.route_fields(_obs(), {"parent_id": "ROW-A", "owner": "AM-OPS"})
    assert out["extra"] == {"_legacy_state": "routed", "_source": "pipeline", "_absent": ["tier"],
                            "routed_to": "ROW-A"}
    assert out["parent_id"] == "ROW-A" and out["owner"] == "AM-OPS"


def test_route_fields_owner_alone_routes_to_the_owner():
    out = cli.route_fields(_obs("due"), {"owner": "research-ops"})
    assert out["extra"]["_legacy_state"] == "routed" and out["extra"]["routed_to"] == "research-ops"


@pytest.mark.parametrize("item,fields", [
    ({"id": "B", "kind": "build", "extra": {"_legacy_state": "queued"}}, {"owner": "x"}),  # builds: no routing
    (_obs("routed"), {"owner": "x"}),                       # already routed: untouched
    (_obs("done"), {"owner": "x"}),                         # terminal legacy word: untouched
    (_obs(), {"state": "blocked"}),                         # no owner/parent in the set
    (_obs(), {"owner": None}),                              # clearing the owner never routes
    (_obs(), {"owner": "x", "extra": {"k": 1}}),            # caller sets extra itself: theirs wins
])
def test_route_fields_leaves_other_sets_alone(item, fields):
    assert cli.route_fields(item, fields) is fields


def test_route_fields_routed_item_leaves_the_unrouted_count():
    """The due condition, end to end over the real projection + pipeline.unrouted."""
    from scripts.ops import pipeline
    from src.runtime.work_store_import import to_pipeline_item
    item = {"id": "PI-20261113-ROUTE-0001", "kind": "observation", "state": "queued", "parent_id": None,
            "owner": "manager", "title": "t", "due_at": "2026-11-01T00:00:00Z",
            "due_rule": {"kind": "observation", "check_every_days": 7, "clears_when": "x"},
            "origin": {"kind": "test", "ref": "r", "rerun": "true"},
            "extra": {"_legacy_state": "queued", "_source": "pipeline"}}
    before = pipeline.unrouted([to_pipeline_item(item)])
    routed = {**item, **cli.route_fields(item, {"owner": "research-ops"})}
    after = pipeline.unrouted([to_pipeline_item(routed)])
    assert [i["id"] for i in before] == [item["id"]] and after == []


def test_cli_set_owner_routes_through_the_api(api, capsys):
    rc, _, err = _run(capsys, "add", "PI-20261113-ROUTE-0002", "--kind", "observation", "--title", "t",
                      "--field", "extra={\"_legacy_state\":\"queued\",\"_source\":\"pipeline\"}",
                      "--field", "origin={\"kind\":\"session\",\"ref\":\"r\",\"rerun\":\"true\"}",
                      "--field", "due_rule={\"kind\":\"observation\",\"check_every_days\":7,\"clears_when\":\"x\"}",
                      "--field", "next_action=check_observation", "--by", "test")
    assert rc == 0, err
    rc, out, err = _run(capsys, "--via", "direct", "set", "PI-20261113-ROUTE-0002", "owner=research-ops",
                        "--by", "test")
    assert rc == 0, err
    assert out["item"]["extra"]["_legacy_state"] == "routed"
    assert out["item"]["extra"]["routed_to"] == "research-ops"
