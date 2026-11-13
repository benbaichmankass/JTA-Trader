"""Mirror positions with no live twin are flagged; acknowledged legacy ones are
excluded from the Gate-2 window (PI-20261004-J4SFBKU9-0001)."""
from __future__ import annotations

from pathlib import Path

from scripts.ops import check_mirror_orphans as cmo
from scripts.ops.check_mirror_orphans import check as _check
from src.config.mirror_exclusions import excluded_trade_ids, load_mirror_exclusions

PAIRS = {"alpaca_live": "alpaca_portfolio"}
NO_FILTER = lambda account_id, side: False  # noqa: E731 -- a live account with no side_filter


def check(payload, exclusions, pairs=None, side_suppressed=NO_FILTER):
    """The generic checks below model a live account WITHOUT a side_filter."""
    return _check(payload, exclusions, pairs, side_suppressed=side_suppressed)


def _acct(aid, positions, error=None):
    return {"account_id": aid, "positions": positions, "error": error}


def _pos(sym, side="short"):
    return {"symbol": sym, "side": side, "size": 1.0, "unrealised_pnl": 1.0}


ACK = {"readState": "ok", "exclusions": [
    {"trade_id": 5912, "account_id": "alpaca_portfolio", "symbol": "TLT", "side": "short"}]}
NONE = {"readState": "ok", "exclusions": []}


def test_unacknowledged_mirror_only_position_is_orphan():
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [_pos("TLT")])]}
    r = check(p, NONE, PAIRS)
    assert not r["ok"] and r["orphans"][0]["symbol"] == "TLT"


def test_acknowledged_position_is_noted_not_failed():
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [_pos("TLT")])]}
    r = check(p, ACK, PAIRS)
    assert r["ok"] and r["findings"][0]["verdict"] == "acknowledged"


def test_live_twin_is_fine_and_side_must_match():
    p = {"accounts": [_acct("alpaca_live", [_pos("IEF", "short")]),
                      _acct("alpaca_portfolio", [_pos("IEF", "short")])]}
    assert check(p, NONE, PAIRS)["ok"]
    p = {"accounts": [_acct("alpaca_live", [_pos("IEF", "long")]),
                      _acct("alpaca_portfolio", [_pos("IEF", "short")])]}
    assert not check(p, NONE, PAIRS)["ok"]


def test_stale_ack_when_position_closed():
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [])]}
    r = check(p, ACK, PAIRS)
    assert r["findings"][0]["verdict"] == "stale_ack"


def test_unreadable_is_not_clean():
    p = {"accounts": [_acct("alpaca_live", None), _acct("alpaca_portfolio", [])]}
    assert not check(p, NONE, PAIRS)["ok"]
    p = {"accounts": [_acct("alpaca_live", [], error="boom"), _acct("alpaca_portfolio", [])]}
    assert not check(p, NONE, PAIRS)["ok"]
    assert not check({"accounts": []}, NONE, PAIRS)["ok"]
    bad = {"readState": "unreadable", "exclusions": []}
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [])]}
    assert not check(p, bad, PAIRS)["ok"]


def test_default_pairs_cover_both_mirrors():
    r = check({"accounts": []}, NONE)
    assert len(r["unreadable"]) == 2


def test_committed_exclusions_parse_and_name_both_trades():
    assert excluded_trade_ids() == [4195, 5912]
    assert load_mirror_exclusions()["readState"] == "ok"


def test_loader_states(tmp_path: Path):
    assert load_mirror_exclusions(tmp_path / "nope.yaml")["readState"] == "absent"
    bad = tmp_path / "bad.yaml"
    bad.write_text("exclusions: [unclosed", encoding="utf-8")
    assert load_mirror_exclusions(bad)["readState"] == "unreadable"


def test_recent_route_drops_excluded_trade_from_mirror_window(tmp_path, monkeypatch):
    """Through the route's own filter: an excluded trade id leaves the mirror's
    per-leg window and is published in excludedTradeIds."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _perf_window_golden_seed as S
    from src.config import mirror_exclusions as me
    from src.web.api.routers import performance as P

    path = tmp_path / "trade_journal.db"
    S.seed(path)
    monkeypatch.setattr(P, "_DB_PATH", path)
    monkeypatch.setattr(P, "datetime", S.FrozenDatetime)
    monkeypatch.setattr(P, "journal_trust_map", lambda: S.TRUST_MAP)
    monkeypatch.setattr(P, "_book_rosters", lambda: {
        "readState": "ok", "realMoneyLegs": ["leg_a"],
        "portfolioAccounts": ["bybit_portfolio"], "portfolioLegs": ["leg_a"]})
    monkeypatch.setattr(me, "EXCLUSIONS_PATH", tmp_path / "none.yaml")
    base = P.get_performance_recent(n=40)["mirror"]
    assert base["excludedTradeIds"] == [] and base["exclusionsReadState"] == "absent"
    victim = base["perStrategy"]["leg_a"]["blocks"][0]["tradeIds"][0]
    n0 = base["perStrategy"]["leg_a"]["closedAvailable"]

    f = tmp_path / "ex.yaml"
    f.write_text(f"exclusions:\n  - trade_id: {victim}\n", encoding="utf-8")
    monkeypatch.setattr(me, "EXCLUSIONS_PATH", f)
    m = P.get_performance_recent(n=40)["mirror"]
    assert m["excludedTradeIds"] == [victim] and m["exclusionsReadState"] == "ok"
    assert m["perStrategy"]["leg_a"]["closedAvailable"] == n0 - 1
    assert all(victim not in b["tradeIds"] for b in m["perStrategy"]["leg_a"]["blocks"])


# ── MIRROR-ORPHAN-SIDE-FILTER: the declared superset is noted, not an orphan ─────────────────────────────────────

LONG_ONLY = lambda account_id, side: account_id == "alpaca_live" and side == "short"  # noqa: E731


def test_a_mirror_short_the_long_only_live_book_suppressed_is_side_filter_superset_not_orphan():
    """Run 43512052836: alpaca_portfolio SLV short 3428, live twin 7189 rejected (dry_cause side_filter:long)."""
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [_pos("SLV", "short")])]}
    r = check(p, NONE, PAIRS, side_suppressed=LONG_ONLY)
    assert r["ok"] and r["orphans"] == []
    assert r["findings"] == [{"pair": "alpaca_live->alpaca_portfolio", "symbol": "SLV", "side": "short",
                              "size": 1.0, "unrealised_pnl": 1.0, "verdict": "side_filter_superset"}]


def test_a_mirror_LONG_with_no_live_twin_is_still_an_orphan_under_a_long_only_filter():
    p = {"accounts": [_acct("alpaca_live", []), _acct("alpaca_portfolio", [_pos("SLV", "long")])]}
    r = check(p, NONE, PAIRS, side_suppressed=LONG_ONLY)
    assert not r["ok"] and r["orphans"][0]["symbol"] == "SLV"


def test_the_default_resolver_reads_the_real_alpaca_live_side_filter():
    """alpaca_live is `side_filter: long` in config/accounts.yaml: a short is suppressed, a long is not."""
    assert cmo._live_side_suppressed("alpaca_live", "short") is True
    assert cmo._live_side_suppressed("alpaca_live", "long") is False
