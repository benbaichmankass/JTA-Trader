"""CLAUDE-GRADE-LOOP: calibration rules, the desk grader, and the LTR grader's hold / brief-version / use-rule blocks."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts" / "ops"):
    sys.path.insert(0, str(_p))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cal = _load("claude_calibration", "scripts/ops/claude_calibration.py")
dg = _load("desk_grade", "scripts/ops/desk_grade.py")
gr = _load("live_review_grade", "scripts/ops/live_review_grade.py")


# --------------------------------------------------------------------------- calibration rules

def test_probability_is_indeterminate_below_min_n_but_still_prints_numbers():
    c = cal.probability([(0.9, 1.0)] * 5 + [(None, 1.0)])
    assert c["n"] == 5 and c["dropped_unpriced"] == 1 and c["verdict"].startswith("INDETERMINATE")
    assert c["brier"] is not None


def test_probability_flags_overconfidence():
    pts = [(0.9, 1.0)] * 5 + [(0.9, 0.0)] * 7          # says 0.9, hits 5/12
    c = cal.probability(pts)
    assert c["verdict"] == "OVERCONFIDENT" and c["overconfidence_gap"] > cal.OVERCONFIDENCE_GAP


def test_probability_calibrated_needs_positive_skill():
    pts = [(0.8, 1.0)] * 8 + [(0.8, 0.0)] * 2 + [(0.2, 0.0)] * 8 + [(0.2, 1.0)] * 2
    c = cal.probability(pts)
    assert c["verdict"] == "CALIBRATED" and c["skill"] > 0
    flat = cal.probability([(0.5, 1.0)] * 6 + [(0.5, 0.0)] * 6)  # always the base rate: no skill
    assert flat["verdict"] == "NO_SKILL"


def test_ordinal_monotone_and_indeterminate():
    pts = [("anecdote", -0.2)] * 5 + [("suggestive", 0.1)] * 5 + [("measured", 0.4)] * 5
    assert cal.ordinal(pts)["verdict"] == "MONOTONE"
    inv = [("anecdote", 0.5)] * 5 + [("measured", -0.5)] * 5
    assert cal.ordinal(inv)["verdict"] == "NOT_MONOTONE"
    assert cal.ordinal([("anecdote", 0.5)] * 5)["verdict"].startswith("INDETERMINATE")


# --------------------------------------------------------------------------- desk grader

def _packet(tmp: Path, pid: str, mean_r: float) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / f"{pid}.json").write_text(json.dumps({
        "history": {"r_unit": "atr_stop_1x", "rows": [
            {"symbol": "BTCUSDT", "side": "long", "timeframe": "1h", "horizon_bars": 12, "mean_r": mean_r, "n": 900},
            {"symbol": "BTCUSDT", "side": "long", "timeframe": "1h", "horizon_bars": 48, "mean_r": 9.0, "n": 900}]},
        "universe": [{"symbol": "BTCUSDT"}]}))


def _decision(i: int, action="propose_entry", conf="suggestive", pre_cutoff=False, p_hit=0.4, sha="aaaa"):
    d = {"decision_id": f"DD-{i}", "packet_id": "DP-1", "role": "entry_generation", "action": action,
         "judged_at": "2026-10-26T13:50:00Z", "info_cutoff_at": "2026-10-26T13:39:00Z", "confidence": conf,
         "pre_cutoff": pre_cutoff, "skill_sha": sha, "training": {"gate_eligible": True}, "proposal": None}
    if action == "propose_entry":
        d["proposal"] = {"symbol": "BTCUSDT", "side": "long", "timeframe": "1h", "horizon_bars": 10,
                         "entry": {"good_till_bars": 2}, "tp": {"p_hit": p_hit}, "expected_r_net": 0.5}
    return d


def _outcome(i: int, net_r, kind="replayed", reason="tp_hit"):
    return {"decision_id": f"DD-{i}", "kind": kind, "net_r": net_r, "close_reason": reason}


def test_desk_population_counts_every_state(tmp_path):
    _packet(tmp_path, "DP-1", 0.0)
    ds = [_decision(0), _decision(1), _decision(2, action="no_trade"), _decision(3), _decision(4, pre_cutoff=True)]
    os_ = [_outcome(0, 0.5), {"decision_id": "DD-1", "kind": "expired_unfilled", "net_r": None},
           {"decision_id": "DD-2", "kind": "not_computable", "net_r": None, "reason": "DESK-20"}, _outcome(4, 1.0)]
    g = dg.grade(ds, os_, packets=tmp_path)
    p = g["population"]
    assert (p["n_decisions"], p["n_proposals"], p["n_proposals_priced"], p["n_proposals_expired_unfilled"],
            p["n_proposals_awaiting"], p["n_priced_gradeable"], p["n_no_trade"]) == (5, 4, 2, 1, 1, 1, 1)
    assert p["not_computable_reasons"] == {"DESK-20": 1}
    assert g["absolute"]["n"] == 1                       # the pre-cutoff decision is reported, never graded
    assert "Desk" in dg.render(g, "t")


def test_desk_random_baseline_pairs_on_nearest_horizon(tmp_path):
    _packet(tmp_path, "DP-1", 0.2)
    g = dg.grade([_decision(0)], [_outcome(0, 0.5)], packets=tmp_path)
    assert abs(g["vs_random"]["mean"] - 0.3) < 1e-9      # horizon 10 pairs with the 12-bar cell, not the 48


def test_desk_edge_needs_n_and_interval_and_gate_needs_all_three(tmp_path):
    _packet(tmp_path, "DP-1", 0.0)
    n = dg.EDGE_MIN_N
    ds = [_decision(i) for i in range(n)]
    os_ = [_outcome(i, 0.5 + (0.1 if i % 2 else -0.1)) for i in range(n)]
    g = dg.grade(ds, os_, packets=tmp_path)
    assert g["absolute"]["verdict"] == "EDGE" and g["vs_random"]["verdict"] == "EDGE"
    assert g["promotion_gate"]["verdict"] == "NOT_YET" and g["promotion_gate"]["failing"] == ["vs_system"]
    g2 = dg.grade(ds, os_, packets=tmp_path, system_trades=lambda s, e, syms: [-0.5, -0.4, -0.6] * 12)
    assert g2["system"]["vs_system"]["verdict"] == "EDGE" and g2["promotion_gate"]["verdict"] == "ELIGIBLE_TO_PROPOSE"
    thin = dg.grade(ds[: n - 1], os_[: n - 1], packets=tmp_path)
    assert thin["absolute"]["verdict"].startswith("INDETERMINATE")


def test_desk_system_could_not_look_is_not_zero(tmp_path):
    _packet(tmp_path, "DP-1", 0.0)
    g = dg.grade([_decision(0)], [_outcome(0, 0.5)], packets=tmp_path, system_trades=lambda s, e, syms: None)
    assert g["system"]["state"] == "could_not_look" and "EDGE" not in g["promotion_gate"]["verdict"]


def test_desk_realised_outranks_replay_and_splits_by_sha(tmp_path):
    _packet(tmp_path, "DP-1", 0.0)
    ds = [_decision(0, sha="aaaa"), _decision(1, sha="bbbb")]
    os_ = [_outcome(0, 0.5), _outcome(0, -0.2, kind="realised", reason="sl_hit"), _outcome(1, 1.0)]
    g = dg.grade(ds, os_, packets=tmp_path)
    assert g["by_skill_sha"]["aaaa"]["proposals_priced"]["mean"] == -0.2
    assert set(g["by_skill_sha"]) == {"aaaa", "bbbb"}
    assert g["calibration"]["p_hit"]["n"] == 2


def test_desk_grading_window_spans_horizon_plus_good_till():
    s, e = dg.grading_window(_decision(0))
    assert s == datetime(2026, 10, 26, 13, 39, tzinfo=timezone.utc) and (e - s).total_seconds() == 12 * 3600


# --------------------------------------------------------------------------- LTR grader additions

def _rv(i, action="tighten_sl", conf=None, open_r=0.4, sha="s1", src="judgement"):
    return {"review_id": f"LR-{i}", "order_package_id": f"pkg-{i}", "trade_id": i, "leg": "t", "reviewed_at": "2026-10-26T12:00",
            "skill_sha": sha, "state": {"open_r": open_r},
            "recommendation": {"action": action, "judgement_confidence": conf, "evidence_source": src, "basis": "judgement"},
            "apply_policy": {}, "shadow_policy": {}}


def _res(i, action="tighten_sl", delta=None, net_r=None, applied=False):
    if action == "hold":
        return {"review_id": f"LR-{i}", "order_package_id": f"pkg-{i}", "action": "hold", "applied": False,
                "state": "not_a_call", "reason": "no_path_change", "leg": "t",
                "outcome": None if net_r is None else {"net_r": net_r, "delta_r": 0.0}}
    return {"review_id": f"LR-{i}", "order_package_id": f"pkg-{i}", "action": action, "applied": applied,
            "state": "priced", "reason": None, "leg": "t", "outcome": {"delta_r": delta, "replay_fidelity": "replay_matches_realised"}}


def test_hold_is_graded_against_closing_at_review():
    rvs = [_rv(0, "hold", 0.6, open_r=0.4), _rv(1, "hold", 0.6, open_r=0.4)]
    res = [_res(0, "hold", net_r=1.0), _res(1, "hold", net_r=None)]   # 1 is still open: not graded
    g = gr.grade(rvs, res)
    assert g["hold_vs_close"]["n"] == 1 and abs(g["hold_vs_close"]["mean_dr"] - 0.6) < 1e-9
    assert g["calibration"]["hold/all"]["n"] == 1


def test_calibration_and_versions_split_by_sha():
    rvs = [_rv(i, conf=0.8, sha="s1" if i < 6 else "s2") for i in range(12)]
    res = [_res(i, delta=(0.3 if i % 3 else -0.3)) for i in range(12)]
    g = gr.grade(rvs, res)
    assert g["calibration"]["tighten_sl/all"]["n"] == 12
    assert {k: v["n_reviews"] for k, v in g["by_skill_sha"].items()} == {"s1": 6, "s2": 6}
    assert g["by_skill_sha"]["s1"]["calibration"]["n"] == 6


def test_use_rules_narrow_widen_and_hold_scope():
    n = gr.USE_MIN_N
    neg = gr.grade([_rv(i) for i in range(n)], [_res(i, delta=-0.3 + (0.05 if i % 2 else -0.05)) for i in range(n)])
    assert neg["use_rules"]["tighten_sl"]["verdict"] == "PROPOSE_NARROW"
    pos = gr.grade([_rv(i) for i in range(n)], [_res(i, delta=0.3 + (0.05 if i % 2 else -0.05)) for i in range(n)])
    assert pos["use_rules"]["tighten_sl"]["verdict"] == "PROPOSE_WIDEN"
    # positive mean but an OVERCONFIDENT reviewer does not widen
    over = gr.grade([_rv(i, conf=0.95) for i in range(n)],
                    [_res(i, delta=(0.9 if i < 6 else -0.05)) for i in range(n)])
    assert over["calibration"]["tighten_sl/all"]["verdict"] == "OVERCONFIDENT"
    assert over["use_rules"]["tighten_sl"]["verdict"] != "PROPOSE_WIDEN"
    thin = gr.grade([_rv(i) for i in range(n - 1)], [_res(i, delta=-0.3) for i in range(n - 1)])
    assert thin["use_rules"]["tighten_sl"]["verdict"].startswith("HOLD_SCOPE (INDETERMINATE")
    assert "Use rules" in gr.render(neg, "t")


# --------------------------------------------------------------------------- ML use rule (c)

def test_call_class_weight_three_states():
    from ml.datasets.families.claude_judgments import CALL_WEIGHT_MIN_N, call_class_weight
    assert call_class_weight(None)[0] == 0.0
    assert call_class_weight({"n": CALL_WEIGHT_MIN_N - 1, "ci95": [0.1, 0.2]})[0] == 0.0
    assert call_class_weight({"n": 40, "ci95": [-0.1, 0.2]}) == (0.0, "no_demonstrated_skill: the 95% interval includes 0")
    assert call_class_weight({"n": 40, "ci95": [-0.3, -0.1]})[0] == 0.0
    assert call_class_weight({"n": 40, "ci95": [0.1, 0.3]}, "OVERCONFIDENT")[0] == 0.5
    assert call_class_weight({"n": 40, "ci95": [0.1, 0.3]}, "CALIBRATED")[0] == 1.0


def test_claude_feature_gate_passes_only_on_an_oos_edge_record(tmp_path):
    lint = _load("ccjm_t", "scripts/ci/check_claude_judgments_manifests.py")
    m = {"dataset": {"family": "trade_outcomes"}, "claude_feature_gate": {"evidence": "ev.json"},
         "trainer_config": {"feature_columns": ["claude_confidence"]}}
    (tmp_path / "ev.json").write_text(json.dumps({"verdict": "EDGE", "out_of_sample": False}))
    assert lint.use_rule_problems(m, root=tmp_path)
    (tmp_path / "ev.json").write_text(json.dumps({"verdict": "EDGE", "out_of_sample": True}))
    assert lint.use_rule_problems(m, root=tmp_path) == []
