import sys


def test_self_test_and_cells():
    sys.path.insert(0, "scripts/research")
    import regime_gate_family_consumer as m
    m._selftest()
    cells = m.load_cells("config/regime_policy.yaml", "trend_donchian")
    assert ("trending", "volatile", "long") in cells  # YAML bare `off` -> False must still count as off
