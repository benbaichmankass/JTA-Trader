"""TRADER-RESTART-GATE: the trader's import closure and the restart decision.

Pins (1) the committed closure equals a fresh walk (the same check the
``trader-import-closure`` guard runs), (2) what the walk follows, (3) the
non-literal dynamic-import sites inside the closure -- a NEW one fails here and
has to be looked at, because the walk cannot see what it loads -- and (4) that
every unsure case decides RESTART.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "trader_import_closure", REPO / "scripts" / "ops" / "trader_import_closure.py")
tic = importlib.util.module_from_spec(_spec)
sys.modules["trader_import_closure"] = tic
_spec.loader.exec_module(tic)


@pytest.fixture(scope="module")
def live():
    return tic.compute_closure(tic.FsSource(REPO))


def test_committed_closure_matches_a_fresh_walk(live):
    assert tic.read_committed(REPO) == live.files, (
        "config/trader_import_closure.txt drifted; run "
        "python3 scripts/ops/trader_import_closure.py generate")
    assert not live.incomplete


def test_closure_contains_the_trader_and_not_the_web_api(live):
    assert "src/main.py" in live.files
    assert "src/__init__.py" in live.files
    assert "src/runtime/pipeline.py" in live.files
    assert "src/web/api/main.py" not in live.files


def test_every_strategy_module_is_in_the_closure(live):
    """coordinator/order_monitor load ``src.units.strategies.{name}`` by a
    computed name; the literal prefix pulls the whole package in."""
    on_disk = {str(p.relative_to(REPO)) for p in (REPO / "src/units/strategies").rglob("*.py")}
    assert on_disk and on_disk <= live.files


# Non-literal import calls inside the closure. Each was read on 2026-10-15:
#  - coordinator / order_monitor: f"src.units.strategies.{x}" -> whole package
#    is in the closure via the literal prefix (test above).
#  - market_data: _connector_class_id("src.exchange.<x>", ...) literal args ->
#    the string-literal rule picks each module up.
#  - ml/experiments/runner, ml/shadow/factory: qualnames from manifests / model
#    state, "ml.trainers.*" -- ml/ is outside src/ and scripts/, so ANY ml/ .py
#    change restarts the trader regardless (rule c).
KNOWN_DYNAMIC_SITES = {
    "ml/experiments/runner.py",
    "ml/shadow/factory.py",
    "src/core/coordinator.py",
    "src/runtime/market_data.py",
    "src/runtime/order_monitor.py",
}


def test_no_new_dynamic_import_site(live):
    files = {s.rsplit(":", 1)[0] for s in live.dynamic_sites}
    new = files - KNOWN_DYNAMIC_SITES
    assert not new, (
        f"new non-literal import call(s) in the trader closure: {sorted(new)}. The walk "
        "cannot follow them: make sure what they load is in the closure (a literal "
        "'pkg.' prefix or module string), then add the file to KNOWN_DYNAMIC_SITES.")


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tic.compute_closure(tic.FsSource(tmp_path))


def test_walk_follows_every_import_form(tmp_path):
    cl = _tree(tmp_path, {
        "src/__init__.py": "",
        "src/main.py": (
            "import src.a\n"
            "def f():\n    from src.pkg import sub\n"
            "try:\n    from . import rel\nexcept ImportError:\n    pass\n"
            "import importlib\nimportlib.import_module('src.lit')\n"
            "M = 'src.qual.Klass'\n"
            "def g(n):\n    return importlib.import_module(f'src.plug.{n}')\n"
        ),
        "src/a.py": "", "src/rel.py": "", "src/lit.py": "", "src/qual.py": "",
        "src/pkg/__init__.py": "", "src/pkg/sub.py": "",
        "src/plug/__init__.py": "", "src/plug/one.py": "", "src/plug/deep/two.py": "",
        "src/unused.py": "",
    })
    for f in ("src/a.py", "src/pkg/__init__.py", "src/pkg/sub.py", "src/rel.py",
              "src/lit.py", "src/qual.py", "src/plug/one.py", "src/plug/deep/two.py"):
        assert f in cl.files, f
    assert "src/unused.py" not in cl.files
    assert cl.dynamic_sites == ["src/main.py:12"]


def test_unparsable_file_marks_the_closure_incomplete(tmp_path):
    cl = _tree(tmp_path, {"src/__init__.py": "", "src/main.py": "import src.b\n",
                          "src/b.py": "def x(:\n"})
    assert cl.incomplete == ["src/b.py"]


@pytest.mark.parametrize("path,expect", [
    ("src/web/api/routers/work.py", None),
    ("scripts/ops/some_cli.py", None),
    ("docs/x.md", None),
    ("src/main.py", "in_closure"),
    ("config/accounts.yaml", "non_py_runtime"),
    ("comms/live_parity/x.json", "non_py_runtime"),
    ("ml/x.py", "py_outside_src_scripts"),
    ("tests/test_x.py", None),
])
def test_classify_path(path, expect):
    assert tic.classify_path(path, {"src/main.py"}) == expect


def test_decide_skips_only_a_positive_all_clear():
    assert tic.decide(["src/web/x.py"], {"src/main.py"})[0] == tic.SKIP
    assert tic.decide(["src/web/x.py", "src/main.py"], {"src/main.py"})[0] == tic.RESTART
    assert tic.decide(["src/web/x.py"], None)[0] == tic.RESTART      # no closure
    assert tic.decide([], {"src/main.py"})[0] == tic.RESTART         # empty diff
    assert tic.decide(["", "  "], {"src/main.py"})[0] == tic.RESTART


def test_deploy_closure_fails_safe(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("")
    closure, notes = tic.deploy_closure(tmp_path)
    assert closure is None and "missing" in notes[0]
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "trader_import_closure.txt").write_text("# header only\n")
    assert tic.deploy_closure(tmp_path)[0] is None                    # empty = unreadable
    (tmp_path / "config" / "trader_import_closure.txt").write_text("src/main.py\n")
    assert tic.deploy_closure(tmp_path)[0] == {"src/main.py"}
