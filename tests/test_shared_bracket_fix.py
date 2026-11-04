"""SHARED-BRACKET-FIX (2026-11-04, PI-20261104-MXMXDI3X-0001).

The question was "why does a second package on one (account, symbol) on bybit_1
REPLACE the first package's venue SL/TP". The venue's own order history refuted
it (``/api/diag/bybit_raw_order_history``, bybit_1, 2026-11-03 23:50Z..11-04
19:00Z): every BTCUSDT and XRPUSDT package carried its OWN qty-scoped Partial
SL + TP at its journal levels, and each bracket ended through its own order
(``Filled`` TP, sibling SL ``CancelByOCOSlCanceledByTpTriggered``). The
"one bracket for two packages" reads were taken minutes after a sibling's TP
had filled.

What WAS wrong is the close the journal wrote. bybit_1 XRPUSDT, two longs:

* e4_oi_shock_1h trade 6858, 25333 qty — own TP 6d5af566 filled 14:41:57Z;
* ict_scalp_xrp_15m trade 6860, 26292.9 qty — own TP 78e74e28 filled 26292.9
  @ 1.3177 at 14:48:08Z.

``netting_attribution_soak``: 14:46:57Z attributed 6858 (anchor 14:43:57Z, the
first observation of ITS divergence) — correct. 14:49:58Z attributed 6860
(venue flat) with the SAME anchor 14:43:57Z, because the divergence key was
never cleared after the 14:46:57Z write and no clean tick fell between. So 6860
was booked closed at 14:43:57Z — four minutes BEFORE its own fill — at the
14:43 candle 1.3067, labelled ``netting_attributed``. Every own-order-fill sweep
windows ``closed_at + 2 min``, so the 14:48:08Z fill sat outside all of them
and the real ``tp`` / 1.3177 was never recovered.

These tests reproduce that shape and pin the fix; the ETH control (two
packages, one closes, the other keeps its qty) must keep passing unchanged.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from src.runtime import fills_pnl
from src.runtime import order_monitor as om


# ----------------------------------------------------------------- fixtures
class _LiveDB:
    """The REAL journal schema, and update_trade that actually writes."""

    def __init__(self, path):
        self.path = str(path)
        from src.units.db.database import Database

        Database(self.path)

    def connect(self):
        return sqlite3.connect(self.path)

    def update_trade(self, tid, updates):
        cols = ", ".join(f"{k} = ?" for k in updates)
        c = sqlite3.connect(self.path)
        c.execute(f"UPDATE trades SET {cols} WHERE id = ?", (*updates.values(), tid))
        c.commit()
        c.close()

    def row(self, tid):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        r = dict(c.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone())
        c.close()
        return r


def _seed(db, *, tid, qty, sl_id, strategy, symbol="XRPUSDT", direction="long",
          created="2026-11-04T05:02:44+00:00", entry=1.27):
    c = sqlite3.connect(db.path)
    c.execute(
        "INSERT INTO trades (id,account_id,symbol,direction,position_size,"
        "entry_price,created_at,timestamp,setup_type,strategy_name,sl_order_id,"
        "status,is_backtest) VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',0)",
        (tid, "bybit_1", symbol, direction, qty, entry, created, created,
         "normal", strategy, sl_id),
    )
    c.commit()
    c.close()


_ACC = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear"}


def _venue(size, side, sl_leg_ids):
    return {"size": float(size), "side": side if size else "",
            "covered_qty": float(size), "source": "partial_sl_legs" if size else "flat",
            "sl_leg_ids": set(sl_leg_ids), "unknown_qty_sl_legs": 0,
            "position_idx": 0 if size else None}


class _Clock:
    """Drives the reconciler's monotonic and wall clocks tick by tick."""

    def __init__(self, monkeypatch):
        self.mono = 1000.0
        self.wall = _dt.datetime(2026, 11, 4, 14, 43, 57, tzinfo=_dt.timezone.utc)
        monkeypatch.setattr(om.time, "monotonic", lambda: self.mono)

        clock = self

        class _DT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.wall

        monkeypatch.setattr(om, "datetime", _DT)

    def tick(self, seconds):
        self.mono += seconds
        self.wall += _dt.timedelta(seconds=seconds)


def _arm(monkeypatch, venue_ref, anchors):
    om._NETTING_DIVERGENCE_SEEN.clear()
    monkeypatch.setenv("NETTING_ATTRIBUTION_MODE", "apply")
    monkeypatch.delenv("NETTING_ATTRIBUTION_ACCOUNTS", raising=False)
    monkeypatch.setenv("RECONCILER_CLOSE_CONFIRM_SECONDS", "60")
    monkeypatch.setattr("src.bot.data_loaders.list_accounts", lambda: [_ACC])
    monkeypatch.setattr("src.units.accounts.clients.bybit_client_for", lambda acc: object())
    monkeypatch.setattr(om, "_bybit_position_protection", lambda *a, **k: venue_ref[0])
    monkeypatch.setattr(om, "_netting_soak_row", lambda **kw: None)
    monkeypatch.setattr(om, "_cascade_close_linked_package", lambda *a, **k: None)
    monkeypatch.setattr(om, "is_active_close", lambda *a, **k: False)

    def _bar(sym, iso, budget=None):
        anchors.append(iso)
        # collapsed-state: anchored — a test fake of the anchor source; deferred / no_anchor are pinned in tests/test_netting_attribution.py
        return (1.3067 if iso.startswith("2026-11-04T14:43") else 1.3180, "anchored")

    monkeypatch.setattr("src.runtime.exit_anchor.bar_close_at", _bar)


# ------------------------------------------- 1. the XRP shape (trade 6860)
def test_second_sibling_close_gets_its_OWN_anchor_not_the_first_ones(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=6858, qty=25333.0, sl_id="sl-e4", strategy="e4_oi_shock_1h")
    _seed(db, tid=6860, qty=26292.9, sl_id="sl-scalp", strategy="ict_scalp_xrp_15m",
          created="2026-11-04T05:08:04+00:00")
    clock = _Clock(monkeypatch)
    anchors: list = []
    # e4's TP has filled: the venue holds only the scalp's 26292.9, its SL leg resting.
    venue = [_venue(26292.9, "long", {"sl-scalp"})]
    _arm(monkeypatch, venue, anchors)

    om._reconcile_netting_partial_closes(db)                # 14:43:57 first observation
    clock.tick(180)
    s = om._reconcile_netting_partial_closes(db)            # 14:46:57 confirmed
    assert s["closed"] == 1
    assert db.row(6858)["status"] == "closed"
    assert db.row(6858)["closed_at"].startswith("2026-11-04T14:43:57")
    assert db.row(6860)["status"] == "open"

    # 14:48:08 the scalp's own TP fills: the venue is flat.
    venue[0] = _venue(0.0, "", set())
    clock.tick(181)                                         # 14:49:58
    s = om._reconcile_netting_partial_closes(db)
    # BEFORE the fix this tick closed 6860 at once with the 14:43:57 anchor.
    assert db.row(6860)["status"] == "open", "a NEW divergence must get its own first observation"
    assert s["pending_confirm"] == 1
    clock.tick(180)                                         # 14:52:58
    om._reconcile_netting_partial_closes(db)
    r = db.row(6860)
    assert r["status"] == "closed"
    assert r["closed_at"].startswith("2026-11-04T14:49:58"), r["closed_at"]
    # the anchor now bounds the real fill (14:48:08) from ABOVE, so the
    # own-order-fill sweeps' closed_at + 2 min window contains it
    assert anchors[-1].startswith("2026-11-04T14:49:58")


def test_divergence_that_GROWS_inside_the_confirm_window_is_reanchored(tmp_path, monkeypatch):
    """Both siblings close before the first divergence confirms (the BTC 14:40Z shape,
    compressed): the second close must not inherit the first close's anchor."""
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=0.517, sl_id="sl-a", strategy="e4_oi_shock_1h", symbol="BTCUSDT")
    _seed(db, tid=2, qty=0.581, sl_id="sl-b", strategy="trend_donchian_1h", symbol="BTCUSDT",
          created="2026-11-04T11:02:33+00:00")
    clock = _Clock(monkeypatch)
    anchors: list = []
    venue = [_venue(0.581, "long", {"sl-b"})]
    _arm(monkeypatch, venue, anchors)

    om._reconcile_netting_partial_closes(db)                # first observation, excess 0.517
    venue[0] = _venue(0.0, "", set())                       # the second sibling closes too
    clock.tick(30)
    s = om._reconcile_netting_partial_closes(db)            # excess grew to 1.098
    assert s["reanchored"] == 1 and s["pending_confirm"] == 1
    clock.tick(61)
    om._reconcile_netting_partial_closes(db)
    assert {db.row(1)["status"], db.row(2)["status"]} == {"closed"}
    assert db.row(2)["closed_at"].startswith("2026-11-04T14:44:27"), db.row(2)["closed_at"]


def test_ETH_control_one_sibling_closes_the_other_keeps_its_qty(tmp_path, monkeypatch):
    """bybit_1 ETHUSDT (18:17Z read): 14.12 + 10.31 (+ 0.11) packages, each with its own
    qty-scoped bracket. When one closes, ONLY it is attributed; the other stays open at
    its own qty. (A 0.11 sibling alone is inside the 10% divergence tolerance.)"""
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=10, qty=14.12, sl_id="sl-prop", strategy="trend_donchian_eth_prop",
          symbol="ETHUSDT", entry=2400.0)
    _seed(db, tid=11, qty=10.31, sl_id="sl-small", strategy="eth_pullback_2h",
          symbol="ETHUSDT", created="2026-11-04T06:00:00+00:00", entry=2400.0)
    clock = _Clock(monkeypatch)
    venue = [_venue(14.12, "long", {"sl-prop"})]
    _arm(monkeypatch, venue, [])

    om._reconcile_netting_partial_closes(db)
    clock.tick(180)
    om._reconcile_netting_partial_closes(db)
    assert db.row(11)["status"] == "closed" and db.row(11)["exit_reason"] == "netting_attributed"
    assert db.row(10)["status"] == "open" and float(db.row(10)["position_size"]) == 14.12
    clock.tick(180)
    s = om._reconcile_netting_partial_closes(db)            # clean: nothing more to do
    assert s["divergent"] == 0 and db.row(10)["status"] == "open"


def test_growth_predicate():
    assert om._netting_divergence_grew(25333.0, 51625.9)
    assert not om._netting_divergence_grew(25333.0, 26292.9)  # within 10%: same divergence
    assert not om._netting_divergence_grew(None, 5.0)


# ------------------- 2. a row closed BEFORE its own fill still gets tp + price
def _journal_premature(tmp_path):
    """Trade 6860 as the journal holds it today: closed 14:43:57 netting_attributed
    at the 1.3067 candle, while its own TP filled at 14:48:08 (outside +2 min)."""
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, "
        "pnl_percent REAL, account_id TEXT, created_at TEXT, closed_at TEXT, "
        "notes TEXT, setup_type TEXT, exit_reason TEXT, status TEXT, "
        "is_backtest INTEGER, sl_order_id TEXT, tp_order_id TEXT)")
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    opened = now - _dt.timedelta(hours=10)
    closed = now - _dt.timedelta(hours=1)
    fill_t = closed + _dt.timedelta(seconds=251)
    notes = json.dumps({"netting_attribution_basis": "leg_gone",
                        "netting_anchor_basis": "divergence_first_observed",
                        "pnl_source": "local_compute",
                        "exit_price_source": "candle_at_close"})
    c.execute(
        "INSERT INTO trades VALUES (6860,'XRPUSDT','long',26292.9,1.2712,1.3067,"
        "933.39795,NULL,'bybit_1',?,?,?,'normal','netting_attributed','closed',0,"
        "'be1d721a','78e74e28')",
        (opened.isoformat(), closed.isoformat(), notes))
    c.commit()
    c.close()

    fpath = tmp_path / "f.db"
    f = sqlite3.connect(fpath)
    f.execute(
        "CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, "
        "symbol TEXT, side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, "
        "exec_time TEXT, order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    rows = [
        # the sibling e4's TP (25333) BEFORE the recorded close
        ("e1", "XRP/USDT:USDT", "sell", 1.3026, 25333.0,
         (closed - _dt.timedelta(seconds=120)).isoformat(), "6d5af566"),
        # 6860's OWN TP, 251 s AFTER the recorded close
        ("e2", "XRP/USDT:USDT", "sell", 1.3177, 26292.9, fill_t.isoformat(), "78e74e28"),
    ]
    for eid, sym, side, px, qty, t, oid in rows:
        f.execute("INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,0.5,'USDT',?,?,0,NULL,NULL)",
                  (eid, "bybit_1", sym, side, px, qty, t, oid))
    f.commit()
    f.close()
    return path, fpath, closed, fill_t


class _PathDB:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        return sqlite3.connect(self.path)


def _row(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id = 6860").fetchone())
    c.close()
    return r


def test_own_fill_after_a_premature_close_is_found(tmp_path):
    _, fpath, closed, fill_t = _journal_premature(tmp_path)
    ms = fills_pnl.own_order_last_fill_ms(
        account_id="bybit_1", symbol="XRPUSDT", direction="long",
        opened_at_ms=int((closed - _dt.timedelta(hours=9)).timestamp() * 1000),
        own_order_ids=("be1d721a", "78e74e28"),
        conn_factory=lambda: sqlite3.connect(fpath))
    assert ms == int(fill_t.timestamp() * 1000)
    assert fills_pnl.own_order_last_fill_ms(
        account_id="bybit_1", symbol="XRPUSDT", direction="long",
        opened_at_ms=0, own_order_ids=("nope",),
        conn_factory=lambda: sqlite3.connect(fpath)) is None


def test_premature_netting_close_is_repriced_relabelled_and_retimed(tmp_path):
    path, fpath, closed, fill_t = _journal_premature(tmp_path)
    db = _PathDB(path)

    def fac():
        return sqlite3.connect(fpath)

    up = om._sweep_upgrade_anchored_exit_to_fill(db, fills_conn_factory=fac)
    assert up["upgraded"] == 1, up
    r = _row(path)
    assert abs(r["exit_price"] - 1.3177) < 1e-9
    notes = json.loads(r["notes"])
    assert notes["exit_price_source"] == "exchange_fill"
    assert notes["closed_at_source"] == "own_bracket_fill"
    assert om._isoformat_to_ms(r["closed_at"]) == int(fill_t.timestamp() * 1000)

    lbl = om._sweep_exit_label_from_bracket_order(db, fills_conn_factory=fac)
    assert lbl["relabelled"] == 1, lbl
    r = _row(path)
    assert r["exit_reason"] == "tp"
    assert json.loads(r["notes"])["pre_label_exit_reason"] == "netting_attributed"


def test_label_sweep_alone_reaches_a_fill_past_the_two_minute_window(tmp_path):
    """Even with closed_at left at the premature time, the label comes from order identity."""
    path, fpath, _closed, _fill_t = _journal_premature(tmp_path)
    lbl = om._sweep_exit_label_from_bracket_order(
        _PathDB(path), fills_conn_factory=lambda: sqlite3.connect(fpath))
    assert lbl["relabelled"] == 1 and _row(path)["exit_reason"] == "tp"


def test_a_lagging_close_is_NOT_moved_forward(tmp_path):
    """The usual case (fill BEFORE the detection-time close) keeps its closed_at here."""
    path, fpath, closed, _ = _journal_premature(tmp_path)
    f = sqlite3.connect(fpath)
    f.execute("UPDATE exchange_fills SET exec_time = ? WHERE exec_id = 'e2'",
              ((closed - _dt.timedelta(seconds=30)).isoformat(),))
    f.commit()
    f.close()
    om._sweep_upgrade_anchored_exit_to_fill(_PathDB(path), fills_conn_factory=lambda: sqlite3.connect(fpath))
    r = _row(path)
    assert abs(r["exit_price"] - 1.3177) < 1e-9
    assert om._isoformat_to_ms(r["closed_at"]) == int(closed.timestamp() * 1000)
    assert "closed_at_source" not in json.loads(r["notes"])


# ---------- 3. SOLUSDT 19:04Z: a closed long graded against the live short's stop
# MEASURED (manager relay, row LR-20261104T1904Z-pkg-5414797739ba4589): bybit_1
# SOLUSDT long pkg-54147977 (trade 6889) closed at its stop 94.80 at 19:01:54Z;
# the hedge short (Sell 293, idx 2, trend_donchian_sol_4h) kept its Partial SL
# 99.49 / TP 87.02. `venue_sl_diverges` fired "venue stop 99.49 vs package sl 94.80".

class _SolClient:
    def get_positions(self, **kw):
        return {"result": {"list": [
            {"symbol": "SOLUSDT", "side": "", "size": "0", "positionIdx": 1, "stopLoss": ""},
            {"symbol": "SOLUSDT", "side": "Sell", "size": "293", "positionIdx": 2, "stopLoss": ""}]}}

    def get_open_orders(self, **kw):
        return {"result": {"list": [
            {"orderId": "s-sl", "side": "Buy", "stopOrderType": "PartialStopLoss",
             "qty": "293", "triggerPrice": "99.49", "positionIdx": 2},
            {"orderId": "s-tp", "side": "Buy", "stopOrderType": "PartialTakeProfit",
             "qty": "293", "triggerPrice": "87.02", "positionIdx": 2}]}}


def test_protection_read_splits_leg_prices_by_book():
    st = om._bybit_position_protection(_SolClient(), "linear", "SOLUSDT")
    assert st is not None and st["side"] == "short"
    assert st["prices_by_book"]["short"] == {"stop": [99.49], "target": [87.02]}
    assert st["prices_by_book"]["long"] == {"stop": [], "target": []}
    assert st["stop_prices"] == [99.49]  # the side-blind list is unchanged


def test_closed_long_is_not_snapshotted_with_the_shorts_stop():
    from src.runtime import venue_protection_snapshot as vps
    st = om._bybit_position_protection(_SolClient(), "linear", "SOLUSDT")
    cov = om._bybit_snapshot_cov(st, "long")
    row = vps.build_snapshot_row(
        order_package_id="pkg-5414797739ba4589", account_id="bybit_1", direction="long",
        stop_prices=cov["stop_prices"], target_prices=cov["target_prices"],
        position_size=cov["size"], ref_sl=94.80, ref_tp=101.23)
    assert row["read_state"] == "none_resting" and row["venue_sl"] is None
    # the short's own package still reads its own stop
    cov_s = om._bybit_snapshot_cov(st, "short")
    row_s = vps.build_snapshot_row(
        order_package_id="pkg-short", account_id="bybit_1", direction="short",
        stop_prices=cov_s["stop_prices"], position_size=cov_s["size"], ref_sl=99.49)
    assert row_s["read_state"] == "measured" and row_s["venue_sl"] == 99.49


def test_same_book_snapshot_keeps_only_that_books_legs():
    st = {"size": 128.8, "side": "long", "stop_prices": [94.8, 99.49],
          "target_prices": [87.02, 101.23],
          "prices_by_book": {"long": {"stop": [94.8], "target": [101.23]},
                             "short": {"stop": [99.49], "target": [87.02]}}}
    cov = om._bybit_snapshot_cov(st, "long")
    assert cov["stop_prices"] == [94.8] and cov["target_prices"] == [101.23]
    assert om._bybit_snapshot_cov(None, "long") is None
    full = {"size": 1.0, "side": "long", "stop_prices": [90.0], "target_prices": []}
    assert om._bybit_snapshot_cov(full, "long") is full  # no split: unchanged


def test_venue_sl_diverges_skips_a_snapshot_whose_trade_closed():
    from datetime import datetime, timezone
    from src.runtime import live_review_due as lrd
    now = datetime(2026, 11, 4, 19, 4, tzinfo=timezone.utc)
    snap = {"account_id": "bybit_1", "read_state": "measured", "venue_sl": 99.49,
            "ref_sl": 94.80, "read_at": "2026-11-04T19:00:30+00:00", "trade_id": "6889"}
    cfg = {"events": {"mechanics": {"venue_sl_tolerance_atr": 0.5}}}

    def ctx(status):
        return {"venue": {"state": "read", "pkg_sl": 94.80, "meta_atr": 1.0,
                          "snapshots": [dict(snap, trade_status=status)]}}
    ev, _ = lrd.venue_events({}, ctx("closed"), cfg, now)
    assert ev == []
    ev, _ = lrd.venue_events({}, ctx("open"), cfg, now)
    assert ev and ev[0][1] == "venue_sl_diverges"   # an OPEN trade is still graded
    ev, _ = lrd.venue_events({}, ctx(None), cfg, now)
    assert ev and ev[0][1] == "venue_sl_diverges"   # unknown status: graded as before


def test_read_venue_context_carries_each_snapshots_trade_status(tmp_path):
    from src.runtime import live_review_due as lrd
    from src.runtime import venue_protection_snapshot as vps
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=6889, qty=128.8, sl_id="l-sl", strategy="trend_donchian_sol",
          symbol="SOLUSDT", entry=97.0)
    c = sqlite3.connect(db.path)
    c.execute("UPDATE trades SET status='closed', order_package_id='pkg-5414797739ba4589' WHERE id=6889")
    cols = {r[1] for r in c.execute("PRAGMA table_info(order_packages)")}
    vals = {"order_package_id": "pkg-5414797739ba4589", "sl": "94.80", "tp": "101.23",
            "meta": "{}", "symbol": "SOLUSDT", "direction": "long", "status": "open",
            "strategy_name": "trend_donchian_sol", "created_at": "2026-11-04T10:00:00+00:00",
            "updated_at": "2026-11-04T19:01:54+00:00", "entry": "97.0"}
    vals = {k: v for k, v in vals.items() if k in cols}
    c.execute(f"INSERT INTO order_packages ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
              tuple(vals.values()))
    c.commit()
    c.close()
    assert vps.record_read(account_id="bybit_1", trade_id=6889, symbol="SOLUSDT", direction="long",
                           venue="bybit", stop_prices=[99.49], position_size=293.0, db_path=db.path)
    ctx = lrd.read_venue_context(["pkg-5414797739ba4589"], db_path=db.path)
    sn = ctx["pkg-5414797739ba4589"]["snapshots"]
    assert len(sn) == 1 and sn[0]["trade_status"] == "closed"
