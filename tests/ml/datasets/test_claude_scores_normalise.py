from ml.datasets.claude_scores_normalise import (
    dedupe_latest,
    derive_author_kind,
    normalise_row,
)


def test_author_kind_template_rule():
    assert derive_author_kind({"rationale": "x; entry=a; risk=b"}) == "rubric_script"
    assert derive_author_kind({"rationale": "Claude wrote prose"}) == "llm"
    assert derive_author_kind({"author_kind": "human", "rationale": "entry= risk="}) == "human"


def test_vocab_mapping_flags():
    r = normalise_row({"entry_quality": "good"})
    assert r["entry_quality"] == "acceptable" and r["vocab_mapped"] is True
    r = normalise_row({"entry_quality": "poor"})
    assert r["entry_quality"] == "late"
    r = normalise_row({"entry_quality": "optimal"})
    assert r["entry_quality"] == "optimal" and r["vocab_mapped"] is False


def test_dedupe_latest_per_key_and_keyed_on():
    rows = [
        {"order_package_id": "p1", "reviewed_at": "2026-01-01", "v": 1},
        {"order_package_id": "p1", "reviewed_at": "2026-02-01", "v": 2},
        {"order_package_id": "p1", "keyed_on": "linked_trade_id", "linked_trade_id": 7,
         "reviewed_at": "2026-01-01", "v": 3},
        {"order_package_id": "p1", "keyed_on": "linked_trade_id", "linked_trade_id": 7,
         "reviewed_at": "2026-03-01", "v": 4},
        {"reviewed_at": "2026-01-01", "v": 5},
    ]
    assert sorted(r["v"] for r in dedupe_latest(rows)) == [2, 4]
