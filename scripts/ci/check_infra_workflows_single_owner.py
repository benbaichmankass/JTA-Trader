#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (step `infra-workflows-single-owner`, allow_fail), tests/test_infra_workflows_single_owner.py
"""infra-workflows-single-owner: REPORT-ONLY. "Which workflows are money-path ops" has ONE owner.

WHY (B13, DEEP-AUDIT-20261104 #14, docs/plans/COMPUTE-ALLOCATION-2026-11-03.md section 9): three lists answered the
question and disagreed. (a) `scripts/research/research_compute.yaml` `limits.infra_workflows`; (b) the workflows whose
`runs-on` reads `vars.INFRA_RUNS_ON`; (c) the class regex in `scripts/ops/actions_capacity_inventory.py`. Three research
workflows sat in (b) and not in (a)'s intent, which is how research reached the ops pool on 2026-11-03.

THE OWNER IS (a). THE REPORT SAYS, with a population for each line:
  1. (b) not in (a), excluding the runner-admin workflows (`infra-runner-*`): an ops-pool workflow nobody told the
     research dispatcher to yield to. Fix: add it to (a), or take it off INFRA_RUNS_ON.
  2. a RESEARCH workflow (`research-*`) in (b): research must never land on the ops pool. Fix: `runs-on: ubuntu-latest`.
  3. (a) names with no workflow file: a dead entry (the yield list silently covers nothing for it).
  (c) is not parsed: the inventory tool READS (a) (see `infra_names()` there); its regex is only a fallback.

NON-BLOCKING by the operator's ruling (2026-11-04, "Yes, non-blocking OK"; CLAUDE.md "No new gates"): it prints findings
as `::warning::` and exits 0. Only `--self-test` (planted controls) can exit 1, so a broken detector is not a clean scan.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OWNER_FILE = "scripts/research/research_compute.yaml"
WORKFLOWS = ".github/workflows"
#: runner-admin workflows: they arm/disarm/smoke the pool itself, so they read the variable by design.
RUNNER_ADMIN = re.compile(r"^infra-runner-")
READS_VAR = re.compile(r"runs-on:.*vars\.INFRA_RUNS_ON")


def owner_list(root: Path) -> set[str] | None:
    """(a). None when it cannot be read: never an empty set, so an unreadable owner is not a clean scan."""
    try:
        import yaml
        cfg = yaml.safe_load((root / OWNER_FILE).read_text(encoding="utf-8"))
        return {str(n) for n in cfg["limits"]["infra_workflows"]}
    except (ImportError, OSError, KeyError, TypeError, ValueError):
        return None


def pool_readers(root: Path) -> set[str]:
    """(b): workflow names (file stem) with a `runs-on` that reads vars.INFRA_RUNS_ON."""
    out: set[str] = set()
    for f in sorted((root / WORKFLOWS).glob("*.yml")):
        if any(READS_VAR.search(line.split("  #", 1)[0]) for line in f.read_text(encoding="utf-8").splitlines()
               if not line.lstrip().startswith("#")):
            out.add(f.stem)
    return out


def existing(root: Path) -> set[str]:
    return {f.stem for f in (root / WORKFLOWS).glob("*.yml")}


def findings(root: Path) -> list[str]:
    a = owner_list(root)
    if a is None:
        return [f"READ_STATE could_not_read {OWNER_FILE} limits.infra_workflows; nothing below is graded"]
    b = pool_readers(root)
    out = []
    for n in sorted(b - a):
        if RUNNER_ADMIN.match(n):
            continue
        out.append(f"{n}: reads vars.INFRA_RUNS_ON but is not in limits.infra_workflows "
                   f"(add it there, or move it to ubuntu-latest)")
    for n in sorted(x for x in b if x.startswith("research-")):
        out.append(f"{n}: a research workflow reads vars.INFRA_RUNS_ON (research must not land on the ops pool)")
    have = existing(root)
    for n in sorted(a - have):
        out.append(f"{n}: listed in limits.infra_workflows but has no .github/workflows/{n}.yml (dead entry)")
    return out


def _plant(root: Path, owner: list[str], wfs: dict[str, str]) -> None:
    (root / WORKFLOWS).mkdir(parents=True)
    (root / "scripts/research").mkdir(parents=True)
    body = "limits:\n  infra_workflows:\n" + "".join(f"    - {n}\n" for n in owner)
    (root / OWNER_FILE).write_text(body, encoding="utf-8")
    for name, text in wfs.items():
        (root / WORKFLOWS / f"{name}.yml").write_text(text, encoding="utf-8")


def self_test() -> int:
    import tempfile
    reads = "jobs:\n  j:\n    runs-on: ${{ fromJSON(vars.INFRA_RUNS_ON || '\"ubuntu-latest\"') }}\n"
    plain = "jobs:\n  j:\n    runs-on: ubuntu-latest\n"
    bad = 0
    with tempfile.TemporaryDirectory() as t:
        r = Path(t)
        _plant(r, ["ops-a", "ghost"], {"ops-a": reads, "stray": reads, "research-x": reads,
                                       "infra-runner-smoke": reads, "ok": plain})
        got = " | ".join(findings(r))
        for needle in ("stray: reads vars", "research-x: a research workflow", "ghost: listed"):
            if needle not in got:
                print(f"SELF-TEST FAIL: planted case not reported: {needle}")
                bad += 1
        for needle in ("ops-a:", "infra-runner-smoke:", "ok:"):
            if needle in got:
                print(f"SELF-TEST FAIL: clean case reported: {needle}")
                bad += 1
    with tempfile.TemporaryDirectory() as t:
        if "could_not_read" not in " ".join(findings(Path(t))):
            print("SELF-TEST FAIL: unreadable owner list was not reported")
            bad += 1
    print("self-test " + ("FAILED" if bad else "ok"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--root", default=str(REPO))
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    root = Path(args.root)
    f = findings(root)
    a = owner_list(root)
    print(f"infra-workflows-single-owner (REPORT-ONLY): owner list = {len(a) if a is not None else 'UNREADABLE'} names; "
          f"{len(pool_readers(root))} workflows read vars.INFRA_RUNS_ON; {len(f)} finding(s)")
    for line in f:
        print(f"::warning::{line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
