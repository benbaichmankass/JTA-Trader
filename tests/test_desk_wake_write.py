"""DESK-WAKE-WRITE: the wake's single writer (.claude/skills/trading-desk/desk_write.py).

Measured 2026-10-27 over the 15 rows on desk/decisions: 7 were written by plain `git push` (author
noreply@anthropic.com), 8 by the GitHub tool; none of the 7 ran the brief's validation. These tests pin
the mechanism that replaces the prose: a draft is compiled from the packet, validated by the guard's own
rules, and pushed as a compare-and-swap; a wrong row cannot land.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
sys.path.insert(0, str(ROOT))

import check_desk_records as cdr  # noqa: E402
import desk_branch  # noqa: E402

dw = cdr.desk_write
NOW = datetime(2026, 10, 26, 13, 6, tzinfo=timezone.utc)
SCHEMA = json.loads(cdr.DECISION_SCHEMA.read_text())


def _packet() -> dict:
    p = copy.deepcopy(cdr.GOOD_SCAN)
    p["meta"].update(packet_id="DP-20261026T1300Z-scan-1h", built_at="2026-10-26T13:01:00Z",
                     info_cutoff_at="2026-10-26T13:00:00Z")
    p["meta"]["missing_inputs"].append("system_book.near_signals: no near-signal producer exists yet")
    p["system_book"]["near_signals_read_state"] = "could_not_look"
    p["system_book"]["items"] = [i for i in p["system_book"]["items"] if i["status"] != "near_signal"]
    p["history"]["rows"].append({**p["history"]["rows"][0], "side": "short", "n": 1480, "mean_r": -0.03, "sd_r": 1.8})
    p["history"]["rows"].append({**p["history"]["rows"][0], "horizon_bars": 48, "n": 1200, "mean_r": 3.1, "sd_r": 6.0})
    p["features_at_review"] = cdr.project_scan_features(p)
    return p


PROPOSE = {"action": "propose_entry", "session": "s", "confidence": "suggestive", "basis": "ev_positive", "judge_prior": 0.4,
           "rationale": "r", "weighed": [{"symbol": "ETHUSDT", "side": "short", "horizon_bars": 12, "level": 105.0}],
           "proposal": {"symbol": "ETHUSDT", "side": "long", "horizon_bars": 12,
                        "entry": {"type": "limit", "level": 99.0, "good_till_bars": 3}, "stop": {"level": 96.0, "basis": "swing_level"},
                        "tp": {"level": 105.0, "basis": "swing_level", "p_hit": 0.4}, "expected_r_net": 0.15, "thesis": "t"}}
NO_TRADE = {"action": "no_trade", "confidence": "suggestive", "basis": "ev_positive", "rationale": "r",
            "weighed": [{"symbol": "ETHUSDT", "side": "long", "horizon_bars": 12, "level": 99.0}]}


def sh(*a, cwd):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    """A bare `origin` with main (brief + schema) and desk/decisions (pointer, packet, empty decisions)."""
    bare, seed = tmp_path / "origin.git", tmp_path / "seed"
    sh("git", "init", "-q", "--bare", str(bare), cwd=tmp_path)
    sh("git", "init", "-q", str(seed), cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        sh("git", "config", k, v, cwd=seed)
    (seed / ".claude/skills/trading-desk").mkdir(parents=True)
    (seed / ".claude/skills/trading-desk/DESK-BRIEF.md").write_text("brief\n")
    (seed / "comms/schema").mkdir(parents=True)
    (seed / "comms/schema/desk_decision.schema.json").write_text(cdr.DECISION_SCHEMA.read_text())
    sh("git", "add", "-A", cwd=seed)
    sh("git", "commit", "-qm", "main", cwd=seed)
    sh("git", "branch", "-M", "main", cwd=seed)
    sh("git", "checkout", "-qb", "desk/decisions", cwd=seed)
    pk = _packet()
    (seed / "comms/desk/packets").mkdir(parents=True)
    (seed / f"comms/desk/packets/{pk['meta']['packet_id']}.json").write_text(json.dumps(pk))
    (seed / "comms/desk/decisions.jsonl").write_text("")
    (seed / "comms/desk/latest_scan.json").write_text(json.dumps({
        "packet_id": pk["meta"]["packet_id"], "packet_sha": cdr.packet_sha(pk), "path": f"comms/desk/packets/{pk['meta']['packet_id']}.json",
        "built_at": pk["meta"]["built_at"], "info_cutoff_at": pk["meta"]["info_cutoff_at"]}))
    sh("git", "add", "-A", cwd=seed)
    sh("git", "commit", "-qm", "packet", cwd=seed)
    sh("git", "push", "-q", str(bare), "main", "desk/decisions", cwd=seed)
    wake = tmp_path / "wake"
    sh("git", "init", "-q", str(wake), cwd=tmp_path)
    sh("git", "remote", "add", "origin", f"file://{bare}", cwd=wake)
    return bare, wake


def branch_rows(bare):
    out = sh("git", "show", "desk/decisions:comms/desk/decisions.jsonl", cwd=bare)
    return [json.loads(x) for x in out.splitlines() if x]


def test_proposal_is_written_by_cas_and_passes_the_guard(origin, tmp_path):
    bare, wake = origin
    rc, res = dw.run(PROPOSE, str(wake), now=NOW)
    assert rc == 0 and res["state"] == "written", res
    (row,) = branch_rows(bare)
    assert row["decision_id"] == "DD-20261026T1300Z-scan-1h-1"
    assert row["proposal"]["novelty"] == "unverifiable" and row["proposal"]["onboarding"] == "onboarded"
    assert row["skill_sha"] == sh("git", "rev-parse", "main:.claude/skills/trading-desk/DESK-BRIEF.md", cwd=bare)
    # the guard accepts exactly what the script wrote
    d = tmp_path / "desk"
    (d / "packets").mkdir(parents=True)
    pk = _packet()
    (d / "packets" / f"{pk['meta']['packet_id']}.json").write_text(json.dumps(pk))
    (d / "decisions.jsonl").write_text(json.dumps(row) + "\n")
    for f in ("touches.jsonl", "outcomes.jsonl", "consumed.jsonl"):
        (d / f).write_text("")
    assert cdr.findings(decisions=d / "decisions.jsonl", touches=d / "touches.jsonl", packets=d / "packets") == []
    # a second wake for the same packet writes nothing
    rc2, res2 = dw.run(NO_TRADE, str(wake), now=NOW)
    assert (rc2, res2["state"]) == (3, "nothing_due") and len(branch_rows(bare)) == 1


def test_stats_come_from_the_named_history_row_not_the_wake(origin):
    bare, wake = origin
    rc, res = dw.run({**NO_TRADE, "weighed": [{"symbol": "ETHUSDT", "side": "long", "horizon_bars": 48, "level": 99.0}]},
                     str(wake), now=NOW)
    assert rc == 0, res
    alts = {a["action"]: a for a in branch_rows(bare)[0]["alternatives"]}
    assert (alts["propose_entry"]["n"], alts["propose_entry"]["mean_r"]) == (1200, 3.1)  # the 48-bar row, as named
    assert alts["no_trade"]["n"] == 1200 and alts["no_trade"]["mean_r"] == 0.0


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["proposal"].update(stop={"level": 101.0, "basis": "swing_level"}), "geometry"),
    (lambda d: d["proposal"]["tp"].update(p_hit=0.05), "p_hit"),
    (lambda d: d["proposal"]["tp"].update(level=108.9), "venue cap"),
    (lambda d: d["proposal"].update(expected_r_net=3.0), "expected_r_net"),
    (lambda d: d["proposal"].update(horizon_bars=7), "history row"),
    (lambda d: d["proposal"].update(venue_class="x"), "proposal keys"),
    (lambda d: d["proposal"].update(symbol="NOPEUSDT"), "universe"),
    (lambda d: d.update(judge_prior=None), "judge_prior"),
    (lambda d: d.update(novelty="new"), "derives"),
    (lambda d: d.update(size=3), "no-size"),
    (lambda d: d.update(confidence="certain"), "not in"),
    (lambda d: d["proposal"]["entry"].update(type="teleport"), "not in"),
])
def test_an_invalid_draft_writes_nothing(origin, mutate, needle):
    bare, wake = origin
    draft = copy.deepcopy(PROPOSE)
    mutate(draft)
    rc, res = dw.run(draft, str(wake), now=NOW)
    assert rc == 1 and res["state"] == "refused", res
    assert needle in " ".join(res["problems"]), res["problems"]
    assert branch_rows(bare) == []


def test_a_moved_branch_rejects_the_push_and_the_retry_keeps_both_rows(origin, tmp_path, monkeypatch):
    bare, wake = origin
    other = tmp_path / "other"
    sh("git", "clone", "-q", "--branch", "desk/decisions", str(bare), str(other), cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        sh("git", "config", k, v, cwd=other)
    real, calls = dw.commit_on, []

    def racing(cwd, tip, text, msg):
        if not calls:  # a concurrent writer lands a line between this wake's read and its push
            (other / "comms/desk/decisions.jsonl").write_text('{"decision_id":"DD-x","packet_id":"DP-other"}\n')
            sh("git", "commit", "-qam", "racer", cwd=other)
            sh("git", "push", "-q", "origin", "HEAD:desk/decisions", cwd=other)
        calls.append(1)
        return real(cwd, tip, text, msg)

    monkeypatch.setattr(dw, "commit_on", racing)
    rc, res = dw.run(NO_TRADE, str(wake), now=NOW)
    assert rc == 0 and res["tries"] == 2, res
    assert [r["decision_id"] for r in branch_rows(bare)] == ["DD-x", "DD-20261026T1300Z-scan-1h-1"]


def test_a_stale_packet_is_marked_in_the_rationale(origin):
    bare, wake = origin
    rc, _ = dw.run(NO_TRADE, str(wake), now=datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc))
    assert rc == 0 and branch_rows(bare)[0]["rationale"].startswith("stale_packet: built 2026-10-26T13:01:00Z")


# ---- the stat-match rule, in the validator, the guard and the mirror

def _row():
    p = _packet()
    return dw.compile_row(NO_TRADE, {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}, p, SCHEMA,
                          now=NOW, skill_sha=None), p


def test_stat_match_rule_flags_a_borrowed_statistic():
    row, p = _row()
    assert dw.alt_stat_problems(row, p) == []
    row["alternatives"][1]["mean_r"] = 3.1  # a 12-bar long carrying the 48-bar row's mean
    assert any("equals no history row" in x for x in dw.alt_stat_problems(row, p))
    row, p = _row()
    row["alternatives"][0]["n"] = 12345
    assert any("no_trade n=12345" in x for x in dw.alt_stat_problems(row, p))


def test_the_guard_and_the_mirror_refuse_a_mismatched_row(tmp_path):
    row, p = _row()
    row["alternatives"][1]["sd_r"] = 9.9
    msgs = _guard(tmp_path / "g", row, p)
    assert any("equals no history row" in m for m in msgs)
    root = tmp_path / "main"
    (root / "comms/desk").mkdir(parents=True)
    pid = p["meta"]["packet_id"]
    blobs = {desk_branch.DECISIONS: (json.dumps(row) + "\n").encode(), f"{desk_branch.PACKETS}/{pid}.json": json.dumps(p).encode()}
    res = desk_branch.mirror(root, blobs.get)
    assert res["mirrored"] == 0 and "stat-match" in res["skipped"][0]["why"]  # skipped with a reason, not a stop
    good, p = _row()
    blobs[desk_branch.DECISIONS] = (json.dumps(good) + "\n").encode()
    assert desk_branch.mirror(root, blobs.get)["mirrored"] == 1


def _guard(tmp, row, packet):
    (tmp / "packets").mkdir(parents=True)
    (tmp / "packets" / f"{packet['meta']['packet_id']}.json").write_text(json.dumps(packet))
    (tmp / "decisions.jsonl").write_text(json.dumps(row) + "\n")
    for f in ("touches.jsonl", "outcomes.jsonl", "consumed.jsonl"):
        (tmp / f).write_text("")
    return cdr.findings(decisions=tmp / "decisions.jsonl", touches=tmp / "touches.jsonl", packets=tmp / "packets")


def test_the_writer_and_the_guard_share_their_constants():
    assert (dw.SENTINEL_R_FLOOR, dw.VENUE_CAP_FRACTION, dw.REACH_FLOOR) == (cdr.SENTINEL_R_FLOOR, cdr.TP_VENUE_CAP_PCT, cdr.REACH_FLOOR)


def test_the_writers_verdict_equals_the_guards_on_mutated_rows(tmp_path):
    """Drift guard: the stdlib validator in the skill dir must never accept what the full guard refuses."""
    muts = [lambda r: None,
            lambda r: r["proposal"].update(novelty="new"),
            lambda r: r["proposal"]["tp"].update(p_hit=0.02),
            lambda r: r["proposal"]["stop"].update(level=100.0),
            lambda r: r.update(judge_prior=None),
            lambda r: r["alternatives"][1].update(chosen=True),
            lambda r: r.update(training={"train_eligible": False, "gate_eligible": False, "exclusion_reasons": []})]
    for i, m in enumerate(muts):
        p = _packet()
        row = dw.compile_row(PROPOSE, {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}, p, SCHEMA,
                             now=NOW, skill_sha=None)
        m(row)
        writer_ok = dw.row_problems(row, p, SCHEMA) == []
        guard_ok = _guard(tmp_path / str(i), row, p) == []
        assert writer_ok == guard_ok, (i, dw.row_problems(row, p, SCHEMA))
