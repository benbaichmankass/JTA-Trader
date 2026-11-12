"""stage_a_folds null calibration (RQ-20261101-78fc-04 pre-run amendment, 2026-11-12).

Run from the repo root: python3 comms/research/RQ-20261101-78fc-04/null_calibration.py
Prints, per synthetic corpus and seed, the max over actions of folds beating the within-trade p95: point estimate vs CI lower.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts/research")
import tm_bench as tb  # noqa: E402


def cost(_sym):
    return (3.0, 1.0)


def cx(_sym, entry, risk):
    return 3.0 / 1e4 * entry / risk


for spec in ("synthetic", "synthetic-planted"):
    for seed in range(1, 9):
        with tempfile.TemporaryDirectory() as td:
            corp, meta = tb.resolve_corpus(spec, work=Path(td), synthetic_seed=seed)
            bc = tb.build_corpus(corp, meta, cost_fn=cx)
            bc["trades"] = bc["trades"][:600]
            r = tb.score(bc, None, k=6, n_boot=300, draws=5, seed=seed, cost=cost, kinds=("lgbm_action_value",),
                         checkins=("every_bar",), calibration=True, n_perm=100, feature_block="path_state")
            cal = r["calibration"]
            print(spec, seed, "point", max(cal["folds_beating_null_point"].values()), "ci",
                  max(cal["folds_beating_null"].values()), "minchk", cal["min_checkins_per_fold"], flush=True)
