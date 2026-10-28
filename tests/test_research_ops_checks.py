"""research_ops_checks: the pure helpers the CHECKS packet is built from."""
from datetime import datetime, timezone

from scripts.research.research_ops_checks import batch_of, expand_ids, parse_since, track


def test_track_programme_wins_then_model_markers():
    assert track({"programme": "P2", "theme": "regime"}) == "MODEL"
    assert track({"programme_node": {"programme": "P1"}, "ml_bakeoff": {}}) == "TRADING"
    assert track({"theme": "regime", "ml_bakeoff": {"x": 1}}) == "MODEL"
    assert track({"theme": "ml_health"}) == "MODEL"
    assert track({"theme": "infra"}) == "INFRA"
    assert track({"theme": "live_strategy"}) == "TRADING"


def test_expand_ids_ranges_and_notes():
    assert expand_ids(["RQ-20261027-3e41-01..03", "RQ-20261027-d789-01 (note)"]) == [
        "RQ-20261027-3e41-01", "RQ-20261027-3e41-02", "RQ-20261027-3e41-03", "RQ-20261027-d789-01"]


def test_batch_of():
    assert batch_of("RQ-20261026-ed1c-07") == "RQ-20261026-ed1c"
    assert batch_of("RQ-20261024-001") is None


def test_parse_since():
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert parse_since("7d", now).day == 21
    assert parse_since("6h", now).hour == 6
    assert parse_since("2026-10-27T21:10:00Z", now).hour == 21


def test_expand_ids_old_record_shapes():
    assert expand_ids(["RQ-20261024-003..005", {"unit": "RQ-20261025-3947-19"}, {"node": "P4-Q2-x"},
                       "RQ-20261026-ed1c-01..02:", "programme", "3947-19"]) == [
        "RQ-20261024-003", "RQ-20261024-004", "RQ-20261024-005", "RQ-20261025-3947-19", "P4-Q2-x",
        "RQ-20261026-ed1c-01", "RQ-20261026-ed1c-02"]
