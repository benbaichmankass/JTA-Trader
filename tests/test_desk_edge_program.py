"""DESK-EDGE-PROGRAM: the information-ceiling harness and the dev loop (synthetic data, no network, no LLM)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import desk_edge_ceiling as ce  # noqa: E402
from scripts.research import desk_edge_devloop as dl  # noqa: E402
from scripts.research import desk_gen_replay_driver as d  # noqa: E402

T0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())


def _acts(n_cut=60, syms=("AAA", "BBB", "CCC"), signal=0.0, seed=0, fold=2):
    """Synthetic actions: y = signal * x + noise, one action per (cutoff, symbol, side)."""
    rng = np.random.default_rng(seed)
    rows, xs = [], []
    for c in range(n_cut):
        for s in syms:
            for side in ("long", "short"):
                x = rng.normal()
                y = signal * x + rng.normal()
                rows.append({"cutoff": T0 + c * 86400, "fold": fold, "week": d.iso_week(T0 + c * 86400), "symbol": s, "side": side,
                             "geom": "GJ", "net_r": y + 0.1, "days": 1.0, "y": y})
                xs.append(x)
    return rows, np.array(xs)


# ----------------------------------------------------------------------------- ceiling
def test_policy_picks_cap_take_and_distinct_symbols():
    rows, x = _acts()
    picks = ce.policy_picks(rows, x, take_frac=0.25, cap=2)
    cuts = {rows[j]["cutoff"] for j in picks}
    assert len(cuts) == 15                                   # 25% of 60 cutoffs
    for c in cuts:
        js = [j for j in picks if rows[j]["cutoff"] == c]
        assert len(js) == 2 and len({rows[j]["symbol"] for j in js}) == 2
    # the chosen cutoffs are those with the highest best prediction (labels are never read)
    best = {}
    for j, r in enumerate(rows):
        best[r["cutoff"]] = max(best.get(r["cutoff"], -9), x[j])
    assert min(best[c] for c in cuts) >= sorted(best.values(), reverse=True)[14]


def test_s3_of_selected_rows_is_the_driver_statistic():
    rows, x = _acts(signal=0.5)
    sr = ce.s_rows(rows, range(len(rows)))
    st = d.cluster_stats(sr, draws=500)
    assert st["paired_diff_vs_random"] == pytest.approx(np.mean([r["y"] for r in rows]))
    lo, hi = ce.cluster_ci(sr, "diff", 0.05, draws=2000)
    assert lo < st["paired_diff_vs_random"] < hi


def test_planted_signal_reads_present_and_noise_does_not():
    rows, x = _acts(n_cut=400, signal=0.8, seed=1)
    picks = ce.policy_picks(rows, x)
    s3 = np.mean([rows[j]["y"] for j in picks])
    assert s3 > 0.5                                          # a real signal is found by the selection
    rows0, x0 = _acts(n_cut=400, signal=0.0, seed=2)
    picks0 = ce.policy_picks(rows0, x0)
    assert abs(np.mean([rows0[j]["y"] for j in picks0])) < 0.25


def test_side_signing_of_packet_features():
    pf = {"BTCUSDT": {"atr_pct": 0.6, "htf_trend": "trending", "session": "us", "dist_high_atr": 1.0, "dist_low_atr": 3.0}}
    for side in ("long", "short"):
        for h in ce.HORIZONS:
            for st in ("mean_r", "sd_r", "p10_r", "p50_r", "p90_r", "mean_cost_r"):
                pf["BTCUSDT"][f"br_{side}_h{h}_{st}"] = 0.1 if side == "long" else -0.2
    lo = ce.p_action_features(pf, "BTCUSDT", "long")
    sh = ce.p_action_features(pf, "BTCUSDT", "short")
    assert lo["room_atr"] == 1.0 and sh["room_atr"] == 3.0     # room ahead = swing in the trade's direction
    assert lo["br_h48_mean_r"] == 0.1 and sh["br_h48_mean_r"] == -0.2
    assert sh["br_opp_h48_mean_r"] == 0.1
    assert lo["htf_trending"] == 1.0 and lo["sess_us"] == 1.0


def test_walk_forward_embargo_and_fold_order(monkeypatch):
    rows = []
    for f in (1, 2, 3):
        for c in range(40):
            rows.append({"cutoff": T0 + (f * 1000 + c) * 3600, "fold": f, "week": "w", "y": float(f), "symbol": "A", "side": "long"})
    seen = {}

    def fake(learner, Xtr, ytr, Xte, seed=0):
        seen[len(seen)] = set(ytr.tolist())
        return np.zeros(len(Xte))
    monkeypatch.setattr(ce, "fit_predict", fake)
    monkeypatch.setattr(ce, "TEST_FOLDS", (2, 3))
    X = np.zeros((len(rows), 1))
    p = ce.walk_forward(rows, X, "ridge")
    assert np.isnan(p[:40]).all() and np.isfinite(p[40:]).all()
    assert seen[0] == {1.0}                                    # fold 2 trains on fold 1 only
    assert seen[1] <= {1.0, 2.0}                               # fold 3 never sees fold 3


def test_verdict_rule_branches():
    good = {"paired_diff_vs_random": 0.2, "S3_ci_corrected": [0.05, 0.4]}
    flat = {"paired_diff_vs_random": 0.0, "S3_ci_corrected": [-0.05, 0.06]}
    wide = {"paired_diff_vs_random": 0.05, "S3_ci_corrected": [-0.1, 0.2]}
    ic_ok, ic_no = {"ci_corrected": [0.01, 0.05]}, {"ci_corrected": [-0.01, 0.02]}
    f_ok, f_no = {"2": 0.1, "3": 0.2, "4": -0.1}, {"2": 0.1, "3": -0.2, "4": -0.1}
    assert ce.verdict_for({"a": good}, {"a": ic_ok}, {"a": f_ok})[0] == "present"
    assert ce.verdict_for({"a": good}, {"a": ic_ok}, {"a": f_no})[0] == "inconclusive"
    assert ce.verdict_for({"a": flat, "b": flat}, {"a": ic_no, "b": ic_no}, {"a": f_no, "b": f_no})[0] == "absent"
    assert ce.verdict_for({"a": flat, "b": wide}, {"a": ic_no, "b": ic_no}, {"a": f_no, "b": f_no})[0] == "inconclusive"


def test_geometries_include_the_registered_six_and_gj():
    names = [g[0] for g in ce.GEOMETRIES]
    assert names[:6] == [g[0] for g in d.REFERENCE_GEOMETRIES] and names[-1] == "GJ"


# ----------------------------------------------------------------------------- dev loop
def test_windows_are_disjoint_and_ordered():
    assert dl.FULL_RUN[1] <= dl.HOLDOUT[0] < dl.HOLDOUT[1] <= dl.DEV[0]
    assert dl.DEV == (d.WINDOW_START, d.WINDOW_END)


def test_holdout_lock_refuses_without_promotion():
    hold = [d._epoch(datetime(2025, 7, 1, tzinfo=timezone.utc))]
    full = [d._epoch(datetime(2024, 7, 1, tzinfo=timezone.utc))]
    dev = [d._epoch(datetime(2026, 1, 1, tzinfo=timezone.utc))]
    dl.assert_not_locked(dev)
    with pytest.raises(PermissionError):
        dl.assert_not_locked(hold)
    with pytest.raises(PermissionError):
        dl.assert_not_locked(hold, {"dev_decision": "screen_fail"})
    dl.assert_not_locked(hold, {"dev_decision": "promote"})
    with pytest.raises(PermissionError):
        dl.assert_not_locked(full, {"dev_decision": "promote"})
    dl.assert_not_locked(full, {"stage": "full_run", "holdout_verdict": "pass"})


def test_stratified_sample_balanced_deterministic_prefix():
    keys = []
    for j in range(2000):
        c = d._epoch(d.WINDOW_START) + j * 3 * 3600
        keys.append({"packet_id": f"P{j}", "index": j, "cutoff_epoch": c, "fold": d.fold_of(c)})

    class S:
        def __init__(self):
            self.c = None

        def last_closed(self, c):
            return 1000

    s = S()
    rng = np.random.default_rng(0)
    s.c = rng.normal(100, 1, 2000)
    mkt = {"BTCUSDT": s}
    a = dl.stratified_sample(keys, mkt, 100, seed=7)
    b = dl.stratified_sample(keys, mkt, 100, seed=7)
    assert [x["packet_id"] for x in a] == [x["packet_id"] for x in b] and len(a) == 100
    first16 = {tuple(x["stratum"]) for x in a[:16]}
    assert len(first16) == 16                                  # round-robin: the first packets hit distinct strata
    cnt = {}
    for x in a:
        cnt[tuple(x["stratum"])] = cnt.get(tuple(x["stratum"]), 0) + 1
    assert max(cnt.values()) - min(cnt.values()) <= 1


def test_read_ranks_validates_cells(tmp_path):
    keys = {"P1": {"alias": {f"ASSET_0{i}": s for i, s in enumerate(["A", "B", "C", "D", "E", "F"], 1)}}}
    cells = [{"alias": f"ASSET_0{i}", "side": side, "score": 0.1 * i} for i in range(1, 7) for side in ("long", "short")]
    f = tmp_path / "r.jsonl"
    f.write_text("\n".join([json.dumps({"packet_id": "P1", "action": "rank", "cells": cells}),
                            json.dumps({"packet_id": "P1", "action": "rank", "cells": cells[:11]}),
                            json.dumps({"packet_id": "P1", "action": "no_trade"})]) + "\n")
    r, acc = dl.read_ranks(f, keys)
    assert acc["rank_rows"] == 1 and acc["refused"] == 1 and r["P1"]["F:short"] == pytest.approx(0.6)


def test_sequential_decision_kill_promote_fail():
    rng = np.random.default_rng(0)
    bad = [list(rng.normal(-0.3, 0.1, 12))]
    assert dl.sequential_decision(bad)[0] == "kill"
    good = [list(rng.normal(0.25, 0.1, k)) for k in (8, 12, 16, 20)]
    assert dl.sequential_decision(good)[0] == "promote"
    meh = [[0.9, -0.9, 0.75, -0.6, 0.3, -0.3, 0.6, -0.45] * (k // 8) for k in (8, 16, 16, 24)]
    assert dl.sequential_decision(meh)[0] == "screen_fail"     # mean SEL ~ +0.04: neither killed nor promoted
    assert dl.sequential_decision(meh[:2])[0] == "continue"


def test_packet_sel_is_top2_minus_packet_mean():
    rows = [{"packet_id": "P", "week": "w", "score": s, "y": y} for s, y in ((3, 1.0), (2, 0.5), (1, -0.5), (0, -1.0))]
    sel = dl.packet_sel(rows)
    assert sel == [{"packet_id": "P", "week": "w", "sel": pytest.approx(0.75 - 0.0)}]
    assert dl.weekly_means(sel + [{"packet_id": "Q", "week": "w", "sel": 0.25}]) == [pytest.approx(0.5)]


def test_promote_batch_cap_and_order():
    res = {"a": ("promote", 0.04), "b": ("promote", 0.09), "c": ("promote", 0.05), "d": ("kill", 0.5)}
    assert dl.promote_batch(res) == ["b", "c"]


def test_top_pick_takes_one_positive_cell_per_packet():
    rows = [{"packet_id": "P1", "cell": "A:long", "score": 0.3, "y": 1.0, "net_r": 1.1, "days": 1, "week": "w"},
            {"packet_id": "P1", "cell": "A:short", "score": 0.1, "y": -1.0, "net_r": -1.0, "days": 1, "week": "w"},
            {"packet_id": "P2", "cell": "B:long", "score": -0.2, "y": 2.0, "net_r": 2.0, "days": 1, "week": "w"}]
    p = dl.top_pick_rows(rows)
    assert len(p) == 1 and p[0]["diff"] == 1.0


def test_base_rate_emulator_scores_by_the_packets_own_rows():
    pf = {}
    for side, v in (("long", 0.3), ("short", -0.3)):
        for h in ce.HORIZONS:
            pf[f"br_{side}_h{h}_mean_r"] = v
    cut = [{"cutoff": 1, "pf": {"A": pf, "B": {k: -x for k, x in pf.items()}}}]
    acts = [{"cutoff": 1, "symbol": s, "side": side, "geom": "GJ", "week": "w", "y": y, "net_r": y, "days": 1.0}
            for s, side, y in (("A", "long", 1.0), ("A", "short", -1.0), ("B", "long", -0.5), ("B", "short", 0.5))]
    acts.append(dict(acts[0], geom="G1"))                     # other geometries are ignored
    rows, tp = dl.emulate_base_rate_rule(cut, acts, (0, 1, 1))
    assert len(rows) == 4
    top = max(rows, key=lambda r: r["score"])
    assert top["y"] in (1.0, 0.5) and tp[0]["diff"] in (1.0, 0.5)
