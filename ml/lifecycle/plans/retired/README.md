# Retired lifecycle plans

Plans here belong to models whose training manifest moved to `ml/configs/retired/`. `ml/lifecycle/plan.py::load_all`
globs only `ml/lifecycle/plans/*.yaml` (non-recursive), so the scheduler never runs them. They are kept so a retired model
can be restored by moving its manifest and plan back together.

- 2026-11-11: 48 plans retired with their manifests. Operator decisions in the Thursday-planning doc: a1 *"Retire the 28 with no
  active manifest now; the 44 after their manifests are removed"* and a2 *"Accept as proposed"*. The lists are in
  `docs/plans/ML-CONSOLIDATION-2026-11-11.md`; the row is ML-RETIRE-WAVES-20261111.
