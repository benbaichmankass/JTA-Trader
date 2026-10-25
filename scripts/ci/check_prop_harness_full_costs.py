#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::prop-harness-full-costs-guard (--self-test, then the scan)
"""prop-harness-full-costs-guard -- no caller of the portfolio engine runs fee-only.

WHY (PROP-EVAL-COSTS, operator 2026-10-15; extends the D1 cost-stack verification,
docs/research/d1-cost-stack-verification-2026-09-25.md): ``backtest_system``'s slippage /
funding globals default to 0.0, so every in-process caller (prop evaluator, prop
Monte-Carlo, alt-prop validation, compat matrix, panel builder, walk-forwards) ran FEE-ONLY
and prop survival / EV was overstated with nothing in the result saying so.

CHECKS (AST, no imports):
1. every call to ``run_system_backtest(...)`` outside ``scripts/backtest_system.py`` and
   ``tests/`` passes BOTH ``costs=`` and ``require_full_costs=`` keywords;
2. the engine wrapper still defines ``costs`` / ``require_full_costs`` and raises
   ``CostPolicyError`` on a missing stack;
3. the prop scripts that own a cost result record ``cost_policy`` in their output.
Exit 0 clean, 1 with findings. ``--self-test`` runs planted controls.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import warnings

warnings.simplefilter("ignore", SyntaxWarning)

REPO = pathlib.Path(__file__).resolve().parents[2]
SCAN_DIRS = ("scripts", "src", "sim")
ENGINE = "scripts/backtest_system.py"
RECORDS_POLICY = ("scripts/prop/evaluate_prop.py", "scripts/prop/montecarlo_prop.py",
                  "scripts/prop/validate_alt_prop.py", "scripts/prop/account_compat_matrix.py")


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def scan_source(src: str, rel: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and _call_name(node) == "run_system_backtest":
            kws = {k.arg for k in node.keywords}
            missing = {"costs", "require_full_costs"} - kws
            if missing and None not in kws:  # **kwargs splat is not statically checkable
                out.append(f"{rel}:{node.lineno}: run_system_backtest() without {sorted(missing)}")
    return out


def scan_repo() -> list[str]:
    findings: list[str] = []
    for d in SCAN_DIRS:
        for p in sorted((REPO / d).rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            if rel == ENGINE:
                continue
            try:
                findings += scan_source(p.read_text(), rel)
            except SyntaxError:
                continue
    eng = (REPO / ENGINE).read_text()
    for needle in ("costs: Optional[Dict[str, Any]] = None", "require_full_costs: bool = False",
                   "raise CostPolicyError"):
        if needle not in eng:
            findings.append(f"{ENGINE}: engine wrapper lost `{needle}`")
    for rel in RECORDS_POLICY:
        if "cost_policy" not in (REPO / rel).read_text():
            findings.append(f"{rel}: result no longer records `cost_policy`")
    return findings


def self_test() -> int:
    bad = "bt.run_system_backtest(b, roster=[], attach_full=True)\n"
    half = "bt.run_system_backtest(b, costs=c)\n"
    good = "bt.run_system_backtest(b, costs=c, require_full_costs=True)\n"
    assert len(scan_source(bad, "x.py")) == 1, "fee-only call not caught"
    assert len(scan_source(half, "x.py")) == 1, "half-wired call not caught"
    assert scan_source(good, "x.py") == [], "compliant call flagged"
    live = scan_repo()
    assert live == [], f"live repo has findings: {live}"
    print("self-test ok")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    f = scan_repo()
    for line in f:
        print("FINDING:", line)
    print(f"prop-harness-full-costs-guard: {len(f)} finding(s)")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
