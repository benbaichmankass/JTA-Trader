"""DESK-14: the feed-gap alert path (scripts/ops/desk_feed_gaps.py)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import desk_feed_gaps as dfg

import pipeline

TODAY = date(2026, 10, 27)


def _item(gap, cls="funding", influence="decisive"):
    return {"source": "venue", "feed_gap": gap, "gap_class": cls, "influence": influence,
            "retrieved_at": "2026-10-27T09:05:00Z", "why_packet_insufficient": "packet lacks it"}


def _decisions(path, *rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _row(did, *items):
    return {"decision_id": did, "judged_at": "2026-10-27T09:06:00Z", "external_context": {"used": bool(items), "items": list(items)}}


def test_one_pipeline_item_per_new_gap_name_and_idempotent(tmp_path):
    dec, store, pdir = tmp_path / "d.jsonl", tmp_path / "gaps.jsonl", tmp_path / "pipeline"
    _decisions(dec, _row("DD-1", _item("bybit_live_funding_rate")), _row("DD-2", _item("bybit_live_funding_rate"), _item("econ_calendar", "calendar", "supporting")),
               _row("DD-3"))
    kw = dict(decisions=dec, short_hold=tmp_path / "none.jsonl", store=store, file_pipeline=True, today=TODAY, pipeline_dir=pdir)
    r1 = dfg.run(**kw)
    assert r1["occurrences"] == 3 and r1["new_lines"] == 3 and len(r1["filed"]) == 2 and not r1["errors"]
    items = list(pipeline.read_log(pdir).items.values())
    assert {i["origin"]["ref"] for i in items} == {"desk-feed-gap:bybit_live_funding_rate", "desk-feed-gap:econ_calendar"}
    assert all(i["due_when"]["kind"] == "date" and i["origin"]["rerun"] for i in items)  # the pipeline's own invariants hold
    assert "2 use(s), 2 decisive" in next(i for i in items if i["origin"]["ref"].endswith("funding_rate"))["what"]
    r2 = dfg.run(**kw)  # a re-run files nothing and writes nothing
    assert r2["new_lines"] == 0 and r2["filed"] == []
    assert len(store.read_text().splitlines()) == 3


def test_a_killed_gap_is_not_refiled(tmp_path):
    dec, store, pdir = tmp_path / "d.jsonl", tmp_path / "gaps.jsonl", tmp_path / "pipeline"
    _decisions(dec, _row("DD-1", _item("g1")))
    kw = dict(decisions=dec, short_hold=tmp_path / "none.jsonl", store=store, file_pipeline=True, today=TODAY, pipeline_dir=pdir)
    (fid,) = dfg.run(**kw)["filed"]
    prior = pipeline.read_log(pdir).items[fid]
    pipeline.append(dict(prior, state="killed", terminal_reason="not worth a feed"), pdir, intent="update",
                    based_on=pipeline.version_of(fid, pdir))
    _decisions(dec, _row("DD-1", _item("g1")), _row("DD-2", _item("g1")))
    assert dfg.run(**kw)["filed"] == []


def test_short_hold_gap_lines_are_read_and_dry_run_files_nothing(tmp_path):
    sh, store, pdir = tmp_path / "sh.jsonl", tmp_path / "gaps.jsonl", tmp_path / "pipeline"
    sh.write_text(json.dumps({"review_id": "LR-1", "decided_at": "2026-10-27T09:00:00Z", "source": "venue", "influence": "supporting",
                              "gap_class": "orderbook", "feed_gap": "l2_depth", "why_packet_insufficient": "x"}) + "\n")
    res = dfg.run(decisions=tmp_path / "none.jsonl", short_hold=sh, store=store, today=TODAY, pipeline_dir=pdir)
    assert res["gap_names"] == ["l2_depth"] and res["filed"] == [] and not pdir.exists()


def test_the_committed_corpus_reads_cleanly():
    """The real comms/desk/decisions.jsonl carries legacy object-only rows: they have no items and raise no gap."""
    root = Path(__file__).resolve().parents[1]
    assert dfg.collect(root / dfg.DECISIONS, root / dfg.SHORT_HOLD_GAPS) is not None
