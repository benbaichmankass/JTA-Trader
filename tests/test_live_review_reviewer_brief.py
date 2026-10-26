"""LTR C3: the repo-less reviewer brief stays exact, and a row written by it passes the
same validator as main's rows and the VM dispatcher's mandate clauses."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIEF = (ROOT / ".claude/skills/live-trade-review/REVIEWER-BRIEF.md").read_text()


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json_block(after: str) -> dict:
    tail = BRIEF.split(after, 1)[1]
    return json.loads(re.search(r"```json\n(.*?)\n```", tail, re.S).group(1))


def test_the_embedded_schema_is_the_schema():
    assert _json_block("### The schema (verbatim)") == json.loads(
        (ROOT / "comms/schema/live_review.schema.json").read_text())


def test_a_row_written_per_the_brief_passes_the_main_validator(tmp_path, monkeypatch):
    v = _load("clr", "scripts/ci/check_live_review_records.py")
    row = _json_block("### Worked example")
    packet = {"review_id": row["review_id"], "order_package_id": row["order_package_id"], "state": row["state"]}
    pk = tmp_path / "packets"
    pk.mkdir()
    (pk / f"{row['review_id']}.json").write_text(json.dumps(packet, indent=2))
    row["packet_sha"] = hashlib.sha256(
        json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rv, oc = tmp_path / "reviews.jsonl", tmp_path / "outcomes.jsonl"
    rv.write_text(json.dumps(row, separators=(",", ":")) + "\n")
    oc.write_text("")
    monkeypatch.setattr(v, "PACKETS", pk)
    assert v.findings(rv, oc) == []


def test_the_example_tighten_clears_the_vm_dispatchers_clauses():
    d = _load("lrd", "scripts/ops/live_review_dispatch.py")
    row = _json_block("### Worked example")
    plan, refusal = d.check_row(row, json.dumps({"read_state": "thin"}))
    assert refusal is None and plan["basis"] == "judgement"


def test_the_write_is_a_compare_and_swap_with_a_bounded_retry():
    """Manager 2026-10-26 ~11:59Z: a lost concurrent line must be impossible, not unlikely."""
    write = BRIEF.split("## 4. The write", 1)[1]
    assert "never `push_files` for `reviews.jsonl`" in write
    assert "with `sha: S`" in write and "409" in write          # contents-API CAS
    assert "`force=false`" in write and "parent T" in write      # Git Data API CAS
    assert "restart from step 2" in write and "Up to 5 tries" in write
    assert "`could_not_write`" in write
