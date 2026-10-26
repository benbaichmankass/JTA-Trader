"""LTR-APPLY-AUTOFLOW (a): only NEW rows that pass the dispatcher's own clauses are filed."""
from __future__ import annotations

import copy
import json
import subprocess
import sys

from scripts.ops import live_review_autoflow as af
from tests.test_live_review_dispatch import MEASURED, TABLE, TABLE_ROW


def jl(*rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def ev(path):
    return MEASURED if path == TABLE else None


def test_a_new_qualifying_row_is_listed():
    go, skip = af.qualifying("", jl(TABLE_ROW), ev)
    assert go == [TABLE_ROW["review_id"]] and not skip


def test_a_row_already_on_the_base_is_never_redispatched():
    go, _ = af.qualifying(jl(TABLE_ROW), jl(TABLE_ROW), ev)
    assert go == []


def test_non_qualifying_rows_are_skipped_with_the_dispatcher_reason():
    hold = copy.deepcopy(TABLE_ROW)
    hold.update(review_id="LR-x-hold", recommendation={"action": "hold"})
    ask = copy.deepcopy(TABLE_ROW)
    ask.update(review_id="LR-x-ask")
    ask["disposition"] = dict(ask["disposition"], route="operator_ask")
    mism = copy.deepcopy(TABLE_ROW)
    mism.update(review_id="LR-x-mech", mechanics={"verdict": "mismatch"})
    go, skip = af.qualifying("", jl(hold, ask, mism), ev)
    assert go == [] and len(skip) == 3


def test_uncommitted_evidence_is_skipped():
    go, skip = af.qualifying("", jl(TABLE_ROW), lambda p: None)
    assert go == [] and skip


def test_an_unresolvable_base_falls_back_to_the_parent_not_to_empty():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run([sys.executable, "scripts/ops/live_review_autoflow.py", "--before", "0" * 40,
                        "--after", head], capture_output=True, text=True)
    assert r.returncode == 0 and f"(base {head}~1)" in r.stderr
