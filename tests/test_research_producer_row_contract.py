"""RESEARCH-PRODUCER-ROW-DEFECTS (2026-11-13): every producer's per-row status / n / verdict must satisfy
research_result.validate, or the run's record is refused at emit and never lands (the orphan class).

Each case builds the producer's rows with its OWN code and feeds them through the real validator, plus the
collector's non-measured-verdict void. The orphans named on the row:
  RQ-20261026-bf56-02/-03  desk_replay_driver score   (no_data carrying an n; measured with not_applicable)
  RQ-20261105-d256-03      fidelity_remeasure          (rows with no population / n)
  RQ-20261105-025          leg_corpus_s1               (producer_failed carrying indeterminate)
  RQ-20261014-470a-11      stage0_capital_day_census   (no_data carrying no_action_warranted / an n)
  RQ-20261101-b623-01      ml_entry_v2_run             (measured, n null -- fixed at source before this row)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

from scripts.research import research_result as rr  # noqa: E402


def _problems(rows: List[Dict[str, Any]]) -> List[str]:
    out = []
    for i, part in enumerate(rows, 1):
        rec = rr.build(research_unit="RQ-20261113-001", decision_rule_id="RULE-T", decision_rule_registered_at="2026-11-13",
                       verdict=str(part.get("verdict", "")), read_state=str(part.get("read_state", "")),
                       population_description=str(part.get("population", "")),
                       n=part["n"] if "n" in part else ..., workflow="w", run_id="1", run_attempt="1", run_url="u",
                       commit_sha="a" * 40, tool="t", power_state="accruing",
                       artifact_store="comms/research/x", artifact_locator="comms/research/x/")
        out += [f"row {i}: {p}" for p in rr.validate(rec)]
    return out


# ── desk_replay_driver ──────────────────────────────────────────────────────────────────────────────────────────────
def test_desk_replay_score_rows_validate_and_keep_pooled_verdict():
    from scripts.research import desk_replay_driver as drv
    res = {"verdict": "fail", "per_leg": [
        {"leg": "a", "n_obs": 31, "state": "measured", "mean_dR": -0.16, "ci": [-0.58, 0.19]},
        {"leg": "b", "n_obs": 15, "state": "insufficient_n", "mean_dR": None, "ci": None},   # the bf56 xrp row
        {"leg": "c", "n_obs": 0, "state": "insufficient_n", "mean_dR": None, "ci": None}]}
    rows = drv.score_records(res, "in_trade")
    assert _problems(rows) == []
    assert [(r["read_state"], r["n"], r["verdict"]) for r in rows] == [
        ("measured", 31, "fail"), ("measured", 15, "fail"), ("no_data", None, "not_applicable")]
    assert rows[1]["mean_dR"] is None and "withheld" in rows[1]["population"]
    assert all("POOLED" in r["population"] for r in rows if r["read_state"] == "measured")


# The refused run's own per-leg block, copied verbatim from comms/research/RQ-20261026-bf56-02/40710666532/verdict.json
# (inlined: comms/research/RQ-*/** is push paths-ignore, so a test may not read it -- test_push_paths_ignore_bot_data).
BF56_02_PER_LEG = [
    {"leg": "ada_pullback_2h", "n_obs": 31, "state": "measured", "mean_dR": -0.1635, "ci": [-0.5863, 0.1896]},
    {"leg": "trend_donchian_eth_4h", "n_obs": 103, "state": "measured", "mean_dR": -0.0051, "ci": [-0.0665, 0.0537]},
    {"leg": "trend_donchian_xrp_4h", "n_obs": 15, "state": "insufficient_n", "mean_dR": None, "ci": None},
    {"leg": "xrp_pullback_2h", "n_obs": 27, "state": "measured", "mean_dR": -0.1081, "ci": [-0.4575, 0.229]}]


def test_desk_replay_score_rows_from_the_bf56_orphan_measurement_validate():
    """The real refused run: the pre-fix rows (as committed) fail the validator; the fixed builder's rows pass."""
    from scripts.research import desk_replay_driver as drv
    old = [{"read_state": "measured" if r["state"] == "measured" else "no_data", "leg": r["leg"],
            "population": f"{r['leg']} in_trade", "n": r["n_obs"], "verdict": "not_applicable"} for r in BF56_02_PER_LEG]
    assert _problems(old), "the pre-fix rows must still show the defect (the probe can find a positive)"
    assert _problems(drv.score_records({"verdict": "fail", "per_leg": BF56_02_PER_LEG}, "in_trade")) == []


def test_desk_replay_selfcheck_rows_never_carry_n_zero_on_no_data():
    from scripts.research import desk_replay_driver as drv
    rows = drv.selfcheck_records({"verdict": "pass", "per_leg": {"a": {"trades": 9, "replayed": 9},
                                                                 "b": {"trades": 3, "replayed": 0}}})
    assert _problems(rows) == []
    assert rows[1] == {**rows[1], "n": None, "verdict": "not_applicable", "read_state": "no_data"}


# ── fidelity_remeasure ──────────────────────────────────────────────────────────────────────────────────────────────
def _fid_row(**kw):
    base = {"leg": "trend_donchian_sol_4h", "rule_id": "R", "record_n": 116, "window": ["s", "e"]}
    return {**base, **kw}


def test_fidelity_rows_carry_population_and_n_and_validate():
    import fidelity_remeasure as fr
    arms = {"approximate": {"n": 102, "net_r": 11.6}, "faithful": {"n": 102, "net_r": 11.6}}
    rows = [_fid_row(arms=arms, read_state="measured", verdict="indeterminate", note="control did not reproduce"),
            _fid_row(read_state="no_data", verdict="indeterminate", note="fetch failed"),
            _fid_row(read_state="not_attempted", verdict="indeterminate", note="no source run"),
            _fid_row(arms={"approximate": {"error": "x"}}, read_state="producer_failed", verdict="indeterminate")]
    v = fr.assemble_verdict(["trend_donchian_sol_4h"], rows)
    assert _problems(v["records"]) == []
    assert [r["n"] for r in v["records"]] == [102, None, None, None]
    assert v["read_state"] == "measured" and v["n"] == 102 and v["verdict"] == "indeterminate"


def test_fidelity_run_that_measured_nothing_is_not_measured_at_top_level():
    import fidelity_remeasure as fr
    v = fr.assemble_verdict(["x"], [_fid_row(read_state="no_data", verdict="indeterminate")])
    assert (v["read_state"], v["verdict"], v["n"]) == ("producer_failed", "not_applicable", None)
    assert _problems([v]) == []


def test_fidelity_d256_orphan_row_validates_after_contract_row():
    """Row copied from comms/research/RQ-20261105-d256-03/42134900236/verdict.json (inlined: paths-ignore)."""
    import fidelity_remeasure as fr
    faithful = {"n": 102, "net_r": 11.678, "net_r_fee_only": 13.4496, "still_omitted": []}
    old = {"leg": "trend_donchian_sol_4h", "rule_id": "RULE-RQ1011-001-FAITHFUL-STAGE0", "record_n": 116,
           "record_net_r_oos": 36.8572, "window": ["2023-10-29 00:00:00+00:00", "2026-10-27 20:00:00+00:00"],
           "arms": {"approximate": dict(faithful), "faithful": faithful}, "control_reproduces_record": False,
           "verdict": "indeterminate", "read_state": "measured", "note": "could_not_measure: ..."}
    assert _problems([old])
    fixed = fr.contract_row(old)
    assert _problems([fixed]) == [] and fixed["n"] == 102


# ── leg_corpus_s1 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_leg_corpus_s1_producer_failed_run_is_not_applicable(tmp_path, monkeypatch):
    import leg_corpus_s1 as lc
    import path_metric_giveback as pmg

    def boom(*a, **k):
        raise ValueError("ml_entry: harness None")
    monkeypatch.setattr(lc, "money_families", lambda root=None: {"None_1h": ["ml_entry"]})
    monkeypatch.setattr(lc, "money_legs", lambda root=None: {"ml_entry": {"timeframe": "1h"}})
    monkeypatch.setattr(pmg, "run_leg_paths", boom)
    lc.run_family("None_1h", tmp_path, days=10, start=None, end=None, paths=False, non_crypto_source="none")
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert (v["read_state"], v["verdict"], v["n"]) == ("producer_failed", "not_applicable", None)
    assert _problems([v]) == []


# ── stage0_capital_day_census ───────────────────────────────────────────────────────────────────────────────────────
def test_census_no_record_rows_are_not_applicable_with_null_n():
    import stage0_capital_day_census as cd
    c = {"rows": [{"class": "prop", "account": "p1", "leg": "a", "grade": "no_record", "n": 28, "why": "no bt"},
                  {"class": "real", "account": "r1", "leg": "b", "grade": "drag", "n": 120}],
         "by_class": {"prop": {"legs": 1, "pulls_weight": 0, "drag": 0, "underpowered": 0, "no_record": 1},
                      "real": {"legs": 1, "pulls_weight": 0, "drag": 1, "underpowered": 0, "no_record": 0}}}
    v = cd.verdict(c, 30, 0.6)
    assert _problems(v["records"]) == [] and _problems([v]) == []
    assert v["records"][0]["n"] is None and v["records"][0]["record_n_trades_oos"] == 28
    empty = cd.verdict({"rows": [c["rows"][0]], "by_class": {"prop": c["by_class"]["prop"]}}, 30, 0.6)
    assert (empty["read_state"], empty["verdict"], empty["n"]) == ("no_data", "not_applicable", None)
    assert _problems([empty]) == []


# ── ml_entry_v2_run (already fixed at source; pin it on the committed b623-01 orphan's result file) ─────────────────
def test_ml_entry_v2_timeframe_verdict_derives_n_from_the_b623_result(tmp_path):
    """The b623-01 run 41567569662 result's verdict fields, copied (inlined: paths-ignore)."""
    import ml_entry_v2_run as mer
    res = {"unit": "RQ-20261101-b623-01", "schema": "ml_entry_timeframe/1", "timeframe": "5m", "verdict": "indeterminate",
           "gated_verdict": "indeterminate",
           "rows": {"1h/bar": {"decision_rows": 665209, "symbols": 60}, "5m/bar": {"decision_rows": 8016428, "symbols": 60}}}
    (tmp_path / "RQ-20261101-b623-01_result.json").write_text(json.dumps(res))
    assert mer.write_verdict("RQ-20261101-b623-01", tmp_path)
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["n"] == 665209 + 8016428
    assert _problems([v]) == []


# ── collector: void a verdict on a row that measured nothing; never touch n or a measured row ──────────────────────
def test_collector_voids_only_nonmeasured_verdicts(tmp_path):
    from scripts.research import collect_runner_results as crr
    rows = [{"read_state": "measured", "n": 5, "verdict": "pass", "population": "p"},
            {"read_state": "no_data", "n": None, "verdict": "no_action_warranted", "population": "p"},
            {"read_state": "no_data", "n": 7, "verdict": "not_applicable", "population": "p"}]
    rf = tmp_path / "records.jsonl"
    rf.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = crr._void_nonmeasured_verdict({"read_state": "producer_failed", "verdict": "indeterminate", "n": "null",
                                         "records_file": str(rf)}, tmp_path)
    assert out["verdict"] == "not_applicable" and "voided" in out["note"]
    fixed = [json.loads(ln) for ln in Path(out["records_file"]).read_text().splitlines()]
    assert fixed[0] == rows[0]                                   # measured row untouched
    assert fixed[1]["verdict"] == "not_applicable" and fixed[1]["n"] is None
    assert fixed[2]["n"] == 7                                    # n is never rewritten: that defect still refuses
    assert json.loads(rf.read_text().splitlines()[1])["verdict"] == "no_action_warranted"   # committed file untouched
    same = {"read_state": "measured", "verdict": "fail", "n": "3"}
    assert crr._void_nonmeasured_verdict(same, tmp_path) == same
