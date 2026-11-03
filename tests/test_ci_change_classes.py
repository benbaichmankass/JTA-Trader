"""CI-STREAMLINE (operator 2026-11-03): ONE change-class map decides what each kind of change gets in pytest-run.

The map is .github/ci-change-classes.json. Pinned here:
  * every tracked path maps to a named class (a new top-level tree must be classified, not silently defaulted);
  * an unclassified path gets the FULL suite (fail toward testing);
  * order-path / risk / sizing / gate-config paths ALWAYS get the full suite, never an affected-tests subset;
  * a data-only diff runs the readers of the trees it touches, and an unknown data path never narrows below all readers.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pytest_run_scope_cc", REPO / "scripts" / "ci" / "pytest_run_scope.py")
scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scope)

ORDER_PATH = [
    "src/units/accounts/risk.py", "src/units/accounts/account.py", "src/exchange/bybit_connector.py",
    "src/core/coordinator.py", "src/core/allocator.py", "src/core/order_contract.py",
    "src/units/strategies/pairs_executor.py", "src/prop/prop_executor.py", "src/prop/prop_sizing.py",
    "src/prop/prop_risk_gate.py", "src/main.py", "src/runtime/anything.py",
    "config/strategies.yaml", "config/accounts.yaml", "config/pairs.yaml", "config/mandates.yaml",
]


def test_the_map_is_valid_json_with_known_behaviours():
    m = json.loads((REPO / ".github" / "ci-change-classes.json").read_text())
    names = [c["name"] for c in m["classes"]]
    assert len(names) == len(set(names))
    assert {c["behaviour"] for c in m["classes"]} <= {"full", "data", "default"}
    assert names[0] == "order_path", "order_path must win before any narrower class can claim its files"


def test_every_tracked_path_maps_to_a_class():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("not a git checkout")
    unclassified = [f for f in out.stdout.splitlines() if scope.class_of(f) == "unclassified"]
    assert not unclassified, f"classify these in .github/ci-change-classes.json: {unclassified[:20]}"


def test_unclassified_gets_the_full_suite():
    assert scope.class_of("brand-new-tree/x.zz") == "unclassified"
    assert scope.full_suite_class("brand-new-tree/x.zz")


@pytest.mark.parametrize("path", ORDER_PATH)
def test_order_path_always_gets_the_full_suite(path):
    assert scope.class_of(path) == "order_path", path
    assert scope.full_suite_class(path)
    mode, reason, _ = scope.classify_affected([path], scope.relevance_regex())
    assert mode == "full", reason


def test_order_path_wins_even_beside_a_data_file():
    mode, _ = scope.classify(["research/results/a.json", "src/units/accounts/risk.py"], scope.relevance_regex())
    assert mode == "full"


def test_per_tree_selection_is_a_subset_of_all_readers_and_never_empty():
    every = set(scope.select_tests())
    for tree in scope.DATA_TREES:
        sample = tree["paths"][0].lstrip("^").replace("\\", "").replace("(?!schema/)", "x/").replace("[^/]+", "x").replace("?ml$", "ml").rstrip("$") + ("" if tree["paths"][0].endswith("$") else "f.json")
        part = set(scope.select_tests(changed=[sample]))
        assert scope.trees_touched([sample]) == [tree["tree"]], (tree["tree"], sample)
        assert set(scope.ALWAYS) <= part <= every, tree["tree"]
        assert len(part) > len(scope.ALWAYS), tree["tree"]


def test_a_changed_list_touching_no_tree_falls_back_to_all_readers():
    assert set(scope.select_tests(changed=["README.md"])) == set(scope.select_tests())


def test_the_workflow_passes_the_diff_to_the_data_selector():
    text = (REPO / ".github" / "workflows" / "pytest-run.yml").read_text()
    assert "--select-tests --changed /tmp/changed-files.txt" in text
    assert "> /tmp/changed-files.txt" in text
