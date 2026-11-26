"""eq_confirm_concentration self-test (RQ-20261126-7c11-03)."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
import eq_confirm_concentration as C  # noqa: E402


def test_self_test():
    C.self_test()


def test_rows_are_emit_valid():
    d = C.decompose([{"symbol": "A", "ts": f"2026-0{m}-10 15:00:00+00:00", "net_r": 0.2} for m in range(1, 8) for _ in range(5)])
    g = C.grade({"served": d}, "served")
    assert g["read_state"] == "measured" and isinstance(g["n"], int)
