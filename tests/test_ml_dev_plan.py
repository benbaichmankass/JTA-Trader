"""ml_dev_plan reader: self-test (planted faults caught, clean line clean) and stage-vocabulary alignment with the RD
registry when that module exists. Deliberately does NOT fail on the plan file's content, so an operator edit to
docs/plans/ml-dev-plan.yaml is never blocked by CI (CLAUDE.md "No new gates"); the content check is the report
`python3 scripts/ops/ml_dev_plan.py --validate`."""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("ml_dev_plan", REPO / "scripts/ops/ml_dev_plan.py")
ml_dev_plan = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ml_dev_plan)


def test_self_test():
    assert ml_dev_plan.self_test() == 0


def test_stage_vocabulary_matches_rd_registry_when_present():
    p = REPO / "src/runtime/rd_registry.py"
    if not p.exists():  # RD-REGISTRY (PR #25313) not landed yet: nothing to align with
        return
    spec = importlib.util.spec_from_file_location("rd_registry_probe", p)
    try:
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(REPO))
        spec.loader.exec_module(mod)
    except (ImportError, OSError):  # an import failure there is that module's test's business
        return
    assert set(ml_dev_plan.STAGES) == set(mod.STAGES)
