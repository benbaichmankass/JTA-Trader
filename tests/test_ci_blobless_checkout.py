"""CI-STREAMLINE (2026-11-03): pytest-run and guards check out blobless, never shallow.

Full commit history stays (guards and tests read `git log`, merge-bases and record ages; a depth-N clone would make them
answer wrongly without failing), while file contents arrive only for the checked-out tree.
"""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _checkout(name):
    steps = yaml.safe_load((WF / f"{name}.yml").read_text())["jobs"][name]["steps"]
    return next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))


def test_blobless_full_history():
    for name in ("guards", "pytest-run"):
        w = _checkout(name).get("with") or {}
        assert w.get("filter") == "blob:none", name
        assert w.get("fetch-depth") == 0, f"{name}: history is read by guards/tests; never shallow"
