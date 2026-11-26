"""DESK-MACRO v1.1 (Manager 26a, 2026-11-26): a same-day correction is written natively and only the head brief is graded."""
from __future__ import annotations

import json

from scripts.ops import desk_macro_outcomes as dmo


def _b(bid, sup=None):
    b = {"schema": "desk_macro_brief/1", "brief_id": bid, "judged_at": "2026-11-26T13:00:00Z", "trades": [], "forecasts": []}
    if sup:
        b["supersedes"] = sup
    return b


def test_outcomes_grade_only_the_head_brief(tmp_path):
    (tmp_path / "2026-11-26.json").write_text(json.dumps(_b("DMB-20261126T1307Z")))
    (tmp_path / "2026-11-26_DMB-20261126T1407Z.json").write_text(json.dumps(_b("DMB-20261126T1407Z", "DMB-20261126T1307Z")))
    (tmp_path / "2026-11-25.json").write_text(json.dumps(_b("DMB-20261125T1307Z")))
    ids = sorted(b["brief_id"] for b in dmo._briefs(tmp_path))
    assert ids == ["DMB-20261125T1307Z", "DMB-20261126T1407Z"]
