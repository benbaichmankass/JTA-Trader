"""Corpus v2 generator (scripts/research/broad_paths_corpus.py): frozen-symbol rule, corpus_id stability, trade_key de-dup."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import broad_paths_corpus as bp  # noqa: E402


def test_self_test():
    assert bp._self_test() == 0


def test_rule_excludes_delivery_short_history_and_delisted():
    spans = {"AUSDT": ("2020-01", "2026-09"), "BUSDT": ("2020-01", "2026-08"), "CUSDT": ("2024-10", "2026-09"),
             "DUSDT_260327": ("2020-01", "2026-09"), "EUSDT": ("2024-09", "2026-10")}
    assert [r["symbol"] for r in bp.select_universe(spans)] == ["AUSDT", "EUSDT"]


def test_legs_are_the_six_money_legs():
    assert len(bp.LEGS) == 6 and len(set(bp.LEGS)) == 6
