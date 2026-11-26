"""CI-BRIEF-RENDER-TIMEOUT: the queue readers on the daily-brief path parse through libyaml with an unchanged result."""
from __future__ import annotations

import yaml
import pytest

from scripts.research.queue_replenish import _fast_unit_load
from scripts.ops import blocker_watch

DOC = "id: RQ-1\nstatus: queued\nrun:\n  command: [python3, x.py]\nvalue: {usd: 200, confidence: 0.3}\nnote: 'a: b'\n"


@pytest.mark.parametrize("fn", [_fast_unit_load, blocker_watch._fast_unit_load])
def test_same_document_as_safe_load(fn):
    assert fn(yaml, DOC) == yaml.safe_load(DOC)


@pytest.mark.parametrize("fn", [_fast_unit_load, blocker_watch._fast_unit_load])
def test_bad_yaml_raises_the_safe_load_error(fn):
    bad = "a: [1, 2\n"
    with pytest.raises(yaml.YAMLError) as fast_err:
        fn(yaml, bad)
    with pytest.raises(yaml.YAMLError) as slow_err:
        yaml.safe_load(bad)
    assert str(fast_err.value) == str(slow_err.value)   # the pure-loader fallback keeps the caller's error text


def test_uses_libyaml_when_available(monkeypatch):
    if not hasattr(yaml, "CSafeLoader"):
        pytest.skip("this build has no libyaml")
    seen = []
    real = yaml.load
    monkeypatch.setattr(yaml, "load", lambda t, L: (seen.append(L), real(t, L))[1])
    _fast_unit_load(yaml, DOC)
    assert seen == [yaml.CSafeLoader]
