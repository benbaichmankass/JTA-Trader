"""DASH-PROP-OVERVIEW: aggregate prop book for the SPA Overview."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import src.prop.prop_journal as pj
import src.prop.prop_reconcile as pr
from src.prop import prop_overview as po


@pytest.fixture(autouse=True)
def _no_mark_feed(monkeypatch):
    """No network: the PROP-TRACKING mark estimate reads the bot's Bybit feed. Default = feed unavailable
    (no estimate), so these tests keep measuring the venue/journal states; tests/test_prop_tracking.py
    covers the estimate."""
    monkeypatch.setattr("src.runtime.local_pnl.last_mark_price", lambda *a, **k: None)

NOW = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
ACCTS = {
    "velotrade_1": {"account_class": "prop", "mode": "live"},
    "tradeify_1": {"account_class": "prop", "mode": "live"},
    "breakout_2": {"account_class": "prop", "mode": "live"},
    "bybit_2": {"account_class": "real_money"},
}
EQ = {"velotrade_1": (4993.08, "ok"), "tradeify_1": (9942.54, "ok"),
      "breakout_2": (5000.0, "stale")}


def _patch(monkeypatch, fills):
    monkeypatch.setattr(pj, "latest_account_status",
                        lambda a: {"equity": EQ[a][0]})
    monkeypatch.setattr(pr, "compute_rule_distance",
                        lambda a, s=None: {"status_freshness": EQ[a][1],
                                           "status_age_hours": 1.0})
    monkeypatch.setattr(pj, "list_fills",
                        lambda account_id=None, limit=100: [f for f in fills if f["account_id"] == account_id])


def _fill(i, acct, status, pnl=None, closed_days_ago=None, tkt=None):
    return {"id": i, "account_id": acct, "status": status, "pnl": pnl, "ticket_id": tkt or f"t{i}",
            "external_order_id": None, "symbol": "ETHUSDT", "direction": "long", "qty": 1.0,
            "entry_price": 100.0, "sl": 99.0, "tp": 110.0, "opened_at": None,
            "closed_at": (NOW - timedelta(days=closed_days_ago)).isoformat() if closed_days_ago is not None else None,
            "reported_at": NOW.isoformat()}


def test_equity_sums_fresh_only_and_lists_stale(monkeypatch):
    _patch(monkeypatch, [])
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    assert o["equity"]["total_usd"] == round(4993.08 + 9942.54, 2)
    assert o["equity"]["accounts_counted"] == 2 and o["equity"]["accounts_total"] == 3
    stale = [a for a in o["equity"]["accounts"] if a["account_id"] == "breakout_2"][0]
    assert stale["counted_in_total"] is False and stale["equity"] == 5000.0


def test_no_fresh_equity_is_null_not_zero(monkeypatch):
    _patch(monkeypatch, [])
    monkeypatch.setattr(pr, "compute_rule_distance",
                        lambda a, s=None: {"status_freshness": "stale"})
    assert po.build_overview("7d", accounts=ACCTS, now=NOW)["equity"]["total_usd"] is None


def test_open_trade_listed_and_closed_ticket_not_open(monkeypatch):
    fills = [_fill(96, "velotrade_1", "open", tkt="A"),
             _fill(1, "velotrade_1", "open", tkt="B"),
             _fill(2, "velotrade_1", "closed", pnl=10.0, closed_days_ago=1, tkt="B"),
             _fill(3, "velotrade_1", "placed", tkt="C")]
    _patch(monkeypatch, fills)
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    assert [t["id"] for t in o["open_trades"]] == [96]


def test_realized_window_population_and_ratios(monkeypatch):
    fills = [_fill(1, "velotrade_1", "closed", pnl=30.0, closed_days_ago=1),
             _fill(2, "tradeify_1", "closed", pnl=-10.0, closed_days_ago=2),
             _fill(3, "tradeify_1", "closed", pnl=None, closed_days_ago=2),
             _fill(4, "tradeify_1", "closed", pnl=500.0, closed_days_ago=20)]
    _patch(monkeypatch, fills)
    r = po.build_overview("7d", accounts=ACCTS, now=NOW)["realized"]
    assert (r["total_pnl"], r["closed_trades"], r["closed_priced"], r["closed_unpriced"]) == (20.0, 3, 2, 1)
    assert r["win_rate"] == 0.5 and r["profit_factor"] == 3.0
    assert po.build_overview("all", accounts=ACCTS, now=NOW)["realized"]["total_pnl"] == 520.0


def test_empty_window_is_null_not_zero(monkeypatch):
    _patch(monkeypatch, [])
    r = po.build_overview("7d", accounts=ACCTS, now=NOW)["realized"]
    assert r["total_pnl"] is None and r["win_rate"] is None and r["closed_trades"] == 0


def test_route_degrades(monkeypatch):
    from src.web.api.routers import prop as router
    monkeypatch.setattr(po, "build_overview", lambda w: (_ for _ in ()).throw(RuntimeError("x")))
    assert router.get_overview("7d")["present"] is False


def test_retired_account_excluded(monkeypatch):
    # breakout_1 is retired (operator 2026-10-09): its stale equity and its
    # never-closed historical fills must not appear in the live prop book.
    accts = dict(ACCTS, breakout_1={"account_class": "prop", "mode": "dry_run", "retired": True})
    EQ["breakout_1"] = (4698.0, "stale")
    try:
        _patch(monkeypatch, [_fill(1, "breakout_1", "open"), _fill(2, "velotrade_1", "open")])
        o = po.build_overview("7d", accounts=accts, now=NOW)
        assert [a["account_id"] for a in o["equity"]["accounts"]].count("breakout_1") == 0
        assert [t["account_id"] for t in o["open_trades"]] == ["velotrade_1"]
    finally:
        EQ.pop("breakout_1", None)


# ── UI-UPGRADE-1 item 3: unrealized P&L projected from the status snapshots ──

def _patch_ur(monkeypatch, fills, ur, fresh=None):
    fresh = fresh or {a: "ok" for a in ur}
    monkeypatch.setattr(pj, "latest_account_status",
                        lambda a: {"equity": 1000.0, "unrealized": ur.get(a),
                                   "reported_at": "2026-10-10T15:59:00+00:00"})
    monkeypatch.setattr(pr, "compute_rule_distance",
                        lambda a, s=None: {"status_freshness": fresh.get(a, "ok"),
                                           "status_age_hours": 0.1})
    monkeypatch.setattr(pj, "list_fills",
                        lambda account_id=None, limit=100: [f for f in fills if f["account_id"] == account_id])


def test_unrealized_sums_venue_numbers_and_flat_accounts(monkeypatch):
    monkeypatch.setattr(po, "_is_phone_account", lambda a: False)  # journal vouches for flat on VM executors
    fills = [_fill(95, "tradeify_1", "open", tkt="A")]
    _patch_ur(monkeypatch, fills, {"tradeify_1": -13.31, "velotrade_1": None, "breakout_2": None})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    states = {a["account_id"]: (a["unrealized"], a["unrealized_state"], a["unrealized_provenance"])
              for a in o["equity"]["accounts"]}
    assert states["tradeify_1"] == (-13.31, "venue_snapshot", "measured")
    assert states["velotrade_1"] == (0.0, "no_open_trades", "journal")
    assert o["unrealized_pnl"] == -13.31 and o["unrealized"]["accounts_unknown"] == 0
    t = o["open_trades"][0]
    assert (t["unrealized_pnl"], t["unrealized_provenance"]) == (-13.31, "measured")
    assert "_unrealized_raw" not in o["equity"]["accounts"][0]


def test_unrealized_total_is_null_when_any_account_unknown(monkeypatch):
    monkeypatch.setattr(po, "_is_phone_account", lambda a: False)
    fills = [_fill(1, "velotrade_1", "open", tkt="A")]
    _patch_ur(monkeypatch, fills, {"tradeify_1": 5.0, "velotrade_1": None, "breakout_2": None})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    vt = [a for a in o["equity"]["accounts"] if a["account_id"] == "velotrade_1"][0]
    assert (vt["unrealized"], vt["unrealized_state"]) == (None, "not_reported")
    assert o["unrealized_pnl"] is None and o["unrealized"]["accounts_unknown"] == 1
    assert o["open_trades"][0]["unrealized_pnl"] is None


def test_stale_snapshot_number_is_not_used(monkeypatch):
    _patch_ur(monkeypatch, [], {"tradeify_1": 50.0, "velotrade_1": 1.0, "breakout_2": 2.0},
              fresh={"tradeify_1": "stale"})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    t1 = [a for a in o["equity"]["accounts"] if a["account_id"] == "tradeify_1"][0]
    assert (t1["unrealized"], t1["unrealized_state"]) == (None, "stale")
    assert o["unrealized_pnl"] is None


def test_two_open_trades_do_not_split_the_account_number(monkeypatch):
    monkeypatch.setattr(po, "_is_phone_account", lambda a: False)
    fills = [_fill(1, "tradeify_1", "open", tkt="A"), _fill(2, "tradeify_1", "open", tkt="B")]
    _patch_ur(monkeypatch, fills, {"tradeify_1": 20.0, "velotrade_1": None, "breakout_2": None})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    assert o["unrealized_pnl"] == 20.0
    assert [t["unrealized_pnl"] for t in o["open_trades"]] == [None, None]


def test_phone_executed_account_with_no_venue_number_is_not_reported_never_zero(monkeypatch):
    """BREAKOUT-UNRECORDED: breakout_2 held two live positions the journal never saw, and the overview said
    0.0 'estimated'. A phone-executed account's journal cannot vouch for flat: null + not_reported."""
    monkeypatch.setattr(po, "_is_phone_account", lambda a: a == "breakout_2")
    _patch_ur(monkeypatch, [], {"tradeify_1": 5.0, "velotrade_1": None, "breakout_2": None})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    by = {a["account_id"]: a for a in o["equity"]["accounts"]}
    b2 = by["breakout_2"]
    assert (b2["unrealized"], b2["unrealized_state"], b2["unrealized_provenance"]) == (None, "not_reported", "unverified")
    assert by["velotrade_1"]["unrealized"] == 0.0 and by["velotrade_1"]["unrealized_provenance"] == "journal"
    assert o["unrealized_pnl"] is None and o["unrealized"]["accounts_unknown"] == 1
    assert "_phone_executed" not in b2


def test_phone_executed_account_with_a_venue_number_still_reports_it(monkeypatch):
    monkeypatch.setattr(po, "_is_phone_account", lambda a: a == "breakout_2")
    _patch_ur(monkeypatch, [], {"tradeify_1": 5.0, "velotrade_1": None, "breakout_2": 51.0})
    o = po.build_overview("7d", accounts=ACCTS, now=NOW)
    b2 = [a for a in o["equity"]["accounts"] if a["account_id"] == "breakout_2"][0]
    assert (b2["unrealized"], b2["unrealized_state"], b2["unrealized_provenance"]) == (51.0, "venue_snapshot", "measured")


def test_unreadable_platform_config_never_reads_as_flat(monkeypatch):
    import src.prop.phone_executor as pe
    monkeypatch.setattr(pe, "is_phone_account", lambda a: (_ for _ in ()).throw(OSError("no config")))
    assert po._is_phone_account("velotrade_1") is True
