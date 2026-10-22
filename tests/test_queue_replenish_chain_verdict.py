"""queue_replenish.chain_verdict: a node chained after a RECURRING unit is not stuck `waiting` forever.

Measured case (EXITS-OVERNIGHT-1021): P1-Q11 waited behind the weekly census RQ-20261014-9807-01 and the
monthly RQ-20260928-019, both graded PASS, because only `status: done` counted as closed.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import queue_replenish as qr  # noqa: E402

NODE = {"id": "N", "after": [{"unit": "RQ-1", "verdict": "any"}]}


def _state(unit):
    return qr.node_state(NODE, {"RQ-1": unit}, {})[0]


def test_recurring_graded_unit_satisfies_a_chain():
    u = {"status": "queued", "cadence": "weekly", "grading": {"verdict": "pass", "needs_review": False}}
    assert qr.chain_verdict(u) == "pass" and _state(u) == "ready"


def test_recurring_ungraded_or_under_review_still_waits():
    assert _state({"status": "queued", "cadence": "weekly"}) == "waiting"
    assert _state({"status": "queued", "cadence": "weekly",
                   "grading": {"verdict": None, "needs_review": True}}) == "waiting"
    assert _state({"status": "queued", "cadence": "monthly",
                   "grading": {"verdict": "pass", "needs_review": True}}) == "waiting"


def test_once_unit_still_needs_done():
    u = {"status": "queued", "cadence": "once", "grading": {"verdict": "pass"}}
    assert qr.chain_verdict(u) is None and _state(u) == "waiting"
    assert _state({**u, "status": "done"}) == "ready"


def test_answered_state_of_a_materialised_node_is_unchanged():
    # chain_verdict must not leak into closed_verdict (a recurring node's own unit is not "answered")
    u = {"status": "queued", "cadence": "weekly", "grading": {"verdict": "pass"}}
    assert qr.closed_verdict(u) is None
