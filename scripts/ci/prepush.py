#!/usr/bin/env python3
"""One command to run BEFORE every push: the guards on your diff + the affected tests.

    python3 scripts/ci/prepush.py            # diff = origin/main...HEAD plus uncommitted
    python3 scripts/ci/prepush.py --no-tests # guards only

Why (CI-THROUGHPUT-20261029): a guard failure CI finds costs a ~15 min round trip
and a re-push cancels the run in flight. The same guard run locally costs
minutes and no CI slot.

This is a LOCAL HABIT, not a gate: it adds no required check, hold or blocking
step.  It reuses `run_guards.py` (the same registry CI runs) and
`pytest_run_scope.py` (the same selector CI uses on a PR), so what passes here is
what CI will run.  Exit 0 = both green; non-zero = fix before pushing.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sh(argv, **kw):
    return subprocess.run(argv, cwd=ROOT, text=True, **kw)


def changed_files(base: str) -> list[str]:
    out: set[str] = set()
    for cmd in (["git", "diff", "--name-only", f"{base}...HEAD"],
                ["git", "diff", "--name-only", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        r = sh(cmd, capture_output=True)
        out.update(ln for ln in r.stdout.splitlines() if ln)
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--no-guards", action="store_true")
    a = ap.parse_args(argv)

    if sh(["git", "merge-base", a.base, "HEAD"], capture_output=True).returncode:
        print(f"no merge base with {a.base}: run `git fetch --deepen=300 origin main` first",
              file=sys.stderr)
        return 2
    files = changed_files(a.base)
    print(f"prepush: {len(files)} changed file(s) vs {a.base}")
    rc = 0
    if not a.no_guards:
        print("\n== guards (scripts/ci/run_guards.py) ==", flush=True)
        g = sh([sys.executable, "scripts/ci/run_guards.py", "--base-ref", a.base.removeprefix("origin/"),
                "--event-name", "pull_request"])
        rc |= 1 if g.returncode else 0
    if not a.no_tests:
        print("\n== affected tests (scripts/ci/pytest_run_scope.py) ==", flush=True)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "tests.txt"
            s = sh([sys.executable, "scripts/ci/pytest_run_scope.py", "--event",
                    "pull_request", "--tests-out", str(out)],
                   input="\n".join(files) + "\n", capture_output=True)
            info = dict(ln.split("=", 1) for ln in s.stdout.splitlines() if "=" in ln)
            mode = info.get("mode", "?")
            print(f"mode={mode} reason={info.get('reason', '')}")
            if mode == "affected" and out.exists():
                tests = [t for t in out.read_text().split() if t]
                print(f"running {len(tests)} affected test file(s)")
                t = sh([sys.executable, "-m", "pytest", "-q", "-x", "-n", "auto",
                        "--dist", "loadfile", *tests])
                rc |= 1 if t.returncode else 0
            elif mode == "data":
                r = sh([sys.executable, "scripts/ci/pytest_run_scope.py", "--select-tests"],
                       capture_output=True)
                tests = r.stdout.split()
                t = sh([sys.executable, "-m", "pytest", "-q", "-n", "auto",
                        "--dist", "loadfile", *tests])
                rc |= 1 if t.returncode else 0
            else:
                mine = [f for f in files if f.startswith("tests/test_") and f.endswith(".py")
                        and (ROOT / f).is_file()]
                print("CI will run the FULL suite for this diff; running only the test files "
                      f"you changed ({len(mine)}). Run their neighbours yourself if needed.")
                if mine:
                    t = sh([sys.executable, "-m", "pytest", "-q", "-n", "auto",
                            "--dist", "loadfile", *mine])
                    rc |= 1 if t.returncode else 0
    print("\nprepush:", "FAIL — fix before pushing" if rc else "OK — safe to push (once; batch commits)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
