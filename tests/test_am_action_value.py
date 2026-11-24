"""AM v2 Stage B iteration 2 (scripts/research/am_action_value.py): the action menu's eligibility and levels, the EV decision rule (first row that clears
its cut, the best action there, once), the matched control (same kind, an eligible row), the label/fit/shard round trip on synthetic data, and the
diagnostic report. Offline: synthetic bars, no network."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research", REPO / "tests"):
    sys.path.insert(0, str(p))

import am_action_value as V
import am_policy_arm as P
from test_am_policy_arm import FLAT, ctx_for

THR = {"stop_first": {"p90": 0.5}, "dip_recovers": {"p50": 0.1, "p90": 0.5}}


def preds5(n, q50=1.0, q90=2.0, stop=0.0, dip=0.0, r1=0.5, r2=0.2):
    return {"q0.5": [q50] * n, "q0.9": [q90] * n, "stop_first": [stop] * n, "dip_recovers": [dip] * n, "reach_1": [r1] * n, "reach_2": [r2] * n}


def _row(k, open_r):
    return {"k": k, "features": {"open_r": open_r}}


def test_action_menu_levels_and_eligibility():
    ctx, _ = ctx_for(FLAT, tp=106.0)
    pr = {"q50": 0.1, "q90": 0.3, "reach_1": 0.5, "reach_2": 0.2, "p_stop": 0.1, "p_dip": 0.0}
    s = V.action_spec("bank_q50", ctx, _row(1, 0.2), pr)
    assert s["kind"] == "bank_at" and abs(s["lvl_r"] - (0.2 + P.TP_MIN_DIST_R)) < 1e-9          # floor of TP_MIN_DIST_R above the close
    assert V.action_spec("bank_1r", ctx, _row(1, 0.8), pr) is None                               # closer than TP_MIN_DIST_R to +1R
    assert V.action_spec("bank_1r", ctx, _row(1, 0.7), pr)["lvl_r"] == 1.0
    assert V.action_spec("breakeven", ctx, _row(1, 0.4), pr) is None
    assert V.action_spec("breakeven", ctx, _row(1, 0.5), pr)["lvl_r"] == 0.0
    assert V.action_spec("lock_half", ctx, _row(1, 1.2), pr)["lvl_r"] == pytest.approx(0.6)
    assert V.action_spec("tighten_half", ctx, _row(1, -0.4), pr)["lvl_r"] == pytest.approx(-0.7)
    b = V.action_spec("bank_now", ctx, _row(1, 0.3), pr)
    assert b["kind"] == "close" and b["frac"] == V.BANK_FRAC


def test_loosen_class_needs_the_dip_cut():
    ctx, _ = ctx_for(FLAT, tp=106.0, pre_low=96.0)              # a pre-entry swing far below the stop: a structure level exists
    lo = {"q50": 1, "q90": 2, "reach_1": .5, "reach_2": .2, "p_stop": 0, "p_dip": 0.4}
    hi = dict(lo, p_dip=0.6)
    assert V.action_spec("loosen_struct", ctx, _row(1, 0.3), lo) is not None
    assert V.eligible("av_loosen", "loosen_struct", ctx, _row(1, 0.3), lo, THR) is None
    assert V.eligible("av_loosen", "loosen_struct", ctx, _row(1, 0.3), hi, THR) is not None


def test_decide_fires_first_row_clearing_cut_once_with_best_action():
    ctx, _ = ctx_for(FLAT, tp=106.0)
    rows = P.decision_rows(ctx)
    n = len(rows)
    ev = {"bank_now": [0.0] * n, "bank_q50": [0.0] * n, "bank_1r": [0.0] * n, "bank_2r": [0.0] * n}
    ev["bank_q50"][2], ev["bank_now"][2] = 0.05, 0.08          # row 3: both clear, bank_now is better
    ev["bank_q50"][4] = 0.5                                    # a better row later never matters: the first clearing row decides
    cuts = {a: 0.01 for a in ev}
    out = V.decide_av("av_bank", ctx, rows, preds5(n), THR, ev, cuts)
    assert len(out) == 1 and out[0]["name"] == "bank_now" and out[0]["k"] == rows[2]["k"]
    assert V.decide_av("av_bank", ctx, rows, preds5(n), THR, ev, {a: 1.0 for a in ev}) == []    # nothing clears: HOLD


def test_control_is_same_kind_at_an_eligible_row():
    ctx, _ = ctx_for(FLAT, tp=106.0)
    rows = P.decision_rows(ctx)
    pred = preds5(len(rows))
    spec = {"name": "breakeven"}
    ok = {r["k"] for r in rows if r["features"]["open_r"] >= 0.5}
    for d in range(20):
        cs = V.control_av("av_tighten", ctx, rows, pred, THR, spec, P.control_rng("k1", "av_tighten", d))
        if not ok:
            assert cs == []
        else:
            assert len(cs) == 1 and cs[0]["k"] in ok and cs[0]["kind"] == "set_stop"


def test_label_fit_shard_round_trip(tmp_path):
    ctx, _job = ctx_for(FLAT, tp=106.0)
    rows = P.decision_rows(ctx)
    pred = preds5(len(rows))
    X = V.av_features(ctx, rows, pred, P.feature_matrix(ctx, rows, 0))
    assert X.shape == (len(rows), len(V.AV_FEATS))
    lab = V.label_trade(ctx, rows, pred, X, random.Random(1))
    assert lab["Y"].shape == (min(V.ROWS_PER_TRADE, len(rows)), len(V.ACTIONS))
    # an action that cannot change the path has label exactly 0 (bank_2r far above a flat path)
    assert np.allclose(lab["Y"][:, V.ACTIONS.index("bank_2r")][~np.isnan(lab["Y"][:, V.ACTIONS.index("bank_2r")])], 0.0)


def test_report_runs_on_diag_output(tmp_path):
    import am_policy_diag_report as R
    rec = {"base": -1.0, "base_reason": "stop", "base_mfe": 0.5, "n_rows": 3, "tp0_r": 3.0, "st": "trend_donchian", "cls": {
        "bank": {"n": 2, "pol": 0.1, "fire": [{"k": 1, "open_r": 0.2, "lvl_r": 1.0}], "bank_fill_r": 1.0, "ctl": [0.0, 0.2],
                 "ctl_fire": [{"k": 2, "open_r": 0.1, "lvl_r": 1.1}], "ctl_bank_fill_r": [None]}},
           "single": [{"k": 1, "open_r": 0.2, "peak_r": 0.3, "mae_r": -0.1, "bars_open": 1, "q50": 1.0, "q90": 2.0, "p_stop": 0.2, "p_dip": 0.01,
                       "d": {"close_half": 0.4}}]}
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps(rec) + "\n")
    r = R.report(str(p))
    assert r["bank"]["n_fired"] == 1 and r["single_action_ex_post"]["close_half"]["mean_delta"] == 0.4
