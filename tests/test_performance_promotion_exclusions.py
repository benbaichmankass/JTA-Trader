"""Operator decision 2026-11-25 (W48 Q3): trades in comms/promotion_exclusions.yaml are out of every promotion/demotion read
and stay visible + labelled. This pins the two served routes that feed a rule (``/performance/recent``,
``/performance/trade-series``); ``/performance`` keeps every total and stays byte-pinned by its golden."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _perf_window_golden_seed as S  # noqa: E402

from scripts.ops import promotion_exclusions as PEX  # noqa: E402
from src.web.api.routers import performance as P  # noqa: E402

ROSTERS = {"readState": "ok", "realMoneyLegs": ["leg_a", "leg_b", "leg_never_closed"],
           "portfolioAccounts": ["bybit_portfolio"], "portfolioLegs": ["leg_a"]}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "trade_journal.db"
    S.seed(path)
    monkeypatch.setattr(P, "_DB_PATH", path)
    monkeypatch.setattr(P, "datetime", S.FrozenDatetime)
    monkeypatch.setattr(P, "journal_trust_map", lambda: S.TRUST_MAP)
    monkeypatch.setattr(P, "_portfolio_paper_account_ids", lambda: ["bybit_portfolio"])
    monkeypatch.setattr(P, "_book_rosters", lambda: ROSTERS)
    monkeypatch.setattr(PEX, "load", lambda path=None: [])
    return path


def _ids(out, book):
    return {i for leg in out[book]["perStrategy"].values() for b in leg["blocks"] for i in b["tradeIds"]}


def test_no_entries_is_ok_and_empty_on_every_served_book(db):
    out = P.get_performance_recent(n=40)
    for book in ("realMoney", "mirror"):
        assert out[book]["promotionExclusionsReadState"] == "ok" and out[book]["promotionExcluded"] == []
    ser = P.get_performance_trade_series(n=40)
    assert ser["realMoney"]["promotionExclusionsReadState"] == "ok" and ser["realMoney"]["promotionExcluded"] == []


def test_an_excluded_real_money_trade_leaves_the_blocks_but_is_labelled(db, monkeypatch):
    base = P.get_performance_recent(n=40)
    victim = sorted(_ids(base, "realMoney"))[-1]
    acct = next(r["account_id"] for r in P._query(db, None, demo=False) if r["trade_id"] == victim)
    monkeypatch.setattr(PEX, "load", lambda path=None: [
        {"trade_id": victim, "account_id": acct, "provenance": "ESTIMATED", "reason": "test", "decided": "2026-11-25"}])
    out = P.get_performance_recent(n=40)
    assert victim not in _ids(out, "realMoney")
    lab = out["realMoney"]["promotionExcluded"]
    assert [x["tradeId"] for x in lab] == [victim] and lab[0]["provenance"] == "ESTIMATED" and lab[0]["decided"] == "2026-11-25"
    ser = P.get_performance_trade_series(n=40)
    assert victim not in {pt["tradeId"] for leg in ser["realMoney"]["perStrategy"].values() for pt in leg["series"]}
    assert [x["tradeId"] for x in ser["realMoney"]["promotionExcluded"]] == [victim]


def test_an_excluded_mirror_trade_leaves_the_mirror_blocks(db, monkeypatch):
    base = P.get_performance_recent(n=40)
    victim = sorted(_ids(base, "mirror"))[-1]
    monkeypatch.setattr(PEX, "load", lambda path=None: [{"trade_id": victim, "provenance": "ESTIMATED"}])
    out = P.get_performance_recent(n=40)
    assert victim not in _ids(out, "mirror")
    assert [x["tradeId"] for x in out["mirror"]["promotionExcluded"]] == [victim]


def test_an_entry_naming_another_account_does_not_exclude(db, monkeypatch):
    base = P.get_performance_recent(n=40)
    victim = sorted(_ids(base, "realMoney"))[-1]
    monkeypatch.setattr(PEX, "load", lambda path=None: [{"trade_id": victim, "account_id": "ib_paper"}])
    out = P.get_performance_recent(n=40)
    assert victim in _ids(out, "realMoney") and out["realMoney"]["promotionExcluded"] == []


def test_an_unreadable_file_is_published_not_read_as_none(db, monkeypatch):
    def boom(path=None):
        raise ValueError("broken yaml")
    base_ids = _ids(P.get_performance_recent(n=40), "realMoney")
    monkeypatch.setattr(PEX, "load", boom)
    out = P.get_performance_recent(n=40)
    assert out["realMoney"]["promotionExclusionsReadState"] == "unreadable"
    assert out["mirror"]["promotionExclusionsReadState"] == "unreadable"
    assert _ids(out, "realMoney") == base_ids          # rows untouched; the gate can refuse on the state
    assert P.get_performance_trade_series(n=40)["realMoney"]["promotionExclusionsReadState"] == "unreadable"
