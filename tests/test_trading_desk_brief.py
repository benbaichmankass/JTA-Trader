"""DESK-5-SKILL: the repo-less desk wake brief stays equal to what desk-records-guard enforces.

A wake session reads ONLY .claude/skills/trading-desk/DESK-BRIEF.md and one scan packet, so the brief
is the whole contract. These tests pin it to the real validator: the embedded schema is the schema
file, the worked example row (and its no_trade twin) passes check_desk_records.findings() against a
packet built the way the desk branch carries it, and the numeric limits the brief quotes are the
guard's own constants.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
sys.path.insert(0, str(ROOT))

import check_desk_records as cdr  # noqa: E402

BRIEF = ROOT / ".claude/skills/trading-desk/DESK-BRIEF.md"


def _block(tag: str) -> str:
    m = re.search(rf"<!-- {tag}:begin -->\s*```json\n(.*?)\n```\s*<!-- {tag}:end -->", BRIEF.read_text(), re.DOTALL)
    assert m, f"{tag} block missing from the brief"
    return m.group(1)


def _scan_packet() -> dict:
    """The guard's own example scan, re-shaped like a live builder packet: near-signals not read."""
    p = copy.deepcopy(cdr.GOOD_SCAN)
    p["meta"].update(packet_id="DP-20261026T1300Z-scan-1h", built_at="2026-10-26T13:01:00Z",
                     info_cutoff_at="2026-10-26T13:00:00Z")
    p["meta"]["missing_inputs"].append("system_book.near_signals: no near-signal producer exists yet")
    p["system_book"]["near_signals_read_state"] = "could_not_look"
    p["system_book"]["items"] = [i for i in p["system_book"]["items"] if i["status"] != "near_signal"]
    p["features_at_review"] = cdr.project_scan_features(p)
    return p


def _findings(tmp_path: Path, rows: list[dict], packet: dict) -> list[str]:
    d = tmp_path / "desk"
    (d / "packets").mkdir(parents=True)
    (d / "packets" / f"{packet['meta']['packet_id']}.json").write_text(json.dumps(packet))
    (d / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for f in ("touches.jsonl", "outcomes.jsonl", "consumed.jsonl"):
        (d / f).write_text("")
    return cdr.findings(decisions=d / "decisions.jsonl", touches=d / "touches.jsonl", packets=d / "packets")


def _example(packet: dict) -> dict:
    row = json.loads(_block("desk-brief-example"))
    row["packet_sha"] = cdr.packet_sha(packet)
    return row


def test_embedded_schema_equals_the_schema_file():
    schema = json.loads(cdr.DECISION_SCHEMA.read_text())
    want = {k: schema[k] for k in ("enums", "role_actions", "role_defaults", "decisions")}
    assert json.loads(_block("desk-brief-schema")) == want, (
        "DESK-BRIEF.md's embedded schema drifted from comms/schema/desk_decision.schema.json; re-embed it")


def test_worked_example_proposal_passes_the_guard(tmp_path):
    p = _scan_packet()
    assert cdr.packet_problems(p, json.loads(cdr.PACKET_SCHEMA.read_text())) == []
    assert _findings(tmp_path, [_example(p)], p) == []


def test_no_trade_twin_passes_and_a_wrong_novelty_is_refused(tmp_path):
    p = _scan_packet()
    nt = _example(p)
    nt.update(action="no_trade", proposal=None, judge_prior=None)
    for a in nt["alternatives"]:
        a["chosen"] = a["action"] == "no_trade"
    assert _findings(tmp_path / "a", [nt], p) == []
    bad = _example(p)
    bad["proposal"]["novelty"] = "new"  # near-signals were not read: the brief says `unverifiable`
    assert any("novelty" in f for f in _findings(tmp_path / "b", [bad], p))


def test_the_limits_the_brief_quotes_are_the_guards():
    text = BRIEF.read_text()
    assert f"{cdr.SENTINEL_R_FLOOR:g} R" in text
    assert f"{cdr.TP_VENUE_CAP_PCT * 100:.1f} %" in text
    assert f"[{cdr.REACH_FLOOR:.2f}, 1)" in text
    assert "sonnet-tier" in json.loads(cdr.DECISION_SCHEMA.read_text())["enums"]["model_tier"]
