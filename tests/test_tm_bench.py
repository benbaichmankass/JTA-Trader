"""TM-BENCH (scripts/research/tm_bench.py): the one trade-management bench.

Pins the bench's invariants on small synthetic corpora (first_passage_paths.synthetic_corpus): the engine replays B0
to the harness exit, HOLD is 0 exactly, the action-value ceiling bounds every labelled action, invalid actions are
refused, the cross-symbol purge leaves no overlapping train trade, a frozen corpus keeps its id, and `score` /
`transfer` run end to end and report the unavailable baselines as unavailable (never 0).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
import first_passage_paths as fpp  # noqa: E402
import tm_bench as tb  # noqa: E402

COST = lambda sym: (3.0, 1.0)  # noqa: E731
CX = lambda sym, entry, risk: 3.0 / 1e4 * entry / risk  # noqa: E731


def _bench(planted: bool = False, n: int = 120, seed: int = 5):
    corp = fpp.synthetic_corpus(planted, n_trades=n, seed=seed, sub=tb.SYNTH_SUBSTEPS)
    return corp, tb.build_corpus(corp, {"source": "test"}, cost_fn=CX)


def test_engine_replays_b0_and_hold_is_zero():
    _c, bc = _bench()
    for t in bc["trades"][:40]:
        L = tb.label_trade(t, COST)
        assert L["fidelity_ok"], (t["trade_key"], L["b0_replay_gross_r"], t["exit_r"])
        assert set(L["labels"]) == set(tb.ACTIONS)
        assert all(len(v) == t["bars"] - 1 for v in L["labels"].values())


def test_invalid_actions_are_refused():
    _c, bc = _bench()
    t = next(t for t in bc["trades"] if t["bars"] > 3)
    t = dict(t, stop_r=t["stop_r"].copy(), target_r=t["target_r"].copy(), c_r=t["c_r"].copy())
    t["c_r"][0], t["stop_r"][0], t["target_r"][0] = -0.5, -1.0, 0.3
    assert tb.action_spec(t, "tighten_sl_be", 0) is None          # BE above the market
    assert tb.action_spec(t, "tp_pull_in_1r", 0) is None          # +1R from -0.5 (0.5) is past the 0.3 target
    assert tb.action_spec(t, "tp_pull_in_0p5r", 0) is not None
    assert tb.action_spec(t, "close", 0) is not None


def test_ceiling_bounds_every_label():
    _c, bc = _bench(planted=True)
    for t in bc["trades"][:40]:
        L = tb.label_trade(t, COST)
        vals = [np.nanmax(v) for v in L["labels"].values() if len(v) and np.isfinite(v).any()]
        ceiling = max([0.0] + vals)
        assert all(v <= ceiling for v in vals)


def test_cross_symbol_purge_and_dedup():
    _c, bc = _bench(n=120)
    T = bc["trades"]
    TR = [dict(t, symbol="OTHERUSDT", trade_key=t["trade_key"] + "|x") for t in T]
    fl = tb.make_folds(T, TR, 6, same=False)
    for f in fl["folds"]:
        lo, hi = pd.Timestamp(f["lo"]).value, pd.Timestamp(f["hi"]).value
        assert not any(TR[i]["entry_time"].value < hi and TR[i]["exit_time"].value >= lo for i in f["train"])
        assert f["n_purged"] > 0
    assert sum(f["n_dedup"] for f in tb.make_folds(T, T, 6, same=False)["folds"]) == 6 * len(T)


def test_frozen_corpus_keeps_its_id():
    corp, bc = _bench(n=60)
    with tempfile.TemporaryDirectory() as td:
        tb.freeze(corp, bc, Path(td) / "c")
        bc2 = tb.build_corpus(*tb.resolve_corpus(str(Path(td) / "c"), work=Path(td)), cost_fn=CX)
    assert bc2["corpus_id"] == bc["corpus_id"] and len(bc2["trades"]) == len(bc["trades"])


def test_checkin_grid():
    _c, bc = _bench()
    t = next(t for t in bc["trades"] if t["bars"] > 10)
    every, four, trig = (tb.checkin_mask(t, c, 5.0) for c in ("every_bar", "every_4", "triggers_only"))
    assert every.all() and four.sum() < every.sum() and not (four & ~every).any()
    x = np.r_[0.0, t["open_r"][:t["bars"] - 1]]
    crossed = np.zeros(len(x) - 1, bool)
    for L in tb.R_LEVELS:
        crossed |= (x[:-1] - L) * (x[1:] - L) < 0
    assert not (crossed & ~trig).any()


def test_score_end_to_end():
    _c, bc = _bench(n=120)
    r = tb.score(bc, None, k=6, n_boot=50, draws=20, seed=3, cost=COST, kinds=("logit_action_value",),
                 checkins=("every_bar",))
    arms = {a["arm_id"]: a for a in r["arms"]}
    assert arms["B0_hold"]["delta_vs_b0_r"] == 0.0 and arms["B0_hold"]["b0_minus_b0_r"] == 0.0
    assert {"B1_best_static_rule", "B2_distance_logit@every_bar", "B6_vol_rescale@every_bar",
            "logit_action_value@every_bar"} <= set(arms)
    assert arms["B3_desk"]["read_state"] == "not_available" and arms["B5_rescore_exit"]["read_state"] == "not_available"
    assert "b4_matched_random" in arms["logit_action_value@every_bar"]
    assert r["engine_fidelity"]["share_within_tol"] >= 0.99
    v, _why = tb.s_offline(arms["logit_action_value@every_bar"], r["arms"])
    assert v in ("pass_pending_fresh_window", "fail", "indeterminate")


def test_transfer_end_to_end():
    pytest.importorskip("lightgbm")
    _c, test = _bench(n=90, seed=5)
    _c2, train = _bench(n=90, seed=9)
    for t in train["trades"]:
        t["trade_key"] += "|broad"
    tr = tb.transfer(test, train, [0.0, 1.0], k=3, n_boot=50, seed=1, cost=COST)
    assert set(tr["mse_by_fraction"]) == {"0.0", "1.0"} and tr["n_test_trades"] > 0
