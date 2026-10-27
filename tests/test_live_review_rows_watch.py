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
    """The rows branch at TIP: legacy ``reviews.jsonl`` lines (``rows``, or raw ``text``) plus per-row
    files (``files``: rows written as comms/live_review/rows/<review_id>.json)."""

    def __init__(self, rows, fetch_rc=0, files=(), text=None, tip=TIP):
        self.rows, self.fetch_rc, self.tip = rows, fetch_rc, tip
        self.text = text if text is not None else "\n".join(json.dumps(r) for r in rows)
        self.blobs = {f"blob-{r['review_id']}-{hash(json.dumps(r, sort_keys=True))}": r for r in files}
        self.calls = []

    def __call__(self, *args, timeout=30):
        self.calls.append(args)
        if args[0] == "fetch":
            return self.fetch_rc, "fatal: unable to access" if self.fetch_rc else ""
        if args[0] == "rev-parse":
            return 0, self.tip
        if args[0] == "ls-tree":
            return 0, "\n".join(f"100644 blob {b}\tcomms/live_review/rows/{r['review_id']}.json"
                                for b, r in self.blobs.items())
        if args[0] == "cat-file" and args[1] == "blob":
            return 0, json.dumps(self.blobs[args[2]], indent=1)
        if args[0] == "show":
            return 0, self.text
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


# ---- LTR-ROWS-SWAP-TRUNCATION: per-row files, and a shrunken tip is refused --------------------

def test_a_per_row_file_is_applied_exactly_once(tmp_path):
    d = FakeDispatch()
    w.run_pass(git=FakeGit([row("LR-old")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    g = FakeGit([row("LR-old")], files=[row("LR-file")])
    for i in range(3):
        st = w.run_pass(git=g, dispatch=d, now_fn=lambda i=i: T0 + timedelta(minutes=i), logs=tmp_path)
    assert d.calls == [("LR-file", TIP)]
    assert st["fetch_state"] == "fetched" and st["file_rows"] == 1 and st["legacy_rows"] == 1 and st["new"] == 0
    assert [r["review_id"] for r in log(tmp_path)] == ["LR-file"]


def test_legacy_rows_still_read_alongside_per_row_files(tmp_path):
    d = FakeDispatch()
    w.run_pass(git=FakeGit([]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    w.run_pass(git=FakeGit([row("LR-legacy")], files=[row("LR-file")]), dispatch=d, now_fn=lambda: T0,
               logs=tmp_path)
    assert sorted(c[0] for c in d.calls) == ["LR-file", "LR-legacy"]


def test_a_per_row_file_whose_name_is_not_its_review_id_is_not_a_row(tmp_path):
    from src.runtime import live_review_rows as rl
    r, why = rl.parse_row_file("comms/live_review/rows/LR-a.json", json.dumps(row("LR-b")))
    assert r is None and "does not match" in why


def test_a_truncated_tip_is_refused_flagged_once_and_nothing_dispatched(tmp_path):
    """The 3f1546c2d incident: 26 valid rows -> 4 valid rows + one cut-off line, plus the swapper's
    own row lost. A reviewer's new row on that tip must not be acted on."""
    d, alerts = FakeDispatch(), []
    full = [row(f"LR-{i:02d}", action="hold") for i in range(26)]
    w.run_pass(git=FakeGit(full), dispatch=d, now_fn=lambda: T0, logs=tmp_path, alert=alerts.append)
    cut = "\n".join(json.dumps(r) for r in full[:4]) + "\n" + json.dumps(full[4])[:40]
    bad = FakeGit([], text=cut, files=[row("LR-new")], tip="b" * 40)
    for i in range(3):
        st = w.run_pass(git=bad, dispatch=d, now_fn=lambda i=i: T0 + timedelta(minutes=i), logs=tmp_path,
                        alert=alerts.append)
    assert st["fetch_state"] == "refused_shrunk" and st["lost"] == 22 and d.calls == []
    assert len(alerts) == 1 and "REFUSED" in alerts[0]
    assert [r["verdict"] for r in log(tmp_path)] == ["refused_shrunk"]
    # the branch is restored and the new row arrives: accepted, the flag clears, the row is applied once
    good = FakeGit(full, files=[row("LR-new")], tip="c" * 40)
    st = w.run_pass(git=good, dispatch=d, now_fn=lambda: T0 + timedelta(minutes=9), logs=tmp_path,
                    alert=alerts.append)
    assert st["fetch_state"] == "fetched" and st.get("shrink_cleared") and d.calls == [("LR-new", "c" * 40)]
    assert len(alerts) == 1


def test_a_count_drop_alone_is_refused(tmp_path):
    d, alerts = FakeDispatch(), []
    w.run_pass(git=FakeGit([row("LR-a"), row("LR-b")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)
    state = json.loads((tmp_path / "rows_watch_state.json").read_text())
    state["seen"] = ["LR-a"]  # a count drop with every seen id still present
    (tmp_path / "rows_watch_state.json").write_text(json.dumps(state))
    st = w.run_pass(git=FakeGit([row("LR-a")]), dispatch=d, now_fn=lambda: T0, logs=tmp_path,
                    alert=alerts.append)
    assert st["fetch_state"] == "refused_shrunk" and len(alerts) == 1 and d.calls == []
