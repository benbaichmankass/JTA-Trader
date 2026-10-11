"""ml_plan_status: the checker detects each planted defect, and the committed ML plan has no orphans."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ml_plan_status", REPO / "scripts/ops/ml_plan_status.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_self_test_detects_planted_defects():
    assert m.self_test() == 0


def test_committed_plan_has_no_orphan_items():
    # An ORPHAN is a plan item whose row/unit is gone -- the exact way a plan item gets forgotten.
    # (STALE / CLOSED-OPEN move with ordinary work and are reported by the loop, not failed in CI.)
    plan = m.load_plan()
    res = m.analyse(plan, m.rows())
    orphans = [r["id"] + "->" + str(r["ref"]) for r in res if "ORPHAN" in r["flags"]]
    assert not orphans, orphans


def test_every_plan_item_has_a_close_condition_and_unique_id():
    plan = m.load_plan()
    ids = [i["id"] for i in plan["items"]]
    assert len(ids) == len(set(ids))
    assert all(i.get("close") and i.get("ref") for i in plan["items"])
