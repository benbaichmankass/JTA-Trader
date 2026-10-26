"""CI-SPEED-1026 fix 2: the queue loader's parse shortcuts must not change results."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import dispatch_queue as dq  # noqa: E402
import research_queue as rq  # noqa: E402


def test_fast_load_equals_safe_load_on_every_committed_unit():
    files = sorted((REPO / "research" / "queue").glob("*.yaml"))
    assert files
    for f in files:
        text = f.read_text()
        assert rq._fast_safe_load(yaml, text) == yaml.safe_load(text), f.name


def test_fast_load_error_is_the_pure_loader_error():
    bad = "a: [unclosed\nb: : :\n"
    try:
        yaml.safe_load(bad)
    except yaml.YAMLError as exc:
        expected = str(exc)
    else:  # pragma: no cover
        raise AssertionError("fixture must be invalid YAML")
    try:
        rq._fast_safe_load(yaml, bad)
    except yaml.YAMLError as exc:
        assert str(exc) == expected
    else:  # pragma: no cover
        raise AssertionError("must raise")


def test_compute_doc_is_cached_but_equals_a_fresh_parse():
    path = REPO / "scripts" / "research" / "research_compute.yaml"
    assert rq._compute_doc() == yaml.safe_load(path.read_text(encoding="utf-8"))
    assert rq._compute_doc() is rq._compute_doc()


def test_declared_inputs_cached_equals_uncached_and_sees_edits(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "x.yml").write_text(
        "on:\n  workflow_dispatch:\n    inputs:\n      a: {}\n      b: {}\n"
    )
    assert dq.declared_inputs("x.yml", repo=tmp_path) == ["a", "b"]
    assert dq.declared_inputs("x.yml", repo=tmp_path) == dq._read_declared_inputs(
        wf / "x.yml"
    )
    (wf / "x.yml").write_text("on:\n  workflow_dispatch:\n    inputs:\n      c: {}\n")
    assert dq.declared_inputs("x.yml", repo=tmp_path) == ["c"]
    assert dq.declared_inputs("missing.yml", repo=tmp_path) is None
