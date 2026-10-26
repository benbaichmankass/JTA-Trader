"""Manager 2026-10-26 ~12:37Z (finding #20322): a real-money / prop review must carry a call.

`insufficient_n` / `default_hold` are refused on those rows from MONEY_CALL_RULE_FROM;
`hold` and `tighten_sl` with basis judgement + confidence + reason are accepted;
`no_recommendation` needs basis could_not_look + a reason. Paper rows and older rows are untouched.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("clr", ROOT / "scripts/ci/check_live_review_records.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)
SCHEMA = json.loads((ROOT / "comms/schema/live_review.schema.json").read_text())
_BRIEF = (ROOT / ".claude/skills/live-trade-review/REVIEWER-BRIEF.md").read_text()
BASE = json.loads(re.search(r"```json\n(.*?)\n```", _BRIEF.split("### Worked example", 1)[1], re.S).group(1))


def row(action, basis, *, src="none", conf=None, reason=None, at="2026-10-26T13:03:00Z", paper=False):
    r = copy.deepcopy(BASE)
    r["reviewed_at"] = at
    rec = r["recommendation"]
    rec.update(action=action, basis=basis, evidence_source=src, judgement_confidence=conf, reason=reason)
    if action != "tighten_sl":
        rec.update(level=None, level_atr=None)
        r["disposition"]["route"] = "none"
        r["disposition"]["mandate"] = None
        for a in r["account_reads"]:
            a["read"] = "no_action"
    if paper:
        for a in r["account_reads"]:
            a["account_class"] = "paper"
    return v.row_problems(r, "reviews", SCHEMA)


def test_insufficient_n_is_refused_on_a_real_money_row():
    assert any("insufficient_n is refused" in m for m in row("no_recommendation", "insufficient_n", src="none"))


def test_default_hold_is_refused_on_a_real_money_row():
    assert any("default_hold is refused" in m for m in row("hold", "default_hold"))


def test_a_judgement_hold_with_confidence_and_reason_is_accepted():
    assert row("hold", "judgement", src="judgement", conf=0.55, reason="thin cell; trend intact") == []


def test_a_judgement_hold_without_confidence_is_refused():
    assert row("hold", "judgement", src="judgement", reason="x")


def test_a_judgement_tighten_is_accepted():
    r = copy.deepcopy(BASE)
    r["reviewed_at"] = "2026-10-26T13:03:00Z"
    assert v.row_problems(r, "reviews", SCHEMA) == []


def test_no_recommendation_needs_could_not_look_and_a_reason():
    assert row("no_recommendation", "could_not_look", src="none", reason="packet table null") == []
    assert row("no_recommendation", "could_not_look", src="none")


def test_paper_rows_and_rows_before_the_rule_are_untouched():
    assert row("no_recommendation", "insufficient_n", src="none", paper=True) == []
    assert row("no_recommendation", "insufficient_n", src="none", at="2026-10-26T08:19:00Z") == []
