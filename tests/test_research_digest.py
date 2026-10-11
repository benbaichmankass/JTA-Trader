"""RESEARCH QUEUE section of the manager update (TELEGRAM-CHANNELS, 2026-10-11)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ops import research_digest as rd

NOW = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)


def _repo(tmp: Path) -> Path:
    (tmp / "research/queue").mkdir(parents=True)
    (tmp / "research/results/RQ-1").mkdir(parents=True)
    return tmp


def _unit(root, uid, status, fired=None):
    (root / f"research/queue/{uid}.yaml").write_text(
        f"id: {uid}\ntitle: t {uid}\nstatus: {status}\n"
        f"last_dispatched_at: {fired or 'null'}\n")


def _row(root, unit, verdict, power="measured", at=NOW, note="n"):
    f = root / f"research/results/{unit}/r.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a") as fh:
        fh.write(json.dumps({"research_unit": unit, "verdict": verdict,
                             "power_state": power, "note": note,
                             "generated_at": at.isoformat()}) + "\n")


def test_first_run_uses_a_stated_fixed_window(tmp_path):
    r = _repo(tmp_path)
    _unit(r, "RQ-1", "queued")
    _row(r, "RQ-1", "pass")
    _row(r, "RQ-1", "fail", at=NOW - timedelta(days=3))  # outside the window
    d = rd.build(root=r, prev=None, now=NOW)
    assert d["mode"] == "first_run_window"
    assert len(d["buckets"][rd.PASSED]) == 1 and not d["buckets"][rd.FAILED]
    assert "fixed window" in rd.render_body(d)


def test_since_cursor_buckets_and_transitions(tmp_path):
    r = _repo(tmp_path)
    for u in ("RQ-1", "RQ-2", "RQ-3"):
        _unit(r, u, "queued")
    _unit(r, "RQ-4", "blocked")
    _row(r, "RQ-1", "pass")
    prev = rd.build(root=r, prev=None, now=NOW)["snapshot"]
    prev = {"at": NOW.isoformat(), "units": prev["units"], "results": prev["results"]}
    # what happens in the hour:
    _row(r, "RQ-1", "fail")
    _row(r, "RQ-2", "indeterminate")
    # collapsed-state: underpowered — this test pins ONLY the under-powered override; every other power_state keeps its verdict bucket (asserted via the RQ-1/RQ-2 rows)
    _row(r, "RQ-3", "pass", power="underpowered")   # a pass at insufficient n
    _unit(r, "RQ-2", "done", fired="2030-01-10T12:30:00Z")
    _unit(r, "RQ-3", "blocked")
    _unit(r, "RQ-4", "queued")
    _unit(r, "RQ-5", "queued")
    d = rd.build(root=r, prev=prev, now=NOW)
    b, t = d["buckets"], d["transitions"]
    assert [len(b[k]) for k in (rd.PASSED, rd.FAILED, rd.FURTHER)] == [0, 1, 2]
    assert [x.split(" ")[0] for x in t["newly_queued"]] == ["RQ-5"]
    assert [x.split(" ")[0] for x in t["newly_blocked"]] == ["RQ-3"]
    assert [x.split(" ")[0] for x in t["unblocked"]] == ["RQ-4"]
    assert [x.split(" ")[0] for x in t["run"]] == ["RQ-2"]
    assert [x.split(" ")[0] for x in t["done"]] == ["RQ-2"]
    # counts equal the listed lines (operator feedback 2026-10-11)
    assert rd.headline(d).startswith("🔬 research: 3 result(s) — 0 pass · 1 fail · 2 further")


def test_nothing_new_is_said_and_differs_from_could_not_look(tmp_path):
    r = _repo(tmp_path)
    _unit(r, "RQ-1", "queued")
    s = rd.snapshot(r)
    prev = {"at": NOW.isoformat(), "units": s["units"], "results": s["results"]}
    quiet = rd.build(root=r, prev=prev, now=NOW)
    assert "Nothing new" in rd.render_body(quiet)
    blind = rd.build(root=tmp_path / "nope", prev=prev, now=NOW)
    body = rd.render_body(blind)
    assert "could not look" in body and "Nothing new" not in body
    assert "NOT READ" in rd.headline(blind)


def test_missing_fields_render_dash(tmp_path):
    r = _repo(tmp_path)
    f = r / "research/results/RQ-9/x.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"verdict": "pass", "generated_at": NOW.isoformat()}) + "\n")
    d = rd.build(root=r, prev=None, now=NOW)
    # never a bare "—" summary: the line says what is missing and where to look
    assert d["buckets"][rd.PASSED] == [
        "RQ-9: pass (row carries no measurement — open the result file)"]


def test_cursor_round_trip(tmp_path):
    r = _repo(tmp_path)
    _unit(r, "RQ-1", "queued")
    s = rd.snapshot(r)
    rd.commit(s, path=tmp_path / "c.json", now=NOW)
    assert rd.read_cursor(tmp_path / "c.json")["units"] == s["units"]
    (tmp_path / "bad.json").write_text("{")
    assert rd.read_cursor(tmp_path / "bad.json") is None
