"""read_ledger.py: claims and results fold into (subject, window) reads; unstated windows are counted, never dropped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import read_ledger  # noqa: E402


def test_self_test():
    read_ledger.self_test()


def test_resolve_window_sources():
    assert read_ledger.resolve_window({"data_start": "2025-01-02 00:00", "data_end": "2025-03-01"}, None)[:2] == ("2025-01-02", "2025-03-01")
    assert read_ledger.resolve_window({"window": {"fold_edges": ["2021-01-01 00:00", "2023-01-01"]}}, None)[:2] == ("2021-01-01", "2023-01-01")
    assert read_ledger.resolve_window({}, "cmd --since 2026-11-29")[:2] == ("2026-11-29", read_ledger.OPEN_END)
    assert read_ledger.resolve_window({}, "no dates here") == (None, None, "window_unstated")
