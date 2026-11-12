from scripts.ops.oci_resize_a1 import check_budget

ROWS = [
    {"display_name": "ict-bot-arm", "ocpus": 2.0, "memory_gb": 12.0},
    {"display_name": "ict-trainer-vm", "ocpus": 1.0, "memory_gb": 6.0},
    {"display_name": "ict-ib-gateway", "ocpus": 1.0, "memory_gb": 6.0},
]


def test_shrink_gateway_ok():
    ok, _, o, m = check_budget(ROWS, "ict-ib-gateway", 1.0, 3.0)
    assert ok and o == 4 and m == 21


def test_trainer_grow_first_refused_over_cap():
    assert not check_budget(ROWS, "ict-trainer-vm", 1.0, 9.0)[0]


def test_trainer_grow_after_shrink_ok():
    rows = [dict(r) for r in ROWS]
    rows[2]["memory_gb"] = 3.0
    ok, _, _o, m = check_budget(rows, "ict-trainer-vm", 1.0, 9.0)
    assert ok and m == 24


def test_trader_refused():
    assert not check_budget(ROWS, "ict-bot-arm", 2.0, 8.0)[0]


def test_ocpu_change_refused():
    assert not check_budget(ROWS, "ict-ib-gateway", 2.0, 3.0)[0]
