"""DESK-18H (RQ-20261112-e4a7-01): the event-driven packet arm's registered accounting.

Pins the parts of scripts/research/desk_event_packet_replay.py a judging lane relies on without candles:
the stopping rule's prefix / whole-batch accounting (a leak-withheld packet is a hole, not a skip), the
registered numbers, and that the judge protocol carries the event addendum and the one-proposal cap.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import desk_event_packet_replay as m  # noqa: E402


def _keys(indices):
    return {f"P{i}": {"packet_id": f"P{i}", "index": i} for i in indices}


def test_registered_numbers_are_the_units():
    assert (m.S3_BAR, m.N_MIN, m.ALPHA, m.B_DRAWS, m.BOOT, m.SEED, m.BATCH, m.MAX_PER_PACKET) == \
        (0.25, 30, 0.05, 200, 10_000, 20261112, 100, 1)
    assert m.UNIT_ID == "RQ-20261112-e4a7-01"
    assert (REPO / "research" / "queue" / "blocked" / f"{m.UNIT_ID}.yaml").exists() or \
        (REPO / "research" / "queue" / f"{m.UNIT_ID}.yaml").exists()


def test_whole_batch_with_a_leak_hole_is_valid():
    keyed = [i for i in range(250) if i != 37]                 # index 37 withheld for a mask leak
    keys = _keys(keyed)
    judged = {f"P{i}": [] for i in keyed if i < 200}
    d = m.prefix_design(keys, judged, 763)
    assert d["is_schedule_prefix"] and d["whole_batches"] and d["batch_end"] == 200


def test_partial_batch_and_gap_are_refused():
    keys = _keys(range(300))
    d = m.prefix_design(keys, {f"P{i}": [] for i in range(150)}, 763)
    assert d["is_schedule_prefix"] and not d["whole_batches"]
    d = m.prefix_design(keys, {f"P{i}": [] for i in range(200) if i != 5}, 763)
    assert not d["is_schedule_prefix"] and not d["whole_batches"]


def test_last_short_batch_closes_the_schedule():
    keys = _keys(range(763))
    d = m.prefix_design(keys, {f"P{i}": [] for i in range(763)}, 763)
    assert d["whole_batches"] and d["batch_end"] == 763


def test_addendum_states_the_trigger_and_the_cap():
    assert "OPENED BY AN EVENT" in m.EVENT_ADDENDUM
    assert "At most one proposal" in m.EVENT_ADDENDUM
    assert "EARLIER period" in m.EVENT_ADDENDUM
