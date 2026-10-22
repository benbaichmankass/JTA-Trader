"""as_traded_stage0.py grades ONLY the incumbent decision_bar arm, with the unit's thresholds."""
import json

from scripts.research import as_traded_stage0 as ats


def _rows(rs, start_year=2021):
    return [{"entry_time": f"{start_year + i // 12}-{i % 12 + 1:02d}-01 00:00:00+00:00", "net_r": r}
            for i, r in enumerate(rs)]


def _g(rows):
    return ats.grade_arm(rows, n_floor=8, folds=4, fold_majority=3, holdout_frac=0.25, holdout_min=4)


def test_pass_fail_mixed_indeterminate():
    assert _g(_rows([0.5] * 48))["verdict"] == "pass"
    assert _g(_rows([-0.1] * 48))["verdict"] == "fail"
    # strong early, flat late: total > 0, holdout <= 0, only 2 of 4 folds positive -> fail
    assert _g(_rows([1.0] * 24 + [-0.01] * 24))["verdict"] == "fail"
    # strong early, late folds slightly positive except the holdout -> mixed
    mixed = _g(_rows([1.0] * 24 + [0.05] * 12 + [-0.02] * 12))
    assert mixed["verdict"] == "mixed", mixed
    assert _g(_rows([1.0] * 5))["verdict"] == "indeterminate"


def test_incumbent_arm_reads_the_strategies_block(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("strategies:\n  a: {decision_bar: closed}\n  b: {tp_r: 3}\n")
    assert ats.incumbent_arm("a", p) == "closed"
    assert ats.incumbent_arm("b", p) == "forming"
    assert ats.incumbent_arm("missing", p) == "forming"


def test_run_on_arms_dir_grades_incumbent_only(tmp_path):
    arms = tmp_path / "arms"
    arms.mkdir()
    (arms / "x__A_closed__trades.jsonl").write_text("\n".join(json.dumps(r) for r in _rows([-1.0] * 48)))
    (arms / "x__B_forming__trades.jsonl").write_text("\n".join(json.dumps(r) for r in _rows([0.5] * 48)))
    s = tmp_path / "s.yaml"
    s.write_text("strategies:\n  x: {tp_r: 3}\n")
    out = tmp_path / "out"
    ats.main(["--leg", "x", "--arms-dir", str(arms), "--out", str(out), "--strategies", str(s),
              "--n-floor", "8", "--folds", "4", "--fold-majority", "3", "--holdout-frac", "0.25",
              "--holdout-min", "4"])
    v = json.loads((out / "verdict.json").read_text())
    assert v["verdict"] == "pass" and v["measurement"]["legs"]["x"]["arm"] == "forming"
    assert v["measurement"]["legs"]["x"]["live_vs_as_traded"]["state"] == "not_measured"
