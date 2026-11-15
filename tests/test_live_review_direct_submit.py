"""TRADE-ACTION-DIRECT-PATH phase 2: a review row submitted DIRECTLY to the VM over HTTPS (no git).

Pins: the route fails closed on its token, validates shape, writes create-only (409 on a repeat), and its receipt
reads the watcher's log; the direct pass runs a row through the SAME process_row as a branch row (dispatch when a
mandate covers it, a Telegram ask when it needs the operator), once, and the branch pass never re-acts on a row the
direct pass handled (the git LOG copy); the dispatcher reads the row and evidence from --local-root before git;
the wake poster keeps a local evidence copy, create-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.runtime import live_review_rows as rows_lib
from src.runtime import live_review_rows_watch as w

TOKEN = "store-token"
NOW = datetime(2026, 11, 11, 22, 50, 13, tzinfo=timezone.utc)
RID = "LR-20261111T2243Z-pkg-462cfc59b2a1469b"


def _row(action="close", route="operator_ask", rid=RID):
    return {"review_id": rid, "order_package_id": rid.split("Z-", 1)[1], "leg": "ml_entry",
            "reviewed_at": "2026-11-11T22:50:10Z", "accounts": ["bybit_2"],
            "recommendation": {"action": action, "level": None, "basis": "ev_positive", "ev_delta_r": 0.35},
            "disposition": {"route": route}, "mechanics": {"verdict": "match"}, "packet_sha": "ab" * 32}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", TOKEN)
    monkeypatch.setattr(w, "direct_root", lambda: tmp_path / "direct")
    monkeypatch.setattr(w, "log_dir", lambda: tmp_path / "logs")
    from src.web.api import main
    return TestClient(main.app, raise_server_exceptions=False), tmp_path


def _post(client, body, token=TOKEN):
    h = {"X-Work-Store-Token": token} if token else {}
    return client.post("/api/bot/live-review/rows", content=json.dumps(body), headers=h)


# ─────────────────────────────────────────────── the route

def test_route_fails_closed(env, monkeypatch):
    client, _ = env
    assert _post(client, _row(), token=None).status_code == 401
    assert _post(client, _row(), token="wrong").status_code == 401
    monkeypatch.delenv("WORK_STORE_TOKEN")
    assert _post(client, _row()).status_code == 503


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.update(review_id="LR-bad"), "review_id"),
    (lambda r: r.pop("mechanics"), "missing: mechanics"),
    (lambda r: r.update(recommendation={}), "recommendation"),
    (lambda r: r.update(order_package_id="pkg-0000000000000000"), "order_package_id"),
])
def test_route_refuses_a_bad_shape(env, mutate, needle):
    client, _ = env
    body = _row()
    mutate(body)
    r = _post(client, body)
    assert r.status_code == 400 and needle in r.json()["detail"]


def test_route_writes_create_only_and_the_receipt_follows(env):
    client, tmp = env
    r = _post(client, _row())
    assert r.status_code == 201 and r.json()["state"] == "accepted"
    f = tmp / "direct" / rows_lib.row_path(RID)
    assert json.loads(f.read_text())["review_id"] == RID
    assert _post(client, _row()).status_code == 409                  # same review_id again
    rec = client.get(f"/api/bot/live-review/rows/{RID}").json()
    assert rec["state"] == "pending" and rec["readState"] == "absent" and rec["submitted_direct"] is True
    (tmp / "logs").mkdir(parents=True, exist_ok=True)
    (tmp / "logs" / "rows_watch.jsonl").write_text(json.dumps({"review_id": RID, "verdict": "advice_only",
                                                               "source": "direct"}) + "\n")
    rec = client.get(f"/api/bot/live-review/rows/{RID}").json()
    assert rec["state"] == "handled" and rec["receipt"]["verdict"] == "advice_only"


def test_route_refuses_a_row_the_branch_pass_already_handled(env):
    client, tmp = env
    (tmp / "logs").mkdir(parents=True)
    (tmp / "logs" / "rows_watch_state.json").write_text(json.dumps({"seen": [RID]}))
    assert _post(client, _row()).status_code == 409


# ─────────────────────────────────────────────── the direct pass

def _write_direct(root: Path, row):
    p = root / rows_lib.row_path(row["review_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(row))


def _pass(tmp_path, **kw):
    calls, offers = [], []
    st = w.run_direct_pass(dispatch=lambda rid: calls.append(rid) or {"exit": 0, "verdict": "dispatched"},
                           now_fn=lambda: NOW, logs=tmp_path / "logs", root=tmp_path / "direct",
                           alert=lambda t: True,
                           offer=lambda row, v: offers.append((row["review_id"], v)) or {"state": "offered"}, **kw)
    lines = [json.loads(x) for x in (tmp_path / "logs" / "rows_watch.jsonl").read_text().splitlines()] \
        if (tmp_path / "logs" / "rows_watch.jsonl").exists() else []
    return st, calls, offers, lines


def test_direct_operator_row_gets_an_ask_once_with_latency(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_proof", lambda fn: None)
    _write_direct(tmp_path / "direct", _row())
    st, calls, offers, lines = _pass(tmp_path)
    # an operator_ask row is never dispatched; since advice-only ended (2026-11-14) its verdict is not_dispatchable
    assert calls == [] and offers == [(RID, "not_dispatchable")] and st["handled"] == 1
    assert lines[0]["source"] == "direct" and lines[0]["approval"] == {"state": "offered"}
    assert lines[0]["reviewed_to_seen_s"] == 3.0
    st2, calls2, offers2, lines2 = _pass(tmp_path)
    assert st2["handled"] == 0 and offers2 == [] and len(lines2) == 1


def test_direct_mandate_row_is_dispatched(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_proof", lambda fn: None)
    monkeypatch.setattr(w, "dispatchable", lambda row, auto=None: None)   # as if a mandate covers it
    monkeypatch.setattr(w.ltr_auto_mandate, "exception_for", lambda row: None)
    _write_direct(tmp_path / "direct", _row(route="recommended"))
    _, calls, offers, lines = _pass(tmp_path)
    assert calls == [RID] and offers == [] and lines[0]["verdict"] == "dispatched"


def test_direct_and_branch_passes_never_both_act(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_proof", lambda fn: None)
    _write_direct(tmp_path / "direct", _row())
    _pass(tmp_path)
    # the branch pass later sees the git LOG copy of the same row: it must not act on it
    logs = tmp_path / "logs"
    (logs / "rows_watch_state.json").write_text(json.dumps({"seeded_at": NOW.isoformat(), "seen": [],
                                                            "pending": {}, "tip_rows": 0}))
    monkeypatch.setattr(rows_lib, "read_at", lambda tip, git: {"state": "ok", "rows": [_row()], "legacy_rows": 0,
                                                               "file_rows": 1, "bad_lines": 0, "bad_files": []})
    st = w.run_pass(git=lambda *a, **k: (0, "tip"), dispatch=lambda rid, tip: pytest.fail("must not dispatch"),
                    now_fn=lambda: NOW, logs=logs, alert=lambda t: True,
                    offer=lambda row, v: pytest.fail("must not re-offer"))
    assert st["new"] == 0
    # and a row the branch pass handled is skipped by the direct pass
    other = _row(rid="LR-20261111T2235Z-pkg-6df5f9dfb83e47b8")
    state = json.loads((logs / "rows_watch_state.json").read_text())
    state["seen"].append(other["review_id"])
    (logs / "rows_watch_state.json").write_text(json.dumps(state))
    _write_direct(tmp_path / "direct", other)
    st2, calls, offers, _ = _pass(tmp_path)
    assert st2["handled"] == 0 and calls == [] and offers == []


def test_a_malformed_direct_file_is_refused_once(tmp_path, monkeypatch):
    p = tmp_path / "direct" / rows_lib.ROWS_DIR / f"{RID}.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    st, calls, offers, lines = _pass(tmp_path)
    assert st["bad"] == [f"{RID}.json"] and lines[0]["verdict"] == "refused" and calls == offers == []
    st2, *_ = _pass(tmp_path)
    assert st2["bad"] == []


# ─────────────────────────────────────────────── dispatcher local roots + the wake poster's local copy

def test_dispatcher_reads_local_roots_before_git(tmp_path, monkeypatch):
    from scripts.ops import live_review_dispatch as lrd
    (tmp_path / "a" / "x").mkdir(parents=True)
    (tmp_path / "a" / "x" / "f.json").write_text("local")
    monkeypatch.setattr(lrd, "LOCAL_ROOTS", [tmp_path / "a"])
    assert lrd._committed_text("x/f.json") == "local"
    assert lrd._local_text("../etc/passwd") is None
    monkeypatch.setattr(lrd, "LOCAL_ROOTS", [])
    assert lrd._local_text("x/f.json") is None


def test_wake_poster_keeps_a_create_only_local_evidence_copy(tmp_path):
    from src.runtime import live_review_wake_post as wp

    class _Wake:
        @staticmethod
        def evidence_files(b):
            return [("comms/live_review/packets/LR-1.json", b"packet"), ("../escape.json", b"x")]

    bundles = {"pkg-1": {"state": "built"}, "pkg-2": {"state": "skipped"}}
    assert wp.keep_local_evidence(_Wake, bundles, root=tmp_path) == 1
    assert (tmp_path / "comms/live_review/packets/LR-1.json").read_bytes() == b"packet"
    assert not (tmp_path.parent / "escape.json").exists()
    assert wp.keep_local_evidence(_Wake, bundles, root=tmp_path) == 0      # never overwritten
