"""CI-THROUGHPUT-20261029: the pre-push helper and the guard-timing summary."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_slowest_guards_block_orders_and_totals():
    rg = _load("scripts/ci/run_guards.py", "rg_t")
    out = rg.slowest_guards_block([("a", 1.0), ("b", 9.0), ("c", 5.0)], top=2)
    lines = out.splitlines()
    assert "15.0s over 3 guard(s)" in lines[0]
    assert lines[1].endswith(" b") and lines[2].endswith(" c")
    assert len(lines) == 3


def test_slowest_guards_block_empty_is_safe():
    rg = _load("scripts/ci/run_guards.py", "rg_t2")
    assert "0.0s over 0 guard(s)" in rg.slowest_guards_block([])


def test_prepush_is_not_a_gate():
    """A habit, not a gate: no workflow may require or invoke it."""
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "prepush.py" not in wf.read_text(), wf.name


def test_prepush_documented_where_lanes_read_it():
    for rel in (".claude/skills/git-actions/SKILL.md", ".claude/skills/manager/SKILL.md"):
        assert "scripts/ci/prepush.py" in (ROOT / rel).read_text(), rel
