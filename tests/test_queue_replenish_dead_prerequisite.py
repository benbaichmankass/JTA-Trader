"""queue_replenish.node_state: a unit-less prerequisite node that can never materialise reads as dead (moot), not "open".

Measured case (2026-11-26, lane BUILDS-W48): 9 nodes sat `waiting` forever -- the P1-Q14 ones on `authoring_closed` Q13 nodes,
P4-Q6/P4-Q7 on a node that was itself moot. A node that is genuinely still open must keep waiting.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import queue_replenish as qr  # noqa: E402

DEP = {"id": "DEP", "after": [{"node": "PRE", "verdict": "pass"}]}
PRE_CLOSED = {"id": "PRE", "authoring_closed": "killed"}
PRE_OPEN = {"id": "PRE", "needs_authoring": "ask"}


def test_authoring_closed_prerequisite_is_dead_and_the_dependent_is_moot():
    dead = qr._dead_nodes([PRE_CLOSED, DEP], {}, {})
    assert qr.node_key("PRE") in dead
    st, why = qr.node_state(DEP, {}, {}, dead)
    assert st == "moot" and "never unlocks" in why[0]


def test_a_dead_chain_propagates_to_the_next_dependent():
    dep2 = {"id": "DEP2", "after": [{"node": "DEP", "verdict": "pass"}]}
    dead = qr._dead_nodes([PRE_CLOSED, DEP, dep2], {}, {})
    assert qr.node_key("DEP2") in dead


def test_a_still_open_unit_less_prerequisite_keeps_the_dependent_waiting():
    # negative control: the same shape with an open (not closed) prerequisite must NOT read as dead
    dead = qr._dead_nodes([PRE_OPEN, DEP], {}, {})
    assert dead == {}
    assert qr.node_state(DEP, {}, {}, dead)[0] == "waiting"


def test_without_the_dead_map_behaviour_is_unchanged():
    assert qr.node_state(DEP, {}, {})[0] == "waiting"
