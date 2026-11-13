"""TREND-ALIGN-V1 labeller (docs/research/trend-alignment-framework-2026-11-13.md): pins the registered definition."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import trend_alignment as ta  # noqa: E402


def test_self_test_passes():
    assert ta.self_test() == 0


def test_registered_constants_match_the_doc_and_the_detector():
    from src.runtime.regime import detector as det
    doc = (REPO / ta.DOC).read_text()
    assert ta.DEFINITION_ID in doc and ta.REGISTERED_AT in doc
    assert ta.TREND_MIN_ADX == det.TREND_MIN_ADX == 25.0 and ta.MIN_BARS == det._MIN_BARS == 30
    for reason in ta.MISSING_REASONS:
        assert f"`{reason}`" in doc, reason


def test_missing_is_never_neutral_or_zero_and_is_counted():
    up = ta._bars(200, 0.004)
    rows = [ta.label_trade({"id": i, "timestamp": up["close_time"].iloc[150].isoformat(), "direction": d,
                            "strategy_name": "leg", "account_class": "paper"}, "1h", up if i else None, up)
            for i, d in enumerate(("long", "long", "short"))]
    assert rows[0]["LEG"] == {**rows[0]["LEG"], "label": None, "missing_reason": "no_candles"}
    assert rows[1]["LEG"]["label"] == "with_trend" and rows[2]["LEG"]["label"] == "counter_trend"
    s = ta.summarize(rows, n_rows=3, n_closed=3)
    assert s["labels_by_tf"]["LEG"] == {"missing": 1, "with_trend": 1, "counter_trend": 1}
    assert s["missing_by_reason"]["LEG"] == {"no_candles": 1}
    assert s["by_leg"]["leg"] == {"paper:missing": 1, "paper:with_trend": 1, "paper:counter_trend": 1}


def test_labels_carry_no_account_id_or_pnl():
    up = ta._bars(200, 0.004)
    row = ta.label_trade({"id": 9, "timestamp": up["close_time"].iloc[150].isoformat(), "direction": "long",
                          "strategy_name": "leg", "account_class": "prop", "account_id": "SECRET-ACCT",
                          "pnl": 123.45}, "1h", up, up)
    flat = str(row)
    assert "SECRET-ACCT" not in flat and "123.45" not in flat and "account_id" not in row and "pnl" not in row
