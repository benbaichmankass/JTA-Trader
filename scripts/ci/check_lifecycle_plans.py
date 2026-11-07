#!/usr/bin/env python3
"""lifecycle-plan-guard: every in-population model has a plan; every plan's commands resolve.

Population = every top-level ml/configs/*.yaml manifest. Static only (nothing is executed). Gates
nothing on the trade path. Exit 1 on any violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.lifecycle import plan as P  # noqa: E402


def check() -> list[str]:
    errs = []
    manifests = {p.stem for p in P.population()}
    plans = P.load_all()
    for s in sorted(manifests - set(plans)):
        errs.append(f"{s}: in-population manifest has no plan (run scripts/ops/seed_lifecycle_plans.py)")
    for s in sorted(set(plans) - manifests):
        errs.append(f"{s}: plan has no manifest in ml/configs/ (orphan; retire the plan with the manifest)")
    for s, pl in sorted(plans.items()):
        errs += [f"{s}: {e}" for e in P.validate(s, pl)]
    return errs


def self_test() -> int:
    good = {"plan_id": "x"}
    assert P.validate("x", good), "incomplete plan must fail"
    assert P.resolve_command(["{py}", "-m", "ml", "no-such-subcommand"]), "bad subcommand must fail"
    assert P.resolve_command(["{py}", "scripts/ml/does_not_exist.py"]), "missing script must fail"
    assert P.resolve_command(["{py}", "-m", "ml", "train", "{bogus}"]), "unknown placeholder must fail"
    assert not P.resolve_command(["{py}", "-m", "ml", "train", "{manifest}"])
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    e = check()
    for x in e:
        print("FAIL", x)
    print(f"lifecycle-plan-guard: {len(P.load_all())} plans / {len(P.population())} manifests, {len(e)} violations")
    raise SystemExit(1 if e else 0)
