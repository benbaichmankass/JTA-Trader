"""CF-D4-PERFREVIEW-TABLE: the counterfactual CHECK table (performance-review C14) is computed from a cf_bulk_live run, carries
its population, marks low-fidelity legs unreadable, and adds no gate (it only prints)."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_check_table as ct  # noqa: E402


def _rec(leg, actual, replay, arms):
    a = [{"arm_id": "actual", "net_r": actual, "resolved": True}, {"arm_id": "replayed_actual", "net_r": replay, "resolved": True},
         {"arm_id": "original_brackets", "net_r": replay, "resolved": True}]
    a += [{"arm_id": k, "net_r": v, "resolved": True} for k, v in arms.items()]
    return {"strategy": leg, "arms": a, "fidelity": {"abs_gap_r": 0.0}}


def _run(tmp_path, recs, per_leg):
    d = tmp_path / "run"
    d.mkdir()
    with gzip.open(d / "records.jsonl.gz", "wt") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    (d / "fidelity.json").write_text(json.dumps({"rule": {"tol_r": 0.1, "frac": 0.8, "min_leg_n": 10}, "overall": {"verdict": "FAIL", "frac_within_tol": 0.5, "n_with_gap": len(recs), "median_abs_gap_r": 0.2},
                                                 "per_leg": per_leg}))
    (d / "manifest.json").write_text(json.dumps({"population": {"closed_n": 99}, "could_not_grade_by_reason": {"pairs_two_leg": 7}}))
    return d


def test_best_arm_delta_population_and_readability(tmp_path):
    recs = [_rec("good", 0.0, 0.0, {"armA": 0.5, "armB": -0.2}) for _ in range(12)] + [_rec("bad", 1.0, 0.0, {"armA": 9.0}) for _ in range(12)]
    t = ct.build(_run(tmp_path, recs, {"good": {"verdict": "PASS", "frac_within_tol": 0.9, "n_with_gap": 12},
                                       "bad": {"verdict": "FAIL", "frac_within_tol": 0.1, "n_with_gap": 12}}))
    rows = {r["leg"]: r for r in t["legs"]}
    assert t["population"]["graded"] == 24 and t["population"]["closed_n"] == 99 and t["population"]["could_not_grade_by_reason"] == {"pairs_two_leg": 7}
    g = rows["good"]
    assert g["readable"] is True and g["best_arm"]["arm_id"] == "armA" and g["best_arm"]["delta_net_r"] == 0.5 and g["arms_searched"] == 2
    assert g["best_arm"]["n"] == 12 and g["best_arm"]["ci95"] == [0.5, 0.5]
    assert rows["bad"]["readable"] is False and rows["bad"]["fidelity"] == "FAIL"
    out = ct.render(t)
    assert "ESTIMATED_LOW_FIDELITY" in out and "in-sample" in out.lower()


def test_unresolved_and_null_arms_are_not_counted_as_zero(tmp_path):
    r = _rec("x", 0.0, 0.0, {"armA": None, "armB": 0.3})
    r["arms"][-1]["resolved"] = False                              # armB unresolved: excluded
    t = ct.build(_run(tmp_path, [r] * 6, {}))
    assert t["legs"][0]["best_arm"] is None and t["legs"][0]["fidelity"] == "INDETERMINATE" and t["legs"][0]["readable"] is False


def test_the_check_adds_no_gate():
    src = (REPO / "scripts/research/cf_check_table.py").read_text()
    assert "sys.exit(1)" not in src and "raise SystemExit" not in src and "return 1" not in src      # prints; never blocks
    assert "C14" in (REPO / ".claude/skills/performance-review/SKILL.md").read_text()
