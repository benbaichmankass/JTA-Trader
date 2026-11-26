"""EXIT-HOLDBIAS-ATTEMPT3-LEVERS: the two attempt-3 levers of scripts/research/exit_holdbias.py.

Iteration 2 (RQ-20261119-2780-05) fixed selectivity (advice rate 0.0706) but the chosen actions realised WORSE than random ones
(p_random_ge_model 0.99): the argmax over many per-action heads picks the most noise-inflated one (winner's curse). Levers, each one
factor, each OFF by default and then BYTE-IDENTICAL to the registered 78fc-05 design:
  --actions   restrict which actions the argmax may pick (names or class prefixes);
  --shrink    scale each head by its out-of-fold calibration slope in [0, 1], estimated inside the outer fold's training data only.
`--shrink` and `--tau-grid` never combine (separate units). The pure tests run without lightgbm; the model tests skip without it.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import exit_holdbias as eh

NAMES = ["close", "tighten_sl_0p25r", "tighten_sl_0p5r", "widen_sl_0p5r"]


class _Head:
    def __init__(self, v):
        self.v = v

    def predict(self, X):
        return np.full(len(X), self.v)


# ---- pure (no lightgbm) -----------------------------------------------------------------------------------------------

def test_resolve_actions_names_classes_and_unknown():
    assert eh.resolve_actions(None, NAMES) is None and eh.resolve_actions("", NAMES) is None
    assert eh.resolve_actions("close", NAMES).tolist() == [True, False, False, False]
    assert eh.resolve_actions("tighten_sl", NAMES).tolist() == [False, True, True, False]          # a class prefix
    assert eh.resolve_actions("close, widen_sl_0p5r", NAMES).tolist() == [True, False, False, True]
    assert eh.resolve_actions("tighten_sl_0p25r", NAMES).tolist() == [False, True, False, False]   # an exact name
    for bad in ("tigh", "clos", "nope", "close,nope"):
        with pytest.raises(ValueError):
            eh.resolve_actions(bad, NAMES)


def test_decide_default_is_the_registered_argmax_and_levers_change_only_what_they_name():
    X = np.zeros((3, 2))
    V = np.zeros((3, 4))
    heads = [_Head(0.9), _Head(0.5), _Head(0.4), _Head(0.2)]
    act, pv = eh.decide(heads, X, V)                                   # best head is 'close' at 0.9 >= tau
    assert act.tolist() == [0, 0, 0] and pv.tolist() == [0.9] * 3
    assert eh.decide(heads, X, V, allowed=None, scale=None)[0].tolist() == act.tolist()           # explicit None == default
    only = np.array([False, True, True, False])
    a2, p2 = eh.decide(heads, X, V, allowed=only)                      # 'close' removed: the next best head acts
    assert a2.tolist() == [1, 1, 1] and p2.tolist() == [0.5] * 3
    a3, _ = eh.decide(heads, X, V, scale=np.array([0.0, 1.0, 1.0, 1.0]))                           # close shrunk to 0 = never acts
    assert a3.tolist() == [1, 1, 1]
    a4, _ = eh.decide(heads, X, V, scale=np.array([0.1, 0.1, 0.1, 0.1]))                           # all shrunk under tau: HOLD
    assert a4.tolist() == [-1, -1, -1]
    V2 = V.copy()
    V2[:, 0] = np.nan                                                  # infeasible is never chosen, lever or not
    assert eh.decide(heads, X, V2)[0].tolist() == [1, 1, 1]


def test_shrink_and_tau_grid_are_separate_levers(tmp_path):
    with pytest.raises(ValueError):
        eh.run(tmp_path / "never_read.jsonl.gz", shrink=True, tau_grid=[0.15, 0.3])    # raised before any file is read
    with pytest.raises(SystemExit):
        eh.main(["--out", str(tmp_path / "o"), "--shrink", "--tau-grid", "0.15,0.3"])  # argparse error, exit code 2


def test_cli_exposes_both_levers(capsys):
    with pytest.raises(SystemExit) as e:
        eh.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--actions" in out and "--shrink" in out


# ---- model tests (need lightgbm + scikit-learn) ---------------------------------------------------------------------------

def _corpus(path: Path, planted: bool, n_trades: int = 600, seed: int = 3) -> Path:
    rng = np.random.default_rng(seed)
    rows = []
    t0 = 1_600_000_000
    for n in range(n_trades):
        fold = n * 6 // n_trades
        leg = "leg_a" if n % 2 else "leg_b"
        for k in range(8):
            now_r = float(rng.normal(0.3, 1.0))
            labels = {}
            for a in ("close", "tighten_sl_0p5r"):
                v = ((0.6 if now_r > 1.0 else -0.3) + float(rng.normal(0, 0.05))) if (planted and a == "close") \
                    else float(rng.normal(-0.02, 0.3))
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


@pytest.fixture()
def planted(tmp_path):
    pytest.importorskip("lightgbm")
    pytest.importorskip("sklearn")
    return _corpus(tmp_path / "p.jsonl.gz", True)


def test_levers_off_or_full_action_set_is_byte_identical_to_the_registered_design(planted):
    base = eh.run(planted, n_boot=200, draws=5)
    for kw in ({"actions": None, "shrink": False}, {"actions": "close,tighten_sl_0p5r"}):
        other = eh.run(planted, n_boot=200, draws=5, **kw)
        for k in ("verdict", "n", "clauses"):
            assert base[k] == other[k], k
        assert (base["rule"] == other["rule"]) == (kw.get("actions") is None)   # naming the lever changes the label, never the numbers
        assert base["measurement"]["mean_dR_per_trade"] == other["measurement"]["mean_dR_per_trade"]
        assert base["measurement"]["action_mix"] == other["measurement"]["action_mix"]
    assert "actions_allowed" not in base["config"] and "shrink" not in base["config"]       # nothing new is stamped by default


def test_actions_restricts_what_may_be_acted_on(planted):
    only_noise = eh.run(planted, n_boot=200, draws=5, actions="tighten_sl")
    assert set(only_noise["measurement"]["action_mix"]) <= {"tighten_sl_0p5r"}
    assert only_noise["config"]["actions_allowed"] == ["tighten_sl_0p5r"] and "--actions" in only_noise["rule"]
    only_close = eh.run(planted, n_boot=200, draws=5, actions="close")
    assert set(only_close["measurement"]["action_mix"]) == {"close"}
    assert only_close["measurement"]["mean_dR_per_trade"] > 0.2                      # the planted edge survives the restriction
    with pytest.raises(ValueError):
        eh.run(planted, n_boot=200, draws=5, actions="clos")


def test_shrink_keeps_a_real_edge_and_reports_calibration(planted):
    v = eh.run(planted, n_boot=200, draws=5, shrink=True)
    assert v["config"]["shrink"] is True and "--shrink" in v["rule"]
    assert v["measurement"]["mean_dR_per_trade"] > 0.2, "a calibrated head must keep its prediction"
    for pf in v["measurement"]["per_fold"].values():
        heads = pf["shrink"]["heads"]
        assert 0.0 <= heads["close"]["scale"] <= 1.0 and heads["close"]["slope"] > 0.5
        assert 0.0 <= heads["tighten_sl_0p5r"]["scale"] <= 1.0


def test_shrink_never_acts_more_than_the_unshrunk_policy_on_noise(tmp_path):
    pytest.importorskip("lightgbm")
    pytest.importorskip("sklearn")
    null = _corpus(tmp_path / "n.jsonl.gz", False)
    a = eh.run(null, n_boot=200, draws=5)
    b = eh.run(null, n_boot=200, draws=5, shrink=True)
    assert b["measurement"]["advice_rate"] <= a["measurement"]["advice_rate"] + 1e-12     # predictions only ever shrink toward HOLD


def test_calibration_never_reads_the_outer_test_fold(planted):
    M = eh.build_matrix(eh.read_labels(planted))
    mask, _ = eh.purged_train_mask(M, 2)
    s1, d1 = eh.calibrate_slopes(M, mask, 2, eh.SEED)
    M["V"][M["fold"] == 2] = 99.0                                                    # poison the outer test fold AFTER the matrix is built
    s2, d2 = eh.calibrate_slopes(M, mask, 2, eh.SEED)
    assert s1.tolist() == s2.tolist() and d1 == d2 and 2 not in d1["inner_folds"]
