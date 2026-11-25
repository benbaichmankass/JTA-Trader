"""ml_entry fix arms (RQ-20261124-f1a0-01..05) and the lever-arms verdict.json harness contract (PI-20261124-RQFAILS-0001)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_fix_arms_self_test():
    import ml_entry_fix_arms as F
    F._self_test()


def test_lever_arms_writes_the_harness_verdict_json():
    """script_run.derive_record reads exactly <out>/verdict.json; lever-arms used to write only verdict_<arm>.json, which landed a
    measured run as producer_failed (RQ-20261124-e1a7-02 run 45455675005)."""
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    body = src[src.index("def lever_arms_cmd"):src.index("def _self_test_lever_arms")]
    assert '(out / "verdict.json").write_text' in body


def test_fix_arms_writes_the_harness_verdict_json():
    src = (REPO / "scripts/research/ml_entry_fix_arms.py").read_text()
    assert '(out / "verdict.json").write_text' in src


def test_run_arm_never_rebinds_its_per_run_inputs_inside_the_fold_loop():
    """f1a0-14 (run 45532031095) died at fold 2: `alt, alt2 = alt` inside the fold loop turned the per-run (fixed, vol) pair into a DataFrame on
    fold 1, so fold 2's unpack raised. No assignment inside run_arm's loops may target `alt` or `tab`."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "scripts/research/ml_entry_fix_arms.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run_arm")
    bad = []
    for loop in (n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))):
        for n in ast.walk(loop):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for tgt in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    bad += [n.lineno for nm in ast.walk(tgt) if isinstance(nm, ast.Name) and nm.id in ("alt", "tab")]
    assert bad == [], f"run_arm rebinds alt/tab inside a fold loop at lines {bad}"


def test_clf_target_breakeven_and_edge_scores():
    """clf_target: p* = mean|loss| / (mean win + mean|loss|) from TRAINING labels only, the score is P(net>0) - p*, and a side whose
    signal is pure noise scores near -p* + base rate (so the policy rarely trades it)."""
    import ml_decision_entry as M
    import ml_entry_fix_arms as F
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(0)
    n = 4000
    X = pd.DataFrame(rng.normal(size=(n, len(M.FEATURES))), columns=M.FEATURES)
    sig = X[M.FEATURES[0]].to_numpy()
    long_ = np.where(sig + rng.normal(0, 0.5, n) > 0, 1.5, -1.0)          # long label learnable from feature 0
    short_ = np.where(rng.random(n) < 0.3, 1.5, -1.0)                       # short label pure noise, 30% win
    df = X.assign(net_long=long_, net_short=short_)
    tr, te = df.iloc[:3000], df.iloc[3000:]
    cl, cs, info = F.clf_predict(tr, te, n_jobs=1)
    assert abs(info["long"]["p_star"] - 1.0 / 2.5) < 1e-6 and abs(info["short"]["p_star"] - 1.0 / 2.5) < 1e-6
    assert cl.shape == cs.shape == (len(te),)
    hi = te[M.FEATURES[0]].to_numpy() > 0.5
    assert cl[hi].mean() > 0.2 and cl[~hi].mean() < cl[hi].mean()       # the learnable side clears p* where the feature says so
    assert info["short"]["test_share_above_p_star"] < 0.2                  # the noise side (30% win < p* 40%) rarely clears
    assert "clf_target" in F.ARMS
