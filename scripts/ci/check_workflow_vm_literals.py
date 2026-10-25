#!/usr/bin/env python3
"""workflow-vm-literal-guard -- no literal VM address in .github/workflows/**.

WHY (IP-IN-PUBLIC-LOGS, operator 2026-10-15). Workflows carried the live-trader and trainer addresses as
literal defaults (`vars.X || '<ip>'`). GitHub prints a step's `env:` block in the run log, so every run of
such a workflow printed the address into a PUBLIC log, and a rotation meant editing ~60 files. The addresses
now come from the repository secrets `VM_SSH_HOST` (live trader) and `TRAINER_VM_IP` (trainer), which Actions
masks in logs and which are changed in one place.

THE RULE. Any occurrence of either address anywhere in a workflow file (code, input default or comment) fails.
The retired micro and the private IB-gateway subnet are NOT covered: they are not the two VMs this protects.

SCOPE. Workflows (and composite actions under .github/actions) only. Literals in src/, deploy/ and config/ are
tracked separately (a follow-up row); this guard does not read them.

HONESTY. The addresses are written below so the guard can recognise them; this file lives outside
.github/workflows/, which is the only tree it checks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parents[2]
# (label, address). Kept here, outside the tree this guard scans.
VM_ADDRESSES: Tuple[Tuple[str, str], ...] = (
    ("live trader (VM_SSH_HOST)", "141.145.193.91"),
    ("trainer (TRAINER_VM_IP)", "158.178.209.121"),
)
SCAN_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml", ".github/actions/**/*.yml",
              ".github/actions/**/*.yaml")


def scan(root: Path) -> List[str]:
    """Return one problem string per offending line. Never prints the matching line (it IS the address)."""
    problems: List[str] = []
    files = sorted({p for g in SCAN_GLOBS for p in root.glob(g)})
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{p.relative_to(root)}: unreadable -- {exc}")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, addr in VM_ADDRESSES:
                if addr in line:
                    problems.append(
                        f"{p.relative_to(root)}:{n}: literal address of the {label}; read it from the "
                        f"repository secret instead (secrets.{label.split('(')[1].rstrip(')')})")
    if not files:
        problems.append("no workflow files found: the guard looked at nothing (COULD NOT LOOK, not clean)")
    return problems


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "clean.yml").write_text("env:\n  H: ${{ secrets.VM_SSH_HOST }}\n")
        assert scan(root) == [], scan(root)                      # control: clean tree is quiet
        for label, addr in VM_ADDRESSES:
            (wf / "bad.yml").write_text(f"env:\n  H: ${{{{ vars.X || '{addr}' }}}}\n")
            hits = scan(root)
            assert len(hits) == 1 and "bad.yml:2" in hits[0], hits  # planted code literal fails
            assert addr not in hits[0], "the report must not echo the address"
            (wf / "bad.yml").write_text(f"# the box at {addr} is the live one\n")
            assert len(scan(root)) == 1, scan(root)                 # planted COMMENT literal fails too
        (wf / "bad.yml").unlink()
        (root / ".github" / "actions" / "a").mkdir(parents=True)
        (root / ".github" / "actions" / "a" / "action.yml").write_text(f"x: {VM_ADDRESSES[0][1]}\n")
        assert len(scan(root)) == 1, scan(root)                     # composite actions are covered
        (root / ".github" / "actions" / "a" / "action.yml").unlink()
        (wf / "clean.yml").unlink()
        assert any("COULD NOT LOOK" in p for p in scan(root))        # empty tree is not a clean pass
    print("workflow-vm-literal-guard self-test OK")
    return 0


def main(argv: List[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    problems = scan(REPO)
    if problems:
        for p in problems:
            print(f"::error::workflow-vm-literal-guard: {p}")
        print(f"workflow-vm-literal-guard: FAIL -- {len(problems)} problem(s)")
        return 1
    print("workflow-vm-literal-guard: OK -- no literal VM address in .github/workflows or .github/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
