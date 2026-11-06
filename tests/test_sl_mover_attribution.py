"""LTR-MECH-PROP-MIRROR-BRACKET: every package SL move names its mover; the venue-divergence
detector does not grade a venue read taken inside the settle window after the package stop moved."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.runtime import live_review_due as lrd
from src.runtime import sl_mover

NOW = datetime(2026, 11, 6, 8, 5, tzinfo=timezone.utc)
MOVED = datetime(2026, 11, 6, 8, 1, 45, tzinfo=timezone.utc)
CFG = {"events": {"mechanics": {"venue_sl_tolerance_atr": 0.25, "venue_sl_settle_seconds": 150}}}


def test_structure_verdict_is_named():
    v = {"sl": 0.18664643, "structure_move": {"reason": "swing_ratchet", "level_type": "swing_high",
                                              "level_price": 0.1858}}
    m = sl_mover.mover_from_verdict(v, "ml_entry_v2")
    assert m == {"source": "structure_exit", "detail": "swing_ratchet:swing_high:0.1858"}


def test_plain_trail_verdict_names_strategy():
    assert sl_mover.mover_from_verdict({"sl": 1.0}, "trend_donchian_eth")["detail"] == "trend_donchian_eth"
    assert sl_mover.mover_from_verdict(None)["source"] == "strategy_monitor"


def test_stamp_merges_meta_and_caps_history():
    meta = json.dumps({"atr": 0.003})
    for i in range(30):
        meta = sl_mover.stamp_sl_move(meta, i, i + 1, "structure_exit", "x", now=MOVED)
    assert meta["atr"] == 0.003 and len(meta["sl_moves"]) == sl_mover.MAX_SL_MOVES
    assert meta["last_sl_move"]["to"] == 30
    assert sl_mover.last_sl_move_ts(meta) == MOVED
    assert sl_mover.last_sl_move_ts(None) is None and sl_mover.last_sl_move_ts("{bad") is None


def _ctx(read_at, moved_at=MOVED, venue_sl=0.1875, ref_sl=0.186646):
    snap = {"account_id": "bybit_1", "read_state": "measured", "venue_sl": venue_sl, "ref_sl": ref_sl,
            "read_at": read_at.isoformat(), "trade_id": "6937", "trade_status": "open"}
    return {"venue": {"state": "read", "pkg_sl": 0.186646, "meta_atr": 0.003, "snapshots": [snap],
                      "pkg_sl_changed_at": moved_at}}


def test_stale_read_right_after_a_package_move_is_not_a_divergence():
    # the 2026-11-06 ADA case: read 20 s after the move still showed the old stop 0.1875
    ev, cnl = lrd.venue_events({"direction": "short"}, _ctx(MOVED + timedelta(seconds=20)), CFG, NOW)
    assert ev == []
    assert any("waiting for a later read" in c["reason"] for c in cnl)


def test_read_after_the_settle_window_is_graded():
    ev, _ = lrd.venue_events({"direction": "short"}, _ctx(MOVED + timedelta(seconds=151)), CFG, NOW)
    assert ev and ev[0][1] == "venue_sl_diverges"   # a real, persistent divergence still wakes


def test_settled_matching_read_is_clean():
    ev, cnl = lrd.venue_events({"direction": "short"},
                               _ctx(MOVED + timedelta(seconds=200), venue_sl=0.1866), CFG, NOW)
    assert ev == [] and cnl == []


def test_unregistered_settle_keeps_old_behaviour():
    cfg = {"events": {"mechanics": {"venue_sl_tolerance_atr": 0.25}}}
    ev, _ = lrd.venue_events({"direction": "short"}, _ctx(MOVED + timedelta(seconds=20)), cfg, NOW)
    assert ev and ev[0][1] == "venue_sl_diverges"


def test_read_venue_context_carries_the_stamped_move_time(tmp_path):
    db = tmp_path / "j.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE venue_protection_snapshot (order_package_id TEXT, account_id TEXT, trade_id TEXT)")
    c.execute("CREATE TABLE trades (id INTEGER, status TEXT, notes TEXT)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, sl REAL, tp REAL, meta TEXT)")
    meta = sl_mover.stamp_sl_move({"atr": 0.003}, 0.18747, 0.186646, "structure_exit", "swing_ratchet", now=MOVED)
    c.execute("INSERT INTO order_packages VALUES ('p1', 0.186646, 0.167, ?)",
              (json.dumps(meta),))
    c.execute("INSERT INTO order_packages VALUES ('p2', 1.0, 2.0, NULL)")
    c.commit(); c.close()
    out = lrd.read_venue_context(["p1", "p2"], db_path=str(db))
    assert out["p1"]["pkg_sl_changed_at"] == MOVED
    assert out["p2"]["pkg_sl_changed_at"] is None            # no record: no settle window, never updated_at


def test_order_monitor_modify_stamps_the_mover_on_the_package_write(monkeypatch):
    """The 2026-11-06 ADA/SOL shape: a structure_exit swing_ratchet verdict. The package row's meta must name it."""
    from unittest.mock import MagicMock

    from src.runtime import order_monitor as om
    monkeypatch.setattr(om, "_send_modify_to_exchange", lambda leg, **kw: {"ok": True, "exchange_response": {}})
    monkeypatch.setattr(om, "_package_open_legs", lambda db, pkg: ([{"id": 6937, "account_id": "bybit_1",
                        "symbol": "ADAUSDT", "direction": "short", "stop_loss": 0.18747143}], "resolved"))
    db = MagicMock()
    pkg = {"order_package_id": "pkg-78342b614f6040f6", "strategy_name": "ml_entry_v2", "symbol": "ADAUSDT",
           "sl": 0.18747143, "tp": 0.16715714, "meta": json.dumps({"atr": 0.003})}
    verdict = {"sl": 0.18664643, "structure_move": {"reason": "swing_ratchet", "level_type": "swing_high",
                                                    "level_price": 0.1858}}
    summary = om._StrategyTickSummary()
    om._apply_update(db, pkg, verdict, summary)
    (pid, written), _ = db.update_order_package.call_args
    assert pid == "pkg-78342b614f6040f6" and written["sl"] == 0.18664643
    last = written["meta"]["last_sl_move"]
    assert (last["source"], last["from"], last["to"]) == ("structure_exit", 0.18747143, 0.18664643)
    assert written["meta"]["atr"] == 0.003   # existing meta preserved
