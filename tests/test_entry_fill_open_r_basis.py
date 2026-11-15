"""Row ENTRY-FILL-OPEN-R-BASIS (manager decision 2026-11-15 04:18Z): once ENTRY-FILL-WRITEBACK has written the FILL
into trades.entry_price, telemetry measures open R from the fill, with 1R = |fill - initial SL|.

Measured case: trade 7260 (bybit_2 ADAUSDT long, pkg-eb9ee0d2). Plan entry 0.1506, risk 0.007929 (initial SL
0.142671), fill 0.1501. The r-block read openR -0.0631 on the plan while the broker showed uPnL +0.07.

Pins:
  1. fill_basis re-bases entry and risk on the fill and copies; the caller's open_pkg / meta are never mutated;
  2. only a trade whose notes carry a FILL entry_price_source re-bases (plan / pending / missing keep the plan);
  3. record_position_telemetry writes the fill-based open_r and leaves the stop / target it was handed untouched;
  4. an unreadable journal keeps today's plan basis and never raises;
  5. a fill at or beyond the initial stop never produces a non-positive risk.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from src.runtime import position_telemetry as pt

PLAN_ENTRY, RISK, FILL = 0.1506, 0.0079285714, 0.1501
INITIAL_SL = PLAN_ENTRY - RISK                     # 0.1426714...
TP = 0.16249285714285716


def _pkg(**over):
    p = {"order_package_id": "pkg-eb9ee0d2ec7e49cb", "symbol": "ADAUSDT", "entry": PLAN_ENTRY, "tp": TP,
         "account_id": "bybit_2", "strategy_name": "ml_entry", "linked_trade_id": 7260}
    p.update(over)
    return p


def _meta(**over):
    m = {"risk_per_unit": RISK, "entry_time": "2026-11-15 04:04:00"}
    m.update(over)
    return m


def _window(px=0.1503):
    return pd.DataFrame({"high": [0.1508, px], "low": [0.1499, px], "close": [0.1504, px]})


@pytest.fixture(autouse=True)
def _clear_cache():
    pt._FILL_CACHE.clear()
    pt._PLAN_SEEN.clear()
    yield
    pt._FILL_CACHE.clear()
    pt._PLAN_SEEN.clear()


def _db(tmp_path, notes, entry=FILL, tid=7260):
    path = str(tmp_path / "j.db")
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, entry_price REAL, notes TEXT)")
        c.execute("INSERT INTO trades VALUES (?,?,?,?)", (tid, "bybit_2", entry, json.dumps(notes)))
        c.execute(f"""CREATE TABLE {pt.TABLE} (
            order_package_id TEXT PRIMARY KEY, trade_id TEXT, strategy TEXT,
            symbol TEXT, account_id TEXT, direction TEXT, entry REAL,
            risk_per_unit REAL, last_price REAL, open_r REAL, peak_r REAL,
            peak_state TEXT, giveback_r REAL, bars_held INTEGER,
            bars_since_peak INTEGER, cap_r REAL, pct_of_cap REAL,
            r_to_stop REAL, r_to_target REAL, rr_from_here REAL,
            peak_provenance TEXT, levers TEXT, updated_at TEXT)""")
    return path


def test_fill_basis_rebases_entry_and_risk_and_never_mutates_the_caller():
    pkg, meta = _pkg(), _meta()
    pkg2, meta2 = pt.fill_basis(pkg, meta, "long", FILL)
    assert pkg2["entry"] == FILL and abs(meta2["risk_per_unit"] - (FILL - INITIAL_SL)) < 1e-12
    assert pkg["entry"] == PLAN_ENTRY and meta["risk_per_unit"] == RISK      # caller's objects untouched
    assert pkg2 is not pkg and meta2 is not meta
    # short: initial SL = plan + risk; a better (higher) short fill widens 1R
    s2, m2 = pt.fill_basis(_pkg(entry=100.0), _meta(risk_per_unit=2.0), "short", 100.5)
    assert s2["entry"] == 100.5 and m2["risk_per_unit"] == pytest.approx(1.5)


def test_no_fill_or_a_fill_past_the_stop_keeps_the_plan_objects():
    pkg, meta = _pkg(), _meta()
    assert pt.fill_basis(pkg, meta, "long", None) == (pkg, meta)
    assert pt.fill_basis(pkg, meta, "long", INITIAL_SL - 0.001) == (pkg, meta)   # risk would be <= 0
    assert pt.fill_basis(pkg, _meta(risk_per_unit=None), "long", FILL)[0] is pkg


def test_record_writes_fill_based_open_r_and_leaves_stop_target_alone(tmp_path):
    db = _db(tmp_path, {"entry_price_source": "bybit_order_history", "package_entry": PLAN_ENTRY})
    pkg, meta = _pkg(), _meta()
    rec = pt.record_position_telemetry(open_pkg=pkg, meta=meta, window=_window(), direction="long",
                                       current_price=0.1503, stop=INITIAL_SL, target=TP, db_path=db)
    fill_risk = FILL - INITIAL_SL
    assert rec["entry"] == pytest.approx(FILL) and rec["risk_per_unit"] == pytest.approx(fill_risk, rel=1e-6)
    assert rec["open_r"] == pytest.approx((0.1503 - FILL) / fill_risk, abs=1e-3)     # about +0.027R, not -0.04R
    assert rec["open_r"] > 0
    assert rec["r_to_stop"] == pytest.approx((0.1503 - INITIAL_SL) / fill_risk, abs=1e-3)
    assert pkg["entry"] == PLAN_ENTRY and meta["risk_per_unit"] == RISK                # the exit loop's inputs
    with sqlite3.connect(db) as c:
        got = c.execute(f"SELECT entry, open_r FROM {pt.TABLE}").fetchone()
    assert got[0] == pytest.approx(FILL) and got[1] > 0


@pytest.mark.parametrize("notes", [
    {"entry_price_source": "plan", "entry_price_source_reason": "fill_pending_writeback"},
    {"entry_price_source": "plan", "entry_price_source_reason": "no_venue_fill_read"},
    {},                                                                   # a pre-stamp row: no backfill
])
def test_a_plan_or_unstamped_row_keeps_the_plan_basis(tmp_path, notes):
    db = _db(tmp_path, notes, entry=PLAN_ENTRY)
    rec = pt.record_position_telemetry(open_pkg=_pkg(), meta=_meta(), window=_window(), direction="long",
                                       current_price=0.1503, stop=INITIAL_SL, target=TP, db_path=db)
    assert rec["entry"] == pytest.approx(PLAN_ENTRY) and rec["risk_per_unit"] == pytest.approx(RISK)
    assert rec["open_r"] == pytest.approx((0.1503 - PLAN_ENTRY) / RISK, abs=1e-3)


def test_a_pending_row_rebases_once_the_writeback_lands(tmp_path, monkeypatch):
    db = _db(tmp_path, {"entry_price_source": "plan", "entry_price_source_reason": "fill_pending_writeback"},
             entry=PLAN_ENTRY)
    assert pt._linked_fill(7260, db) is None
    with sqlite3.connect(db) as c:
        c.execute("UPDATE trades SET entry_price = ?, notes = ? WHERE id = 7260",
                  (FILL, json.dumps({"entry_price_source": "bybit_order_history", "package_entry": PLAN_ENTRY})))
    monkeypatch.setattr(pt, "_PLAN_RECHECK_S", 0.0)                     # past the recheck window
    assert pt._linked_fill(7260, db) == pytest.approx(FILL)


def test_unreadable_journal_or_no_linked_trade_keeps_the_plan_and_never_raises(tmp_path):
    missing = str(tmp_path / "nope.db")
    assert pt._linked_fill(7260, missing) is None
    assert pt._linked_fill(None, missing) is None
    rec = pt.build_record(open_pkg=_pkg(linked_trade_id=None), meta=_meta(), window=_window(), direction="long",
                          current_price=0.1503)
    assert rec["entry"] == pytest.approx(PLAN_ENTRY)


def test_upsert_moves_entry_and_risk_to_the_fill_on_a_row_opened_on_the_plan(tmp_path):
    """TELEMETRY-UPSERT-ENTRY-RISK-COLUMNS: a row first written on the plan basis (before #26203) must not keep the
    plan entry/risk beside a fill-based open_r once the fill is known; a later record without them never wipes them."""
    db = _db(tmp_path, {"entry_price_source": "plan", "entry_price_source_reason": "fill_pending_writeback"},
             entry=PLAN_ENTRY)
    pt.record_position_telemetry(open_pkg=_pkg(), meta=_meta(), window=_window(), direction="long",
                                 current_price=0.1503, db_path=db)
    with sqlite3.connect(db) as c:
        assert c.execute(f"SELECT entry FROM {pt.TABLE}").fetchone()[0] == pytest.approx(PLAN_ENTRY)
        c.execute("UPDATE trades SET entry_price = ?, notes = ? WHERE id = 7260",
                  (FILL, json.dumps({"entry_price_source": "bybit_order_history"})))
    pt._PLAN_SEEN.clear()
    pt.record_position_telemetry(open_pkg=_pkg(), meta=_meta(), window=_window(), direction="long",
                                 current_price=0.1503, db_path=db)
    with sqlite3.connect(db) as c:
        entry, risk, open_r = c.execute(f"SELECT entry, risk_per_unit, open_r FROM {pt.TABLE}").fetchone()
    assert entry == pytest.approx(FILL) and risk == pytest.approx(FILL - INITIAL_SL, rel=1e-6)
    assert open_r == pytest.approx((0.1503 - FILL) / (FILL - INITIAL_SL), abs=1e-3)
    rec = pt.build_record(open_pkg=_pkg(entry=None), meta=_meta(risk_per_unit=None), window=_window(),
                          direction="long", current_price=0.1503)
    pt.write_record(rec, db_path=db)
    with sqlite3.connect(db) as c:
        assert c.execute(f"SELECT entry, risk_per_unit FROM {pt.TABLE}").fetchone() == pytest.approx(
            (FILL, FILL - INITIAL_SL), rel=1e-6)
