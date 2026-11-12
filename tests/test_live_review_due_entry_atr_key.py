"""RM-AM-DUE-COULDNOTLOOK re-score (AM-TRADING, 2026-11-12 21:13Z): 3 non-youth could_not_look of 23 open.

(b)/(c) two ml_entry packages read "history starts N bars after entry and the package carries no entry ATR" while
their order_packages.meta carried `atr14` (read live: 1.1696 / 1.1554); only `atr` was read.
(a) e4_oi_shock_1h's stall read 'bars_held / peak_r unknown': peak_state is `unanchored` because the package meta
carries no entry_time (the strategy does not publish one), which is not youth and is now said so.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import UTC, datetime

from src.runtime import live_review_due as lrd

NOW = datetime(2026, 11, 12, 21, 0, tzinfo=UTC)
CFG = lrd.load_config()


def _db(tmp_path, meta):
    db = tmp_path / "j.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE venue_protection_snapshot (order_package_id TEXT, trade_id TEXT, account_id TEXT, "
              "read_state TEXT)")
    c.execute("CREATE TABLE trades (id INTEGER, status TEXT, notes TEXT)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, sl REAL, tp REAL, meta TEXT)")
    c.execute("INSERT INTO order_packages VALUES ('pkg-m', 79.0, 84.0, ?)", (json.dumps(meta),))
    c.commit()
    c.close()
    return str(db)


def test_entry_atr_is_read_from_atr14_when_atr_is_absent(tmp_path):
    out = lrd.read_venue_context(["pkg-m"], db_path=_db(tmp_path, {"atr14": 1.1696, "entry_time": "x"}))
    assert out["pkg-m"]["meta_atr"] == 1.1696 and out["pkg-m"]["meta_atr_key"] == "atr14"


def test_atr_wins_over_atr14_and_absent_is_none(tmp_path):
    out = lrd.read_venue_context(["pkg-m"], db_path=_db(tmp_path, {"atr": 2.0, "atr14": 1.0}))
    assert out["pkg-m"]["meta_atr"] == 2.0 and out["pkg-m"]["meta_atr_key"] == "atr"
    other = tmp_path / "b"
    other.mkdir()
    out = lrd.read_venue_context(["pkg-m"], db_path=_db(other, {"other": 1}))
    assert out["pkg-m"]["meta_atr"] is None and out["pkg-m"]["meta_atr_key"] is None


def test_vol_regime_label_names_the_meta_key():
    from datetime import timedelta
    tf = 3600
    hist = [{"bar_ts": (NOW - timedelta(seconds=tf * (2 - i))).isoformat(), "last_price": 1.0, "atr": 2.0}
            for i in range(3)]
    row = {"order_package_id": "pkg-m", "strategy": "ml_entry", "symbol": "XLE", "direction": "long",
           "bars_held": 10, "updated_at": NOW.isoformat(), "lifecycle": "open"}
    ctx = {"history": hist, "history_reason": None, "calendar": {"state": "read", "events": [], "classes": {}},
           "venue": {"state": "read", "snapshots": [], "meta_atr": 1.0, "meta_atr_key": "atr14"}}
    ev, cnl = lrd.market_events(row, ctx, CFG, NOW, tf)
    assert "vol_regime" not in {c["event"] for c in cnl}
    vr = [e for e in ev if e[0] == "vol_regime"]
    assert vr and "entry_atr_source=package_meta, meta.atr14: not path-measured" in vr[0][2]


def test_stall_names_the_unanchored_cause_and_it_is_not_youth():
    import re
    no_prior = {"fired": set(), "last": None, "peak": None, "mech": None}
    row = {"order_package_id": "pkg-e", "strategy": "e4_oi_shock_1h", "symbol": "SOLUSDT", "direction": "long",
           "bars_held": 0, "peak_r": None, "peak_state": "unanchored", "open_r": 0.57,
           "updated_at": NOW.isoformat(), "lifecycle": "open"}
    _, cnl, _ = lrd.prescreen(row, copy.deepcopy(no_prior), {"history": []}, CFG, NOW, 3600)
    reasons = [c["reason"] for c in cnl if c["event"] == "stall"]
    assert reasons == ["peak_r unanchored: package meta has no entry_time (the strategy does not publish it)"]
    youth = re.compile(r"^\d+ (closed history bar\(s\)|history bar\(s\) with a price); need \d+$"
                       r"|^peak_r thin_window: \d+ bar\(s\) since entry; need \d+$")
    assert not youth.match(reasons[0])   # a real input gap, never folded into youth
