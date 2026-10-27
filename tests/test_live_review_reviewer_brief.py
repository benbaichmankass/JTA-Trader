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


def test_the_write_is_one_create_only_file_per_row_with_a_bounded_retry():
    """LTR-ROWS-SWAP-TRUNCATION (2026-10-27): a reviewer re-sending the whole reviews.jsonl truncated it
    (26 rows -> 4). The row is ONE create-only file, so its size never depends on the branch's, and a
    concurrent reviewer's row is a different path (a lost line stays impossible)."""
    write = BRIEF.split("## 4. The write", 1)[1]
    assert "**never write `reviews.jsonl`**" in write and "never `push_files`" in write
    assert "**`comms/live_review/rows/<review_id>.json`**" in write and "**no `sha`** (create-only)" in write
    assert "Never add a `sha` to overwrite it" in write
    assert "`force=false`" in write and "parent T" in write      # Git Data API path still fast-forward only
    assert "Up to 5 tries" in write and "`could_not_write`" in write and "row_conflict" in write
    assert "with `sha: S`" not in write                            # the whole-file compare-and-swap is gone


def test_the_brief_row_path_is_the_one_the_readers_read():
    from src.runtime import live_review_rows as rl
    assert rl.row_path("<review_id>") in BRIEF.split("## 4. The write", 1)[1]


def test_the_reviewer_never_writes_the_packet_or_the_table():
    """LTR-PACKET-ECHO (2026-10-27): a re-typed packet dropped "sd_r":null and the mirror refused the row.
    The wake poster commits packet + table byte-exact; the reviewer only reads that the packet exists."""
    write = BRIEF.split("## 4. The write", 1)[1]
    assert "**never write `comms/live_review/packets/` or `comms/live_review/tables/`**" in write
    assert "Your ONE write is your row file" in write and "evidence_missing" in write
    assert "= the block's `packet` object" not in write and "`table_path` = the block's `table` object" not in write
    assert "ADDS only `comms/live_review/rows/<review_id>.json`" in write   # the git-data path writes one file too
