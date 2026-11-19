"""Research harness entry points must not leak the module knobs they assign (see src/backtest/module_globals.py).

PR #27149: backtest_ict_scalp.main() left a venue-aware cost stack in module globals; the next in-process run moved
net_total_r -14.7793 -> -17.1766 on identical trades. Sweep of the sibling harnesses 2026-11-19 (PI-20261119-FILLW47B-0001).
Locks: (1) the decorator restores on return AND on exception, (2) every harness main()/entry point that declares `global X`
restores X (a new knob added later without updating the list fails here), (3) every restored name exists in its module."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from src.backtest.module_globals import restores_globals

REPO = Path(__file__).resolve().parents[1]
# (module path, entry points that assign module globals)
HARNESSES = {
    "scripts/backtest_chop_scalp.py": ("main",),
    "scripts/backtest_fade.py": ("main",),
    "scripts/backtest_funding_carry.py": ("main",),
    "scripts/backtest_fvg_range.py": ("main",),
    "scripts/backtest_orb.py": ("main",),
    "scripts/backtest_pairs.py": ("main",),
    "scripts/backtest_pullback.py": ("main",),
    "scripts/backtest_squeeze.py": ("main",),
    "scripts/backtest_system.py": ("main", "run_system_backtest"),
    "scripts/backtest_trend.py": ("main",),
    "src/backtest/run_backtest_vwap.py": ("main",),
}
_IGNORED = {"_CACHE_WRITE_WARNED"}   # a warn-once flag, not a result-bearing knob


def test_decorator_restores_on_return_and_on_exception():
    def assign(boom: bool):
        g = assign.__globals__
        g["_KNOB_A"], g["_KNOB_B"] = 99, "y"
        if boom:
            raise RuntimeError("x")
        return "ok"

    g = assign.__globals__
    g["_KNOB_A"], g["_KNOB_B"] = 1, "x"
    try:
        w = restores_globals("_KNOB_A", "_KNOB_B")(assign)
        assert w(False) == "ok" and (g["_KNOB_A"], g["_KNOB_B"]) == (1, "x")
        with pytest.raises(RuntimeError):
            w(True)
        assert (g["_KNOB_A"], g["_KNOB_B"]) == (1, "x")
        assert w.__restored_globals__ == ("_KNOB_A", "_KNOB_B")
    finally:
        g.pop("_KNOB_A", None)
        g.pop("_KNOB_B", None)


def test_a_misnamed_knob_fails_loudly():
    def f():
        return 1
    with pytest.raises(KeyError):
        restores_globals("NO_SUCH_KNOB_XYZ")(f)()


@pytest.mark.parametrize("rel,entries", sorted(HARNESSES.items()))
def test_every_assigned_global_is_restored(rel, entries):
    tree = ast.parse((REPO / rel).read_text())
    mod = importlib.import_module(rel[:-3].replace("/", "."))
    for name in entries:
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assigned = {x for n in ast.walk(fn) if isinstance(n, ast.Global) for x in n.names} - _IGNORED
        restored = set(getattr(getattr(mod, name), "__restored_globals__", ()))
        assert assigned <= restored, f"{rel}:{name} assigns {sorted(assigned - restored)} but does not restore them"
        for g in restored:
            assert g in vars(mod), f"{rel}: restored knob {g} is not a module global"


def test_no_other_harness_main_assigns_unrestored_globals():
    """A NEW scripts/backtest_*.py whose main() declares `global` must join HARNESSES (and be decorated)."""
    known = {Path(k).name for k in HARNESSES} | {"backtest_ict_scalp.py"}   # ict_scalp: PR #27175's own decorator + test
    for p in sorted((REPO / "scripts").glob("backtest_*.py")):
        if p.name in known:
            continue
        tree = ast.parse(p.read_text())
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef) and fn.name == "main":
                g = {x for n in ast.walk(fn) if isinstance(n, ast.Global) for x in n.names} - _IGNORED
                assert not g, f"{p.name}:main assigns {sorted(g)}: add it to HARNESSES and decorate it with restores_globals"
