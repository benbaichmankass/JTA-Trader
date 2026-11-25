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
