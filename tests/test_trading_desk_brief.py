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
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


def _packet_with_short_row() -> dict:
    p = _scan_packet()
    p["history"]["rows"].append({**p["history"]["rows"][0], "side": "short", "n": 1480, "mean_r": -0.03, "sd_r": 1.8})
    p["features_at_review"] = cdr.project_scan_features(p)
    return p


def _example(packet: dict) -> dict:
    """The brief's worked DRAFT, compiled the way desk_write.py compiles it for a wake."""
    pointer = {"packet_id": packet["meta"]["packet_id"], "packet_sha": cdr.packet_sha(packet)}
    return cdr.desk_write.compile_row(json.loads(_block("desk-brief-example")), pointer, packet, {}, now=NOW, skill_sha=None)


NOW = datetime(2026, 10, 26, 13, 6, tzinfo=timezone.utc)


def test_worked_example_proposal_passes_the_guard(tmp_path):
    p = _packet_with_short_row()
    assert cdr.packet_problems(p, json.loads(cdr.PACKET_SCHEMA.read_text())) == []
    row = _example(p)
    assert _findings(tmp_path, [row], p) == []
    # the wake's own validator agrees with the guard on this row
    assert cdr.desk_write.row_problems(row, p, json.loads(cdr.DECISION_SCHEMA.read_text())) == []


def test_no_trade_twin_passes_and_a_hand_set_novelty_is_refused(tmp_path):
    p = _packet_with_short_row()
    draft = json.loads(_block("desk-brief-example"))
    nt = {k: draft[k] for k in ("session", "confidence", "basis", "rationale", "weighed")} | {"action": "no_trade"}
    pointer = {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}
    row = cdr.desk_write.compile_row(nt, pointer, p, {}, now=NOW, skill_sha=None)
    assert _findings(tmp_path / "a", [row], p) == []
    bad = _example(p)
    bad["proposal"]["novelty"] = "new"  # near-signals were not read: the script derives `unverifiable`
    assert any("novelty" in f for f in _findings(tmp_path / "b", [bad], p))
    with pytest.raises(cdr.desk_write.Refused):  # a wake cannot set a derived field
        cdr.desk_write.compile_row({**draft, "proposal": {**draft["proposal"], "novelty": "new"}}, pointer, p, {}, now=NOW, skill_sha=None)


def test_the_limits_the_brief_quotes_are_the_guards():
    text = BRIEF.read_text()
    assert f"{cdr.SENTINEL_R_FLOOR:g} R" in text
    assert f"{cdr.TP_VENUE_CAP_PCT * 100:.1f} %" in text
    assert f"[{cdr.REACH_FLOOR:.2f}, 1)" in text
    assert "sonnet-tier" in json.loads(cdr.DECISION_SCHEMA.read_text())["enums"]["model_tier"]
