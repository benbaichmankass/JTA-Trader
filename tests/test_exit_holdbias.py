"""exit-holdbias-v1 harness (scripts/research/exit_holdbias.py, row ML-HOLDBIAS-EXIT-MODEL, unit RQ-20261101-78fc-05)."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import exit_holdbias as eh  # noqa: E402

ACTIONS = ("close", "tighten_sl_0p5r")


def _corpus(path: Path, planted: bool, n_trades: int = 600, seed: int = 3) -> Path:
    """Synthetic action-grid labels: 6 folds by entry, two legs. planted: closing pays +0.6 R when now_r > 1 and costs
    -0.3 R otherwise; null: every action is pure noise around a small negative (cost)."""
    rng = np.random.default_rng(seed)
    rows = []
    t0 = 1_600_000_000
    for n in range(n_trades):
        fold = n * 6 // n_trades
        leg = "leg_a" if n % 2 else "leg_b"
        for k in range(8):
            now_r = float(rng.normal(0.3, 1.0))
            labels = {}
            for a in ACTIONS:
                if planted and a == "close":
                    v = (0.6 if now_r > 1.0 else -0.3) + float(rng.normal(0, 0.05))
                else:
                    v = float(rng.normal(-0.02, 0.3))
                labels[a] = {"feasible": True, "value_r": v}
            rows.append({"entry_id": f"T{n}", "leg": leg, "fold": fold, "k": k, "bar_t": t0 + n * 86400 + k * 3600,
                         "now_r": now_r, "stop_r": -1.0, "tp_r": 2.0, "mfe_r": max(now_r, 0), "mae_r": min(now_r, 0),
                         "bars_held": k + 1, "bars_left": 40 - k, "dist_sl_r": now_r + 1, "dist_tp_r": 2 - now_r,
                         "atr_r": 0.5, "dist_sl_atr": (now_r + 1) / 0.5, "dist_tp_atr": (2 - now_r) / 0.5,
                         "atr_ratio": 1.0, "mom3_r": 0.0, "tags": ["clock"], "labels": labels})
    with gzip.open(path, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


pytest.importorskip("lightgbm")


def test_registered_numbers_are_the_plan_section_2a_rule():
    assert (eh.TAU_R, eh.LB_FLOOR_R, eh.ADVICE_RATE_MAX, eh.LEG_FLOOR_R, eh.MIN_HELDOUT_TRADES) == (0.15, -0.01, 0.15, -0.05, 500)


def test_planted_edge_is_found_and_null_mostly_holds(tmp_path):
    vp = eh.run(_corpus(tmp_path / "p.jsonl.gz", True), n_boot=500, draws=20)
    assert vp["read_state"] == "measured" and vp["n"] == 600
    assert vp["measurement"]["mean_dR_per_trade"] > 0.2          # closes the now_r > 1 states
    assert vp["measurement"]["action_mix"].get("close", 0) > 100
    assert vp["measurement"]["mean_dR_per_trade"] > vp["measurement"]["matched_random"]["mean_dR"]
    vn = eh.run(_corpus(tmp_path / "n.jsonl.gz", False), n_boot=500, draws=20)
    assert vn["measurement"]["advice_rate"] < 0.05                 # noise never clears the 0.15 R margin
    assert vn["verdict"] in ("pass", "fail")


def test_indeterminate_below_500_heldout_trades(tmp_path):
    v = eh.run(_corpus(tmp_path / "s.jsonl.gz", True, n_trades=120), n_boot=200, draws=5)
    assert v["n"] == 120 and v["verdict"] == "indeterminate"


def test_purge_drops_overlapping_train_trades():
    M = {"trade": np.array(["a", "a", "b", "b", "c", "c"]), "fold": np.array([0, 0, 1, 1, 2, 2]),
         "t": np.array([0, 100, 150, 200, 1000, 1100], dtype=np.int64)}
    mask, info = eh.purged_train_mask(M, 1)
    # embargo = longest span = 100 s: trade a ends at 100, 100 + 100 >= 150 -> purged; c starts 1000 > 200 + 100 -> kept
    assert info["embargo_s"] == 100 and info["purged_trades"] == 1
    assert mask.tolist() == [False, False, False, False, True, True]


def test_first_action_only_and_infeasible_never_chosen():
    M = {"trade": np.array(["a", "a", "b"]), "k": np.array([0, 1, 0]),
         "V": np.array([[0.5, np.nan], [0.9, 0.1], [np.nan, -0.2]])}
    p = eh.as_if_applied(M, np.array([0, 1, 2]), np.array([0, 0, -1]))
    assert p["a"] == (0.5, 0) and p["b"] == (0.0, None)

    class H:
        def __init__(self, v): self.v = v
        def predict(self, X): return np.full(len(X), self.v)
    act, _ = eh.decide([H(1.0), H(0.2)], np.zeros((1, 1)), np.array([[np.nan, 0.0]]))
    assert act.tolist() == [1]                                      # head 0 is infeasible here, head 1 clears tau


def test_cli_writes_verdict(tmp_path):
    lab = _corpus(tmp_path / "c.jsonl.gz", True, n_trades=120)
    assert eh.main(["--labels", str(lab), "--out", str(tmp_path / "o"), "--n-boot", "100", "--draws", "5"]) == 0
    v = json.loads((tmp_path / "o" / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] == "indeterminate"


# ---- PI-20261119-RIMARY12-0005: tau chosen per outer fold on training data only (--tau-grid) ----
GRID = (0.15, 0.3, 0.5, 0.8)


def test_tau_grid_off_is_byte_identical_to_the_fixed_rule(tmp_path):
    c = _corpus(tmp_path / "p.jsonl.gz", True, n_trades=600)
    a = eh.run(c, n_boot=200, draws=5)
    b = eh.run(c, n_boot=200, draws=5, tau_grid=None)
    for k in ("verdict", "n", "clauses"):
        assert a[k] == b[k]
    assert b["config"]["tau_r"] == 0.15 and b["config"]["tau_grid"] is None


def _rare_edge(path: Path) -> Path:
    """The planted corpus with the close edge only at now_r > 1.6 (~8% of check-ins), so a tau under the 15% advice
    cap exists; on the base corpus (edge on ~24% of check-ins) the cap is unreachable by construction."""
    src = _corpus(path.with_suffix(".src.gz"), True)
    rows = eh.read_labels(src)
    rng = np.random.default_rng(11)
    for r in rows:
        r["labels"]["close"]["value_r"] = (0.6 if r["now_r"] > 1.6 else -0.3) + float(rng.normal(0, 0.05))
    with gzip.open(path, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def test_tau_inner_selection_respects_the_advice_cap_and_keeps_the_planted_edge(tmp_path):
    v = eh.run(_rare_edge(tmp_path / "r.jsonl.gz"), n_boot=200, draws=5, tau_grid=GRID)
    for f, pf in v["measurement"]["per_fold"].items():
        sel = pf["tau_selection"]
        assert sel["selected_tau"] in GRID and int(f) not in sel["inner_folds"], "the outer test fold is never an inner fold"
        chosen = next(r for r in sel["table"] if r["tau"] == sel["selected_tau"])
        assert sel["cap_unreachable"] or chosen["advice_rate"] <= eh.ADVICE_RATE_MAX
    assert not any(pf["tau_selection"]["cap_unreachable"] for pf in v["measurement"]["per_fold"].values())
    assert v["measurement"]["mean_dR_per_trade"] > 0.05 and v["measurement"]["advice_rate"] <= eh.ADVICE_RATE_MAX


def test_tau_selection_never_reads_the_outer_test_fold(tmp_path, monkeypatch):
    """Poison the outer test fold's labels AFTER the matrix is built: the selection table for that fold must not move."""
    rows = eh.read_labels(_corpus(tmp_path / "p.jsonl.gz", True))
    M = eh.build_matrix(rows)
    mask, _ = eh.purged_train_mask(M, 2)
    s1 = eh.select_tau_inner(M, mask, 2, GRID, eh.SEED)
    M["V"][M["fold"] == 2] = 99.0
    s2 = eh.select_tau_inner(M, mask, 2, GRID, eh.SEED)
    assert s1["table"] == s2["table"] and s1["selected_tau"] == s2["selected_tau"]
