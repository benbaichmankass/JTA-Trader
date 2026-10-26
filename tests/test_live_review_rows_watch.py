"""LTR C1: the VM rows-branch watcher (src/runtime/live_review_rows_watch.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.runtime import live_review_rows_watch as w

T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
TIP = "a" * 40


def row(rid, action="tighten_sl", route="recommended"):
    return {"review_id": rid, "order_package_id": "pkg-1", "reviewed_at": "2026-10-26T11:59:00Z",
            "recommendation": {"action": action, "level": 1.0}, "disposition": {"route": route}}


class FakeGit:
    def __init__(self, rows, fetch_rc=0):
        self.rows, self.fetch_rc = rows, fetch_rc
        self.calls = []

    def __call__(self, *args, timeout=30):
        self.calls.append(args)
        if args[0] == "fetch":
            return self.fetch_rc, "fatal: unable to access" if self.fetch_rc else ""
        if args[0] == "rev-parse":
            return 0, TIP
        if args[0] == "show":
            return 0, "\n".join(json.dumps(r) for r in self.rows)
        return 1, "unexpected"


class FakeDispatch:
    def __init__(self, exits=None):
        self.exits = list(exits or [0])
        self.calls = []

    def __call__(self, rid, ref):
        self.calls.append((rid, ref))
        code = self.exits.pop(0) if len(self.exits) > 1 else self.exits[0]
        return {"exit": code, "verdict": "dispatched" if code in (0, 1) else "could_not_look",
                "detail": None, "lines": [">>> bybit_2 [real_money]: APPLIED level=1.0 executor=ok venue_after=1.0 — x"]}


def log(tmp_path):
    p = tmp_path / "rows_watch.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_first_pass_seeds_and_never_replays(tmp_path):
    d = FakeDispatch()
    st = w.run_pass(git=FakeGit([row("LR-old")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    assert st["seeded"] == 1 and d.calls == [] and log(tmp_path) == []
    w.run_pass(git=FakeGit([row("LR-old")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    assert d.calls == []


def test_a_new_tighten_is_dispatched_once_at_the_tip_with_latency(tmp_path):
    d = FakeDispatch()
    w.run_pass(git=FakeGit([]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    w.run_pass(git=FakeGit([row("LR-new")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    w.run_pass(git=FakeGit([row("LR-new")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    assert d.calls == [("LR-new", TIP)]
    (rec,) = log(tmp_path)
    assert rec["exit"] == 0 and rec["ref"] == TIP and rec["reviewed_to_done_s"] == 60.0
    assert "venue_after=1.0" in rec["lines"][0]


def test_non_tighten_and_operator_ask_rows_are_never_sent(tmp_path):
    d = FakeDispatch()
    w.run_pass(git=FakeGit([]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    w.run_pass(git=FakeGit([row("LR-h", action="hold"), row("LR-a", route="operator_ask")]),
               dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    assert d.calls == [] and [r["verdict"] for r in log(tmp_path)] == ["not_dispatchable"] * 2


def test_could_not_look_retries_then_expires(tmp_path):
    d = FakeDispatch(exits=[3])
    w.run_pass(git=FakeGit([]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    g = FakeGit([row("LR-r")])
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(minutes=5), logs=tmp_path)
    assert len(d.calls) == 2
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(hours=2), logs=tmp_path)
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(hours=3), logs=tmp_path)
    assert len(d.calls) == 3 and log(tmp_path)[-1]["verdict"] == "expired"


def test_a_failed_fetch_is_its_own_status_and_dispatches_nothing(tmp_path):
    d = FakeDispatch()
    st = w.run_pass(git=FakeGit([row("LR-x")], fetch_rc=128), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    assert st["fetch_state"] == "could_not_fetch" and d.calls == []
    assert json.loads((tmp_path / "rows_watch_status.json").read_text())["fetch_state"] == "could_not_fetch"


def test_fetch_uses_the_dispatchers_private_ref_and_no_fetch_head(tmp_path):
    g = FakeGit([])
    w.run_pass(git=g, dispatch=FakeDispatch(), now_fn=lambda: T0, logs=tmp_path)
    fetch = g.calls[0]
    assert "--no-write-fetch-head" in fetch and fetch[-1] == "+refs/heads/live-review/rows:refs/live-review/live-review/rows"


def test_ensure_started_is_live_trader_only():
    assert w.ensure_started() is False


import pytest as _pytest  # noqa: E402


@_pytest.fixture(autouse=True)
def _isolated_first_proof(tmp_path, monkeypatch):
    from src.runtime import ltr_first_proof as _fp
    monkeypatch.setattr(_fp, "state_path", lambda: tmp_path / "ltr_first_proof.json")
    monkeypatch.setattr(_fp, "_committed_reviews", lambda: [])
    monkeypatch.setattr(_fp, "_send", lambda text: True)
