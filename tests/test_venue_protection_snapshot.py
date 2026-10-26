"""LTR-MECHANICS-VENUE-SNAPSHOT — the venue half of the live review's mechanics check.

Pinned: the snapshot keeps the three read states distinct; the writer never
raises into the exit loop, is timed through ``tick_cost`` and makes no venue
call; the broker sweeps' coverage reads now expose target prices additively; and
``live_review_due`` fires mechanics ``venue_sl_diverges`` on a fixture of each of
the two paper mismatches that motivated the row (the ``alpaca_paper`` GLD wedge
and the ``ib_paper`` MGC bracket replaced by a second leg's). The tables are
created by the REAL ``Database`` DDL so a DDL/writer drift fails here.

FIXTURE PROVENANCE. GLD: journal sl 414.54 vs venue stop 416.09 (review row
LR-20261025T1616Z-pkg-6a8e3fb325464be3, ``comms/live_review`` rows branch).
MGC: package sl 4270.03 vs venue stop 4040.8 (PI-20261026-UNSVQMPZ-0001). The
ATRs below are ASSUMED fixture values (neither was recorded with the mismatch);
the asserts state the ATR bound each fixture holds for.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import live_review_due as lrd
from src.runtime import venue_protection_snapshot as vps
from src.units.db.database import Database

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
CFG = lrd.load_config()


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "journal.db")
    Database(path)  # the production DDL, including venue_protection_snapshot
    vps._last_prune.clear()
    return path


def _package(db, pkg, *, sl, tp, atr=None, strategy="x_1h", symbol="GLD",
             direction="long", account="alpaca_paper", trade_id=1):
    meta = json.dumps({"atr": atr}) if atr is not None else None
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO order_packages (order_package_id, strategy_name, symbol, "
                  "direction, entry, sl, tp, created_at, updated_at, status, meta) "
                  "VALUES (?,?,?,?,?,?,?,?,?,'open',?)",
                  (pkg, strategy, symbol, direction, 400.0, sl, tp, NOW.isoformat(),
                   NOW.isoformat(), meta))
        c.execute("INSERT INTO trades (id, timestamp, symbol, direction, entry_price, "
                  "position_size, account_id, status, order_package_id, strategy_name, "
                  "stop_loss, take_profit_1) VALUES (?,?,?,?,?,?,?,'open',?,?,?,?)",
                  (trade_id, NOW.isoformat(), symbol, direction, 400.0, 10.0, account,
                   pkg, strategy, sl, tp))


def _rows(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM venue_protection_snapshot")]


class _Row(dict):
    """sqlite3.Row-shaped: the sweeps index it by name."""


# ---------------------------------------------------------------- pure builder
def test_nearest_stop_is_chosen_against_the_package_level_not_the_first():
    r = vps.build_snapshot_row(order_package_id="p", account_id="a", ref_sl=100.0,
                               stop_prices=[90.0, 99.5, 120.0], target_prices=[130.0],
                               ref_tp=131.0, now=NOW)
    assert r["read_state"] == "measured" and r["venue_sl"] == 99.5
    assert r["venue_tp"] == 130.0 and r["n_stop_legs"] == 3 and r["n_target_legs"] == 1


def test_three_states_never_collapse():
    flat = vps.build_snapshot_row(order_package_id="p", account_id="a", stop_prices=[],
                                  position_size=0.0, now=NOW)
    nostop = vps.build_snapshot_row(order_package_id="p", account_id="a", stop_prices=[],
                                    target_prices=[5.0], position_size=3.0, now=NOW)
    cnl = vps.build_snapshot_row(order_package_id="p", account_id="a",
                                 unreadable="ib_coverage_unavailable", now=NOW)
    assert (flat["read_state"], flat["read_reason"]) == ("none_resting", "venue_flat")
    assert (nostop["read_state"], nostop["read_reason"]) == ("none_resting", "no_stop_leg")
    assert cnl["read_state"] == "could_not_look" and cnl["read_reason"] == "ib_coverage_unavailable"
    # NULL, never 0.0, when no price was read
    for r in (flat, nostop, cnl):
        assert r["venue_sl"] is None and r["venue_tp"] is None


def test_several_stops_and_no_reference_is_could_not_look_not_a_guess():
    r = vps.build_snapshot_row(order_package_id="p", account_id="a",
                               stop_prices=[90.0, 95.0], now=NOW)
    assert r["read_state"] == "could_not_look" and r["read_reason"] == "no_reference_level"
    one = vps.build_snapshot_row(order_package_id="p", account_id="a",
                                 stop_prices=[90.0], now=NOW)
    assert one["read_state"] == "measured" and one["venue_sl"] == 90.0


def test_unattributable_read_builds_no_row_and_garbage_prices_are_dropped():
    assert vps.build_snapshot_row(order_package_id=None, account_id="a") is None
    assert vps.build_snapshot_row(order_package_id="p", account_id="") is None
    r = vps.build_snapshot_row(order_package_id="p", account_id="a",
                               stop_prices=[0, -1, "x", None, float("nan"), 7.0],
                               ref_sl=7.0, now=NOW)
    assert r["venue_sl"] == 7.0 and r["n_stop_legs"] == 1


# ---------------------------------------------------------------- writer
def test_record_read_upserts_latest_wins_and_counts_reads(db):
    _package(db, "pkg-1", sl=414.54, tp=366.0)
    t0, t1 = NOW, NOW + timedelta(minutes=5)
    assert vps.record_read(account_id="alpaca_paper", trade_id=1, symbol="GLD",
                           direction="long", venue="alpaca", stop_prices=[416.09],
                           target_prices=[366.0], position_size=10, db_path=db, now=t0)
    assert vps.record_read(account_id="alpaca_paper", trade_id=1, venue="alpaca",
                           unreadable="alpaca_coverage_unavailable", db_path=db, now=t1)
    (row,) = _rows(db)
    assert row["order_package_id"] == "pkg-1" and row["reads"] == 2
    assert row["first_read_at"] == t0.isoformat() and row["read_at"] == t1.isoformat()
    # the latest read is the failed one: it must NOT keep reading as measured
    assert row["read_state"] == "could_not_look" and row["venue_sl"] is None
    assert row["ref_sl"] == 414.54


def test_one_package_on_two_accounts_keeps_two_rows(db):
    _package(db, "pkg-1", sl=100.0, tp=120.0, account="bybit_2", trade_id=1)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO trades (id, timestamp, symbol, direction, entry_price, "
                  "position_size, account_id, status, order_package_id) "
                  "VALUES (2,?,?,?,?,?,?,'open','pkg-1')",
                  (NOW.isoformat(), "GLD", "long", 400.0, 1.0, "bybit_portfolio"))
    for tid, acct, px in ((1, "bybit_2", 100.0), (2, "bybit_portfolio", 101.0)):
        vps.record_read(account_id=acct, trade_id=tid, stop_prices=[px], db_path=db, now=NOW)
    assert {(r["account_id"], r["venue_sl"]) for r in _rows(db)} == {
        ("bybit_2", 100.0), ("bybit_portfolio", 101.0)}


def test_trade_without_a_package_writes_nothing_and_does_not_raise(db):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO trades (id, timestamp, symbol, direction, entry_price, "
                  "position_size, account_id, status) VALUES (9,?,?,?,?,?,?,'open')",
                  (NOW.isoformat(), "GLD", "long", 1.0, 1.0, "alpaca_paper"))
    assert vps.record_read(account_id="alpaca_paper", trade_id=9, stop_prices=[1.0],
                           db_path=db) is False
    assert _rows(db) == []


def test_writer_never_raises_when_the_table_or_db_is_missing(tmp_path, caplog):
    bare = str(tmp_path / "bare.db")
    sqlite3.connect(bare).close()
    assert vps.record_read(account_id="a", trade_id=1, stop_prices=[1.0], db_path=bare) is False
    assert vps.record_read(account_id="a", trade_id=1, db_path=str(tmp_path / "no" / "x.db")) is False


def test_writer_is_timed_through_tick_cost_and_places_no_order(db, monkeypatch):
    from src.runtime import tick_cost
    seen = []
    real = tick_cost.hook

    def spy(name):
        seen.append(name)
        return real(name)

    monkeypatch.setattr(tick_cost, "hook", spy)
    _package(db, "pkg-1", sl=1.0, tp=2.0)
    vps.record_read(account_id="a", trade_id=1, stop_prices=[1.0], db_path=db, now=NOW)
    assert vps.HOOK_NAME in seen
    # no venue client, executor or order module is imported by the snapshot
    imports = [ln for ln in open(vps.__file__).read().splitlines()
               if ln.strip().startswith(("import ", "from "))]
    for banned in ("ib_insync", "pybit", "ccxt", "alpaca_client", "executor",
                   "order_monitor", "risk", "coordinator"):
        assert not [ln for ln in imports if banned in ln], (banned, imports)


def test_prune_drops_rows_past_retention(db):
    _package(db, "pkg-1", sl=1.0, tp=2.0)
    import time
    old = NOW - timedelta(days=vps.RETENTION_DAYS + 1)
    vps._last_prune[db] = time.monotonic()  # hold off the write path's own hourly prune
    vps.record_read(account_id="a", trade_id=1, stop_prices=[1.0], db_path=db, now=old)
    assert len(_rows(db)) == 1
    with sqlite3.connect(db) as c:
        assert vps.prune(c, now=NOW - timedelta(days=2)) == 0  # inside retention: kept
        assert vps.prune(c, now=NOW) == 1
    assert _rows(db) == []


def test_read_snapshots_distinguishes_absent_table_from_empty(tmp_path, db):
    bare = str(tmp_path / "bare.db")
    sqlite3.connect(bare).close()
    absent = vps.read_snapshots(bare)
    assert absent["present"] is False and absent["count"] == 0
    empty = vps.read_snapshots(db)
    assert empty["present"] is True and empty["count"] == 0


# ---------------------------------------------------------------- sweep wiring
def test_snapshot_hook_in_order_monitor_stores_and_never_raises(db, monkeypatch):
    from src.runtime import order_monitor as om
    monkeypatch.setenv("TRADE_JOURNAL_DB", db)
    monkeypatch.setattr("src.utils.paths.trade_journal_db_path", lambda: db)
    _package(db, "pkg-1", sl=100.0, tp=90.0, direction="short", symbol="MGC",
             account="ib_paper")
    row = _Row(id=1, symbol="MGC", direction="short")
    om._snapshot_venue_read(row, "ib_paper", "ib", cov={
        "size": 3.0, "stop_prices": [101.0], "target_prices": [89.0]})
    (r,) = _rows(db)
    assert (r["venue"], r["read_state"], r["venue_sl"], r["venue_tp"]) == ("ib", "measured", 101.0, 89.0)
    om._snapshot_venue_read(row, "ib_paper", "ib", unreadable="ib_coverage_unavailable")
    assert _rows(db)[0]["read_state"] == "could_not_look"
    om._snapshot_venue_read(None, "ib_paper", "ib")  # a bad row must not raise


def test_bybit_protection_exposes_target_prices_additively():
    from src.runtime import order_monitor as om

    class C:
        def get_positions(self, category=None, symbol=None):
            return {"retCode": 0, "result": {"list": [
                {"symbol": "ETHUSDT", "positionIdx": 0, "side": "Buy", "size": "2",
                 "stopLoss": "", "takeProfit": "", "tpSlMode": "Partial"}]}}

        def get_open_orders(self, category=None, symbol=None, orderFilter=None):
            return {"retCode": 0, "result": {"list": [
                {"stopOrderType": "PartialStopLoss", "qty": "2", "triggerPrice": "3000"},
                {"stopOrderType": "PartialTakeProfit", "qty": "2", "triggerPrice": "3600"}]}}

    st = om._bybit_position_protection(C(), "linear", "ETHUSDT")
    assert st["stop_prices"] == [3000.0] and st["target_prices"] == [3600.0]
    assert st["covered_qty"] == 2.0 and st["protective_leg_count"] == 2  # unchanged

    class Full(C):
        def get_positions(self, category=None, symbol=None):
            return {"retCode": 0, "result": {"list": [
                {"symbol": "ETHUSDT", "positionIdx": 0, "side": "Buy", "size": "2",
                 "stopLoss": "2900", "takeProfit": "3700"}]}}

    st = om._bybit_position_protection(Full(), "linear", "ETHUSDT")
    assert st["stop_prices"] == [2900.0] and st["target_prices"] == [3700.0]
    nt = om._bybit_position_protection(
        type("N", (Full,), {"get_positions": lambda s, **k: {"retCode": 0, "result": {"list": [
            {"symbol": "ETHUSDT", "positionIdx": 0, "side": "Buy", "size": "2",
             "stopLoss": "2900", "takeProfit": ""}]}}})(), "linear", "ETHUSDT")
    assert nt["target_prices"] == []  # none resting is [], never [0.0]


def test_alpaca_protection_coverage_exposes_leg_prices_additively():
    from src.units.accounts.alpaca_client import AlpacaClient
    c = AlpacaClient.__new__(AlpacaClient)
    legs = [{"type": "stop", "side": "sell", "qty": "10", "stop_price": "416.09"},
            {"type": "limit", "side": "sell", "qty": "10", "limit_price": "366.0"},
            {"type": "trailing_stop", "side": "sell", "qty": "10"}]  # no absolute price yet
    c._open_orders_for_symbol = lambda sym, **k: legs
    cov = c.protection_coverage("GLD", position={"qty": "10", "side": "long"})
    assert cov["stop_prices"] == [416.09] and cov["target_prices"] == [366.0]
    assert cov["stop_qty"] == 20.0 and cov["target_qty"] == 10.0  # quantity grading unchanged


# ---------------------------------------------------------------- due computation
def _venue(snaps, pkg_sl, atr=None, meta_atr=None):
    return {"venue": {"state": "read", "snapshots": snaps, "pkg_sl": pkg_sl, "pkg_tp": None,
                      "meta_atr": meta_atr},
            "history": ([{"bar_ts": NOW.isoformat(), "atr": atr, "last_price": 1.0}]
                        if atr is not None else [])}


def _snap(acct, state="measured", venue_sl=None, ref_sl=None, reason=None, age_min=1):
    return {"account_id": acct, "read_state": state, "venue_sl": venue_sl, "ref_sl": ref_sl,
            "read_reason": reason, "read_at": (NOW - timedelta(minutes=age_min)).isoformat()}


def _ve(ctx):
    return lrd.venue_events({}, ctx, CFG, NOW)


def test_tolerance_is_registered_in_config_before_use():
    mc = CFG["events"]["mechanics"]
    assert mc["venue_sl_tolerance_atr"] == 0.25 and mc["venue_snapshot_max_age_minutes"] == 60
    assert "mechanics_venue_tp" in CFG["not_evaluated"] and "mechanics_venue" not in CFG["not_evaluated"]


def test_FIXTURE_alpaca_gld_wedge_fires():
    # journal sl 414.54, venue OCO stop 416.09 (gap 1.55). Holds for any assumed ATR < 6.2.
    ev, cnl = _ve(_venue([_snap("alpaca_paper", venue_sl=416.09, ref_sl=414.54)], 414.54, atr=2.0))
    assert [e[:2] for e in ev] == [("mechanics", "venue_sl_diverges")] and not cnl
    assert "alpaca_paper venue stop 416.09 vs package sl 414.54" in ev[0][2]
    assert "position_path_history" in ev[0][2]  # says where the ATR came from


def test_FIXTURE_ib_mgc_bracket_replaced_by_a_second_legs_fires():
    # pullback pkg sl 4270.03; the venue shows ict_scalp_mgc_15m's stop 4040.8 (gap 229.2).
    ev, cnl = _ve(_venue([_snap("ib_paper", venue_sl=4040.8, ref_sl=4270.03)], 4270.03,
                         meta_atr=60.0))
    assert [e[:2] for e in ev] == [("mechanics", "venue_sl_diverges")] and not cnl
    assert "package_entry_atr" in ev[0][2]


def test_matching_venue_stop_does_not_fire_including_tick_rounding():
    # the recorded IB match: package 4270.0286 vs venue 4270.0 (0.0286 << 0.25 x ATR)
    ev, cnl = _ve(_venue([_snap("ib_paper", venue_sl=4270.0, ref_sl=4270.0286)], 4270.0286, atr=60.0))
    assert ev == [] and cnl == []


def test_tolerance_boundary():
    inside, _ = _ve(_venue([_snap("a", venue_sl=100.5, ref_sl=100.0)], 100.0, atr=2.0))   # gap 0.5 == 0.25*2
    outside, _ = _ve(_venue([_snap("a", venue_sl=100.51, ref_sl=100.0)], 100.0, atr=2.0))
    assert inside == [] and len(outside) == 1


def test_could_not_look_is_listed_and_never_reads_as_no_divergence():
    ev, cnl = _ve(_venue([_snap("ib_paper", state="could_not_look",
                                reason="ib_coverage_unavailable")], 100.0, atr=2.0))
    assert ev == [] and cnl == [{"event": "mechanics",
                                 "reason": "venue_sl: ib_paper: ib_coverage_unavailable"}]
    # ... and one account measured-diverging still fires beside another that could not look
    ev, cnl = _ve(_venue([_snap("bybit_2", venue_sl=90.0, ref_sl=100.0),
                          _snap("bybit_portfolio", state="could_not_look", reason="x")], 100.0, atr=2.0))
    assert len(ev) == 1 and len(cnl) == 1


def test_none_resting_is_not_graded_and_not_reported_as_a_miss():
    ev, cnl = _ve(_venue([_snap("alpaca_paper", state="none_resting", reason="no_stop_leg")],
                         100.0, atr=2.0))
    assert ev == [] and cnl == []


def test_missing_inputs_are_could_not_look_with_a_reason():
    assert _ve({"venue": None})[1][0]["reason"] == "venue_sl: venue snapshot not read"
    assert "no venue snapshot row" in _ve(_venue([], 100.0, atr=2.0))[1][0]["reason"]
    assert "package sl unreadable" in _ve(_venue([_snap("a", venue_sl=1.0)], None, atr=2.0))[1][0]["reason"]
    assert "no ATR" in _ve(_venue([_snap("a", venue_sl=1.0, ref_sl=100.0)], 100.0))[1][0]["reason"]
    assert _ve({"venue": {"state": "could_not_look", "reason": "venue_snapshot_table_absent"}})[1][0][
        "reason"] == "venue_sl: venue_snapshot_table_absent"
    assert _ve(None)[1][0]["reason"] == "venue_sl: venue snapshot not read"


def test_stale_snapshot_and_package_moved_since_read_are_could_not_look():
    ev, cnl = _ve(_venue([_snap("a", venue_sl=50.0, ref_sl=100.0, age_min=61)], 100.0, atr=2.0))
    assert ev == [] and "older than 60 min" in cnl[0]["reason"]
    # the trail moved the package sl after the read: the pair is not comparable
    ev, cnl = _ve(_venue([_snap("a", venue_sl=100.0, ref_sl=100.0)], 108.0, atr=2.0))
    assert ev == [] and "moved since the venue read" in cnl[0]["reason"]


def test_path_history_atr_outranks_entry_atr():
    ctx = _venue([_snap("a", venue_sl=101.0, ref_sl=100.0)], 100.0, atr=10.0, meta_atr=1.0)
    ev, _ = _ve(ctx)
    assert ev == []  # tol 2.5 from the path-history ATR 10, gap 1.0


def test_unregistered_tolerance_evaluates_nothing():
    cfg = {"events": {"mechanics": {"journal_trade_absent": True}}}
    assert lrd.venue_events({}, {"venue": None}, cfg, NOW) == ([], [])


# ---------------------------------------------------------------- end to end
def test_due_payload_fires_for_both_fixtures_and_counts_states(db, tmp_path):
    _package(db, "pkg-gld", sl=414.54, tp=366.0, atr=2.0, strategy="gld_pullback_1h",
             symbol="GLD", account="alpaca_paper", trade_id=1)
    _package(db, "pkg-mgc", sl=4270.03, tp=3766.99, atr=60.0, strategy="mgc_pullback_1d",
             symbol="MGC", direction="short", account="ib_paper", trade_id=2)
    _package(db, "pkg-ok", sl=89.19, tp=78.25, atr=2.0, strategy="x_pullback_1h",
             symbol="AMD", account="alpaca_paper", trade_id=3)
    _package(db, "pkg-blind", sl=10.0, tp=20.0, atr=1.0, strategy="y_pullback_1h",
             symbol="XRPUSDT", account="bybit_2", trade_id=4)  # a daily-floor account: due, so its misses show
    for tid, acct, px in ((1, "alpaca_paper", 416.09), (2, "ib_paper", 4040.8), (3, "alpaca_paper", 89.19)):
        vps.record_read(account_id=acct, trade_id=tid, stop_prices=[px], db_path=db,
                        now=NOW - timedelta(minutes=2))
    vps.record_read(account_id="bybit_2", trade_id=4, unreadable="bybit_read_refused:read_error",
                    db_path=db, now=NOW - timedelta(minutes=2))
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW)
    assert out["read_state"] == "looked" and out["open_count"] == 4
    due = {d["order_package_id"]: d for d in out["due"]}
    fired = {p for p, d in due.items()
             if ("mechanics", "venue_sl_diverges") in {(e["event"], e["level"]) for e in d["events"]}}
    assert fired == {"pkg-gld", "pkg-mgc"}
    assert "pkg-ok" not in fired
    # the blind package is NOT silently "fine": it reads could_not_look with the reason
    blind = [d for d in out["due"] if d["order_package_id"] == "pkg-blind"]
    cnl = [x["reason"] for d in blind for x in d["events_could_not_look"]]
    assert any("bybit_read_refused:read_error" in r for r in cnl)
    assert out["venue_snapshot"]["rows"] == 4 and out["venue_snapshot"]["measured"] == 3
    assert out["venue_snapshot"]["could_not_look"] == 1 and out["venue_snapshot"]["packages_without_row"] == 0


def test_fired_once_per_package_is_deduped_by_review_log(db, tmp_path):
    _package(db, "pkg-gld", sl=414.54, tp=366.0, atr=2.0, strategy="gld_pullback_1h")
    vps.record_read(account_id="alpaca_paper", trade_id=1, stop_prices=[416.09], db_path=db,
                    now=NOW - timedelta(minutes=2))
    rv = tmp_path / "r.jsonl"
    rv.write_text(json.dumps({"order_package_id": "pkg-gld", "reviewed_at": NOW.isoformat(),
                              "trigger": {"event": "mechanics", "level": "venue_sl_diverges"}}) + "\n")
    out = lrd.live_review_due(db_path=db, reviews_path=str(rv), now=NOW)
    assert not [d for d in out["due"] if d["order_package_id"] == "pkg-gld"
                and any(e["event"] == "mechanics" for e in d["events"])]


def test_absent_snapshot_table_is_could_not_look_not_an_empty_set(tmp_path):
    path = str(tmp_path / "old.db")
    Database(path)
    with sqlite3.connect(path) as c:
        c.execute("DROP TABLE venue_protection_snapshot")
    ctx = lrd.read_venue_context(["pkg-1"], path)
    assert ctx["pkg-1"] == {"state": "could_not_look", "reason": "venue_snapshot_table_absent"}
