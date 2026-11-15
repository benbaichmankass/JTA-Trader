"""scripts/ops/decisions_page_build.py: the decisions-page collections keep the shape the page renders."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.ops import decisions_page_build as B

PLAN = """# Weekly workplan

## 3. Day-by-day schedule per assistant manager (surge)

### AM-OPS (`session_x`)

**2026-11-12**

| # | row | size | what |
|--:|---|---|---|
| 1 | ROW-A | M | do a |
| 2 | ROW-B | S | do b |

## 4. Throttle (after the surge; due 11-17 / 11-18, in order)

**AM-ML (2):** ROW-C, ROW-A

## 5. Standing

ROW-D (AM-TRADING), ROW-E (AM-OPS). Plus the recurring checkups.

## 6. Landed, observation owed (`landed_unproven`)

| row | AM | observation that closes it |
|---|---|---|
| ROW-F | OPS | the thing is seen live. |
"""

ITEMS = [
    {"id": "ROW-A", "kind": "build", "state": "in_flight", "title": "A title", "owner": "AM-OPS (session_x)",
     "updated_at": "2026-11-15T01:00:00Z", "prs": [1], "terminal_reason": None, "created_at": "2026-11-10T00:00:00Z",
     "extra": {"note": "n" * 600}, "priority_rank": 1},
    {"id": "ROW-C", "kind": "build", "state": "queued", "title": "C title", "owner": "AM-ML",
     "updated_at": "2026-11-14T00:00:00Z", "created_at": "2026-11-01T00:00:00Z", "priority_rank": 2},
    {"id": "NEW-1", "kind": "build", "state": "done", "title": "new row", "owner": "AM-OPS (session_x)",
     "updated_at": "2026-11-15T02:00:00Z", "created_at": "2026-11-13T00:00:00Z", "prs": [9]},
    {"id": "FRONTIER-Q-X", "kind": "build", "state": "queued", "title": "fq", "owner": "lane FRONTIER-RESEARCH (AM-ML)",
     "updated_at": "2026-11-13T00:00:00Z", "created_at": "2026-11-13T00:00:00Z",
     "extra": {"note": "note", "frontier": {"family": "f", "p_pass": 0.1, "state": "unit_authored"}}},
]


def test_parse_workplan_sections_and_first_mention_wins():
    rows = B.parse_workplan(PLAN)
    by = {r["id"]: r for r in rows}
    assert [r["id"] for r in rows] == ["ROW-A", "ROW-B", "ROW-C", "ROW-D", "ROW-E", "ROW-F"]
    assert by["ROW-A"]["bucket"] == "surge" and by["ROW-A"]["slot"] == "2026-11-12" and by["ROW-A"]["am"] == "AM-OPS"
    assert by["ROW-C"]["bucket"] == "throttle" and by["ROW-C"]["slot"] == "11-17/11-18" and by["ROW-C"]["n"] == "1"
    assert by["ROW-D"]["bucket"] == "standing" and by["ROW-D"]["am"] == "AM-TRADING"
    assert by["ROW-F"]["bucket"] == "landed_unproven" and by["ROW-F"]["what"] == "the thing is seen live."


def test_build_workplan_joins_the_store_and_lists_rows_added_since_the_week(tmp_path):
    p = tmp_path / "docs/plans/weekly/2026-11-12/WORKPLAN.md"
    p.parent.mkdir(parents=True)
    p.write_text(PLAN)
    old_repo = B.REPO
    B.REPO = tmp_path
    try:
        wp = B.build_workplan(ITEMS, p, "read")
    finally:
        B.REPO = old_repo
    a = next(r for r in wp["rows"] if r["id"] == "ROW-A")
    assert set(a) == {"id", "am", "slot", "bucket", "n", "size", "what", "state", "title", "owner", "updated_at",
                      "prs", "terminal", "note"}
    assert a["state"] == "in_flight" and len(a["note"]) == B.NOTE_TAIL
    b = next(r for r in wp["rows"] if r["id"] == "ROW-B")
    assert b["state"] is None                                   # not in the store: null, never a made-up state
    assert sorted(x["id"] for x in wp["added"]) == ["FRONTIER-Q-X", "NEW-1"]
    assert wp["store_total"] == len(ITEMS) and wp["read_state"] == "read"


def test_lanestatus_states_merged_deployed_observed_separately():
    ls = B.build_lanestatus(ITEMS, "read", today="2026-11-15")
    ops = next(lane for lane in ls["lanes"] if lane["name"].startswith("AM-OPS"))
    assert any("NEW-1: observed (#9)" in x for x in ops["moved_today"])
    assert any(x.startswith("ROW-A: in flight (#1)") for x in ops["working_now"])
    ml = next(lane for lane in ls["lanes"] if lane["name"].startswith("ML-PRIMARY"))
    assert any(x.startswith("ROW-C: queued") for x in ml["next"])


def test_rdreg_slim_caps_text_and_never_invents_a_fold_count(tmp_path):
    full = {"generated_at": "g", "stages": [{"stage": "idea"}], "stage_rules": [{"stage": "retired", "rule": "r"}],
            "summary": {"ideas": 1, "per_track": {}, "per_stage_per_track": {},
                        "changed_last_7d": {"basis": "b", "count": 1, "items": [{"id": "x"}] * 50}},
            "ideas": [{"id": "x", "name": "n" * 300, "programme": ["P2", "P3"], "next_step": None,
                       "latest_result": {"unit": "U", "verdict": "fail", "date": "2026-11-06T08:00:11Z", "n": 5,
                                         "title": "t" * 250},
                       "stage0_evidence": {"coverage_state": "measured", "expectancy_r_oos": 0.1, "n_trades_oos": 9},
                       "open_units": ["a", "b", "c", "d", "e"], "last_activity": "2026-11-12T00:00:00Z",
                       "links": {"plan": "L"}}]}
    p = tmp_path / "rd.json"
    p.write_text(json.dumps(full))
    rd = B.build_rdreg(p)
    i = rd["ideas"][0]
    assert len(i["name"]) == 160 and i["name"].endswith("…") and len(i["lr"]["t"]) == 200
    assert i["prog"] == "P2, P3" and i["next"] == "" and i["last"] == "2026-11-12T00:00" and len(i["open"]) == 4
    assert i["ev"] == {"r": 0.1, "n": 9, "f": None} and i["link"] == "L" and i["lr"]["d"] == "2026-11-06"
    assert len(rd["changed"]["items"]) == 40
    assert B.build_rdreg(tmp_path / "missing.json")["read_state"].startswith("could_not_look")


def test_chunks_reassemble_to_the_payload():
    payload = {"rows": ["x" * 1000] * 400}
    docs = B.chunk_docs(payload, "p", "gen")
    assert [d for d, _ in docs] == [f"p{n}" for n in range(len(docs))] and len(docs) >= 3
    assert all(set(v) == {"gen", "seq", "total", "chunk"} and v["total"] == len(docs) for _, v in docs)
    assert json.loads("".join(v["chunk"] for _, v in docs)) == payload


def test_plans_map_lines_and_frontier(tmp_path):
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "docs/plans/ml-dev-plan.yaml").write_text(
        "updated: 2026-11-15\nlines:\n  - id: MLP-X\n    track: S\n    subject: subj\n    row: ROW-C\n"
        "    state: {summary: s, evidence: []}\n    owner: AM-ML\n")
    pl = B.build_plans(ITEMS, root=tmp_path)
    assert pl["plan"][0] == {"id": "MLP-X", "track": "S", "family": None, "title": "subj",
                             "plan_state": {"summary": "s", "evidence": []}, "ref": "ROW-C", "ref_state": "queued",
                             "close": "", "steps": None, "next": None, "owner": "AM-ML",
                             "updated": "2026-11-14T00:00:00Z", "tier": None}
    fq = pl["frontier"][0]
    assert fq["id"] == "FRONTIER-Q-X" and fq["state"] == "unit_authored" and fq["f"]["p_pass"] == 0.1
    assert set(fq["f"]) == set(B.FRONTIER_F_KEYS) and pl["tracks"] == B.TRACKS


def test_cli_writes_files_and_a_manifest(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps(ITEMS))
    out = tmp_path / "out"
    assert B.main(["lanestatus", "--out", str(out), "--items-json", str(items)]) == 0
    man = json.loads((out / "manifest.json").read_text())
    assert [(d["collection"], d["doc_id"]) for d in man["docs"]] == [("lanestatus", "current")]
    assert "json" in json.loads(Path(man["docs"][0]["path"]).read_text())


def test_workplan_source_is_pinnable_and_always_printed(tmp_path, capsys):
    for wk in ("2026-11-05", "2026-11-12"):
        p = tmp_path / f"docs/plans/weekly/{wk}/WORKPLAN.md"
        p.parent.mkdir(parents=True)
        p.write_text(PLAN)
    newest = B.latest_workplan(root=tmp_path)
    assert newest.parent.name == "2026-11-12" and "newest of 2 weekly plan(s)" in capsys.readouterr().err
    pin = tmp_path / "docs/plans/weekly/2026-11-05/WORKPLAN.md"
    assert B.latest_workplan(root=tmp_path, pinned=pin) == pin and "pinned (--plan)" in capsys.readouterr().err
