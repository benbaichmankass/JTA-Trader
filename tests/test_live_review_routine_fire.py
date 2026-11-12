"""TRADE-ACTION-DIRECT-PATH phase 3: the live-review routine fire (src/runtime/live_review_routine_fire.py).

Batching, dedupe, the 429 / failure fallback (one flag per incident) and not_configured.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import live_review_routine_fire as rf

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
ENV = {rf.ENV_TOKEN: "sk-ant-oat01-TESTONLY", rf.ENV_ID: "trig_TEST"}


def _entry(pkg: str, level: str = "-0.5R", event: str = "adverse_r", evidence: str = "committed") -> dict:
    return {"order_package_id": pkg, "leg": "x", "symbol": "ETHUSDT", "accounts": ["bybit_2"], "event": event,
            "level": level, "why": "w", "due_at": (T0 - timedelta(seconds=30)).isoformat(),
            "review_id": f"LR-20261112T1000Z-{pkg}", "packet_sha": "a" * 64, "evidence_state": evidence}


def _bundles(*pkgs: str) -> dict:
    return {p: {"state": "built", "packet_sha": "a" * 64, "packet": {"review_id": f"LR-{p}"}, "table": None,
                "table_path": None} for p in pkgs}


class Poster:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, body, headers):
        self.calls.append((url, json.loads(body), headers))
        return self.responses.pop(0)


OK = (200, {"type": "routine_fire", "claude_code_session_id": "session_A",
            "claude_code_session_url": "https://claude.ai/code/session_A"}, {})


@pytest.fixture()
def paths(tmp_path):
    return {"log_path": tmp_path / "fires.jsonl", "state_file": tmp_path / "fire_state.json"}


def _fire(entries, poster, paths, sent=None, env=ENV, now=T0):
    return rf.fire(entries, _bundles(*{e["order_package_id"] for e in entries}), now_fn=lambda: now, env=env,
                   post=poster, send=(sent.append if sent is not None else (lambda t: True)), **paths)


def test_not_configured_is_inert(paths):
    poster = Poster()
    for env in ({}, {rf.ENV_TOKEN: "x"}, {rf.ENV_ID: "trig_x"}, {rf.ENV_TOKEN: " ", rf.ENV_ID: "trig_x"}):
        es = [_entry("pkg-0000000000000001")]
        out = _fire(es, poster, paths, env=env)
        assert out == {"state": "not_configured"}
        assert "routine_fire" not in es[0]  # the comment path renders exactly as before
    assert poster.calls == []
    assert not paths["log_path"].exists()


def test_batches_every_due_package_into_one_fire(paths):
    poster = Poster(OK)
    es = [_entry("pkg-0000000000000001"), _entry("pkg-0000000000000002"),
          _entry("pkg-0000000000000002", event="mandate_cadence", level="2026-11-12T10:00Z")]
    out = _fire(es, poster, paths)
    assert out["state"] == "fired" and out["session_id"] == "session_A"
    assert len(poster.calls) == 1
    url, body, headers = poster.calls[0]
    assert url == "https://api.anthropic.com/v1/claude_code/routines/trig_TEST/fire"
    assert headers["Authorization"] == "Bearer sk-ant-oat01-TESTONLY"
    assert headers["anthropic-version"] == rf.ANTHROPIC_VERSION
    doc = json.loads(body["text"])
    assert len(doc["entries"]) == 3
    assert set(doc["packets"]) == {"pkg-0000000000000001", "pkg-0000000000000002"}
    assert all(e["routine_fire"]["state"] == "fired" for e in es)
    line = json.loads(paths["log_path"].read_text().strip())
    assert line["state"] == "fired" and line["session_id"] == "session_A" and len(line["keys"]) == 3
    assert line["due_to_fire_s"] == 30.0
    assert "TESTONLY" not in paths["log_path"].read_text()  # the token never reaches the log


def test_dedupe_one_fire_per_package_event_level(paths):
    poster = Poster(OK, OK)
    _fire([_entry("pkg-0000000000000001")], poster, paths)
    es = [_entry("pkg-0000000000000001")]
    out = _fire(es, poster, paths)
    assert out["state"] == "nothing_to_fire"
    assert es[0]["routine_fire"]["state"] == "already_fired"
    assert es[0]["routine_fire"]["session_id"] == "session_A"
    assert len(poster.calls) == 1
    # a new due level of the same package is a new fire
    out = _fire([_entry("pkg-0000000000000001", level="-1.0R")], poster, paths)
    assert out["state"] == "fired" and len(poster.calls) == 2


def test_entry_without_evidence_on_branch_is_not_fired(paths):
    poster = Poster(OK)
    es = [_entry("pkg-0000000000000001", evidence="could_not_commit"), _entry("pkg-0000000000000002")]
    out = _fire(es, poster, paths)
    assert out["not_fired_no_evidence"] == ["pkg-0000000000000001|adverse_r|-0.5R"]
    assert es[0]["routine_fire"]["state"] == "not_fired_no_evidence"
    assert len(json.loads(poster.calls[0][1]["text"])["entries"]) == 1


def test_429_falls_back_flags_once_and_backs_off(paths):
    sent: list = []
    poster = Poster((429, {"type": "error", "error": {"type": "rate_limit_error"}}, {"retry-after": "600"}))
    es = [_entry("pkg-0000000000000001")]
    out = _fire(es, poster, paths, sent)
    assert out["state"] == "rate_limited"
    assert es[0]["routine_fire"]["state"] == "rate_limited"  # stays on the comment path
    assert len(sent) == 1
    # inside Retry-After: no call, no second flag, still the fallback
    es2 = [_entry("pkg-0000000000000002")]
    out = _fire(es2, poster, paths, sent, now=T0 + timedelta(seconds=60))
    assert out["state"] == "rate_limited_backoff" and len(poster.calls) == 1 and len(sent) == 1
    assert es2[0]["routine_fire"]["state"] == "rate_limited_backoff"
    # a failed key was never fired: after the window it fires
    poster.responses.append(OK)
    out = _fire([_entry("pkg-0000000000000001")], poster, paths, sent, now=T0 + timedelta(seconds=700))
    assert out["state"] == "fired"
    st = json.loads(paths["state_file"].read_text())
    assert st["incident_open"] is False and st["retry_after_until"] is None


def test_failure_one_flag_per_incident_never_raises(paths):
    sent: list = []
    poster = Poster((500, {"type": "error", "error": {"type": "api_error"}}, {}),
                    (None, {"transport_error": "URLError"}, {}), OK,
                    (401, {"type": "error", "error": {"type": "authentication_error"}}, {}))
    out1 = _fire([_entry("pkg-0000000000000001")], poster, paths, sent)
    out2 = _fire([_entry("pkg-0000000000000001")], poster, paths, sent)
    assert (out1["state"], out2["state"]) == ("could_not_fire", "could_not_fire")
    assert "api_error" in out1["reason"] and "URLError" in out2["reason"]
    assert len(sent) == 1  # same incident
    assert _fire([_entry("pkg-0000000000000001")], poster, paths, sent)["state"] == "fired"
    assert _fire([_entry("pkg-0000000000000003")], poster, paths, sent)["state"] == "could_not_fire"
    assert len(sent) == 2  # a new incident after a success


def test_post_exception_is_contained(paths):
    def boom(*a):
        raise RuntimeError("x")
    es = [_entry("pkg-0000000000000001")]
    out = rf.fire(es, _bundles("pkg-0000000000000001"), now_fn=lambda: T0, env=ENV, post=boom,
                  send=lambda t: True, **paths)
    assert out["state"] == "fire_error"
    assert es[0]["routine_fire"]["state"] == "fire_error"


def test_text_stays_under_the_cap(paths):
    big = {"review_id": "LR-x", "blob": "z" * 40000}
    es = [_entry("pkg-0000000000000001"), _entry("pkg-0000000000000002")]
    bundles = {e["order_package_id"]: {"packet": big, "packet_sha": "a" * 64} for e in es}
    text = rf.build_text(es, bundles, T0)
    assert len(text) <= rf.MAX_TEXT_CHARS
    doc = json.loads(text)
    assert len(doc["packets"]) == 1 and len(doc["packet_omitted"]) == 1


def test_render_tells_the_manager_not_to_dispatch_fired_entries():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "lrw_rf", Path(__file__).resolve().parents[1] / "scripts/ops/live_review_wake.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    e1 = dict(_entry("pkg-0000000000000001"), routine_fire={"state": "fired", "session_id": "session_A"})
    e2 = dict(_entry("pkg-0000000000000002"), routine_fire={"state": "rate_limited", "reason": "429"})
    body = w.render({"kind": "wake", "entries": [e1]}, T0, "run")
    assert "do NOT dispatch" in body and "session_A" in body
    body = w.render({"kind": "wake", "entries": [e1, e2]}, T0, "run")
    assert "dispatch ONE Sonnet LIVE-REVIEW lane per package NOT marked" in body
    assert "routine fire `rate_limited`" in body
    # the marker still carries both keys, so the Actions poller's dedupe sees them as posted
    m = w.parse_markers([{"body": body}])[0]
    assert {w._key(e) for e in m["entries"]} == {w._key(e1), w._key(e2)}
